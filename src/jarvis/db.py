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

-- Append-only log used for evaluation (dedup verdicts, user prompts, status changes, ...).
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
    return conn


def log_event(conn: sqlite3.Connection, kind: str, project_id: int | None = None, **payload) -> None:
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
