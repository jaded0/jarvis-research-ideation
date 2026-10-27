"""SQLite storage. One file, created on first use."""

import json
import os
import sqlite3
from datetime import datetime, timezone

SCHEMA = """
CREATE TABLE IF NOT EXISTS projects (
    id          INTEGER PRIMARY KEY,
    name        TEXT NOT NULL UNIQUE,
    description TEXT NOT NULL DEFAULT '',
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS ideas (
    id         INTEGER PRIMARY KEY,
    project_id INTEGER NOT NULL REFERENCES projects(id),
    title      TEXT NOT NULL,
    summary    TEXT NOT NULL DEFAULT '',
    body       TEXT NOT NULL DEFAULT '',
    embedding  BLOB,
    embed_model TEXT,
    status     TEXT NOT NULL DEFAULT 'proposed'
               CHECK (status IN ('proposed', 'approved', 'rejected', 'elaborating')),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE VIRTUAL TABLE IF NOT EXISTS ideas_fts USING fts5(
    title, summary, body, content='ideas', content_rowid='id'
);
CREATE TRIGGER IF NOT EXISTS ideas_ai AFTER INSERT ON ideas BEGIN
    INSERT INTO ideas_fts(rowid, title, summary, body) VALUES (new.id, new.title, new.summary, new.body);
END;
CREATE TRIGGER IF NOT EXISTS ideas_ad AFTER DELETE ON ideas BEGIN
    INSERT INTO ideas_fts(ideas_fts, rowid, title, summary, body) VALUES ('delete', old.id, old.title, old.summary, old.body);
END;
CREATE TRIGGER IF NOT EXISTS ideas_au AFTER UPDATE ON ideas BEGIN
    INSERT INTO ideas_fts(ideas_fts, rowid, title, summary, body) VALUES ('delete', old.id, old.title, old.summary, old.body);
    INSERT INTO ideas_fts(rowid, title, summary, body) VALUES (new.id, new.title, new.summary, new.body);
END;

-- Cache of paper metadata. id is '<source>:<native id>', e.g. 's2:abc123', 'arxiv:2408.06292'.
CREATE TABLE IF NOT EXISTS papers (
    id         TEXT PRIMARY KEY,
    source     TEXT NOT NULL,
    title      TEXT NOT NULL,
    year       INTEGER,
    authors    TEXT NOT NULL DEFAULT '',
    abstract   TEXT NOT NULL DEFAULT '',
    tldr       TEXT NOT NULL DEFAULT '',
    url        TEXT NOT NULL DEFAULT '',
    raw_json   TEXT NOT NULL DEFAULT '{}',
    fetched_at TEXT NOT NULL
);

-- Recent searches, so repeating a query doesn't hit the API again (see papers.SEARCH_TTL_DAYS).
CREATE TABLE IF NOT EXISTS searches (
    query     TEXT NOT NULL,
    source    TEXT NOT NULL,
    lim       INTEGER NOT NULL,
    paper_ids TEXT NOT NULL,
    ts        TEXT NOT NULL,
    PRIMARY KEY (query, source, lim)
);

CREATE TABLE IF NOT EXISTS idea_papers (
    idea_id  INTEGER NOT NULL REFERENCES ideas(id),
    paper_id TEXT NOT NULL REFERENCES papers(id),
    why      TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (idea_id, paper_id)
);

CREATE TABLE IF NOT EXISTS notes (
    id         INTEGER PRIMARY KEY,
    project_id INTEGER NOT NULL REFERENCES projects(id),
    idea_id    INTEGER REFERENCES ideas(id),
    body       TEXT NOT NULL,
    created_at TEXT NOT NULL
);

-- Append-only log used for evaluation; `jarvis stats` reads it. payload is a JSON object.
--   kind          logged by                  payload                                  read by
--   idea_added    ideas.add                  idea_id                                  -
--   idea_status   ideas.set_status           idea_id, old, new                        -
--   idea_edited   ideas.edit                 idea_id, fields                          -
--   dedup         CLI ideas add              verdict: flagged|unique, candidate, idea_id?, matches,
--                                            nearest_id, top_score, distinct_from, source  stats: duplicate_rate
--   ask_user      agent (`jarvis event`)     reason                                   stats: user_prompts
-- duplicate_rate is flagged / (flagged + unique) CLI add attempts, not ground-truth duplicates.
-- ask_user's payload is specified in skill/SKILL.md.
CREATE TABLE IF NOT EXISTS events (
    id         INTEGER PRIMARY KEY,
    ts         TEXT NOT NULL,
    kind       TEXT NOT NULL,
    project_id INTEGER REFERENCES projects(id),
    payload    TEXT NOT NULL DEFAULT '{}'
);
"""


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def default_path() -> str:
    return os.environ.get("JARVIS_DB", "jarvis.db")


def connect(path: str | None = None) -> sqlite3.Connection:
    conn = sqlite3.connect(path or default_path())
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA)
    columns = {r["name"] for r in conn.execute("PRAGMA table_info(ideas)")}
    for name, kind in (("embedding", "BLOB"), ("embed_model", "TEXT")):
        if name not in columns:
            conn.execute(f"ALTER TABLE ideas ADD COLUMN {name} {kind}")
    conn.commit()
    return conn


def log_event(conn: sqlite3.Connection, kind: str, project_id: int | None = None, /, **payload) -> None:
    """Append to the events log. Positional-only, so a payload may itself contain "kind" or "project_id"."""
    conn.execute(
        "INSERT INTO events (ts, kind, project_id, payload) VALUES (?, ?, ?, ?)",
        (now(), kind, project_id, json.dumps(payload)),
    )
    conn.commit()


def project_id(conn: sqlite3.Connection, name: str) -> int:
    row = conn.execute("SELECT id FROM projects WHERE name = ?", (name,)).fetchone()
    if row is None:
        raise LookupError(f"no project named {name!r}; create it with `jarvis project add`")
    return row["id"]
