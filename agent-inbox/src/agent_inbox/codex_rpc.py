"""Codex JSON-RPC errors, response framing and native root identity."""

import json
import time

from .models import decode_json


class RpcRejected(RuntimeError):
    def __init__(self, code, message):
        super().__init__("Harness rejected the request; check its native interface")
        self.code, self.message = code, message


class Rpc:
    def __init__(self, connection):
        self.connection, self.number = connection, 0

    def call(self, method, params):
        self.number += 1
        self.connection.send(json.dumps({"id": self.number, "method": method, "params": params}))
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            value = decode_json(self.connection.recv(timeout=max(0, deadline - time.monotonic())))
            if type(value) is not dict:
                raise ValueError("Invalid harness response")
            if type(value.get("id")) is int and value["id"] == self.number:
                if "error" in value:
                    error = value["error"]
                    if (type(error) is not dict or type(error.get("code")) is not int
                            or type(error.get("message")) is not str):
                        raise ValueError("Invalid harness error")
                    raise RpcRejected(error["code"], error["message"])
                if type(value.get("result")) is not dict:
                    raise ValueError("Invalid harness result")
                return value["result"]
        raise TimeoutError("Harness request timed out")


def validate_root(value, session_id):
    if type(value) is not dict or value.get("id") != session_id or "parentThreadId" not in value:
        raise ValueError("Harness did not identify the selected root")
    if value["parentThreadId"] is not None or value.get("sessionId") != session_id:
        raise ValueError("Only root sessions can be registered")
    if type(value.get("canAcceptDirectInput")) is not bool:
        raise ValueError("Harness did not report input capability")
    status = value.get("status")
    if type(status) is not dict or status.get("type") not in ("active", "idle", "notLoaded", "systemError"):
        raise ValueError("Harness returned an unsupported session status")
    return value
