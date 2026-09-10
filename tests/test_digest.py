"""The digest is what actually lands on a phone."""

from __future__ import annotations

from datetime import UTC, datetime

from scanner.digest import build, heartbeat
from scanner.models import Event, Observation

AT = datetime(2026, 9, 9, tzinfo=UTC)


def event(kind="appeared", watch="w", title="Patagonia Better Sweater", **changes):
    return Event(
        at=AT,
        kind=kind,
        watch_id=watch,
        observation=Observation(
            platform="vinted",
            entity_key="1",
            url="https://vinted.co.uk/items/1",
            title=title,
            attributes={
                "price": "29.88", "currency": "GBP", "brand": "Patagonia",
                "size": "L", "condition": "Very good",
            },
            extra={"image": "https://img/1.jpg"},
        ),
        changes=changes,
    )


def test_the_subject_counts_the_finds():
    assert "1 find" in build([event()]).subject
    assert "2 finds" in build([event(), event()]).subject


def test_a_single_watch_is_named_in_the_subject():
    digest = build([event(watch="pat")], watch_labels={"pat": "Patagonia fleece"})

    assert "Patagonia fleece" in digest.subject


def test_several_watches_are_counted_instead():
    digest = build([event(watch="a"), event(watch="b")])

    assert "2 watches" in digest.subject


def test_price_and_details_reach_both_bodies():
    digest = build([event()])

    for body in (digest.text_body, digest.html_body):
        assert "29.88" in body
        assert "Patagonia" in body
        assert "Very good" in body
        assert "https://vinted.co.uk/items/1" in body


def test_the_currency_becomes_a_symbol():
    assert "£29.88" in build([event()]).text_body


def test_a_thumbnail_is_used_when_there_is_one():
    assert "https://img/1.jpg" in build([event()]).html_body


def test_a_price_change_is_spelled_out():
    digest = build([event(kind="changed", price=("40.00", "29.88"))])

    assert "40.00" in digest.text_body
    assert "29.88" in digest.text_body


def test_back_in_stock_is_said_plainly():
    digest = build([event(kind="changed", available=(False, True))])

    assert "back in stock" in digest.text_body


def test_html_is_escaped_so_a_listing_title_cannot_inject_markup():
    digest = build([event(title='<script>alert("x")</script>')])

    assert "<script>" not in digest.html_body
    assert "&lt;script&gt;" in digest.html_body


def test_events_are_grouped_under_their_watch():
    digest = build(
        [event(watch="a"), event(watch="b")],
        watch_labels={"a": "Fleeces", "b": "Boots"},
    )

    assert "Fleeces" in digest.text_body
    assert "Boots" in digest.text_body


def test_the_heartbeat_reports_the_state_of_things():
    digest = heartbeat(watches=3, log_size=142)

    assert "heartbeat" in digest.subject
    assert "3" in digest.text_body
    assert "142" in digest.text_body
