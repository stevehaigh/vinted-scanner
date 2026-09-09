"""Shopify storefronts, via the unauthenticated product feed.

Two of the retailers on the shortlist (Private White V.C., Derek Rose) run stock
Shopify and serve ``/collections/{collection}/products.json`` without auth, so a
single adapter covers both with the base URL as configuration.

Observations are emitted **per variant**, not per product: price and availability
live on the variant, and those are the attributes the price-drop and
back-in-stock rules care about.
"""

from __future__ import annotations

from typing import Any

import requests

from ..models import Observation
from .base import SourceError

BROWSER_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

TIMEOUT = 30
PAGE_SIZE = 250
MAX_PAGES = 10


class ShopifySource:
    name = "shopify"

    def fetch(self, query: dict[str, Any], session: requests.Session) -> list[Observation]:
        base = str(query.get("base_url", "")).rstrip("/")
        if not base:
            raise SourceError("shopify watch needs a base_url")

        collection = query.get("collection", "all")
        # products.json carries no currency, so the watch declares it.
        currency = query.get("currency", "GBP")
        limit = int(query.get("max_products", PAGE_SIZE))
        path = f"/collections/{collection}/products.json" if collection else "/products.json"

        # Assigned, not setdefault: a fresh Session already has a
        # python-requests User-Agent, which storefronts routinely reject.
        session.headers["User-Agent"] = BROWSER_USER_AGENT
        session.headers["Accept"] = "application/json"

        observations: list[Observation] = []
        fetched = 0
        for page in range(1, MAX_PAGES + 1):
            # Page on *products*, which is what the API counts. Paging on
            # observations would stop early on any store with several variants
            # per product - and most have one per size.
            remaining = limit - fetched
            if remaining <= 0:
                break

            response = session.get(
                f"{base}{path}",
                params={"limit": min(PAGE_SIZE, remaining), "page": page},
                timeout=TIMEOUT,
            )
            if response.status_code != 200:
                raise SourceError(f"shopify {base} returned HTTP {response.status_code}")

            try:
                products = response.json().get("products", [])
            except ValueError as exc:
                raise SourceError(f"shopify {base} returned unexpected JSON: {exc}") from exc

            if not products:
                break
            fetched += len(products)
            for product in products:
                observations.extend(self._observations_for(product, base, currency))

        return observations

    def _observations_for(
        self, product: dict[str, Any], base: str, currency: str = "GBP"
    ) -> list[Observation]:
        handle = product.get("handle", "")
        image = (product.get("images") or [{}])[0].get("src")
        product_id = product.get("id")

        results = []
        for variant in product.get("variants") or []:
            price = variant.get("price")
            compare_at = variant.get("compare_at_price")
            results.append(
                Observation(
                    source=self.name,
                    entity_key=f"{product_id}:{variant.get('id')}",
                    url=f"{base}/products/{handle}?variant={variant.get('id')}",
                    title=product.get("title") or "",
                    attributes={
                        "price": price,
                        "currency": currency,
                        "compare_at_price": compare_at,
                        "available": bool(variant.get("available")),
                        "variant": variant.get("title"),
                        "on_sale": _is_on_sale(price, compare_at),
                    },
                    extra={
                        "image": image,
                        "vendor": product.get("vendor"),
                        "product_type": product.get("product_type"),
                        "sku": variant.get("sku"),
                    },
                )
            )
        return results


def _is_on_sale(price: Any, compare_at: Any) -> bool:
    """Shopify marks a discount by setting compare_at_price above price."""
    try:
        return compare_at is not None and float(compare_at) > float(price)
    except (TypeError, ValueError):
        return False
