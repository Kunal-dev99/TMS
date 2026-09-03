# Treasury Register

A control system, not a register. It decides whether a deal is allowed to
happen and keeps testing that decision as the world changes.

Built against the five design documents in `Design Documents/`. Where this
code and documents 1 to 4 disagree, the documents win.

- Document 1, data model. Thirty-three tables in eight subject areas.
- Document 2, application programming interface. Forty-four endpoints.
- Document 3, user interface. One surface, five strip items.
- Document 4, architecture. Six containers, thirteen services.
- Document 5, phased execution plan. Five phases, three workstreams.

`docs/ASSUMPTIONS.md` records every decision taken where the documents left
something open or contradicted themselves. Read it before phase one.

---

## Running it

Prerequisites: Python 3.13, Node 24, and `pip install -r backend/requirements.txt`.

Double click **`start-all.bat`**, or run it:

```bash
start-all.bat
```

It builds the schema from the migrations, loads the seed if there is no
database, opens one window for the API and one for the surface, waits for
each to answer rather than guessing at a sleep, and opens the browser at
http://localhost:3000.

```bash
start-all.bat real         read the real API on 8000 instead of the mock
start-all.bat mock 3100    serve the surface on another port
stop-all.bat               free the ports if a window was killed rather than closed
```

The two halves also run on their own, which is what you want while working
on one of them:

```bash
start-backend.bat          the mock on 8001, migrations and seed first
start-frontend.bat         the surface on 3000, reading the mock
```

`start.ps1` and `start.sh` do the same in one window, for PowerShell and for
a POSIX shell.

---

## Where things are

```
backend/
  app/
    models.py        SQLAlchemy, the fifteen phase one tables
    seed_data.py     the seeded book, read by the seeder and the fixtures
    measurement.py   how a deal is measured. One implementation
    errors.py        thirty-eight codes, each with its status
    formatting.py    money into sentences, for server composed messages
    db.py            engine, session, WAL on connect
    main.py          the real application, handlers and ten routers
    schemas/         the contract. Response models and request bodies
    api/             ten routers. Groups 1, 2, 5, 6 and admin are live
    services/        eight services. The rule engine and every decision
    repo/            every query. policy, counterparties, deals, oracle, evidence
  alembic/           migrations. 0001 empty, 0002 the phase one schema
  seed/seed.py       loads the book
  mock/              the mock server and its fixtures
  tests/             exit criteria and the phase one test gate, as tests
frontend/
  app/               the surface, layout and the design tokens
  components/        Header, Book, Blotter, CheckPanel, Strip
  lib/               format, api, types
docs/ASSUMPTIONS.md
```

---

## The rule that is not negotiable

No rule lives in more than one place.

There is one CheckEngine. The browser has no copy of it, the mock server has
no copy of it, and the advisory layer has no copy of it. A frontend that
computes headroom to colour a bar has introduced a second implementation of
the limit arithmetic, and the two will disagree the first time a threshold
changes.

Where the frontend needs a number it does not have, the answer is a field on
the response, not a calculation in the client.

This is enforced by reading the code at the end of every phase, not by a
test.

---

## Progress

| Phase | Scope | State |
|---|---|---|
| 0 | Foundations: repository, migrations, seed, contract, mock server, shell | **Done** |
| 1 | The control loop. The demonstration | **Done. 23 endpoints, six panels, run sheet end to end** |
| 1.5 | Identity. Users, roles, bearer token, segregation of duties | **Done. All three exit criteria pass** |
| 2 | Accrual, journals, the nightly job, the advisory harness | **Done. Both exit criteria pass** |
| 3 | Confirmation, matching, amendment, settlement, currency, hedging | Not started |
| 4 | PostgreSQL, real tenancy, real adapters, deployment | Not started |

### Phase 0 exit criteria

- [x] `alembic upgrade head` builds every phase one table from empty
- [x] The seed loads and the book opens with no counterparty in breach
- [x] The mock server answers all forty-four endpoints of document 2
- [x] The frontend shell renders against the mock with no backend running
- [x] One command starts everything

### Phase 1, the day nine test gate

Document 5 puts three assertions before the surface exists. If they pass, the
demonstration works. All three pass.

- £10,000,000 with Northern Bank plc fails the group limit and passes the
  entity limit, at £28,119,836 against £25,000,000, and offers £6,880,164 as
  the amount that would fit
- An eighteen month deal fails the tenor band at BBB+, and nothing else
- A downgrade to BBB+ leaves a booked six month deposit inside the new
  £8,000,000 limit and outside the new three month term

### Phase 1, the control loop

All eight steps of the build sequence, and the twenty-two endpoints of
groups 1, 2, 5 and 6 replacing the mock:

