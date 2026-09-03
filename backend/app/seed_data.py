"""The seeded book.

One module, read by two callers: the database seeder (seed/seed.py) and the
mock server's fixture builder (mock/fixtures.py). They agree on every figure
because they read the same constants, which is the whole point of putting
them here rather than in either one.

Money is integer pence throughout. Rates are integer basis points.
Dates are ISO 8601 text, because SQLite has no date type.
"""

from datetime import date, timedelta

# --------------------------------------------------------------------------
# Clock
# --------------------------------------------------------------------------

CLOCK_DATE = "2026-09-03"
_TODAY = date.fromisoformat(CLOCK_DATE)


def days_ago(n: int) -> str:
    return (_TODAY - timedelta(days=n)).isoformat()


def months_after(iso: str, months: int) -> str:
    d = date.fromisoformat(iso)
    y, m = divmod(d.month - 1 + months, 12)
    return date(d.year + y, m + 1, min(d.day, 28)).isoformat()


P = 100  # pence in a pound

TENANT_ID = "ten_demo"
TENANT_NAME = "Northgate Group Treasury"

# --------------------------------------------------------------------------
# Treasury policy
# --------------------------------------------------------------------------
#
# concentration_cap_bp is 5000 rather than the 3000 a real treasury would set.
# The seeded book is five names and roughly 50,000,000, so the Northern group
# ceiling of 25,000,000 is itself 46 per cent of the portfolio. Any cap below
# about 47 per cent would make that ceiling unreachable, and the screen where
# five checks pass and only the group check fails would become two failures.
# The cap is versioned policy data the customer owns, so this is a seed choice
# rather than a design one. See docs/ASSUMPTIONS.md.

POLICY_VERSION = {
    "id": "pol_v1",
    "tenant_id": TENANT_ID,
    "effective_from": "2026-01-01",
    "superseded_at": None,
    "concentration_cap_bp": 5000,
    "threshold_analyst_pence": 1_000_000 * P,
    "threshold_hot_pence": 10_000_000 * P,
    "enforcement": "HARD_BLOCK",
    "fx_add_on_bp": 1000,
    "approved_by": "Group CFO",
}

# --------------------------------------------------------------------------
# Rating bands
# --------------------------------------------------------------------------
# ordinal ascends with credit quality, so a downgrade is a fall in ordinal.

RATING_BANDS = [
    # id, rating, ordinal, max_limit_pence, max_tenor_months
    ("rb_aaa", "AAA", 9, 50_000_000 * P, 24),
    ("rb_aa", "AA", 8, 40_000_000 * P, 24),
    ("rb_aam", "AA-", 7, 35_000_000 * P, 24),
    ("rb_ap", "A+", 6, 20_000_000 * P, 12),
    ("rb_a", "A", 5, 18_000_000 * P, 12),
    ("rb_am", "A-", 4, 15_000_000 * P, 12),
    ("rb_bbbp", "BBB+", 3, 8_000_000 * P, 3),
    ("rb_bbb", "BBB", 2, 5_000_000 * P, 3),
    ("rb_bbbm", "BBB-", 1, 3_000_000 * P, 3),
    ("rb_sub", "BB+", 0, 0, 0),
]

# --------------------------------------------------------------------------
# Credit groups
# --------------------------------------------------------------------------
# The group limit is the ceiling for the whole credit, and it is the only
# thing that connects Northern Bank plc to Northern Treasury Services Ltd.

CP_GROUPS = [
    # id, name, group_limit_pence
    ("grp_meridian", "Meridian Group", 25_000_000 * P),
    ("grp_caledonia", "Caledonia Group", 30_000_000 * P),
    ("grp_northern", "Northern Group", 25_000_000 * P),
    ("grp_harbour", "Harbour and Vale Group", 8_000_000 * P),
]

# --------------------------------------------------------------------------
# Counterparties
# --------------------------------------------------------------------------

