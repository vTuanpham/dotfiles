"""`agent-baton doctor`: one line per thing the tool leans on, so a silent failure has a name."""

import ctypes
import json
import shutil
import subprocess
from pathlib import Path
from urllib.parse import urlsplit

from agent_baton import core, inject

HOOKS = (Path("~/.claude/settings.json"), Path("~/.codex/hooks.json"))  # the harnesses that run the guard


def libs_load():
    try:
        return all(ctypes.CDLL(name) for name in ("libX11.so.6", "libXtst.so.6"))
    except OSError:
        return False


def forwards():
    """{tailnet port: local target} that `tailscale serve` forwards, or None when it cannot be read."""
    try:
        out = subprocess.run(
            ["tailscale", "serve", "status", "--json"], capture_output=True, text=True, timeout=10
        )
        return {port: spec.get("TCPForward") for port, spec in json.loads(out.stdout).get("TCP", {}).items()}
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


def phone_gaps(cfg):
    if not cfg["url"]:
        return []
    gaps = [] if cfg["ntfy"] else ["no `ntfy` topic in the config, so the phone gets no alert"]
    forwarded = forwards()
    if forwarded is None:
        return [*gaps, "`tailscale serve status` failed: is Tailscale up?"]
    first = urlsplit(cfg["url"]).port or 80
    for slot in range(cfg["slots"]):
        want = f"127.0.0.1:{cfg['port'] + slot}"
        if forwarded.get(str(first + slot)) != want:
            gaps.append(f"tailscale serve --bg --tcp={first + slot} tcp://{want}")
    return gaps


def checks(cfg):
    """(what, problems): an empty list means ok."""
    hooked = [
        path
        for path in map(Path.expanduser, HOOKS)
        if path.parent.is_dir() and not (path.is_file() and "agent-baton guard" in path.read_text("utf-8"))
    ]
    yield (
        "toast and Windows typing",
        [] if shutil.which(inject.POWERSHELL) else ["powershell.exe is not on PATH"],
    )
    yield (
        "WSLg typing",
        [] if shutil.which("xwininfo") and libs_load() else ["install x11-utils and libxtst6"],
    )
    yield "guard hook", [f"{path} has no `agent-baton guard` PreToolUse hook" for path in hooked]
    yield "phone", phone_gaps(cfg)


def main():
    cfg, failed = core.config(), False
    for what, problems in checks(cfg):
        failed |= bool(problems)
        print(f"{'FIX' if problems else 'ok '}  {what}" + "".join(f"\n       {line}" for line in problems))
    return int(failed)
