"""The log round-trips, partitions by month, and only ever grows on change."""

from __future__ import annotations

from datetime import UTC, datetime

from scanner.models import Event, Observation
from scanner.store import Store, diff


def observation(key: str = "1", price: str = "10.00", **attrs) -> Observation:
    return Observation(
        platform="vinted",
        entity_key=key,
        url=f"https://example.com/{key}",
        title=f"Item {key}",
        attributes={"price": price, "currency": "GBP", **attrs},
        extra={"image": "https://img/1.jpg?s=rotating"},
    )


class TestRoundTrip:
    def test_an_event_survives_being_written_and_read(self, tmp_path, now):
        store = Store(tmp_path)
        original = Event(at=now, kind="appeared", watch_id="w", observation=observation())

        store.append([original])
        (recovered,) = store.read_events()

        assert recovered.at == original.at
        assert recovered.kind == "appeared"
        assert recovered.watch_id == "w"
        assert recovered.observation == original.observation

    def test_changes_survive_the_round_trip(self, tmp_path, now):
        store = Store(tmp_path)
        store.append(
            [
                Event(
                    at=now,
                    kind="changed",
                    watch_id="w",
                    observation=observation(price="8.00"),
                    changes={"price": ("10.00", "8.00")},
                )
            ]
        )

        (recovered,) = store.read_events()

        assert recovered.changes == {"price": ("10.00", "8.00")}

    def test_events_are_partitioned_by_month(self, tmp_path):
        store = Store(tmp_path)
        store.append(
            [
                Event(
                    at=datetime(2026, 8, 31, 23, 0, tzinfo=UTC),
                    kind="appeared",
                    watch_id="w",
                    observation=observation("a"),
                ),
                Event(
                    at=datetime(2026, 9, 1, 1, 0, tzinfo=UTC),
                    kind="appeared",
                    watch_id="w",
                    observation=observation("b"),
                ),
            ]
        )

        assert [p.name for p in store.month_files()] == ["2026-08.jsonl", "2026-09.jsonl"]
        assert len(list(store.read_events())) == 2

    def test_one_line_per_event(self, tmp_path, now):
        store = Store(tmp_path)
        store.append(
            [
                Event(at=now, kind="appeared", watch_id="w", observation=observation(str(i)))
                for i in range(5)
            ]
        )

        text = store.path_for(now).read_text(encoding="utf-8")
        assert len(text.strip().splitlines()) == 5


class TestDiff:
    def test_an_unseen_entity_has_appeared(self, now):
        events = diff([observation("1")], {}, at=now, watch_id="w")

        assert [e.kind for e in events] == ["appeared"]
        assert events[0].changes == {}

    def test_an_identical_observation_produces_nothing(self, now):
        known = {("vinted", "1"): {"price": "10.00", "currency": "GBP"}}

        assert diff([observation("1")], known, at=now, watch_id="w") == []

    def test_a_changed_attribute_produces_a_changed_event(self, now):
        known = {("vinted", "1"): {"price": "10.00", "currency": "GBP"}}

        (event,) = diff([observation("1", price="8.00")], known, at=now, watch_id="w")

        assert event.kind == "changed"
        assert event.changes == {"price": ("10.00", "8.00")}

    def test_only_the_changed_attribute_is_reported(self, now):
        known = {("vinted", "1"): {"price": "10.00", "currency": "GBP"}}

        (event,) = diff([observation("1", price="8.00")], known, at=now, watch_id="w")

        assert set(event.changes) == {"price"}

    def test_two_watches_seeing_one_entity_claim_it_once(self, now):
        known: dict = {}

        first = diff([observation("1")], known, at=now, watch_id="a")
        second = diff([observation("1")], known, at=now, watch_id="b")

        assert len(first) == 1
        assert second == []

    def test_replaying_the_log_reconstructs_current_attributes(self, tmp_path, now):
        store = Store(tmp_path)
        store.append(diff([observation("1", price="10.00")], {}, at=now, watch_id="w"))
        store.append(
            diff(
                [observation("1", price="8.00")],
                store.latest_attributes(),
                at=now,
                watch_id="w",
            )
        )

        assert store.latest_attributes()[("vinted", "1")]["price"] == "8.00"


class TestState:
    def test_missing_state_reads_as_empty(self, tmp_path):
        assert Store(tmp_path).notified_through is None
        assert Store(tmp_path).last_heartbeat is None

    def test_the_watermark_round_trips(self, tmp_path, now):
        store = Store(tmp_path)
        store.mark_notified_through(now)

        assert Store(tmp_path).notified_through == now

    def test_events_after_the_watermark_excludes_earlier_ones(self, tmp_path, now):
        store = Store(tmp_path)
        earlier = now.replace(hour=10)
        store.append(
            [
                Event(at=earlier, kind="appeared", watch_id="w", observation=observation("old")),
                Event(at=now, kind="appeared", watch_id="w", observation=observation("new")),
            ]
        )

        pending = store.events_after(earlier)

        assert [e.observation.entity_key for e in pending] == ["new"]

    def test_heartbeat_date_round_trips(self, tmp_path, now):
        store = Store(tmp_path)
        store.mark_notified_through(now)
        store.mark_heartbeat(now.date())

        reopened = Store(tmp_path)
        assert reopened.last_heartbeat == now.date()
        assert reopened.notified_through == now


def test_log_lines_from_before_the_rename_still_read():
    from scanner.models import Event

    old = (
        '{"at": "2026-09-10T08:18:19Z", "kind": "appeared", "watch_id": "w", '
        '"source": "vinted", "entity_key": "1", "url": "u", "title": "t"}'
    )

    assert Event.from_json_line(old).observation.platform == "vinted"
