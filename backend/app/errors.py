"""The error catalogue.

Thirty-eight codes, each with the status it maps to and the message shape it
carries. A service raises a code and the exception handler maps it, so no
router decides a status.

Document 2 revision B lists the sixteen codes added in revision B verbatim.
The twenty-two from revision A are named in the prose but not reproduced in
the revision B document, so they are reconstructed here from the endpoints
and the refusals those documents describe. They are marked accordingly and
are the first thing to reconcile against revision A when it is to hand. See
docs/ASSUMPTIONS.md.

Every message states what to do next rather than what went wrong. A refusal
that only names the field is a refusal the user cannot act on.
"""

from enum import Enum


class ErrorCode(str, Enum):
    # -- counterparty control, reconstructed from revision A ---------------
    COUNTERPARTY_NOT_FOUND = "COUNTERPARTY_NOT_FOUND"
    COUNTERPARTY_NOT_VERIFIED = "COUNTERPARTY_NOT_VERIFIED"
    COUNTERPARTY_NOT_APPROVED = "COUNTERPARTY_NOT_APPROVED"
    COUNTERPARTY_ALREADY_ACTIVE = "COUNTERPARTY_ALREADY_ACTIVE"
    COUNTERPARTY_NOT_ACTIVE = "COUNTERPARTY_NOT_ACTIVE"
    APPROVER_REQUIRED = "APPROVER_REQUIRED"
    LIMIT_REASON_REQUIRED = "LIMIT_REASON_REQUIRED"
    UNKNOWN_RATING = "UNKNOWN_RATING"
    NO_LIMIT_IN_FORCE = "NO_LIMIT_IN_FORCE"

    # -- dealing, reconstructed from revision A ----------------------------
    DEAL_NOT_FOUND = "DEAL_NOT_FOUND"
    DEAL_NOT_APPROVED = "DEAL_NOT_APPROVED"
    DEAL_ALREADY_APPROVED = "DEAL_ALREADY_APPROVED"
    DEAL_ALREADY_INSTRUCTED = "DEAL_ALREADY_INSTRUCTED"
    INSTRUMENT_NOT_PERMITTED = "INSTRUMENT_NOT_PERMITTED"
    PRINCIPAL_MUST_BE_POSITIVE = "PRINCIPAL_MUST_BE_POSITIVE"
    TENOR_OUT_OF_RANGE = "TENOR_OUT_OF_RANGE"
    OVERRIDE_REASON_REQUIRED = "OVERRIDE_REASON_REQUIRED"
    OVERRIDE_NOT_ALLOWED = "OVERRIDE_NOT_ALLOWED"
    CHECK_INPUTS_UNAVAILABLE = "CHECK_INPUTS_UNAVAILABLE"

    # -- the queue and breaches, reconstructed from revision A -------------
    QUEUE_ITEM_NOT_FOUND = "QUEUE_ITEM_NOT_FOUND"
    QUEUE_ITEM_ALREADY_RESOLVED = "QUEUE_ITEM_ALREADY_RESOLVED"
    BREACH_NOT_FOUND = "BREACH_NOT_FOUND"

    # -- revision B, amendments --------------------------------------------
    AMENDMENT_REASON_REQUIRED = "AMENDMENT_REASON_REQUIRED"
    EFFECTIVE_DATE_BEFORE_VALUE_DATE = "EFFECTIVE_DATE_BEFORE_VALUE_DATE"
    DEAL_NOT_AMENDABLE = "DEAL_NOT_AMENDABLE"
    AMENDMENT_ALREADY_APPLIED = "AMENDMENT_ALREADY_APPLIED"
    CLOSED_PERIOD_LOCKED = "CLOSED_PERIOD_LOCKED"
    AMENDMENT_FAILS_CHECKS = "AMENDMENT_FAILS_CHECKS"
    AMENDMENT_TYPE_INVALID = "AMENDMENT_TYPE_INVALID"

    # -- revision B, confirmations and settlement --------------------------
    UNKNOWN_MESSAGE_TYPE = "UNKNOWN_MESSAGE_TYPE"
    CONFIRMATION_NOT_FOUND = "CONFIRMATION_NOT_FOUND"
    ALREADY_MATCHED = "ALREADY_MATCHED"
    SETTLEMENT_BREAK = "SETTLEMENT_BREAK"

    # -- revision B, the advisory layer ------------------------------------
    NO_INVESTMENT_POLICY = "NO_INVESTMENT_POLICY"
    RUN_NOT_FOUND = "RUN_NOT_FOUND"
    ALREADY_DECIDED = "ALREADY_DECIDED"
    RECOMMENDATION_EXPIRED = "RECOMMENDATION_EXPIRED"
    REJECTION_REASON_REQUIRED = "REJECTION_REASON_REQUIRED"

    # -- revision B, currency risk -----------------------------------------
    HEDGE_EXCEEDS_EXPOSURE = "HEDGE_EXCEEDS_EXPOSURE"
    NOT_AN_FX_FORWARD = "NOT_AN_FX_FORWARD"

    # -- phase 1.5, identity -----------------------------------------------
    # Three codes the design documents do not list, because they describe a
    # system with no identity. They are marked so the count of thirty-eight
    # can still be reconciled against document 2.
    NOT_AUTHENTICATED = "NOT_AUTHENTICATED"
    ROLE_NOT_HELD = "ROLE_NOT_HELD"
    SEGREGATION_OF_DUTIES = "SEGREGATION_OF_DUTIES"


