import json

import pytest

from jarvis import cli, db, ideas, papers


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


def test_sample_is_bounded_and_logged(conn):
    for i in range(100):
        ideas.add(conn, 1, f"idea {i}", "x" * 100)
    assert len(ideas.sample(conn, 1, n=40, seed=0)) == 40
    assert len(ideas.sample(conn, 1, n=40, max_chars=1000, seed=0)) < 40
    payload = json.loads(conn.execute(
        "SELECT payload FROM events WHERE kind = 'dedup_sample' ORDER BY id DESC").fetchone()[0])
    assert payload["pool"] == 100


def test_sample_small_pool_returns_everything(conn):
    for i in range(3):
        ideas.add(conn, 1, f"idea {i}")
    assert len(ideas.sample(conn, 1, n=40)) == 3


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
    run(tmp_path, capsys, "event", "dedup", "-p", "demo", "--data", '{"verdict": "duplicate"}')
    run(tmp_path, capsys, "event", "ask_user", "-p", "demo")
    stats = json.loads(run(tmp_path, capsys, "stats", "-p", "demo", "--json"))
    assert stats["duplicate_rate"] == 1.0 and stats["user_prompts"] == 1
    assert "[1] First" in run(tmp_path, capsys, "ideas", "list", "-p", "demo")


def test_pi_command_uses_persona_and_only_our_skill():
    args = cli.build_parser().parse_args(["chat", "-p", "x", "--", "--thinking", "low"])
    cmd = cli.pi_command(args)
    assert cmd[cmd.index("--append-system-prompt") + 1].endswith("persona.md")
    assert "--no-skills" in cmd and "edit" not in cmd[cmd.index("--tools") + 1]
    assert "--thinking" in cmd and "--" not in cmd


def test_s2_throttle_spaces_calls(tmp_path, monkeypatch):
    import time
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    t0 = time.time()
    papers._s2_throttle()
    papers._s2_throttle()
    assert time.time() - t0 >= papers.S2_MIN_INTERVAL
