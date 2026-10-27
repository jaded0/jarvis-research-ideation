# Progress presentation

**Due: Tuesday 2026-10-27, 2:00 pm.** 15 minutes.

## Assignment

> Prepare a 15 minute presentation, including slides, preliminary results, demonstrations, etc. that showcase your project in its current state. Argue for why it is/will be creative, and discuss challenges and work yet to be accomplished.

## What it has to cover

- [ ] Current state of the project
- [ ] Preliminary results
- [ ] Demonstration (live, or screenshots/recording as backup)
- [ ] Why it is / will be creative
- [ ] Challenges
- [ ] Work still to do

## Materials

- Slides: [`slides/slides.md`](../slides/slides.md), built to PDF with `make -C slides` (pandoc + beamer + xelatex, metropolis theme). Put images in `slides/img/`.
- Demo candidate: run `jarvis chat` inside `~/ai-jeans` to show the interface on a real research project.
- Screenshots: TBD.

## Known issues going in

- Semantic Scholar was returning HTTP 429 on 2026-10-26, even with the API key. OpenAlex and arXiv work. For the demo, use `--source openalex` or `--source arxiv`, or have results cached beforehand.
