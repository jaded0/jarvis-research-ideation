"""OpenRouter embeddings. Float32 storage, brute-force cosine."""

from array import array
import json
import math
import os
import time
import urllib.error
import urllib.request

from .papers import RETRY_CODES, USER_AGENT

MODEL = "openai/text-embedding-3-small"


def model() -> str:
    return os.environ.get("JARVIS_EMBED_MODEL", MODEL)


def embed(texts: list[str]) -> list[list[float]]:
    key = os.environ.get("OPENROUTER_API_KEY")
    if not key:
        raise ValueError("OPENROUTER_API_KEY is not set")
    req = urllib.request.Request(
        "https://openrouter.ai/api/v1/embeddings",
        data=json.dumps({"model": model(), "input": texts}).encode(),
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json", "User-Agent": USER_AGENT})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.load(resp)
            vectors = [r["embedding"] for r in sorted(data["data"], key=lambda r: r["index"])]
            if len(vectors) != len(texts) or any(not v or not all(math.isfinite(x) for x in v) for v in vectors):
                raise ValueError("invalid embedding response")
            return vectors
        except urllib.error.HTTPError as e:
            if e.code not in RETRY_CODES or attempt == 2:
                raise
            retry_after = e.headers.get("Retry-After", "") if e.headers else ""
            wait = float(retry_after) if retry_after.isdigit() else 0.0
            time.sleep(min(60.0, max(wait, 3 * 2 ** attempt)))


def pack(vector) -> bytes:
    return array("f", vector).tobytes()


def unpack(blob: bytes) -> array:
    vector = array("f")
    vector.frombytes(blob)
    return vector


def cosine(a, b) -> float:
    if len(a) != len(b):
        return 0.0
    norm = math.sqrt(sum(x * x for x in a) * sum(x * x for x in b))
    return sum(x * y for x, y in zip(a, b)) / norm if norm else 0.0
