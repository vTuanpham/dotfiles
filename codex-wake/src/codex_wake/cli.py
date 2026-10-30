"""Small CLI for event producers and background command completion."""

import argparse
import os
import subprocess
import sys

from .client import Wake, validate_message

NOTICE = "Automatic task notification, not user approval."


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Deliver task notifications to an existing Codex conversation.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  codex-wake check\n"
            '  codex-wake run --message "Tests finished. Review the results." -- uv run pytest\n'
            '  codex-wake send --message "The awaited file arrived."\n'
            "\nTargets this session by default (CODEX_THREAD_ID and CODEX_HOME).\n"
            "Start run in a persistent background terminal, then continue independent work.\n"
            "Its notification can resume this conversation after the model turn ends.\n"
            "Read command output from the original terminal after waking.\n"
            "Bridge watch already handles delivery; do not wrap it again.\n"
            "Use SUBCOMMAND --help for explicit target options."
        ),
    )
    commands = parser.add_subparsers(dest="action", required=True)
    for action in ("check", "send", "run"):
        command = commands.add_parser(
            action,
            help={
                "check": "verify native delivery without waking the session",
                "send": "send one task notification",
                "run": "run a command, then notify on success or failure",
            }[action],
        )
        command.add_argument(
            "--thread",
            default=os.environ.get("CODEX_THREAD_ID"),
            help="target thread (default: CODEX_THREAD_ID)",
        )
        command.add_argument("--home", help="target Codex home (default: CODEX_HOME or ~/.codex)")
        if action != "check":
            command.add_argument(
                "--message", required=True, help="short event context; never include secrets"
            )
        if action == "run":
            command.add_argument("command", nargs=argparse.REMAINDER, help="-- PROGRAM [ARG ...]")
    args = parser.parse_args(argv)
    if args.action == "run":
        command = args.command[1:] if args.command[:1] == ["--"] else args.command
        if not command:
            parser.error("run requires a command after --")
    try:
        target = Wake(args.thread, args.home)
        if args.action != "check":
            prompt = f"{args.message}\n{NOTICE}"
            validate_message(args.message)
            validate_message(
                prompt if args.action == "send" else f"Command exited with status -255. {prompt}"
            )
        target.check()
        if args.action == "check":
            print(f"Native Codex wake delivery ready: {target.thread}")
            return 0
        if args.action == "send":
            target.send(prompt)
            return 0
        try:
            code = subprocess.run(command, check=False).returncode
        except OSError as exc:
            target.send(f"Command could not start. {prompt}")
            print(f"codex-wake: command could not start ({type(exc).__name__})", file=sys.stderr)
            return 127
        target.send(f"Command exited with status {code}. {prompt}")
        return code if code >= 0 else 128 - code
    except (RuntimeError, OSError) as exc:
        print(f"codex-wake: {exc}", file=sys.stderr)
        return 125
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
