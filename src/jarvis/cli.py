"""Command-line entry point. Output is short markdown by default; pass --json for machine output."""

import argparse
import json
import os
import sqlite3
import sys
import urllib.error

from . import db, ideas, papers


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
    links = [tuple(p.split("=", 1)) if "=" in p else (p, "") for p in args.paper]
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
    cur = conn.execute("INSERT INTO notes (project_id, idea_id, body, created_at) VALUES (?, ?, ?, ?)",
                       (db.project_id(conn, args.project), args.idea, args.body, db.now()))
    conn.commit()
    emit(args, {"id": cur.lastrowid}, f"Added note {cur.lastrowid}.")


def cmd_papers_search(conn, args):
    emit(args, [{k: v for k, v in p.items() if k != "raw"}
                for p in papers.search(conn, args.query, args.source, args.limit)], paper_lines)


def cmd_papers_show(conn, args):
    p = papers.get(conn, args.id)
    emit(args, p, lambda p: "\n".join(x for x in [
        f"## {p['title']} ({p['year']})", p["authors"], p["url"],
        f"TLDR: {p['tldr']}" if p["tldr"] else "", p["abstract"]] if x))


def cmd_event(conn, args):
    pid = db.project_id(conn, args.project) if args.project else None
    db.log_event(conn, args.kind, pid, **json.loads(args.data))
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
    p.add_argument("--body", default="")
    p.add_argument("--paper", action="append", default=[], metavar="ID[=WHY]",
                   help="cached paper id that supports the idea (repeatable)")
    p = sub(g, "list", cmd_ideas_list, (common, proj))
    p.add_argument("--status", choices=ideas.STATUSES)
    p = sub(g, "show", cmd_ideas_show)
    p.add_argument("id", type=int)
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

    g = groups.add_parser("papers", help="literature search").add_subparsers(required=True)
    p = sub(g, "search", cmd_papers_search)
    p.add_argument("query")
    p.add_argument("--source", choices=list(papers.SOURCES), default="s2")
    p.add_argument("--limit", type=int, default=10)
    p = sub(g, "show", cmd_papers_show)
    p.add_argument("id")

    p = sub(groups, "event", cmd_event, help="log an evaluation event (e.g. dedup, ask_user)")
    p.add_argument("kind")
    p.add_argument("-p", "--project", default=os.environ.get("JARVIS_PROJECT"))
    p.add_argument("--data", default="{}", help="JSON payload")

    sub(groups, "stats", cmd_stats, (common, proj), help="evaluation metrics for a project")
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    conn = db.connect(args.db)
    try:
        args.fn(conn, args)
    except (LookupError, ValueError, sqlite3.IntegrityError, urllib.error.URLError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
