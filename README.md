# J.A.R.V.I.S.

**Just-in-time Agent for Research Validation & Ideation Support**

A research ideation assistant for researchers who are stuck. It reads what you have already tried, searches the literature, and suggests a handful of grounded, non-duplicate next directions. It does not write code or run experiments.

Class project.

## Quick start

```bash
uv sync                          # install (Python ≥ 3.11, no runtime dependencies)
export JARVIS_PROJECT=demo      # API keys can go in .env at the repo root; jarvis loads it
uv run jarvis project add demo --description "what the research is about"
uv run jarvis papers search "fast weights memory"          # OpenAlex by default; also --source arxiv|s2
uv run jarvis ideas add --title "..." --summary "..." --body "description" --paper "openalex:W3132041002=why"
uv run jarvis ideas edit 1 --append "elaboration: first experiment, signal, risk"
uv run jarvis ideas export -o ideas.md
uv run pytest
```

To talk to J.A.R.V.I.S., `cd` into *your research project* and run `jarvis chat` (install once with `uv tool install -e ~/jarvis`, or use `uv run --project ~/jarvis jarvis chat`). This launches [pi](https://github.com/badlogic/pi-mono) with:
- the persona in `src/jarvis/persona.md`, appended to pi's system prompt
- only the jarvis skill (`src/jarvis/skill/`)
- read-only tools plus bash, so it can't edit your files
- Haiku 5.5 through OpenRouter, with Ctrl+P switching to Luna. Override with `JARVIS_MODELS=provider/model,...`, and pass extra pi flags after `--`.

The database (`jarvis.db`) and the project name default to the current directory. Working on this repo with pi or another coding agent is unaffected; the skill is also linked at `.agents/skills/jarvis` for testing.

## Slides

The slides are in `slides/slides.md`, written as [Marp](https://marp.app) markdown: `---` separates slides, and images go in `slides/img/` as `![](img/foo.png)`. You need Node (for `npx`) and Chrome or Chromium.

```bash
make -C slides          # build slides/slides.pdf (gitignored)
make -C slides watch    # live preview server; re-renders on save
make -C slides clean
```

The Makefile pins `@marp-team/marp-cli@4.5.1` and finds Chrome on its own. If it guesses wrong, set `CHROME_PATH`.

On every push to `main`, GitHub Actions (`.github/workflows/ci.yml`) runs the tests and builds the slides. The PDF can be downloaded as the `slides` artifact on each run in the [Actions tab](https://github.com/jaded0/jarvis-research-ideation/actions).

## Layout

- `src/jarvis/db.py`: SQLite schema (projects, ideas + FTS5, papers cache, idea↔paper links, notes, events).
- `src/jarvis/ideas.py`: the idea pool, including `sample` for naive dedup (a random n, capped by characters).
- `src/jarvis/papers.py`: Semantic Scholar / OpenAlex / arXiv search; results are cached in `papers`.
- `src/jarvis/cli.py`: the `jarvis` command; `stats` reports value, variety and persistence from `events`; `chat` launches pi.
- `src/jarvis/persona.md`: the J.A.R.V.I.S. persona (session flow, idea format, behaviour).

## Data sources

Literature data comes from [Semantic Scholar](https://www.semanticscholar.org) (Kinney et al., *The Semantic Scholar Open Data Platform*, 2023), [OpenAlex](https://openalex.org) and [arXiv](https://arxiv.org). Read [docs/semantic-scholar.md](docs/semantic-scholar.md) before changing anything that calls the S2 API.

## Contents

- [`proposal.md`](proposal.md): original project proposal, based on the first (more elaborate) brainstorm.
- [`Notebook-18.pdf`](Notebook-18.pdf): handwritten brainstorm.
  - Page 1: first pipeline sketch (collect → judge with Elo → deliver → human judge), then a "SIMPLER" pass and evaluation criteria (value, variety, persistence).
  - Page 2: UI sketches (project description → idea list → approve/reject/elaborate).
  - Page 3: MVP scope. This is the current direction.
- [`references/`](references/): related work on AI scientists and idea generation.
- [`docs/presentation.md`](docs/presentation.md): progress presentation (due 2026-10-27, 2 pm), with requirements and a checklist.
- [`slides/`](slides/): presentation slides in Marp markdown; see [Slides](#slides).

## MVP direction (from page 3)

- Agent harness: [pi](https://github.com/badlogic/pi-mono). The tools are a plain CLI + skill, so the harness can be swapped.
- A basic chatbot UI; the only special feature is an occasional multiple-choice prompt.
- RAG tools: arXiv search, plus an ideas DB linking to papers, notes, and summaries.
- Agents: a main chat agent, a dedup evaluator, and maybe research-specific subagents.
- Models: cheap API models. Claude Haiku is the default; OpenAI Luna is the alternate.
- Design rules: manage context aggressively, and use naive solutions only. Write elegant ideas down for later.
