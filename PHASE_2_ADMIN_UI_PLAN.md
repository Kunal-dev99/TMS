# Phase 2 — Admin UI Plan (parked)

> **⛔ PARKED — ENFORCED.** This plan's parked status is enforced by
> `backend/tests/test_parked_plans.py` reading `PARKED_PLANS.json`
> (plan id `phase_2_admin_ui`). Creating any of the forbidden files
> or symbols listed there fails CI with a clear error naming this
> plan. To start building, first change `status: "parked"` →
> `"unparked"` in `PARKED_PLANS.json` **as its own commit** — the
> diff is the audit trail.

**Status:** parked. Not started.
**Companion to:** `PHASE_2_IMPLEMENTATION_PLAN.md` (Stages 4/7/9 introduce data that needs UI).
**Purpose:** the admin-facing surfaces the Phase 2 substrate makes necessary. Without them, every mapping change is a `INSERT INTO ...` DB edit — not enterprise-acceptable.

## Anchor

Three things Phase 2 introduces need an admin edit surface, not code deploys:

1. **Oracle mapping tables** (`oracle_entity_mapping`, `gl_account_map`) — decide where money-movement journals land in the customer's Oracle chart of accounts. Getting this wrong posts to the wrong ledger; a customer needs to fix it in minutes, not a release cycle.
2. **SSO group mapping** (`sso_group_map`) — decides which IdP group grants which role. Getting it wrong grants CFO to the wrong person. Customer admin needs to fix it immediately.
3. **Integration Health** (`integration_health`) — read-only ops surface. Answers "is the ERP feed alive?" without a shell into the box.

**Enterprise-grade rule:** every write to (1) or (2) is treated like a `policy_version` edit — versioned, audited, and gated by four-eye control (ADR-0015). Nothing about these tables can change silently.

## Rules that hold across every admin surface here

- **Every write** produces:
  - a row in `audit_event` (naming actor, before, after)
  - a snapshot in `data_snapshot` (so a compliance officer can replay 'what did this mapping say on 12 May?')
  - a four-eye request in `access_change_request` when the change routes money or grants access — see the per-page table below for which classes of edit are sensitive
- **Every read** is gated by a permission, never by role name.
- **Every table** is CSV-importable + CSV-exportable so implementation teams and auditors don't screen-scrape.
- **Every edit form** shows the current effective value + the pending queued change (if a four-eye request is open) so a second admin knows what they're approving.

---

## 1. New permissions (additive to `permissions.py`)

| Permission | Grants |
|---|---|
| `MANAGE_INTEGRATIONS` | Read + write Oracle mapping tables + SSO group map. Held by ADMIN. Never by ANALYST. |
| `VIEW_INTEGRATION_HEALTH` | Read-only integration_health. Held by ADMIN + COMPLIANCE_OFFICER + CFO. |

Every existing permission unchanged.

## 2. New endpoints

Prefix `/admin/integrations` throughout, one router.

