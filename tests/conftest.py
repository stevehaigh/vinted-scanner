"""Shared test doubles.

Sources are exercised through a fake session backed by recorded fixtures, so the
suite never opens a socket and never fails because Vinted is having a bad day.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


def load_fixture(name: str) -> dict[str, Any]:
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


class FakeResponse:
    def __init__(self, payload: Any, status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code

    def json(self) -> Any:
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


class FakeSession:
    """Answers by matching a substring of the requested URL against ``routes``."""

    def __init__(self, routes: dict[str, Any], default: Any = None) -> None:
        self.routes = routes
        self.default = default if default is not None else FakeResponse({})
        self.headers: dict[str, str] = {}
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def get(self, url: str, params: dict[str, Any] | None = None, **_: Any) -> FakeResponse:
        self.calls.append((url, params or {}))
        for fragment, response in self.routes.items():
            if fragment in url:
                return response if isinstance(response, FakeResponse) else FakeResponse(response)
        return self.default


class CapturingNotifier:
    def __init__(self, fail: bool = False) -> None:
        self.sent: list[Any] = []
        self.fail = fail

    def send(self, digest: Any) -> None:
        if self.fail:
            raise RuntimeError("smtp exploded")
        self.sent.append(digest)


@pytest.fixture
def now() -> datetime:
    return datetime(2026, 9, 9, 12, 0, tzinfo=UTC)


@pytest.fixture
def vinted_session() -> FakeSession:
    return FakeSession({"/api/v2/catalog/items": load_fixture("vinted_catalog")})


@pytest.fixture
def shopify_session() -> FakeSession:
    return FakeSession({"products.json": load_fixture("shopify_products")})
