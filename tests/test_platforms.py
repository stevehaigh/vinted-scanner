"""Platforms map real API payloads onto observations."""

from __future__ import annotations

import pytest

from conftest import FakeResponse, FakeSession
from scanner.platforms import get_platform, platform_names
from scanner.platforms.base import PlatformError
from scanner.platforms.shopify import ShopifyPlatform
from scanner.platforms.vinted import VintedPlatform, build_api_params, parse_search_url


def test_registry_knows_both_platforms():
    assert platform_names() == ["shopify", "vinted"]
    assert get_platform("vinted").name == "vinted"


def test_unknown_platform_names_the_alternatives():
    with pytest.raises(PlatformError, match="vinted"):
        get_platform("gumtree")


class TestVinted:
    def test_maps_items_to_observations(self, vinted_session):
        observations = VintedPlatform().fetch({"search_text": "patagonia"}, vinted_session)

        assert observations
        first = observations[0]
        assert first.platform == "vinted"
        assert first.entity_key.isdigit()
        assert first.url.startswith("https://")
        assert first.title
        assert first.attributes["price"]
        assert first.attributes["currency"]

    def test_volatile_fields_are_never_material(self, vinted_session):
        # Photo URLs carry a rotating signature and favourite counts drift; if
        # either were diffed we would manufacture change events forever.
        first = VintedPlatform().fetch({}, vinted_session)[0]

        assert "image" not in first.attributes
        assert "favourites" not in first.attributes
        assert first.extra["image"]

    def test_primes_cookies_before_calling_the_api(self, vinted_session):
        VintedPlatform().fetch({"host": "www.vinted.co.uk"}, vinted_session)

        assert vinted_session.calls[0][0] == "https://www.vinted.co.uk/"
        assert "/api/v2/catalog/items" in vinted_session.calls[1][0]

    def test_non_200_is_a_platform_error(self):
        session = FakeSession({"/api/v2/catalog/items": FakeResponse({}, status_code=403)})

        with pytest.raises(PlatformError, match="403"):
            VintedPlatform().fetch({}, session)

    def test_unexpected_json_is_a_platform_error(self):
        session = FakeSession({"/api/v2/catalog/items": {"nope": True}})

        with pytest.raises(PlatformError, match="unexpected JSON"):
            VintedPlatform().fetch({}, session)


class TestVintedPayloadShape:
    def test_a_null_item_is_a_platform_error(self):
        session = FakeSession({"catalog/items": {"items": [None]}})

        with pytest.raises(PlatformError, match="item list"):
            VintedPlatform().fetch({"search_text": "x"}, session)


class TestVintedHosts:
    def test_an_unknown_host_is_refused_before_any_request(self):
        session = FakeSession({})

        with pytest.raises(PlatformError, match="not a known Vinted site"):
            VintedPlatform().fetch({"host": "evil.example", "search_text": "x"}, session)

        assert session.calls == []

    def test_the_host_header_is_left_to_requests(self, vinted_session):
        VintedPlatform().fetch({"host": "www.vinted.co.uk", "search_text": "x"}, vinted_session)

        assert "Host" not in vinted_session.headers


class TestVintedUrlImport:
    def test_parses_a_pasted_search_url(self):
        query = parse_search_url(
            "https://www.vinted.co.uk/catalog?search_text=nike%20shoes"
            "&price_to=50&currency=GBP&brand_ids[]=53&brand_ids[]=88"
        )

        assert query["host"] == "www.vinted.co.uk"
        assert query["search_text"] == "nike shoes"
        assert query["price_to"] == "50"
        assert query["brand_ids"] == ["53", "88"]

    def test_applies_defaults_for_anything_absent(self):
        query = parse_search_url("https://www.vinted.fr/catalog?search_text=veste")

        assert query["order"] == "newest_first"
        assert query["per_page"] == 40

    def test_explicit_order_survives_the_defaults(self):
        query = parse_search_url("https://www.vinted.fr/catalog?search_text=x&order=price_low_to_high")

        assert query["order"] == "price_low_to_high"

    def test_rejects_something_that_is_not_a_url(self):
        with pytest.raises(PlatformError):
            parse_search_url("")

    def test_lists_become_comma_joined_api_params(self):
        params = build_api_params({"brand_ids": ["53", "88"], "search_text": "x"})

        assert params["brand_ids"] == "53,88"
        assert params["per_page"] == 40


