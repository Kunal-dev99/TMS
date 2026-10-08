# Phase 2 — Multi-Tenancy Plan (parked)

> **⛔ PARKED — ENFORCED.** This plan's parked status is enforced by
> `backend/tests/test_parked_plans.py` reading `PARKED_PLANS.json`
> (plan id `phase_2_multitenancy`). Creating any of the forbidden
> files, symbols, or SQL patterns listed there (including RLS DDL in
> a migration) fails CI. To start building, first change
> `status: "parked"` → `"unparked"` in `PARKED_PLANS.json` **as its
> own commit** — the diff is the audit trail. Add ADR-0019 in the
> same commit recording the Q-002 resolution.

**Status:** parked. Not started. Unpark when customer #2 becomes real.
**Companion to:** `PHASE_2_IMPLEMENTATION_PLAN.md` (this plan is a peer Stage 11) and `PHASE_2_ADMIN_UI_PLAN.md` (the new-tenant wizard reuses its patterns).
**Purpose:** the plan for taking the app from single-tenant (today) to enterprise-grade multi-tenant, without ever leaking a row across customers.

## Anchor

Today every table has a `tenant_id` column and every service query includes `WHERE tenant_id = ?`. **Nothing enforces that at the database layer.** A missing WHERE in one endpoint would leak customer A's deals to customer B — a single bug becomes a data breach.

Enterprise-grade multi-tenancy means the **database** refuses to return another tenant's row, no matter what the application code asks for. Postgres row-level security (RLS) is the mature answer. Q-002 in `open-questions.json` names this.

## Rules that hold across every multi-tenant change

- **Default deny.** RLS on every table. New tables added later automatically get an RLS policy — enforced by a test.
- **Tenant identity comes from the auth layer, not the request body.** Set via `SET LOCAL app.tenant_id = ?` in a per-request middleware.
- **Platform admins are separate.** A special role held only by our staff. Every platform-admin action logs at higher severity + emits a notification (§4).
- **Break-glass access to cross-tenant data** is opt-in per session, logged, and auto-expires after 15 minutes.
- **Tenant deprovisioning is archive, not delete.** A departed customer's data stays for the contracted retention (7 years UK/EU default), read-only.
- **Per-tenant secrets isolation.** Each tenant's Oracle service account, Xignite key, SMTP credentials live in a per-tenant vault path (§5).
- **Data residency is per-tenant.** UK customer's DB lives in UK region, EU customer's in EU. Enforced at provisioning time.

## Q-002 — resolved (proposed)

**Shared schema + `tenant_id` column + Postgres RLS.** Not schema-per-tenant.

Reasons:
- Every table already has `tenant_id`; no migration to reshape.
- Postgres RLS is mature, well-audited, and matches our threat model (SQL injection into an unfiltered query is the class of attack RLS actually neutralises).
- Backup + PITR + monitoring stay a single-DB problem, not N.
- Schema-per-tenant remains an escape hatch for a future customer whose regulator demands physical DB isolation. The abstraction below is compatible with either.

Downside: RLS policies must be right on every table forever. Mitigated by the invariant test (§7) that every table has a policy AND every policy references `app.tenant_id`.

---

## 1. New database work

### 1.1 The `app.tenant_id` setting

Postgres session-scoped setting, wiped at connection release. Set via one line in a request middleware:

```sql
SET LOCAL app.tenant_id = 'ten_abc';
```

`LOCAL` means it stays within the transaction — a connection returned to the pool has no leaked context.

### 1.2 The RLS policy shape

One policy per table:

```sql
ALTER TABLE deal ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation_deal ON deal
    USING (tenant_id = current_setting('app.tenant_id')::text);
```

`FORCE ROW LEVEL SECURITY` on every table so **even the table owner** can't bypass it (blocks a runaway migration script from leaking). Only the platform-admin role (§4) is `BYPASSRLS`.

### 1.3 The migration

One migration adds the policy to every existing table (~52 today). New tables from that point on get a fixture in `conftest.py` that adds their policy at test time; the test suite refuses a table without one.

`tenant_id`-less tables (`tenant` itself, `system_clock`, `rating_band` — global reference data) are called out in a **`RLS_EXEMPT` allow-list**. The allow-list is the only place a new table can escape RLS, and adding to it needs an ADR.

### 1.4 Non-Postgres fallback

SQLite has no RLS. When `TREASURY_DATABASE_URL` is SQLite (dev + demo VM), RLS is skipped and the app relies on service-layer `WHERE tenant_id = ?` clauses — same as today. **A separate invariant test** exercises every service query with a two-tenant fixture to prove nothing leaks in the SQLite path either.

