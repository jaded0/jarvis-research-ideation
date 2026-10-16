---
name: jarvis
description: Research ideation tools. Use to search the literature (Semantic Scholar, OpenAlex, arXiv), store and dedup research ideas, link ideas to supporting papers, and log evaluation events. Use whenever helping a researcher decide what to try next.
---

# jarvis CLI

All state lives in one SQLite file (`$JARVIS_DB`, default `./jarvis.db`). Every command prints short markdown; add `--json` only when you need exact fields. Set `JARVIS_PROJECT` or pass `-p NAME`.

## Commands

```bash
jarvis project add NAME --description "..."   # once per research project
jarvis project list

jarvis papers search "QUERY" [--source s2|openalex|arxiv] [--limit 10]
jarvis papers show s2:PAPER_ID                 # full abstract of a cached paper

jarvis ideas add --title "..." --summary "one or two sentences" [--body "..."] [--paper s2:ID=why]
jarvis ideas list [--status proposed|approved|rejected|elaborating]
jarvis ideas show ID
jarvis ideas status ID approved|rejected|elaborating
jarvis ideas link ID s2:PAPER_ID --why "..."
jarvis ideas search "KEYWORDS"                  # keyword search over existing ideas
jarvis ideas sample [-n 40]                     # random sample of the pool, for dedup
jarvis ideas export [-o ideas.md]

jarvis notes add "..." [--idea ID]
jarvis event KIND --data '{"...": ...}'        # evaluation log
jarvis stats
```

## Workflow

1. **Ground before proposing.** Search the literature for the researcher's problem. Every idea must cite at least one paper you actually retrieved (`--paper`). Never invent paper ids.
2. **Dedup before adding.** For each candidate idea:
   - Run `jarvis ideas sample` and compare the candidate against the sampled ideas.
   - If it duplicates one, don't add it. Run `jarvis event dedup --data '{"verdict": "duplicate", "match": ID, "candidate": "TITLE"}'`.
   - Otherwise run `jarvis event dedup --data '{"verdict": "unique", "candidate": "TITLE"}'`, then `jarvis ideas add`.
3. **Present a few ideas at a time** (about five). Let the researcher approve, reject or ask you to elaborate on each, and record the answer with `jarvis ideas status`.
4. **Log every time you ask the user something:** `jarvis event ask_user --data '{"reason": "..."}'`. This is how persistence is measured.
5. **Keep context small.** Prefer TLDRs and list views. Only `show` a paper or idea when you need its details.
