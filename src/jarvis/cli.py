"""Command-line entry point. Output is short markdown by default; pass --json for machine output."""

import argparse
import http.client
import json
import os
import shutil
import sqlite3
import sys

from . import db, ideas, papers

HERE = os.path.dirname(os.path.abspath(__file__))
ENV_FILE = os.path.join(HERE, "..", "..", ".env")  # repo-root .env (API keys), when run from a checkout
DEFAULT_MODELS = "openrouter/anthropic/claude-haiku-5.5,openrouter/openai/gpt-5.6-luna"


def emit(args, data, md) -> None:
    if args.json:
        print(json.dumps(data, indent=2, default=str))
    else:
        print(md(data) if callable(md) else md)


def clip(text: str, n: int) -> str:
    text = " ".join(text.split())
    return text if len(text) <= n else text[: n - 1] + "…"


def idea_lines(rows) -> str:
    if not rows:
        return "(no ideas)"
    return "\n".join(
        f"- [{r['id']}] {r['title']}" + (f" ({r['status']})" if "status" in r else "")
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
    links = [tuple(x.strip() for x in p.split("=", 1)) if "=" in p else (p.strip(), "") for p in args.paper]
    idea_id = ideas.add(conn, db.project_id(conn, args.project), args.title, args.summary, args.body, links)
    emit(args, {"id": idea_id}, f"Added idea {idea_id}.")


def cmd_ideas_list(conn, args):
    emit(args, ideas.list_(conn, db.project_id(conn, args.project), args.status), idea_lines)


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


def cmd_ideas_sample(conn, args):
    rows = ideas.sample(conn, db.project_id(conn, args.project), args.n, args.max_chars, args.seed)
    emit(args, rows, idea_lines)


def cmd_ideas_search(conn, args):
    emit(args, ideas.search(conn, db.project_id(conn, args.project), args.query, args.limit), idea_lines)


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
    emit(args, [{k: v for k, v in p.items() if k != "raw"}
                for p in papers.search(conn, args.query, args.source, args.limit, args.refresh)], paper_lines)


def cmd_papers_show(conn, args):
    p = papers.get(conn, args.id)
    emit(args, p, lambda p: "\n".join(x for x in [
        f"## {p['title']} ({p['year']})", p["authors"], p["url"],
        f"TLDR: {p['tldr']}" if p["tldr"] else "", p["abstract"]] if x))


def cmd_event(conn, args):
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
    pid = db.project_id(conn, args.project)
    counts = dict(conn.execute(
        "SELECT status, COUNT(*) FROM ideas WHERE project_id = ? GROUP BY status", (pid,)).fetchall())
    events = dict(conn.execute(
        "SELECT kind, COUNT(*) FROM events WHERE project_id = ? GROUP BY kind", (pid,)).fetchall())
    verdicts = [json.loads(r[0]).get("verdict") for r in conn.execute(
        "SELECT payload FROM events WHERE project_id = ? AND kind = 'dedup'", (pid,))]
    total = sum(counts.values())
    stats = {
        "ideas": counts,
        # value: share of ideas the user approved
        "approved_rate": counts.get("approved", 0) / total if total else None,
        # variety: share of dedup checks that flagged a duplicate
        "duplicate_rate": verdicts.count("duplicate") / len(verdicts) if verdicts else None,
        # persistence: how often the agent had to prompt the user
        "user_prompts": events.get("ask_user", 0),
        "events": events,
    }
    emit(args, stats, lambda s: "\n".join(f"- {k}: {v}" for k, v in s.items()))


def pi_command(args) -> list[str]:
    models = os.environ.get("JARVIS_MODELS", DEFAULT_MODELS)
    return [
        "pi",
        "--model", models.split(",")[0],
        "--models", models,  # Ctrl+P cycles through these
        "--append-system-prompt", os.path.join(HERE, "persona.md"),
        "--no-skills", "--skill", os.path.join(HERE, "skill"),  # only our skill, to keep context small
        "--tools", "read,bash,grep,find,ls",  # no edit/write: JARVIS suggests, it doesn't change files
        *[a for a in args.pi_args if a != "--"],
        "Begin the session.",
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

    proj = argparse.ArgumentParser(add_help=False)
    proj.add_argument("-p", "--project", default=os.environ.get("JARVIS_PROJECT"),
                      required="JARVIS_PROJECT" not in os.environ, help="project name (default: $JARVIS_PROJECT)")

    parser = argparse.ArgumentParser(prog="jarvis", description=__doc__)
    groups = parser.add_subparsers(dest="group", required=True)

    def sub(group, name, fn, parents=(common,), **kw):
        p = group.add_parser(name, parents=list(parents), **kw)
        p.set_defaults(fn=fn)
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
    p.add_argument("--paper", action="append", default=[], metavar="ID[=WHY]",
                   help="cached paper id that supports the idea (repeatable)")
    p = sub(g, "list", cmd_ideas_list, (common, proj))
    p.add_argument("--status", choices=ideas.STATUSES)
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
    p = sub(g, "sample", cmd_ideas_sample, (common, proj), help="random sample of the pool for dedup")
    p.add_argument("-n", type=int, default=40)
    p.add_argument("--max-chars", type=int, default=12000)
    p.add_argument("--seed", type=int)
    p = sub(g, "search", cmd_ideas_search, (common, proj), help="keyword search (SQLite FTS5)")
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

    p = sub(groups, "event", cmd_event, help="log an evaluation event (e.g. dedup, ask_user)")
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
        args.fn(conn, args)
    # Expected failures print one line. OSError covers network errors and timeouts (URLError is one) and bad paths.
    except (LookupError, ValueError, sqlite3.IntegrityError, sqlite3.OperationalError, OSError,
            http.client.HTTPException) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
