"""Read and maintain the shared model reference without loading Bridge."""

import argparse
import json
import os
import sys

from . import benchmarks, coverage, inventory, reference, refresh, shortlist


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(prog="model-guide", description="Shared model selection reference.")
    commands = parser.add_subparsers(dest="command", required=True)
    read = commands.add_parser("read", help="read only the reference needed for this task")
    read.add_argument("topic", choices=("models", "subscriptions", "sources", "maintenance"))
    compare = commands.add_parser("benchmarks", help="search benchmark evidence with local account context")
    compare.add_argument("--domain", choices=benchmarks.DOMAINS, default="overall")
    compare.add_argument("--query", default="", help="case-insensitive model name/ID substring")
    compare.add_argument("--limit", type=int, choices=range(1, 21), default=5, metavar="1..20")
    compare.add_argument("--backend", choices=("codex", "claude", "agy", "opencode"),
                         help="match evidence to this native model/effort catalog")
    compare.add_argument("--account", help="exact local account ID; requires --backend")
    compare.add_argument("--brief", action="store_true",
                         help="compact evidence, native controls and account hints")
    for name in ("check", "stale"):
        suffix = " as JSON" if name == "check" else " and cache warnings"
        check = commands.add_parser(name, help="inspect reference drift" + suffix)
        check.add_argument("--live", action="store_true",
                           help="explicitly query signed-in native CLI inventories")
    models = commands.add_parser("models", help="list native CLI inventory; not account entitlement")
    models.add_argument("--backend", choices=("codex", "claude", "agy", "opencode"), required=True)
    models.add_argument("--account", help="existing agy account; otherwise current native profile")
    models.add_argument("--json", action="store_true",
                        help="native IDs/efforts and generated benchmark coverage")
    update = commands.add_parser("refresh", help="propose or explicitly review a reference update")
    action = update.add_mutually_exclusive_group()
    for flag in ("force", "prepare", "apply", "record", "discard"):
        action.add_argument("--" + flag, action="store_true")
    update.add_argument("--yes", action="store_true", help="confirm completed source review")
    args = parser.parse_args()
    try:
        if args.command == "read":
            print((reference.GUIDES / (args.topic + ".md")).read_text().strip())
        elif args.command == "benchmarks":
            if args.account and not args.backend:
                parser.error("--account requires --backend")
            catalog = inventory.catalog(args.backend, args.account if args.backend == "agy" else None) \
                if args.backend else None
            result = benchmarks.search(args.domain, args.query, args.limit, catalog)
            result["account_observation"] = benchmarks.account_observation(args.backend, args.account)
            print(shortlist.brief(result) if args.brief else json.dumps(result, indent=2))
        elif args.command == "models":
            if args.json:
                print(json.dumps(coverage.summarize(inventory.catalog(args.backend, args.account),
                                                    benchmarks.snapshot()), indent=2))
            else:
                inventory.show(args.backend, args.account)
        elif args.command == "check":
            print(json.dumps(reference.inspect(probe=args.live), indent=2))
        elif args.command == "stale":
            found = reference.check(probe=args.live)
            print("\n".join(found) if found else "the reference is current")
            return int(bool(found))
        elif args.prepare:
            print(benchmarks.prepare())
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
