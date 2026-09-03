"""Confirmations and matching.

Group 3. Ingest, list, match.

Empty in phase zero. Filled in phase one, one group at a time, replacing the
mock server group by group. A router validates, calls exactly one service and
returns. Anything longer than about ten lines here belongs in a service, and
a router that decides something is a defect.
"""

from fastapi import APIRouter

router = APIRouter(tags=["Confirmations and matching"])
