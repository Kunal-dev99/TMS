# Treasury Register — LLM entry point

This project follows Fusion Practices' AI-assisted engineering approach.
Methodology: `docs/AI_Assisted_Development_Framework.md`.
Feature kickoff template: `docs/MASTER_PROMPT_FEATURE_KICKOFF.md`.
Agent roles + boundaries: `.claude/agents/{solution-architect,backend-engineer,frontend-engineer}.md`.
Dev scripts (OneDrive-safe, port-clearing): `scripts/start-backend.ps1`, `scripts/start-frontend.ps1`.

Standing rules (**D-01 additive · D-02 reversible · D-03 isolation ·
D-04 fail-closed authz**) are enforced in the agent definitions. D-03
isolation is formalised in ADR-0021.

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

For questions about **where the product is heading** (Phase 2, real
data sources, integrations, roadmap), read `PHASE_2_BLUEPRINT.md` at
the repo root and `.context/roadmap.json`. The matrix describes what
exists; those two describe what comes next.

For **how Phase 2 is actually built** (package layout, port
interfaces, adapters, migrations, sequencing) read
`PHASE_2_IMPLEMENTATION_PLAN.md`. Stages 1–3 have shipped; Stages 4+
are still parked. Do NOT start executing later stages of this plan
unless the user explicitly asks to "unpark it" or "start Stage N".

Two peer plans are **parked** — no code exists yet, do not start
either without explicit "unpark" instruction:

- `PHASE_2_ADMIN_UI_PLAN.md` — admin surfaces for Phase 2 tables
  (Oracle mappings, SSO group map, Integration Health). Needed when
  Stages 4/7/9 of the implementation plan land.
- `PHASE_2_MULTITENANCY_PLAN.md` — Postgres RLS, tenant provisioning,
  platform admin, break-glass, data residency. Unpark when customer
  #2 is real. Resolves Q-002.

**The park state is ENFORCED, not documented.** `PARKED_PLANS.json`
at repo root names every parked plan + the exact files and symbols
that must NOT exist while it is parked. `backend/tests/test_parked_plans.py`
runs on every CI and fails hard if any parked-plan territory is
touched. To start building a parked plan:

  1. Read the plan document end-to-end.
  2. Change that plan's `status` from `"parked"` to `"unparked"` in
     `PARKED_PLANS.json` — as its own commit, so the diff is the
     audit record.
  3. Only then start writing code.

Attempting to build a parked plan without step (2) fails CI with a
message naming exactly which plan needs unparking and how.

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
