import json
import os

import pytest

from jarvis import cli, db, embeddings, ideas, papers

REAL_EMBED = embeddings.embed

@pytest.fixture(autouse=True)
def no_embedding_network(monkeypatch):
    def unavailable(texts):
        raise ValueError("offline test")
    monkeypatch.setattr(embeddings, "embed", unavailable)


@pytest.fixture
def fake_embeddings(monkeypatch):
    def fake(texts):
        return [[float(word in text.lower()) for word in ("memory", "batch", "optimizer")] for text in texts]
    monkeypatch.setattr(embeddings, "embed", fake)
    return fake


@pytest.fixture
def conn(tmp_path):
    c = db.connect(str(tmp_path / "t.db"))
    c.execute("INSERT INTO projects (name, created_at) VALUES ('demo', ?)", (db.now(),))
    c.commit()
    yield c
    c.close()


def run(tmp_path, capsys, *argv):
    assert cli.main([*argv, "--db", str(tmp_path / "t.db")]) == 0
    return capsys.readouterr().out


def test_search_and_status_update_fts(conn):
    i = ideas.add(conn, 1, "Contrastive pretraining", "use contrastive loss on fast weights")
    ideas.add(conn, 1, "Bigger batch", "scale the batch size")
    assert [r["id"] for r in ideas.search(conn, 1, "contrastive")] == [i]
    ideas.set_status(conn, i, "approved")
    assert ideas.search(conn, 1, "contrastive")[0]["status"] == "approved"


def test_link_requires_cached_paper(conn):
    i = ideas.add(conn, 1, "t")
    with pytest.raises(LookupError):
        ideas.link_paper(conn, i, "s2:missing")


def test_export_includes_papers(conn):
    papers.cache(conn, papers.parse_s2({"paperId": "abc", "title": "A Paper", "year": 2024,
                                        "url": "https://x", "tldr": {"text": "short"}}))
    ideas.add(conn, 1, "Try it", "summary", papers=[("s2:abc", "motivates it")])
    md = ideas.export_markdown(conn, 1)
    assert "## 1. Try it" in md and "[A Paper](https://x) (2024): motivates it" in md


def test_parse_openalex_rebuilds_abstract():
    p = papers.parse_openalex({"id": "https://openalex.org/W1", "display_name": "T",
                               "abstract_inverted_index": {"world": [1], "hello": [0]}})
    assert p["id"] == "openalex:W1" and p["abstract"] == "hello world"


def test_parse_arxiv():
    xml = b"""<feed xmlns="http://www.w3.org/2005/Atom"><entry>
      <id>http://arxiv.org/abs/2408.06292v3</id><published>2024-08-12T00:00:00Z</published>
      <title>The AI
        Scientist</title><summary> abs </summary><author><name>Lu</name></author></entry></feed>"""
    [p] = papers.parse_arxiv(xml)
    assert p["id"] == "arxiv:2408.06292" and p["title"] == "The AI Scientist" and p["year"] == 2024


def test_cli_roundtrip(tmp_path, capsys):
    run(tmp_path, capsys, "project", "add", "demo", "--description", "test")
    assert "Added idea 1" in run(tmp_path, capsys, "ideas", "add", "-p", "demo", "--title", "First", "--summary", "s")
    assert cli.main(["ideas", "add", "-p", "demo", "--title", "First", "--db", str(tmp_path / "t.db")]) == 1
    capsys.readouterr()
    run(tmp_path, capsys, "event", "ask_user", "-p", "demo")
    stats = json.loads(run(tmp_path, capsys, "stats", "-p", "demo", "--json"))
    assert stats["duplicate_rate"] == 0.5 and stats["user_prompts"] == 1
    assert "[1] First" in run(tmp_path, capsys, "ideas", "list", "-p", "demo")


def test_pi_command_uses_persona_and_only_our_skill():
    args = cli.build_parser().parse_args(["chat", "-p", "x", "--", "--thinking", "low"])
    cmd = cli.pi_command(args)
    assert cmd[cmd.index("--append-system-prompt") + 1].endswith("persona.md")
    assert "--no-skills" in cmd and "edit" not in cmd[cmd.index("--tools") + 1]
    assert "--thinking" in cmd and "--" not in cmd
    assert "ask" in cmd[cmd.index("--tools") + 1].split(",")
    assert os.path.exists(cmd[cmd.index("--extension") + 1])
    assert cmd[-1] == "Begin the session."
    resumed = cli.pi_command(cli.build_parser().parse_args(["chat", "-p", "x", "--", "-c"]))
    assert resumed[-1] == "-c"


