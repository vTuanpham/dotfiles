"""Reuse existing provider CLIs and caches; never switch accounts or create auth stores."""

import json
import os
import re
import subprocess
import tempfile
import time
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from .models import loads
from .readers import agy_quota, claude_quotas, codex_quotas

ACCOUNTS = Path.home() / ".agy-accounts"
TOKEN = Path(".gemini/antigravity-cli/antigravity-oauth-token")
CLAUDE_CACHE = (Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local/state"))
                / "agent-accounts/claude.json")


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


def snapshot(now=None, *, root=None, environ=None, claude_cache=None):
    now = time.time() if now is None else now
    root = root or ACCOUNTS
    result, errors = [], []
    try:
        run = subprocess.run(["codex-auth", "list", "--skip-api"], capture_output=True, text=True,
                             timeout=5, env=environ)
        if run.returncode:
            raise ValueError("unavailable")
        result.extend(codex_quotas(run.stdout))
    except (OSError, ValueError, subprocess.SubprocessError):
        errors.append("codex quota unavailable")
    cache = CLAUDE_CACHE if claude_cache is None else claude_cache
    try:
        if cache.is_symlink() or cache.parent.is_symlink() or cache.stat().st_size > 1048576:
            raise ValueError("unsafe Claude quota cache")
        result.extend(claude_quotas(loads(cache.read_text()), now))
    except FileNotFoundError:
        pass
    except (OSError, ValueError, TypeError, OverflowError):
        errors.append("claude quota cache invalid")
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


def context():
    """Local profile hints, not a claim about an already-running session's identity."""
    quotas, errors = snapshot()
    profiles = {}
    try:
        run = subprocess.run(["claude", "auth", "status", "--json"], capture_output=True,
                             text=True, timeout=10)
        if run.returncode or len(run.stdout.encode()) > 65536:
            raise ValueError("Claude auth status unavailable")
        data = loads(run.stdout)
        if type(data) is not dict or type(data.get("loggedIn")) is not bool:
            raise ValueError("invalid Claude auth status")
        profile = {"logged_in": data["loggedIn"]}
        for key in ("authMethod", "apiProvider", "subscriptionType"):
            value = data.get(key)
            if value is not None and (type(value) is not str or not re.fullmatch(r"[\w .-]{1,100}", value)):
                raise ValueError("invalid Claude profile value")
            profile[key] = value
        profiles["claude"] = profile
    except (OSError, ValueError, subprocess.SubprocessError):
        errors.append("Claude native profile unavailable")
    return {"quotas": [asdict(row) for row in quotas], "profiles": profiles, "errors": errors,
            "scope": "local profiles; current session account binding unverified",
            "access": "Plan labels are observed, not hardcoded. Active-profile markers do not prove "
                      "an existing session uses that account. Confirm native session account, model "
                      "picker and billing mode before selecting. Optional paid credits are not "
                      "included allowance or permission to spend.",
            "reference": "model-guide read subscriptions"}


def refresh_claude(*, cache=None, environ=None):
    """Only this explicit refresh invokes cswap; snapshots never consume OAuth grants."""
    cache = CLAUDE_CACHE if cache is None else cache
    run = subprocess.run(["cswap", "list", "--json"], capture_output=True, text=True,
                         timeout=120, env=environ)
    if run.returncode or len(run.stdout.encode()) > 1048576:
        raise ValueError("Claude quota query failed")
    data = loads(run.stdout)
    observations = claude_quotas(data, time.time())
    # Persist only allowance fields, never addresses, aliases, credentials or vendor extras.
    public = {"schemaVersion": 1, "activeAccountNumber": data.get("activeAccountNumber"), "accounts": []}
    for row in data["accounts"]:
        account = {key: row[key] for key in
                   ("number", "active", "usageStatus", "usageFetchedAt", "disabled") if key in row}
        usage = row.get("usage")
        if usage is None:
            account["usage"] = None
        else:
            public_usage: dict[str, object] = {
                key: {field: usage[key][field] for field in ("pct", "resetsAt") if field in usage[key]}
                for key in ("fiveHour", "sevenDay") if key in usage}
            if "scoped" in usage:
                public_usage["scoped"] = [
                    {key: window[key] for key in ("name", "pct", "resetsAt") if key in window}
                    for window in usage["scoped"]]
            account["usage"] = public_usage
        public["accounts"].append(account)
    if cache.is_symlink() or cache.parent.is_symlink():
        raise ValueError("unsafe Claude quota cache")
    cache.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    cache.parent.chmod(0o700)
    descriptor, name = tempfile.mkstemp(prefix=".claude-", dir=cache.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(public, stream, allow_nan=False)
        os.replace(name, cache)
    finally:
        Path(name).unlink(missing_ok=True)
    return observations


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
