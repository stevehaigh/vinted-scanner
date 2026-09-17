"""Vinted catalog listings, read from the public catalog page.

Vinted withdrew ``/api/v2/catalog/items``. It answers 404 with an HTML error
page for every query, while sibling endpoints under ``/api/v2`` still answer
JSON, so this is a withdrawal rather than a block on us: no User-Agent, cookie
or proxy change brings it back. There is no point spending a request per scan
finding that out again, so the catalog page is now the only path.

The catalog page is fully server-rendered and carries everything a listing
needs. See ``vinted_catalog`` for how it is read.

``/api/v2/brands`` still works, and ``brands()`` still uses it.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlparse

import requests

from ..models import Observation
from .base import PlatformError
from .vinted_catalog import looks_empty, parse_catalog

PARAMS_PATH = Path(__file__).with_name("vinted_params.json")
DEFAULT_HOST = "www.vinted.co.uk"
BRANDS_PATH = "/api/v2/brands"
CATALOG_PATH = "/catalog"
TIMEOUT = 30
MAX_PAGES = 5

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
        raise PlatformError(f"not a Vinted URL: {url!r}")

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


def build_catalog_params(query: dict[str, Any]) -> list[tuple[str, str]]:
    """Structured query -> public catalog querystring.

    List fields repeat (``brand_ids[]=1&brand_ids[]=2``) rather than joining
    with commas, which is what the page itself expects.
    """
    params: list[tuple[str, str]] = []
    for field in params_spec()["fields"]:
        value = query.get(field["name"])
        if value in (None, "", []):
            continue
        if field["list"]:
            values = value if isinstance(value, list) else [value]
            params.extend((field["url_param"], str(v)) for v in values)
        else:
            params.append((field["url_param"], str(value)))
    return params


class VintedPlatform:
    name = "vinted"

    def fetch(self, query: dict[str, Any], session: requests.Session) -> list[Observation]:
        host = query.get("host") or DEFAULT_HOST
        if host not in params_spec()["hosts"]:
            raise PlatformError(
                f"{host!r} is not a known Vinted site; add it to vinted_params.json if it should be"
            )

        self._prime(session, host)
        base_params = build_catalog_params(query)
        pages = max(1, min(int(query.get("pages", 1)), MAX_PAGES))

        listings: list[dict[str, Any]] = []
        seen: set[str] = set()
        for page in range(1, pages + 1):
            params = base_params if page == 1 else [*base_params, ("page", str(page))]
            response = session.get(f"https://{host}{CATALOG_PATH}", params=params, timeout=TIMEOUT)
            if response.status_code != 200:
                raise PlatformError(f"vinted {host} returned HTTP {response.status_code}")

            found = parse_catalog(response.text, host)
            if not found:
                # A search matching nothing is a legitimate empty result. Markup
                # we can no longer read is a failure. Conflating them would let
                # a broken scanner sit there looking like a quiet one, which is
                # the worst way for this to fail.
                if page == 1 and not looks_empty(response.text):
                    raise PlatformError(
                        f"vinted {host} catalog page parsed to no listings and shows no "
                        "empty-results state; the page markup has probably changed"
                    )
                break

            new = [item for item in found if item["id"] not in seen]
            seen.update(item["id"] for item in found)
            listings.extend(new)
            if not new:
                break

        return [self._to_observation(item, host) for item in listings]

    def brands(
        self, keyword: str, session: requests.Session, host: str = DEFAULT_HOST
    ) -> list[tuple[int, str]]:
        """Look up ``(id, title)`` pairs by name, for filling in ``brand_ids``.

        Vinted filters by brand id, not name, and the ids are not guessable.
        """
        if host not in params_spec()["hosts"]:
            raise PlatformError(f"{host!r} is not a known Vinted site")
        self._prime(session, host)
        response = session.get(
            f"https://{host}{BRANDS_PATH}", params={"keyword": keyword}, timeout=TIMEOUT
        )
        if response.status_code != 200:
            raise PlatformError(f"vinted {host} returned HTTP {response.status_code}")
        try:
            found = response.json()["brands"]
        except (ValueError, KeyError, TypeError) as exc:
            raise PlatformError(f"vinted {host} returned unexpected JSON: {exc}") from exc
        if not isinstance(found, list):
            raise PlatformError(f"vinted {host} returned no brand list")
        return [(int(b["id"]), str(b["title"])) for b in found if isinstance(b, dict)]

    def _prime(self, session: requests.Session, host: str) -> None:
        """Visit the homepage so Vinted sees a browser-like session.

        Headers are *assigned*, never ``setdefault``-ed: a fresh
        ``requests.Session`` already carries ``User-Agent: python-requests/x.y``,
        so setdefault silently leaves it in place and Vinted answers 403.
        """
        session.headers["User-Agent"] = BROWSER_USER_AGENT
        session.headers["Accept"] = (
            "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
        )
        session.headers["Accept-Language"] = "en-GB,en;q=0.9"
        try:
            session.get(f"https://{host}/", timeout=TIMEOUT)
        except requests.RequestException as exc:
            raise PlatformError(f"could not reach {host}: {exc}") from exc

    def _to_observation(self, item: dict[str, Any], host: str) -> Observation:
        return Observation(
            platform=self.name,
            entity_key=item["id"],
            url=item["url"],
            title=item["title"],
            # Material: diffed between runs.
            attributes={
                "price": item["price"],
                "currency": item["currency"],
                "brand": item["brand"],
                "size": item["size"],
                "condition": item["condition"],
            },
            # Informational: recorded, never diffed. Photo URLs carry a rotating
            # signature and favourite counts move constantly; diffing either
            # would manufacture change events forever.
            extra={
                "image": item["image"],
                "total_price": item["total_price"],
                "favourites": item["favourites"],
                "host": host,
            },
        )
