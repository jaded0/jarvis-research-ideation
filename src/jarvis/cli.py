"""Command-line entry point. Output is short markdown by default; pass --json for machine output."""

import argparse
import http.client
import json
import math
import os
import shutil
import sqlite3
import sys

from . import db, ideas, papers, ranking

HERE = os.path.dirname(os.path.abspath(__file__))
ENV_FILE = os.path.join(HERE, "..", "..", ".env")  # repo-root .env (API keys), when run from a checkout
DEFAULT_MODELS = "openrouter/anthropic/claude-haiku-5.5,openrouter/openai/gpt-5.6-luna"


def emit(args, data, md) -> None:
    """Print `data` as JSON with --json, else as markdown. `md` is a string or a function of `data`."""
    if args.json:
        print(json.dumps(data, indent=2, default=str))
    else:
        print(md(data) if callable(md) else md)


def clip(text: str, n: int) -> str:
    text = " ".join(text.split())
    return text if len(text) <= n else text[: n - 1] + "…"


def idea_lines(rows, ranked: bool = False) -> str:
    if not rows:
        return "(no ideas)"
    return "\n".join(
        f"- [{r['id']}] {r['title']}" + (f" ({r['status']})" if "status" in r else "")
        + (f" — Elo {r['elo']:.0f}, {r['comparisons']} comparisons" if ranked else "")
        + (f": {clip(r['summary'], 200)}" if r.get("summary") else "")
        for r in rows)


def paper_lines(rows) -> str:
    if not rows:
        return "(no results)"
    return "\n".join(
        f"- {p['id']} | {p['title']} ({p['year']}): {clip(p['tldr'] or p['abstract'], 300)}" for p in rows)


# --- handlers -----------------------------------------------------------------

def cmd_project_add(conn, args):
    cur = conn.execute("INSERT INTO projects (name, description, created_at) VALUES (?, ?, ?)",
                       (args.name, args.description, db.now()))
    conn.commit()
    emit(args, {"id": cur.lastrowid, "name": args.name}, f"Created project {args.name!r}.")


def cmd_project_list(conn, args):
    rows = [dict(r) for r in conn.execute("SELECT id, name, description FROM projects ORDER BY id")]
    emit(args, rows, lambda rs: "\n".join(f"- {r['name']}: {clip(r['description'], 200)}" for r in rs)
         or "(no projects)")


def cmd_ideas_add(conn, args):
    pid = db.project_id(conn, args.project)
    if not math.isfinite(args.threshold) or not -1 <= args.threshold <= 1:
        raise ValueError("--threshold must be between -1 and 1")
    distinct = sorted({int(x) for x in args.distinct_from.split(",") if x.strip()})
    query = ideas.text(args.title, args.summary)
    v = ideas.vector(query)
    rows = ideas.candidates(conn, pid, query, v)
    matches = ideas.flagged(rows, args.threshold)
    missing = {r["id"] for r in matches} - set(distinct)
    payload = dict(candidate=args.title, matches=[r["id"] for r in matches],
                   nearest_id=rows[0]["id"] if rows else None,
                   top_score=rows[0]["score"] if rows else None, distinct_from=distinct,
                   source="embedding" if v is not None else "keyword")
    if missing:
        db.log_event(conn, "dedup", pid, verdict="flagged", **payload)
        message = "Not added. Read the neighbours, then drop the idea or re-run with --distinct-from ID[,ID...] "
        message += "naming every flagged neighbour judged different. Missing: " + ",".join(map(str, sorted(missing)))
        emit(args, {"error": message, "neighbours": matches}, message + "\n" + neighbour_lines(matches))
        return 1
    links = [tuple(x.strip() for x in p.split("=", 1)) if "=" in p else (p.strip(), "") for p in args.paper]
    idea_id = ideas.add(conn, pid, args.title, args.summary, args.body, links, embedding=v)
    db.log_event(conn, "dedup", pid, verdict="unique", idea_id=idea_id, **payload)
    ranking.on_add(conn, pid, idea_id)
    emit(args, {"id": idea_id}, f"Added idea {idea_id}.")


