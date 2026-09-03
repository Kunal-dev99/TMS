"""Step 3 of the build sequence. Who has to sign.

Reads the two thresholds from the policy version in force, not from a
constant. Every threshold in this system is data a customer owns, and a
number in this file would be the one place that stopped being true.

The verdict names the approver before the user commits rather than after,
which is the whole reason this runs during the check and not at approval
time.
"""

from app.models import PolicyVersion

ANALYST = "ANALYST"
HEAD_OF_TREASURY = "HEAD_OF_TREASURY"
CFO = "CFO"

#: How a role is said in a sentence. The client formats figures; the server
#: composes messages, so the phrasing belongs here.
PHRASING = {
    ANALYST: "An analyst",
    HEAD_OF_TREASURY: "The Head of Treasury",
    CFO: "The CFO",
}


class ApprovalRouter:
    def __init__(self, policy: PolicyVersion) -> None:
        self.policy = policy

    def required_approver(self, principal_pence: int) -> str:
        """At or below the analyst threshold, an analyst may sign. At or below
        the second, the Head of Treasury. Above it, the CFO."""
        if principal_pence <= self.policy.threshold_analyst_pence:
            return ANALYST
        if principal_pence <= self.policy.threshold_hot_pence:
            return HEAD_OF_TREASURY
        return CFO

    def phrase(self, role: str) -> str:
        return PHRASING.get(role, role)

    def may_sign(self, role_held: str, principal_pence: int) -> bool:
        """Whether a caller holding `role_held` may sign this amount.

        Nothing calls this yet. There is no identity in the system, so no
        caller has a role to check against, and phase 1.5 is the gate where
        that changes. The comparison lives here so that phase adds one call
        rather than a rule.
        """
        order = [ANALYST, HEAD_OF_TREASURY, CFO]
        required = self.required_approver(principal_pence)
        if role_held not in order:
            return False
        return order.index(role_held) >= order.index(required)
