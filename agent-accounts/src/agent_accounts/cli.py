import argparse
import json
import subprocess
import sys
from dataclasses import asdict
from datetime import datetime, timezone

from . import providers


def main():
    parser = argparse.ArgumentParser(description="Account observations, independent of job state.")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("snapshot", help="read cached account observations as JSON; no provider refresh")
    refresh = commands.add_parser("refresh", help="explicitly query existing provider account allowance")
    refresh.add_argument("--backend", choices=("agy", "claude"), default="agy")
    refresh.add_argument("--account", help="one signed-in account; omitted means all existing accounts")
    args = parser.parse_args()
    try:
        if args.command == "refresh":
            if args.backend == "claude":
                if args.account:
                    parser.error("Claude refresh reads the managed cswap inventory; omit --account")
                providers.refresh_claude()
            else:
                accounts = ([args.account] if args.account else
                            [path.name for path in sorted(providers.ACCOUNTS.glob("*"))
                             if path.is_dir() and (path / providers.TOKEN).is_file()])
                for account in accounts:
                    providers.refresh(account)
        quotas, errors = providers.snapshot()
        value = {"schema_version": 1, "generated_at": datetime.now(timezone.utc).isoformat(),
                 "quotas": [asdict(row) for row in quotas], "errors": errors}
        print(json.dumps(value, allow_nan=False))
    except (OSError, ValueError, RuntimeError, TypeError, AttributeError,
            subprocess.SubprocessError) as error:
        print(f"agent-accounts: {type(error).__name__}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
