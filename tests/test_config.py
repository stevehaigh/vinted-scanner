"""watches.yaml is validated with errors that say what to fix."""

from __future__ import annotations

import pytest

from scanner.config import ConfigError, load, parse


def minimal(**overrides):
    watch = {"id": "w", "source": "vinted", "query": {"search_text": "x"}, **overrides}
    return {"watches": [watch]}


def test_parses_a_minimal_watch():
    config = parse(minimal())

    assert config.watches[0].id == "w"
    assert config.watches[0].notify_on == ("new_listing",)
    assert config.watches[0].enabled is True


def test_defaults_apply_when_a_watch_says_nothing():
    config = parse({"defaults": {"notify_on": ["price_drop"]}, "watches": minimal()["watches"]})

    assert config.watches[0].notify_on == ("price_drop",)


def test_a_watch_overrides_the_defaults():
    watches = minimal(notify_on=["new_listing"])["watches"]
    raw = {"defaults": {"notify_on": ["price_drop"]}, "watches": watches}

    assert parse(raw).watches[0].notify_on == ("new_listing",)


def test_enabled_watches_excludes_the_disabled_ones():
    raw = {
        "watches": [
            {"id": "on", "source": "vinted", "query": {}},
            {"id": "off", "source": "vinted", "query": {}, "enabled": False},
        ]
    }

    config = parse(raw)

    assert len(config.watches) == 2
    assert [w.id for w in config.enabled_watches] == ["on"]


@pytest.mark.parametrize(
    ("raw", "message"),
    [
        ({"watches": "nope"}, "watches"),
        ({"watches": [{"source": "vinted", "query": {}}]}, "id"),
        ({"watches": [{"id": "w", "source": "ebay", "query": {}}]}, "unknown source"),
        ({"watches": [{"id": "w", "source": "vinted"}]}, "query"),
        (minimal(notify_on=["teleport"]), "unknown notify_on"),
    ],
)
def test_bad_config_explains_itself(raw, message):
    with pytest.raises(ConfigError, match=message):
        parse(raw)


def test_duplicate_ids_are_rejected():
    raw = {"watches": [{"id": "w", "source": "vinted", "query": {}}] * 2}

    with pytest.raises(ConfigError, match="duplicate"):
        parse(raw)


def test_a_string_notify_on_is_accepted_as_one_rule():
    assert parse(minimal(notify_on="price_drop")).watches[0].notify_on == ("price_drop",)


def test_missing_file_is_a_config_error(tmp_path):
    with pytest.raises(ConfigError, match="no config"):
        load(tmp_path / "absent.yaml")


def test_the_repo_config_is_valid():
    # The committed watches.yaml must always parse, or every scan fails.
    assert load("watches.yaml").watches


def test_an_empty_notify_on_means_record_but_never_email():
    assert parse(minimal(notify_on=[])).watches[0].notify_on == ()


def test_ids_are_compared_as_strings():
    raw = {"watches": [minimal()["watches"][0] | {"id": 1}, minimal()["watches"][0] | {"id": "1"}]}

    with pytest.raises(ConfigError, match="duplicate"):
        parse(raw)


def test_defaults_must_be_a_mapping():
    with pytest.raises(ConfigError, match="defaults"):
        parse({"defaults": "price_drop", "watches": minimal()["watches"]})


@pytest.mark.parametrize("bad", [7, {}, {"a": 1}])
def test_notify_on_must_be_a_list(bad):
    with pytest.raises(ConfigError, match="notify_on must be a list"):
        parse(minimal(notify_on=bad))


def test_a_falsy_non_mapping_defaults_is_still_rejected():
    with pytest.raises(ConfigError, match="defaults"):
        parse({"defaults": [], "watches": minimal()["watches"]})
