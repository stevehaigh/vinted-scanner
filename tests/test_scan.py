"""End-to-end through the one seam: config in, events and a digest out.

These are the tests that matter. Everything is injected - fake session, temp
store, capturing notifier, frozen clock - so a whole scan runs in microseconds
with no network and no clock skew.
"""

from __future__ import annotations

import copy
from datetime import timedelta

import pytest

from conftest import CapturingNotifier, FakeSession, load_fixture
from scanner.config import parse
from scanner.scan import run_scan
from scanner.store import Store


@pytest.fixture
def config():
    return parse(
        {
            "watches": [
                {
                    "id": "patagonia",
                    "label": "Patagonia fleece",
                    "source": "vinted",
                    "query": {"host": "www.vinted.co.uk", "search_text": "patagonia fleece"},
                    "notify_on": ["new_listing", "price_drop"],
                }
            ]
        }
    )


@pytest.fixture
def catalog():
    return load_fixture("vinted_catalog")


def scan(config, store, session, now, notifier=None, **kwargs):
    return run_scan(
        config=config,
        store=store,
        notifier=notifier,
        now=now,
        session_factory=lambda: session,
        **kwargs,
    )


class TestFirstRun:
    def test_everything_visible_counts_as_new(self, tmp_path, config, catalog, now):
        store = Store(tmp_path)
        notifier = CapturingNotifier()

        report = scan(config, store, FakeSession({"catalog/items": catalog}), now, notifier)

        assert report.scanned == 1
        assert len(report.appeared) == len(catalog["items"])
        assert report.changed == []
        assert report.notification_sent

    def test_the_digest_names_the_watch_and_lists_the_finds(self, tmp_path, config, catalog, now):
        notifier = CapturingNotifier()

        scan(config, Store(tmp_path), FakeSession({"catalog/items": catalog}), now, notifier)

        (digest,) = notifier.sent
        assert "Patagonia fleece" in digest.subject or "Patagonia fleece" in digest.text_body
        for item in catalog["items"]:
            assert item["title"] in digest.text_body
            assert item["title"] in digest.html_body

    def test_events_are_persisted(self, tmp_path, config, catalog, now):
        store = Store(tmp_path)

        scan(config, store, FakeSession({"catalog/items": catalog}), now, CapturingNotifier())

        assert len(list(Store(tmp_path).read_events())) == len(catalog["items"])


class TestSecondRun:
    def test_an_unchanged_rerun_is_completely_silent(self, tmp_path, config, catalog, now):
        store = Store(tmp_path)
        session = FakeSession({"catalog/items": catalog})
        scan(config, store, session, now, CapturingNotifier())
        before = len(list(store.read_events()))

        notifier = CapturingNotifier()
        report = scan(config, store, session, now + timedelta(minutes=15), notifier)

        assert report.events == []
        assert notifier.sent == []
        assert len(list(store.read_events())) == before

    def test_a_price_change_is_recorded_and_notified(self, tmp_path, config, catalog, now):
        store = Store(tmp_path)
        scan(config, store, FakeSession({"catalog/items": catalog}), now, CapturingNotifier())

        cheaper = copy.deepcopy(catalog)
        cheaper["items"][0]["price"]["amount"] = "1.00"
        notifier = CapturingNotifier()

        report = scan(
            config, store, FakeSession({"catalog/items": cheaper}),
            now + timedelta(minutes=15), notifier,
        )

        assert len(report.changed) == 1
        assert report.changed[0].changes["price"][1] == "1.00"
        assert notifier.sent

    def test_a_price_rise_is_recorded_but_not_notified(self, tmp_path, config, catalog, now):
        store = Store(tmp_path)
        scan(config, store, FakeSession({"catalog/items": catalog}), now, CapturingNotifier())

        dearer = copy.deepcopy(catalog)
        dearer["items"][0]["price"]["amount"] = "9999.00"
        notifier = CapturingNotifier()

        report = scan(
            config, store, FakeSession({"catalog/items": dearer}),
            now + timedelta(minutes=15), notifier,
        )

        assert len(report.changed) == 1  # recorded, for price history
        assert notifier.sent == []       # but not worth an email

    def test_a_rotating_photo_signature_changes_nothing(self, tmp_path, config, catalog, now):
        store = Store(tmp_path)
        scan(config, store, FakeSession({"catalog/items": catalog}), now, CapturingNotifier())

        rotated = copy.deepcopy(catalog)
        for item in rotated["items"]:
            item["photo"]["url"] = item["photo"]["url"].split("?")[0] + "?s=totally-different"
            item["favourite_count"] = (item.get("favourite_count") or 0) + 17
        notifier = CapturingNotifier()

        report = scan(
            config, store, FakeSession({"catalog/items": rotated}),
            now + timedelta(minutes=15), notifier,
        )

        assert report.events == []
        assert notifier.sent == []


