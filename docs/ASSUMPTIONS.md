# Assumptions, gaps and things the documents disagree about

Everything built so far follows documents 1 to 4, with document 5 for the
order of work. Where this file records a decision, it is a decision the
documents left open or contradicted themselves on. Each one is cheap to
reverse now and expensive to reverse after phase one.

Raise anything here that is wrong before phase one starts.

---

## 1. The phase one table count does not reconcile

Document 1 prose and document 5 both say **eighteen** tables in phase one,
twenty-six by phase two and thirty-three by phase three.

Document 1 section 2.1, which lists every table against its phase, gives:

| Subject area | Phase 1 | Phase 2 | Phase 3 |
|---|---|---|---|
| Tenancy and policy | tenant, policy_version, rating_band, system_clock | investment_policy, ladder_target, currency_cover_target | |
| Counterparty control | cp_group, counterparty, counterparty_instrument, cp_limit, rating_event | | |
| Dealing | deal | | confirmation, match_difference, amendment |
| Accounting and settlement | | accrual, journal | settlement |
| Control and evidence | check_run, exception_item, breach | | |
| Advisory | | forecast_line, advisory_run, candidate, recommendation, validation_result | |
| Currency risk | | | currency_exposure, hedge_link, fx_rate |
| Oracle boundary | oracle_balance, oracle_instruction | | bank_statement_line |
| **Total** | **15** | **10** | **8** |

Fifteen, then twenty-five, then thirty-three. The thirty-three agrees. The
phase split does not.

**Decision.** The itemised list wins over the prose, so phase one builds
**fifteen** tables. `alembic upgrade head` creates fifteen plus
`alembic_version`.

**What to confirm.** Whether three tables were meant to move into phase one,
and if so which three. The likely candidates are the investment policy trio,
but the advisory layer that reads them is phase two, so moving them forward
buys nothing.

---

## 2. Revision A is not in the pack

Documents 1 and 2 are revision B. Both say the revision A material is
unchanged and do not reproduce it. Three things were therefore reconstructed
rather than copied:

**a. Columns for eleven counterparty control tables.** `tenant`,
`rating_band`, `system_clock`, `cp_group`, `counterparty`,
`counterparty_instrument`, `cp_limit`, `rating_event`, `check_run`,
`exception_item` and `breach` are in `backend/app/models.py` as reconstructed
from the endpoints, the screens and the checks that read them. `deal` and
`policy_version` are copied from revision B, which does give them in full.

**b. Twenty-two of the thirty-eight error codes.** Revision B lists its
sixteen new codes verbatim. The other twenty-two in
`backend/app/errors.py` are inferred from the refusals the documents
describe. They are marked in the file.

**c. Ten of the shared response models.** `CheckResult`, `CheckOutcome`,
`BookRow`, `DealSummary`, `ExceptionItem`, `Breach`, `ExposureView`,
`LimitVersion`, `RatingBand` and `PolicyConfig` are named in revision B but
their fields are not restated. They are in
`backend/app/schemas/models.py` as reconstructed.

**This is the first thing to reconcile when revision A is to hand.** The
contract is the interface between two workstreams, and a field that changes
after the frontend has built against it is the most expensive change in the
plan.

---

## 3. The six checks are never enumerated

No document lists the six checks as a set. This enumeration is assembled from
screens 1, 2 and 4 of document 3, and the ordering puts the group check at
number four because screen 2 says so outright.

| # | Key | What it tests |
|---|---|---|
| 1 | `COUNTERPARTY_ACTIVE` | Approved and active, not draft, verified or suspended |
| 2 | `INSTRUMENT_PERMITTED` | This name is approved for this instrument |
| 3 | `ENTITY_LIMIT` | Measured exposure against the limit version in force |
| 4 | `GROUP_LIMIT` | The credit group total against the group limit |
| 5 | `TENOR_BAND` | The term against the maximum in force at this rating |
| 6 | `CONCENTRATION` | The group's share of the portfolio against the cap |

Check 6 is the one that fails closed without an Oracle balance, which matches
document 4's worked example.

---

## 4. Seed figures

Document 5 refers to "the seed data in section 8.1 of document 3". Document 3
revision B section 8.1 is the live check panel, not seed data. The seed is
therefore built to satisfy the figures the screens and the run sheet quote.

Every number below is in `backend/app/seed_data.py` and asserted in
`backend/tests/test_phase0.py`.

