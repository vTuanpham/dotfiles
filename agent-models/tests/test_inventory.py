import json

import pytest

from agent_models import inventory


def test_model_catalog_parser_lists_supported_ids_and_efforts():
    catalog = json.dumps(
        {
            "models": [
                {
                    "slug": "model-a",
                    "visibility": "list",
                    "supported_reasoning_levels": [{"effort": "low"}, {"effort": "high"}],
                },
                {"slug": "hidden", "visibility": "hide", "supported_reasoning_levels": []},
            ]
        }
    )
    assert inventory.parse_codex(catalog) == ["model-a\tlow,high"]


def test_authoritative_empty_catalog_is_distinct_from_invalid_output():
    assert inventory.parse_codex('{"models":[]}') == []
    for raw in ('{}', '{"models":null}', '{"models":[],"models":[]}'):
        with pytest.raises(ValueError):
            inventory.parse_codex(raw)


def test_reference_check_does_not_start_provider_processes(monkeypatch, tmp_path):
    from agent_models import reference

    monkeypatch.setattr(reference, "live", lambda: pytest.fail("health check launched provider"))
    assert reference.inspect()["inventory_checked"] is False


def test_models_marks_and_sorts_free_first(monkeypatch, capsys):
    monkeypatch.setattr(
        inventory.subprocess,
        "run",
        lambda *args, **kwargs: type(
            "Result",
            (),
            {
                "stdout": "paid/model\nopencode/example-free\nopencode/glm-5.3-flash-free\n"
                "opencode/big-pickle\n",
                "returncode": 0,
            },
        )(),
    )
    inventory.show("opencode")
    assert capsys.readouterr().out.splitlines() == [
        "opencode/example-free\t-\tfree-logged",
        "opencode/glm-5.3-flash-free\t-\tfree",
        "opencode/big-pickle\t-\tfree-logged",
        "paid/model\t-\tpaid",
    ]


def test_models_failure_reports_stderr(monkeypatch):
    monkeypatch.setattr(
        inventory.subprocess,
        "run",
        lambda *args, **kwargs: type(
            "Result", (), {"stdout": "", "stderr": "not logged in", "returncode": 1}
        )(),
    )
    with pytest.raises(RuntimeError, match="inventory failed"):
        inventory.show("opencode")
