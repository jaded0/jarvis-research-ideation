---
name: jarvis
description: Research ideation tools. Use to search the literature (OpenAlex, arXiv, Semantic Scholar), store and dedup research ideas, link ideas to supporting papers, and log evaluation events. Use whenever helping a researcher decide what to try next.
---

# jarvis CLI

This skill is the command reference plus the mechanical protocols (dedup, event logging, API use). Who you are and how a session flows is in the J.A.R.V.I.S. persona.

All state lives in one SQLite file (`$JARVIS_DB`, default `./jarvis.db`). Every command prints short markdown; add `--json` after the subcommand (`jarvis ideas list --json`) only when you need exact fields. The project comes from `$JARVIS_PROJECT`, which `jarvis chat` sets, so don't pass `-p`. (Outside `jarvis chat`, from the jarvis repo: `uv run -q jarvis`.)

## Commands

```bash
jarvis project add NAME --description "..."   # setup only; never during a session
jarvis project list

jarvis papers search "QUERY" [--source openalex|arxiv|s2] [--limit 10]   # default openalex
jarvis papers show PAPER_ID                     # full abstract of a cached paper

jarvis ideas add --title "..." --summary "one or two sentences" [--body "description"] [--paper ID=why]
jarvis ideas add --title "..." --summary "..." --distinct-from "1,2" [--threshold 0.5] [--paper ID=why]
jarvis ideas edit ID [--title ...] [--summary ...] [--body "replace description"] [--append "add to description"]
jarvis ideas list [--status proposed|approved|rejected|elaborating] [--ranked]
jarvis ideas prefer WINNER_ID LOSER_ID [--why "..."] # researcher preference; no API call
jarvis ideas rank [--rounds 1]                  # on demand only: refresh after a direction change
jarvis ideas show ID
jarvis ideas status ID approved|rejected|elaborating
jarvis ideas link ID PAPER_ID --why "..."
jarvis ideas check --title "..." --summary "..." # neighbours only; no insertion
jarvis ideas embed                              # backfill this project's current-model embeddings
jarvis ideas search "QUERY" [--limit 10]        # semantic neighbours; FTS keyword fallback
jarvis ideas export [-o ideas.md]

jarvis notes add "..." [--idea ID]
jarvis notes list
jarvis event ask_user --data '{"reason": "..."}' # evaluation log; dedup is CLI-only
jarvis stats
```

## Protocols

Ranking means **most promising for this researcher to try next**: approved/elaborating first, then proposed, then rejected; Elo descending within each tier. `ideas list --ranked` includes Elo and comparison counts, with no judgments. Accepted adds make at most three concurrent model judgments against nearby-Elo non-rejected ideas. `prefer` records a user judgment with twice the model's Elo weight (K=64 vs 32). `rank` explicitly requests Swiss-style rounds (adjacent non-rejected ideas by Elo); it prints the call count, ⌊M/2⌋ per round. It is never automatic. OpenRouter judge: `anthropic/claude-haiku-5.5`, overridden by `JARVIS_JUDGE_MODEL`; uses `OPENROUTER_API_KEY` and the project description plus the latest note starting with `PROJECT SUMMARY`. Start project-summary notes with that prefix.

1. **Ground before proposing.** Search the literature for the researcher's problem. Every idea must cite at least one paper you actually retrieved (`--paper`). Never invent paper ids.
2. **Dedup through add, one candidate at a time.** The CLI embeds title + summary through OpenRouter (`OPENROUTER_API_KEY`), default `openai/text-embedding-3-small`; `JARVIS_EMBED_MODEL` overrides the model. It scans the project's current-model embeddings, including rejected ideas. Cosine scores ≥0.5 gate insertion; `--threshold` on add overrides this gate, not a substitute for reviewing neighbours.
   - Optionally screen with `jarvis ideas check --title "..." --summary "..."`: it lists neighbours without inserting. Then use the add command above with retrieved paper evidence; add always checks again, so newly accepted ideas are included.
   - If add refuses, read every flagged neighbour (use `jarvis ideas show ID` for detail). Drop a repeat. Only if genuinely different, retry add with comma-separated `--distinct-from` IDs covering **every** flagged neighbour, including rejected ones. Do not bypass review by raising the threshold.
   - Missing keys or embedding failures visibly fall back to keyword neighbours, which also gate insertion. Older rows lacking current-model embeddings are keyword-gated even when candidate embedding succeeds. Use `jarvis ideas embed` to backfill the selected project for the current model.
   - Add automatically logs `dedup` verdicts `flagged` (refused) or `unique` (accepted). Never log dedup yourself: the event command forbids it. `stats` reports `duplicate_rate` = flagged / (flagged + unique) CLI add attempts; retries count, and similarity flags are not ground-truth duplicates.
3. **Log every time you ask the user something** (each `ask` call counts): `jarvis event ask_user --data '{"reason": "..."}'`. This is how persistence is measured.
4. **Go easy on the APIs.** Our Semantic Scholar key allows 1 request/s and can be revoked. Before searching, check whether a paper you already found covers it (ideas link their papers; `jarvis papers show ID` works on any id you've seen). Use a few well-chosen queries (about 3 per idea), not many variations. Never loop searches in bash, and never retry a failed search more than once. Identical searches are served from cache automatically.