class TestShopify:
    def test_emits_one_observation_per_variant(self, shopify_session):
        payload = shopify_session.routes["products.json"]
        expected = sum(len(p["variants"]) for p in payload["products"])

        observations = ShopifyPlatform().fetch(
            {"base_url": "https://privatewhitevc.com", "max_products": 3}, shopify_session
        )

        assert len(observations) == expected

    def test_variant_key_is_stable_and_compound(self, shopify_session):
        first = ShopifyPlatform().fetch(
            {"base_url": "https://example.com", "max_products": 3}, shopify_session
        )[0]

        assert ":" in first.entity_key
        assert "available" in first.attributes
        assert "price" in first.attributes
        assert "on_sale" in first.attributes

    def test_requires_a_base_url(self, shopify_session):
        with pytest.raises(PlatformError, match="base_url"):
            ShopifyPlatform().fetch({}, shopify_session)

    def test_detects_a_discount_from_compare_at_price(self):
        platform = ShopifyPlatform()
        product = {
            "id": 1,
            "handle": "coat",
            "title": "Coat",
            "images": [{"src": "x"}],
            "variants": [
                {"id": 10, "price": "80.00", "compare_at_price": "120.00", "available": True},
                {"id": 11, "price": "120.00", "compare_at_price": None, "available": True},
            ],
        }

        discounted, full_price = platform._observations_for(product, "https://example.com")

        assert discounted.attributes["on_sale"] is True
        assert full_price.attributes["on_sale"] is False


class TestBrowserHeaders:
    """A fresh requests.Session already carries a python-requests User-Agent.

    Setting it with ``setdefault`` leaves that in place, and both Vinted and
    Shopify storefronts reject it. This is a regression guard for a live 403.
    """

    def test_vinted_overrides_a_preset_user_agent(self, vinted_session):
        vinted_session.headers["User-Agent"] = "python-requests/2.32.0"

        VintedPlatform().fetch({}, vinted_session)

        assert "python-requests" not in vinted_session.headers["User-Agent"]
        assert "Mozilla" in vinted_session.headers["User-Agent"]

    def test_shopify_overrides_a_preset_user_agent(self, shopify_session):
        shopify_session.headers["User-Agent"] = "python-requests/2.32.0"

        ShopifyPlatform().fetch({"base_url": "https://example.com"}, shopify_session)

        assert "Mozilla" in shopify_session.headers["User-Agent"]

    def test_vinted_sends_an_accept_language(self, vinted_session):
        VintedPlatform().fetch({}, vinted_session)

        assert vinted_session.headers["Accept-Language"]


