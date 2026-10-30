"""Correctness hook: parse shell text without executing it; never inspect or signal processes."""

import json
import re
import shlex
import signal
import subprocess
import sys
from pathlib import PurePosixPath

REASON = (
    "Full-command pgrep/pkill matching can select this command's own shell or waiter. "
    "Use the native job/session stop or wait handle; otherwise verify an owned PID "
    "and signal/wait for that PID, or use an exact process-name query such as pgrep -x. "
    "Do not retry by moving the same pattern into another shell wrapper."
)


def literal(word):
    parts = word.get("Parts", [])
    values = []
    for part in parts:
        kind = part.get("Type")
        if kind == "Lit" or (kind == "SglQuoted" and not part.get("Dollar")):
            values.append(part.get("Value", ""))
        elif kind == "DblQuoted" and not part.get("Dollar"):
            value = literal(part)
            if value is None:
                return None
            values.append(value)
        else:
            return None  # variable/command expansion is not evaluated by this hook
    return "".join(values)


def calls(node):
    if isinstance(node, list):
        for item in node:
            yield from calls(item)
    elif isinstance(node, dict):
        if node.get("Type") == "CallExpr":
            yield [literal(word) for word in node.get("Args", [])]
        for value in node.values():
            yield from calls(value)


def unwrap(words):
    """Recognize common static launchers; this is a mistake guard, not a shell security boundary."""
    value_flags = {"-u", "--user", "-g", "--group", "-C", "--chdir", "--unset", "-s",
                   "--signal", "-k", "--kill-after"}
    while words and words[0]:
        name = PurePosixPath(words[0]).name
        if name == "rtk":
            words = words[1:]
            while words and words[0] == "--skip-env":
                words = words[1:]
            if words and words[0] in ("summary", "err", "test", "bypass", "proxy"):
                words = words[1:]
            elif words and words[0] == "run":
                words = words[1:]
                shell = "sh"
                while words and words[0]:
                    if words[0] == "--shell" and len(words) > 1:
                        shell, words = words[1], words[2:]
                    elif words[0].startswith("--shell="):
                        shell, words = words[0].split("=", 1)[1], words[1:]
                    elif words[0] in ("-c", "--command") and len(words) > 1:
                        return [shell, "-c", words[1]]
                    elif words[0].startswith("--command="):
                        return [shell, "-c", words[0].split("=", 1)[1]]
                    elif words[0] in ("--skip-env", "--"):
                        words = words[1:]
                    else:
                        break
        elif name in ("command", "exec", "env", "sudo", "nohup", "timeout"):
            words = words[1:]
            while words and words[0] is not None:
                flag = words[0]
                if flag == "--":
                    words = words[1:]
                    break
                if "=" in flag and re.match(r"[A-Za-z_][A-Za-z0-9_]*=", flag):
                    words = words[1:]
                elif flag.startswith("-"):
                    words = words[2:] if flag in value_flags else words[1:]
                else:
                    break
            if name == "timeout":
                words = words[1:]
        elif name in ("docker", "podman") and len(words) > 1 and words[1] == "exec":
            words = words[2:]
            while words and words[0] is not None and words[0].startswith("-"):
                flag = words[0]
                if flag == "--":
                    words = words[1:]
                    break
                takes_value = flag in ("-e", "--env", "--env-file", "-u", "--user", "-w", "--workdir")
                words = words[2:] if takes_value else words[1:]
            words = words[1:]  # container name, followed by its literal command
        else:
            break
    return words


def process_flags(name, words):
    flags = set()
    skip = False
    valued = {"--delimiter", "--pgroup", "--group", "--older", "--parent", "--session", "--terminal",
              "--euid", "--uid", "--pidfile", "--runstates", "--ns", "--nslist", "--signal", "--queue",
              "--cgroup", "--env", "--pid"}
    signals = {"-" + key for key in signal.Signals.__members__}
    signals |= {key.replace("-SIG", "-", 1) for key in signals}
    for word in words:
        if skip:
            skip = False
            continue
        if word == "--":
            break
        if word is None or not word.startswith("-"):
            continue
        if name == "pkill" and word in signals:
            continue
        if word.startswith("--"):
            option, equals, _ = word.partition("=")
            if option in valued:
                skip = not equals
            else:
                flags.add(option)
            continue
        for index, flag in enumerate(word[1:], 1):
            if flag in "dgGOPpstuUFrq":
                skip = index == len(word) - 1
                break
            flags.add(flag)
    return flags


def inspect(command, depth=0):
    if depth > 8 or len(command) > 1024 * 1024:
        return "Process-match guard could not inspect this command; use an explicit owned PID."
    parsed = subprocess.run(["shfmt", "-ln", "bash", "-tojson"], input=command,
                            capture_output=True, text=True, timeout=3)
    if parsed.returncode:
        return ("Process-match guard could not parse this shell syntax; "
                "use a native handle or explicit owned PID.")
    tree = json.loads(parsed.stdout)
    if not isinstance(tree, dict) or tree.get("Type") != "File":
        raise ValueError("unsupported shell AST")
    for argv in calls(tree):
        words = unwrap(argv)
        if not words or words[0] is None:
            continue
        name = PurePosixPath(words[0]).name
        if name in ("bash", "sh", "dash", "zsh"):
            for i, flag in enumerate(words[1:], 1):
                if (flag and re.fullmatch(r"-[A-Za-z]*c[A-Za-z]*", flag)
                        and i + 1 < len(words) and words[i + 1] is not None):
                    reason = inspect(words[i + 1], depth + 1)
                    if reason:
                        return reason
                    break
        if name not in ("pgrep", "pkill"):
            continue
        flags = process_flags(name, words[1:])
        if flags.intersection(("--help", "--version", "h", "V")):
            continue
        full = bool(flags.intersection(("--full", "f")))
        ancestors = bool(flags.intersection(("--ignore-ancestors", "A")))
        if full and not ancestors:
            return REASON
    return None


def main():
    try:
        event = json.load(sys.stdin)
        antigravity = "toolCall" in event
        if antigravity:
            tool_input = event["toolCall"].get("args") or {}
            command = tool_input.get("CommandLine", "")
        else:
            tool_input = event.get("tool_input") or {}
            command = tool_input.get("command", tool_input.get("cmd", ""))
        if isinstance(command, list):
            command = shlex.join(command)
        reason = None
        if not isinstance(command, str) or not re.search(r"\b(?:pgrep|pkill)\b", command):
            if antigravity:
                print(json.dumps({"decision": "allow"}))
            return 0
        try:
            reason = inspect(command)
        except (OSError, ValueError, subprocess.SubprocessError, RecursionError):
            reason = "Process-match guard is unavailable; use a native job handle or explicit owned PID."
        if antigravity:
            print(json.dumps({"decision": "deny", "reason": reason} if reason else {"decision": "allow"}))
        elif reason:
            print(reason, file=sys.stderr)
            return 2
    except (ValueError, TypeError, AttributeError):
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
