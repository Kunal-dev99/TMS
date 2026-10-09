# Feature kickoff — AuthN substrate: TOTP MFA + SSO port shape (no real provider yet)

**Date:** 2026-10-09
**Status:** plan approved → ___ (fill in once approved)
**Author:** architect agent

## Requirement

The product has no SSO customer yet and MFA isn't offered to users. We want
the code to be **ready** for both — so that when customer #1 asks for SSO,
it's a config change plus one adapter file, not a rewrite — and we want
**TOTP MFA shipped as a real, usable feature today** (independent of any
IdP, opt-in per user, enforceable per tenant later).

**Constraints the user named explicitly:**
- Must not break day-to-day dev + testing. Every change behind a default-off
  switch or feature flag; local-password sign-in stays the only path until
  someone opts in. If we `git checkout` back to today's commit the behaviour
  is identical.
- Must follow the new Fusion AI-assisted engineering approach — plan first,
  phases with Done-when per phase, reversibility per phase, worktree
  isolation per D-03, ADRs for non-obvious decisions.

## Pre-plan reading completed
- `.context/MANIFEST.json` + the files in `read_order_for_new_chats`
- `.context/open-questions.json` — no open Q blocks this
- Relevant ADRs: ADR-0011 (permission matrix), ADR-0013 (scope preflight),
  ADR-0014 (activation links), ADR-0015 (four-eye on sensitive grants),
  ADR-0020 (Postgres in prod)
- `PARKED_PLANS.json` — this feature does **not** overlap any parked plan's
  forbidden territory (SSO is called out in the Admin UI plan but as a
  future admin surface; the backend substrate here is unparked)
- `backend/app/security.py`, `backend/app/api/auth.py`,
  `backend/app/connector/ports.py::IdentityPort`,
  `backend/app/connector/adapters/identity/local_password.py`
- `backend/app/models.py::SsoIdentity`, `::SsoGroupMap` (empty substrate
  tables shipped in Phase 2 Stage 2 — unused today, ready to use)

## Plan

See the architect's plan in this session's conversation (phases BE-1.x …
BE-5.x, each with Done-when + reversibility note). This file exists so a
future session can find the kickoff that produced the resulting commits.
