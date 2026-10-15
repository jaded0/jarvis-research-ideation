# J.A.R.V.I.S.

**Just-in-time Agent for Research Validation & Ideation Support**

A research ideation assistant for researchers who are stuck. It reads what you have already tried, searches the literature, and suggests a handful of grounded, non-duplicate next directions. It does not write code or run experiments.

Class project.

## Contents

- [`proposal.md`](proposal.md): original project proposal, based on the first (more elaborate) brainstorm.
- [`Notebook-18.pdf`](Notebook-18.pdf): handwritten brainstorm.
  - Page 1: first pipeline sketch (collect → judge with Elo → deliver → human judge), then a "SIMPLER" pass and evaluation criteria (value, variety, persistence).
  - Page 2: UI sketches (project description → idea list → approve/reject/elaborate).
  - Page 3: MVP scope. This is the current direction.
- [`references/`](references/): related work on AI scientists and idea generation.

## MVP direction (from page 3)

- Agent harness: [pi](https://github.com/badlogic/pi-mono) (leaning), with the tools built as a plain CLI + skill so they stay harness-agnostic.
- A basic chatbot UI; the only special feature is an occasional multiple-choice prompt.
- RAG tools: arXiv search, plus an ideas DB linking to papers, notes, and summaries.
- Agents: a main chat agent, a dedup evaluator, and maybe research-specific subagents.
- Models: cheap API models (e.g. Flash, Haiku).
- Design rules: manage context aggressively, and use naive solutions only. Write elegant ideas down for later.