COUNTERPARTIES = [
    {
        "id": "cp_meridian",
        "group_id": "grp_meridian",
        "name": "Meridian Bank plc",
        "lei": "213800MERIDIAN000001",
        "group_parent": "Meridian Group Holdings plc",
        "country": "GB",
        "rating": "A+",
        "rating_status": "STABLE",
        "status": "ACTIVE",
        "instruments": ["DEPOSIT", "MMF"],
    },
    {
        "id": "cp_caledonia",
        "group_id": "grp_caledonia",
        "name": "Caledonia Trust Bank",
        "lei": "213800CALEDONIA00001",
        "group_parent": "Caledonia Trust Holdings Ltd",
        "country": "GB",
        "rating": "AA-",
        "rating_status": "STABLE",
        "status": "ACTIVE",
        "instruments": ["DEPOSIT", "GILT", "MMF"],
    },
    {
        "id": "cp_nts",
        "group_id": "grp_northern",
        "name": "Northern Treasury Services Ltd",
        "lei": "213800NORTHERNTS0001",
        "group_parent": "Northern Group plc",
        "country": "GB",
        "rating": "A-",
        "rating_status": "STABLE",
        "status": "ACTIVE",
        "instruments": ["DEPOSIT"],
    },
    {
        "id": "cp_northern",
        "group_id": "grp_northern",
        "name": "Northern Bank plc",
        "lei": "213800NORTHERNBK0001",
        "group_parent": "Northern Group plc",
        "country": "GB",
        "rating": "A-",
        "rating_status": "STABLE",
        "status": "ACTIVE",
        "instruments": ["DEPOSIT", "FX_FORWARD"],
    },
    {
        "id": "cp_harbour",
        "group_id": "grp_harbour",
        "name": "Harbour and Vale Bank",
        "lei": "213800HARBOURVALE001",
        "group_parent": "Harbour and Vale Holdings Ltd",
        "country": "GB",
        "rating": "BBB+",
        "rating_status": "STABLE",
        "status": "ACTIVE",
        "instruments": ["FX_FORWARD", "DEPOSIT"],
    },
]

# --------------------------------------------------------------------------
# Limits in force
# --------------------------------------------------------------------------
# cp_nts carries a manual limit of 20,000,000 pounds against a band ceiling
# of 15,000,000 at A-. Without it the book opens with an 18,119,836 position
# already in breach of its own limit, which is the one thing the seed must
# not do.

CP_LIMITS = [
    {
        "id": "lim_meridian_1",
        "counterparty_id": "cp_meridian",
        "amount_pence": 20_000_000 * P,
        "max_tenor_months": 12,
        "source": "BAND",
        "effective_from": "2026-01-05",
        "approved_by": "Head of Treasury",
        "reason": "Band limit at A+.",
    },
    {
        "id": "lim_caledonia_1",
        "counterparty_id": "cp_caledonia",
        "amount_pence": 25_000_000 * P,
        "max_tenor_months": 24,
        "source": "BAND",
        "effective_from": "2026-01-05",
        "approved_by": "Head of Treasury",
        "reason": "Band limit at AA-, held below the band ceiling.",
    },
    {
        "id": "lim_nts_1",
        "counterparty_id": "cp_nts",
        "amount_pence": 20_000_000 * P,
        "max_tenor_months": 12,
        "source": "MANUAL",
        "effective_from": "2026-02-11",
        "approved_by": "Group CFO",
        "reason": (
            "Manual limit above the A- band ceiling of 15,000,000, approved "
            "on the strength of the group parent."
        ),
    },
    {
        "id": "lim_northern_1",
        "counterparty_id": "cp_northern",
        "amount_pence": 15_000_000 * P,
        "max_tenor_months": 6,
        "source": "MANUAL",
        "effective_from": "2026-01-05",
        "approved_by": "Head of Treasury",
        "reason": "Band amount at A-, term held at 6 months.",
    },
    {
        "id": "lim_harbour_1",
        "counterparty_id": "cp_harbour",
        "amount_pence": 8_000_000 * P,
        "max_tenor_months": 3,
        "source": "BAND",
        "effective_from": "2026-03-02",
        "approved_by": "Head of Treasury",
        "reason": "Band limit at BBB+.",
    },
]

