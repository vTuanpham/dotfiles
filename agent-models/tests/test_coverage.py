import json

import pytest

from agent_models import benchmarks, cli, coverage, inventory


def fixture_snapshot():
    return {"retrieved": "2026-10-30T12:00:00Z", "sources": {
        "LiveBench": {"status": "ok", "release": "current",
                      "points": {"Overall": [{"model": "claude-example-5.5", "score": 80, "cost": 1},
                                              {"model": "claude-example-5", "score": 81, "cost": 2}]},
                      "frontiers": {"Overall": []}, "efforts": {"claude-example-5.5": "high"}},
        "Arena/webdev": {"status": "ok", "rows": [
            {"model_name": "Claude Example 5.5 (Max)", "rank": 1}]}}}


def native():
    return {"backend": "claude", "models": [
        {"id": "example", "model": "claude-example-5-5", "efforts": ["high"]},
        {"id": "unknown", "model": "claude-other-5", "efforts": None}]}


def test_coverage_generated_with_versions_aliases_and_actual_settings():
    result = coverage.summarize(native(), fixture_snapshot())
    first, unknown = result["models"]
    assert first["sources"]["LiveBench"] == [
        {"label": "claude-example-5.5", "setting": "high", "native_effort_supported": True}]
    assert first["sources"]["Arena/webdev"][0]["native_effort_supported"] is False
    assert unknown["coverage"] == "no exact benchmark identity"
    assert unknown["efforts"] is None
    assert not coverage.matches(first, "Claude Example 5 (Max)")
    assert not coverage.matches(first, "Claude Example 55 (Max)")
    assert coverage.matches({"model": "provider/claude-example-5.5"}, "Claude Example 5.5")


def test_backend_query_resolves_native_alias_and_excludes_other_versions(monkeypatch):
    monkeypatch.setattr(benchmarks, "snapshot", fixture_snapshot)
    result = benchmarks.search("overall", "example", 1, native())
    assert [r["model"] for r in result["sources"]["LiveBench"]["results"]] == ["claude-example-5.5"]
    assert result["native_catalog"]["models"] == [native()["models"][0]]
    assert result["native_catalog"]["unmeasured_count"] == 0
    unknown = benchmarks.search("overall", "unknown", 1, native())
    assert unknown["sources"]["LiveBench"]["results"] == []
    assert unknown["native_catalog"]["unmeasured_ids"] == ["unknown"]


def test_native_context_is_bounded_without_hiding_match_counts(monkeypatch):
    monkeypatch.setattr(benchmarks, "snapshot", fixture_snapshot)
    catalog = native()
    catalog["models"].append({**catalog["models"][0], "id": "another-route"})
    result = benchmarks.search("overall", "", 1, catalog)["native_catalog"]
    assert len(result["models"]) == result["limit"] == 1
    assert result["matches"] == 2


def claude_frame(models):
    return json.dumps({"type": "control_response", "response": {
        "subtype": "success", "request_id": "inventory", "response": {
            "models": models, "account": {"secret": "must not be returned"}}}}) + "\n"


def test_claude_initialization_reads_native_models_without_prompt_or_history(monkeypatch):
    model = {"value": "current", "resolvedModel": "claude-example-5-5",
             "supportedEffortLevels": ["adaptive", "deep"]}

    def run(command, **kwargs):
        assert "--no-session-persistence" in command and "--strict-mcp-config" in command
        assert json.loads(kwargs["input"])["request"] == {"subtype": "initialize", "hooks": {}}
        assert "--prompt" not in command and "--model" not in command
        kwargs["stdout"].write(claude_frame([model]))
        return type("Result", (), {"returncode": 0})()

    monkeypatch.setattr(inventory.subprocess, "run", run)
    result = inventory.catalog("claude")
    assert result["models"] == [
        {"id": "current", "model": "claude-example-5-5", "efforts": ["adaptive", "deep"]}]
    assert "secret" not in json.dumps(result)


@pytest.mark.parametrize("models", [None, [{}], [{"value": "x", "resolvedModel": "x",
                                                "supportedEffortLevels": ["high", "high"]}]])
def test_invalid_native_catalog_is_rejected(models):
    with pytest.raises(ValueError):
        inventory.parse_claude(claude_frame(models))


def test_opencode_uses_enabled_native_variants_not_a_global_effort_enum():
    result = inventory.parse_opencode(json.dumps({"data": [
        {"providerID": "example", "id": "google/model", "enabled": True,
         "variants": [{"id": "adaptive"}]},
        {"providerID": "example", "id": "disabled", "enabled": False}]}))
    assert result[0]["id"] == "example/google/model"
    assert result[0]["efforts"] == ["adaptive"]
    assert result[0]["privacy_gate"] == "unreviewed"
    with pytest.raises(ValueError):
        inventory.parse_opencode('{"data":[{"enabled":true,"providerID":"x","id":"y"}]}')


def test_backend_cli_does_not_require_account_override(monkeypatch, capsys):
    monkeypatch.setattr(cli.sys, "argv", ["model-guide", "benchmarks", "--backend", "claude"])
    monkeypatch.setattr(inventory, "catalog", lambda backend, account: native())
    monkeypatch.setattr(benchmarks, "snapshot", fixture_snapshot)
    monkeypatch.setattr(benchmarks, "account_observation", lambda backend, account: {})
    assert cli.main() == 0
    assert json.loads(capsys.readouterr().out)["native_catalog"]["backend"] == "claude"
