"""Shared test doubles.

Platforms are exercised through a fake session backed by recorded fixtures, so the
suite never opens a socket and never fails because Vinted is having a bad day.
"""

from __future__ import annotations

import html as html_module
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


def load_fixture(name: str) -> dict[str, Any]:
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


def load_fixture_text(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


class FakeResponse:
    def __init__(self, payload: Any, status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code
        if isinstance(payload, str):
            self.text = payload
        else:
            try:
                self.text = json.dumps(payload)
            except TypeError:
                self.text = str(payload)

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
    return FakeSession({"/catalog": FakeResponse(load_fixture_text("vinted_catalog.html"))})


@pytest.fixture
def shopify_session() -> FakeSession:
    return FakeSession({"products.json": load_fixture("shopify_products")})


def catalog_page(items: list[dict[str, Any]]) -> str:
    """Build a Vinted catalog page in the real markup shape.

    The recorded fixture proves the parser copes with a real page; this builder
    lets a test vary one price without hand-editing 7MB of HTML.
    """
    blocks = []
    for item in items:
        item_id = str(item["id"])
        price = item.get("price", "10.00")
        total = item.get("total_price", price)
        label = (
            f"{item.get('title', 'Item')}, "
            f"Brand: {item.get('brand', 'Patagonia')}, "
            f"Condition: {item.get('condition', 'Very good')}, "
            f"Size: {item.get('size', 'M')}, "
            f"{price} £, {total} £"
        )
        escaped = html_module.escape(label, quote=True)
        slug = item.get("slug", "item")
        blocks.append(
            f'<div data-testid="grid-item">'
            f'<img src="{item.get("image", f"https://img/{item_id}.webp?s=sig")}" '
            f'alt="{escaped}" data-testid="product-item-id-{item_id}--image--img"/>'
            f'<button aria-label="Add to favourites, favourited by '
            f'{item.get("favourites", 3)} users" '
            f'data-testid="product-item-id-{item_id}--favourite"></button>'
            f'<a href="/items/{item_id}-{slug}?referrer=catalog" '
            f'data-testid="product-item-id-{item_id}--overlay-link" '
            f'title="{escaped}"></a>'
            f"</div>"
        )
    return "<!doctype html><html><body>" + "".join(blocks) + "</body></html>"


def vinted_items(count: int = 3, **overrides: Any) -> list[dict[str, Any]]:
    return [
        {"id": 9900000000 + n, "title": f"Patagonia fleece {n}", "price": f"{20 + n}.00",
         "total_price": f"{22 + n}.10", "slug": f"patagonia-fleece-{n}", **overrides}
        for n in range(count)
    ]
