"""Rules are pure predicates over events."""

from __future__ import annotations

import pytest

from scanner.models import Event, Observation
from scanner.rules import back_in_stock, new_listing, price_drop, select, went_on_sale


def event(kind="changed", **changes) -> Event:
    from datetime import UTC, datetime

    return Event(
        at=datetime(2026, 9, 9, tzinfo=UTC),
        kind=kind,
        watch_id="w",
        observation=Observation(source="s", entity_key="1", url="u", title="t"),
        changes=changes,
    )


def test_new_listing_matches_only_appearances():
    assert new_listing(event(kind="appeared"))
    assert not new_listing(event(price=("10", "8")))


@pytest.mark.parametrize(
    ("before", "after", "expected"),
    [("10.00", "8.00", True), ("8.00", "10.00", False), ("8.00", "8.00", False),
     (None, "8.00", False), ("10.00", "abc", False)],
)
def test_price_drop_only_fires_when_the_number_actually_falls(before, after, expected):
    assert price_drop(event(price=(before, after))) is expected


def test_price_drop_ignores_events_without_a_price_change():
    assert not price_drop(event(size=("M", "L")))
    assert not price_drop(event(kind="appeared"))


def test_back_in_stock_fires_only_on_the_false_to_true_edge():
    assert back_in_stock(event(available=(False, True)))
    assert not back_in_stock(event(available=(True, False)))


def test_went_on_sale_fires_only_on_the_false_to_true_edge():
    assert went_on_sale(event(on_sale=(False, True)))
    assert not went_on_sale(event(on_sale=(True, False)))


class TestSelect:
    def test_picks_events_matching_any_named_rule(self):
        events = [event(kind="appeared"), event(price=("10", "8")), event(size=("M", "L"))]

        assert len(select(events, ["new_listing"])) == 1
        assert len(select(events, ["new_listing", "price_drop"])) == 2

    def test_no_rules_selects_nothing(self):
        assert select([event(kind="appeared")], []) == []

    def test_unknown_rule_names_are_ignored(self):
        assert select([event(kind="appeared")], ["nonsense", "new_listing"]) != []

    def test_order_is_preserved(self):
        events = [event(kind="appeared"), event(price=("10", "8"))]

        assert select(events, ["new_listing", "price_drop"]) == events