| Figure | Value | Where it comes from |
|---|---|---|
| Northern Treasury Services holding | £18,119,836 | Screen 2 and section 11 of document 3 |
| Northern group limit | £25,000,000 | Screen 2 |
| £10m attempt reaches | £28,119,836 | Screen 2 |
| Resize offers | £6,880,164 | Run sheet at 2:00 |
| Northern Bank limit, term | £15,000,000, 6 months | Screen 4 |
| After the BBB+ downgrade | £8,000,000, 3 months | Screen 4 |
| Advisory gap | £8,000,000 | Run sheet at 0:20 |
| Approver on the £8m deal | Head of Treasury | Run sheet at 1:05 |

The £18,119,836 comes out of £18,000,000 at 4.05 per cent over 60 days.
Interest is simple, actual over 365, rounded half up to the penny. Document 3
quotes the accrued figure as £119,835 in one place and the total as
£18,119,836 in another, which differ by a penny of rounding. The total is
the figure the group arithmetic depends on, so the total wins.

### The concentration cap is 5000 basis points, not 3000

A real treasury sets this nearer 30 per cent. It cannot be 30 per cent here.

The seeded book is five names and about £50,000,000. The Northern group limit
of £25,000,000 is by itself 46 per cent of that portfolio. Any cap below
about 47 per cent makes the group ceiling unreachable, and screen 2 stops
being five green and one red because concentration fails alongside the group
limit.

Three ways out, in order of preference:

1. **Leave it at 5000 and say so.** The cap is versioned policy data a
   customer owns, and the seed is illustrative.
2. **Grow the book.** Eight to ten counterparties and eight to ten deals
   supports a 30 per cent cap. It also breaks screen 1, which says five
   counterparties and four live deals.
3. **Lower the Northern group limit.** This changes £28,119,836, £25,000,000
   and £6,880,164, which are the three figures the demonstration turns on.

Option 1 is what is built. This needs a decision before the demonstration,
because a treasury audience will notice a 50 per cent concentration cap.

### Real institution names

Document 5 lists this as a decision needed before the demonstration and notes
that the group argument lands hardest with real group structures. The seed
uses invented names: Meridian, Caledonia, Northern, Harbour and Vale.
Northern Bank plc and Northern Treasury Services Ltd share the Northern
Group, which is the pair the whole demonstration rests on.

Document 5 section 5.1 quotes the three test gate assertions against Coutts,
Goldman and NatWest. Document 3 uses the Meridian and Northern names. The
shapes are identical and documents 1 to 4 win, so the Northern names are
built. Swapping in real names is a change to one file.

---

## 5. Decisions this build has taken, from document 5 section 12

| Decision | Taken | Why |
|---|---|---|
| Hard block or warn with an override | Both, as `policy_version.enforcement`, seeded to `HARD_BLOCK` | The recommendation in document 5, which removes it from the critical path. Settle it by flipping it on a failing deal in the room |
| Journal posting frequency | Not needed until phase two | |
| Prior period corrections | Not needed until phase three | |

---

## 6. Deliberately not built in phase zero

Not gaps. Scope.

- **No rules anywhere.** ExposureCalculator, CheckEngine, ApprovalRouter and
  the other ten services are phase one. `app/services/` holds the build
  order and nothing else.
- **No routers.** `app/api/` holds ten empty modules matching document 2
  section 9. They fill one group at a time in phase one, replacing the mock.
- **No identity.** Every actor is still a string in a request body. Every
  such field in `app/schemas/requests.py` is marked with the phase it goes
  in. Phase 1.5 is a gate, not a task inside phase two.
- **No accrual.** Stored accrual is phase two, so the blotter stage label
  reads `matures in n days` rather than `accruing`. `_stage` in
  `mock/fixtures.py` is the only thing that changes when it arrives.

---

## 7. One thing worth watching

`mock/fixtures.py` contains a single comparison that decides which of two
prepared check fixtures to return. It is marked, and it exists so the check
panel can be seen passing and failing before any backend exists.

It is not the rule engine and it must never grow into one. It goes the day
the group 2 routers replace the mock. If it ever needs a second comparison,
that is the signal the frontend is being built against mock behaviour rather
than against the contract.

---

# Phase 1 decisions

Added while building the control loop. Same rule: these are places the
documents left something open, or where building it surfaced a question the
design did not answer.

## 8. Recording and approving are two calls in one interaction

