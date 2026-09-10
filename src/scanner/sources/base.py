"""The ``Source`` seam.

A source is a *pure function of its query*: it reports what it can currently see
and nothing else. It is handed a session rather than making one, so tests can
drive it from recorded fixtures without touching the network.

Deliberately stateless. The core owns every piece of durable state and does all
the diffing, which means a source has no cursor and therefore cannot get cursor
handling wrong.
"""

from __future__ import annotations

from typing import Any, Protocol

import requests

from ..models import Observation


class Source(Protocol):
    #: Registry key, matching ``source:`` in watches.yaml.
    name: str

    def fetch(self, query: dict[str, Any], session: requests.Session) -> list[Observation]:
        """Return everything currently visible for this query."""
        ...


class SourceError(RuntimeError):
    """A source could not answer. Fails one watch, never the whole run."""
