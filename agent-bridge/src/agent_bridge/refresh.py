"""Weekly proposal for the model and subscription guides.

A sandboxed worker sees only a scratch directory and edits a copy. Code then checks the copy and writes a
report. Changes always wait for `refresh --apply`; nothing is applied automatically."""

import difflib
import re
import subprocess
import sys
from datetime import date, datetime
from pathlib import Path
from urllib.parse import urlsplit

from . import opencode, reference
from .core import HOME, command_env

DIR = HOME / "refresh"
STAMP = DIR / "last"
EVERY_DAYS = 7
WORKER = ("codex", "gpt-6.1-sol", "medium")
TIMEOUT_S = 2400
EFFORTS = ("low", "medium", "high", "xhigh", "max")
BIG_MOVE = 8  # index points; a bigger jump is shown to the user, not rejected
SOURCES = (
    "https://artificialanalysis.ai/leaderboards/models (Intelligence Index, cost per task, a row per effort)",
    "https://learn.chatgpt.com/docs/models.md (OpenAI positioning and Capability/Speed ratings)",
    "https://docs.anthropic.com/en/docs/about-claude/models/overview (Claude positioning, latency, prices)",
    "https://openrouter.ai/api/v1/models (list prices per model)",
    "https://learn.chatgpt.com/docs/pricing.md (Codex plans, models and limits)",
    "https://opencode.ai/docs/zen (OpenCode free models and their data policies)",
    "https://opencode.ai/docs/go (OpenCode Go plan)",
    "https://antigravity.google/pricing (Antigravity plans)",
    "https://antigravity.google/docs/plans (allowance windows)",
    "https://antigravity.google/docs/models (tier-specific model access)",
    "https://support.claude.com/en/articles/11145838 (Claude plans)",
    "https://code.claude.com/docs/en/data-usage (Claude privacy)",
    "https://learn.chatgpt.com/docs/security (Codex security)",
)
BRIEF = """You are refreshing two vendor reference documents. Work only in this directory.

Read sources.md first: it records how each source is reached, which are unusable and what each may support.
Files: current-models.md and current-subscriptions.md (reviewed documents), proposed-models.md and
proposed-subscriptions.md (copies: edit these), drift.txt and live.txt (model inventory, not entitlement).

Scope:
- models.md contains generic strengths, benchmark facts and model/effort advice, never held subscriptions.
- subscriptions.md catalogs EVERY vendor tier of ALL four supported harnesses, regardless of account access.
  Keep Free, Go, Plus, all Pro prices, Business, Enterprise/Edu, API; Antigravity Individual,
  AI Plus/Pro/Ultra and Business; OpenCode free, Zen, Go, Go Plus; Claude Free, Pro, Max 5x/20x,
  Team/Enterprise and API.
- Use vendor names: Pro ($100), Pro ($200), Pro ($500). The pricing page publishes no multipliers.
- Never describe any person's subscription, live balance, account layout or local tier nickname. Write
  vendor facts or conditionals. Account discovery belongs to live commands, not these documents.
- Match a tier's facts to its own vendor row by name/price; never infer entitlement from a model list.

Do:
1. Fetch these pages and required linked official guides, including every source cited in the documents:
{sources}
2. Edit both proposed files in place: refresh the effort table and vendor tier facts from what
   those pages say now, add a row for a new model that matters, and change the "Checked" date to {today}.
   If the pages contradict nothing in a document, change nothing: leave its proposal exactly as it is,
   Checked date included. Most weeks nothing has changed, and that is the right answer.
3. Write notes.md: each change with its source URL, and everything you could not fetch or confirm.

Rules:
- Keep the structure, headings, bullet labels and wording. Change a sentence only if a source contradicts it.
- Never guess. A number or claim no source confirmed stays as it was, or is marked "Unverified".
- Preserve generic model/effort advice; allowance-dependent advice must remain conditional.
- The OpenCode free zero-retention list is a privacy gate kept in code: do not add or remove a model from it.
  If a source says the set changed, say so in notes.md only.
- Table cells are `index / $cost per task`, five efforts per row.
- Edit no other file and run nothing that changes the system.
"""
ROW = re.compile(r"^\| ([^|]+?) \|((?: \d+ / \$[\d.]+ \|){5})$")
CELL = re.compile(r"(\d+) / \$([\d.]+)")
BULLET = re.compile(r"^- \*\*([^*]+)\*\*", re.M)
FREE_IDS = re.compile(r"`(opencode/[\w.\-]+-free)`")
CHECKED = re.compile(r"Checked \d{4}-\d{2}-\d{2}")
HOLDER_WORDING = re.compile(
    r"\b(?:not\s+subscribed|your\s+plan\s+is|currently\s+on|pro\s+lite|our\s+pro|"
    r"the\s+user(?:'s\s+plans|\s+is\s+on)|the\s+owner(?:'s\s+(?:plan|subscription)|\s+subscribes)|"
    r"we\s+have\s+(?:a\s+)?(?:pro|plus|max)|35%\s+and\s+12%|"
    r"used\s+extremely\s+heavily|burn\s+the\s+plus\s+accounts)\b",
    re.I,
)