Document 3 section 8.2 says a deal on a pass "is recorded and approved in the
same interaction and a toast names the role that signed". Document 2 keeps
`POST /deals` and `POST /deals/{id}/approve` as separate endpoints, and
document 1 keeps `PROPOSED` and `ACTIVE` as separate statuses.

**Decision.** `POST /deals` writes the deal as `PROPOSED`, `POST /approve`
makes it `ACTIVE`, and the surface calls both from one button. One
interaction, two calls, and `ApprovalRouter` still means something.

**The consequence to know.** A proposed deal consumes no headroom until it is
approved. Two proposals could each pass and each be approved, and together
exceed a limit. SQLite allows one writer at a time so it cannot happen in
this build, and the honest fix is to re-run the checks inside `approve`. That
is a phase 1.5 change, made at the same time as the approver identity, so the
re-check and the segregation of duties land together.

## 9. Approving does not re-check, and the signer is the proposer

Both are named in document 4 section 10 and both wait for phase 1.5. The
toast names the role rather than a person, so the interface does not dress
the gap up as a control.

## 10. Balances are the latest feed on or before the clock date

The first version demanded a balance stamped with the clock date exactly.
Moving the clock forward in a demonstration then lost the Oracle balance,
the portfolio total had no denominator, and the concentration check failed
closed on every deal.

Document 4 states prior day balances as a boundary rather than a defect, so
`uninvested_cash_pence` now takes the most recent feed not after the clock
date, and still returns `None` when nothing has ever been fed.

**Still open.** How old is too old. Phase 4 adds an explicit stale threshold
and a visible warning; `latest_balance_date` is the hook it reads.

## 11. Responding to a breach does not lower the count

Document 3 says responding "does not clear the breach and does not change the
deal". The status moves to `RESPONDED` and there is no `CLEARED` state,
because nothing in phase one puts a position back inside policy. The strip
count therefore counts rows, not open rows. A count that fell on a response
would say the problem had gone away when only the conversation had.

## 12. Resolving a queue item cancels the deal it refused

`RESIZED` and `REROUTED` set the refused deal to `CANCELLED`, because the
client resubmits a smaller deal or books with a different counterparty.
Neither edits the deal that failed: a refused deal is evidence, and rewriting
it in place would lose the refusal.

`CORRECTED` and `CHALLENGED` belong to the confirmation cause and are refused
against a limit failure. They are reachable in phase three.

## 13. A downgrade resets a manual limit to the band

The seed's one manual limit above the band raises the question: what happens
to it on a downgrade. The re-test supersedes whatever is in force and writes
the band's figures.

The reasoning is that the band is the ceiling a rating entitles a name to, so
a downgrade takes the entitlement away whoever signed for the old one. The
old row survives, so a deal booked under it is still re-derivable.

**Worth confirming with the customer.** An alternative is to leave a manually
approved limit alone and flag it for re-approval. That is a policy question,
not a technical one.

## 14. The re-test excludes the position under test

A booked deal is already inside the held exposure. Re-testing it against a
total that includes it counts it twice, and every position looks like a
breach the moment anything is downgraded. `exclude_deal_id` threads through
`ExposureCalculator` and `CheckEngine` for this one purpose.

## 15. The frontend no longer uses plain CSS

Document 3 section 13 says "Plain CSS with the section 10 tokens as custom
properties. No utility framework." The surface has since been rebuilt on
Tailwind and shadcn with a sidebar and a card layout.

That is a deliberate change made outside the design documents, and it was
kept rather than reverted. The visual language is a preference; the structure
is not.

**What was changed back.** The reskin added a sidebar with six entries beside
the five item strip. Section 2 of document 3 caps navigation at one surface
and five strip items and calls that a limit rather than a target, so the
sidebar was removed and the documented anatomy restored: header, book at 58
per cent, ticket at 42, five strip items, panels over the surface. The
Tailwind and shadcn styling stayed.

**Still to confirm.** That `tailwind.config.ts` maps to the section 10 tokens
rather than to framework defaults. Those tokens are the contract between the
screens and the design, and a card that is the framework's grey rather than
`--card` is a small drift that gets larger.

## 16. Five panels, and the sixth entry that is empty

Document 5 schedules "panel shell and five panels" in phase one: exposure,
queue, breaches, evidence and onboarding. All five are built, plus the
ratings and policy panel, because the demonstration cannot apply a rating
action without it.

The advisory entry stays in the strip with an empty panel that says what will
be there. The alternative is an entry that appears in phase two and changes
the shape of the strip in front of an audience.