| Endpoint | Purpose | Guard |
|---|---|---|
| `GET  /admin/integrations/oracle-entities` | List `oracle_entity_mapping` for this tenant | `MANAGE_INTEGRATIONS` |
| `POST /admin/integrations/oracle-entities` | Propose a new mapping (queues an `access_change_request` since it changes money-flow config) | `MANAGE_INTEGRATIONS` |
| `PATCH /admin/integrations/oracle-entities/{id}` | Propose an update — same four-eye | `MANAGE_INTEGRATIONS` |
| `DELETE /admin/integrations/oracle-entities/{id}` | Propose removal — same four-eye | `MANAGE_INTEGRATIONS` |
| `POST /admin/integrations/oracle-entities/import.csv` | Bulk import; each row still queues a four-eye request | `MANAGE_INTEGRATIONS` |
| `GET  /admin/integrations/oracle-entities.csv` | Export | `MANAGE_INTEGRATIONS` |
| (same shape for `gl-account-map`) | | |
| (same shape for `sso-group-map`) | | |
| `GET  /admin/integrations/health` | Every adapter's last-success / last-error / consecutive failures | `VIEW_INTEGRATION_HEALTH` |
| `POST /admin/integrations/health/{port}/{provider}/test` | On-demand health ping (calls the adapter's `ping()` method) | `MANAGE_INTEGRATIONS` |

**Every write endpoint** returns `202` when it queued a four-eye request, `200` when it applied directly (e.g. reading, or non-sensitive edits — none in scope for these three tables). The frontend reads the response and either shows "queued for approval by another admin" or "applied".

## 3. New adapter method (extends `ports.py`)

Every adapter grows one method:

```python
class HasPing(Protocol):
    def ping(self) -> HealthResult: ...

@dataclass(frozen=True)
class HealthResult:
    ok: bool
    latency_ms: int
    detail: str  # human-readable; error message on failure
```

`registry.get(ports.ERPPort).ping()` returns whether the Oracle service account can reach `/fscmRestApi/resources/latest/ledgers`. The `POST .../health/{port}/{provider}/test` endpoint calls it and returns the result live.

## 4. New frontend surfaces

Under `/admin` — the existing Admin page grows a tab bar (which it doesn't have today; the current page is a single stack).

| Tab | Route | Component | Notes |
|---|---|---|---|
| People (existing) | `/admin` (default) | current admin page | Unchanged. |
| Oracle mappings | `/admin/oracle` | `_oracle_mappings.tsx` | Two side-by-side tables: business unit → legal entity, and event-kind + LE + currency → account combination. Row-level edit + a CSV import/export toolbar. |
| SSO mappings | `/admin/sso` | `_sso_mappings.tsx` | Group claim → role. Same shape. |
| Integrations | `/admin/health` | `_integration_health.tsx` | Adapter grid with green/amber/red, "test now" button per row, last-error banner. |

**Every edit form** shows the pending four-eye state inline: "Change to `01-100-4550-…` is queued for approval by another admin. Requested 12:03 by R. Sethi." No admin can accept their own edit — the four-eye control from Phase 1 (ADR-0015) handles it. New table on `access_change_request.subject_type`: `integration_mapping`, `sso_group_map`.

## 5. Stages

### Stage 1 — Permissions + audit shape (~half day)
Add `MANAGE_INTEGRATIONS` and `VIEW_INTEGRATION_HEALTH` to `permissions.py`. Add `subject_type = "integration_mapping"` and `"sso_group_map"` to `access_change_service`. New audit action codes: `integration.mapping.proposed`, `.approved`, `.rejected`.

**DoD:** unit tests confirming the new permissions gate correctly + audit codes register.

### Stage 2 — Oracle mapping admin (~1.5 days)
Backend endpoints + frontend `_oracle_mappings.tsx`. Every write queues a four-eye request; every apply writes the snapshot + the audit row.

**DoD:** an admin can add a mapping row, see it as "pending", a second admin approves it, it lands in `oracle_entity_mapping` — and there is a `data_snapshot` row + two `audit_event` rows (proposed + approved) tracing the whole flow.

### Stage 3 — SSO mapping admin (~1 day)
Same shape as Stage 2 for `sso_group_map`. Copy-paste + rename.

**DoD:** same test shape as Stage 2, plus one test that proves the mapping does NOT apply until approval — a user with the queued group claim gets no role until a second admin says yes.

### Stage 4 — Integration Health page (~1 day)
Reads `integration_health` + on-demand `ping()` calls. Green/amber/red per adapter, per tenant when applicable.

**DoD:** page renders every configured adapter, "test now" hits the real adapter and returns latency + status within 30s.

### Stage 5 — CSV import + export (~half day, per table)
Each mapping table's import + export. Rows still queue four-eye requests; a bulk import produces one `access_change_request` per row (or a single batch — TBD in the ADR).

**DoD:** an implementation team can import 100 GL account mappings from a CSV, all 100 are queued, a second admin approves them in one bulk action.

## 6. Config knobs introduced

None. Every new capability is admin-driven; no env var flips the UI on/off. `PORT_PING_TIMEOUT_MS` (default 5000) is the only new tuning knob.

## 7. Test strategy

- **Unit** — every endpoint under `/admin/integrations` has a contract test.
- **E2E** — one journey test: propose mapping → open a second signer session → approve → assert the mapping is in force → assert the audit trail lists both actors.
- **Isolation** — cross-tenant test: admin from ten_A cannot see ten_B's mappings even via direct SQL enumeration through the API.
- **Negative** — proposer cannot approve their own request (SEGREGATION_OF_DUTIES).

## 8. What this plan is NOT

- Not a general-purpose "connector configuration" surface. Env vars still bind adapters; this UI is for **data** the adapters need (mappings + health), not for **wiring** them.
- Not a rewrite of the `access_change_request` flow — it reuses it exactly, only adding two new `subject_type` values.
- Not a place to edit `policy_version` — that's a separate concern with its own future ADR (ADR-0017 already reserved the columns).

## 9. Unpark instructions

When the plan lands:
1. Read this document + `PHASE_2_IMPLEMENTATION_PLAN.md` Stage 4/7/9 sections (they name the tables + adapters this UI depends on).
2. Verify `oracle_entity_mapping`, `gl_account_map`, `sso_group_map`, `integration_health` all exist (they were shipped as Phase 2 Stage 2).
3. Start at Stage 1 of this plan. Ship in order.
