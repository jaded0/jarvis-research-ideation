# Using the Semantic Scholar API responsibly

We applied for a Semantic Scholar (S2) API key on 2026-10-16 as a two-person class project at BYU. The key is a trust relationship: S2 can suspend or revoke it at any time without notice ([license](https://www.semanticscholar.org/product/api/license)). These are the rules we follow so we keep it.

## Rules

1. **Never exceed 1 request per second, on any endpoint, combined.** The introductory key limit is 1 req/s across *all* endpoints together, not per endpoint. The license also forbids trying to "exceed or circumvent limitations". So:
   - Don't spread load across several keys, and don't fall back to keyless requests to get extra throughput.
   - Don't run parallel evaluation jobs against one key.
2. **Back off on 429 and 5xx; never retry in a tight loop.** A 429 means slow down, not try again immediately.
3. **Ask for only the fields we use.** Extra fields slow S2's responses. Our application declared `paperId, title, abstract, tldr, year, url, openAccessPdf`. Adding a field means updating `S2_FIELDS` in `src/jarvis/papers.py` and this doc together, and it should still match what we told S2 we would use.
4. **Fetch each paper once.** Cache everything locally and look papers up by ID before searching again.
5. **Use batch endpoints for lookups.** To get details for several known papers, use one `POST /graph/v1/paper/batch` (up to 500 IDs), not N single-paper requests.
6. **Relevance search is the expensive endpoint.** S2's tutorial says bulk search (`/paper/search/bulk`) "should be used in most cases because paper relevance search is more resource intensive". We use relevance search because the agent needs the top few *ranked* results, so we keep `limit` small (10 by default). Anything that wants many results, sorting, or a sweep (for example, building an evaluation corpus) uses bulk search or the [Datasets API](https://api.semanticscholar.org/api-docs/datasets), not hundreds of relevance searches.
7. **Bulk data comes from Datasets, never from crawling the API.**

## Key handling

- Keep the key in the `S2_API_KEY` environment variable, for example in a `.env` file (git-ignored) or your shell profile. Never commit it, paste it into an issue or chat, or put it in a prompt or log the agent can see.
- **Don't share the key.** The license allows disclosure only to people authorized to use the API for your organization. To be safe, Jason should apply for his own key instead of borrowing Jaden's. Two keys are fine as long as each person uses only their own; rule 1 forbids pooling them for throughput.
- Keys that are inactive for about 60 days may be removed. If the project pauses, expect to re-apply.
- If a key leaks, ask S2 to revoke it and request a new one.

## Attribution

- The README credits Semantic Scholar as a data source.
- The class report and any paper must cite the platform: Kinney et al., *The Semantic Scholar Open Data Platform* (2023), [arXiv:2301.10140](https://arxiv.org/abs/2301.10140).
- S2 data carries its own licenses (some abstracts are CC BY-NC, etc.). Don't commit a dump of S2 responses to the public repo. `jarvis.db` is git-ignored for this reason.

## What the code enforces

| Rule | Where |
|---|---|
| ≥ 1.05 s between S2 calls, across all processes on the machine (file lock on `~/.cache/jarvis/s2_last`) | `papers._s2_throttle` |
| Exponential backoff on 429/5xx (3 s, 6 s), then give up | `papers._get` |
| Only the declared fields | `papers.S2_FIELDS` |
| Paper metadata is cached; identical searches are reused for 7 days (`--refresh` to override) | `papers.search`, `searches` table |
| Agent instructions: reuse cached papers and keep searches few | `src/jarvis/skill/SKILL.md` |

The throttle is per machine. Two people running on different machines with **different** keys is fine. **The same** key on two machines at once is not, because the throttles don't see each other.

## Before running anything big

For example, an evaluation over many held-out projects:
- Estimate the requests first: projects × sessions × searches per session. At 1 req/s that's at most 86,400 a day, but we told S2 to expect about 100–500 a day typically and up to about 3,000 on evaluation days. Stay within that.
- Run sequentially, not in parallel.
- Prefer pre-fetching a corpus once (bulk search or Datasets) and evaluating against the cache.
- If we ever need more, ask S2 for a higher limit rather than working around it.

## Notes

- From BYU's network, **keyless** requests are usually rate-limited (429), because the whole campus shares outgoing IP addresses and the keyless pool is shared. A key fixes that. Don't use the keyless pool as a backup.
- OpenAlex and arXiv have their own etiquette. arXiv asks for ≥ 3 s between calls. OpenAlex bills per call beyond $1/day of free usage.
