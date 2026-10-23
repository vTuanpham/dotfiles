"""Keep Windows console code pages out of the WSL text protocol."""

import base64
import shutil
import subprocess

import pytest

from agent_baton import inject, notify


def test_script_uses_utf8_pipes_and_keeps_payload_off_command_line(monkeypatch):
    calls = []
    monkeypatch.setattr(inject.shutil, "which", lambda _: "powershell.exe")

    def run(args, **kwargs):
        calls.append((args, kwargs))
        return subprocess.CompletedProcess(args, 0, "", "")

    monkeypatch.setattr(inject.subprocess, "run", run)
    payload = "private · ảnh 日本語 🔒"
    inject.run_script("[Console]::Out.Write([Console]::In.ReadToEnd())", payload)
    args, kwargs = calls[0]
    source = base64.b64decode(args[-1]).decode("utf-16-le")
    assert payload not in source and payload not in str(args)
    assert kwargs["input"] == payload
    assert kwargs["encoding"] == "utf-8"
    assert kwargs["capture_output"] is True
    assert kwargs["timeout"] == inject.SEND_TIMEOUT_S
    assert "[Console]::InputEncoding" in source
    assert "[Console]::OutputEncoding" in source


def test_notifications_share_pipe_contract_and_preserve_failure(monkeypatch):
    calls = []

    def run(script, **kwargs):
        calls.append((script, kwargs))
        return subprocess.CompletedProcess([], 7)

    monkeypatch.setattr(inject, "run_script", run)
    with pytest.raises(OSError, match="powershell exited 7"):
        notify.powershell("exit 7")
    assert calls == [("exit 7", {"timeout": 20})]


@pytest.mark.skipif(not shutil.which(inject.POWERSHELL), reason="requires Windows PowerShell")
@pytest.mark.parametrize("exit_code", [0, 7])
def test_windows_unicode_round_trip_and_notification_output(exit_code):
    sample = "· ảnh 日本語 🔒"
    result = inject.run_script(
        "$text = [Console]::In.ReadToEnd(); "
        f"[Console]::Out.Write($text); [Console]::Error.Write($text); exit {exit_code}",
        sample,
    )
    assert result.returncode == exit_code
    assert result.stdout == result.stderr == sample
    notify.powershell("[Console]::Out.Write([char]0xb7)")


@pytest.mark.skipif(not shutil.which(inject.POWERSHELL), reason="requires Windows PowerShell")
def test_windows_invalid_utf8_is_not_silently_replaced():
    with pytest.raises(UnicodeDecodeError):
        inject.run_script("[Console]::OpenStandardOutput().WriteByte(0xfa)")
