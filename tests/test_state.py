"""T1: state.json rules. Imports live inside tests so each test fails on its own before the code exists."""
import json
from datetime import datetime, timedelta, timezone

import pytest

NOW = datetime(2026, 11, 4, 12, tzinfo=timezone.utc)


def make_item(item_id):
    from bot.feeds import Item

    return Item(
        id=str(item_id), feed="sc_commlink", kind="commlink", title=f"T{item_id}", url="https://example.test/a",
        description="d", timestamp=datetime(2026, 11, 2, tzinfo=timezone.utc), image=None,
    )


def test_load_missing_file_gives_empty_state(tmp_path):
    from bot import state

    assert state.load(tmp_path / "none.json") == {"version": 1, "feeds": {}}


def test_save_then_load_roundtrip(tmp_path):
    from bot import state

    path = tmp_path / "s.json"
    data = {"version": 1, "feeds": {"sc_status": {"seen": ["a"], "failing_since": None}}}
    state.save(path, data)
    assert state.load(path) == data
    assert [p.name for p in tmp_path.iterdir()] == ["s.json"]  # no temp file left behind


def test_save_is_deterministic(tmp_path):
    from bot import state

    path = tmp_path / "s.json"
    data = {"version": 1, "feeds": {"b": {"seen": ["2", "1"]}, "a": {"seen": []}}}
    state.save(path, data)
    first = path.read_bytes()
    state.save(path, state.load(path))
    assert path.read_bytes() == first


def test_corrupt_state_raises_instead_of_resetting(tmp_path):
    from bot import state

    path = tmp_path / "s.json"
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(state.StateError):
        state.load(path)
    assert path.read_text(encoding="utf-8") == "{not json"


def test_state_with_wrong_shape_raises(tmp_path):
    from bot import state

    path = tmp_path / "s.json"
    path.write_text(json.dumps({"feeds": "oops"}), encoding="utf-8")
    with pytest.raises(state.StateError):
        state.load(path)


def test_bootstrap_records_all_items():
    from bot import state

    data = {"version": 1, "feeds": {}}
    assert state.is_bootstrapped(data, "sc_commlink") is False
    state.bootstrap(data, "sc_commlink", [make_item(10), make_item(11)])
    assert state.is_bootstrapped(data, "sc_commlink") is True
    assert sorted(data["feeds"]["sc_commlink"]["seen"]) == ["10", "11"]


def test_new_items_only_unseen():
    from bot import state

    data = {"version": 1, "feeds": {}}
    state.bootstrap(data, "sc_commlink", [make_item(10), make_item(11)])
    found = state.new_items(data, "sc_commlink", [make_item(10), make_item(11), make_item(12)], now=NOW)
    assert [i.id for i in found] == ["12"]


def test_older_id_with_a_recent_date_is_new():
    from bot import state

    data = {"version": 1, "feeds": {}}
    state.bootstrap(data, "sc_commlink", [make_item(10), make_item(11)])
    assert [i.id for i in state.new_items(data, "sc_commlink", [make_item(9), make_item(10)], now=NOW)] == ["9"]


@pytest.mark.parametrize("age_days,expected", [(13, True), (14, True), (15, False)])
def test_unseen_item_must_be_recent(age_days, expected):
    from bot import state

    data = {"version": 1, "feeds": {}}
    state.bootstrap(data, "sc_commlink", [make_item(10)])
    item = make_item(11)
    item.timestamp = NOW - timedelta(days=age_days)
    assert bool(state.new_items(data, "sc_commlink", [item], now=NOW)) is expected


def test_item_without_a_date_counts_as_recent():
    from bot import state

    data = {"version": 1, "feeds": {}}
    state.bootstrap(data, "sc_commlink", [make_item(10)])
    item = make_item(11)
    item.timestamp = None
    assert state.new_items(data, "sc_commlink", [item], now=NOW) == [item]


def test_mark_sent_adds_id_once():
    from bot import state

    data = {"version": 1, "feeds": {}}
    state.bootstrap(data, "sc_commlink", [make_item(10)])
    state.mark_sent(data, make_item(11))
    state.mark_sent(data, make_item(11))
    assert sorted(data["feeds"]["sc_commlink"]["seen"]) == ["10", "11"]


def test_failing_since_set_once_then_cleared():
    from bot import state

    data = {"version": 1, "feeds": {}}
    state.record_failure(data, "sc_status", "2026-11-04T00:00:00+00:00")
    state.record_failure(data, "sc_status", "2026-11-04T00:30:00+00:00")
    assert data["feeds"]["sc_status"]["failing_since"] == "2026-11-04T00:00:00+00:00"
    assert state.is_bootstrapped(data, "sc_status") is False  # a failure is not a bootstrap
    state.record_success(data, "sc_status")
    assert data["feeds"]["sc_status"]["failing_since"] is None


@pytest.mark.parametrize("age_days,expected", [(0, False), (49, False), (50, True), (70, True)])
def test_keepalive_due(age_days, expected):
    from bot import state

    now = 1_800_000_000
    assert state.keepalive_due(now - age_days * 86400, now) is expected
