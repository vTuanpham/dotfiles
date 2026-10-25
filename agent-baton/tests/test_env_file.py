import json
import stat

import pytest

from agent_baton import env_file


def test_store_replaces_entries_formats_and_backs_up_with_restore_info(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    shell = tmp_path / "secrets.sh"
    dotenv = tmp_path / ".env"
    shell.write_text("export TOKEN=old\nkeep=yes\n")
    dotenv.write_text("TOKEN=old\nkeep=yes\n")

    backup = env_file.store("TOKEN", "liquid_new-1", [shell, dotenv], "liquid_")

    assert shell.read_text() == "keep=yes\nexport TOKEN=liquid_new-1\n"
    assert dotenv.read_text() == "keep=yes\nTOKEN=liquid_new-1\n"
    assert all(path.stat().st_mode & 0o777 == 0o600 for path in (shell, dotenv))
    assert stat.S_IMODE(backup.stat().st_mode) == 0o700
    info = json.loads((backup / "origin.json").read_text())
    assert info["restore"] and set(info["files"].values()) == {str(shell), str(dotenv)}
    assert all((backup / name).stat().st_mode & 0o777 == 0o600 for name in info["files"])
    assert all((backup / name).exists() for name in info["files"])


@pytest.mark.parametrize(
    "name,value,prefix",
    [
        ("bad-name", "liquid_key", "liquid_"),
        ("TOKEN", "other_key", "liquid_"),
        ("TOKEN", "liquid key", "liquid_"),
        ("TOKEN", 'liquid"key', "liquid_"),
        ("TOKEN", "liquid\nkey", "liquid_"),
        ("TOKEN", "liquid_key", "bad prefix"),
    ],
)
def test_rejects_bad_name_prefix_and_value_without_writing(tmp_path, name, value, prefix):
    target = tmp_path / ".env"
    target.write_text("keep=yes\n")
    with pytest.raises(ValueError):
        env_file.store(name, value, [target], prefix)
    assert target.read_text() == "keep=yes\n"


@pytest.mark.parametrize("mode", [0o622, 0o660, 0o666])
def test_refuses_group_or_world_writable_targets(tmp_path, mode):
    target = tmp_path / ".env"
    target.write_text("keep=yes\n")
    target.chmod(mode)
    with pytest.raises(ValueError, match="unsafe target"):
        env_file.store("TOKEN", "key", [target])
    assert target.read_text() == "keep=yes\n"


def test_refuses_symlinked_targets(tmp_path):
    original = tmp_path / "original"
    original.write_text("keep=yes\n")
    link = tmp_path / ".env"
    link.symlink_to(original)
    with pytest.raises(ValueError, match="unsafe target"):
        env_file.store("TOKEN", "key", [link])
    assert original.read_text() == "keep=yes\n"


def test_new_file_is_created_without_backup(tmp_path):
    target = tmp_path / ".env"
    assert env_file.store("TOKEN", "key", [target]) is None
    assert target.read_text() == "TOKEN=key\n"
    assert target.stat().st_mode & 0o777 == 0o600
