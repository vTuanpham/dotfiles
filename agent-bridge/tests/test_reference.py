import json
import re
import subprocess
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from agent_bridge import cli, reference, refresh

REAL = (reference.GUIDES / "models.md").read_text(encoding="utf-8")
SUBSCRIPTIONS = (reference.GUIDES / "subscriptions.md").read_text(encoding="utf-8")
TODAY = date.today().isoformat()
_LUNA = re.search(
    r"\| Luna \| (\d+) / \$[\d.]+", REAL
)  # the first Luna cell, whatever the last refresh wrote
LUNA_CELL, LUNA_LOW = _LUNA.group(0), int(_LUNA.group(1))


@pytest.fixture
def home(tmp_path, monkeypatch):
    guides = tmp_path / "guide"
    guides.mkdir()
    (guides / "models.md").write_text(REAL, encoding="utf-8")
    (guides / "subscriptions.md").write_text(SUBSCRIPTIONS, encoding="utf-8")
    monkeypatch.setattr(reference, "GUIDES", guides)
    monkeypatch.setattr(reference, "LOCK", guides / "models.lock")
    monkeypatch.setattr(reference, "CACHE", tmp_path / "stale.json")
    monkeypatch.setattr(reference, "PENDING", tmp_path / "refresh/pending")
    monkeypatch.setattr(refresh, "DIR", tmp_path / "refresh")
    monkeypatch.setattr(refresh, "STAMP", tmp_path / "refresh/last")
    monkeypatch.setattr(reference, "HOME", tmp_path)
    monkeypatch.setattr(refresh, "committed", lambda: {"models.md": REAL, "subscriptions.md": SUBSCRIPTIONS})
    (tmp_path / "refresh").mkdir()
    lists = {"codex": ["gpt-6-luna", "gpt-6.1-sol"], "opencode": ["opencode/glm-5.3-flash-free", "other/x"]}
    monkeypatch.setattr(
        reference,
        "LISTERS",
        {name: (lambda ids=ids: print("\n".join(f"{i}\t-" for i in ids))) for name, ids in lists.items()},
    )
    return tmp_path


def refreshed(text=REAL, **changes):
    """The reference as a worker would hand it back: today's date, optionally with edits."""
    text = re.sub(r"Checked \d{4}-\d{2}-\d{2}", f"Checked {TODAY}", text)
    for old, new in changes.items():
        assert old in text
        text = text.replace(old, new)
    return text


def test_a_clean_refresh_passes_and_a_big_move_is_only_a_note():
    errors, notes = refresh.validate(REAL, refreshed(), TODAY)
    assert (errors, notes) == ([], [])
    errors, notes = refresh.validate(REAL, refreshed(**{LUNA_CELL: "| Luna | 40 / $0.005"}), TODAY)
    assert errors == [] and notes == [f"Luna low: index {LUNA_LOW} -> 40"]


@pytest.mark.parametrize(
    ("edit", "expected"),
    [
        ({"| Haiku 5.5 |": "| Haiku 5.4 |"}, "model row was dropped"),
        ({LUNA_CELL: "| Luna | 220 / $0.005"}, "out of range"),
        ({"- **Small models need effort**": "- **Small models**"}, "bullet labels"),
        ({"| Astra | hardest audits": "| Astra | routine work"}, "advice"),
    ],
)
def test_a_proposal_that_restructures_or_touches_the_privacy_list_is_rejected(edit, expected):
    errors, _ = refresh.validate(REAL, refreshed(**edit), TODAY)
    assert any(expected in e for e in errors)


def test_a_stale_date_and_a_truncated_rewrite_are_rejected():
    edited = refreshed(
        **{LUNA_CELL: f"| Luna | {LUNA_LOW} / $0.0049"}
    )  # a real change that keeps the old date
    assert any("Checked date" in e for e in refresh.validate(REAL, edited, "2099-01-01")[0])
    assert refresh.validate(REAL, REAL, "2099-01-01") == ([], [])  # no change at all needs no date
    assert any("size" in e for e in refresh.validate(REAL, refreshed()[:200], TODAY)[0])


def test_stale_reports_new_and_gone_models_and_warns_from_the_cache(home, capsys):
    write_lock("codex gpt-6-luna\ncodex gpt-5.6-terra\n")
    assert reference.warning() is None
    found = reference.check()
    assert found[0].startswith("codex: new gpt-6.1-sol; gone gpt-5.6-terra")
    assert any(line.startswith("opencode: new opencode/glm-5.3-flash-free") for line in found)
    assert "other/x" not in "".join(found)  # only the opencode/ free tier is tracked
    assert "live model lists changed" in reference.warning()
    reference.accept()
    assert reference.check() == [] and "live model lists" not in (reference.warning() or "")


