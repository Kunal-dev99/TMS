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
    ("grp_ukgov", "UK Government", 60_000_000 * P),
    ("grp_kfw", "KfW Group", 50_000_000 * P),
    ("grp_meridian", "Meridian Group", 25_000_000 * P),
    ("grp_caledonia", "Caledonia Group", 30_000_000 * P),
    ("grp_nordea", "Nordea Group", 30_000_000 * P),
    ("grp_northern", "Northern Group", 25_000_000 * P),
    ("grp_harbour", "Harbour and Vale Group", 8_000_000 * P),
    ("grp_regional", "Regional Trust Group", 6_000_000 * P),
]

# --------------------------------------------------------------------------
# Counterparties
# --------------------------------------------------------------------------

COUNTERPARTIES = [
    {
        "id": "cp_ukdmo",
        "group_id": "grp_ukgov",
        "name": "UK Debt Management Office",
        "lei": "213800UKDMOGILTS0001",
        "group_parent": "HM Treasury",
        "country": "GB",
        "rating": "AAA",
        "rating_status": "STABLE",
        "status": "ACTIVE",
        "instruments": ["GILT", "DEPOSIT"],
    },
    {
        "id": "cp_kfw",
        "group_id": "grp_kfw",
        "name": "KfW Bankengruppe",
        "lei": "213800KFWBANKENGR001",
        "group_parent": "KfW Group",
        "country": "DE",
        "rating": "AAA",
        "rating_status": "STABLE",
        "status": "ACTIVE",
        "instruments": ["DEPOSIT", "MMF"],
    },
    {
        "id": "cp_nordea",
        "group_id": "grp_nordea",
        "name": "Nordea Bank Abp",
        "lei": "213800NORDEABANKA001",
        "group_parent": "Nordea Group",
        "country": "FI",
        "rating": "AA-",
        "rating_status": "STABLE",
        "status": "ACTIVE",
        "instruments": ["DEPOSIT", "MMF", "FX_FORWARD"],
    },
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
        "instruments": ["DEPOSIT", "GILT", "MMF", "FX_FORWARD"],
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
    {
        "id": "cp_regional",
        "group_id": "grp_regional",
        "name": "Regional Trust Bank",
        "lei": "213800REGIONALTRT001",
        "group_parent": "Regional Trust Group Ltd",
        "country": "GB",
        "rating": "BBB",
        "rating_status": "STABLE",
        "status": "ACTIVE",
        "instruments": ["DEPOSIT"],
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
        "id": "lim_ukdmo_1",
        "counterparty_id": "cp_ukdmo",
        "amount_pence": 50_000_000 * P,
        "max_tenor_months": 24,
        "source": "BAND",
        "effective_from": "2026-01-05",
        "approved_by": "Head of Treasury",
        "reason": "Band limit at AAA; UK government paper.",
    },
    {
        "id": "lim_kfw_1",
        "counterparty_id": "cp_kfw",
        "amount_pence": 40_000_000 * P,
        "max_tenor_months": 24,
        "source": "BAND",
        "effective_from": "2026-01-05",
        "approved_by": "Head of Treasury",
        "reason": "Band limit at AAA; KfW carries an explicit German guarantee.",
    },
    {
        "id": "lim_nordea_1",
        "counterparty_id": "cp_nordea",
        "amount_pence": 25_000_000 * P,
        "max_tenor_months": 12,
        "source": "BAND",
        "effective_from": "2026-01-05",
        "approved_by": "Head of Treasury",
        "reason": "Band limit at AA-.",
    },
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
    {
        "id": "lim_regional_1",
        "counterparty_id": "cp_regional",
        "amount_pence": 5_000_000 * P,
        "max_tenor_months": 3,
        "source": "BAND",
        "effective_from": "2026-03-02",
        "approved_by": "Head of Treasury",
        "reason": "Band limit at BBB.",
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
# Confirmations. Phase 3.
# --------------------------------------------------------------------------
#
# Two of the four positions have been confirmed and two have not, which is
# the mix screen 6 of document 3 shows: a blotter where some rows are
# accruing and some are still waiting on the bank.
#
# None of them disagrees. A mismatch is not seeded on purpose: the queue
# opens empty, and a demonstration creates the mismatch by ingesting a
# confirmation with a different rate. Finding one pre-baked is a weaker
# argument than watching one appear.

CONFIRMATIONS = [
    {
        "id": "cnf_nts_001",
        "deal_id": "dl_nts_001",
        "counterparty_id": "cp_nts",
        "message_type": "MT320",
        "reference": "NTS-2026-88213",
    },
    {
        "id": "cnf_cal_001",
        "deal_id": "dl_cal_001",
        "counterparty_id": "cp_caledonia",
        "message_type": "MT320",
        "reference": "CAL-2026-41077",
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
    ("USD", 7500, 180),
    ("CHF", 6000, 180),
]

# --------------------------------------------------------------------------
# FX exposures (sales-side). Forecast receivables from overseas customers,
# to be surfaced on the Hedging panel. Directions are RECEIVABLE because
# we sell recyclables in EUR / USD / CHF; the sold-EUR-forward hedge
# protects the GBP value of that receipt.
# --------------------------------------------------------------------------

FX_EXPOSURES = [
    # ---- EUR: €100m spread over 12 months, laddered by delivery ----
    {"id": "fxe_eur_001", "currency": "EUR", "amount_minor": 8_000_000 * 100,  "expected_offset_days": 30,  "source": "FORECAST",   "source_reference": "Oracle EPM FY26"},
    {"id": "fxe_eur_002", "currency": "EUR", "amount_minor": 10_000_000 * 100, "expected_offset_days": 60,  "source": "CONTRACT",   "source_reference": "SC-EU-4412"},
    {"id": "fxe_eur_003", "currency": "EUR", "amount_minor": 7_000_000 * 100,  "expected_offset_days": 90,  "source": "FORECAST",   "source_reference": "Oracle EPM FY26"},
    {"id": "fxe_eur_004", "currency": "EUR", "amount_minor": 12_000_000 * 100, "expected_offset_days": 130, "source": "CONTRACT",   "source_reference": "SC-EU-4471"},
    {"id": "fxe_eur_005", "currency": "EUR", "amount_minor": 15_000_000 * 100, "expected_offset_days": 170, "source": "PURCHASE_ORDER", "source_reference": "PO-45119"},
    {"id": "fxe_eur_006", "currency": "EUR", "amount_minor": 12_000_000 * 100, "expected_offset_days": 220, "source": "FORECAST",   "source_reference": "Oracle EPM FY26"},
    {"id": "fxe_eur_007", "currency": "EUR", "amount_minor": 13_000_000 * 100, "expected_offset_days": 270, "source": "FORECAST",   "source_reference": "Oracle EPM FY26"},
    {"id": "fxe_eur_008", "currency": "EUR", "amount_minor": 23_000_000 * 100, "expected_offset_days": 340, "source": "FORECAST",   "source_reference": "Oracle EPM FY26"},

    # ---- USD: $60m over 12 months ----
    {"id": "fxe_usd_001", "currency": "USD", "amount_minor": 6_000_000 * 100,  "expected_offset_days": 45,  "source": "CONTRACT",   "source_reference": "SC-US-2201"},
    {"id": "fxe_usd_002", "currency": "USD", "amount_minor": 8_000_000 * 100,  "expected_offset_days": 100, "source": "FORECAST",   "source_reference": "Oracle EPM FY26"},
    {"id": "fxe_usd_003", "currency": "USD", "amount_minor": 12_000_000 * 100, "expected_offset_days": 160, "source": "CONTRACT",   "source_reference": "SC-US-2230"},
    {"id": "fxe_usd_004", "currency": "USD", "amount_minor": 14_000_000 * 100, "expected_offset_days": 240, "source": "FORECAST",   "source_reference": "Oracle EPM FY26"},
    {"id": "fxe_usd_005", "currency": "USD", "amount_minor": 20_000_000 * 100, "expected_offset_days": 330, "source": "FORECAST",   "source_reference": "Oracle EPM FY26"},

    # ---- CHF: CHF 12m over 12 months, entirely unhedged ----
    {"id": "fxe_chf_001", "currency": "CHF", "amount_minor": 2_000_000 * 100, "expected_offset_days": 60,  "source": "CONTRACT", "source_reference": "SC-CH-0091"},
    {"id": "fxe_chf_002", "currency": "CHF", "amount_minor": 3_000_000 * 100, "expected_offset_days": 150, "source": "FORECAST", "source_reference": "Oracle EPM FY26"},
    {"id": "fxe_chf_003", "currency": "CHF", "amount_minor": 3_000_000 * 100, "expected_offset_days": 250, "source": "FORECAST", "source_reference": "Oracle EPM FY26"},
    {"id": "fxe_chf_004", "currency": "CHF", "amount_minor": 4_000_000 * 100, "expected_offset_days": 340, "source": "FORECAST", "source_reference": "Oracle EPM FY26"},
]

# --------------------------------------------------------------------------
# Existing FX_FORWARD deals + HedgeLinks so the panel opens with a story:
# EUR ~60% hedged, USD ~40% hedged, CHF 0% hedged.
# --------------------------------------------------------------------------

FX_HEDGE_DEALS = [
    # EUR forwards booked against near-term receivables — cp_caledonia is
    # AA-, cp_nordea is AA-, both FX_FORWARD-permitted.
    {
        "id": "dl_fx_eur_001",
        "counterparty_id": "cp_caledonia",
        "currency": "EUR",
        "sell_amount_minor": 20_000_000 * P,
        "rate": 0.8570,
        "tenor_months": 3,
        "trade_offset_days": -15,
    },
    {
        "id": "dl_fx_eur_002",
        "counterparty_id": "cp_nordea",
        "currency": "EUR",
        "sell_amount_minor": 25_000_000 * P,
        "rate": 0.8555,
        "tenor_months": 6,
        "trade_offset_days": -30,
    },
    {
        "id": "dl_fx_eur_003",
        "counterparty_id": "cp_caledonia",
        "currency": "EUR",
        "sell_amount_minor": 15_000_000 * P,
        "rate": 0.8540,
        "tenor_months": 9,
        "trade_offset_days": -10,
    },

    # USD — one forward covering ~40% of the book
    {
        "id": "dl_fx_usd_001",
        "counterparty_id": "cp_nordea",
        "currency": "USD",
        "sell_amount_minor": 24_000_000 * P,
        "rate": 0.7810,
        "tenor_months": 6,
        "trade_offset_days": -20,
    },
]

# links: [(deal_id, exposure_id, covered_amount_minor)]
FX_HEDGE_LINKS = [
    # EUR forward #1 (20m) → covers Oct, Nov, part-Dec
    ("dl_fx_eur_001", "fxe_eur_001", 8_000_000 * 100),
    ("dl_fx_eur_001", "fxe_eur_002", 10_000_000 * 100),
    ("dl_fx_eur_001", "fxe_eur_003", 2_000_000 * 100),

    # EUR forward #2 (25m) → part-Dec Jan Feb
    ("dl_fx_eur_002", "fxe_eur_003", 5_000_000 * 100),
    ("dl_fx_eur_002", "fxe_eur_004", 12_000_000 * 100),
    ("dl_fx_eur_002", "fxe_eur_005", 8_000_000 * 100),

    # EUR forward #3 (15m) → Feb tail + Mar
    ("dl_fx_eur_003", "fxe_eur_005", 7_000_000 * 100),
    ("dl_fx_eur_003", "fxe_eur_006", 8_000_000 * 100),

    # USD forward → covers the first two months of USD
    ("dl_fx_usd_001", "fxe_usd_001", 6_000_000 * 100),
    ("dl_fx_usd_001", "fxe_usd_002", 8_000_000 * 100),
    ("dl_fx_usd_001", "fxe_usd_003", 10_000_000 * 100),
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
# News. Seeded so the credit-signal scanner has something to read on open.
#
# A mix per counterparty: at least one item worth reading (a rating watch, a
# results miss, sector contagion) and at least one that is deliberately not
# material (a routine dividend, a management appointment). The scanner has
# to tell them apart; leaving both in tests the classifier as well as the
# prose.
# --------------------------------------------------------------------------

NEWS_ITEMS = [
    # Caledonia Trust Bank — quiet, one small positive
    {
        "id": "nw_cal_001",
        "counterparty_id": "cp_caledonia",
        "source": "S&P Global Ratings",
        "headline": "S&P affirms Caledonia Trust Bank at AA-, outlook stable",
        "body": "S&P Global Ratings today affirmed the AA- long-term "
                 "issuer credit rating on Caledonia Trust Bank, citing a "
                 "solid capital position and steady net interest margin.",
        "published_at": days_ago(3),
    },
    {
        "id": "nw_cal_002",
        "counterparty_id": "cp_caledonia",
        "source": "Reuters",
        "headline": "Caledonia Q3 profit up 4% year-on-year",
        "body": "Caledonia Trust Bank posted a Q3 profit of GBP 412 "
                 "million, up 4% on the prior year, on a modest expansion "
                 "of the loan book and stable cost of risk.",
        "published_at": days_ago(9),
    },

    # Harbour and Vale Bank — a real signal
    {
        "id": "nw_har_001",
        "counterparty_id": "cp_harbour",
        "source": "Moody's Investors Service",
        "headline": "Moody's places Harbour and Vale Bank on review for downgrade",
        "body": "Moody's has placed the Baa1 issuer rating of Harbour and "
                 "Vale Bank on review for downgrade, citing declining net "
                 "interest margin and rising loan loss provisions in the "
                 "consumer lending book. A rating decision is expected "
                 "within 90 days.",
        "published_at": days_ago(1),
    },
    {
        "id": "nw_har_002",
        "counterparty_id": "cp_harbour",
        "source": "Financial Times",
        "headline": "Harbour Bank to cut 400 jobs from retail arm",
        "body": "Harbour and Vale Bank has announced plans to eliminate "
                 "about 400 positions from its retail banking arm as part "
                 "of a cost-reduction programme in response to margin "
                 "pressure.",
        "published_at": days_ago(4),
    },

    # Meridian Bank plc — mixed
    {
        "id": "nw_mer_001",
        "counterparty_id": "cp_meridian",
        "source": "Fitch Ratings",
        "headline": "Fitch upgrades outlook on Meridian Bank to positive",
        "body": "Fitch Ratings has revised the outlook on Meridian Bank's "
                 "A rating to positive from stable, citing an improving "
                 "capital position and disciplined risk management.",
        "published_at": days_ago(6),
    },
    {
        "id": "nw_mer_002",
        "counterparty_id": "cp_meridian",
        "source": "Bloomberg",
        "headline": "Meridian appoints new head of treasury operations",
        "body": "Meridian Bank plc today confirmed the appointment of "
                 "Sarah Novak as head of treasury operations, effective 1 "
                 "October. Ms Novak joins from a regional peer.",
        "published_at": days_ago(11),
    },

    # Northern Bank plc — sector contagion signal
    {
        "id": "nw_nbk_001",
        "counterparty_id": "cp_northern",
        "source": "Wall Street Journal",
        "headline": "Regional bank stress test flags concentration risk at three lenders",
        "body": "A stress test published today by the FCA identified "
                 "elevated commercial real estate concentration risk at "
                 "three regional lenders, including Northern Bank plc. "
                 "None of the three failed the test, but the FCA has "
                 "asked for additional reporting.",
        "published_at": days_ago(2),
    },
    {
        "id": "nw_nbk_002",
        "counterparty_id": "cp_northern",
        "source": "Reuters",
        "headline": "Northern Bank declares interim dividend of 8p",
        "body": "Northern Bank plc has declared an interim dividend of "
                 "8p per share, in line with prior guidance.",
        "published_at": days_ago(14),
    },

    # Northern Treasury Services Ltd — quiet
    {
        "id": "nw_nts_001",
        "counterparty_id": "cp_nts",
        "source": "Bloomberg",
        "headline": "NTS parent Northern Group announces GBP 200m buyback",
        "body": "Northern Group has announced a GBP 200 million share "
                 "buyback programme to run over the next twelve months, "
                 "citing surplus capital and strong cash generation.",
        "published_at": days_ago(5),
    },
    {
        "id": "nw_nts_002",
        "counterparty_id": "cp_nts",
        "source": "Financial Times",
        "headline": "NTS wins mandate on GBP 1.2bn syndicated loan",
        "body": "Northern Treasury Services Ltd has been appointed a "
                 "co-manager on a GBP 1.2 billion syndicated loan to a "
                 "FTSE 250 utility, alongside three other lenders.",
        "published_at": days_ago(8),
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
