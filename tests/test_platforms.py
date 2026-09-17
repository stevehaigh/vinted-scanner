"""Platforms map real API payloads onto observations."""

from __future__ import annotations

import pytest

from conftest import (
    FakeResponse,
    FakeSession,
    catalog_page,
    load_fixture_text,
    vinted_items,
)
from scanner.platforms import get_platform, platform_names
from scanner.platforms.base import PlatformError
from scanner.platforms.shopify import ShopifyPlatform
from scanner.platforms.vinted import VintedPlatform, build_catalog_params, parse_search_url
from scanner.platforms.vinted_catalog import parse_catalog, parse_label


def test_registry_knows_both_platforms():
    assert platform_names() == ["shopify", "vinted"]
    assert get_platform("vinted").name == "vinted"


def test_unknown_platform_names_the_alternatives():
    with pytest.raises(PlatformError, match="vinted"):
        get_platform("gumtree")


class TestVinted:
    """Vinted is read from the server-rendered catalog page.

    ``/api/v2/catalog/items`` was withdrawn: it 404s for every query while
    sibling ``/api/v2`` endpoints still answer JSON, so no header or cookie
    change brings it back and there is no point asking.
    """

    def test_maps_listings_to_observations(self, vinted_session):
        observations = VintedPlatform().fetch({"search_text": "patagonia"}, vinted_session)

        assert observations
        first = observations[0]
        assert first.platform == "vinted"
        assert first.entity_key.isdigit()
        assert first.url.startswith("https://www.vinted.co.uk/items/")
        assert first.title
        assert first.attributes["price"]
        assert first.attributes["currency"] == "GBP"
        assert first.attributes["brand"]
        assert first.attributes["size"]
        assert first.attributes["condition"]

    def test_currency_is_an_iso_code_not_a_symbol(self, vinted_session):
        # The page renders "110.00 £". Storing the symbol would make every
        # listing logged under the old API look like a changed observation.
        for observation in VintedPlatform().fetch({}, vinted_session):
            assert observation.attributes["currency"] == "GBP"

    def test_volatile_fields_are_never_material(self, vinted_session):
        first = VintedPlatform().fetch({}, vinted_session)[0]

        assert "image" not in first.attributes
        assert "favourites" not in first.attributes
        assert first.extra["image"]
        assert first.extra["total_price"]

    def test_the_url_drops_the_referrer_parameter(self, vinted_session):
        # Links on the page carry ?referrer=catalog. Keeping it would make the
        # stored URL depend on where we happened to find the listing.
        for observation in VintedPlatform().fetch({}, vinted_session):
            assert "?" not in observation.url

    def test_primes_the_session_before_asking_for_the_catalog(self, vinted_session):
        VintedPlatform().fetch({"host": "www.vinted.co.uk"}, vinted_session)

        assert vinted_session.calls[0][0] == "https://www.vinted.co.uk/"
        assert "/catalog" in vinted_session.calls[1][0]

    def test_it_never_calls_the_withdrawn_api(self, vinted_session):
        VintedPlatform().fetch({"search_text": "x"}, vinted_session)

        assert not any("/api/v2/catalog/items" in url for url, _ in vinted_session.calls)

    def test_list_filters_repeat_rather_than_joining(self, vinted_session):
        VintedPlatform().fetch(
            {"search_text": "x", "brand_ids": ["917025", "198238"], "size_ids": ["209"]},
            vinted_session,
        )

        _, params = vinted_session.calls[1]
        assert ("brand_ids[]", "917025") in params
        assert ("brand_ids[]", "198238") in params
        assert ("size_ids[]", "209") in params

    def test_non_200_is_a_platform_error(self):
        session = FakeSession({"/catalog": FakeResponse("", status_code=503)})

        with pytest.raises(PlatformError, match="503"):
            VintedPlatform().fetch({}, session)

    def test_markup_that_parses_to_nothing_is_a_platform_error(self):
        # Silence here would read as "nothing new" forever, which is the worst
        # possible failure for a scanner: it looks like it is working.
        session = FakeSession({"/catalog": FakeResponse("<html><body>rebuilt</body></html>")})

        with pytest.raises(PlatformError, match="markup has probably changed"):
            VintedPlatform().fetch({"host": "www.vinted.co.uk"}, session)