def test_a_listing_that_shares_nothing_with_the_lock_is_a_failed_listing(home, monkeypatch):
    write_lock("codex gpt-6-luna\nopencode opencode/glm-5.3-flash-free\n")
    monkeypatch.setattr(
        reference,
        "LISTERS",
        {
            "codex": lambda: print("gpt-6-luna\t-"),
            "opencode": lambda: print("opencode/some-other-free\t-"),  # the flaky listing
        },
    )
    assert reference.drift() == []  # not "the whole free tier retired"
    reference.accept()
    assert "opencode opencode/glm-5.3-flash-free" in reference.LOCK.read_text()  # and the lock keeps it


def test_an_old_lock_and_a_waiting_proposal_each_warn(home):
    reference.LOCK.write_text(f"refreshed {date.today() - timedelta(days=45)}\n", encoding="utf-8")
    assert "past their check date" in reference.warning()
    reference.accept()
    reference.PENDING.write_text(str(home))
    assert "waiting for a root to re-check" in reference.warning()


def worker(home, edit, subscriptions=lambda text: text):
    """A stand-in for the sandboxed worker: edits only the proposal in its working directory."""

    def run(cmd, **_):
        if cmd[3:4] == ["start"]:
            work = home / "refresh" / TODAY
            for name, change in (("models.md", edit), ("subscriptions.md", subscriptions)):
                (work / f"proposed-{name}").write_text(
                    change((work / f"current-{name}").read_text()), encoding="utf-8")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    return run


def small_fix(text):
    return refreshed(text, **{LUNA_CELL: f"| Luna | {LUNA_LOW} / $0.0049"})


def test_refresh_does_not_reuse_a_retained_job_name(home, monkeypatch):
    reference.accept()
    started = []
    simulate = worker(home, lambda text: text)

    def run(cmd, **kwargs):
        if cmd[3:4] == ["start"]:
            started.append(cmd[4])
        return simulate(cmd, **kwargs)

    monkeypatch.setattr(refresh.subprocess, "run", run)
    assert refresh.run(force=True) == 0
    assert refresh.run(force=True) == 0
    assert len(started) == 2 and started[0] != started[1]


def big_move(text):
    return refreshed(text, **{LUNA_CELL: "| Luna | 40 / $0.005"})


def test_a_change_is_never_applied_by_the_job_and_the_next_root_applies_it_after_re_checking(
    home, monkeypatch, capsys
):
    reference.accept()
    monkeypatch.setattr(refresh.subprocess, "run", worker(home, big_move))
    assert refresh.run(force=True) == 0
    guide = reference.GUIDES / "models.md"
    assert reference.PENDING.is_file() and guide.read_text() == REAL  # the job only proposes
    assert "waiting for the next root" in capsys.readouterr().out
    assert "waiting for a root to re-check" in reference.warning()  # what the next `start` says
    waiting = "\n".join(reference.check())
    assert "report.md" in waiting  # `stale` names the report to read
    assert "Big moves" in Path(waiting.split("report: ")[1]).read_text()
    with pytest.raises(SystemExit, match="re-check the changed claims"):
        refresh.apply(yes=False)  # a root says --yes once it has re-checked; a bare call does not apply
    assert refresh.apply(yes=True) == 0
    assert "| Luna | 40 /" in guide.read_text() and not reference.PENDING.exists()
    assert refresh.run() == 0 and not refresh.due()  # ran today: the next run waits a week


LIVE_LOCK = (
    "codex gpt-6-luna\ncodex gpt-6.1-sol\nopencode opencode/glm-5.3-flash-free\n"  # what the fixture lists
)


def write_lock(models, refreshed=TODAY):
    hashes = "".join(f"guide {name} {digest}\n" for name, digest in reference.guide_hashes().items())
    reference.LOCK.write_text(f"refreshed {refreshed}\n{hashes}{models}", encoding="utf-8")


def test_a_worker_that_changes_nothing_waits_for_apply_before_restarting_the_clock(
    home, monkeypatch, capsys
):
    old = date.today() - timedelta(days=20)
    write_lock(LIVE_LOCK, old)
    monkeypatch.setattr(refresh.subprocess, "run", worker(home, lambda text: text))  # not even the date
    assert refresh.run(force=True) == 0
    assert "proposal is waiting" in capsys.readouterr().out
    assert (reference.GUIDES / "models.md").read_text() == REAL and reference.PENDING.exists()
    assert reference.read_lock()[0] == old
    assert refresh.apply(yes=True) == 0
    assert reference.read_lock()[0] == date.today()


