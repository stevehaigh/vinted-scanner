"""Load and validate watches.yaml."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from .models import Config, Watch
from .rules import rule_names
from .sources import source_names

DEFAULT_PATH = Path("watches.yaml")


class ConfigError(ValueError):
    """watches.yaml is wrong in a way we can explain."""


def load(path: Path | str = DEFAULT_PATH) -> Config:
    path = Path(path)
    if not path.exists():
        raise ConfigError(f"no config at {path}")
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return parse(raw)


def parse(raw: dict[str, Any]) -> Config:
    if not isinstance(raw, dict):
        raise ConfigError("config must be a mapping")

    defaults = raw.get("defaults") or {}
    entries = raw.get("watches")
    if not isinstance(entries, list):
        raise ConfigError("config needs a 'watches' list")

    known_sources = source_names()
    known_rules = rule_names()
    seen: set[str] = set()
    watches: list[Watch] = []

    for index, entry in enumerate(entries):
        where = f"watches[{index}]"
        if not isinstance(entry, dict):
            raise ConfigError(f"{where} must be a mapping")

        watch_id = entry.get("id")
        if not watch_id:
            raise ConfigError(f"{where} needs an 'id'")
        if watch_id in seen:
            raise ConfigError(f"duplicate watch id {watch_id!r}")
        seen.add(watch_id)

        source = entry.get("source")
        if source not in known_sources:
            raise ConfigError(
                f"{where} ({watch_id}) has unknown source {source!r}; "
                f"known: {', '.join(known_sources)}"
            )

        query = entry.get("query")
        if not isinstance(query, dict):
            raise ConfigError(f"{where} ({watch_id}) needs a 'query' mapping")

        notify_on = entry.get("notify_on") or defaults.get("notify_on") or ["new_listing"]
        if isinstance(notify_on, str):
            notify_on = [notify_on]
        unknown = [name for name in notify_on if name not in known_rules]
        if unknown:
            raise ConfigError(
                f"{where} ({watch_id}) has unknown notify_on {unknown}; "
                f"known: {', '.join(known_rules)}"
            )

        watches.append(
            Watch(
                id=str(watch_id),
                source=str(source),
                query=query,
                notify_on=tuple(notify_on),
                enabled=bool(entry.get("enabled", True)),
                label=str(entry.get("label", "")),
            )
        )

    return Config(watches=tuple(watches))
