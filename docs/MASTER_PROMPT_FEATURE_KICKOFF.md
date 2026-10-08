# Master prompt — feature kickoff

A copy-paste template for the start of any new feature in this project.
Edit the three fenced placeholders; paste the whole thing into a fresh
Claude Code session.

---

```
# Feature: <<one-line name of the feature>>

## Requirement
<<Paragraph. What outcome is the user asking for? Who is the persona?
What triggers it? What does success look like from the outside — not
the implementation, the behaviour.>>

## Pre-plan reading (do this before you write a plan or any code)
1. Read .context/MANIFEST.json → every file in `read_order_for_new_chats`.
2. Read .context/open-questions.json. Flag anything related to this feature.
3. Read every ADR in .context/decisions/ whose title mentions a subject this feature touches.
4. Read PARKED_PLANS.json. If this feature overlaps a parked plan's forbidden territory, STOP and surface it — don't start by unparking.
5. Read PHASE_2_BLUEPRINT.md and PHASE_2_IMPLEMENTATION_PLAN.md for roadmap context — this feature slots into them, not around them.
6. Explore the codebase for the most relevant existing module. If a similar feature exists, read its router + service + repo + tests end to end. Mirror its shape.

## Standing rules (D-01…D-04 — enforced everywhere)
- D-01 Additive, never destructive. Forward migrations do not DROP. Exceptions require an ADR.
- D-02 Reversibility. Every migration ships a tested downgrade. New behaviour sits behind a setting or an additive migration.
- D-03 Isolation. Build this feature in a git worktree outside the running app, against a DB copy. Not the live dev DB.
- D-04 Fail closed on authorization. New endpoints use `Depends(require_permission(...))` or `require_role(...)`.

Project-specific rules on top of the standing ones:
- Portable DDL (ADR-0018) — every migration works on SQLite AND Postgres.
- Per-tenant config → `tenant_setting` table via `backend/app/repo/tenant_settings.py`. No new in-memory singletons.
- Secrets → `SecretsPort` only. No direct `os.environ` for anything that could be a secret.
- AI calls → `ai_run_service.chat()`. Audit trail is the point.
- Rate-limited endpoints add a `LimitPolicy` to `backend/app/services/rate_limit.py`.
- Logs → `app.logging.get_logger`. `request_id` + `tenant_id` are already bound by the middleware.

## Deliver the plan FIRST (no code yet)
Hand back a plan with:
- Phases (ordered). Each phase has a one-line Done-when (an observable: a test, a route shape, a column that holds a value).
- Reversibility note per phase: what the downgrade looks like, what setting disables the new behaviour.
- Deferred list: things in scope for the feature but out of scope for this round. Named + reasoned.
- BE-* and FE-* task IDs that never get renumbered.
- One ADR per non-obvious decision (data model shape, authorisation boundary, dependency choice).

## Build ONE phase, then stop
Build the first phase only. Run its tests. Hand back the plan with that phase ticked (by the architect, after verification), the test output quoted verbatim, and the Done-when for the next phase as the next prompt. Do not race ahead.

## What you must NOT do
- Write code against this prompt. The first output is a plan, not a diff.
- Touch the live dev DB. All work in a worktree against a DB copy (D-03, ADR-0021).
- Delete data. Lifecycle actions hide; schema changes are additive (D-01, D-02).
- Approve your own request. Four-eye flows are the point (ADR-0015).
- Tick your own tasks. The engineer agent reports done; the architect verifies and ticks.
- Fabricate test coverage. Quote the actual pytest / tsc output. "Looks right" is not Done-when.
```

---

## Why this exists
Fusion's AI-assisted engineering approach treats the plan as a first-class deliverable. The plan is reviewable, the implementation is derivative. If the plan is wrong, catching it in review costs minutes; catching it in merge costs days.

A kickoff that skips the plan is a kickoff that ships someone's guesses as if they were decisions.