def rows(text):
    return {
        m[1]: [(int(i), float(c)) for i, c in CELL.findall(m[2])]
        for line in text.splitlines()
        if (m := ROW.match(line))
    }


def unchanged(old, new):
    """The same document, whatever date it says it was checked on."""
    return CHECKED.sub("Checked", old) == CHECKED.sub("Checked", new)


def validate(old, new, stamp, name="models.md"):
    """(errors that reject the proposal, notes shown to the user)."""
    errors, notes = [], []
    if HOLDER_WORDING.search(new):
        errors.append("holder-specific wording is forbidden in public guides")
    if unchanged(old, new):
        return errors, notes
    if not 0.7 * len(old) <= len(new) <= 1.5 * len(old):
        errors.append("the size changed too much: a rewrite, not a refresh")
    for heading in re.findall(r"^###+ .*", old, re.M):
        if heading not in new:
            errors.append(f"the heading {heading!r} is missing")
    if f"Checked {stamp}" not in new:
        errors.append(f"the Checked date was not set to {stamp}")
    if BULLET.findall(old) != BULLET.findall(new):
        errors.append("the bullet labels changed")
    before, after = rows(old), rows(new)
    if name == "subscriptions.md":
        if table_labels(old) != table_labels(new):
            errors.append("the subscription tier rows changed")
        free = next((line for line in new.splitlines() if line.startswith("- **OpenCode free**")), "")
        if set(FREE_IDS.findall(free)) != set(opencode.ZDR_FREE):
            errors.append("the free-tier list differs from the zero-retention list in code")
        return errors, notes
    if not after or not set(before) <= set(after):
        errors.append("a model row was dropped or the table no longer parses")
    for name, cells in after.items():
        if any(not 0 <= i <= 100 or c <= 0 for i, c in cells):
            errors.append(f"{name}: a number is out of range")
        for effort, (was, _), (now, _) in zip(EFFORTS, before.get(name, cells), cells):
            if abs(now - was) > BIG_MOVE:
                notes.append(f"{name} {effort}: index {was} -> {now}")
    if advice(old) != advice(new):
        errors.append("the use-pattern advice (model, plan, role, effort) changed: that is the user's call")
    return errors, notes


def content_errors(text, name, stamp):
    errors = []
    sections = {
        "models.md": ("### Effort and model strength", "### How to use each model", "### Inventory coverage"),
        "subscriptions.md": ("### Find live account state", "### Codex / ChatGPT", "### Antigravity / agy",
                             "### OpenCode", "### Claude / Claude Code"),
    }
    for section in sections[name]:
        if section not in text:
            errors.append(f"{name}: missing section {section}")
    if f"Checked {stamp}" not in text:
        errors.append(f"{name}: Checked date must be {stamp}")
    if HOLDER_WORDING.search(text):
        errors.append(f"{name}: holder-specific wording is forbidden")
    links = re.findall(r"\]\(([^)]+)\)", text)
    if text.count("](") != len(links):
        errors.append(f"{name}: malformed Markdown link")
    for link in links:
        try:
            parsed = urlsplit(link)
            _ = parsed.port
        except ValueError:
            errors.append(f"{name}: malformed link {link!r}")
            continue
        if (any(c.isspace() for c in link) or
                (parsed.scheme and (parsed.scheme not in ("https", "http") or not parsed.netloc)) or
                (not parsed.scheme and not (reference.GUIDES / parsed.path).is_file())):
            errors.append(f"{name}: malformed or missing link {link!r}")
    return errors


def table_labels(text):
    return [line.split("|")[1].strip() for line in text.splitlines() if line.startswith("| ")]


