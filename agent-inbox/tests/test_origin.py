import pytest

from agent_inbox.models import Target
from agent_inbox.origin import annotate, decode


def bindings(backend="claude", parent=None):
    return {"version": 1, "sessions": [{"backend": backend, "session_id": "worker", "job": "other-root/ui",
                                        "title": "UI worker", "parent": parent}]}


@pytest.mark.parametrize("backend", ["claude", "codex", "agy", "opencode"])
def test_launcher_origin_is_not_limited_to_one_owner_or_harness(backend):
    result = decode(bindings(backend, {"backend": "codex", "session_id": "coordinator"}))
    adapter = "acp" if backend == "agy" else backend
    settings = {"bridge_backend": "agy"} if backend == "agy" else {}
    targets = {"a": Target("a", "codex", "Codex", "coordinator", "Parent task", {}),
               "b": Target("b", adapter, backend, "worker", "Native worker", settings)}
    rows = [targets["a"].public(), targets["b"].public()]
    annotate(targets, rows, result)
    assert "origin" not in rows[0]
    assert rows[1]["origin"]["tool"] == "Agent Bridge"
    assert rows[1]["origin"]["parent"] == {"harness": "Codex", "id": "a", "label": "Parent task"}


def test_missing_or_ambiguous_launcher_history_never_invents_a_parent():
    original = bindings()
    decoded = decode(original)
    assert decoded[("claude", "worker")]["parent"] is None
    original["sessions"] *= 2
    assert decode(original) == {}
    original = bindings()
    original["sessions"][0]["parent"] = {"backend": "codex", "session_id": "missing"}
    target = Target("worker", "claude", "Claude", "worker", "Worker", {})
    rows = [target.public()]
    annotate({target.id: target}, rows, decode(original))
    assert rows[0]["origin"]["parent"] == {"harness": "Codex", "id": None, "label": None}
    original["sessions"][0]["job"] = "../escape"
    with pytest.raises(ValueError):
        decode(original)


def test_same_native_id_in_two_profiles_is_not_assigned_launcher_metadata():
    targets = {key: Target(key, "claude", "Claude", "worker", "Worker", {"profile": key})
               for key in ("a", "b")}
    rows = [target.public() for target in targets.values()]
    annotate(targets, rows, decode(bindings()))
    assert all("origin" not in row for row in rows)
