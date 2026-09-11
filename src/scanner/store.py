"""Append-only event log, partitioned by month, plus a little run state.

The log is the source of truth. It is line-oriented JSON so that git can
delta-compress an append, which a committed SQLite file could not: at roughly
2,900 scheduled runs a month, a binary database would add a near-full copy per
commit and put the repository into gigabyte territory within the year.

It stays small for a second reason - it is a *change* log. An observation that
matches what we already knew writes nothing at all.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Iterator
from datetime import date, datetime
from pathlib import Path
from typing import Any

from .models import Event, Observation

STATE_FILENAME = "state.json"
OBSERVATIONS_DIRNAME = "observations"


class Store:
    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.observations_dir = self.root / OBSERVATIONS_DIRNAME
        self.state_path = self.root / STATE_FILENAME

    # -- log ---------------------------------------------------------------

    def month_files(self) -> list[Path]:
        if not self.observations_dir.is_dir():
            return []
        return sorted(self.observations_dir.glob("*.jsonl"))

    def path_for(self, at: datetime) -> Path:
        return self.observations_dir / f"{at:%Y-%m}.jsonl"

    def read_events(self) -> Iterator[Event]:
        """Replay the whole log, oldest first."""
        for path in self.month_files():
            with path.open(encoding="utf-8") as handle:
                for line in handle:
                    line = line.strip()
                    if line:
                        yield Event.from_json_line(line)

    def events_after(self, cutoff: datetime | None) -> list[Event]:
        if cutoff is None:
            return list(self.read_events())
        return [e for e in self.read_events() if e.at > cutoff]

    def latest_attributes(self) -> dict[tuple[str, str], dict[str, Any]]:
        """Current known material attributes per entity, by replaying the log.

        Replay is cheap because the log only ever grew when something changed.
        """
        known: dict[tuple[str, str], dict[str, Any]] = {}
        for event in self.read_events():
            known[event.observation.identity] = event.observation.attributes
        return known

    def append(self, events: Iterable[Event]) -> int:
        """Append events, grouped into the right month file. Returns the count."""
        by_month: dict[Path, list[Event]] = {}
        for event in events:
            by_month.setdefault(self.path_for(event.at), []).append(event)

        written = 0
        for path, group in by_month.items():
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as handle:
                for event in group:
                    handle.write(event.to_json_line() + "\n")
                    written += 1
        return written

    # -- state -------------------------------------------------------------

    def read_state(self) -> dict[str, Any]:
        if not self.state_path.exists():
            return {}
        return json.loads(self.state_path.read_text(encoding="utf-8"))

    def write_state(self, state: dict[str, Any]) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        # Write-then-rename, so an interrupted run cannot leave half a file.
        scratch = self.state_path.with_suffix(".json.tmp")
        scratch.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        scratch.replace(self.state_path)

    @property
    def notified_through(self) -> datetime | None:
        raw = self.read_state().get("notified_through")
        return datetime.fromisoformat(raw.replace("Z", "+00:00")) if raw else None

    def mark_notified_through(self, at: datetime) -> None:
        state = self.read_state()
        state["notified_through"] = at.isoformat().replace("+00:00", "Z")
        self.write_state(state)

    @property
    def last_heartbeat(self) -> date | None:
        raw = self.read_state().get("last_heartbeat")
        return date.fromisoformat(raw) if raw else None

    def mark_heartbeat(self, on: date) -> None:
        state = self.read_state()
        state["last_heartbeat"] = on.isoformat()
        self.write_state(state)


def diff(
    observations: Iterable[Observation],
    known: dict[tuple[str, str], dict[str, Any]],
    *,
    at: datetime,
    watch_id: str,
) -> list[Event]:
    """Turn what a source can see now into events, given what we already knew.

    ``known`` is mutated as we go, so that two watches reporting the same entity
    in one run do not both claim it appeared.
    """
    events: list[Event] = []
    for observation in observations:
        previous = known.get(observation.identity)
        if previous is None:
            events.append(
                Event(at=at, kind="appeared", watch_id=watch_id, observation=observation)
            )
            known[observation.identity] = observation.attributes
            continue

        changes = {
            key: (previous.get(key), value)
            for key, value in observation.attributes.items()
            if previous.get(key) != value
        }
        if changes:
            events.append(
                Event(
                    at=at,
                    kind="changed",
                    watch_id=watch_id,
                    observation=observation,
                    changes=changes,
                )
            )
            known[observation.identity] = {**previous, **observation.attributes}
    return events