#: Status and default message per code. The message is a fallback; a service
#: that can state the arithmetic composes its own and passes it in.
CATALOGUE: dict[ErrorCode, tuple[int, str]] = {
    ErrorCode.COUNTERPARTY_NOT_FOUND: (404, "That counterparty does not exist."),
    ErrorCode.COUNTERPARTY_NOT_VERIFIED: (
        409,
        "Verify the identifier, the group parent and the rating before setting a limit.",
    ),
    ErrorCode.COUNTERPARTY_NOT_APPROVED: (
        409,
        "A limit nobody signed is not a control. Record the approver before activating.",
    ),
    ErrorCode.COUNTERPARTY_ALREADY_ACTIVE: (409, "This counterparty is already active."),
    ErrorCode.COUNTERPARTY_NOT_ACTIVE: (
        409,
        "Only an active counterparty can be dealt with.",
    ),
    ErrorCode.APPROVER_REQUIRED: (
        400,
        "A limit nobody signed is not a control. Record the approver.",
    ),
    ErrorCode.LIMIT_REASON_REQUIRED: (
        400,
        "A limit set above the rating band needs a reason.",
    ),
    ErrorCode.UNKNOWN_RATING: (400, "That rating has no band in the policy in force."),
    ErrorCode.NO_LIMIT_IN_FORCE: (
        409,
        "This counterparty has no limit in force, which is not the same as a limit of nothing.",
    ),
    ErrorCode.DEAL_NOT_FOUND: (404, "That deal does not exist."),
    ErrorCode.DEAL_NOT_APPROVED: (409, "This deal has not been approved."),
    ErrorCode.DEAL_ALREADY_APPROVED: (409, "Somebody has already signed this deal."),
    ErrorCode.DEAL_ALREADY_INSTRUCTED: (
        409,
        "A payment instruction has already been handed to Oracle for this deal.",
    ),
    ErrorCode.INSTRUMENT_NOT_PERMITTED: (
        400,
        "This counterparty is not approved to trade that instrument.",
    ),
    ErrorCode.PRINCIPAL_MUST_BE_POSITIVE: (400, "Enter an amount above nothing."),
    ErrorCode.TENOR_OUT_OF_RANGE: (400, "Enter a term between one and sixty months."),
    ErrorCode.OVERRIDE_REASON_REQUIRED: (
        400,
        "An override that puts the book outside policy needs a reason.",
    ),
    ErrorCode.OVERRIDE_NOT_ALLOWED: (
        409,
        "The policy in force is a hard block. Nothing can be overridden.",
    ),
    ErrorCode.CHECK_INPUTS_UNAVAILABLE: (
        409,
        "A check could not read its inputs, so it failed rather than passed.",
    ),
    ErrorCode.QUEUE_ITEM_NOT_FOUND: (404, "That queue item does not exist."),
    ErrorCode.QUEUE_ITEM_ALREADY_RESOLVED: (409, "That queue item is already resolved."),
    ErrorCode.BREACH_NOT_FOUND: (404, "That breach does not exist."),
    ErrorCode.AMENDMENT_REASON_REQUIRED: (
        400,
        "An amendment that reverses posted journals needs a reason.",
    ),
    ErrorCode.EFFECTIVE_DATE_BEFORE_VALUE_DATE: (
        400,
        "An amendment cannot take effect before the deal started.",
    ),
    ErrorCode.DEAL_NOT_AMENDABLE: (
        409,
        "Only a live deal can be amended. This one is closed.",
    ),
    ErrorCode.AMENDMENT_ALREADY_APPLIED: (409, "This amendment has already been applied."),
    ErrorCode.CLOSED_PERIOD_LOCKED: (
        409,
        "Policy does not allow a closed period to be reopened.",
    ),
    ErrorCode.AMENDMENT_FAILS_CHECKS: (
        409,
        "The amended terms do not pass the six checks.",
    ),
    ErrorCode.AMENDMENT_TYPE_INVALID: (
        400,
        "Those terms do not match the kind of amendment this is.",
    ),
    ErrorCode.UNKNOWN_MESSAGE_TYPE: (
        400,
        "That is not a confirmation type this system reads.",
    ),
    ErrorCode.CONFIRMATION_NOT_FOUND: (404, "That confirmation does not exist."),
    ErrorCode.ALREADY_MATCHED: (409, "This confirmation is already matched to a deal."),
    ErrorCode.SETTLEMENT_BREAK: (
        409,
        "Two of the three sources agree and the third does not.",
    ),
    ErrorCode.NO_INVESTMENT_POLICY: (
        400,
        "Set a liquidity buffer, a maturity ladder and the cover targets before "
        "running the advisory layer.",
    ),
    ErrorCode.RUN_NOT_FOUND: (404, "That advisory run does not exist."),
    ErrorCode.ALREADY_DECIDED: (
        409,
        "Somebody has already decided on this recommendation.",
    ),
    ErrorCode.RECOMMENDATION_EXPIRED: (
        409,
        "A later run has replaced this recommendation.",
    ),
    ErrorCode.REJECTION_REASON_REQUIRED: (
        400,
        "Say why, so the next run can learn from it.",
    ),
    ErrorCode.HEDGE_EXCEEDS_EXPOSURE: (
        409,
        "This link would cover more than is owed.",
    ),
    ErrorCode.NOT_AN_FX_FORWARD: (
        409,
        "Only a forward can be linked to a currency obligation.",
    ),
    ErrorCode.NOT_AUTHENTICATED: (401, "Sign in first."),
    ErrorCode.ROLE_NOT_HELD: (
        403,
        "This amount needs a signature from somebody who holds that role.",
    ),
    ErrorCode.SEGREGATION_OF_DUTIES: (
        403,
        "A deal cannot be approved by the person who proposed it.",
    ),
}

