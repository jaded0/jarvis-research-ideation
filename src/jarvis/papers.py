"""Literature search. Each source returns the same flat dict shape and results are cached.

Sources:
  s2        Semantic Scholar Graph API. Key: S2_API_KEY (keyless works but shares a throttled pool).
            Calls are spaced >= 1 s apart and back off exponentially on 429.
  openalex  OpenAlex works search. Key: OPENALEX_API_KEY (required by OpenAlex since Feb 2026).
  arxiv     arXiv export API. No key.
"""

import fcntl
import json
import os
import sqlite3
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

from .db import now

USER_AGENT = "jarvis-research-ideation/0.1 (+https://github.com/jaded0/jarvis-research-ideation)"


def _get(url: str, headers: dict | None = None, retries: int = 3) -> bytes:
    """GET with naive backoff on 429/5xx."""
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, **(headers or {})})
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return resp.read()
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503) and attempt < retries - 1:
                time.sleep(3 * 2 ** attempt)  # arXiv asks for >= 3 s between calls
                continue
            raise


S2_MIN_INTERVAL = 1.05  # seconds; S2's introductory key limit is 1 request/s across all endpoints
S2_FIELDS = "paperId,title,abstract,tldr,year,url,openAccessPdf"  # keep in sync with the key application


def _s2_throttle() -> None:
    """Space S2 calls >= 1 s apart across processes (each CLI call is its own process)."""
    path = os.path.join(os.environ.get("XDG_CACHE_HOME", os.path.expanduser("~/.cache")), "jarvis", "s2_last")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a+") as f:
        fcntl.flock(f, fcntl.LOCK_EX)  # held until the file closes, so concurrent callers queue up
        f.seek(0)
        last = float(f.read() or 0)
        time.sleep(max(0.0, last + S2_MIN_INTERVAL - time.time()))
        f.seek(0)
        f.truncate()
        f.write(str(time.time()))


def search_s2(query: str, limit: int) -> list[dict]:
    _s2_throttle()
    fields = S2_FIELDS
    url = "https://api.semanticscholar.org/graph/v1/paper/search?" + urllib.parse.urlencode(
        {"query": query, "limit": limit, "fields": fields})
    key = os.environ.get("S2_API_KEY")
    data = json.loads(_get(url, {"x-api-key": key} if key else None))
    return [parse_s2(p) for p in data.get("data", [])]


def parse_s2(p: dict) -> dict:
    return {
        "id": f"s2:{p['paperId']}",
        "source": "s2",
        "title": p.get("title") or "",
        "year": p.get("year"),
        "authors": ", ".join(a.get("name", "") for a in p.get("authors") or []),
        "abstract": p.get("abstract") or "",
        "tldr": (p.get("tldr") or {}).get("text") or "",
        "url": (p.get("openAccessPdf") or {}).get("url") or p.get("url") or "",
        "raw": p,
    }


def search_openalex(query: str, limit: int) -> list[dict]:
    params = {
        "search": query,
        "per-page": limit,
        "select": "id,display_name,publication_year,authorships,abstract_inverted_index,doi",
    }
    if key := os.environ.get("OPENALEX_API_KEY"):
        params["api_key"] = key
    data = json.loads(_get("https://api.openalex.org/works?" + urllib.parse.urlencode(params)))
    return [parse_openalex(w) for w in data.get("results", [])]


def parse_openalex(w: dict) -> dict:
    # OpenAlex ships abstracts as {word: [positions]}; rebuild the text.
    inv = w.get("abstract_inverted_index") or {}
    words = sorted((pos, word) for word, positions in inv.items() for pos in positions)
    return {
        "id": "openalex:" + w["id"].rsplit("/", 1)[-1],
        "source": "openalex",
        "title": w.get("display_name") or "",
        "year": w.get("publication_year"),
        "authors": ", ".join(a["author"]["display_name"] for a in w.get("authorships") or []),
        "abstract": " ".join(word for _, word in words),
        "tldr": "",
        "url": w.get("doi") or w["id"],
        "raw": w,
    }


ATOM = {"a": "http://www.w3.org/2005/Atom"}


def search_arxiv(query: str, limit: int) -> list[dict]:
    url = "https://export.arxiv.org/api/query?" + urllib.parse.urlencode(
        {"search_query": f"all:{query}", "max_results": limit})
    return parse_arxiv(_get(url))


def parse_arxiv(xml: bytes) -> list[dict]:
    out = []
    for entry in ET.fromstring(xml).findall("a:entry", ATOM):
        abs_url = entry.findtext("a:id", "", ATOM).strip()
        arxiv_id = abs_url.rsplit("/abs/", 1)[-1].split("v")[0] if "/abs/" in abs_url else abs_url
        published = entry.findtext("a:published", "", ATOM)
        out.append({
            "id": f"arxiv:{arxiv_id}",
            "source": "arxiv",
            "title": " ".join(entry.findtext("a:title", "", ATOM).split()),
            "year": int(published[:4]) if published[:4].isdigit() else None,
            "authors": ", ".join(a.findtext("a:name", "", ATOM) for a in entry.findall("a:author", ATOM)),
            "abstract": " ".join(entry.findtext("a:summary", "", ATOM).split()),
            "tldr": "",
            "url": abs_url,
            "raw": {},
        })
    return out


SOURCES = {"s2": search_s2, "openalex": search_openalex, "arxiv": search_arxiv}


def search(conn: sqlite3.Connection, query: str, source: str = "s2", limit: int = 10) -> list[dict]:
    results = SOURCES[source](query, limit)
    for p in results:
        cache(conn, p)
    conn.commit()
    return results


def cache(conn: sqlite3.Connection, p: dict) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO papers (id, source, title, year, authors, abstract, tldr, url, raw_json, fetched_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (p["id"], p["source"], p["title"], p["year"], p["authors"], p["abstract"], p["tldr"], p["url"],
         json.dumps(p["raw"]), now()),
    )


def get(conn: sqlite3.Connection, paper_id: str) -> dict:
    row = conn.execute(
        "SELECT id, source, title, year, authors, abstract, tldr, url FROM papers WHERE id = ?", (paper_id,)
    ).fetchone()
    if row is None:
        raise LookupError(f"paper {paper_id!r} is not cached; find it with `jarvis papers search` first")
    return dict(row)
