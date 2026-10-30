import io
import json

import polars as pl
import pytest

from agent_models import benchmarks


@pytest.fixture
def live(monkeypatch):
    data = {
        benchmarks.LIVE: '<title>LiveBench 2.0 - Benchmark</title>'
                         '<script src="./static/js/main.abc.js"></script>',
        benchmarks.LIVE + "static/js/main.abc.js":
            'releases=["20261014","20261025"];'
            '"alpha":{displayName:"Alpha",effort:"high"},'
            '"beta":{displayName:"Beta",effort:"adaptive"}',
        benchmarks.LIVE + "data/20261025/table.csv":
            "model,long,browser\nalpha,50,100\nbeta,0,0\ngamma,,75\n",
        benchmarks.LIVE + "data/20261025/categories.json":
            '{"Long Agentic":["long"],"Browser":["browser"],'
            '"_overall_weights":{"Long Agentic":2}}',
        benchmarks.LIVE + "data/20261025/cost.csv":
            "model,long,browser,nq_long,nq_browser\nalpha,10,20,2,4\nbeta,1,1,2,4\ngamma,1,1,2,4\n",
    }
    monkeypatch.setattr(benchmarks, "fetch", data.__getitem__)
    return data


def test_live_weights_success_cost_zero_and_missing_are_distinct(live):
    result = benchmarks.livebench()
    assert result["release"] == "20261025"
    assert result["efforts"] == {"alpha": "high", "beta": "adaptive"}
    points = {p["model"]: p for p in result["points"]["Overall"]}
    assert points["alpha"]["score"] == pytest.approx(200 / 3)
    assert points["alpha"]["cost"] == pytest.approx(7.5)
    assert points["beta"] == {"model": "beta", "score": 0, "cost": None}
    assert points["gamma"] == {"model": "gamma", "score": None, "cost": None}
    assert [p["model"] for p in result["frontiers"]["Overall"]] == ["alpha"]
    assert result["weights"] == {"Long Agentic": 2}


@pytest.mark.parametrize("bad", ["NaN", "inf", "-1", "101", "true"])
def test_live_rejects_invalid_scores_instead_of_ranking_them(live, bad):
    key = benchmarks.LIVE + "data/20261025/table.csv"
    live[key] = live[key].replace("alpha,50", "alpha," + bad)
    with pytest.raises(ValueError):
        benchmarks.livebench()


def test_frontier_does_not_assume_more_cost_means_more_capability():
    points = [{"model": "a", "score": 50, "cost": 1},
              {"model": "b", "score": 49, "cost": 2},
              {"model": "c", "score": 60, "cost": 3},
              {"model": "tie", "score": 50, "cost": 1},
              {"model": "missing", "score": None, "cost": 0}]
    assert [p["model"] for p in benchmarks.frontier(points)] == ["a", "c", "tie"]


def test_native_ids_find_display_names_without_conflating_versions():
    assert benchmarks.name_matches("gpt-6.1-sol", "GPT-6.1 Sol (high)")
    assert benchmarks.name_matches("claude-sonnet-5-5", "Claude Sonnet 5.5")
    assert not benchmarks.name_matches("gpt-6.1-sol", "GPT-6 Sol (high)")


def test_vals_terminal_release_follows_official_links_not_a_fixed_version(monkeypatch):
    monkeypatch.setattr(benchmarks, "fetch", lambda _: '<a href="/benchmarks/terminal-bench-4">old</a>'
                        '<a href="https://www.vals.ai/benchmarks/terminal-bench-12">current</a>')
    monkeypatch.setattr(benchmarks, "webpage", lambda url: {"url": url})
    assert benchmarks.vals_terminal()["url"].endswith("/terminal-bench-12")
    monkeypatch.setattr(benchmarks, "fetch", lambda _: '<a href="https://evil.invalid/private">x</a>')
    with pytest.raises(ValueError):
        benchmarks.vals_terminal()


def row(index, config="agent", category="overall"):
    fields = (("score", "score_ci_lower", "score_ci_upper") if config == "agent"
              else ("rating", "rating_lower", "rating_upper"))
    return {"row_idx": index, "truncated_cells": [], "row": {
        "model_name": f"Example {index} (high)", "category": category, "rank": index + 1,
        fields[0]: 10, fields[1]: 9, fields[2]: 11, "leaderboard_publish_date": "2026-10-28"}}


@pytest.mark.parametrize("config", ["agent", "webdev"])
def test_arena_reads_all_export_shards_and_preserves_each_schema(monkeypatch, config):
    catalog, blobs = exports([[row(i, config)["row"] for i in range(100)],
                              [row(100, config)["row"]]], config)
    calls = []
    monkeypatch.setattr(benchmarks, "fetch_bytes", lambda url: calls.append(url) or blobs[url])
    result = benchmarks.arena(config, catalog)
    assert len(calls) == 2 and len(result["rows"]) == 101
    assert ("score" if config == "agent" else "rating") in result["rows"][0]
    assert result["published"] == "2026-10-28"
    assert set(result["sha256"]) == set(blobs)


