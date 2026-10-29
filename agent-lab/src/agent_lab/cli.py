"""Small public CLI; registry state stays private and outside repositories."""

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

from .context import infer
from .files import existing_dir, inspect_tree
from .models import Actor
from .store import Store


def actor(args: argparse.Namespace) -> Actor:
    def supplied(name: str) -> str | None:
        return getattr(args, name) or os.environ.get(f"AGENT_LAB_{name.upper()}") or None

    detected = infer()
    harness = supplied("harness") or detected.harness
    session = supplied("session") or (detected.session if harness == detected.harness else None)
    same = harness == detected.harness and session == detected.session

    def git(*flags: str) -> str | None:
        try:
            result = subprocess.run(["git", "rev-parse", *flags], capture_output=True, text=True, timeout=3)
            return result.stdout.strip() if result.returncode == 0 and result.stdout.strip() else None
        except (OSError, subprocess.TimeoutExpired):
            return None

    repository = git("--show-toplevel")
    return Actor(
        harness,
        session,
        supplied("model") or (detected.model if same else None),
        supplied("effort") or (detected.effort if same else None),
        str(Path.cwd()),
        repository,
        git("--abbrev-ref", "HEAD") if repository else None,
        git("--verify", "HEAD") if repository else None,
    )


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(
        description="Persistent experiments with safe retirement. Caller context is detected automatically."
    )
    sub = root.add_subparsers(dest="action", required=True)
    new = sub.add_parser("new", help="create a private workspace; print its ID")
    new.add_argument("name", help="short lowercase name; a unique suffix is added")
    new.add_argument("--purpose", required=True)
    new.add_argument("--json", action="store_true")
    run = sub.add_parser(
        "run",
        help="run a command in work/, lease the workspace, preserve its exit code",
        epilog="agent-lab run [provenance flags] ID -- COMMAND [ARGS...]",
    )
    run.add_argument("id")
    for command in (new, run):
        for name in ("harness", "session", "model", "effort"):
            command.add_argument(f"--{name}", help=f"override inferred {name} or AGENT_LAB_{name.upper()}")
    listing = sub.add_parser("list", help="list registry entries, including provenance and state")
    listing.add_argument("--sizes", action="store_true", help="scan file counts and logical sizes")
    listing.add_argument("--json", action="store_true")
    show = sub.add_parser("show", help="show metadata, paths, sizes and warnings as JSON")
    show.add_argument("id")
    path = sub.add_parser("path", help="print the path for file/edit tools")
    path.add_argument("id")
    path.add_argument("--area", choices=("work", "artifacts", "tmp", "root"), default="work")
    for name in ("retire", "restore", "keep"):
        command = sub.add_parser(
            name,
            help={
                "retire": "mark done; allow GC after the grace period",
                "restore": "return to active; clear keep/retirement",
                "keep": "protect indefinitely; clear retirement",
            }[name],
        )
        command.add_argument("id")
        if name == "retire":
            command.add_argument("--days", type=int, default=14, help="grace period, default 14")
            command.add_argument("--summary", help="brief outcome; durable findings belong in project docs")
    gc = sub.add_parser(
        "gc", help="preview cleanup; only expired, retired, unleased, non-Git folders qualify"
    )
    gc.add_argument("--apply", action="store_true", help="delete eligible workspaces permanently")
    return root


def details(store: Store, identifier: str, *, sizes: bool = False) -> dict:
    record = store.read(identifier)
    result = {**record.to_dict(), "state": record.state, "running": store.running(identifier)}
    base = store.directory(identifier)
    existing_dir(base)
    result["paths"] = {name: str(base / name) for name in ("work", "artifacts", "tmp")}
    result["paths"]["root"] = str(base)
    if sizes:
        result["size"] = inspect_tree(base)
    return result


def main(argv: list[str] | None = None) -> int:
    root = parser()
    raw = list(sys.argv[1:] if argv is None else argv)
    command = []
    if raw[:1] == ["run"] and "--" in raw:
        separator = raw.index("--")
        command, raw = raw[separator + 1 :], raw[:separator]
    args = root.parse_args(raw)
    try:
        store = Store()
        if args.action == "run":
            if not command:
                root.error("run requires -- COMMAND [ARGS...]")
            code = store.run(args.id, command, actor(args))
            try:
                for warning in inspect_tree(store.directory(args.id))["warnings"]:
                    print(f"agent-lab: warning: {warning}", file=sys.stderr)
            except (OSError, ValueError) as exc:
                print(f"agent-lab: size scan unavailable: {exc}", file=sys.stderr)
            return code
        read_only = args.action in ("show", "path", "list")
        if args.action == "list" and not store.root.exists() and not store.root.is_symlink():
            if args.json:
                print("[]")
            return 0
        with store.locked(read_only=read_only):
            if args.action == "new":
                record = store.create(args.name, args.purpose, actor(args))
                print(json.dumps(details(store, record.id)) if args.json else record.id)
            elif args.action == "show":
                print(json.dumps(details(store, args.id, sizes=True), indent=2))
            elif args.action == "path":
                store.read(args.id)
                base = store.directory(args.id)
                existing_dir(base)
                private_path = base if args.area == "root" else base / args.area
                existing_dir(private_path)
                print(private_path)
            elif args.action == "list":
                values = [details(store, record.id, sizes=args.sizes) for record in store.all()]
                if args.json:
                    print(json.dumps(values, indent=2))
                else:
                    for entry in values:
                        source = entry["created_by"]
                        state = "running" if entry["running"] else entry["state"]
                        size = f"  {entry['size']['bytes']} bytes" if args.sizes else ""
                        print(
                            f"{entry['id']}  {state}  {source['harness'] or '?'} / "
                            f"{source['model'] or '?'}{size}"
                        )
                        for warning in entry.get("size", {}).get("warnings", []):
                            print(f"  warning: {warning}")
            elif args.action in ("retire", "restore", "keep"):
                record = store.change(
                    args.id,
                    args.action,
                    days=getattr(args, "days", 14),
                    summary=getattr(args, "summary", None),
                )
                print(
                    f"{record.id}  {record.state}"
                    + (f"  purge after {record.purge_after}" if record.purge_after else "")
                )
            elif args.action == "gc":
                results = store.gc(apply=args.apply)
                print(json.dumps(results, indent=2))
                return int(any(item["action"] == "blocked" for item in results))
        return 0
    except (OSError, ValueError, UnicodeError) as exc:
        print(f"agent-lab: {exc}", file=sys.stderr)
        if isinstance(exc, FileNotFoundError) and args.action == "run":
            return 127
        if isinstance(exc, PermissionError) and args.action == "run":
            return 126
        return 1
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
