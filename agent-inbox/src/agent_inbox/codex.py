"""Read and send to an existing Codex daemon without resuming or cloning it."""

import time
from contextlib import contextmanager
from pathlib import Path

from websockets.sync.client import unix_connect

from . import codex_commands, codex_context
from .capabilities import AdapterCapabilities
from .codex_history import history, turns
from .codex_rpc import Rpc, RpcRejected, validate_root
from .models import DeliveryRejected, RootInfo, Snapshot, fields, text


def settings(target):
    fields(target.settings, ("socket", "command"))
    text(target.settings["socket"], "server socket", 4096)
    if not Path(target.settings["socket"]).is_absolute():
        raise ValueError("Server socket must be absolute")
    command = target.settings["command"]
    if type(command) is not list or not command or any(type(x) is not str or not x for x in command):
        raise ValueError("Invalid harness command")
    if not Path(command[0]).is_absolute():
        raise ValueError("Harness executable must be absolute")
    return target.settings


@contextmanager
def connection(target):
    config = settings(target)
    with unix_connect(config["socket"], uri="ws://localhost/", open_timeout=5,
                      close_timeout=2, max_size=16 * 1024 * 1024) as stream:
        rpc = Rpc(stream)
        rpc.call("initialize", {"clientInfo": {"name": "agent-inbox", "version": "0.1.0"},
                                "capabilities": {"experimentalApi": True}})
        stream.send('{"method":"initialized","params":{}}')
        yield rpc


def root(rpc, target):
    value = rpc.call("thread/read", {"threadId": target.session_id})["thread"]
    return validate_root(value, target.session_id)


def activity(info):
    state = info["status"]["type"]
    flags = info["status"].get("activeFlags", [])
    if type(flags) is not list or any(type(flag) is not str for flag in flags):
        raise ValueError("Invalid session activity flags")
    if any(flag in ("waitingOnApproval", "waitingOnUserInput") for flag in flags):
        return "input-needed"
    return state


def active_turn(page):
    if type(page.get("data")) is not list:
        raise ValueError("Invalid turn page")
    active = []
    for turn in page["data"]:
        if type(turn) is not dict or turn.get("status") not in (
            "inProgress", "completed", "interrupted", "failed",
        ):
            raise ValueError("Invalid turn status")
        identifier = text(turn.get("id"), "turn id", 200)
        if turn["status"] == "inProgress":
            active.append(identifier)
    if len(active) > 1:
        raise ValueError("Ambiguous active turn")
    return active[0] if active else None


class Codex:
    capabilities = AdapterCapabilities(
        queued_messages=True, mid_turn_steering=True, approvals_survive_restart=False,
        history_while_unloaded=True, images=True, interrupt=True, commands=True, questions=False,
        reply_mode="direct",
    )

    def context(self, target):
        with connection(target) as rpc:
            return codex_context.context(rpc, root(rpc, target))

    def commands(self, target):
        with connection(target) as rpc:
            return codex_commands.commands(rpc, root(rpc, target))

    def execute(self, target, command, value):
        with connection(target) as rpc:
            info = root(rpc, target)
            codex_commands.commands(rpc, info).selected(command, value)
            turn_id = None
            if command == "interrupt":
                turn_id = active_turn(turns(rpc, target.session_id))
                if turn_id is None:
                    raise DeliveryRejected("The active turn has finished")
            codex_commands.execute(rpc, target, command, value, turn_id)
        return "applied"

    def discover(self, seed):
        out = []
        deadline = time.monotonic() + 8
        with connection(seed) as rpc:
            identifiers = rpc.call("thread/loaded/list", {}).get("data")
            if type(identifiers) is not list:
                raise ValueError("Invalid loaded-session list")
            for identifier in identifiers:
                if time.monotonic() > deadline:
                    raise TimeoutError("Session discovery timed out")
                text(identifier, "session id", 200)
                info = rpc.call("thread/read", {"threadId": identifier}).get("thread")
                if type(info) is not dict or info.get("id") != identifier:
                    raise ValueError("Invalid loaded-session metadata")
                if "parentThreadId" not in info or "sessionId" not in info:
                    raise ValueError("Missing session ancestry")
                if info["parentThreadId"] is not None or info["sessionId"] != identifier:
                    continue
                info = validate_root(info, identifier)
                if info["status"]["type"] not in ("active", "idle"):
                    continue
                try:
                    turns(rpc, identifier, limit=1)
                except RpcRejected as error:
                    # Blank native placeholders cannot serve conversation history yet.
                    if error.code == -32600 and error.message == (
                        f"thread {identifier} is not materialized yet; "
                        "thread/turns/list is unavailable before first user message"
                    ):
                        continue
                    raise
                name = info.get("name")
                if name is not None:
                    text(name, "session title", 200)
                label = name if name is not None else "Codex " + identifier[-8:]
                out.append(RootInfo(identifier, label, activity(info)))
        return out

    def snapshot(self, target, cursor=None, since=None):
        with connection(target) as rpc:
            info = root(rpc, target)
            page = history(rpc, target.session_id, cursor, since)
        return Snapshot(activity(info), info["canAcceptDirectInput"], page.messages, page.older,
                        newer_cursor=page.newer, catching_up=page.catching_up,
                        activity=page.activity, timeline=page.timeline)

    def send(self, target, message):
        if message.delivery not in ("queue", "steer"):
            raise DeliveryRejected("Unsupported delivery mode")
        inputs = ([{"type": "text", "text": message.text}] if message.text else [])
        inputs.extend({"type": "image", "url": url} for url in message.images)
        with connection(target) as rpc:
            info = root(rpc, target)
            if not info["canAcceptDirectInput"]:
                raise DeliveryRejected("This root is not accepting direct input")
            attempts = 2 if message.delivery == "steer" else 0
            for _ in range(attempts):
                if info["status"]["type"] != "active":
                    break
                page = turns(rpc, target.session_id)
                turn_id = active_turn(page)
                if turn_id:
                    try:
                        result = rpc.call("turn/steer", {
                            "threadId": target.session_id, "expectedTurnId": turn_id,
                            "input": inputs, "clientUserMessageId": message.id,
                        })
                    except RpcRejected as error:
                        if error.code == -32600 and error.message == "no active turn to steer":
                            raise DeliveryRejected("The turn finished before steering") from error
                        raise
                    if result.get("turnId") != turn_id:
                        raise RuntimeError("Harness did not confirm the selected turn")
                    return "steered"
                info = root(rpc, target)
            if message.delivery == "steer":
                raise DeliveryRejected("No authoritative active turn is available yet")
            if info["status"]["type"] not in ("idle", "active"):
                raise DeliveryRejected("This root is not accepting queued input")
            result = rpc.call("thread/queue/add", {
                "threadId": target.session_id, "clientUserMessageId": message.id, "input": inputs,
            })
            receipt = result.get("queuedSubmission")
            if type(receipt) is not dict or receipt.get("clientUserMessageId") != message.id:
                raise RuntimeError("Harness did not confirm the selected submission")
            text(receipt.get("id"), "queue receipt id", 200)
            echoed = receipt.get("input")
            if type(echoed) is not list or len(echoed) != len(inputs):
                raise RuntimeError("Harness did not confirm the submitted input")
            for expected, actual in zip(inputs, echoed, strict=True):
                if (type(actual) is not dict
                        or any(actual.get(key) != value for key, value in expected.items())):
                    raise RuntimeError("Harness did not confirm the submitted input")
        return "queued"