| Step | Service | What it owns |
|---|---|---|
| 1 | ExposureCalculator | Measurement per instrument, entity, group and portfolio totals |
| 2 | CheckEngine | The six checks. Fails closed. Re-derivable from stored inputs |
| 3 | ApprovalRouter | Who signs, from the thresholds in the policy version |
| 4 | DealService | The only path that writes a deal. The control run |
| 5 | QueueService, BreachService | One queue, two causes. Breaches that do not clear |
| 6 | RetestService | A rating action, and the re-test it causes |
| 7 | OnboardingService | Four separately refusable steps |
| 8 | ExposureService | Utilisation by group, band and maturity bucket |

The demonstration run sheet from section 12 of document 3 runs as a test on
every merge.

**Performance budget**, measured against the seeded book:

| Path | Budget | Measured, p95 |
|---|---|---|
| `POST /deals/check` | 80 ms | 8 ms |
| `GET /state` | 300 ms | 11 ms |

**The surface**, at the anatomy document 3 sets out: header, book at 58 per
cent, ticket at 42, five strip items, panels over the surface. No second
navigation surface beside the strip, because section 2 makes that a limit
rather than a target.

- The ticket, five fields, debounced at 150 ms with in-flight requests
  cancelled
- The six checks, live, with the resize control the server computes
- The verdict, naming who signs before the deal is committed
- Six panels: exposure, queue, breaches, evidence, onboarding, ratings and
  policy. One open at a time, escape closes, focus returns to whatever
  opened it

The whole run sheet has been driven through the interface: type ten million
with Northern Bank plc, five green and one red, resize to £6,880,164, record,
downgrade to BBB+, and the breaches panel opens itself because the result is
the reason the user pressed it.

### Phase 1.5, identity

The largest single gap in the design, closed. Document 5 sets three exit
criteria and all three pass:

- [x] No endpoint accepts an actor in a request body
- [x] A user cannot approve a deal they proposed
- [x] Every evidence record names a user identifier rather than typed text

Two tables, three endpoints, and a bearer token. Signing also re-runs the six
checks, because a deal proposed in the morning and signed in the afternoon
has sat outside the gate in between.

**Three prototype accounts**, password `treasury`:

| Person | Holds | Signs |
|---|---|---|
| A. Whitfield | Analyst | up to the analyst threshold |
| M. Doran | Head of Treasury, Analyst | up to the second threshold |
| R. Sethi | CFO | above it |

Seeing the control needs two of them: propose as one, sign as the other.

### Phase 2, accounting and advisory

Ten tables, ten endpoints, and the order inside the phase that matters:
accrual first, because the advisory layer reads live positions and a stale
accrual mis-states the ladder it is measuring a gap against.

- [x] The nightly job runs twice for one date and writes accruals once
- [x] A recommendation that fails validation still appears, with the rule
      based pick flagged as such and only the explanation lost
- [x] Accepting a recommendation produces a deal that carries a check run
      identical in shape to a typed deal

**Accounting.** One accrual row per deal per day, stored rather than
recomputed, with each day written as the difference between the interest
accrued to that day and the day before. The cumulative on any row therefore
equals what the exposure calculator measures on the same date, by
construction. Journals are built nightly and posted on demand, idempotent per
journal.

**The advisory layer.** Six stages, one of which calls a model:

| Stage | Kind | What it guarantees |
|---|---|---|
| 1 Assemble context | Deterministic | Built by query. Nothing is retrieved |
| 2 Detect the gap | Deterministic | With no gap the model is never called |
| 3 Build candidates | Deterministic | **The main guardrail.** Anything failing the six checks is excluded before the list exists |
| 4 Rank and explain | The model | An identifier and prose. Never a number |
| 5 Validate | Deterministic | Three tests, all of which must pass |
| 5b Rule based pick | Fallback | Flagged as such. Degrades rather than fails |
| 6 Accept or edit | Human | Records a decision. **Books nothing** |

### The model

Stage 4 calls Groq when a key is configured, and a stub when it is not. The
guardrails do not move either way.

```bash
cp backend/.env.example backend/.env    # then fill in the key
python -m app.config                     # says what is set, prints no secrets
```

| `model_enabled` | Key set | What runs |
|---|---|---|
| off | either | Weighted score. The policy switch wins |
| on | no | The stub. The prototype works with nothing set up |
| on | yes | Groq, `openai/gpt-oss-120b` by default |

A model that invents a figure, names a candidate from another run, or does
not answer at all ends the same way: the deterministic pick, flagged
`RULE_FALLBACK` on screen, with only the explanation lost.

Secrets come from the environment. `backend/.env` is gitignored and is the
only place a key should be written. **Set `TREASURY_TOKEN_SECRET` anywhere
that is not a laptop** — it falls back to a development constant.

```bash
cd backend && python -m pytest tests/ -q
```

Two hundred and fifteen tests.