def advice(text):
    """Generic model, role and effort advice stays under root review."""
    section = text.partition("### How to use each model")[2]
    return [
        line for line in section.splitlines() if line[:2] == "| "
    ]


def report(work, old, new, errors, notes):
    diff = "".join(
        line for name in reference.DOCUMENTS
        for line in difflib.unified_diff(old[name].splitlines(1), new[name].splitlines(1),
                                         f"current/{name}", f"proposed/{name}")
    )
    said = (work / "notes.md").read_text(encoding="utf-8") if (work / "notes.md").is_file() else "(none)"
    parts = [
        "Rejected:\n" + "\n".join(f"- {e}" for e in errors) if errors else "Checks passed.",
        "Big moves:\n" + "\n".join(f"- {n}" for n in notes) if notes else "",
        f"Worker notes:\n{said}",
        f"Diff:\n{diff or '(no change)'}",
    ]
    text = "\n\n".join(p for p in parts if p)
    (work / "report.md").write_text(text, encoding="utf-8")
    return text


def documents(directory, prefix=""):
    return {name: (directory / f"{prefix}{name}").read_text(encoding="utf-8")
            for name in reference.DOCUMENTS}


def validate_documents(old, new, stamp):
    errors, notes = [], []
    for name in reference.DOCUMENTS:
        rejected, moves = validate(old[name], new[name], stamp, name)
        errors.extend(f"{name}: {error}" for error in rejected)
        notes.extend(f"{name}: {note}" for note in moves)
        if not unchanged(old[name], new[name]):
            errors.extend(content_errors(new[name], name, stamp))
        if new[name].lower().count("unverified") < old[name].lower().count("unverified"):
            errors.append(f"{name}: Unverified markers were removed")
    return errors, notes


def due():
    try:
        return (date.today() - date.fromisoformat(STAMP.read_text().strip())).days >= EVERY_DAYS
    except (OSError, ValueError):
        return True


def run(force=False):
    if reference.PENDING.is_file() and not force:
        print("a refreshed reference is waiting: `agent-bridge refresh --apply` or `--discard`")
        return 0
    if not force and not due():
        return 0
    reference.check()  # also refreshes the cache that `start` reads
    today = date.today().isoformat()
    work = DIR / today
    work.mkdir(parents=True, exist_ok=True)
    current = documents(reference.GUIDES)
    for name, text in current.items():
        (work / f"current-{name}").write_text(text, encoding="utf-8")
        (work / f"proposed-{name}").write_text(text, encoding="utf-8")
    (work / "sources.md").write_text(
        (Path(__file__).with_name("guide") / "sources.md").read_text(encoding="utf-8"), encoding="utf-8"
    )
    live = "".join(f"{n} {i}\n" for n, ids in sorted(reference.live().items()) for i in sorted(ids))
    for name, text in (
        ("drift.txt", "\n".join(reference.drift()) + "\n"),
        ("live.txt", live),
        ("brief.md", BRIEF.format(sources="\n".join(f"   - {s}" for s in SOURCES), today=today)),
    ):
        (work / name).write_text(text, encoding="utf-8")
    (work / "notes.md").unlink(missing_ok=True)
    backend, model, effort = WORKER
    job = f"refresh/models-{datetime.now():%Y%m%d-%H%M%S-%f}"
    cmd = [sys.executable, "-m", "agent_bridge.cli", "start", job, "--backend", backend, "--model", model]
    cmd += ["--effort", effort, "--title", "Refresh model reference", "--cwd", str(work)]
    cmd += ["--sandbox", "workspace-write", "--prompt-file", str(work / "brief.md")]
    try:
        done = subprocess.run(cmd, env=command_env(), capture_output=True, text=True, timeout=TIMEOUT_S)
    except subprocess.TimeoutExpired:
        print(f"the refresh worker timed out; nothing changed (job {job})")
        return 1
    STAMP.write_text(today)
    if done.returncode:
        print(f"the refresh worker failed; nothing changed (job {job}):\n{done.stderr.strip()[-600:]}")
        return 1
    new = documents(work, "proposed-")
    errors, notes = validate_documents(current, new, today)
    report(work, current, new, errors, notes)
    subprocess.run([sys.executable, "-m", "agent_bridge.cli", "retire", job],
                   env=command_env(), capture_output=True)
    if errors:
        print(f"proposal rejected, nothing changed: {'; '.join(errors)}\nreport: {work / 'report.md'}")
        return 1
    if documents(reference.GUIDES) != current:
        print(f"the guide changed while the worker ran; nothing applied. `refresh --force` to redo\n{work}")
        return 1
    # Even an unchanged proposal requires explicit review before the lock can advance.
    reference.PENDING.write_text(str(work))
    print(f"a proposal is waiting for the next root to re-check and apply: {work / 'report.md'}")
    return 0


