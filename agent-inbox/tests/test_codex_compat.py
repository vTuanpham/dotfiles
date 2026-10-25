"""Explicit compatibility with servers that reject paginated history methods."""

from copy import deepcopy

import pytest
from test_inbox import codex_root, codex_target, outgoing, use_rpc

from agent_inbox import codex, codex_history


def turn(number, status="completed"):
    return {"id": f"turn-{number}", "status": status, "items": [
        {"id": f"item-{number}", "type": "agentMessage", "text": f"Reply {number}"},
    ]}


class LegacyRpc:
    def __init__(self, count=205):
        self.turns = [turn(number) for number in range(count)]
        self.calls = []
        self.error = codex.RpcRejected(-32601, "list_items is not supported yet")
        self.metadata = codex_root()

    def call(self, method, params):
        self.calls.append((method, params))
        if method in ("thread/items/list", "thread/turns/list"):
            raise self.error
        if method == "thread/read":
            return {"thread": {**self.metadata, **({"turns": deepcopy(self.turns)}
                                                     if params.get("includeTurns") else {})}}
        if method == "thread/loaded/list":
            return {"data": ["root-id"]}
        if method == "turn/steer":
            return {"turnId": params["expectedTurnId"]}
        if method == "turn/interrupt":
            return {}
        raise AssertionError((method, params))


def test_legacy_history_pages_older_items_and_catches_up_without_gaps_or_duplicates():
    rpc = LegacyRpc()
    first = codex_history.history(rpc, "root-id")
    assert [message.text for message in first.messages] == [f"Reply {n}" for n in range(105, 205)]
    second = codex_history.history(rpc, "root-id", older=first.older)
    third = codex_history.history(rpc, "root-id", older=second.older)
    all_messages = third.messages + second.messages + first.messages
    assert [message.text for message in all_messages] == [f"Reply {n}" for n in range(205)]
    assert third.older is None and len({message.id for message in all_messages}) == 205

    rpc.turns[-1]["items"][0]["text"] = "Reply continued"
    rpc.turns.extend(turn(n) for n in range(205, 410))
    caught = []
    page = first
    for _ in range(3):
        page = codex_history.history(rpc, "root-id", since=page.newer)
        assert len(page.messages) <= 100
        caught.extend(message.text for message in page.messages)
    assert not page.catching_up
    assert caught[0] == "Reply continued"
    assert set(f"Reply {n}" for n in range(205, 410)) <= set(caught)
    assert not any(method in ("thread/resume", "thread/start") for method, _ in rpc.calls)


@pytest.mark.parametrize("mutation", ["truncate", "reorder", "replace"])
def test_legacy_cursor_rejects_changed_prefix_even_if_its_last_item_is_unchanged(mutation):
    rpc = LegacyRpc()
    first = codex_history.history(rpc, "root-id")
    if mutation == "truncate":
        rpc.turns.pop(0)
    elif mutation == "reorder":
        rpc.turns[0], rpc.turns[1] = rpc.turns[1], rpc.turns[0]
    else:
        rpc.turns[0] = turn("replacement")
    with pytest.raises(ValueError, match="changed|reload"):
        codex_history.history(rpc, "root-id", since=first.newer)


def test_legacy_cursor_is_root_bound_and_does_not_accept_a_modern_cursor():
    rpc = LegacyRpc()
    first = codex_history.history(rpc, "root-id")
    rpc.metadata.update(id="other", sessionId="other")
    with pytest.raises(ValueError, match="cursor|root"):
        codex_history.history(rpc, "other", since=first.newer)
    with pytest.raises(ValueError, match="backend|reload"):
        codex_history.history(rpc, "other", since="opaque-native-cursor")


@pytest.mark.parametrize("error", [codex.RpcRejected(-32602, "bad params"), TimeoutError(), ValueError()])
def test_only_unsupported_method_errors_select_legacy_history(error):
    rpc = LegacyRpc()
    rpc.error = error
    with pytest.raises(type(error)):
        codex_history.history(rpc, "root-id")
    assert not any(method == "thread/read" for method, _ in rpc.calls)