class TestShopifyPagination:
    """The cap counts products, which is what the API pages on.

    Counting observations instead stops early on any store with several
    variants per product, and most have one variant per size.
    """

    @staticmethod
    def _store(total_products: int, variants_each: int):
        """A fake storefront that pages exactly the way Shopify does: offset
        ``(page - 1) * limit``, so a smaller limit re-reads earlier products."""

        def product(n: int):
            return {
                "id": n,
                "handle": f"p{n}",
                "title": f"Product {n}",
                "images": [{"src": "x"}],
                "variants": [
                    {"id": n * 1000 + v, "price": "10.00", "available": True}
                    for v in range(variants_each)
                ],
            }

        products = [product(n) for n in range(total_products)]
        calls = []

        class Paging(FakeSession):
            def get(self, url, params=None, **kw):
                params = params or {}
                calls.append(params)
                limit, page = params["limit"], params["page"]
                return FakeResponse({"products": products[(page - 1) * limit : page * limit]})

        return Paging({}), calls

    def test_pages_until_the_product_cap_is_reached(self):
        session, calls = self._store(total_products=600, variants_each=2)

        observations = ShopifyPlatform().fetch(
            {"base_url": "https://example.com", "max_products": 300}, session
        )

        # 300 products, two variants each, and never a product seen twice.
        assert len(calls) == 2
        assert len(observations) == 600
        assert len({o.entity_key for o in observations}) == 600
        assert {o.entity_key.split(":")[0] for o in observations} == {str(n) for n in range(300)}

    def test_a_short_page_is_the_last_page(self):
        session, calls = self._store(total_products=30, variants_each=1)

        observations = ShopifyPlatform().fetch({"base_url": "https://example.com"}, session)

        assert len(calls) == 1
        assert len(observations) == 30

    @pytest.mark.parametrize("cap", [0, -1, "all", 1.5, True, None])
    def test_a_cap_below_one_is_a_platform_error(self, shopify_session, cap):
        with pytest.raises(PlatformError, match="max_products"):
            ShopifyPlatform().fetch(
                {"base_url": "https://example.com", "max_products": cap}, shopify_session
            )

    def test_a_null_product_is_a_platform_error(self):
        session = FakeSession({"products.json": {"products": [None]}})

        with pytest.raises(PlatformError, match="product list"):
            ShopifyPlatform().fetch({"base_url": "https://example.com"}, session)

    def test_a_feed_that_is_not_an_object_is_a_platform_error(self):
        session = FakeSession({"products.json": []})

        with pytest.raises(PlatformError, match="product list"):
            ShopifyPlatform().fetch({"base_url": "https://example.com"}, session)

    def test_stops_when_a_page_comes_back_empty(self):
        class Empty(FakeSession):
            def get(self, url, params=None, **kw):
                return FakeResponse({"products": []})

        observations = ShopifyPlatform().fetch(
            {"base_url": "https://example.com", "max_products": 250}, Empty({})
        )

        assert observations == []


class TestShopifyCurrency:
    """products.json carries no currency, so the watch declares it."""

    def test_the_declared_currency_reaches_the_observation(self, shopify_session):
        observations = ShopifyPlatform().fetch(
            {"base_url": "https://example.com", "currency": "EUR"}, shopify_session
        )

        assert observations[0].attributes["currency"] == "EUR"

    def test_defaults_to_gbp(self, shopify_session):
        observations = ShopifyPlatform().fetch({"base_url": "https://example.com"}, shopify_session)

        assert observations[0].attributes["currency"] == "GBP"


class TestVintedBrandLookup:
    def test_returns_id_and_title_pairs(self):
        session = FakeSession(
            {
                "/api/v2/brands": {
                    "brands": [
                        {"id": 90804, "title": "Patagonia", "item_count": 12345},
                        {"id": 7, "title": "Patagonia x Something"},
                    ]
                }
            }
        )

        found = VintedPlatform().brands("patagonia", session)

        assert found == [(90804, "Patagonia"), (7, "Patagonia x Something")]
        assert session.calls[-1][1] == {"keyword": "patagonia"}

    def test_the_lookup_primes_cookies_like_a_search(self, vinted_session):
        vinted_session.routes["/api/v2/brands"] = {"brands": []}

        VintedPlatform().brands("x", vinted_session)

        assert vinted_session.calls[0][0] == "https://www.vinted.co.uk/"

    def test_a_brand_list_that_is_not_a_list_is_a_platform_error(self):
        session = FakeSession({"/api/v2/brands": {"brands": {"id": 1}}})

        with pytest.raises(PlatformError, match="no brand list"):
            VintedPlatform().brands("x", session)

    def test_a_missing_brand_list_is_a_platform_error(self):
        session = FakeSession({"/api/v2/brands": {"nope": 1}})

        with pytest.raises(PlatformError, match="unexpected JSON"):
            VintedPlatform().brands("x", session)
