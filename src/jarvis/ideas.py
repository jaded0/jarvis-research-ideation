"""Ideas: storage, semantic neighbours, keyword fallback, export."""

import sqlite3
import sys

from . import embeddings
from .db import log_event, now

STATUSES = ("proposed", "approved", "rejected", "elaborating")
DEDUP_THRESHOLD = 0.5


def vector(text: str):
    """Unavailable embeddings must be visible, never a silent pass."""
    try:
        return embeddings.embed([text])[0]
    except Exception as e:
        print(f"Embeddings unavailable ({e}); using keyword neighbours.", file=sys.stderr)
        return None


def text(title: str, summary: str) -> str:
    return title + "\n" + summary


def add(conn: sqlite3.Connection, project_id: int, title: str, summary: str = "", body: str = "",
        papers: list[tuple[str, str]] = (), embedding=..., embed_model: str | None = None) -> int:
    if embedding is ...:
        embedding = vector(text(title, summary))
    ts = now()
    cur = conn.execute(
        "INSERT INTO ideas (project_id, title, summary, body, created_at, updated_at, embedding, embed_model) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (project_id, title, summary, body, ts, ts, embeddings.pack(embedding) if embedding is not None else None,
         (embed_model or embeddings.model()) if embedding is not None else None),
    )
    idea_id = cur.lastrowid
    for paper_id, why in papers:
        link_paper(conn, idea_id, paper_id, why)
    conn.commit()
    log_event(conn, "idea_added", project_id, idea_id=idea_id)
    return idea_id


def link_paper(conn: sqlite3.Connection, idea_id: int, paper_id: str, why: str = "") -> None:
    if conn.execute("SELECT 1 FROM papers WHERE id = ?", (paper_id,)).fetchone() is None:
        raise LookupError(f"paper {paper_id!r} is not cached; find it with `jarvis papers search` first")
    conn.execute(
        "INSERT OR REPLACE INTO idea_papers (idea_id, paper_id, why) VALUES (?, ?, ?)",
        (idea_id, paper_id, why),
    )


def get(conn: sqlite3.Connection, idea_id: int) -> dict:
    row = conn.execute("SELECT * FROM ideas WHERE id = ?", (idea_id,)).fetchone()
    if row is None:
        raise LookupError(f"no idea with id {idea_id}")
    idea = dict(row)
    idea["papers"] = [dict(r) for r in conn.execute(
        "SELECT p.id, p.title, p.year, p.url, ip.why FROM idea_papers ip JOIN papers p ON p.id = ip.paper_id "
        "WHERE ip.idea_id = ?", (idea_id,))]
    idea["notes"] = [dict(r) for r in conn.execute(
        "SELECT id, body, created_at FROM notes WHERE idea_id = ? ORDER BY id", (idea_id,))]
    return idea


def list_(conn: sqlite3.Connection, project_id: int, status: str | None = None) -> list[dict]:
    sql, args = "SELECT id, title, summary, status FROM ideas WHERE project_id = ?", [project_id]
    if status:
        sql += " AND status = ?"
        args.append(status)
    return [dict(r) for r in conn.execute(sql + " ORDER BY id", args)]


def set_status(conn: sqlite3.Connection, idea_id: int, status: str) -> None:
    if status not in STATUSES:
        raise ValueError(f"status must be one of {STATUSES}")
    row = conn.execute("SELECT project_id, status FROM ideas WHERE id = ?", (idea_id,)).fetchone()
    if row is None:
        raise LookupError(f"no idea with id {idea_id}")
    conn.execute("UPDATE ideas SET status = ?, updated_at = ? WHERE id = ?", (status, now(), idea_id))
    conn.commit()
    log_event(conn, "idea_status", row["project_id"], idea_id=idea_id, old=row["status"], new=status)


def edit(conn: sqlite3.Connection, idea_id: int, title: str | None = None, summary: str | None = None,
         body: str | None = None, append: str | None = None) -> None:
    """Change an idea's fields. `body` replaces the description; `append` adds a paragraph to it (elaborations)."""
    row = conn.execute("SELECT project_id, title, summary, body FROM ideas WHERE id = ?", (idea_id,)).fetchone()
    if row is None:
        raise LookupError(f"no idea with id {idea_id}")
    fields = {"title": title, "summary": summary, "body": body}
    fields = {k: v for k, v in fields.items() if v is not None}
    if append:
        base = fields.get("body", row["body"])
        fields["body"] = f"{base}\n\n{append}" if base else append
    if not fields:
        raise ValueError("nothing to change: pass --title, --summary, --body or --append")
    changed = sorted(fields)
    if any(k in fields and fields[k] != row[k] for k in ("title", "summary")):
        v = vector(text(fields.get("title", row["title"]), fields.get("summary", row["summary"])))
        fields["embedding"] = embeddings.pack(v) if v is not None else None
        fields["embed_model"] = embeddings.model() if v is not None else None
    sets = ", ".join(f"{k} = ?" for k in fields)
    conn.execute(f"UPDATE ideas SET {sets}, updated_at = ? WHERE id = ?", (*fields.values(), now(), idea_id))
    conn.commit()
    log_event(conn, "idea_edited", row["project_id"], idea_id=idea_id, fields=changed)