# --------------------------------------------------------------------------
# The four live deals
# --------------------------------------------------------------------------
# The Northern Treasury Services position is the one the group check is
# about. 18,000,000 at 4.05 per cent for 60 days measures 18,119,836, and
# 25,000,000 less that figure is the 6,880,164 resize in the run sheet.

DEALS = [
    {
        "id": "dl_nts_001",
        "counterparty_id": "cp_nts",
        "instrument": "DEPOSIT",
        "principal_pence": 18_000_000 * P,
        "currency": "GBP",
        "rate_bp": 405,
        "tenor_months": 12,
        "trade_date": days_ago(60),
        "value_date": days_ago(60),
        "maturity_date": months_after(days_ago(60), 12),
        "status": "ACTIVE",
        "capture_source": "KEYED",
        "created_by": "A. Whitfield",
        "required_approver": "HEAD_OF_TREASURY",
        "approved_by": "M. Doran",
        "limit_id_at_booking": "lim_nts_1",
    },
    {
        "id": "dl_cal_001",
        "counterparty_id": "cp_caledonia",
        "instrument": "DEPOSIT",
        "principal_pence": 20_000_000 * P,
        "currency": "GBP",
        "rate_bp": 415,
        "tenor_months": 24,
        "trade_date": days_ago(90),
        "value_date": days_ago(90),
        "maturity_date": months_after(days_ago(90), 24),
        "status": "ACTIVE",
        "capture_source": "KEYED",
        "created_by": "A. Whitfield",
        "required_approver": "HEAD_OF_TREASURY",
        "approved_by": "M. Doran",
        "limit_id_at_booking": "lim_caledonia_1",
    },
    {
        "id": "dl_mer_001",
        "counterparty_id": "cp_meridian",
        "instrument": "DEPOSIT",
        "principal_pence": 4_000_000 * P,
        "currency": "GBP",
        "rate_bp": 420,
        "tenor_months": 3,
        "trade_date": days_ago(20),
        "value_date": days_ago(20),
        "maturity_date": months_after(days_ago(20), 3),
        "status": "ACTIVE",
        "capture_source": "KEYED",
        "created_by": "A. Whitfield",
        "required_approver": "HEAD_OF_TREASURY",
        "approved_by": "M. Doran",
        "limit_id_at_booking": "lim_meridian_1",
    },
    {
        "id": "dl_har_001",
        "counterparty_id": "cp_harbour",
        "instrument": "FX_FORWARD",
        "principal_pence": 3_000_000 * P,
        "currency": "EUR",
        "rate_bp": 11740,
        # Three months, not six. BBB+ allows three, and a seeded position
        # outside its own term limit puts the book in breach the first time
        # anything re-tests it. The measure is the notional times the add on
        # either way, so no figure the demonstration turns on moves.
        "tenor_months": 3,
        "trade_date": days_ago(30),
        "value_date": days_ago(30),
        "maturity_date": months_after(days_ago(30), 3),
        "status": "ACTIVE",
        "capture_source": "KEYED",
        "created_by": "A. Whitfield",
        "required_approver": "ANALYST",
        "approved_by": "M. Doran",
        "limit_id_at_booking": "lim_harbour_1",
    },
]

# --------------------------------------------------------------------------
# The Oracle boundary
# --------------------------------------------------------------------------
# Interface I-3, behind an adapter over this table. 8,000,000 uninvested is
# the cash the overnight advisory run finds landing with nowhere to go.

ORACLE_BALANCES = [
    {
        "id": "obal_001",
        "account_name": "Group operating account",
        "balance_pence": 8_000_000 * P,
        "as_of_date": CLOCK_DATE,
    },
]

ORACLE_INSTRUCTIONS: list = []