class TestVintedPaging:
    def test_one_page_by_default(self, vinted_session):
        VintedPlatform().fetch({"search_text": "x"}, vinted_session)

        catalog_calls = [c for c in vinted_session.calls if "/catalog" in c[0]]
        assert len(catalog_calls) == 1

    def test_asking_for_more_pages_walks_them(self):
        pages = {
            "1": catalog_page(vinted_items(2)),
            "2": catalog_page([{**i, "id": i["id"] + 500} for i in vinted_items(2)]),
            "3": catalog_page([{**i, "id": i["id"] + 900} for i in vinted_items(2)]),
        }

        class Paging(FakeSession):
            def get(self, url, params=None, **kw):
                self.calls.append((url, params or []))
                if "/catalog" not in url:
                    return FakeResponse("")
                page = dict(params or []).get("page", "1")
                return FakeResponse(pages[page])

        session = Paging({})
        observations = VintedPlatform().fetch({"search_text": "x", "pages": 3}, session)

        catalog_calls = [c for c in session.calls if "/catalog" in c[0]]
        assert len(catalog_calls) == 3
        assert ("page", "2") in catalog_calls[1][1]
        assert len(observations) == 6

    def test_a_page_adding_nothing_new_ends_the_walk(self, vinted_session):
        # The fake serves the same page every time, so page two is all repeats
        # and there is no point asking for page three.
        VintedPlatform().fetch({"search_text": "x", "pages": 5}, vinted_session)

        catalog_calls = [c for c in vinted_session.calls if "/catalog" in c[0]]
        assert len(catalog_calls) == 2

    def test_repeated_listings_across_pages_appear_once(self, vinted_session):
        # The fake serves the same page every time, so page two is all repeats.
        one = VintedPlatform().fetch({"search_text": "x"}, vinted_session)
        many = VintedPlatform().fetch({"search_text": "x", "pages": 3}, vinted_session)

        assert len(many) == len(one)
        assert len({o.entity_key for o in many}) == len(many)

    def test_paging_is_capped(self, vinted_session):
        VintedPlatform().fetch({"search_text": "x", "pages": 99}, vinted_session)

        catalog_calls = [c for c in vinted_session.calls if "/catalog" in c[0]]
        assert len(catalog_calls) <= 5


class TestVintedHosts:
    def test_an_unknown_host_is_refused_before_any_request(self):
        session = FakeSession({})

        with pytest.raises(PlatformError, match="not a known Vinted site"):
            VintedPlatform().fetch({"host": "www.vinted.example"}, session)

        assert session.calls == []

    def test_the_host_header_is_left_to_requests(self, vinted_session):
        VintedPlatform().fetch({"host": "www.vinted.co.uk"}, vinted_session)

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

    def test_lists_become_repeated_catalog_params(self):
        params = build_catalog_params({"brand_ids": ["53", "88"], "search_text": "x"})

        assert ("brand_ids[]", "53") in params
        assert ("brand_ids[]", "88") in params
        assert ("search_text", "x") in params


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


class TestVintedEmptyResults:
    """A search matching nothing is not a failure; unreadable markup is.

    Conflating them is the worst failure available to a scanner: it sits there
    reporting nothing new while being completely broken. Vinted renders an
    explicit empty state, which is what tells the two apart.
    """

    EMPTY_PAGE = (
        '<html><body><div class="feed-grid"></div>'
        '<h1 data-testid="search-empty-state--title">No items found</h1>'
        "</body></html>"
    )

    def test_an_empty_search_returns_no_listings_without_erroring(self):
        session = FakeSession({"/catalog": FakeResponse(self.EMPTY_PAGE)})

        assert VintedPlatform().fetch({"host": "www.vinted.co.uk"}, session) == []

    def test_a_page_with_the_grid_but_no_items_is_accepted(self):
        session = FakeSession(
            {"/catalog": FakeResponse('<html><body><div class="feed-grid"></div></body></html>')}
        )

        assert VintedPlatform().fetch({"host": "www.vinted.co.uk"}, session) == []

    def test_a_page_with_neither_grid_nor_empty_state_is_an_error(self):
        session = FakeSession({"/catalog": FakeResponse("<html><body>Welcome!</body></html>")})

        with pytest.raises(PlatformError, match="markup has probably changed"):
            VintedPlatform().fetch({"host": "www.vinted.co.uk"}, session)