def test_legacy_boundary_rejects_foreign_roots_duplicate_items_and_excess_history(monkeypatch):
    rpc = LegacyRpc(3)
    rpc.metadata["sessionId"] = "different"
    with pytest.raises(ValueError):
        codex_history.history(rpc, "root-id")
    rpc.metadata = codex_root()
    rpc.turns[1]["items"] *= 2
    with pytest.raises(ValueError, match="Duplicate"):
        codex_history.history(rpc, "root-id")
    rpc.turns[1] = turn(1)
    monkeypatch.setattr(codex_history, "LEGACY_ITEM_LIMIT", 2)
    with pytest.raises(ValueError, match="limit"):
        codex_history.history(rpc, "root-id")


def test_discovery_send_and_cancel_use_the_same_legacy_turn_contract(monkeypatch):
    rpc = LegacyRpc(2)
    use_rpc(monkeypatch, rpc)
    assert [root.session_id for root in codex.Codex().discover(codex_target())] == ["root-id"]
    rpc.metadata["status"] = {"type": "active"}
    rpc.turns[-1]["status"] = "inProgress"
    assert codex.Codex().send(codex_target(), outgoing()) == "steered"
    assert rpc.calls[-1][1]["expectedTurnId"] == "turn-1"
    monkeypatch.setattr(codex.codex_commands, "commands", lambda *args: type("Commands", (), {
        "selected": lambda *args: None,
    })())
    assert codex.Codex().execute(codex_target(), "interrupt", "") == "applied"
    assert rpc.calls[-1] == ("turn/interrupt", {"threadId": "root-id", "turnId": "turn-1"})


def test_legacy_empty_history_can_catch_new_items_and_rejects_ambiguous_active_turns():
    rpc = LegacyRpc(0)
    first = codex_history.history(rpc, "root-id")
    rpc.turns = [turn(0, "inProgress"), turn(1, "inProgress")]
    assert len(codex_history.history(rpc, "root-id", since=first.newer).messages) == 2
    with pytest.raises(ValueError, match="Ambiguous"):
        codex.active_turn(codex_history.turns(rpc, "root-id"))


def test_legacy_cursor_remains_readable_when_pagination_becomes_available():
    rpc = LegacyRpc(3)
    first = codex_history.history(rpc, "root-id")
    rpc.calls.clear()
    rpc.error = AssertionError("A legacy cursor must not reach the paginated API")
    page = codex_history.history(rpc, "root-id", since=first.newer)
    assert [message.text for message in page.messages] == ["Reply 2"]
    assert [method for method, _ in rpc.calls] == ["thread/read"]


@pytest.mark.parametrize("payload", [
    '{"thread":"root-id","offset":true,"anchor":"a"}',
    '{"thread":"root-id","offset":-1,"anchor":"a"}',
    '{"thread":"root-id","offset":1,"offset":2,"anchor":"a"}',
    '{"thread":"root-id","offset":99999,"anchor":"a"}',
    '[]',
])
def test_legacy_cursor_decoder_rejects_ambiguous_or_unbounded_offsets(payload):
    with pytest.raises(ValueError):
        codex_history.history(LegacyRpc(3), "root-id", since=codex_history.LEGACY_CURSOR + payload)


def test_legacy_history_rejects_unloaded_items_and_a_single_oversized_turn(monkeypatch):
    rpc = LegacyRpc(1)
    rpc.turns[0]["itemsView"] = "notLoaded"
    with pytest.raises(ValueError, match="full turn items"):
        codex_history.history(rpc, "root-id")
    rpc.turns[0]["itemsView"] = "full"
    rpc.turns[0]["items"] = [turn(number)["items"][0] for number in range(3)]
    monkeypatch.setattr(codex_history, "LEGACY_ITEM_LIMIT", 2)
    with pytest.raises(ValueError, match="item limit"):
        codex_history.history(rpc, "root-id")