# --------------------------------------------------------------------------
# People. Phase 1.5.
# --------------------------------------------------------------------------
#
# Three accounts, because one is not enough to demonstrate the control. A
# deal cannot be approved by the person who proposed it, so a demonstration
# needs somebody to propose and somebody else to sign, and the CFO exists
# because the approval router routes above the second threshold to a role
# neither of the others holds.
#
# The passwords are here in the open, and they are demonstration passwords
# for a prototype with a seeded book. Nothing in this file survives contact
# with Entra ID single sign on, which document 4 names as the destination.

DEMO_PASSWORD = "treasury"

USERS = [
    {
        "id": "usr_whitfield",
        "email": "a.whitfield@northgate.example",
        "display_name": "A. Whitfield",
        "roles": ["ANALYST"],
        "note": "Proposes deals and keys counterparties. Signs up to the analyst threshold.",
    },
    {
        "id": "usr_doran",
        "email": "m.doran@northgate.example",
        "display_name": "M. Doran",
        "roles": ["HEAD_OF_TREASURY", "ANALYST"],
        "note": "Signs up to the second threshold. The signer in the run sheet.",
    },
    {
        "id": "usr_sethi",
        "email": "r.sethi@northgate.example",
        "display_name": "R. Sethi",
        "roles": ["CFO"],
        "note": "Signs anything above the second threshold.",
    },
]

# --------------------------------------------------------------------------
# The investment policy. Phase 2.
# --------------------------------------------------------------------------
#
# The advisory layer refuses to run without one, and the refusal is a
# feature: it is the conversation that shapes the customer policy. The seed
# supplies one so a demonstration has something to show, and the refusal is
# still reachable by superseding it.
#
# The buffer and the forecast inflow are chosen so the gap comes out at the
# 8,000,000 the run sheet quotes: 8,000,000 of cash plus 2,000,000 forecast
# to arrive, less a 2,000,000 buffer that has to stay available.

INVESTMENT_POLICY = {
    "id": "inv_v1",
    "liquidity_buffer_pence": 2_000_000 * P,
    "buffer_horizon_days": 30,
    "priority_order": "SECURITY,LIQUIDITY,YIELD",
    "model_enabled": 1,
    "approved_by": "Group CFO",
}

#: What share of the portfolio should mature in each bucket. The emptiest
#: bucket is what decides the term of a recommendation, so this is the data
#: that turns a cash surplus into a six month deposit rather than a
#: three month one.
LADDER_TARGETS = [
    # bucket, target_share_bp, minimum_pence
    ("0_3M", 2500, 2_000_000 * P),
    ("3_6M", 2500, 2_000_000 * P),
    ("6_12M", 2500, 2_000_000 * P),
    ("OVER_12M", 2500, 0),
]

CURRENCY_COVER_TARGETS = [
    # currency, target_cover_bp, horizon_days
    ("EUR", 8000, 180),
]

#: Interface I-9, from Oracle EPM. Without it the advisory layer has nothing
#: to test. A forecast is a statement made on a day and is not corrected in
#: place, which is why as_of is on every row.
FORECAST_LINES = [
    {
        "id": "fcl_001",
        "as_of": CLOCK_DATE,
        "forecast_date": CLOCK_DATE,
        "currency": "GBP",
        "amount_minor": 2_000_000 * P,
        "entity": "Group operating",
    },
    {
        "id": "fcl_002",
        "as_of": CLOCK_DATE,
        "forecast_date": months_after(CLOCK_DATE, 2),
        "currency": "EUR",
        "amount_minor": -4_000_000 * P,
        "entity": "Group procurement",
    },
]

# --------------------------------------------------------------------------
# Figures the seed is asserted against
# --------------------------------------------------------------------------
# Not stored. Written here so a test can state what the book is meant to look
# like on open, rather than restating the arithmetic in the test.

EXPECTED = {
    "nts_measured_pence": 18_119_836 * P,
    "northern_group_limit_pence": 25_000_000 * P,
    "resize_to_pence": 6_880_164 * P,
    "advisory_gap_pence": 8_000_000 * P,
}