def neighbours(conn: sqlite3.Connection, project_id: int, v, limit: int | None = 5) -> list[dict]:
    """Scan the whole project, including rejected ideas, using only the current model."""
    rows = []
    for r in conn.execute("SELECT id, title, summary, status, embedding FROM ideas "
                          "WHERE project_id = ? AND embedding IS NOT NULL AND embed_model = ?",
                          (project_id, embeddings.model())):
        idea = {k: r[k] for k in ("id", "title", "summary", "status")}
        idea["score"] = embeddings.cosine(v, embeddings.unpack(r["embedding"]))
        rows.append(idea)
    rows.sort(key=lambda r: (-r["score"], r["id"]))
    return rows[:limit] if limit is not None else rows


def candidates(conn: sqlite3.Connection, project_id: int, query: str, v) -> list[dict]:
    """Semantic neighbours plus keyword matches for ideas not yet embedded."""
    rows = neighbours(conn, project_id, v, limit=None) if v is not None else []
    scored = {r["id"] for r in rows}
    for r in search(conn, project_id, query, limit=-1):
        if r["id"] not in scored:
            rows.append({**r, "score": None})
    return rows


def flagged(rows: list[dict], threshold: float = DEDUP_THRESHOLD) -> list[dict]:
    return [r for r in rows if r["score"] is None or r["score"] >= threshold]


def backfill(conn: sqlite3.Connection, project_id: int) -> int:
    rows = conn.execute("SELECT id, title, summary FROM ideas WHERE project_id = ? "
                        "AND (embedding IS NULL OR embed_model IS NULL OR embed_model != ?)",
                        (project_id, embeddings.model())).fetchall()
    for start in range(0, len(rows), 100):
        batch = rows[start:start + 100]
        vectors = embeddings.embed([text(r["title"], r["summary"]) for r in batch])
        for r, v in zip(batch, vectors):
            conn.execute("UPDATE ideas SET embedding = ?, embed_model = ? WHERE id = ?",
                         (embeddings.pack(v), embeddings.model(), r["id"]))
    conn.commit()
    return len(rows)


def fts_query(query: str) -> str:
    """Plain keywords -> an FTS5 query: each word quoted (so '-', ':', quotes, AND etc. are literal), any may match."""
    return " OR ".join('"' + w.replace('"', '""') + '"' for w in query.split())


def search(conn: sqlite3.Connection, project_id: int, query: str, limit: int = 10) -> list[dict]:
    """Keyword search over title, summary and body. Any word may match; best matches (bm25) first."""
    if not query.split():
        return []
    return [dict(r) for r in conn.execute(
        "SELECT i.id, i.title, i.summary, i.status FROM ideas_fts f JOIN ideas i ON i.id = f.rowid "
        "WHERE ideas_fts MATCH ? AND i.project_id = ? ORDER BY rank LIMIT ?",
        (fts_query(query), project_id, limit))]


def export_markdown(conn: sqlite3.Connection, project_id: int, status: str | None = None) -> str:
    project = conn.execute("SELECT name, description FROM projects WHERE id = ?", (project_id,)).fetchone()
    lines = [f"# {project['name']}: ideas", ""]
    if project["description"]:
        lines += [project["description"], ""]
    for row in list_(conn, project_id, status):
        idea = get(conn, row["id"])
        lines += [f"## {idea['id']}. {idea['title']}", "", f"*Status: {idea['status']}*", ""]
        if idea["summary"]:
            lines += [idea["summary"], ""]
        if idea["body"]:
            lines += [idea["body"], ""]
        if idea["papers"]:
            lines.append("**Papers**")
            for p in idea["papers"]:
                why = f": {p['why']}" if p["why"] else ""
                lines.append(f"- [{p['title']}]({p['url']}) ({p['year']}){why}")
            lines.append("")
        if idea["notes"]:
            lines.append("**Notes**")
            lines += [f"- {n['body']}" for n in idea["notes"]]
            lines.append("")
    return "\n".join(lines)
