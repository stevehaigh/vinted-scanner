"""Load and validate watches.yaml."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from .models import Config, Watch
from .platforms import platform_names
from .rules import rule_names

DEFAULT_PATH = Path("watches.yaml")


class ConfigError(ValueError):
    """watches.yaml is wrong in a way we can explain."""


def load(path: Path | str = DEFAULT_PATH) -> Config:
    path = Path(path)
    if not path.exists():
        raise ConfigError(f"no config at {path}")
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise ConfigError(f"{path} is not valid YAML: {exc}") from exc
    return parse(raw)


def parse(raw: dict[str, Any]) -> Config:
    if not isinstance(raw, dict):
        raise ConfigError("config must be a mapping")

    defaults = raw.get("defaults")
    if defaults is None:
        defaults = {}
    if not isinstance(defaults, dict):
        raise ConfigError("'defaults' must be a mapping")
    entries = raw.get("watches")
    if not isinstance(entries, list):
        raise ConfigError("config needs a 'watches' list")

    known_platforms = platform_names()
    known_rules = rule_names()
    seen: set[str] = set()
    watches: list[Watch] = []

    for index, entry in enumerate(entries):
        where = f"watches[{index}]"
        if not isinstance(entry, dict):
            raise ConfigError(f"{where} must be a mapping")

        raw_id = entry.get("id")
        watch_id = "" if raw_id is None else str(raw_id).strip()
        if not watch_id:
            raise ConfigError(f"{where} needs an 'id'")
        if watch_id in seen:
            raise ConfigError(f"duplicate watch id {watch_id!r}")
        seen.add(watch_id)

        platform = entry.get("platform")
        if platform is None and "source" in entry:
            raise ConfigError(f"{where} ({watch_id}): 'source' is now called 'platform'")
        if platform not in known_platforms:
            raise ConfigError(
                f"{where} ({watch_id}) has unknown platform {platform!r}; "
                f"known: {', '.join(known_platforms)}"
            )

        query = entry.get("query")
        if not isinstance(query, dict):
            raise ConfigError(f"{where} ({watch_id}) needs a 'query' mapping")

        # An explicit empty list means "record, never email" - only a missing
        # key falls through to the defaults.
        notify_on = entry.get("notify_on")
        if notify_on is None:
            notify_on = defaults.get("notify_on")
        if notify_on is None:
            notify_on = ["new_listing"]
        if isinstance(notify_on, str):
            notify_on = [notify_on]
        if not isinstance(notify_on, list):
            raise ConfigError(f"{where} ({watch_id}) notify_on must be a list of rule names")
        unknown = [name for name in notify_on if name not in known_rules]
        if unknown:
            raise ConfigError(
                f"{where} ({watch_id}) has unknown notify_on {unknown}; "
                f"known: {', '.join(known_rules)}"
            )

        watches.append(
            Watch(
                id=str(watch_id),
                platform=str(platform),
                query=query,
                notify_on=tuple(notify_on),
                enabled=bool(entry.get("enabled", True)),
                label=str(entry.get("label", "")),
            )
        )

    return Config(watches=tuple(watches))