def exports(shards, config="agent"):
    files, blobs = [], {}
    for index, rows in enumerate(shards):
        buffer = io.BytesIO()
        pl.DataFrame(rows).write_parquet(buffer)
        url = f"https://huggingface.co/datasets/{benchmarks.DATASET}/resolve/main/{config}/{index}.parquet"
        blobs[url] = buffer.getvalue()
        files.append({"config": config, "split": "latest", "url": url, "size": len(blobs[url])})
    return {"partial": False, "parquet_files": files}, blobs


@pytest.mark.parametrize("fault", ["partial", "size", "duplicate", "date", "nan", "unsafe_url"])
def test_arena_partial_or_ambiguous_data_is_not_a_complete_snapshot(monkeypatch, fault):
    rows = [row(0)["row"], row(1)["row"]]
    if fault == "duplicate":
        rows[1] = rows[0]
    elif fault == "date":
        rows[1]["leaderboard_publish_date"] = "2026-10-27"
    elif fault == "nan":
        rows[1]["score"] = float("nan")
    catalog, blobs = exports([rows])
    if fault == "partial":
        catalog["partial"] = True
    elif fault == "size":
        catalog["parquet_files"][0]["size"] += 1
    elif fault == "unsafe_url":
        catalog["parquet_files"][0]["url"] = "http://localhost/private"
    monkeypatch.setattr(benchmarks, "fetch_bytes", blobs.__getitem__)
    with pytest.raises(ValueError):
        benchmarks.arena("agent", catalog)


def test_same_display_name_different_evaluations_are_preserved_and_flagged(monkeypatch):
    rows = [row(0)["row"], row(1)["row"]]
    rows[1]["model_name"] = rows[0]["model_name"]
    catalog, blobs = exports([rows])
    monkeypatch.setattr(benchmarks, "fetch_bytes", blobs.__getitem__)
    result = benchmarks.arena("agent", catalog)
    assert len(result["rows"]) == 2
    assert result["ambiguous_names"] == [rows[0]["model_name"]]


def test_setting_deltas_are_observed_not_a_universal_effort_ladder():
    header = ["Model", "Artificial Analysis Intelligence Index", "Cost per Task USD",
              "Latency First Chunk (s)", "Total Response (s)"]
    table = [header, ["Example (adaptive)", "30", "$1", "1", "2"],
             ["Example (deep)", "29", "$3", "3", "5"],
             ["Google model (high)", "50", "$1", "1", "2"],
             ["Example (deep with fallback)", "99", "$4", "4", "7"]]
    trade, = benchmarks.effort_tradeoffs([table])
    assert trade["from"] == "adaptive" and trade["to"] == "deep"
    assert trade["delta"]["Artificial Analysis Intelligence Index"] == -1
    assert trade["delta"]["Cost per Task USD"] == 2
    assert trade["delta"]["Total Response (s)"] == 3


def test_search_is_bounded_keeps_unknowns_and_does_not_fetch(monkeypatch, tmp_path, live):
    result = benchmarks.livebench()
    monkeypatch.setattr(benchmarks, "CACHE", tmp_path)
    snapshot = {"retrieved": "2026-10-30T12:00:00Z", "sources": {"LiveBench": {"status": "ok", **result}}}
    (tmp_path / "benchmark-data.json").write_text(json.dumps(snapshot))
    monkeypatch.setattr(benchmarks, "fetch", lambda _: pytest.fail("search must not fetch"))
    found = benchmarks.search("browser", "", 1)
    assert found["retrieved"] == snapshot["retrieved"]
    assert found["sources"]["LiveBench"]["matches"] == 3
    assert len(found["sources"]["LiveBench"]["results"]) == 1
    assert found["sources"]["LiveBench"]["results"][0]["time_per_task"] is None
    unknown = benchmarks.search("overall", "gamma", 5)["sources"]["LiveBench"]["results"][0]
    assert unknown["score"] is None and unknown["usd_per_success"] is None


def test_component_headers_and_duration_labels_survive_bounded_search(monkeypatch, tmp_path):
    monkeypatch.setattr(benchmarks, "CACHE", tmp_path)
    tables = [[["Models", "Finance", "Coding"],
               ["", "Finance Agent v2.1", "Terminal-Bench 4.0"],
               ["Example", "60%", "50%"]],
              [["Rank", "Model", "Cost / Test", "Duration / Test"],
               ["1", "Example", "$3.61", "44m24s"]]]
    snapshot = {"retrieved": "2026-10-30T12:00:00Z", "sources": {
        "Vals Index": {"status": "ok", "tables": tables}}}
    (tmp_path / "benchmark-data.json").write_text(json.dumps(snapshot))
    found = benchmarks.search("finance", "Example", 1)["sources"]["Vals Index"]["tables"]
    assert found[0]["headers"] == tables[0][:2]
    assert found[0]["rows"] == tables[0][2:]
    assert found[1]["headers"][0][-1] == "Duration / Test"
    assert found[1]["rows"][0][-1] == "44m24s"
