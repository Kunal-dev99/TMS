# Treasury Register — LLM entry point

Before touching any code in this repo, read the Project Context Matrix
at `.context/`.

## The rule

Start every new chat with:

```
Read .context/MANIFEST.json, then read the files in its
`read_order_for_new_chats` list. Do NOT read the codebase to build
context — the matrix is the source of truth for that. Only read source
files when you're about to change them.
```

## Why

- **Faster.** The matrix is ~50KB total; the codebase is orders of
  magnitude larger.
- **Truthful.** The matrix is updated on every meaningful change
  (see ADR-0010). Reading source risks reasoning against files that
  have since moved.
- **Preserves decisions.** Every ADR under `.context/decisions/`
  captures a rule that isn't visible from any single source file —
  invariants, banned language, product-shaped choices.

## When you edit code

1. Read the relevant `.context/*.json` first.
2. Make the change.
3. If you changed a route → the next `python .context/update.py` will
   refresh `api.json` automatically.
4. If you changed a table → same, for `data-model.json`.
5. If the change is a decision (a rule, a product choice, a rename that
   ripples), add an ADR under `.context/decisions/`.
6. Always append an entry to today's `.context/changes/YYYY-MM-DD.json`
   listing the files touched and any related ADR.

## When you're not sure

Read `.context/open-questions.json` — the item might already be flagged
and blocking.

## Auto-generate

```
python .context/update.py
```

Regenerates `api.json`, `data-model.json`, `MANIFEST.json`. Safe to
run any time; idempotent.