def test_s2_throttle_spaces_calls(tmp_path, monkeypatch):
    import time
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    t0 = time.time()
    papers._s2_throttle()
    papers._s2_throttle()
    assert time.time() - t0 >= papers.S2_MIN_INTERVAL


def test_repeated_search_uses_cache(conn, monkeypatch):
    calls = []

    def fake(query, limit):
        calls.append(query)
        return [papers.parse_s2({"paperId": "p1", "title": "T"})]

    monkeypatch.setitem(papers.SOURCES, "s2", fake)
    papers.search(conn, "Fast  Weights", "s2", 5)
    hit = papers.search(conn, "fast weights", "s2", 5)
    assert len(calls) == 1 and hit[0]["id"] == "s2:p1"
    papers.search(conn, "fast weights", "s2", 5, refresh=True)
    assert len(calls) == 2


def test_edit_replaces_fields_and_appends_elaboration(conn):
    i = ideas.add(conn, 1, "Old", "old summary", "First experiment: none yet.")
    ideas.edit(conn, i, title="New", append="Signal: loss drops.")
    idea = ideas.get(conn, i)
    assert idea["title"] == "New" and idea["summary"] == "old summary"
    assert idea["body"] == "First experiment: none yet.\n\nSignal: loss drops."
    assert [r["id"] for r in ideas.search(conn, 1, "signal")] == [i]  # FTS sees the edit
    with pytest.raises(ValueError):
        ideas.edit(conn, i)
    with pytest.raises(LookupError):
        ideas.edit(conn, 99, title="x")


def test_cli_edit(tmp_path, capsys):
    run(tmp_path, capsys, "project", "add", "demo")
    run(tmp_path, capsys, "ideas", "add", "-p", "demo", "--title", "T")
    assert "Updated idea 1" in run(tmp_path, capsys, "ideas", "edit", "1", "--append", "risk: none")
    assert "risk: none" in run(tmp_path, capsys, "ideas", "show", "1")


@pytest.mark.parametrize("query", ["meta-learning", "GPT-4 (ablation)", "what's next", '"unbalanced',
                                   "C++", "AND", "*", "a:b", "   "])
def test_search_treats_query_as_plain_keywords(conn, query):
    ideas.search(conn, 1, query)  # must not raise


def test_search_matches_any_keyword(conn):
    i = ideas.add(conn, 1, "Meta-learning the optimizer", "learned update rules")
    assert [r["id"] for r in ideas.search(conn, 1, "meta-learning hypernetworks")] == [i]


def test_arxiv_requires_every_word(monkeypatch):
    urls = []
    empty = b'<feed xmlns="http://www.w3.org/2005/Atom"/>'
    monkeypatch.setattr(papers, "_get", lambda url, *a, **k: urls.append(url) or empty)
    papers.search_arxiv('fast weights (attention "x', 5)
    assert "all%3Afast+AND+all%3Aweights+AND+all%3Aattention+AND+all%3Ax&" in urls[0]


def test_parse_arxiv_raises_on_error_entry_and_keeps_old_ids():
    err = b"""<feed xmlns="http://www.w3.org/2005/Atom"><entry><id>http://arxiv.org/api/errors#x</id>
      <title>Error</title><summary>Invalid query</summary></entry></feed>"""
    with pytest.raises(ValueError, match="Invalid query"):
        papers.parse_arxiv(err)
    old = b"""<feed xmlns="http://www.w3.org/2005/Atom"><entry><id>http://arxiv.org/abs/solv-int/9901001v1</id>
      <title>T</title></entry></feed>"""
    assert papers.parse_arxiv(old)[0]["id"] == "arxiv:solv-int/9901001"


def test_load_env_does_not_override(tmp_path, monkeypatch):
    f = tmp_path / ".env"
    f.write_text("# comment\nJARVIS_T1=from_file\nexport JARVIS_T2='quoted'\nJARVIS_T3=from_file\n")
    monkeypatch.setenv("JARVIS_T3", "already_set")
    for k in ("JARVIS_T1", "JARVIS_T2"):
        monkeypatch.delenv(k, raising=False)
    cli.load_env(str(f))
    assert (os.environ["JARVIS_T1"], os.environ["JARVIS_T2"], os.environ["JARVIS_T3"]) == ("from_file", "quoted", "already_set")


