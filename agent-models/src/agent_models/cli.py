"""Read and maintain the shared model reference without loading Bridge."""

import argparse
import json
import os
import sys

from . import inventory, reference, refresh


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(prog="model-guide", description="Shared model selection reference.")
    commands = parser.add_subparsers(dest="command", required=True)
    read = commands.add_parser("read", help="read only the reference needed for this task")
    read.add_argument("topic", choices=("models", "subscriptions", "sources", "maintenance"))
    for name in ("check", "stale"):
        suffix = " as JSON" if name == "check" else " and cache warnings"
        check = commands.add_parser(name, help="inspect reference drift" + suffix)
        check.add_argument("--live", action="store_true",
                           help="explicitly query signed-in native CLI inventories")
    models = commands.add_parser("models", help="list native CLI inventory; not account entitlement")
    models.add_argument("--backend", choices=("codex", "claude", "agy", "opencode"), required=True)
    models.add_argument("--account", default="a1", help="existing agy account")
    update = commands.add_parser("refresh", help="propose or explicitly review a reference update")
    action = update.add_mutually_exclusive_group()
    for flag in ("force", "apply", "record", "discard"):
        action.add_argument("--" + flag, action="store_true")
    update.add_argument("--yes", action="store_true", help="confirm completed source review")
    args = parser.parse_args()
    try:
        if args.command == "read":
            print((reference.GUIDES / (args.topic + ".md")).read_text().strip())
        elif args.command == "models":
            inventory.show(args.backend, args.account)
        elif args.command == "check":
            print(json.dumps(reference.inspect(probe=args.live), indent=2))
        elif args.command == "stale":
            found = reference.check(probe=args.live)
            print("\n".join(found) if found else "the reference is current")
            return int(bool(found))
        elif args.apply:
            return refresh.apply(args.yes)
        elif args.record:
            return refresh.record(args.yes)
        elif args.discard:
            return refresh.discard()
        else:
            return refresh.run(args.force)
    except (OSError, ValueError, RuntimeError, KeyError) as error:
        print(f"model-guide: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
