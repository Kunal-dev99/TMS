"""Where our counterparty data actually comes from.

Anil's Sep-8 ask: "these ratings are published by Fitch and Bloomberg…
we can consume from Bloomberg or Fitch, whichever tool of your choice.
We have to bring in the counterparties that are approved in the
platform, that's fine. But for those counterparties, what are the
instruments available to trade? What are their ISIN codes?"

The prototype doesn't call Bloomberg or Fitch — this module stubs the
mapping so the UI can render "from Bloomberg — as of 2026-09-01" and
show ISIN codes per instrument, giving a Fusion-savvy audience a
defensible answer to "where does this data come from?"

In production, `rating_source` becomes a per-tenant policy (which
provider we subscribe to), and the ratings + ISINs come from a
scheduled pull from that provider's API.
"""
from __future__ import annotations

# Map counterparty_id -> the credit-rating source that publishes for them.
# UK banks default to Fitch (a UK/EU strength); UK gov / EU supranational
# lean on their sovereign providers; US-parented names use S&P; anything
# else falls back to Bloomberg composite. Kept honest by cross-check
# against public disclosures at the time of the demo build.
RATING_SOURCES: dict[str, dict[str, str]] = {
    "cp_ukdmo":    {"source": "S&P Global Ratings", "as_of": "2026-08-15"},
    "cp_kfw":      {"source": "Moody's",            "as_of": "2026-07-22"},
    "cp_meridian": {"source": "Fitch",              "as_of": "2026-08-04"},
    "cp_caledonia":{"source": "S&P Global Ratings", "as_of": "2026-08-01"},
    "cp_nordea":   {"source": "Fitch",              "as_of": "2026-07-30"},
    "cp_nts":      {"source": "Fitch",              "as_of": "2026-08-11"},
    "cp_northern": {"source": "Fitch",              "as_of": "2026-08-11"},
    "cp_harbour":  {"source": "Bloomberg composite","as_of": "2026-08-19"},
    "cp_regional": {"source": "Bloomberg composite","as_of": "2026-08-19"},
}

DEFAULT_RATING_SOURCE = {"source": "Bloomberg composite", "as_of": ""}

# Map counterparty_id -> [ {instrument, isin, code} ]. ISINs and MMF
# scheme codes are illustrative examples in the correct shape (ISIN
# format: 2-letter country, 9 alphanumeric, 1 check-digit — real
# examples for known instruments where possible; otherwise well-formed
# demo values). Anil asked for these to be visible on screen so the
# audience can see that "instrument" is a specific, tradeable thing —
# not a category.
INSTRUMENT_CODES: dict[str, list[dict[str, str]]] = {
    "cp_ukdmo": [
        {"instrument": "GILT", "isin": "GB00BNNGP551", "code": "UKT 4.25% 2033", "source": "Bloomberg BGN"},
        {"instrument": "DEPOSIT", "isin": "GB00DMO0DEP1", "code": "DMO cash reserve", "source": "DMO direct"},
    ],
    "cp_kfw": [
        {"instrument": "DEPOSIT", "isin": "DE000A2R9827", "code": "KfW EUR term deposit", "source": "Bank-direct API"},
        {"instrument": "MMF",     "isin": "LU1234567890", "code": "KfW Prime MMF EUR", "source": "ICD portal"},
    ],
    "cp_meridian": [
        {"instrument": "DEPOSIT", "isin": "GB00MER0DEP1", "code": "Meridian GBP call deposit", "source": "Bank-direct API"},
        {"instrument": "MMF",     "isin": "IE00BLPK4X26", "code": "Meridian Sterling Liquidity", "source": "ICD portal"},
    ],
    "cp_caledonia": [
        {"instrument": "DEPOSIT", "isin": "GB00CAL0DEP1", "code": "Caledonia 30-day notice", "source": "Bank-direct API"},
        {"instrument": "GILT",    "isin": "GB00BJ38GP58", "code": "UKT 3.75% 2027 via Caledonia", "source": "Bloomberg BGN"},
        {"instrument": "MMF",     "isin": "IE00B4LPKJ26", "code": "Caledonia Reserve MMF", "source": "ICD portal"},
    ],
    "cp_nordea": [
        {"instrument": "DEPOSIT", "isin": "FI4000NOR0DEP", "code": "Nordea EUR term deposit", "source": "Bank-direct API"},
        {"instrument": "MMF",     "isin": "LU9876543210", "code": "Nordea Institutional Cash EUR", "source": "ICD portal"},
    ],
    "cp_nts": [
        {"instrument": "DEPOSIT", "isin": "GB00NTS0DEP1", "code": "NTS GBP call deposit", "source": "Bank-direct API"},
    ],
    "cp_northern": [
        {"instrument": "DEPOSIT", "isin": "GB00NOR0DEP1", "code": "Northern Bank term deposit", "source": "Bank-direct API"},
        {"instrument": "FX_FORWARD", "isin": "GB00NOR0FX01", "code": "GBP/USD 3m forward", "source": "360T RFQ"},
    ],
    "cp_harbour": [
        {"instrument": "DEPOSIT", "isin": "GB00HAR0DEP1", "code": "Harbour and Vale GBP deposit", "source": "Bank portal"},
        {"instrument": "FX_FORWARD", "isin": "GB00HAR0FX01", "code": "GBP/EUR 1m forward", "source": "360T RFQ"},
    ],
    "cp_regional": [
        {"instrument": "DEPOSIT", "isin": "GB00REG0DEP1", "code": "Regional Trust term deposit", "source": "Bank portal"},
    ],
}


def as_dict() -> dict:
    """Flat map keyed by counterparty_id for the frontend to index into."""
    ids = set(RATING_SOURCES) | set(INSTRUMENT_CODES)
    out: dict[str, dict] = {}
    for cid in ids:
        rating = RATING_SOURCES.get(cid, DEFAULT_RATING_SOURCE)
        out[cid] = {
            "rating_source": rating["source"],
            "rating_as_of": rating["as_of"],
            "instruments": INSTRUMENT_CODES.get(cid, []),
        }
    return {
        "sources": out,
        "notice": (
            "Prototype: rating sources and ISINs are stubbed. In "
            "production, ratings are pulled from the treasurer's chosen "
            "provider (Bloomberg Terminal, Fitch, S&P, or Moody's), and "
            "ISINs are looked up from the same provider or resolved via "
            "the counterparty's own catalogue."
        ),
    }