def install(new):
    for name, text in new.items():
        (reference.GUIDES / name).write_text(text, encoding="utf-8")
    reference.accept()
    reference.PENDING.unlink(missing_ok=True)


def committed():
    """The public baseline, not a copy captured after the root's edits."""
    result = {}
    for name in reference.DOCUMENTS:
        path = reference.GUIDES / name
        relative = subprocess.run(["git", "ls-files", "--full-name", "--", str(path)],
                                  cwd=reference.GUIDES, check=True, capture_output=True,
                                  text=True, env=command_env()).stdout.strip()
        if not relative:
            sys.exit(f"cannot review {name}: guide must have a committed baseline")
        result[name] = subprocess.run(["git", "show", f"HEAD:{relative}"], cwd=reference.GUIDES,
                                      check=True, capture_output=True, text=True,
                                      env=command_env()).stdout
    return result


def record(yes=False):
    """Validate root edits and record their review; never modify the documents."""
    current, baseline = documents(reference.GUIDES), committed()
    found = reference.live()
    errors = []
    today = date.today().isoformat()
    for name, text in current.items():
        errors.extend(content_errors(text, name, today))
        if text.lower().count("unverified") < baseline[name].lower().count("unverified"):
            errors.append(f"{name}: Unverified markers were removed; retain unresolved claims")
    missing_tiers = set(table_labels(baseline["subscriptions.md"])) - set(
        table_labels(current["subscriptions.md"]))
    if missing_tiers:
        errors.append("subscriptions.md: missing tier rows: " + ", ".join(sorted(missing_tiers)))
    if set(BULLET.findall(baseline["subscriptions.md"])) - set(
            BULLET.findall(current["subscriptions.md"])):
        errors.append("subscriptions.md: a subscription catalog bullet was removed")
    covered = set(re.findall(r"`([^`\n]+)`", "\n".join(current.values())))
    for backend, ids in found.items():
        for identifier in sorted(ids - covered):
            errors.append(f"{backend}: live model {identifier} missing; "
                          "document it or list as intentionally omitted")
    for name in reference.DOCUMENTS:
        print("".join(difflib.unified_diff(baseline[name].splitlines(1), current[name].splitlines(1),
                                          f"HEAD/{name}", f"working/{name}")), end="")
    if errors:
        sys.exit("record refused:\n" + "\n".join(f"- {error}" for error in errors))
    if not yes:
        if not sys.stdin.isatty():
            sys.exit("re-check the cited sources, then re-run refresh --record --yes")
        if input("Record both guides as source-checked? [y/N] ").strip().lower() != "y":
            return 1
    if documents(reference.GUIDES) != current:
        sys.exit("guides changed during review; record again")
    reference.accept(found=found)
    reference.PENDING.unlink(missing_ok=True)
    print("recorded both guides and live model lists in models.lock; guide text unchanged (uncommitted)")
    return 0


def apply(yes):
    if not reference.PENDING.is_file():
        sys.exit("nothing is waiting")
    work = Path(reference.PENDING.read_text())
    old, new = documents(reference.GUIDES), documents(work, "proposed-")
    if old != documents(work, "current-"):
        sys.exit(
            "the guide changed since this proposal was made; applying it would undo that: `refresh --force`"
        )
    errors, notes = validate_documents(old, new, work.name)
    text = report(work, old, new, errors, notes)
    if errors:
        sys.exit(text)
    print(text)
    if not yes:
        if not sys.stdin.isatty():
            sys.exit("re-check the changed claims against their cited sources, then re-run with --yes")
        if input("Apply this to both guides? [y/N] ").strip().lower() != "y":
            print("left as it was; `refresh --discard` drops it")
            return 1
    if documents(reference.GUIDES) != old:
        sys.exit("the guides changed during review; refresh again")
    install(new)
    print("applied to guide/models.md, guide/subscriptions.md and the lock (uncommitted, see `git diff`)")
    return 0


def discard():
    reference.PENDING.unlink(missing_ok=True)
    print("dropped the waiting proposal")
    return 0