class TestFailureIsolation:
    def test_one_dead_source_does_not_stop_the_others(self, tmp_path, catalog, now):
        config = parse(
            {
                "watches": [
                    {"id": "dead", "source": "shopify", "query": {}},
                    {"id": "alive", "source": "vinted", "query": {"search_text": "x"}},
                ]
            }
        )
        notifier = CapturingNotifier()

        session = FakeSession({"catalog/items": catalog})
        report = scan(config, Store(tmp_path), session, now, notifier)

        assert [f.watch_id for f in report.failures] == ["dead"]
        assert len(report.appeared) == len(catalog["items"])
        assert notifier.sent

    def test_a_source_that_chokes_on_its_response_fails_alone(self, tmp_path, catalog, now):
        """A changed API shape raises inside the mapper, not a SourceError."""
        config = parse(
            {
                "watches": [
                    {"id": "broken", "source": "vinted", "query": {"search_text": "a"}},
                    {"id": "fine", "source": "shopify", "query": {"base_url": "https://s"}},
                ]
            }
        )
        session = FakeSession(
            {
                "catalog/items": {"items": [{"title": "no id field"}]},
                "products.json": load_fixture("shopify_products"),
            }
        )

        report = scan(config, Store(tmp_path), session, now, CapturingNotifier())

        assert [f.watch_id for f in report.failures] == ["broken"]
        assert report.appeared

    def test_a_total_wipeout_reports_every_failure(self, tmp_path, now):
        config = parse({"watches": [{"id": "a", "source": "shopify", "query": {}}]})

        report = scan(config, Store(tmp_path), FakeSession({}), now, CapturingNotifier())

        assert len(report.failures) == report.scanned == 1


class TestNotificationDurability:
    def test_a_failed_send_leaves_the_watermark_untouched(self, tmp_path, config, catalog, now):
        store = Store(tmp_path)

        with pytest.raises(RuntimeError, match="smtp exploded"):
            scan(config, store, FakeSession({"catalog/items": catalog}), now,
                 CapturingNotifier(fail=True))

        assert store.notified_through is None

    def test_the_next_run_resends_what_the_failure_lost(self, tmp_path, config, catalog, now):
        store = Store(tmp_path)
        session = FakeSession({"catalog/items": catalog})
        with pytest.raises(RuntimeError):
            scan(config, store, session, now, CapturingNotifier(fail=True))

        notifier = CapturingNotifier()
        report = scan(config, store, session, now + timedelta(minutes=15), notifier)

        # Nothing new was observed, but the pending alerts still go out.
        assert report.events == []
        assert len(report.notified) == len(catalog["items"])
        assert notifier.sent

    def test_no_notifier_records_the_events_anyway(self, tmp_path, config, catalog, now):
        store = Store(tmp_path)

        report = scan(config, store, FakeSession({"catalog/items": catalog}), now, None)

        assert len(report.appeared) == len(catalog["items"])
        assert report.notification_sent is False
        assert store.notified_through is None


class TestHeartbeat:
    def test_fires_on_the_configured_weekday(self, tmp_path, config, now):
        store = Store(tmp_path)
        sunday = now + timedelta(days=(6 - now.weekday()) % 7)
        notifier = CapturingNotifier()

        report = scan(config, store, FakeSession({}), sunday, notifier, heartbeat_weekday=6)

        assert report.heartbeat_sent
        assert "heartbeat" in notifier.sent[-1].subject

    def test_stays_quiet_on_other_days(self, tmp_path, config, now):
        notifier = CapturingNotifier()
        monday = now - timedelta(days=now.weekday())

        report = scan(
            config, Store(tmp_path), FakeSession({}), monday, notifier, heartbeat_weekday=6
        )

        assert not report.heartbeat_sent

    def test_only_once_a_day(self, tmp_path, config, now):
        store = Store(tmp_path)
        sunday = now + timedelta(days=(6 - now.weekday()) % 7)
        scan(config, store, FakeSession({}), sunday, CapturingNotifier(), heartbeat_weekday=6)

        notifier = CapturingNotifier()
        report = scan(config, store, FakeSession({}), sunday + timedelta(minutes=15),
                      notifier, heartbeat_weekday=6)

        assert not report.heartbeat_sent