The currency tab inside the exposure panel is visible and empty for the same
reason, and because document 3 is explicit: hiding it would hide the
distinction it exists to make.

## 17. GET /exposure/counterparty is phase one, not phase three

Document 5 puts group 8 in phase three. Document 2 notes that
`GET /exposure/counterparty` was "renamed from GET /exposure", so it existed
in revision A and belongs to phase one; only the currency endpoints are new.
Document 4 agrees, putting the exposure panel at step 7 of the phase one
build sequence.

**Decision.** It is live. Twenty-three endpoints answer rather than the
twenty-two document 5 quotes, and the extra one is this.

---

## 18. A rating upgrade does not raise a limit

Found by accident while testing the exposure dial: a stray click upgraded
Harbour and Vale Bank from BBB+ to AA-, and the re-test raised its limit from
8,000,000 to the AA- band ceiling of 35,000,000, with `approved_by` set to
whoever recorded the upgrade.

Assumption 13 said a rating action resets the limit to the band. That is
right for a downgrade and wrong for an upgrade, and the asymmetry was not
noticed when it was written.

**Decision.** `RetestService` tightens and never widens. Amount and term are
each taken as the lower of what is in force and what the band allows, so a
rating that moves one without the other tightens only what tightened. An
upgrade leaves the limit alone, and the higher one has to be set through the
limit endpoint by somebody who signs for it.

A downgrade takes an entitlement away and is the world moving. An upgrade
grants headroom, and a limit nobody signed is not a control.

`backend/tests/test_rating_actions.py` covers both directions.

## 19. The seed opened with a latent term breach

The same test run surfaced a second defect. The Harbour and Vale forward was
seeded at six months against a three month limit, so the book opened with a
position outside its own term limit. Nothing showed it, because the phase
zero test only checked amounts, and it only appeared when something re-tested
the book.

The forward is now three months. The measure is the notional times the add on
either way, so no figure the demonstration turns on moved.

Two tests now assert the term as well as the amount on open. Amount and
duration are two independent constraints, and a seed that checks one of them
is a seed that half works.

## 20. The exposure dial

A rotating disc in the exposure panel whose sections are proportionate to
what is held: credit groups on the outer ring, the counterparties inside a
group on the inner one, laid across their parent's arc so a name holds the
same share of the group that the group holds of the portfolio.

It is navigation, and it is deliberately not **the** navigation. Section 2 of
document 3 caps the surface at one navigation surface and five strip items,
and a dial with sections and subsections beside the strip would be a second
one with two levels of depth. It sits inside a panel that was already one
click away, and it navigates the book rather than the application.

Two rules it keeps. Every figure comes from the server, and the wedge angles
are the only arithmetic in the file. And nothing depends on motion: the
selection is stated in the centre, in the readout and in the accessible name
of every wedge, and under reduced motion the rotation is instant.

Colour still means distance from a limit rather than identity, because
section 10 gives the palette its meanings and a categorical colour per group
would take one away. Groups are told apart by size and label; the hue only
moves as one approaches its ceiling.

**If it should be promoted to primary navigation, that is a change to the
navigation budget and worth arguing about explicitly rather than absorbing.**

---

# Phase 1.5 decisions

## 21. Two tables, and columns on everything else

Document 5 budgets two tables. `app_user` and `membership` are the two. The
table is `app_user` rather than `user`, because USER is reserved in
PostgreSQL and phase four should be a dialect change rather than a rename.

The third exit criterion, that every evidence record names a user identifier
rather than typed text, needed columns rather than tables: twelve nullable
foreign keys to `app_user` across the deal, the check run, the limit, the
queue item, the breach, the rating event, the counterparty and the
instruction. The display name stays beside each one, because a limit
approval reads as a person rather than as a primary key.

## 22. Tokens are signed, not stored

A session table would have been a third table. A signed token needs no
lookup on the request path, which the eighty millisecond check budget cares
about.

**The cost, stated rather than hidden.** A token cannot be revoked before it
expires, and they last twelve hours. That is the wrong trade for a product
and the right one for a prototype whose stated destination is Entra ID
single sign on. `POST /auth/logout` discards the token on the client and
says so in its response.

Passwords use PBKDF2 from the standard library rather than bcrypt or argon2,
for the same reason: adding a native dependency to something single sign on
will replace buys nothing.