def neighbour_lines(rows) -> str:
    return "\n".join(f"- [{r['id']}] ({r['status']}, "
                     + (f"score {r['score']:.3f}" if r["score"] is not None else "keyword match")
                     + f") {r['title']}: {r['summary']}" for r in rows) or "(no neighbours)"


def cmd_ideas_check(conn, args):
    query = ideas.text(args.title, args.summary)
    rows = ideas.candidates(conn, db.project_id(conn, args.project), query, ideas.vector(query))
    matches = ideas.flagged(rows)
    shown = rows[:5] + [r for r in matches if r not in rows[:5]]
    emit(args, shown, neighbour_lines)


def cmd_ideas_embed(conn, args):
    n = ideas.backfill(conn, db.project_id(conn, args.project))
    emit(args, {"embedded": n}, f"Embedded {n} ideas.")


def cmd_ideas_list(conn, args):
    rows = ideas.list_(conn, db.project_id(conn, args.project), args.status, args.ranked)
    emit(args, rows, lambda rs: idea_lines(rs, args.ranked))


def cmd_ideas_prefer(conn, args):
    comparison = ranking.record(conn, args.winner_id, args.loser_id, reason=args.why)
    emit(args, {"id": comparison, "winner_id": args.winner_id, "loser_id": args.loser_id},
         f"Recorded preference for idea {args.winner_id} over {args.loser_id}.")


