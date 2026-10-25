"""The agent builds a form with `ask`; the human fills it on a page; the daemon keeps the answers.

Nothing here ever returns a value. The only way a secret leaves is `type`, which puts it into the
window the human saw on the form, at the OS level, through inject.py. The agent clicks the field
with its own tools, then asks the daemon to type by name."""

import json
import re
import select
import socket
import threading

from agent_baton import core, env_file, inject

NAME = re.compile(r"^[a-z][a-z0-9_]{0,31}$")
TYPE_REPLY_S = 45
NO_WINDOW = "refused: " + inject.CODES[2]  # this title matched nothing: try the next approved one
AUTOCOMPLETE = {
    "email": "username",
    "username": "username",
    "user": "username",
    "password": "current-password",
}


def sock_path(baton_id):
    return core.BATONS / f"{baton_id}.sock"


def autocomplete(name):
    return AUTOCOMPLETE.get(name, "one-time-code" if name in ("code", "otp") else "off")


class Ask:
    def __init__(self, baton, cfg):
        self.baton, self.cfg = baton, cfg
        self.secrets = {}  # name -> value, only ever read by `type`
        self.sock = None
        self.lock = threading.Lock()

    def start(self):
        path = sock_path(self.baton["id"])
        path.unlink(missing_ok=True)
        self.sock = socket.socket(socket.AF_UNIX)
        self.sock.bind(str(path))
        path.chmod(0o600)
        self.sock.listen(4)

    def stop(self):
        self.secrets.clear()
        for closer in (
            lambda: self.sock.close(),
            lambda: sock_path(self.baton["id"]).unlink(missing_ok=True),
        ):
            try:
                closer()
            except Exception:  # noqa: BLE001
                pass

    def tick(self):
        """Serve one `type` request if one is waiting."""
        if not select.select([self.sock], [], [], 0)[0]:
            return
        conn, _ = self.sock.accept()
        with conn:
            conn.settimeout(5)
            try:
                request = json.loads(conn.makefile().readline())
                reply = self.handle(request["verb"], request.get("args", []), request.get("opts", {}))
            except Exception as error:  # noqa: BLE001 - say what failed, never what was typed
                reply = {"text": f"error: {type(error).__name__}", "code": 1}
            conn.settimeout(TYPE_REPLY_S)
            conn.sendall((json.dumps(reply) + "\n").encode())

    def handle(self, verb, args, opts):
        if verb not in ("type", "focus"):
            return {"text": f"unknown verb {verb!r}", "code": 2}
        if verb == "type":
            (name,) = args
            with self.lock:
                secret = self.secrets.get(name)
            if secret is None:
                known = ", ".join(self.secrets) or "nothing yet (the human has not answered)"
                return {"text": f"refused: no secret named {name!r}; held: {known}", "code": 1}
        for window in self.baton["windows"]:  # the titles the human approved, in order
            if verb == "focus":
                status = inject.focus(window, self.cfg["no_type"])
            else:
                status = inject.type_into(
                    window, secret, opts.get("enter", False), self.cfg["no_type"], opts.get("clear", False)
                )
            if not status.startswith(NO_WINDOW):
                break
        return {"text": status, "code": 1 if status.startswith("refused") else 0}

    def answer(self, values):
        """Called from a page thread with the human's answers."""
        if self.baton["kind"] == "env":
            with self.lock:
                baton = core.load(self.baton["id"])
                if baton["status"] != "held" or baton.get("answered"):
                    raise ValueError("request is no longer pending")
                backup = env_file.store(
                    self.baton["name"], values[self.baton["name"]], self.baton["files"], self.baton["prefix"]
                )
                core.save(
                    {**core.load(self.baton["id"]), "answered": True,
                     "backup": str(backup) if backup else ""}
                )
                core.resolve(self.baton["id"], "returned")
                return backup
        with self.lock:
            self.secrets = dict(values)
        baton = core.load(self.baton["id"])
        core.save({**baton, "answered": True, "expires": core.now() + baton["hold"]})


def request(baton_id, verb, args=(), opts=None):
    """The agent's side of the socket: one JSON line out, one back."""
    with socket.socket(socket.AF_UNIX) as conn:
        conn.settimeout(inject.SEND_TIMEOUT_S + 15)
        conn.connect(str(sock_path(baton_id)))
        conn.sendall((json.dumps({"verb": verb, "args": list(args), "opts": opts or {}}) + "\n").encode())
        return json.loads(conn.makefile().readline())
