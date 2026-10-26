import sys

import pytest

from agent_bridge import cli


@pytest.mark.parametrize("args", [
    ("start", "owner/job", "--backend", "codex", "--title", "A task", "--cwd", ".",
     "--sandbox", "read-only", "--watch", "a very long invalid value that must be truncated"),
    ("resume", "owner/job", "--watch", "a very long invalid value that must be truncated"),
])
def test_noninteger_watch_without_text_is_rejected_helpfully(monkeypatch, capsys, args):
    monkeypatch.delenv(cli.WORKER_FLAG, raising=False)
    monkeypatch.setattr(sys, "argv", ["agent-bridge", *args])
    with pytest.raises(SystemExit) as error:
        cli.main()
    message = capsys.readouterr().err
    assert error.value.code == 2
    assert "put text before --watch" in message
    assert "use --watch=SECONDS" in message
    assert "or use --prompt-file" in message
    assert "a very long invalid value that must be truncated" not in message


def test_numeric_message_after_explicit_timeout_is_rejected_as_ambiguous(monkeypatch, capsys):
    monkeypatch.delenv(cli.WORKER_FLAG, raising=False)
    monkeypatch.setattr(sys, "argv", ["agent-bridge", "steer", "owner/job", "--watch", "20", "30"])
    with pytest.raises(SystemExit) as error:
        cli.main()
    assert error.value.code == 2
    assert "ambiguous numeric steer text" in capsys.readouterr().err