class TestVintedPriceFormat:
    """Prices are canonicalised so formatting alone never reads as a change."""

    @pytest.mark.parametrize(
        ("rendered", "expected"),
        [
            ("24 £", "24.00"),
            ("24.0 £", "24.00"),
            ("24.00 £", "24.00"),
            ("1,234.50 £", "1234.50"),
            ("1 234,50 €", "1234.50"),
            ("€1.99", "1.99"),
        ],
    )
    def test_amounts_canonicalise_to_two_places(self, rendered, expected):
        _, _, prices = parse_label(f"An item, Brand: X, {rendered}")

        assert prices[0][0] == expected

    def test_symbols_become_iso_codes(self):
        # Storing "£" would make every listing recorded under the old JSON API
        # look like it had changed the first time it was seen again.
        for symbol, code in (("£", "GBP"), ("€", "EUR"), ("$", "USD")):
            _, _, prices = parse_label(f"An item, 10.00 {symbol}")
            assert prices[0][1] == code


class TestVintedLabelParsing:
    """The accessibility label is the only place the listing's fields live."""

    def test_a_title_containing_commas_survives(self):
        title, fields, prices = parse_label(
            "Patagonia Retro-X fleece jacket, size M, Brand: Patagonia, "
            "Condition: New without tags, Size: M, 110.00 £, 116.20 £"
        )

        assert title == "Patagonia Retro-X fleece jacket, size M"
        assert fields == {"brand": "Patagonia", "condition": "New without tags", "size": "M"}
        assert [p[0] for p in prices] == ["110.00", "116.20"]

    def test_a_size_ending_in_digits_is_not_mistaken_for_a_price(self):
        # "M / UK 12-14, 100.00 £" must not yield a price of 14.
        _, fields, prices = parse_label(
            "A fleece, Brand: Patagonia, Size: M / UK 12-14, 100.00 £, 105.70 £"
        )

        assert fields["size"] == "M / UK 12-14"
        assert [p[0] for p in prices] == ["100.00", "105.70"]

    def test_an_unknown_locale_still_yields_title_and_price(self):
        # Title and price come from the label's shape, not its vocabulary, so a
        # locale we have never seen degrades to a usable listing.
        title, fields, prices = parse_label(
            "Flisinis džemperis, Prekės ženklas: Patagonia, 45,00 €"
        )

        assert title == "Flisinis džemperis"
        assert prices[0] == ("45.00", "EUR")
        assert fields == {}

    def test_french_labels_map_to_our_field_names(self):
        _, fields, _ = parse_label("Polaire, Marque: Patagonia, Taille: M, État: Bon, 30,00 €")

        assert fields == {"brand": "Patagonia", "size": "M", "condition": "Bon"}

    def test_a_label_with_no_fields_at_all_is_still_a_title(self):
        title, fields, prices = parse_label("Just a thing")

        assert title == "Just a thing"
        assert fields == {}
        assert prices == []


class TestVintedRealMarkup:
    """Recorded from the live catalog page, so this is what we actually face."""

    def test_the_recorded_page_parses_completely(self):
        listings = parse_catalog(load_fixture_text("vinted_catalog.html"), "www.vinted.co.uk")

        assert len(listings) == 4
        for listing in listings:
            assert listing["id"].isdigit()
            assert listing["title"]
            assert listing["price"]
            assert listing["currency"] == "GBP"
            assert listing["url"].startswith("https://www.vinted.co.uk/items/")
            assert listing["image"]
            assert listing["brand"] and listing["size"] and listing["condition"]

    def test_a_listing_with_no_favourites_reads_as_zero_not_missing(self):
        listings = parse_catalog(load_fixture_text("vinted_catalog.html"), "www.vinted.co.uk")

        assert all(isinstance(listing["favourites"], int) for listing in listings)
        assert 0 in {listing["favourites"] for listing in listings}
