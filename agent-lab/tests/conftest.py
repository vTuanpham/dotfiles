import pytest


@pytest.fixture(autouse=True)
def isolated_native_profiles(monkeypatch, tmp_path):
    for name in (
        "CODEX_THREAD_ID",
        "CLAUDECODE",
        "CLAUDE_CODE_SESSION_ID",
        "ANTIGRAVITY_CONVERSATION_ID",
        "AGENT_BRIDGE_WORKER",
        "AGENT_BRIDGE_JOB",
        "AGENT_BRIDGE_ROOT_HARNESS",
        "AGENT_BRIDGE_ROOT_SESSION",
        "AGENT_LAB_HARNESS",
        "AGENT_LAB_SESSION",
        "AGENT_LAB_MODEL",
        "AGENT_LAB_EFFORT",
        "AGENT_LAB_HOME",
    ):
        monkeypatch.delenv(name, raising=False)
    for name, directory in (
        ("CODEX_HOME", "codex"),
        ("CLAUDE_CONFIG_DIR", "claude"),
        ("AGENT_BRIDGE_HOME", "bridge"),
    ):
        monkeypatch.setenv(name, str(tmp_path / directory))