The signing key comes from `TREASURY_TOKEN_SECRET` and falls back to a
development constant so the prototype starts with no setup. **Set it before
anything that is not a laptop.**

## 23. Three error codes the documents do not have

`NOT_AUTHENTICATED`, `ROLE_NOT_HELD` and `SEGREGATION_OF_DUTIES`. The
documents describe a system with no identity, so they cannot list these. The
catalogue is now 38 documented plus 3, and `errors.py` names both counts so
the reconciliation against document 2 still holds.

The mock server gained the three sign in endpoints for the same reason, so
the frontend's token handling has something to build against: 44 documented
plus 3. **The mock hands back a token and then ignores it.** It is a fixture
source, not a security boundary, and that is the one place it and the real
API deliberately do not match.

## 24. Signing re-runs the checks

Assumption 8 flagged this and said it would land with identity. It has. A
deal proposed in the morning and signed in the afternoon has sat outside the
gate in between, during which a rating can move or another deal can take the
headroom. Signing is the moment it goes on the book, so it is the moment
that has to be true, and the re-check excludes the deal itself from the held
total.

The refusal says the world moved rather than repeating the failed check, and
asks for the deal to be proposed again against the book as it now is.

## 25. The role on the request is a claim, not a rank

Signing names a role, and the signer must actually hold it. Holding CFO does
not let somebody sign as an analyst: they sign as CFO or not at all. The
amount then has to be within what that role may sign, which is the
comparison `ApprovalRouter` was written for in phase one and nothing checked
until now.

## 26. The surface no longer signs on the proposer's behalf

Before this phase, recording a deal and approving it were one button,
because the same string did both. Now the proposer cannot sign, so recording
leaves the deal proposed and the toast says who has to pick it up.

That opened a gap the moment it was built: a proposed deal had nowhere in
the interface to be signed. The deal panel now carries the signature, with
the refusal shown inline when the caller may not give it.

**The sign button is offered to everybody.** Whether this caller may sign is
the server's decision; hiding the button would be the client guessing at a
rule, and a guess that disagreed with the server would be worse than a
refusal the reader can act on.

## 27. Demonstration passwords are in the repository

Three seeded accounts share the password `treasury`, and the sign in screen
lists them. This is a prototype with a seeded book, and hiding them would
only mean somebody has to be told them out loud.

They go with the password field when single sign on arrives. **Nothing in
`seed_data.py` should ever be pointed at real data.**

---

# Phase 2 decisions

## 28. Exposure computes the accrual, it does not read it

Document 1 says exposure reads from the stored accrual rather than
recomputing. It does not, and the reason is worth stating.

Both numbers come from the same function. `AccrualService` writes each day as
the difference between the interest accrued to that day and to the day
before, both from `app.measurement`, so the cumulative on any row equals what
`ExposureCalculator` measures on the same date. They agree by construction,
and a test asserts it for every live position.

**Why not read the table.** Reading it would make exposure depend on the
nightly job having run. On a morning the job failed, every measured figure
would silently fall and every limit would look further away than it is.
Computing it fails safe; reading a stored value fails open, and a control
system must not understate an exposure because a batch job did not run.

The stored accrual is still what the ledger uses, which is the thing document
1 actually needs it for.

## 29. A forward accrues nothing

Interest accrues on deposits, money market funds and gilts. A forward is
revalued rather than accrued, and revaluation is a different journal type
that phase two does not build. `ACCRUING_INSTRUMENTS` names the three.

## 30. Journals are built nightly and posted on demand

Building is arithmetic against rows we own. Posting depends on somebody else
being reachable. They fail differently, so they are separate calls: the
nightly job builds, and `POST /journals/post` posts a period.

Posting is idempotent per journal rather than per batch, so a partial failure
leaves the successful entries posted and a retry posts only what did not
land. A failing adapter marks entries FAILED and retriable rather than losing
them.

**The account mapping is a table in a module**, not in the database. A
customer changing their chart of accounts is a configuration change worth a
migration rather than a screen.

**Still open, from document 5.** Posting frequency. Daily calculation is
required either way; daily, weekly or monthly posting is a volume and
reconciliation decision that needs the customer close process.

## 31. The gap is cash first, then the ladder

Cash above the liquidity buffer is a surplus and comes first, because money
sitting uninvested is the loudest gap. A ladder bucket below its target is
second, and it changes the term rather than the amount.

The seed is arranged so the gap comes out at the 8,000,000 the run sheet
quotes: 8,000,000 of cash plus 2,000,000 of forecast inflow, less a 2,000,000
buffer that has to stay available.

