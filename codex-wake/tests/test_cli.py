import signal
import sys

import pytest

from codex_wake import cli
from codex_wake.client import validate_message


@pytest.fixture
def target(monkeypatch):
    class Target:
        def __init__(self, thread, home):
            self.thread, self.home = thread, home
            self.checked = False
            self.messages = []

        def check(self):
            self.checked = True

        def send(self, prompt):
            validate_message(prompt)
            self.messages.append(prompt)

    instance = Target("root-thread", None)
    monkeypatch.setattr(cli, "Wake", lambda thread, home: instance)
    return instance


def test_check_does_not_send(target, capsys):
    assert cli.main(["check"]) == 0
    assert target.checked and not target.messages
    assert "ready" in capsys.readouterr().out


def test_send_is_an_automatic_notification(target):
    assert cli.main(["send", "--message", "Build ready"]) == 0
    assert target.checked
    assert target.messages == [f"Build ready\n{cli.NOTICE}"]


@pytest.mark.parametrize("code", [0, 7])
def test_run_preserves_command_output_and_failure(target, capfd, code):
    assert (
        cli.main(
            [
                "run",
                "--message",
                "Check finished",
                "--",
                sys.executable,
                "-c",
                f"import sys; print(sys.argv[1]); sys.exit({code})",
                "$(must stay literal); hello",
            ]
        )
        == code
    )
    assert "$(must stay literal); hello" in capfd.readouterr().out
    assert f"status {code}" in target.messages[0]


def test_run_notifies_when_program_is_missing(target):
    assert cli.main(["run", "--message", "Import", "--", "/nonexistent/codex-wake-test"]) == 127
    assert "could not start" in target.messages[0]


def test_signal_exit_is_reported(target):
    assert (
        cli.main(
            [
                "run",
                "--message",
                "Check",
                "--",
                sys.executable,
                "-c",
                "import os, signal; os.kill(os.getpid(), signal.SIGTERM)",
            ]
        )
        == 128 + signal.SIGTERM
    )
    assert "status -15" in target.messages[0]


def test_delivery_failure_is_not_reported_as_command_success(target, monkeypatch, capsys):
    def fail(_):
        raise RuntimeError("delivery failed")

    monkeypatch.setattr(target, "send", fail)
    assert cli.main(["run", "--message", "Check", "--", sys.executable, "-c", "pass"]) == 125
    assert "delivery failed" in capsys.readouterr().err


@pytest.mark.parametrize("failure", ["preflight", "message"])
def test_invalid_setup_never_starts_command(target, monkeypatch, tmp_path, failure):
    def fail():
        raise RuntimeError("missing capability")

    if failure == "preflight":
        monkeypatch.setattr(target, "check", fail)
    marker = tmp_path / "must-not-exist"
    assert (
        cli.main(
            [
                "run",
                "--message",
                "x" * 1000 if failure == "message" else "Check",
                "--",
                sys.executable,
                "-c",
                "from pathlib import Path; import sys; Path(sys.argv[1]).touch()",
                str(marker),
            ]
        )
        == 125
    )
    assert not marker.exists()


@pytest.mark.parametrize("text", ["", "   ", "é" * 501])
def test_invalid_message_never_sends(target, text):
    assert cli.main(["send", "--message", text]) == 125
    assert not target.messages


def test_explicit_target_overrides_session_environment(monkeypatch):
    monkeypatch.setenv("CODEX_THREAD_ID", "wrong-thread")
    captured = []

    class Target:
        def __init__(self, thread, home):
            captured.append((thread, home))
            self.thread = thread

        def check(self):
            pass

    monkeypatch.setattr(cli, "Wake", Target)
    assert cli.main(["check", "--thread", "target-thread", "--home", "/some/codex-home"]) == 0
    assert captured == [("target-thread", "/some/codex-home")]


def test_missing_target_fails_clearly(monkeypatch, capsys):
    monkeypatch.delenv("CODEX_THREAD_ID", raising=False)
    assert cli.main(["check"]) == 125
    assert "target thread" in capsys.readouterr().err


def test_run_requires_program_before_connecting(monkeypatch):
    monkeypatch.setattr(cli, "Wake", lambda *_: pytest.fail("connected with no program"))
    with pytest.raises(SystemExit) as error:
        cli.main(["run", "--message", "Check", "--"])
    assert error.value.code == 2
