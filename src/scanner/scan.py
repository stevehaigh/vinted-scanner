"""The whole scan, behind one function.

``run_scan`` is the highest seam in the system and the one the end-to-end tests
drive: configuration in, events appended and a digest sent out, with the store,
notifier, clock and HTTP session all injected.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import replace
from datetime import datetime

import requests

from . import digest as digest_module
from . import rules
from .models import Config, Event, Observation, RunReport, Watch, WatchFailure
from .notify import Notifier
from .sources import SourceError, get_source
from .store import Store, diff

log = logging.getLogger("scanner")

SessionFactory = Callable[[], requests.Session]


def run_scan(
    *,
    config: Config,
    store: Store,
    notifier: Notifier | None,
    now: datetime,
    session_factory: SessionFactory = requests.Session,
    heartbeat_weekday: int | None = None,
) -> RunReport:
    report = RunReport()
    known = store.latest_attributes()
    labels = {watch.id: watch.display_name for watch in config.watches}

    # Fetch everything before diffing anything, so an entity that two watches
    # both see is recorded once but credited to every watch that saw it.
    fetched: list[tuple[Watch, list[Observation]]] = []
    for watch in config.enabled_watches:
        report.scanned += 1
        try:
            source = get_source(watch.source)
            session = session_factory()
            observations = source.fetch(watch.query, session)
        except Exception as exc:
            # One dead site must never stop the others reporting - and a site
            # changing its response shape under us counts as dead. Anything
            # other than the expected failures gets a traceback in the log.
            expected = isinstance(exc, SourceError | requests.RequestException)
            log.warning("watch %s failed: %s", watch.id, exc, exc_info=not expected)
            report.failures.append(WatchFailure(watch_id=watch.id, error=str(exc)))
            continue

        report.observed += len(observations)
        fetched.append((watch, observations))

    seen_by: dict[tuple[str, str], list[str]] = {}
    for watch, observations in fetched:
        for observation in observations:
            seen_by.setdefault(observation.identity, []).append(watch.id)

    fresh_events: list[Event] = []
    for watch, observations in fetched:
        events = [
            replace(event, seen_by=tuple(seen_by[event.observation.identity]))
            for event in diff(observations, known, at=now, watch_id=watch.id)
        ]
        fresh_events.extend(events)
        log.info(
            "watch %s: %d observed, %d new, %d changed",
            watch.id,
            len(observations),
            sum(1 for e in events if e.kind == "appeared"),
            sum(1 for e in events if e.kind == "changed"),
        )

    if fresh_events:
        store.append(fresh_events)
    report.events = fresh_events

    _notify(config, store, notifier, report, labels, now)
    _heartbeat(config, store, notifier, report, now, heartbeat_weekday)
    return report


def _notify(
    config: Config,
    store: Store,
    notifier: Notifier | None,
    report: RunReport,
    labels: dict[str, str],
    now: datetime,
) -> None:
    """Send everything not yet notified, and only then advance the watermark.

    Reading pending work from the log rather than from this run's events means a
    failed send is retried next run instead of being lost.
    """
    notify_on = {watch.id: watch.notify_on for watch in config.watches}
    pending = [
        credited
        for event in store.events_after(store.notified_through)
        if (credited := _credit(event, notify_on)) is not None
    ]
    report.notified = pending
    if not pending:
        return
    if notifier is None:
        log.info("%d events to notify, but no notifier configured", len(pending))
        return

    notifier.send(digest_module.build(pending, watch_labels=labels))
    report.notification_sent = True
    store.mark_notified_through(now)


def _credit(event: Event, notify_on: dict[str, tuple[str, ...]]) -> Event | None:
    """The event as the first watch whose rules select it would report it.

    ``watch_id`` is whichever watch happened to run first; a second watch that
    also saw the entity may be the one that actually asked to hear about it.
    """
    for watch_id in dict.fromkeys((event.watch_id, *event.seen_by)):
        if rules.select([event], notify_on.get(watch_id, ("new_listing",))):
            return event if watch_id == event.watch_id else replace(event, watch_id=watch_id)
    return None


def _heartbeat(
    config: Config,
    store: Store,
    notifier: Notifier | None,
    report: RunReport,
    now: datetime,
    weekday: int | None,
) -> None:
    """A weekly "still alive" mail, so silence means nothing found, not broken."""
    if weekday is None or notifier is None or now.weekday() != weekday:
        return
    if store.last_heartbeat == now.date():
        return

    notifier.send(
        digest_module.heartbeat(
            watches=len(config.enabled_watches),
            log_size=sum(1 for _ in store.read_events()),
        )
    )
    store.mark_heartbeat(now.date())
    report.heartbeat_sent = True