## 32. Candidates are priced from the rating band

A real desk quotes. `AdvisoryService` derives an indicative rate from a base
rate, a spread by rating and a spread by tenor, so every figure in a
recommendation comes from data the customer owns rather than from anywhere
else. The model never generates a rate, and stage 5 checks that every figure
in the prose matches one computed at stage 3.

**This is the thing to replace first with a real quote feed.** The mechanism
is right and the numbers are illustrative.

## 33. The model is a stub, and that is the point

`ModelRanker` picks the highest scoring candidate and writes prose about it,
which is what a working model would do most of the time. Everything that
makes the real call safe is already built around it: it receives a bounded
list from stage 3, returns an identifier from that list, and every figure in
its prose is checked against the candidate row.

Swapping in a real model is a change to one class behind the `Ranker`
interface. Nothing else in the code path changes, and the four failures
document 4 says are structurally impossible stay impossible.

The tests do not prompt a model and hope. They inject a ranker that invents a
figure, one that names a candidate from another run, and one that raises, and
assert the layer catches each and falls back.

## 34. The strip reaches the latest run even after a decision

Found by driving it: accepting a recommendation removes the card, and with it
the only route to the run that produced it. The run is still the evidence of
what was considered and what was refused.

`StateResponse` gained `advisory_run_id`, which is the latest run whether or
not it left a recommendation outstanding. The card is still absent once
somebody decides.

## 35. Ten tables, not eight

Document 5 says eight tables in phase two. Document 1 section 2.1 lists ten:
the investment policy trio, accrual and journal, and the advisory five. The
itemised list wins, as in assumption 1.

The running system now holds 27 tables: 15 from phase one, 2 from phase 1.5,
and 10 here.

## 36. A real model behind the Ranker interface

Stage 4 now calls Groq when a key is configured, and the stub when it is not.
Nothing else in the code path changed, which was the point of putting the
model behind an interface in the first place.

`ranker_for` reads two independent things:

| model_enabled | key configured | What runs |
|---|---|---|
| off | either | `WeightedScoreRanker`. The policy switch wins |
| on | no | `ModelRanker`, the stub. The prototype works with nothing set up |
| on | yes | `GroqRanker` |

The policy field wins over the environment. A key sitting in a deployment
must not turn the model back on for a customer who switched it off.

**What the model is allowed to return is unchanged**: one candidate
identifier from the list stage 3 built, and prose. The system prompt says so,
and the system prompt is not what enforces it. Stage 5 does, and it does not
trust the ranker at all. A model that invents a figure, names a candidate
from another run, answers with something unreadable, or does not answer, all
end the same way: the deterministic pick, flagged `RULE_FALLBACK` on screen,
with only the explanation lost.

**Temperature is 0.2.** This is an explanation of an arithmetic result rather
than a piece of writing, and the pick should not move between two runs of the
same book.

### An outage is not the same as being switched off

Found while wiring it. A model call that failed was being recorded as
`RULE_ONLY`, which is what a model switched off in the policy looks like. A
model that has been failing for a week would have been indistinguishable from
one nobody wanted.

`RULE_ONLY` now means the policy switched it off. A model that was asked and
did not answer is `MODEL_REJECTED_FALLBACK`, and the reason is logged.

### The model name is not a constant to trust

`llama-3.3-70b-versatile` was the name in the example and the key has no
access to it, which is a 404 rather than a warning. The default is
`openai/gpt-oss-120b`, which the key does reach, and `TREASURY_MODEL_NAME`
overrides it. **Check what a key can reach before changing the name.**

## 37. Secrets come from the environment, never from the repository

`app/config.py` reads `backend/.env` if it is present and never overrides a
variable already set, so a real deployment sets environment variables and has
no `.env` at all. `.env` is gitignored; `.env.example` documents the
variables with no values in it.

`python -m app.config` prints what is set without printing any secret.

Two variables matter and both have unsafe defaults for convenience:

- `TREASURY_TOKEN_SECRET` falls back to a development constant. **Set it
  anywhere that is not a laptop.**
- `TREASURY_MODEL_API_KEY` absent means the stub runs, which is a safe
  default rather than a broken one.

**The tests never reach the network.** An autouse fixture clears the key, so
a developer with one in their environment does not have a suite whose result
depends on somebody else's endpoint being up. The tests that care about model
behaviour inject a ranker instead.
