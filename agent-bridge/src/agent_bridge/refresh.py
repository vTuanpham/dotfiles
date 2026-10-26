"""Weekly refresh of guide/models.md without letting a worker rewrite the guide.

A sandboxed worker sees only a scratch directory and edits a copy. Code then checks the copy and writes a
report. A clean proposal lands by itself (uncommitted); one with big moves waits for `refresh --apply`."""

import difflib
import re
import subprocess
import sys
from datetime import date, datetime
from pathlib import Path

from . import opencode, reference
from .core import HOME, command_env

DIR = HOME / "refresh"
STAMP = DIR / "last"
EVERY_DAYS = 7
WORKER = ("codex", "gpt-6.1-sol", "medium")  # reads pricing pages reliably; a Free Codex plan only has Luna
TIMEOUT_S = 2400
EFFORTS = ("low", "medium", "high", "xhigh", "max")
BIG_MOVE = 8  # index points; a bigger jump is shown to the user, not rejected
SOURCES = (
    "https://artificialanalysis.ai/leaderboards/models (Intelligence Index, cost per task, a row per effort)",
    "https://learn.chatgpt.com/docs/pricing.md (Codex plans, models and limits)",
    "https://opencode.ai/docs/zen (OpenCode free models and their data policies)",
    "https://opencode.ai/docs/go (OpenCode Go plan)",
    "https://antigravity.google/pricing (Antigravity plans)",
    "https://support.claude.com/en/articles/11145838 (Claude plans)",
)
BRIEF = """You are refreshing a dated reference document. Work only in this directory.

Files: current.md (the reference as it stands), proposed.md (a copy: edit this one), drift.txt (model ids that
appeared or vanished since it was written), live.txt (the model ids the tools list right now), plans.txt (the
plans signed in on this machine, with emails masked).

Working out the plan tiers:
- plans.txt is the ground truth for which plans exist here: codex-auth's PLAN column, and agy's quota buckets
  and model tiers. Never infer a plan from a model list: a listed model is not an included model.
- Match each plan to its row on the vendor page by name or price, not by position. Codex "Pro Lite" is the
  $100 Pro tier, and the pricing page lists Pro at $100, $200 and $500.
- Facts under a plan come only from that tier's own row. If the tier has no row, keep the old text and list it
  as Unverified in notes.md. If a vendor shows a new or renamed tier, report it in notes.md; do not add or
  rename bullets.
- Plans that no account here uses (for example Plus, Claude, OpenCode Go) stay as documentation of the vendor
  page: refresh their facts, never drop them.

Do:
1. Fetch these pages and nothing else:
{sources}
2. Edit proposed.md in place: refresh the numbers in the effort table and the facts under each plan from what
   those pages say now, add a row for a new model that matters, and change the "Checked" date to {today}.
   If the pages contradict nothing in the document, change nothing: leave proposed.md exactly as it is,
   Checked date included. Most weeks nothing has changed, and that is the right answer.
3. Write notes.md: each change with its source URL, and everything you could not fetch or confirm.

Rules:
- Keep the structure, headings, bullet labels and wording. Change a sentence only if a source contradicts it.
- Never guess. A number or claim no source confirmed stays as it was, or is marked "Unverified".
- How freely to spend each plan, and which effort to prefer, is the user's call: change the facts under that
  advice, never the advice.
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
EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")


def rows(text):
    return {
        m[1]: [(int(i), float(c)) for i, c in CELL.findall(m[2])]
        for line in text.splitlines()
        if (m := ROW.match(line))
    }


def unchanged(old, new):
    """The same document, whatever date it says it was checked on."""
    return CHECKED.sub("Checked", old) == CHECKED.sub("Checked", new)


def validate(old, new, stamp):
    """(errors that reject the proposal, notes shown to the user)."""
    errors, notes = [], []
    if unchanged(old, new):
        return errors, notes
    if not 0.7 * len(old) <= len(new) <= 1.5 * len(old):
        errors.append("the size changed too much: a rewrite, not a refresh")
    for heading in ("### Plans", "### Effort and model strength"):
        if heading not in new:
            errors.append(f"the heading {heading!r} is missing")
    if f"Checked {stamp}" not in new:
        errors.append(f"the Checked date was not set to {stamp}")
    if BULLET.findall(old) != BULLET.findall(new):
        errors.append("the bullet labels changed")
    before, after = rows(old), rows(new)
    if not after or not set(before) <= set(after):
        errors.append("a model row was dropped or the table no longer parses")
    for name, cells in after.items():
        if any(not 0 <= i <= 100 or c <= 0 for i, c in cells):
            errors.append(f"{name}: a number is out of range")
        for effort, (was, _), (now, _) in zip(EFFORTS, before.get(name, cells), cells):
            if abs(now - was) > BIG_MOVE:
                notes.append(f"{name} {effort}: index {was} -> {now}")
    free = next((line for line in new.splitlines() if line.startswith("- **OpenCode free**")), "")
    if set(FREE_IDS.findall(free)) != set(opencode.ZDR_FREE):
        errors.append("the free-tier list differs from the zero-retention list in code")
    if advice(old) != advice(new):
        errors.append("the use-pattern advice (model, plan, role, effort) changed: that is the user's call")
    return errors, notes


def advice(text):
    """The Model, Plan, Role and Effort cells of the use-pattern table; the Pattern column holds facts."""
    section = text.partition("### How to use each model")[2]
    return [
        tuple(c.strip() for c in line.split("|")[1:5]) for line in section.splitlines() if line[:2] == "| "
    ]


def report(work, old, new, errors, notes):
    diff = "".join(difflib.unified_diff(old.splitlines(1), new.splitlines(1), "current", "proposed"))
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


def plans():
    """The plans signed in on this machine, emails masked: the ground truth the worker resolves tiers from."""
    quota = [sys.executable, "-m", "agent_bridge.cli", "quota", "--backend", "agy"]
    models = [sys.executable, "-m", "agent_bridge.cli", "models", "--backend", "agy"]
    parts = []
    for title, cmd in (
        ("codex-auth list (the PLAN column)", ["codex-auth", "list"]),
        ("agy quota (buckets per account)", quota),
        ("agy models (id, effort, tier, bucket)", models),
    ):
        try:
            out = subprocess.run(cmd, env=command_env(), capture_output=True, text=True, timeout=60).stdout
        except (OSError, subprocess.SubprocessError):
            out = "(unavailable)"
        parts.append(f"== {title}\n{EMAIL.sub('<email>', out).strip()}\n")
    return "\n".join(parts)


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
    current = (reference.GUIDES / "models.md").read_text(encoding="utf-8")
    live = "".join(f"{n} {i}\n" for n, ids in sorted(reference.live().items()) for i in sorted(ids))
    for name, text in (
        ("current.md", current),
        ("proposed.md", current),
        ("drift.txt", "\n".join(reference.drift()) + "\n"),
        ("live.txt", live),
        ("plans.txt", plans()),
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
    new = (work / "proposed.md").read_text(encoding="utf-8")
    errors, notes = validate(current, new, today)
    report(work, current, new, errors, notes)
    subprocess.run([sys.executable, "-m", "agent_bridge.cli", "retire", job],
                   env=command_env(), capture_output=True)
    if errors:
        print(f"proposal rejected, nothing changed: {'; '.join(errors)}\nreport: {work / 'report.md'}")
        return 1
    if (reference.GUIDES / "models.md").read_text(encoding="utf-8") != current:
        print(f"the guide changed while the worker ran; nothing applied. `refresh --force` to redo\n{work}")
        return 1
    if unchanged(current, new) and not reference.drift():  # the common week: nothing to judge
        reference.accept()  # today's check counts, so the staleness clock restarts
        print(f"nothing changed: the sources still agree with guide/models.md. Report: {work / 'report.md'}")
        return 0
    # A change, or model ids the worker skipped: never applied here; the next root re-checks and applies it.
    reference.PENDING.write_text(str(work))
    print(f"a proposal is waiting for the next root to re-check and apply: {work / 'report.md'}")
    return 0


def install(new):
    (reference.GUIDES / "models.md").write_text(new, encoding="utf-8")
    reference.accept()
    reference.PENDING.unlink(missing_ok=True)


def apply(yes):
    if not reference.PENDING.is_file():
        sys.exit("nothing is waiting")
    work = Path(reference.PENDING.read_text())
    guide = reference.GUIDES / "models.md"
    old, new = guide.read_text(encoding="utf-8"), (work / "proposed.md").read_text(encoding="utf-8")
    if old != (work / "current.md").read_text(encoding="utf-8"):
        sys.exit(
            "the guide changed since this proposal was made; applying it would undo that: `refresh --force`"
        )
    errors, notes = validate(old, new, work.name)
    text = report(work, old, new, errors, notes)
    if errors:
        sys.exit(text)
    print(text)
    if not yes:
        if not sys.stdin.isatty():
            sys.exit("re-check the changed claims against their cited sources, then re-run with --yes")
        if input("Apply this to guide/models.md? [y/N] ").strip().lower() != "y":
            print("left as it was; `refresh --discard` drops it")
            return 1
    install(new)
    print("applied to guide/models.md and the lock (uncommitted, see `git diff`)")
    return 0


def discard():
    reference.PENDING.unlink(missing_ok=True)
    print("dropped the waiting proposal")
    return 0