def cmd_ideas_rank(conn, args):
    if args.rounds < 1:
        raise ValueError("--rounds must be at least 1")
    pid = db.project_id(conn, args.project)
    n = conn.execute("SELECT COUNT(*) FROM ideas WHERE project_id = ? AND status != 'rejected'", (pid,)).fetchone()[0]
    calls = (n // 2) * args.rounds
    print(f"Ranking: {calls} judge calls ({args.rounds} rounds).", file=sys.stderr, flush=True)
    completed = ranking.rank(conn, pid, args.rounds)
    emit(args, {"calls": calls, "comparisons": completed}, f"Recorded {completed} comparisons.")


def cmd_ideas_show(conn, args):
    idea = ideas.get(conn, args.id)

    def md(i):
        out = [f"## [{i['id']}] {i['title']} ({i['status']})", i["summary"], i["body"]]
        out += [f"- paper {p['id']} | {p['title']}" + (f": {p['why']}" if p["why"] else "") for p in i["papers"]]
        out += [f"- note: {n['body']}" for n in i["notes"]]
        return "\n".join(x for x in out if x)

    emit(args, idea, md)


def cmd_ideas_edit(conn, args):
    ideas.edit(conn, args.id, args.title, args.summary, args.body, args.append)
    emit(args, {"id": args.id}, f"Updated idea {args.id}.")


def cmd_ideas_status(conn, args):
    ideas.set_status(conn, args.id, args.status)
    emit(args, {"id": args.id, "status": args.status}, f"Idea {args.id} is now {args.status}.")


def cmd_ideas_search(conn, args):
    pid = db.project_id(conn, args.project)
    v = ideas.vector(args.query)
    rows = ideas.neighbours(conn, pid, v, args.limit) if v is not None else []
    if not rows:
        rows = ideas.search(conn, pid, args.query, args.limit)
    emit(args, rows, idea_lines)


def cmd_ideas_link(conn, args):
    ideas.link_paper(conn, args.id, args.paper, args.why)
    conn.commit()
    emit(args, {"id": args.id, "paper": args.paper}, f"Linked {args.paper} to idea {args.id}.")


def cmd_ideas_export(conn, args):
    md = ideas.export_markdown(conn, db.project_id(conn, args.project), args.status)
    if args.out:
        with open(args.out, "w") as f:
            f.write(md)
        print(f"Wrote {args.out}.")
    else:
        print(md)


def cmd_notes_add(conn, args):
    if args.idea is not None:
        ideas.get(conn, args.idea)  # raises "no idea with id N" instead of a foreign-key error
    cur = conn.execute("INSERT INTO notes (project_id, idea_id, body, created_at) VALUES (?, ?, ?, ?)",
                       (db.project_id(conn, args.project), args.idea, args.body, db.now()))
    conn.commit()
    emit(args, {"id": cur.lastrowid}, f"Added note {cur.lastrowid}.")


def cmd_notes_list(conn, args):
    rows = [dict(r) for r in conn.execute(
        "SELECT id, idea_id, body, created_at FROM notes WHERE project_id = ? ORDER BY id",
        (db.project_id(conn, args.project),))]
    emit(args, rows, lambda rs: "\n".join(
        f"- [{r['id']}]" + (f" (idea {r['idea_id']})" if r["idea_id"] else "") + f" {r['body']}" for r in rs)
         or "(no notes)")


def cmd_papers_search(conn, args):
    # Fresh results carry the raw API response under "raw"; it's stored, never shown.
    emit(args, [{k: v for k, v in p.items() if k != "raw"}
                for p in papers.search(conn, args.query, args.source, args.limit, args.refresh)], paper_lines)


def cmd_papers_show(conn, args):
    p = papers.get(conn, args.id)
    emit(args, p, lambda p: "\n".join(x for x in [
        f"## {p['title']} ({p['year']})", p["authors"], p["url"],
        f"TLDR: {p['tldr']}" if p["tldr"] else "", p["abstract"]] if x))


def cmd_event(conn, args):
    if args.kind == "dedup":
        raise ValueError("dedup events are logged by `jarvis ideas add`, not `jarvis event`")
    pid = db.project_id(conn, args.project) if args.project else None
    try:
        data = json.loads(args.data)
    except json.JSONDecodeError as e:
        raise ValueError(f"--data is not valid JSON: {e}") from None
    if not isinstance(data, dict):
        raise ValueError('--data must be a JSON object, e.g. \'{"verdict": "unique"}\'')
    db.log_event(conn, args.kind, pid, **data)
    emit(args, {"kind": args.kind}, f"Logged {args.kind}.")


def cmd_stats(conn, args):
    """Evaluation metrics, from the ideas table and the events log (event kinds are listed in db.py).

    value        approved_rate: approved / all ideas, proposed ones included. Higher is better.
    variety      duplicate_rate: share of CLI add attempts refused (flagged / (flagged + unique)).
                 Retries count as attempts. Lower is better; similarity flags are not ground truth.
    persistence  user_prompts: how many times the agent logged asking the user. Lower is better.
    """
    pid = db.project_id(conn, args.project)
    counts = dict(conn.execute(
        "SELECT status, COUNT(*) FROM ideas WHERE project_id = ? GROUP BY status", (pid,)).fetchall())
    events = dict(conn.execute(
        "SELECT kind, COUNT(*) FROM events WHERE project_id = ? GROUP BY kind", (pid,)).fetchall())
    verdicts = [p["verdict"] for r in conn.execute(
        "SELECT payload FROM events WHERE project_id = ? AND kind = 'dedup'", (pid,))
        if (p := json.loads(r[0])).get("source") in ("embedding", "keyword")
        and p.get("verdict") in ("flagged", "unique")]
    total = sum(counts.values())
    stats = {
        "ideas": counts,
        # value: share of ideas the user approved
        "approved_rate": counts.get("approved", 0) / total if total else None,
        # variety: share of dedup checks that flagged a duplicate
        "duplicate_rate": verdicts.count("flagged") / len(verdicts) if verdicts else None,
        # persistence: how often the agent had to prompt the user
        "user_prompts": events.get("ask_user", 0),
        "events": events,
    }
    emit(args, stats, lambda s: "\n".join(f"- {k}: {v}" for k, v in s.items()))


# --- chat: hand the terminal over to pi ---------------------------------------

def pi_command(args) -> list[str]:
    models = os.environ.get("JARVIS_MODELS", DEFAULT_MODELS)
    extra = [a for a in args.pi_args if a != "--"]
    resuming = any(a in ("-c", "--continue", "-r", "--resume", "--session") for a in extra)  # no opener mid-conversation
    return [
        "pi",
        "--model", models.split(",")[0],
        "--models", models,  # Ctrl+P cycles through these
        "--append-system-prompt", os.path.join(HERE, "persona.md"),
        "--no-skills", "--skill", os.path.join(HERE, "skill"),  # only our skill, to keep context small
        "--extension", os.path.join(HERE, "ask.ts"),  # the `ask` tool: answer menus as cards, not typed codes
        "--extension", os.path.join(HERE, "ideas_pane.ts"),
        "--tools", "read,bash,grep,find,ls,ask",  # no edit/write: JARVIS suggests, it doesn't change files
        *extra,
        *([] if resuming else ["Begin the session."]),
    ]


def cmd_chat(conn, args):
    """Launch pi as J.A.R.V.I.S. in the current directory (the researcher's project)."""
    if conn.execute("SELECT 1 FROM projects WHERE name = ?", (args.project,)).fetchone() is None:
        conn.execute("INSERT INTO projects (name, created_at) VALUES (?, ?)", (args.project, db.now()))
        conn.commit()
    conn.close()
    if shutil.which("pi") is None:
        raise LookupError("pi is not installed: npm i -g @earendil-works/pi-coding-agent")
    env = dict(os.environ, JARVIS_PROJECT=args.project, JARVIS_DB=os.path.abspath(args.db or db.default_path()))
    # Put this interpreter's bin dir first so the agent can call `jarvis` directly.
    env["PATH"] = os.path.dirname(sys.executable) + os.pathsep + env.get("PATH", "")
    os.execvpe("pi", pi_command(args), env)


# --- parser -------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--json", action="store_true", help="machine-readable output")
    common.add_argument("--db", default=None, help="database path (default: $JARVIS_DB or ./jarvis.db)")

    # -p is required only if $JARVIS_PROJECT is unset (decided when the parser is built). `event` and
    # `chat` define their own optional -p; chat falls back to the current directory's name.
    proj = argparse.ArgumentParser(add_help=False)
    proj.add_argument("-p", "--project", default=os.environ.get("JARVIS_PROJECT"),
                      required="JARVIS_PROJECT" not in os.environ, help="project name (default: $JARVIS_PROJECT)")

    parser = argparse.ArgumentParser(prog="jarvis", description=__doc__)
    groups = parser.add_subparsers(dest="group", required=True)

    def sub(group, name, fn, parents=(common,), **kw):
        p = group.add_parser(name, parents=list(parents), **kw)
        p.set_defaults(fn=fn)  # main() calls args.fn(conn, args): this is how a command reaches its handler
        return p

    g = groups.add_parser("project", help="manage projects").add_subparsers(required=True)
    p = sub(g, "add", cmd_project_add)
    p.add_argument("name")
    p.add_argument("--description", default="")
    sub(g, "list", cmd_project_list)

    g = groups.add_parser("ideas", help="manage the idea pool").add_subparsers(required=True)
    p = sub(g, "add", cmd_ideas_add, (common, proj))
    p.add_argument("--title", required=True)
    p.add_argument("--summary", default="", help="one or two sentences; this is what dedup sees")
    p.add_argument("--body", default="", help="longer description")
    p.add_argument("--distinct-from", default="", metavar="ID[,ID...]", help="neighbours judged different")
    p.add_argument("--threshold", type=float, default=ideas.DEDUP_THRESHOLD, help="cosine gate (default: 0.5)")
    p.add_argument("--paper", action="append", default=[], metavar="ID[=WHY]",
                   help="cached paper id that supports the idea (repeatable)")
    p = sub(g, "list", cmd_ideas_list, (common, proj))
    p.add_argument("--status", choices=ideas.STATUSES)
    p.add_argument("--ranked", action="store_true", help="status tier, then Elo; no judge calls")
    p = sub(g, "prefer", cmd_ideas_prefer, help="record a researcher preference; no judge call")
    p.add_argument("winner_id", type=int)
    p.add_argument("loser_id", type=int)
    p.add_argument("--why", default="")
    p = sub(g, "rank", cmd_ideas_rank, (common, proj), help="on-demand Swiss rounds of model judgments")
    p.add_argument("--rounds", type=int, default=1)
    p = sub(g, "show", cmd_ideas_show)
    p.add_argument("id", type=int)
    p = sub(g, "edit", cmd_ideas_edit, help="change an idea; --append adds an elaboration to its description")
    p.add_argument("id", type=int)
    p.add_argument("--title")
    p.add_argument("--summary")
    p.add_argument("--body", help="replace the description")
    p.add_argument("--append", help="add a paragraph to the description")
    p = sub(g, "status", cmd_ideas_status)
    p.add_argument("id", type=int)
    p.add_argument("status", choices=ideas.STATUSES)
    p = sub(g, "check", cmd_ideas_check, (common, proj), help="screen without adding")
    p.add_argument("--title", required=True)
    p.add_argument("--summary", default="")
    sub(g, "embed", cmd_ideas_embed, (common, proj), help="backfill embeddings for this project")
    p = sub(g, "search", cmd_ideas_search, (common, proj), help="semantic search, keyword fallback")
    p.add_argument("query")
    p.add_argument("--limit", type=int, default=10)
    p = sub(g, "link", cmd_ideas_link)
    p.add_argument("id", type=int)
    p.add_argument("paper")
    p.add_argument("--why", default="")
    p = sub(g, "export", cmd_ideas_export, (common, proj), help="write ideas as markdown")
    p.add_argument("--status", choices=ideas.STATUSES)
    p.add_argument("-o", "--out")

    g = groups.add_parser("notes", help="free-form notes").add_subparsers(required=True)
    p = sub(g, "add", cmd_notes_add, (common, proj))
    p.add_argument("body")
    p.add_argument("--idea", type=int)
    sub(g, "list", cmd_notes_list, (common, proj))

    g = groups.add_parser("papers", help="literature search").add_subparsers(required=True)
    p = sub(g, "search", cmd_papers_search)
    p.add_argument("query")
    p.add_argument("--source", choices=list(papers.SOURCES), default="openalex")
    p.add_argument("--limit", type=int, default=10)
    p.add_argument("--refresh", action="store_true", help="ignore a cached identical search")
    p = sub(g, "show", cmd_papers_show)
    p.add_argument("id")

    p = sub(groups, "event", cmd_event, help="log an evaluation event (e.g. ask_user)")
    p.add_argument("kind")
    p.add_argument("-p", "--project", default=os.environ.get("JARVIS_PROJECT"))
    p.add_argument("--data", default="{}", help="JSON payload")

    p = sub(groups, "chat", cmd_chat, help="talk to J.A.R.V.I.S. (launches pi) in the current directory")
    p.add_argument("-p", "--project",
                   default=os.environ.get("JARVIS_PROJECT") or os.path.basename(os.getcwd()),
                   help="project name (default: $JARVIS_PROJECT, else the current directory's name)")
    p.add_argument("pi_args", nargs=argparse.REMAINDER, help="extra pi flags, after --")

    sub(groups, "stats", cmd_stats, (common, proj), help="evaluation metrics for a project")
    return parser


def load_env(path: str = ENV_FILE) -> None:
    """Read KEY=VALUE lines from .env into os.environ, without overriding variables already set."""
    if not os.path.exists(path):
        return
    for line in open(path):
        key, sep, value = line.strip().removeprefix("export ").partition("=")
        if sep and key and not key.startswith("#"):
            os.environ.setdefault(key.strip(), value.strip().strip("\"'"))


def main(argv=None) -> int:
    load_env()
    args = build_parser().parse_args(argv)
    try:
        conn = db.connect(args.db)
    except (sqlite3.OperationalError, OSError) as e:
        print(f"error: can't open database {args.db or db.default_path()!r}: {e}", file=sys.stderr)
        return 1
    try:
        return args.fn(conn, args) or 0
    # Expected failures print one line. OSError covers network errors and timeouts (URLError is one) and bad paths.
    except (LookupError, ValueError, sqlite3.IntegrityError, sqlite3.OperationalError, OSError,
            http.client.HTTPException) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
