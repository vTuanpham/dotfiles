"""Native CLI inventory; availability never establishes subscription entitlement."""

import json
import os
import re
import shutil
import subprocess
import tempfile
from datetime import UTC, datetime
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


def identity(value):
    if type(value) is not str or not value or len(value) > 300 or any(
            c.isspace() or ord(c) < 32 for c in value):
        raise ValueError("invalid native model identity")
    return value


def efforts(value):
    if value is None:
        return None
    if type(value) is not list or any(type(v) is not str or not re.fullmatch(r"[\w-]+", v)
                                      for v in value) or len(set(value)) != len(value):
        raise ValueError("invalid native effort catalog")
    return value


def parse_claude(raw):
    responses = []
    for line in raw.splitlines():
        frame = loads(line)
        if type(frame) is not dict:
            raise ValueError("invalid Claude initialization frame")
        if frame.get("type") == "control_response":
            response = frame.get("response", {})
            if type(response) is not dict:
                raise ValueError("invalid Claude control response")
            if response.get("request_id") == "inventory":
                if response.get("subtype") != "success":
                    raise ValueError("Claude initialization rejected")
                responses.append(response.get("response"))
    if len(responses) != 1 or type(responses[0]) is not dict:
        raise ValueError("missing Claude initialization catalog")
    models = responses[0].get("models")
    if type(models) is not list:
        raise ValueError("invalid Claude model catalog")
    result = []
    for model in models:
        if type(model) is not dict:
            raise ValueError("invalid Claude model entry")
        result.append({"id": identity(model.get("value")),
                       "model": identity(model.get("resolvedModel")),
                       "efforts": efforts(model.get("supportedEffortLevels"))})
    if len({r["id"] for r in result}) != len(result):
        raise ValueError("duplicate Claude model identity")
    return result


def parse_opencode(raw):
    value = loads(raw)
    if type(value) is not dict or type(value.get("data")) is not list:
        raise ValueError("invalid OpenCode model catalog")
    models = []
    for model in value["data"]:
        if type(model) is not dict or type(model.get("enabled")) is not bool:
            raise ValueError("invalid OpenCode model entry")
        if not model["enabled"]:
            continue
        identifier = identity(model.get("providerID")) + "/" + identity(model.get("id"))
        variants = model.get("variants")
        if type(variants) is not list or any(type(v) is not dict for v in variants):
            raise ValueError("invalid OpenCode model variants")
        tier = "free-logged" if logged_free(identifier) else "free" if "free" in identifier else "paid"
        models.append({"id": identifier, "model": model["id"],
                       "efforts": efforts([v.get("id") for v in variants]),
                       "effort_control": "variant", "listing_tier": tier,
                       "privacy_gate": "reviewed" if identifier in ZDR_FREE else "unreviewed"})
    return sorted(models, key=lambda m: ("free" not in m["id"].casefold(), m["id"].casefold()))


def catalog(backend, account=None):
    request = None
    if account is not None and backend != "agy":
        raise ValueError("native inventory account override is supported only by agy")
    if backend == "claude":
        # Initialize only: no user prompt, persistent session, hooks or MCP processes.
        command = ["claude", "--print", "--input-format", "stream-json", "--output-format", "stream-json",
                   "--verbose", "--no-session-persistence", "--setting-sources", "", "--settings",
                   json.dumps({"disableAllHooks": True}), "--strict-mcp-config", "--mcp-config",
                   json.dumps({"mcpServers": {}}), "--tools", ""]
        request = json.dumps({"type": "control_request", "request_id": "inventory",
                              "request": {"subtype": "initialize", "hooks": {}}}) + "\n"
    elif backend == "codex":
        command = ["codex", "debug", "models"]
    elif backend == "agy":
        command = ["agy", "models"]
    elif backend == "opencode":
        command = [shutil.which("opencode") or str(Path.home() / ".opencode/bin/opencode"),
                   "api", "GET", "/api/model", "--param", "location[directory]=" + os.getcwd()]
    else:
        raise ValueError("unknown model inventory backend")
    try:
        # OpenCode can exit before pipe writes drain; a regular file preserves its complete JSON.
        with tempfile.TemporaryFile(mode="w+") as output:
            result = subprocess.run(command, env=account_env(account) if account is not None else None,
                                    input=request, stdout=output, stderr=subprocess.PIPE,
                                    text=True, timeout=120)
            output.seek(0)
            raw = output.read(8_000_001)
    except subprocess.SubprocessError as error:
        raise RuntimeError(f"{backend} model inventory failed") from error
    if result.returncode:
        raise RuntimeError(f"{backend} model inventory failed (exit {result.returncode})")
    if len(raw.encode()) > 8_000_000:
        raise ValueError("native model catalog exceeds size limit")
    if backend == "claude":
        models = parse_claude(raw)
        rows = []
    elif backend == "opencode":
        models = parse_opencode(raw)
        rows = []
    elif backend == "codex":
        rows = parse_codex(raw)
    elif backend == "agy":
        rows = []
        for line in raw.splitlines():
            if not line.strip():
                continue
            identifier, tab, label = line.partition("\t")
            if not tab or not identifier or not label or any(c.isspace() for c in identifier):
                raise ValueError("invalid agy model inventory")
            rows.append(line)
    if backend in ("codex", "agy"):
        models = []
        for line in rows:
            columns = line.split("\t")
            identifier = identity(columns[0])
            model = {"id": identifier, "model": identifier,
                     "efforts": efforts(columns[1].split(",") if columns[1] != "-" else [])
                     if backend == "codex" else None}
            models.append(model)
    if len({m["id"] for m in models}) != len(models):
        raise ValueError("duplicate native model identity")
    return {"backend": backend, "account": account, "observed": datetime.now(UTC).isoformat(),
            "models": models, "scope": "native CLI profile inventory; not session entitlement",
            "source": {"codex": "codex debug models", "claude": "Claude stream initialization",
                       "agy": "agy models", "opencode": "opencode api GET /api/model"}[backend],
            "effort_scope": "null means the listing does not publish selectable efforts; "
                            "verify the target native control"}


def show(backend, account=None):
    for model in catalog(backend, account)["models"]:
        columns = [model["id"], ",".join(model["efforts"] or []) or "-"]
        if "listing_tier" in model:
            columns.append(model["listing_tier"])
        elif model["id"] != model["model"]:
            columns.append("resolves=" + model["model"])
        print("\t".join(columns))
