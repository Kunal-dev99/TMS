# Project Context Matrix

Machine-readable index of everything a fresh LLM chat needs to know about
this project **without re-reading the codebase**.

> This directory is for machines. Humans, feel free to look — but treat
> it like a spec, not a manual.

## Read order for a new chat

1. `MANIFEST.json` — index, mtimes, decision list
2. `project.json` — what this app is
3. `architecture.json` — the layers + invariants
4. `conventions.json` — how we write code + product language
5. `backend.json` — the services + their responsibilities
6. `frontend.json` — the panels + design rules
7. `data-model.json` — the DB schema (auto-generated)
8. `api.json` — the endpoint surface (auto-generated)
9. `ai.json` — the LLM paths + safety rails
10. `decisions/` — every ADR that shapes today's code
11. `open-questions.json` — things we've deferred

## What's auto-generated (do NOT hand-edit)

- `api.json` — from `fastapi.openapi()`
- `data-model.json` — from `sqlalchemy.MetaData`
- `MANIFEST.json` — from directory scan

Regenerate:

```bash
python .context/update.py
```

Everything else is hand-written and lives with the code changes that
touched it.

## Adding a decision (ADR)

Copy `decisions/0001-*.json` as a template. Give it the next number.
Keep it terse: context, decision, alternatives_rejected, consequences.

## Journaling changes

Every meaningful code change appends an entry to today's file under
`changes/YYYY-MM-DD.json`. Entries link to the ADR they implement (if
any) and list the files touched. This is the alive-log the whole
matrix exists to preserve.

## Why JSON, not YAML or Markdown

JSON is faster to parse for LLMs, denser than YAML, and structured
enough that a query like "find every ADR touching planner_service.py"
is trivial. The tradeoff is human legibility — that's what this README
and inline `purpose` / `notes` fields are for.
