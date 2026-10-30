"""Native CLI inventory; availability never establishes subscription entitlement."""

import re
import shutil
import subprocess
from pathlib import Path

from agent_accounts.models import loads
from agent_accounts.providers import account_env

# Reviewed privacy policy used by Bridge admission and reference validation.
ZDR_FREE = (
    "opencode/glm-5.3-flash-free",
    "opencode/deepseek-v4.1-flash-free",
    "opencode/minimax-m3.1-flash-free",
)


def logged_free(model):
    free = not model or (model.startswith("opencode/") and
                         ("free" in model or model == "opencode/big-pickle"))
    return free and model not in ZDR_FREE


def parse_codex(catalog):
    rows = []
    value = loads(catalog)
    if type(value) is not dict or type(value.get("models")) is not list:
        raise ValueError("invalid Codex model catalog")
    seen = set()
    for model in value["models"]:
        if type(model) is not dict or type(model.get("slug")) is not str:
            raise ValueError("invalid Codex model entry")
        identifier = model["slug"]
        if not identifier or any(c.isspace() or ord(c) < 32 for c in identifier) or identifier in seen:
            raise ValueError("invalid or duplicate model identity")
        seen.add(identifier)
        if model.get("visibility") not in ("list", "hide"):
            raise ValueError("unknown Codex catalog visibility")
        if model["visibility"] == "list":
            levels = model.get("supported_reasoning_levels")
            if type(levels) is not list or any(type(level) is not dict or
                    type(level.get("effort")) is not str for level in levels):
                raise ValueError("invalid Codex reasoning levels")
            efforts = ",".join(level["effort"] for level in levels)
            rows.append(f"{model['slug']}\t{efforts or '-'}")
    return rows


def show(backend, account="a1"):
    if backend == "claude":
        print("\n".join(f"{name}\t-\talias" for name in ("sonnet", "opus", "haiku", "fable")))
        return
    if backend == "codex":
        command = ["codex", "debug", "models"]
    elif backend == "agy":
        command = ["agy", "models"]
    elif backend == "opencode":
        command = [shutil.which("opencode") or str(Path.home() / ".opencode/bin/opencode"), "models"]
    else:
        raise ValueError("unknown model inventory backend")
    result = subprocess.run(command, env=account_env(account) if backend == "agy" else None,
                            capture_output=True, text=True, timeout=120)
    if result.returncode:
        raise RuntimeError(f"{backend} model inventory failed (exit {result.returncode})")
    if backend == "codex":
        rows = parse_codex(result.stdout)
    elif backend == "agy":
        rows = []
        for line in result.stdout.splitlines():
            if not line.strip():
                continue
            identifier, tab, label = line.partition("\t")
            if not tab or not identifier or not label or any(c.isspace() for c in identifier):
                raise ValueError("invalid agy model inventory")
            if "gpt-oss" not in identifier:
                rows.append(line)
    else:
        if any(line and not re.fullmatch(r"[^\s/]+/[^\s]+", line)
               for line in result.stdout.splitlines()):
            raise ValueError("invalid OpenCode model inventory")
        rows = [f"{line}\t-\t{'free-logged' if logged_free(line) else 'free' if 'free' in line else 'paid'}"
                for line in sorted(result.stdout.splitlines(),
                                   key=lambda row: ("free" not in row.casefold(), row.casefold()))]
    print("\n".join(rows))
