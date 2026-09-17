"""Vinted catalog listings.

Vinted's old undocumented API endpoint now often returns 404. We still try it
first, but fall back to extracting listings from the public catalog page's
embedded structured data when needed.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlparse

import requests

from ..models import Observation
from .base import PlatformError

PARAMS_PATH = Path(__file__).with_name("vinted_params.json")
DEFAULT_HOST = "www.vinted.co.uk"
API_PATH = "/api/v2/catalog/items"
BRANDS_PATH = "/api/v2/brands"
CATALOG_PATH = "/catalog"
TIMEOUT = 30
ITEM_ID_RE = re.compile(r"/items/(\d+)")

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


def build_catalog_params(query: dict[str, Any]) -> list[tuple[str, str]]:
    """Structured query -> public catalog querystring."""
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


def _money(value: Any) -> str | None:
    """Vinted money objects are ``{"amount": "29.88", "currency_code": "GBP"}``."""
    if isinstance(value, dict):
        return value.get("amount")
    if isinstance(value, (int, float, str)):
        return str(value)
    return None


class VintedPlatform:
    name = "vinted"

    def fetch(self, query: dict[str, Any], session: requests.Session) -> list[Observation]:
        host = query.get("host") or DEFAULT_HOST
        if host not in params_spec()["hosts"]:
            raise PlatformError(
                f"{host!r} is not a known Vinted site; add it to vinted_params.json if it should be"
            )
        candidate_hosts = self._candidate_hosts(host)
        api_404_hosts: list[str] = []
        for candidate_host in candidate_hosts:
            self._prime(session, candidate_host)
            response = session.get(
                f"https://{candidate_host}{API_PATH}",
                params=build_api_params(query),
                timeout=TIMEOUT,
            )
            if response.status_code == 200:
                return [
                    self._to_observation(item, candidate_host)
                    for item in self._items(response, candidate_host)
                ]
            if response.status_code != 404:
                raise PlatformError(f"vinted {candidate_host} returned HTTP {response.status_code}")
            api_404_hosts.append(candidate_host)

        if len(api_404_hosts) != len(candidate_hosts):
            raise PlatformError(f"vinted {host} API failed")

        for candidate_host in candidate_hosts:
            self._prime(session, candidate_host)
            response = session.get(
                f"https://{candidate_host}{CATALOG_PATH}",
                params=build_catalog_params(query),
                timeout=TIMEOUT,
            )
            if response.status_code == 200:
                items = self._items_from_catalog_page(response.text, candidate_host)
                if items:
                    return [self._to_observation(item, candidate_host) for item in items]
                raise PlatformError(f"vinted {candidate_host} catalog page returned no listings")
            if response.status_code != 404:
                raise PlatformError(f"vinted {candidate_host} returned HTTP {response.status_code}")

        raise PlatformError(f"vinted {host} returned HTTP 404")

    def brands(
        self, keyword: str, session: requests.Session, host: str = DEFAULT_HOST
    ) -> list[tuple[int, str]]:
        """Look up ``(id, title)`` pairs by name, for filling in ``brand_ids``.

        Vinted filters by brand id, not name, and the ids are not guessable:
        Patagonia is 90804. Collaborations come back as separate brands.
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
        """Visit the homepage so Vinted sees browser-like session headers.

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
            raise PlatformError(f"could not reach {host}: {exc}") from exc

    def _candidate_hosts(self, host: str) -> list[str]:
        hosts = [host]
        if host.startswith("www."):
            hosts.append(host[4:])
        elif f"www.{host}" in params_spec()["hosts"]:
            hosts.append(f"www.{host}")
        return list(dict.fromkeys(hosts))

    def _items(self, response: requests.Response, host: str) -> list[dict[str, Any]]:
        try:
            items = response.json()["items"]
        except (ValueError, KeyError, TypeError) as exc:
            raise PlatformError(f"vinted {host} returned unexpected JSON: {exc}") from exc
        if not isinstance(items, list) or not all(isinstance(item, dict) for item in items):
            raise PlatformError(f"vinted {host} returned no item list")
        return items

    def _items_from_catalog_page(self, page: str, host: str) -> list[dict[str, Any]]:
        scripts = re.findall(
            r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
            page,
            flags=re.IGNORECASE | re.DOTALL,
        )
        for script in scripts:
            try:
                payload = json.loads(script.strip())
            except ValueError:
                continue
            items = self._items_from_ld_json(payload, host)
            if items:
                return items
        return []

    def _items_from_ld_json(self, payload: Any, host: str) -> list[dict[str, Any]]:
        if isinstance(payload, list):
            found: list[dict[str, Any]] = []
            for value in payload:
                found.extend(self._items_from_ld_json(value, host))
            return found
        if not isinstance(payload, dict):
            return []

        entries = payload.get("itemListElement")
        if payload.get("@type") == "ItemList" and isinstance(entries, list):
            found = [
                item
                for entry in entries
                if (item := self._item_from_ld_json_entry(entry, host))
            ]
            if found:
                return found

        for value in payload.values():
            found = self._items_from_ld_json(value, host)
            if found:
                return found
        return []

    def _item_from_ld_json_entry(self, entry: Any, host: str) -> dict[str, Any] | None:
        if not isinstance(entry, dict):
            return None
        raw_item = entry.get("item") if isinstance(entry.get("item"), dict) else entry
        url = raw_item.get("url")
        if not isinstance(url, str):
            return None
        url = url if "://" in url else f"https://{host}{url}"
        item_id = ITEM_ID_RE.search(urlparse(url).path or "")
        if item_id is None:
            return None

        offers = raw_item.get("offers")
        if isinstance(offers, list):
            offers = offers[0] if offers else {}
        if not isinstance(offers, dict):
            offers = {}

        brand = raw_item.get("brand")
        if isinstance(brand, dict):
            brand = brand.get("name")
        if not isinstance(brand, str):
            brand = None

        image = raw_item.get("image")
        if isinstance(image, list):
            image = image[0] if image else None
        if isinstance(image, dict):
            image = image.get("url") or image.get("contentUrl")
        photo = {"url": image} if isinstance(image, str) else {}

        return {
            "id": item_id.group(1),
            "title": raw_item.get("name") or raw_item.get("title") or "",
            "url": url,
            "price": {
                "amount": _money(offers.get("price")),
                "currency_code": offers.get("priceCurrency"),
            },
            "brand_title": brand,
            "photo": photo,
            "user": {},
            "is_visible": True,
        }

    def _to_observation(self, item: dict[str, Any], host: str) -> Observation:
        photo = item.get("photo") or {}
        user = item.get("user") or {}
        price = item.get("price") or {}
        if not isinstance(price, dict):
            price = {"amount": _money(price), "currency_code": item.get("currency")}
        total_item_price = item.get("total_item_price") or {}
        if not isinstance(total_item_price, dict):
            total_item_price = {"amount": _money(total_item_price)}
        return Observation(
            platform=self.name,
            entity_key=str(item["id"]),
            url=item.get("url") or f"https://{host}{item.get('path', '')}",
            title=item.get("title") or "",
            # Material: diffed between runs.
            attributes={
                "price": _money(price),
                "currency": price.get("currency_code"),
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
                "total_price": _money(total_item_price),
                "favourites": item.get("favourite_count"),
                "host": host,
            },
        )
