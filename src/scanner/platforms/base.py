"""The ``Platform`` seam.

A platform adapter is a *pure function of its query*: it reports what it can
currently see and nothing else. It is handed a session rather than making one, so
tests can drive it from recorded fixtures without touching the network.

Deliberately stateless. The core owns every piece of durable state and does all
the diffing, which means an adapter has no cursor and therefore cannot get cursor
handling wrong.
"""

from __future__ import annotations

from typing import Any, Protocol

import requests

from ..models import Observation


class Platform(Protocol):
    #: Registry key, matching ``platform:`` in watches.yaml.
    name: str

    def fetch(self, query: dict[str, Any], session: requests.Session) -> list[Observation]:
        """Return everything currently visible for this query."""
        ...


class PlatformError(RuntimeError):
    """A platform could not answer. Fails one watch, never the whole run."""