Production (multi-tenant) always uses Postgres.

## 2. New services + middleware

### 2.1 `TenantContextMiddleware`

Runs after auth. Reads `caller.tenant_id`, issues:
```
SET LOCAL app.tenant_id = '<tenant>'
```
on the request's DB session. Wipes on request end (implicit via `LOCAL`).

Refuses the request with `501 TENANT_UNKNOWN` if the caller has no tenant. No default; no fallback.

### 2.2 `TenantProvisioner`

Idempotent function that stands up a new tenant:

1. Insert `tenant` row.
2. Seed `policy_version` (default) + `rating_band` catalogue.
3. Insert first `app_user` with role `ADMIN`.
4. Emit invite via activation link (ADR-0014).
5. Write `data_snapshot` capturing the entire seeded state (for the compliance officer of that tenant to see what they started with).
6. Return a summary to the platform admin.

Callable from the platform-admin UI (§4) and from a CLI (`python -m app.platform.provision --name "Customer X" --admin-email ...`).

### 2.3 `TenantArchiver`

Marks a tenant as `ARCHIVED`. All reads still work; every write refused with `410 TENANT_ARCHIVED`. Data stays for the retention period. Called only by platform admins, and only after a 30-day "no writes" grace window (protects against accidental archival).

## 3. New tables

Minimal — most work happens in policies + code.

| Table | Purpose |
|---|---|
| `platform_admin` | Users with the platform role. Every row + revocation logged in `audit_event`. |
| `break_glass_session` | Time-boxed cross-tenant access grants — reason, granted_by, expires_at, revoked_at. |
| `tenant_status_history` | Every ACTIVE → SUSPENDED → ARCHIVED transition, with actor + reason. |

Existing `tenant` table grows two columns: `status` (`ACTIVE|SUSPENDED|ARCHIVED`), `data_residency` (`UK|EU|US`).

## 4. Platform admin — a new persona

Held by our staff only. Never granted to a user inside a customer tenant. Sits **outside** the tenant hierarchy — a platform admin sees a list of tenants and can act on any (subject to break-glass).

| Page | Purpose |
|---|---|
| `/platform/tenants` | Every tenant with status + last-active-user timestamp |
| `/platform/tenants/new` | Wizard (§2.2) — name, base currency, legal entities, first admin email, data residency |
| `/platform/tenants/{id}` | Read-only tenant profile + break-glass button |
| `/platform/audit` | Cross-tenant audit trail of platform-admin actions only |

**Break-glass button** on the tenant profile opens a modal: reason (mandatory, min 20 chars), duration (max 60 min). On submit:
- `break_glass_session` row written.
- Platform admin's next request is issued with `SET LOCAL app.tenant_id = '<that-tenant>'`.
- Every request in that session is tagged in `audit_event` with `platform_admin_action=true` and the session id.
- Notification: every ADMIN in the affected tenant gets an email saying "Fusion Practices staff accessed your data at 14:03 for reason: X". (P2-03 SMTP delivery required.)

## 5. Per-tenant secrets

Every tenant's third-party credentials (Oracle IDCS service account, Xignite API key, SMTP credentials, HSM key ref) live at `secrets://<tenant_id>/<name>` in the vault. The `SecretsPort.get(name, tenant_id=None)` grows a `tenant_id` argument — the current tenant context resolves it if not passed.

Cross-tenant secret access is impossible except via break-glass.

## 6. Data residency

At provisioning time, `data_residency` is set on the tenant. Every long-running deployment is region-fixed — a UK tenant's connection string reaches a UK-region Postgres cluster, its vault is UK-region, its outbound LLM calls go to UK-region OCI Gen AI or Azure OpenAI UK South.

**Implementation:** a UK tenant's `TREASURY_DATABASE_URL` is UK-only. There is no single global connection string in multi-tenant production. The `DatabaseRouter` picks the right pool per-tenant based on `data_residency`.

Practical shape: probably starts as one deployment per region, each hosting one or more tenants. Cross-region is a separate deployment, separate ops rotation, separate compliance boundary.

## 7. Test strategy — the load-bearing part

The whole plan collapses without these tests. Every one is a hard gate.

### 7.1 The RLS invariant tests
- `test_every_non_exempt_table_has_rls_policy` — enumerate `information_schema.tables`, assert every one is in the `RLS_EXEMPT` list OR has an active RLS policy.
- `test_every_rls_policy_references_app_tenant_id` — parse policies, assert the predicate names `app.tenant_id`.

