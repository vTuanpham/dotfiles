"""Reuse existing provider CLIs and caches; never switch accounts or create auth stores."""

import json
import os
import re
import subprocess
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

from .models import loads
from .readers import agy_quota, codex_quotas

ACCOUNTS = Path.home() / ".agy-accounts"
TOKEN = Path(".gemini/antigravity-cli/antigravity-oauth-token")


def account_env(account, root=None):
    if not isinstance(account, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", account):
        raise ValueError("invalid account identifier")
    home = (root or ACCOUNTS) / account
    if home.is_symlink() or not (home / TOKEN).is_file():
        raise ValueError("account must already be signed in")
    # Explicit account queries use that account's existing file auth, not inherited API credentials.
    env = {name: value for name, value in os.environ.items()
           if not re.search("KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL|AUTH|COOKIE", name, re.I)}
    return {**env, "HOME": str(home)}


def snapshot(now=None, *, root=None, environ=None):
    now = time.time() if now is None else now
    root = root or ACCOUNTS
    result, errors = [], []
    try:
        run = subprocess.run(["codex-auth", "list"], capture_output=True, text=True,
                             timeout=5, env=environ)
        if run.returncode:
            raise ValueError("unavailable")
        result.extend(codex_quotas(run.stdout))
    except (OSError, ValueError, subprocess.SubprocessError):
        errors.append("codex quota unavailable")
    for path in sorted(root.glob("*/quota.json")):
        try:
            if (path.is_symlink() or not path.resolve().is_relative_to(root.resolve())
                    or path.stat().st_size > 1048576):
                raise ValueError("unsafe quota cache")
            observation = agy_quota(loads(path.read_text()), now)
            if observation.account != path.parent.name:
                raise ValueError("quota account mismatch")
            result.append(observation)
        except (OSError, ValueError, TypeError):
            errors.append("agy quota cache invalid")
    return tuple(result), errors


def refresh(account, *, root=None, environ=None):
    root = root or ACCOUNTS
    env = account_env(account, root)
    if environ is not None:
        env = {**environ, "HOME": env["HOME"]}
    directory = root / account
    if directory.is_symlink() or not (directory / TOKEN).is_file():
        raise ValueError("account must already be signed in")
    result = subprocess.run(["agy", "--output-format", "json", "-p=/usage"], env=env,
                            capture_output=True, text=True, timeout=120, cwd=str(directory))
    if result.returncode:
        raise RuntimeError(f"agy usage query failed (exit {result.returncode})")
    out = loads(result.stdout)
    rows = []
    for line in out.get("result", out).get("response", "").splitlines():
        parts = line.split("\t")
        if len(parts) == 4 and parts[2].rstrip("%").isdigit():
            rows.append(dict(group=parts[0], limit=parts[1], remaining=int(parts[2].rstrip("%")),
                             resets=parts[3]))
    data = {"account": account, "at": datetime.now(timezone.utc).isoformat(), "rows": rows}
    observation = agy_quota(data, time.time())
    descriptor, name = tempfile.mkstemp(prefix=".quota-", dir=directory)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(data, stream)
        os.replace(name, directory / "quota.json")
    finally:
        Path(name).unlink(missing_ok=True)
    return observation