#: Thirty-eight from document 2, plus the three identity codes added in
#: phase 1.5. The documents describe a system with no identity, so those
#: three have no entry to reconcile against.
DOCUMENTED_CODES = 38
IDENTITY_CODES = 3

#: Two more, for the amendment gate. Document 2 has no code for an amendment
#: that fails the checks because the documents do not gate an amendment at
#: all: `AmendmentService` moves the terms and reposts, and nothing re-tests
#: the position. That is a hole rather than a decision -- an amendment can
#: raise a principal past its limit, and the correction path in
#: `QueueService` already re-runs the checks on exactly the reasoning that
#: applies here. These two codes are the deviation, recorded rather than
#: quietly absorbed.
GATE_CODES = 2

assert (
    len(CATALOGUE)
    == len(ErrorCode)
    == DOCUMENTED_CODES + IDENTITY_CODES + GATE_CODES
), "The catalogue and the enumeration disagree."


class TreasuryError(Exception):
    """Raised by a service. Mapped to a status and a body by one handler.

    A service raises a code. It never chooses a status, because a status is a
    transport concern and the service layer knows nothing about transport.
    """

    def __init__(
        self,
        code: ErrorCode,
        message: str | None = None,
        field: str | None = None,
    ) -> None:
        self.code = code
        self.status, default = CATALOGUE[code]
        self.message = message or default
        self.field = field
        super().__init__(f"{code.value}: {self.message}")

    def body(self) -> dict:
        return {
            "error": {
                "code": self.code.value,
                "message": self.message,
                "field": self.field,
            }
        }
