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
jarvis ideas edit ID [--title ...] [--summary ...] [--body "replace description"] [--append "add to description"]
jarvis ideas list [--status proposed|approved|rejected|elaborating]
jarvis ideas show ID
jarvis ideas status ID approved|rejected|elaborating
jarvis ideas link ID PAPER_ID --why "..."
jarvis ideas search "KEYWORDS"                  # existing ideas matching any keyword, best first
jarvis ideas sample [-n 40]                     # random sample of the pool, for dedup
jarvis ideas export [-o ideas.md]

jarvis notes add "..." [--idea ID]
jarvis notes list
jarvis event KIND --data '{"...": ...}'        # evaluation log
jarvis stats
```

## Protocols

1. **Ground before proposing.** Search the literature for the researcher's problem. Every idea must cite at least one paper you actually retrieved (`--paper`). Never invent paper ids.
2. **Dedup before adding, one candidate at a time.** Take a fresh sample for every candidate, after adding the previous one, so new ideas are checked against each other too:
   - Run `jarvis ideas sample` and compare the candidate against the sampled ideas.
   - If it duplicates one, don't add it. Run `jarvis event dedup --data '{"verdict": "duplicate", "match": ID, "candidate": "TITLE"}'`.
   - Otherwise run `jarvis event dedup --data '{"verdict": "unique", "candidate": "TITLE"}'`, then `jarvis ideas add`.
3. **Log every time you ask the user something:** `jarvis event ask_user --data '{"reason": "..."}'`. This is how persistence is measured.
4. **Go easy on the APIs.** Our Semantic Scholar key allows 1 request/s and can be revoked. Before searching, check whether a paper you already found covers it (ideas link their papers; `jarvis papers show ID` works on any id you've seen). Use a few well-chosen queries (about 3 per idea), not many variations. Never loop searches in bash, and never retry a failed search more than once. Identical searches are served from cache automatically.
