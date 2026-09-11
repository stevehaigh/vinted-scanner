"""The CLI surface people actually type."""

from __future__ import annotations

import json

import pytest

from scanner.cli import main


def test_import_url_prints_a_pasteable_watch(capsys):
    exit_code = main(
        ["import-url", "https://www.vinted.co.uk/catalog?search_text=patagonia%20fleece&price_to=60"]
    )
    parsed = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert parsed["platform"] == "vinted"
    assert parsed["id"] == "patagonia-fleece"
    assert parsed["query"]["search_text"] == "patagonia fleece"
    assert parsed["query"]["price_to"] == "60"


def test_import_url_accepts_an_explicit_id(capsys):
    main(["import-url", "https://www.vinted.fr/catalog?search_text=x", "--id", "chosen"])

    assert json.loads(capsys.readouterr().out)["id"] == "chosen"


def test_list_shows_the_configured_watches(capsys):
    assert main(["list"]) == 0
    assert capsys.readouterr().out.strip()


def test_a_missing_config_exits_non_zero(capsys, tmp_path):
    exit_code = main(["--config", str(tmp_path / "nope.yaml"), "list"])

    assert exit_code == 2
    assert "config error" in capsys.readouterr().err


def test_rebuild_db_derives_a_queryable_database(tmp_path, capsys):
    import sqlite3
    from datetime import UTC, datetime

    from scanner.models import Event, Observation
    from scanner.store import Store

    store = Store(tmp_path)
    store.append(
        [
            Event(
                at=datetime(2026, 9, 9, tzinfo=UTC),
                kind="appeared",
                watch_id="w",
                observation=Observation(
                    platform="vinted", entity_key="1", url="u", title="Fleece",
                    attributes={"price": "29.88", "currency": "GBP"},
                ),
            )
        ]
    )

    assert main(["--data-dir", str(tmp_path), "rebuild-db"]) == 0

    connection = sqlite3.connect(tmp_path / "scanner.db")
    assert connection.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 1
    price = connection.execute("SELECT price FROM price_history").fetchone()[0]
    assert price == pytest.approx(29.88)
    connection.close()


def test_invalid_yaml_is_a_config_error_not_a_traceback(capsys, tmp_path):
    bad = tmp_path / "watches.yaml"
    bad.write_text("watches: [\n  - id: x\n", encoding="utf-8")

    exit_code = main(["--config", str(bad), "list"])

    assert exit_code == 2
    assert "config error" in capsys.readouterr().err


def test_a_scan_without_email_configured_has_no_notifier(monkeypatch, tmp_path):
    """A console fallback would count as delivered and eat the scheduled digest."""
    from scanner import cli
    from scanner.models import RunReport

    for name in ("GMAIL_ADDRESS", "GMAIL_APP_PASSWORD", "HEARTBEAT_WEEKDAY"):
        monkeypatch.delenv(name, raising=False)
    seen = {}

    def fake_run_scan(**kwargs):
        seen.update(kwargs)
        return RunReport()

    monkeypatch.setattr(cli, "run_scan", fake_run_scan)

    assert main(["--data-dir", str(tmp_path), "scan"]) == 0
    assert seen["notifier"] is None


def test_a_failed_send_is_one_line_and_a_non_zero_exit(monkeypatch, tmp_path, capsys):
    from scanner import cli
    from scanner.notify import EmailError

    monkeypatch.setenv("GMAIL_ADDRESS", "a@example.com")
    monkeypatch.setenv("GMAIL_APP_PASSWORD", "x")

    def fake_run_scan(**kwargs):
        raise EmailError("could not send mail: boom")

    monkeypatch.setattr(cli, "run_scan", fake_run_scan)

    assert main(["--data-dir", str(tmp_path), "scan"]) == 1
    assert "email error: could not send mail: boom" in capsys.readouterr().err


@pytest.mark.parametrize("raw", ["sunday", "7", "-1"])
def test_a_bad_heartbeat_weekday_is_a_config_error(monkeypatch, tmp_path, capsys, raw):
    monkeypatch.setenv("HEARTBEAT_WEEKDAY", raw)

    assert main(["--data-dir", str(tmp_path), "scan", "--dry-run"]) == 2
    assert "HEARTBEAT_WEEKDAY" in capsys.readouterr().err


def test_brands_prints_ids_to_paste_into_brand_ids(monkeypatch, capsys):
    from conftest import FakeSession
    from scanner import cli

    session = FakeSession({"/api/v2/brands": {"brands": [{"id": 90804, "title": "Patagonia"}]}})
    monkeypatch.setattr(cli.requests, "Session", lambda: session)

    assert main(["brands", "patagonia"]) == 0
    assert "90804  Patagonia" in capsys.readouterr().out


def test_brands_with_no_match_exits_non_zero(monkeypatch, capsys):
    from conftest import FakeSession
    from scanner import cli

    session = FakeSession({"/api/v2/brands": {"brands": []}})
    monkeypatch.setattr(cli.requests, "Session", lambda: session)

    assert main(["brands", "zzz"]) == 1
    assert "no brands match" in capsys.readouterr().err
