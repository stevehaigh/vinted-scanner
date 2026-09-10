"""SQLite, derived from the log on demand.

Never committed, never a source of truth. Delete it and rebuild it; a schema
change is a re-derive rather than a migration.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from .store import Store

SCHEMA = """
CREATE TABLE events (
    at          TEXT NOT NULL,
    kind        TEXT NOT NULL,
    watch_id    TEXT NOT NULL,
    source      TEXT NOT NULL,
    entity_key  TEXT NOT NULL,
    url         TEXT NOT NULL,
    title       TEXT NOT NULL,
    price       REAL,
    currency    TEXT,
    attributes  TEXT NOT NULL,
    extra       TEXT NOT NULL,
    changes     TEXT NOT NULL
);
CREATE INDEX events_entity ON events (source, entity_key, at);
CREATE INDEX events_watch  ON events (watch_id, at);
CREATE INDEX events_kind   ON events (kind, at);

CREATE VIEW price_history AS
  SELECT source, entity_key, title, url, at, price, currency
  FROM events WHERE price IS NOT NULL ORDER BY source, entity_key, at;
"""


def rebuild(store: Store, target: Path) -> int:
    target = Path(target)
    target.unlink(missing_ok=True)
    target.parent.mkdir(parents=True, exist_ok=True)

    connection = sqlite3.connect(target)
    try:
        connection.executescript(SCHEMA)
        rows = 0
        for event in store.read_events():
            observation = event.observation
            connection.execute(
                "INSERT INTO events VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    event.at.isoformat(),
                    event.kind,
                    event.watch_id,
                    observation.source,
                    observation.entity_key,
                    observation.url,
                    observation.title,
                    _as_float(observation.attributes.get("price")),
                    observation.attributes.get("currency"),
                    json.dumps(observation.attributes, sort_keys=True),
                    json.dumps(observation.extra, sort_keys=True),
                    json.dumps({k: list(v) for k, v in event.changes.items()}, sort_keys=True),
                ),
            )
            rows += 1
        connection.commit()
        return rows
    finally:
        connection.close()


def _as_float(value: object) -> float | None:
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
