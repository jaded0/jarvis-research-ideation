# J.A.R.V.I.S.

**Just-in-time Agent for Research Validation & Ideation Support**

A research ideation assistant for researchers who are stuck. It reads what you have already tried, searches the literature, and suggests a handful of grounded, non-duplicate next directions. It does not write code or run experiments.

Class project.

## Quick start

```bash
uv sync                          # install (Python ≥ 3.11, no runtime dependencies)
export JARVIS_PROJECT=demo S2_API_KEY=... OPENALEX_API_KEY=...
uv run jarvis project add demo --description "what the research is about"
uv run jarvis papers search "fast weights memory" --source s2
uv run jarvis ideas add --title "..." --summary "..." --paper s2:<id>=why
uv run jarvis ideas export -o ideas.md
uv run pytest
```

Run `pi` in this directory to use it as an agent. The project settings in `.pi/settings.json` make Claude Haiku 5.5 the default, and the skill in `.agents/skills/jarvis/` explains the CLI to the agent. Any harness that reads Agent Skills, or can just run bash, works too.

## Layout

- `src/jarvis/db.py`: SQLite schema (projects, ideas + FTS5, papers cache, idea↔paper links, notes, events).
- `src/jarvis/ideas.py`: the idea pool, including `sample` for naive dedup (a random n, capped by characters).
- `src/jarvis/papers.py`: Semantic Scholar / OpenAlex / arXiv search; results are cached in `papers`.
- `src/jarvis/cli.py`: the `jarvis` command; `stats` reports value, variety and persistence from `events`.

## Contents

- [`proposal.md`](proposal.md): original project proposal, based on the first (more elaborate) brainstorm.
- [`Notebook-18.pdf`](Notebook-18.pdf): handwritten brainstorm.
  - Page 1: first pipeline sketch (collect → judge with Elo → deliver → human judge), then a "SIMPLER" pass and evaluation criteria (value, variety, persistence).
  - Page 2: UI sketches (project description → idea list → approve/reject/elaborate).
  - Page 3: MVP scope. This is the current direction.
- [`references/`](references/): related work on AI scientists and idea generation.

## MVP direction (from page 3)

- Agent harness: [pi](https://github.com/badlogic/pi-mono). The tools are a plain CLI + skill, so the harness can be swapped.
- A basic chatbot UI; the only special feature is an occasional multiple-choice prompt.
- RAG tools: arXiv search, plus an ideas DB linking to papers, notes, and summaries.
- Agents: a main chat agent, a dedup evaluator, and maybe research-specific subagents.
- Models: cheap API models. Claude Haiku is the default; OpenAI Luna is the alternate.
- Design rules: manage context aggressively, and use naive solutions only. Write elegant ideas down for later.
