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
