"""Core domain types.

The whole system is built on one idea: a source reports what it can *currently*
see, and the difference between that and what we have seen before is an event.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

EventKind = Literal["appeared", "changed"]


@dataclass(frozen=True, slots=True)
class Observation:
    """A single sighting of an entity by a source.

    ``attributes`` are *material*: they are diffed between runs, and a difference
    produces a ``changed`` event. ``extra`` is recorded but never diffed, which is
    where anything volatile belongs - Vinted photo URLs carry a rotating signature
    and favourite counts move constantly, so diffing either would produce a
    permanent stream of meaningless change events.
    """

    source: str
    entity_key: str
    url: str
    title: str
    attributes: dict[str, Any] = field(default_factory=dict)
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def identity(self) -> tuple[str, str]:
        return (self.source, self.entity_key)


@dataclass(frozen=True, slots=True)
class Event:
    """Something worth recording happened to an entity."""

    at: datetime
    kind: EventKind
    watch_id: str
    observation: Observation
    #: attribute name -> (before, after). Empty for ``appeared``.
    changes: dict[str, tuple[Any, Any]] = field(default_factory=dict)

    def to_json_line(self) -> str:
        payload = {
            "at": self.at.isoformat().replace("+00:00", "Z"),
            "kind": self.kind,
            "watch_id": self.watch_id,
            "source": self.observation.source,
            "entity_key": self.observation.entity_key,
            "url": self.observation.url,
            "title": self.observation.title,
            "attributes": self.observation.attributes,
            "extra": self.observation.extra,
            "changes": {k: list(v) for k, v in self.changes.items()},
        }
        return json.dumps(payload, sort_keys=True, ensure_ascii=False)

    @classmethod
    def from_json_line(cls, line: str) -> Event:
        raw = json.loads(line)
        return cls(
            at=datetime.fromisoformat(raw["at"].replace("Z", "+00:00")),
            kind=raw["kind"],
            watch_id=raw["watch_id"],
            observation=Observation(
                source=raw["source"],
                entity_key=raw["entity_key"],
                url=raw["url"],
                title=raw["title"],
                attributes=raw.get("attributes", {}),
                extra=raw.get("extra", {}),
            ),
            changes={k: (v[0], v[1]) for k, v in raw.get("changes", {}).items()},
        )


@dataclass(frozen=True, slots=True)
class Watch:
    """One thing being watched, on one source."""

    id: str
    source: str
    query: dict[str, Any]
    notify_on: tuple[str, ...] = ("new_listing",)
    enabled: bool = True
    label: str = ""

    @property
    def display_name(self) -> str:
        return self.label or self.id


@dataclass(frozen=True, slots=True)
class Config:
    watches: tuple[Watch, ...]

    @property
    def enabled_watches(self) -> tuple[Watch, ...]:
        return tuple(w for w in self.watches if w.enabled)


@dataclass(frozen=True, slots=True)
class WatchFailure:
    watch_id: str
    error: str


@dataclass(slots=True)
class RunReport:
    """What one scan did. Returned by ``run_scan`` so callers can log or assert."""

    scanned: int = 0
    observed: int = 0
    events: list[Event] = field(default_factory=list)
    notified: list[Event] = field(default_factory=list)
    failures: list[WatchFailure] = field(default_factory=list)
    notification_sent: bool = False
    heartbeat_sent: bool = False

    @property
    def appeared(self) -> list[Event]:
        return [e for e in self.events if e.kind == "appeared"]

    @property
    def changed(self) -> list[Event]:
        return [e for e in self.events if e.kind == "changed"]
