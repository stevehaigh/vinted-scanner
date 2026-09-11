"""Vinted, via its undocumented catalog API.

Vinted looks like a scraping target but isn't. Hitting the locale homepage sets
``access_token_web`` and ``anon_id`` cookies, after which ``/api/v2/catalog/items``
answers with clean JSON. A spike confirmed this works from a datacenter IP with
no proxy, so unlike the reference implementation there is no proxy pool here.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlparse

import requests

from ..models import Observation
from .base import SourceError

PARAMS_PATH = Path(__file__).with_name("vinted_params.json")
DEFAULT_HOST = "www.vinted.co.uk"
API_PATH = "/api/v2/catalog/items"
BRANDS_PATH = "/api/v2/brands"
TIMEOUT = 30

BROWSER_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)


@lru_cache(maxsize=1)
def params_spec() -> dict[str, Any]:
    return json.loads(PARAMS_PATH.read_text(encoding="utf-8"))


def parse_search_url(url: str) -> dict[str, Any]:
    """Turn a pasted Vinted search URL into the structured query we store.

    The URL is an import affordance only - we never store it. Field mapping comes
    from ``vinted_params.json``, which the UI reads too.
    """
    parsed = urlparse(url if "//" in url else f"https://{url}")
    if not parsed.netloc:
        raise SourceError(f"not a Vinted URL: {url!r}")

    pairs = parse_qsl(parsed.query, keep_blank_values=False)
    query: dict[str, Any] = {"host": parsed.netloc}

    for field in params_spec()["fields"]:
        values = [value for key, value in pairs if key == field["url_param"]]
        if not values:
            continue
        query[field["name"]] = values if field["list"] else values[0]

    for key, value in params_spec()["defaults"].items():
        query.setdefault(key, value)
    return query


def build_api_params(query: dict[str, Any]) -> dict[str, Any]:
    """Structured query -> API querystring. Lists become comma-joined strings."""
    params: dict[str, Any] = {}
    for field in params_spec()["fields"]:
        value = query.get(field["name"])
        if value in (None, "", []):
            continue
        params[field["name"]] = ",".join(str(v) for v in value) if field["list"] else value

    params["page"] = 1
    params["per_page"] = query.get("per_page", params_spec()["defaults"]["per_page"])
    return params


def _money(value: Any) -> str | None:
    """Vinted money objects are ``{"amount": "29.88", "currency_code": "GBP"}``."""
    if isinstance(value, dict):
        return value.get("amount")
    return None


class VintedSource:
    name = "vinted"

    def fetch(self, query: dict[str, Any], session: requests.Session) -> list[Observation]:
        host = query.get("host") or DEFAULT_HOST
        if host not in params_spec()["hosts"]:
            raise SourceError(
                f"{host!r} is not a known Vinted site; add it to vinted_params.json if it should be"
            )
        self._prime(session, host)

        response = session.get(
            f"https://{host}{API_PATH}",
            params=build_api_params(query),
            timeout=TIMEOUT,
        )
        if response.status_code != 200:
            raise SourceError(f"vinted {host} returned HTTP {response.status_code}")

        try:
            items = response.json()["items"]
        except (ValueError, KeyError, TypeError) as exc:
            raise SourceError(f"vinted {host} returned unexpected JSON: {exc}") from exc
        if not isinstance(items, list):
            raise SourceError(f"vinted {host} returned no item list")

        return [self._to_observation(item, host) for item in items]

    def brands(
        self, keyword: str, session: requests.Session, host: str = DEFAULT_HOST
    ) -> list[tuple[int, str]]:
        """Look up ``(id, title)`` pairs by name, for filling in ``brand_ids``.

        Vinted filters by brand id, not name, and the ids are not guessable:
        Patagonia is 90804. Collaborations come back as separate brands.
        """
        if host not in params_spec()["hosts"]:
            raise SourceError(f"{host!r} is not a known Vinted site")
        self._prime(session, host)
        response = session.get(
            f"https://{host}{BRANDS_PATH}", params={"keyword": keyword}, timeout=TIMEOUT
        )
        if response.status_code != 200:
            raise SourceError(f"vinted {host} returned HTTP {response.status_code}")
        try:
            found = response.json()["brands"]
        except (ValueError, KeyError, TypeError) as exc:
            raise SourceError(f"vinted {host} returned unexpected JSON: {exc}") from exc
        return [(int(b["id"]), str(b["title"])) for b in found if isinstance(b, dict)]

    def _prime(self, session: requests.Session, host: str) -> None:
        """Visit the homepage so the API will talk to us.

        Headers are *assigned*, never ``setdefault``-ed: a fresh
        ``requests.Session`` already carries ``User-Agent: python-requests/x.y``,
        so setdefault silently leaves it in place and Vinted answers 403.
        """
        session.headers["User-Agent"] = BROWSER_USER_AGENT
        session.headers["Accept"] = "application/json, text/plain, */*"
        session.headers["Accept-Language"] = "en-GB,en;q=0.9"
        try:
            session.get(f"https://{host}/", timeout=TIMEOUT)
        except requests.RequestException as exc:
            raise SourceError(f"could not reach {host}: {exc}") from exc

    def _to_observation(self, item: dict[str, Any], host: str) -> Observation:
        photo = item.get("photo") or {}
        user = item.get("user") or {}
        return Observation(
            source=self.name,
            entity_key=str(item["id"]),
            url=item.get("url") or f"https://{host}{item.get('path', '')}",
            title=item.get("title") or "",
            # Material: diffed between runs.
            attributes={
                "price": _money(item.get("price")),
                "currency": (item.get("price") or {}).get("currency_code"),
                "brand": item.get("brand_title") or None,
                "size": item.get("size_title") or None,
                "condition": item.get("status") or None,
                "seller": user.get("login") or None,
                "visible": bool(item.get("is_visible", True)),
            },
            # Informational: recorded, never diffed. Photo URLs carry a rotating
            # signature and favourite counts move constantly; diffing either
            # would manufacture change events forever.
            extra={
                "image": photo.get("url"),
                "total_price": _money(item.get("total_item_price")),
                "favourites": item.get("favourite_count"),
                "host": host,
            },
        )
