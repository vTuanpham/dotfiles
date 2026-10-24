"""Explicit interactive opt-in; preserve the native terminal and remote-control setup."""

import json
import os
import shutil
import subprocess
import sys
import uuid
from pathlib import Path

from .claude import sessions
from .claude_channel import profile_channels
from .models import Target


def target(store, command, config_dir):
    executable = shutil.which(command)
    if executable is None:
        raise ValueError("Native Claude executable not found")
    config_dir = str(Path(config_dir).expanduser().resolve())
    return Target(uuid.uuid4().hex, "claude", "Claude", "connection", "Claude",
                  {"command": executable, "config_dir": config_dir,
                   "channels": str(profile_channels(store.home, config_dir))})


def launch(store, command, config_dir, resume, native_args):
    selected = target(store, command, config_dir)
    identifier = resume or str(uuid.uuid4())
    if str(uuid.UUID(identifier)) != identifier:
        raise ValueError("Use the native session UUID")
    blocked = {"--resume", "-r", "--continue", "-c", "--session-id", "--fork-session",
               "--print", "-p", "--dangerously-load-development-channels", "--channels"}
    native_args = native_args[1:] if native_args[:1] == ["--"] else native_args
    if any(value.split("=", 1)[0] in blocked for value in native_args):
        raise ValueError("Session identity, channel opt-in and interactive mode are owned by this launcher")
    if resume and any(row["sessionId"] == identifier for row in sessions(selected)):
        raise ValueError("Close that native session before restarting it with the inbox channel")
    selected = store.register(selected)
    configuration = {"mcpServers": {"agent-inbox": {
        "command": sys.executable,
        "args": ["-m", "agent_inbox.cli", "--state", str(store.home),
                 "claude-channel", "--session", identifier, "--config-dir", selected.settings["config_dir"]],
    }}}
    arguments = [selected.settings["command"], "--resume" if resume else "--session-id", identifier,
                 "--mcp-config", json.dumps(configuration),
                 "--dangerously-load-development-channels", "server:agent-inbox", *native_args]
    # Claude presents its own development-channel consent; do not automate or suppress it.
    return subprocess.call(arguments, env={**os.environ,
                                           "CLAUDE_CONFIG_DIR": selected.settings["config_dir"]})