def test_s2_throttle_runs_before_every_retry(monkeypatch):
    import io
    import urllib.error
    calls, sleeps = [], []

    def fake_urlopen(req, timeout):
        calls.append("request")
        if calls.count("request") < 3:
            raise urllib.error.HTTPError(req.full_url, 429, "Too Many", {}, io.BytesIO())
        return io.BytesIO(b'{"data": []}')

    monkeypatch.setattr(papers.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(papers.time, "sleep", sleeps.append)
    monkeypatch.setattr(papers, "_s2_throttle", lambda: calls.append("throttle"))
    assert papers.search_s2("q", 1) == []
    assert calls == ["throttle", "request"] * 3 and sleeps == [3, 6]


@pytest.mark.parametrize("data", ["[1, 2]", '{"kind": "x", "project_id": 5}', "not json"])
def test_event_payloads(tmp_path, capsys, data):
    run(tmp_path, capsys, "project", "add", "demo")
    code = cli.main(["event", "ask_user", "-p", "demo", "--data", data, "--db", str(tmp_path / "t.db")])
    assert code == (0 if data.startswith("{") else 1)  # bad payloads are a one-line error, not a traceback


def test_expected_failures_are_one_line_errors(tmp_path, capsys):
    run(tmp_path, capsys, "project", "add", "demo")
    db_arg = ["--db", str(tmp_path / "t.db")]
    assert cli.main(["notes", "add", "x", "--idea", "99", "-p", "demo", *db_arg]) == 1
    assert "no idea with id 99" in capsys.readouterr().err
    assert cli.main(["ideas", "export", "-p", "demo", "-o", str(tmp_path / "nodir" / "x.md"), *db_arg]) == 1
    assert cli.main(["project", "list", "--db", str(tmp_path / "nodir" / "x.db")]) == 1


def test_paper_link_strips_spaces(tmp_path, capsys):
    run(tmp_path, capsys, "project", "add", "demo")
    conn = db.connect(str(tmp_path / "t.db"))
    papers.cache(conn, papers.parse_s2({"paperId": "abc", "title": "T"}))
    conn.commit()
    conn.close()
    run(tmp_path, capsys, "ideas", "add", "-p", "demo", "--title", "T", "--paper", "s2:abc = motivates")
    assert "s2:abc | T: motivates" in run(tmp_path, capsys, "ideas", "show", "1")


def test_every_skill_command_parses(monkeypatch):
    """SKILL.md is the agent's CLI reference; renaming a flag without updating it breaks the agent at runtime."""
    import re
    import shlex
    monkeypatch.setenv("JARVIS_PROJECT", "x")
    parser = cli.build_parser()
    skill = open(os.path.join(cli.HERE, "skill", "SKILL.md")).read()
    lines = [ln.split("#")[0].strip() for ln in skill.splitlines() if ln.startswith("jarvis ")]
    assert len(lines) > 10
    for line in lines:
        line = re.sub(r"\[([^\]]*)\]", lambda m: m.group(1).split("|")[0], line)  # [--x a|b] -> --x a
        line = re.sub(r"(\w+)\|[\w|]+", r"\1", line)                             # a|b|c -> a
        line = line.replace("ID", "1").replace("NAME", "x").replace("KIND", "dedup")
        parser.parse_args(shlex.split(line)[1:])  # SystemExit fails the test


def test_migrate_old_database(tmp_path):
    import sqlite3
    path = str(tmp_path / "old.db")
    c = sqlite3.connect(path)
    c.executescript(db.SCHEMA.replace("    embedding  BLOB,\n", "").replace("    embed_model TEXT,\n", ""))
    c.execute("INSERT INTO projects (name, created_at) VALUES ('old', ?)", (db.now(),))
    c.execute("INSERT INTO ideas (project_id, title, created_at, updated_at) VALUES (1, 'kept', ?, ?)",
              (db.now(), db.now()))
    c.commit()
    c.close()
    for _ in range(2):
        c = db.connect(path)
        row = c.execute("SELECT title, embedding, embed_model FROM ideas").fetchone()
        assert tuple(row) == ("kept", None, None)
        c.close()


def test_add_gates_all_neighbours_including_rejected(conn, tmp_path, capsys, fake_embeddings):
    ids = [ideas.add(conn, 1, f"Memory {i}", f"summary {i}") for i in range(7)]
    ideas.set_status(conn, ids[-1], "rejected")
    argv = ["ideas", "add", "-p", "demo", "--title", "Memory paraphrase", "--summary", "same mechanism",
            "--db", str(tmp_path / "t.db")]
    assert cli.main(argv) == 1
    output = capsys.readouterr().out
    assert "[7] (rejected, score 1.000) Memory 6: summary 6" in output
    assert "--distinct-from" in output
    assert cli.main([*argv, "--distinct-from", "1,2,3,4,5,6"]) == 1
    assert "Missing: 7" in capsys.readouterr().out
    assert cli.main([*argv, "--distinct-from", ",".join(map(str, ids))]) == 0
    capsys.readouterr()
    events = [json.loads(r[0]) for r in conn.execute("SELECT payload FROM events WHERE kind = 'dedup'")]
    assert [p["verdict"] for p in events] == ["flagged", "flagged", "unique"]
    assert events[-1]["distinct_from"] == ids and events[-1]["nearest_id"] == 1
    assert events[-1]["top_score"] == pytest.approx(1)
    stats = json.loads(run(tmp_path, capsys, "stats", "-p", "demo", "--json"))
    assert stats["duplicate_rate"] == pytest.approx(2 / 3)


def test_fallback_gates_and_never_stores_vector(conn, tmp_path, capsys):
    ideas.add(conn, 1, "Memory retrieval", "old summary")
    argv = ["ideas", "add", "-p", "demo", "--title", "Memory caching", "--db", str(tmp_path / "t.db")]
    assert cli.main(argv) == 1
    output = capsys.readouterr()
    assert "Embeddings unavailable" in output.err and "keyword match" in output.out
    assert cli.main([*argv, "--distinct-from", "1"]) == 0
    assert conn.execute("SELECT embedding FROM ideas WHERE id = 2").fetchone()[0] is None


def test_unembedded_ideas_still_gate(conn, tmp_path, capsys, fake_embeddings):
    ideas.add(conn, 1, "Memory retrieval", embedding=None)
    argv = ["ideas", "add", "-p", "demo", "--title", "Memory caching", "--db", str(tmp_path / "t.db")]
    assert cli.main(argv) == 1
    assert "keyword match" in capsys.readouterr().out


def test_backfill_batches_project_and_model(conn, tmp_path, capsys, monkeypatch):
    for i in range(103):
        ideas.add(conn, 1, f"Memory {i}", "summary", embedding=None)
    conn.execute("INSERT INTO projects (name, created_at) VALUES ('other', ?)", (db.now(),))
    conn.commit()
    ideas.add(conn, 2, "Batch", embedding=None)
    calls = []

    def fake(texts):
        calls.append(texts)
        return [[1., 0.] for _ in texts]

    monkeypatch.setattr(embeddings, "embed", fake)
    assert "Embedded 103" in run(tmp_path, capsys, "ideas", "embed", "-p", "demo")
    assert [len(c) for c in calls] == [100, 3]
    assert calls[0][0] == "Memory 0\nsummary"
    assert "Embedded 0" in run(tmp_path, capsys, "ideas", "embed", "-p", "demo")
    assert conn.execute("SELECT embedding FROM ideas WHERE project_id = 2").fetchone()[0] is None
    monkeypatch.setenv("JARVIS_EMBED_MODEL", "other-model")
    assert "Embedded 103" in run(tmp_path, capsys, "ideas", "embed", "-p", "demo")
    assert len(ideas.neighbours(conn, 1, [1., 0.])) == 5


def test_edit_reembeds_only_title_or_summary(conn, fake_embeddings, monkeypatch):
    i = ideas.add(conn, 1, "Memory", "retrieval")
    before = ideas.get(conn, i)["embedding"]
    calls = []

    def fake(texts):
        calls.extend(texts)
        return fake_embeddings(texts)

    monkeypatch.setattr(embeddings, "embed", fake)
    ideas.edit(conn, i, append="body only")
    ideas.edit(conn, i, title="Memory")
    assert not calls and ideas.get(conn, i)["embedding"] == before
    ideas.edit(conn, i, title="Batch")
    assert calls == ["Batch\nretrieval"] and ideas.get(conn, i)["embedding"] != before


def test_semantic_search_and_check(conn, tmp_path, capsys, fake_embeddings):
    i = ideas.add(conn, 1, "Memory", "retrieve facts")
    ideas.add(conn, 1, "Batch", "scale training")
    rows = json.loads(run(tmp_path, capsys, "ideas", "search", "memory", "-p", "demo", "--json"))
    assert rows[0]["id"] == i and rows[0]["score"] == pytest.approx(1)
    assert "score 1.000" in run(tmp_path, capsys, "ideas", "check", "--title", "Memory", "-p", "demo")
    assert len(ideas.list_(conn, 1)) == 2
    assert conn.execute("SELECT COUNT(*) FROM events WHERE kind = 'dedup'").fetchone()[0] == 0


def test_agent_cannot_forge_dedup(tmp_path, capsys):
    run(tmp_path, capsys, "project", "add", "demo")
    assert cli.main(["event", "dedup", "-p", "demo", "--data", '{"verdict":"unique"}',
                     "--db", str(tmp_path / "t.db")]) == 1
    assert "logged by" in capsys.readouterr().err


def test_model_and_project_isolation(conn, fake_embeddings, monkeypatch):
    ideas.add(conn, 1, "Memory", "current")
    conn.execute("INSERT INTO projects (name, created_at) VALUES ('other', ?)", (db.now(),))
    conn.commit()
    ideas.add(conn, 2, "Memory", "other project")
    assert [r["id"] for r in ideas.neighbours(conn, 1, [1, 0, 0])] == [1]
    monkeypatch.setenv("JARVIS_EMBED_MODEL", "new-model")
    assert ideas.neighbours(conn, 1, [1, 0, 0]) == []
    assert ideas.candidates(conn, 1, "memory", [1, 0, 0]) == [
        {"id": 1, "title": "Memory", "summary": "current", "status": "proposed", "score": None}]


def test_failed_edit_clears_stale_embedding(conn, fake_embeddings, monkeypatch, capsys):
    i = ideas.add(conn, 1, "Memory")

    def fail(texts):
        raise OSError("request failed")

    monkeypatch.setattr(embeddings, "embed", fail)
    ideas.edit(conn, i, summary="changed")
    idea = ideas.get(conn, i)
    assert idea["embedding"] is None and idea["embed_model"] is None
    assert "Embeddings unavailable" in capsys.readouterr().err


def test_stats_ignores_old_agent_verdicts(conn, tmp_path, capsys):
    db.log_event(conn, "dedup", 1, verdict="duplicate")
    db.log_event(conn, "dedup", 1, verdict="unique")
    stats = json.loads(run(tmp_path, capsys, "stats", "-p", "demo", "--json"))
    assert stats["duplicate_rate"] is None
    run(tmp_path, capsys, "ideas", "add", "-p", "demo", "--title", "First")
    stats = json.loads(run(tmp_path, capsys, "stats", "-p", "demo", "--json"))
    assert stats["duplicate_rate"] == 0


def test_missing_key_uses_keyword_fallback(conn, tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(embeddings, "embed", REAL_EMBED)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setattr(cli, "load_env", lambda: None)
    ideas.add(conn, 1, "Memory")
    output = run(tmp_path, capsys, "ideas", "search", "memory", "-p", "demo")
    assert "[1] Memory" in output
    assert cli.main(["ideas", "add", "-p", "demo", "--title", "Memory alternative",
                     "--db", str(tmp_path / "t.db")]) == 1
    output = capsys.readouterr()
    assert "OPENROUTER_API_KEY is not set" in output.err
    assert "keyword match" in output.out


@pytest.mark.parametrize("threshold", ["nan", "inf", "1.1"])
def test_invalid_threshold_cannot_bypass_gate(conn, tmp_path, capsys, threshold):
    assert cli.main(["ideas", "add", "-p", "demo", "--title", "Memory", "--threshold", threshold,
                     "--db", str(tmp_path / "t.db")]) == 1
    assert "--threshold must" in capsys.readouterr().err


def test_embedding_post_and_retry(monkeypatch):
    import io
    import urllib.error
    calls, sleeps = [], []

    def fake(req, timeout):
        calls.append(req)
        if len(calls) == 1:
            raise urllib.error.HTTPError(req.full_url, 429, "Too Many", {"Retry-After": "4"}, io.BytesIO())
        return io.BytesIO(b'{"data":[{"index":1,"embedding":[0,1]},{"index":0,"embedding":[1,0]}]}')

    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.setattr(embeddings.urllib.request, "urlopen", fake)
    monkeypatch.setattr(embeddings.time, "sleep", sleeps.append)
    monkeypatch.setattr(embeddings, "embed", REAL_EMBED)
    assert embeddings.embed(["a", "b"]) == [[1, 0], [0, 1]]
    assert sleeps == [4]
    req = calls[0]
    assert req.get_method() == "POST"
    assert req.get_header("Authorization") == "Bearer test-key"
    assert json.loads(req.data) == {"model": embeddings.model(), "input": ["a", "b"]}
