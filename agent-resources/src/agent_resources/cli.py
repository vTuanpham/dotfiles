import argparse
import sys
from pathlib import Path

from . import control, heavy


def main():
    parser = argparse.ArgumentParser(description="Host admission for heavy foreground commands.")
    commands = parser.add_subparsers(dest="action", required=True)
    run = commands.add_parser("run", help="wait for headroom, then exec the command unchanged")
    run.add_argument("--mem", help="expected peak memory, such as 1G or 2500M")
    run.add_argument("--exclusive", action="store_true", help="isolate timing measurements")
    run.add_argument("--memory-max-mib", help="require a systemd memory cap")
    run.add_argument("argv", nargs=argparse.REMAINDER)
    commands.add_parser("list", help="inspect live requests")
    commands.add_parser("guide", help="read admission, ownership and cancellation details")
    commands.add_parser("cancel", help="cancel a request owned by this root").add_argument("target")
    commands.add_parser("pause", help="pause admissions").add_argument("--reason", default="maintenance")
    commands.add_parser("resume", help="resume admissions")
    args = parser.parse_args()
    try:
        if args.action == "run":
            argv = args.argv[1:] if args.argv[:1] == ["--"] else args.argv
            heavy.run(argv, args.memory_max_mib, mem=args.mem, exclusive=args.exclusive)
        elif args.action == "guide":
            print(Path(__file__).with_name("guide.md").read_text().strip())
        else:
            control.require_root()
            if args.action == "list":
                control.listing()
            elif args.action == "cancel":
                control.cancel(args.target)
            elif args.action == "pause":
                control.pause(args.reason)
            else:
                control.resume()
    except (OSError, ValueError, RuntimeError) as error:
        print(f"agent-resources: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