def test_no_change_with_new_models_the_worker_skipped_is_left_for_the_next_root(home, monkeypatch, capsys):
    old = date.today() - timedelta(days=20)
    reference.LOCK.write_text(f"refreshed {old}\ncodex gpt-6-luna\n", encoding="utf-8")  # gpt-6.1-sol is new
    monkeypatch.setattr(refresh.subprocess, "run", worker(home, lambda text: text))
    assert refresh.run(force=True) == 0
    assert reference.PENDING.is_file() and reference.read_lock()[0] == old  # not acknowledged for it


def test_a_guide_edited_while_the_worker_ran_is_not_overwritten(home, monkeypatch, capsys):
    reference.accept()
    guide = reference.GUIDES / "models.md"

    def edits_mid_run(cmd, **kwargs):
        done = worker(home, small_fix)(cmd, **kwargs)
        guide.write_text(REAL + "\nan edit made meanwhile\n", encoding="utf-8")
        return done

    monkeypatch.setattr(refresh.subprocess, "run", edits_mid_run)
    assert refresh.run(force=True) == 1
    assert (
        guide.read_text().endswith("an edit made meanwhile\n") and "changed while" in capsys.readouterr().out
    )


def test_refresh_brief_has_no_live_subscription_input():
    assert "plans.txt" not in refresh.BRIEF
    assert "EVERY vendor tier" in refresh.BRIEF
    assert not refresh.HOLDER_WORDING.search(refresh.BRIEF)


def test_apply_refuses_a_proposal_made_against_an_older_guide(home, monkeypatch):
    reference.accept()
    monkeypatch.setattr(refresh.subprocess, "run", worker(home, big_move))
    assert refresh.run(force=True) == 0
    (reference.GUIDES / "models.md").write_text(REAL + "\nan edit made since\n", encoding="utf-8")
    with pytest.raises(SystemExit, match="guide changed"):
        refresh.apply(yes=True)
    assert refresh.run(force=True) == 0  # --force replaces the stale proposal with a fresh one


def test_a_rejected_proposal_leaves_the_guide_and_queues_nothing(home, monkeypatch, capsys):
    reference.accept()
    monkeypatch.setattr(refresh.subprocess, "run", worker(home, lambda text: text[:100]))
    assert refresh.run(force=True) == 1
    assert "rejected" in capsys.readouterr().out
    assert not reference.PENDING.exists() and (reference.GUIDES / "models.md").read_text() == REAL


def test_a_failed_or_timed_out_worker_changes_nothing(home, monkeypatch, capsys):
    reference.accept()

    def timeout(cmd, **_):
        raise subprocess.TimeoutExpired(cmd, 1)

    monkeypatch.setattr(refresh.subprocess, "run", timeout)
    assert refresh.run(force=True) == 1
    assert "timed out" in capsys.readouterr().out and not reference.PENDING.exists()


def test_both_guides_share_one_report_apply_and_lock(home, monkeypatch):
    reference.accept()
    changed = refreshed(SUBSCRIPTIONS).replace("numeric allowance Unverified", "exact allowance Unverified")
    monkeypatch.setattr(refresh.subprocess, "run", worker(home, small_fix, lambda text: changed))
    assert refresh.run(force=True) == 0
    assert (reference.GUIDES / "subscriptions.md").read_text() == SUBSCRIPTIONS
    report = (Path(reference.PENDING.read_text()) / "report.md").read_text()
    assert "proposed/models.md" in report and "proposed/subscriptions.md" in report
    assert refresh.apply(yes=True) == 0
    assert (reference.GUIDES / "subscriptions.md").read_text() == changed
    assert reference.guide_drift() == []
    assert reference.read_lock()[1] == {
        "codex": {"gpt-6-luna", "gpt-6.1-sol"}, "opencode": {"opencode/glm-5.3-flash-free"}}


def test_apply_refuses_intervening_subscription_edit(home, monkeypatch):
    reference.accept()
    monkeypatch.setattr(refresh.subprocess, "run", worker(home, small_fix))
    refresh.run(force=True)
    (reference.GUIDES / "subscriptions.md").write_text(SUBSCRIPTIONS + "\nintervening edit\n")
    with pytest.raises(SystemExit, match="guide changed"):
        refresh.apply(yes=True)
    assert (reference.GUIDES / "models.md").read_text() == REAL


