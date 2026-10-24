"""Read and reply to root agent conversations from your phone."""

import argparse
import asyncio
import fcntl
import os
import shutil
import subprocess
import uuid
from pathlib import Path

from .adapters import ADAPTERS, adapter
from .catalog import Catalog
from .models import Target, decode_json, https_url, text
from .server import App, Server
from .store import Store


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state", type=Path, default=Path(os.environ.get(
        "AGENT_INBOX_HOME", str(Path(os.environ.get("XDG_STATE_HOME", "~/.local/state")).expanduser()
                                / "agent-inbox"))))
    sub = parser.add_subparsers(dest="action", required=True)
    add = sub.add_parser("add-codex", help="register an existing root on a running local daemon")
    add.add_argument("--session", required=True)
    add.add_argument("--label", required=True)
    add.add_argument("--command", default="codex")
    opencode = sub.add_parser("add-opencode", help="connect to an already-running native v2 service")
    opencode.add_argument("--service", type=Path, default=Path(os.environ.get(
        "XDG_STATE_HOME", str(Path.home() / ".local/state"))) / "opencode/service.json")
    acp = sub.add_parser("add-acp", help="connect to an installed ACP agent's own saved sessions")
    acp.add_argument("--harness", required=True)
    acp.add_argument("--bridge-backend", choices=("codex", "claude", "agy", "opencode"))
    acp.add_argument("--cwd", type=Path)
    acp.add_argument("--command", required=True, nargs=argparse.REMAINDER,
                     help="executable and exact arguments; put this option last")
    for action, description in (("add-claude", "connect to native Claude live-session discovery"),
                                ("claude", "open the native terminal with the optional inbox channel")):
        claude = sub.add_parser(action, help=description)
        claude.add_argument("--command", default="claude")
        claude.add_argument("--config-dir", type=Path, default=Path(os.environ.get(
            "CLAUDE_CONFIG_DIR", str(Path.home() / ".claude"))))
        if action == "claude":
            claude.add_argument("--resume")
            claude.add_argument("native_args", nargs=argparse.REMAINDER)
    channel = sub.add_parser("claude-channel",
                             help="run the native Claude channel (normally started by the launcher)")
    channel.add_argument("--session", required=True)
    channel.add_argument("--config-dir", type=Path, required=True)
    native = sub.add_parser("add-native", help="register another harness's existing native root link")
    for option in ("harness", "session", "label", "url"):
        native.add_argument("--" + option, required=True)
    listing = sub.add_parser("list", help="list live roots, or saved registrations with --configured")
    listing.add_argument("--configured", action="store_true")
    remove = sub.add_parser("remove", help="remove a saved registration; keep native conversations")
    remove.add_argument("id")
    sub.add_parser("pair", help="human: print a one-use code locally; never paste it into agent chat")
    sub.add_parser("devices")
    revoke = sub.add_parser("revoke")
    revoke.add_argument("id")
    serve = sub.add_parser("serve")
    serve.add_argument("--port", type=int, default=8766)
    serve.add_argument("--public-url", default="")
    args = parser.parse_args()
    os.umask(0o077)
    store = Store(args.state.expanduser())
    try:
        if args.action == "claude-channel":
            from .claude_channel import profile_channels, run

            asyncio.run(run(profile_channels(store.home, args.config_dir), args.session, args.config_dir))
        elif args.action == "claude":
            from .claude_launch import launch

            raise SystemExit(launch(store, args.command, args.config_dir, args.resume, args.native_args))
        elif args.action == "add-claude":
            from .claude import sessions
            from .claude_launch import target

            selected = target(store, args.command, args.config_dir)
            sessions(selected)
            selected = store.register(selected)
            print(f"Connected Claude profile: {selected.id}")
        elif args.action == "add-acp":
            if not args.command or not (command := shutil.which(args.command[0])):
                raise ValueError("ACP executable not found")
            settings = {"command": [command, *args.command[1:]]}
            if args.cwd:
                settings["cwd"] = str(args.cwd.expanduser().resolve())
            if args.bridge_backend:
                settings["bridge_backend"] = args.bridge_backend
            selected = Target(uuid.uuid4().hex, "acp", text(args.harness, "harness", 60),
                              "connection", text(args.harness, "harness", 60), settings)
            adapter(selected).discover(selected)
            selected = store.register(selected)
            print(f"Connected ACP source: {selected.id}")
        elif args.action == "add-opencode":
            target = Target(uuid.uuid4().hex, "opencode", "OpenCode", "connection", "OpenCode",
                            {"service": str(args.service.expanduser().absolute())})
            adapter(target).discover(target)
            target = store.register(target)
            print(f"Connected OpenCode service: {target.id}")
        elif args.action in ("add-codex", "add-native"):
            for name in ("session", "label"):
                text(getattr(args, name), name, 200)
            if args.action == "add-codex":
                command = shutil.which(args.command)
                if not command:
                    raise ValueError("Harness executable not found")
                info = decode_json(subprocess.check_output(
                    [command, "app-server", "daemon", "version"], timeout=10, text=True,
                ))
                if (type(info) is not dict or info.get("status") != "running"
                        or type(info.get("socketPath")) is not str):
                    raise ValueError("Start your root session's native daemon before registering it")
                managed = info.get("managedCodexPath")
                if type(managed) is str and Path(managed).is_absolute() and os.access(managed, os.X_OK):
                    command = managed
                target = Target(uuid.uuid4().hex, "codex", "Codex", args.session, args.label,
                                {"socket": info["socketPath"], "command": [command]})
            else:
                target = Target(uuid.uuid4().hex, "native", text(args.harness, "harness", 60),
                                args.session, args.label, {"url": https_url(args.url)})
            adapter(target).snapshot(target)
            target = store.register(target)
            print(f"Registered root {target.id}: {target.label}")
        elif args.action == "pair":
            print("Pairing code (one use, five minutes): " + store.pair_code())
            print("Enter it on your phone's inbox page. Keep it out of agent chat and logs.")
        elif args.action == "devices":
            for identifier, name in store.devices():
                print(f"{identifier}  {name}")
        elif args.action == "revoke":
            store.revoke(args.id)
            print("Device revoked")
        elif args.action == "remove":
            store.remove(args.id)
            print("Inbox entry removed")
        elif args.action == "list":
            if args.configured:
                for target in store.targets():
                    print(f"{target.id}  {target.harness}  {target.label}")
            else:
                result = Catalog(store).listing()
                for row in result["roots"]:
                    print(f"{row['id']}  {row['harness']}  {row['status']}  {row['label']}")
                for warning in result["warnings"]:
                    print(warning)
        elif args.action == "serve":
            with (store.home / "server.lock").open("a") as lock:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                store.recover()
                with Server(App(store), args.port, args.public_url) as server:
                    print(f"Inbox listening on loopback port {server.server_address[1]}", flush=True)
                    server.serve_forever()
    except (OSError, RuntimeError, ValueError, KeyError, subprocess.SubprocessError, ExceptionGroup) as error:
        parser.exit(1, f"agent-inbox: {type(error).__name__}; check native harness and configuration\n")
    finally:
        ADAPTERS["acp"].runtimes.close()


if __name__ == "__main__":
    main()
