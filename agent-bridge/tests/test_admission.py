import json
from pathlib import Path

import pytest

from agent_bridge import heavy, resources

GIB = 1024 * resources.MIB


def request(name, need, *, running=False, exclusive=False, queued_seconds=0, cap=None):
    return Path(name), {"need": need * GIB, "running": running, "exclusive": exclusive,
                        "queued_ns": queued_seconds * 1000000000, "cap": cap}


def test_fifo_prefers_a_fitting_head_over_smaller_later_work():
    rows = [request("head", 3), request("later", 1)]
    selected, reserved, cap, reason = heavy.choose(rows, 4 * GIB, None, 0)
    assert selected == Path("head") and reserved == 0 and cap is None and reason == "FIFO"


@pytest.mark.parametrize("age,expected", [(299, "small"), (300, None), (301, None)])
def test_backfill_stops_after_head_has_waited_five_minutes(age, expected):
    rows = [request("running", 2, running=True), request("head", 3), request("small", 1)]
    selected, reserved, cap, reason = heavy.choose(rows, 4 * GIB, None, age * 1000000000)
    assert selected == (Path(expected) if expected else None)
    assert reserved == 2 * GIB
    assert ("backfill paused" in reason) is (age >= 300)


def test_backfill_uses_the_first_later_job_that_fits_and_respects_all_running_needs():
    rows = [request("one", 1, running=True), request("two", 1, running=True),
            request("head", 4), request("also-large", 3), request("small", 1)]
    assert heavy.choose(rows, 3 * GIB, None, 0)[0] == Path("small")
    assert heavy.choose(rows, 2 * GIB, None, 0)[0] is None


def test_aged_head_runs_when_it_fits_instead_of_remaining_blocked():
    rows = [request("head", 3), request("small", 1)]
    assert heavy.choose(rows, 4 * GIB, None, 500 * 1000000000)[0] == Path("head")


def test_waiting_exclusive_is_a_backfill_barrier():
    rows = [request("running", 1, running=True), request("head", 4),
            request("timing", 1, exclusive=True), request("small", 1)]
    assert heavy.choose(rows, 3 * GIB, None, 0)[0] is None
    assert heavy.choose([rows[2], rows[3]], 3 * GIB, None, 0)[0] == Path("timing")


def test_tightest_live_optional_cap_wins():
    rows = [request("running", 1, running=True, cap=1), request("later", 1)]
    selected, _, cap, reason = heavy.choose(rows, 10 * GIB, None, 0)
    assert selected is None and cap == 1 and reason == "hard job cap reached"
    rows[0][1]["cap"] = None
    assert heavy.choose(rows, 10 * GIB, None, 0)[0] == Path("later")
    assert heavy.choose(rows, 10 * GIB, 1, 0)[0] is None


def test_exact_memory_fit_is_admitted():
    rows = [request("running", 1, running=True), request("later", 1)]
    assert heavy.choose(rows, 2 * GIB, None, 0)[0] == Path("later")
    assert heavy.choose(rows, 2 * GIB - 1, None, 0)[0] is None


@pytest.mark.parametrize("field,value", [("need", True), ("need", 0), ("need", "1G"),
                                        ("exclusive", 1), ("queued_ns", -1), ("cap", False), ("cap", 0)])
def test_malformed_reservation_metadata_is_rejected(tmp_path, field, value):
    path = tmp_path / "job.request"
    data = {"need": GIB, "exclusive": False, "queued_ns": 0, "cap": None}
    data[field] = value
    heavy.reservation_path(path).write_text(json.dumps(data))
    with pytest.raises(ValueError, match="invalid heavy reservation"):
        heavy.reservation(path, {"slots": 1})


def test_slot_only_request_is_exclusive_until_it_finishes(tmp_path):
    metadata = heavy.reservation(tmp_path / "old.request", {"slots": 2})
    assert metadata == {"need": GIB, "exclusive": True, "queued_ns": 0, "cap": 2}


def test_memory_units_use_exact_binary_sizes():
    assert resources.memory_size("2500M") == 2500 * resources.MIB
    assert resources.memory_size("1.5G") == 3 * GIB // 2
    with pytest.raises(ValueError, match="whole number of bytes"):
        resources.memory_size("1.0000000000000000000000000001G")


@pytest.mark.parametrize("name", ["SLOTS", "MIN_AVAILABLE_MIB", "MAX_LOAD"])
def test_malformed_limit_errors_never_echo_environment_values(monkeypatch, name):
    monkeypatch.setenv("AGENT_BRIDGE_HEAVY_" + name, "fixture-private-value")
    host = resources.Pressure(8 * GIB, 4 * GIB, 0, 0, ())
    with pytest.raises(ValueError) as error:
        resources.limits(host)
    assert "AGENT_BRIDGE_HEAVY_" in str(error.value)
    assert "fixture-private-value" not in str(error.value)
