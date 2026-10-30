import json

import pytest

from agent_models import benchmarks, cli, shortlist


def data():
    values = [{"model": "expensive", "score": 95, "cost": 9},
              {"model": "middle", "score": 92, "cost": 2},
              {"model": "cheap", "score": 80, "cost": 0.1},
              {"model": "dominated", "score": 75, "cost": 1},
              {"model": "unknown", "score": None, "cost": None}]
    return {"retrieved": "2026-10-30T12:00:00Z", "sources": {
        "LiveBench": {"status": "ok", "url": "https://livebench.ai/", "release": "current",
                      "points": {"Coding": values}, "efforts": {},
                      "frontiers": {"Coding": benchmarks.frontier(values)}}}}


def test_small_limit_keeps_cheapest_tradeoff_alongside_quality_leader(monkeypatch):
    monkeypatch.setattr(benchmarks, "snapshot", data)
    result = benchmarks.search("backend", limit=1)
    source = result["sources"]["LiveBench"]
    assert source["results"][0]["model"] == "expensive"
    assert source["efficient_results"][0]["model"] == "cheap"
    assert source["efficient_matches"] == 3
    assert "not directly measured" in result["coverage_notes"][0]


def test_efficiency_is_recomputed_after_native_filtering(monkeypatch):
    monkeypatch.setattr(benchmarks, "snapshot", data)
    native = {"backend": "test", "models": [{"id": "dominated", "model": "dominated", "efforts": []}]}
    source = benchmarks.search("backend", catalog=native)["sources"]["LiveBench"]
    assert source["efficient_results"][0]["model"] == "dominated"
    assert source["results"][0]["on_frontier"] is True


def test_table_frontiers_keep_harnesses_separate_and_unknowns_unknown():
    header = [["Rank", "Model", "Harness", "Score", "Cost / Test", "Duration / Test"]]
    rows = [["1", "Strong", "A", "90%", "$9", "30m"],
            ["2", "Cheap", "A", "80%", "$1", "10m"],
            ["3", "Weak", "B", "70%", "$2", "20m"],
            ["4", "Missing cost", "A", "85%", "--", "--"]]
    result = shortlist.table_views(header, rows, 4)
    assert result["efficient_rows"] == [rows[1], rows[2], rows[0]]
    assert result["rows"][-1][-1] == "--"
    assert result["efficient_matches"] == 3
    with pytest.raises(ValueError):
        shortlist.table_views(header, [["1", "Invalid", "A", "NaN", "$1", "1m"]], 1)


def test_brief_preserves_provenance_gaps_and_both_views(monkeypatch):
    monkeypatch.setattr(benchmarks, "snapshot", data)
    result = benchmarks.search("backend", limit=1)
    result["account_observation"] = {"scope": "local profile, not session", "profiles": {},
                                     "quotas": [], "errors": ["quota unavailable"]}
    output = shortlist.brief(result)
    assert all(value in output for value in ("expensive", "cheap", "current", "Quality:", "Efficient:",
                                             "not directly measured", "quota unavailable", "https://"))
    result["sources"]["LiveBench"]["results"][0]["model"] = "unsafe\x1b[2J"
    assert "\x1b" not in shortlist.brief(result)


def test_native_budget_represents_both_sources_and_efficiency(monkeypatch):
    snapshot = data()
    snapshot["sources"]["Vals Terminal-Bench"] = {"status": "ok", "tables": [
        [["Rank", "Model", "Score", "Cost / Test"], ["1", "middle", "95%", "$2"],
         ["2", "expensive", "90%", "$9"], ["3", "cheap", "80%", "$0.1"]]]}
    monkeypatch.setattr(benchmarks, "snapshot", lambda: snapshot)
    native = {"backend": "test", "models": [
        {"id": name, "model": name, "efforts": []} for name in ("expensive", "middle", "cheap")]}
    result = benchmarks.search("backend", limit=3, catalog=native)
    assert [m["id"] for m in result["native_catalog"]["models"]] == ["expensive", "middle", "cheap"]


def test_compact_cli_is_opt_in_and_json_keeps_both_views(monkeypatch, capsys):
    monkeypatch.setattr(benchmarks, "snapshot", data)
    monkeypatch.setattr(benchmarks, "account_observation", lambda *args: {})
    args = ["model-guide", "benchmarks", "--domain", "backend", "--limit", "1"]
    monkeypatch.setattr(cli.sys, "argv", args)
    assert cli.main() == 0
    assert "efficient_results" in json.loads(capsys.readouterr().out)["sources"]["LiveBench"]
    monkeypatch.setattr(cli.sys, "argv", [*args, "--brief"])
    assert cli.main() == 0
    assert "Efficient:" in capsys.readouterr().out
