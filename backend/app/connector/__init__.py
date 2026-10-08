"""Treasury Register Connector — Phase 2 substrate.

Ports and adapters. The whole app talks to external systems through
the interfaces in ``ports``. Each port is bound to an adapter at
startup via ``registry.get(port_cls)``. Fakes match today's behaviour
so nothing user-visible changes until a real adapter is bound.

ADR-0004: this is a first-party integration surface; NEVER named
'Oracle Integration Cloud' anywhere in code or docs.

See ``PHASE_2_IMPLEMENTATION_PLAN.md`` for the full plan. This module
is Stage 1 of that plan.
"""

from app.connector import ports  # noqa: F401 — re-exported for callers
from app.connector.registry import get, reset  # noqa: F401