def test_subscription_tier_and_privacy_gate_validation():
    for old, new, error in (
        ("| Pro ($100/month)", "| Other tier", "tier rows"),
        ("`opencode/minimax-m3.1-flash-free`", "`opencode/new-free`", "zero-retention list"),
    ):
        errors, _ = refresh.validate(SUBSCRIPTIONS, refreshed(SUBSCRIPTIONS).replace(old, new),
                                     TODAY, "subscriptions.md")
        assert any(error in item for item in errors)


def test_structured_check_is_read_only_and_identifies_stale_guide(home, monkeypatch):
    reference.accept()
    before = reference.LOCK.read_bytes()
    (reference.GUIDES / "subscriptions.md").write_text(SUBSCRIPTIONS + "\nedit\n")
    monkeypatch.setattr(reference, "live", lambda: {"codex": {"gpt-6-luna", "new-model"}})
    data = reference.inspect()
    assert data["age_days"] == 0
    assert data["stale_guides"] == ["subscriptions.md"]
    assert data["models"]["codex"] == {"new": ["new-model"], "gone": ["gpt-6.1-sol"]}
    assert reference.LOCK.read_bytes() == before and not reference.CACHE.exists()


def test_record_keeps_guide_text_and_records_both_hashes(home):
    reference.accept()
    model = reference.GUIDES / "models.md"
    model.write_text(refreshed(REAL) + "\nIntentionally omitted: `new-model`.\n")
    before = refresh.documents(reference.GUIDES)
    assert refresh.record(yes=True) == 0
    assert refresh.documents(reference.GUIDES) == before
    assert reference.guide_drift() == []
    assert set(reference.guide_hashes()) == set(reference.DOCUMENTS)


@pytest.mark.parametrize("failure", ["model", "date", "holder", "section", "link", "unverified"])
def test_record_rejects_invalid_root_edits_without_changing_lock(home, monkeypatch, failure):
    reference.accept()
    before = reference.LOCK.read_bytes()
    path = reference.GUIDES / "models.md"
    text = refreshed(REAL)
    if failure == "model":
        monkeypatch.setattr(reference, "live", lambda: {"codex": {"gpt-6-luna", "uncovered-model"}})
        expected = "uncovered-model missing"
    elif failure == "date":
        text = text.replace(f"Checked {TODAY}", "Checked 2000-01-01")
        expected = "Checked date"
    elif failure == "holder":
        text += "\nYour plan is Plus.\n"
        expected = "holder-specific"
    elif failure == "section":
        text = text.replace("### Inventory coverage", "### Coverage")
        expected = "missing section"
    elif failure == "link":
        text += "\n[bad](https://)\n"
        expected = "malformed"
    else:
        text = text.replace("Unverified", "Verified")
        expected = "Unverified markers"
    path.write_text(text)
    with pytest.raises(SystemExit, match=expected):
        refresh.record(yes=True)
    assert reference.LOCK.read_bytes() == before and path.read_text() == text


def test_record_requires_confirmation(home, monkeypatch):
    monkeypatch.setattr(refresh.sys.stdin, "isatty", lambda: False)
    with pytest.raises(SystemExit, match="--record --yes"):
        refresh.record()


def test_refresh_check_and_record_cli_routes(home, monkeypatch, capsys):
    reference.accept()
    monkeypatch.setattr(refresh.sys, "argv", ["agent-bridge", "refresh", "--check"])
    cli.main()
    assert json.loads(capsys.readouterr().out)["stale_guides"] == []
    assert not reference.CACHE.exists()
    calls = []
    monkeypatch.setattr(refresh, "record", lambda yes: calls.append(yes) or 0)
    monkeypatch.setattr(refresh.sys, "argv", ["agent-bridge", "refresh", "--record", "--yes"])
    with pytest.raises(SystemExit) as done:
        cli.main()
    assert done.value.code == 0 and calls == [True]


def test_subscription_guide_cli_remains_opt_in(monkeypatch, capsys):
    monkeypatch.setattr(refresh.sys, "argv", ["agent-bridge", "guide", "subscriptions"])
    cli.main()
    assert capsys.readouterr().out == SUBSCRIPTIONS.strip() + "\n"


def test_public_docs_and_help_have_no_holder_specific_wording():
    repo = Path(__file__).resolve().parents[2]
    tracked = subprocess.run(["git", "ls-files", "-z"], cwd=repo,
                             capture_output=True, text=True, check=True).stdout.split("\0")
    paths = {repo / name for name in tracked if name.endswith(".md")}
    paths.update(reference.GUIDES / name for name in reference.DOCUMENTS)
    paths.add(reference.GUIDES.parent / "cli.py")
    offenders = [str(path.relative_to(repo)) for path in sorted(paths)
                 if refresh.HOLDER_WORDING.search(path.read_text(encoding="utf-8"))]
    assert offenders == []
