"""Money into sentences.

The client formats every figure it displays. This module exists for the one
exception document 2 grants: a human readable message is composed on the
server with the money already in the sentence, because a client that has to
assemble a sentence from a code and three amounts is a client that has to
know what the sentence means.
"""

MINOR_UNITS = {"GBP": 2, "EUR": 2, "USD": 2, "JPY": 0}


def pounds(pence: int) -> str:
    """1_811_983_562 becomes 18,119,836. Rounded to the pound, as displayed."""
    return f"{round(pence / 100):,}"


def sterling(pence: int) -> str:
    return f"£{pounds(pence)}"


def minor(amount: int, currency: str) -> str:
    places = MINOR_UNITS.get(currency, 2)
    return f"{amount / (10 ** places):,.0f} {currency}"


def per_cent(basis_points: int) -> str:
    """420 becomes 4.20 per cent."""
    return f"{basis_points / 100:.2f} per cent"


def deal_rate(basis_points: int, instrument: str) -> str:
    """The same column, read two ways.

    `rate_bp` holds an interest rate for a deposit and an exchange rate for a
    forward. One column, because a deal has one rate, but 11740 is 117.40 per
    cent on a deposit and 1.1740 on a forward. Rendering a forward as a
    percentage produces a figure that is wrong by two orders of magnitude and
    looks like a rate, which is worse than looking broken.
    """
    if instrument == "FX_FORWARD":
        return f"{basis_points / 10000:.4f}"
    return per_cent(basis_points)