### 7.2 The cross-tenant leak tests
- `test_tenant_A_cannot_see_tenant_B_deals` — provisioner spins up two tenants, seeds one deal per tenant, tenant A makes every read endpoint call, none returns tenant B's deal.
- `test_forgetting_tenant_context_returns_zero_rows` — issue a request with no `SET LOCAL app.tenant_id` — every query returns empty; nothing 500s.
- One test per subject_type: `test_cross_tenant_isolation_on_<subject>` — deal, hedge, counterparty, ai_run, audit_event, exception_item, cash_balance, etc. Auto-generated over a table list, one test per row.

### 7.3 The break-glass tests
- Opening a session writes a `break_glass_session` row + one `audit_event` for the grant.
- Every request during the session is tagged `platform_admin_action=true`.
- On expiry (or manual revoke) the next request is refused.
- Every ADMIN in the affected tenant receives an email.

### 7.4 The provisioner tests
- Provisioner is idempotent — running it twice with the same tenant name is a no-op.
- Provisioner's `data_snapshot` captures every seeded row.
- Provisioning a UK tenant lands on the UK Postgres cluster, not the EU one.

## 8. Stages

Sequenced so each is a hard gate — no stage lands until the previous one's tests are green.

### Stage 1 — Postgres RLS foundation (~3 days)
Everything from §1 + §2.1 + the invariant tests (§7.1, §7.2). No new UI. SQLite dev flow unchanged.

**DoD:** every table has a policy; leak tests pass; running with `TREASURY_DATABASE_URL=postgres://…` refuses reads without a tenant context.

### Stage 2 — Tenant provisioning API (~2 days)
Provisioner (§2.2), archiver (§2.3), `platform_admin` + `tenant_status_history` + `break_glass_session` tables. Backend only.

**DoD:** `python -m app.platform.provision --name "Customer X" --admin-email x@…` creates a fully-functional new tenant that the invitee can sign into. Provisioner idempotent.

### Stage 3 — Per-tenant secrets (~1 day)
`SecretsPort.get(name, tenant_id=None)`. `AzureKeyVaultAdapter` uses per-tenant vault paths. Env-var adapter refuses `tenant_id != None` (dev doesn't need it).

**DoD:** Two tenants each with their own Oracle service account key; neither can read the other's.

### Stage 4 — Platform admin UI (~3 days)
The four pages in §4. Break-glass modal + notification path.

**DoD:** A platform admin can list tenants, provision a new one via wizard, and break-glass into an existing one — with every step audited and every ADMIN in the affected tenant notified.

### Stage 5 — Data residency wiring (~2 days)
`DatabaseRouter` selects the pool per-tenant. Provisioner refuses if the region isn't configured. LLM adapter picks the region-appropriate endpoint per call.

**DoD:** A UK tenant's writes hit UK Postgres; an EU tenant's writes hit EU Postgres; a test proves no cross-region query.

**Total effort:** ~2 weeks solo dev after Postgres already lands (P0-01, shipped).

## 9. Config knobs introduced

| Env var | Purpose |
|---|---|
| `PLATFORM_ADMIN_ALLOWED_SUBJECTS` | Comma-separated IdP subject ids that may claim the platform role. Cannot be granted through UI — this is the sole way in. |
| `BREAK_GLASS_MAX_DURATION_MINUTES` | Default 60. Hard cap. |
| `TENANT_ARCHIVE_GRACE_DAYS` | Default 30. Time between "SUSPEND" and "ARCHIVE" transition. |
| `RLS_EXEMPT_TABLES` | Read-only allow-list from code; only ADR-documented tables. |

## 10. What this plan is NOT

- **Not a customer-visible feature.** Customers never see multi-tenancy. The tenant is invisible from within the app.
- **Not a rewrite of any Phase 1 code.** RLS is orthogonal — the service-layer `WHERE tenant_id = ?` stays for the SQLite path and belt-and-braces on Postgres.
- **Not schema-per-tenant.** Considered and rejected in §Q-002. The abstraction stays compatible; a future customer whose regulator demands physical isolation gets their own database, not their own schema.
- **Not "multi-region"** in the horizontal-scaling sense. Data residency = one deployment per region; not eventual consistency across regions.
- **Not tenant self-provisioning.** Customers don't sign up on a website; a Fusion Practices salesperson signs a contract and a platform admin provisions the tenant.

## 11. Unpark instructions

When the plan lands:
1. Read this document + `.context/roadmap.json` (P0-01 Postgres readiness is a prerequisite — already shipped).
2. Verify Q-002 in `.context/open-questions.json` says "resolved: shared schema + RLS" or update it.
3. Start at Stage 1. Every stage's DoD gates the next.

## 12. Related decisions

- **ADR-0018** — Postgres-ready. Prerequisite.
- **A future ADR-0019** — will capture Q-002's resolution when Stage 1 lands.
