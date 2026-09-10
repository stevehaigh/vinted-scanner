"""Command line entry point."""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

from . import config as config_module
from . import db as db_module
from .notify import ConsoleNotifier, EmailError, EmailNotifier, EmailSettings
from .scan import run_scan
from .sources.vinted import parse_search_url
from .store import Store

DEFAULT_DATA_DIR = Path("data")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="scanner", description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    parser.add_argument("--config", type=Path, default=config_module.DEFAULT_PATH)
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)

    scan = sub.add_parser("scan", help="run every enabled watch once")
    scan.add_argument(
        "--dry-run",
        action="store_true",
        help="print the digest instead of emailing, and write nothing",
    )

    sub.add_parser("rebuild-db", help="derive a queryable SQLite database from the log")
    sub.add_parser("list", help="show configured watches")

    imp = sub.add_parser("import-url", help="turn a pasted Vinted search URL into a watch")
    imp.add_argument("url")
    imp.add_argument("--id", default=None, help="watch id (default: derived from search text)")

    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(message)s",
    )

    try:
        return _dispatch(args)
    except config_module.ConfigError as exc:
        print(f"config error: {exc}", file=sys.stderr)
        return 2
    except EmailError as exc:
        # The watermark was not advanced, so the digest goes out next run.
        print(f"email error: {exc}", file=sys.stderr)
        return 1


def _dispatch(args: argparse.Namespace) -> int:
    if args.command == "import-url":
        return _import_url(args.url, args.id)
    if args.command == "list":
        return _list(args.config)
    if args.command == "rebuild-db":
        store = Store(args.data_dir)
        rows = db_module.rebuild(store, args.data_dir / "scanner.db")
        print(f"rebuilt {args.data_dir / 'scanner.db'} from {rows} events")
        return 0
    return _scan(args)


def _scan(args: argparse.Namespace) -> int:
    config = config_module.load(args.config)
    store = Store(args.data_dir)

    if args.dry_run:
        # A scratch store keeps a dry run from touching the real log.
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            scratch = Store(Path(tmp))
            for path in store.month_files():
                (scratch.observations_dir).mkdir(parents=True, exist_ok=True)
                (scratch.observations_dir / path.name).write_bytes(path.read_bytes())
            if store.state_path.exists():
                scratch.state_path.write_bytes(store.state_path.read_bytes())
            report = run_scan(
                config=config,
                store=scratch,
                notifier=ConsoleNotifier(),
                now=datetime.now(UTC),
            )
    else:
        settings = EmailSettings.from_env()
        # No email means no notifier at all: a console fallback would count as
        # delivered and advance the watermark, eating alerts the scheduled run
        # was meant to send. Use --dry-run to see the digest locally.
        notifier = EmailNotifier(settings) if settings else None
        if settings is None:
            logging.getLogger("scanner").warning(
                "GMAIL_ADDRESS / GMAIL_APP_PASSWORD not set - nothing will be sent"
            )
        weekday = os.environ.get("HEARTBEAT_WEEKDAY")
        report = run_scan(
            config=config,
            store=store,
            notifier=notifier,
            now=datetime.now(UTC),
            heartbeat_weekday=int(weekday) if weekday not in (None, "") else None,
        )

    print(
        f"scanned {report.scanned} watches, {report.observed} observed, "
        f"{len(report.appeared)} new, {len(report.changed)} changed, "
        f"{len(report.notified)} notified"
    )
    for failure in report.failures:
        print(f"  ! {failure.watch_id}: {failure.error}", file=sys.stderr)

    # A failed watch is worth surfacing in the Actions log, but only a total
    # wipeout is worth failing the run over.
    if report.failures and len(report.failures) == report.scanned:
        return 1
    return 0


def _list(path: Path) -> int:
    config = config_module.load(path)
    for watch in config.watches:
        mark = " " if watch.enabled else "-"
        print(f"{mark} {watch.id:24} {watch.source:10} {', '.join(watch.notify_on)}")
    return 0


def _import_url(url: str, watch_id: str | None) -> int:
    query = parse_search_url(url)
    derived = watch_id or (
        str(query.get("search_text", "watch")).lower().replace(" ", "-")[:40] or "watch"
    )
    print(
        json.dumps(
            {
                "id": derived,
                "source": "vinted",
                "enabled": True,
                "notify_on": ["new_listing"],
                "query": query,
            },
            indent=2,
        )
    )
    return 0
