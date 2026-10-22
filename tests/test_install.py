"""Check install.sh against a throwaway HOME: dry runs change nothing, links are idempotent, and a file
that differs from the repo is reported and left alone."""

import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest

root = Path(__file__).resolve().parents[1]
script = root / "install.sh"


def install(home, *args):
    env = {**os.environ, "HOME": str(home)}
    return subprocess.run([str(script), *args], capture_output=True, text=True, env=env, cwd=root)


class InstallTests(unittest.TestCase):
    def test_a_dry_run_changes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = install(tmp, "links", "snapshots")

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("ln -s", result.stdout)
            self.assertEqual(list(Path(tmp).iterdir()), [])

    def test_links_point_into_the_repo_and_a_second_run_does_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            first = install(tmp, "--apply", "links")
            second = install(tmp, "--apply", "links")

            self.assertEqual(first.returncode, 0, first.stderr)
            for name in (".zshrc", ".claude/CLAUDE.md", ".config/systemd/user/agent-bridge-reference.timer"):
                link = Path(tmp) / name
                self.assertTrue(link.is_symlink(), name)
                self.assertTrue(str(link.resolve()).startswith(str(root)), name)
            self.assertNotIn("  + ", second.stdout)

    def test_a_different_file_is_a_conflict_and_is_left_alone_but_an_identical_copy_becomes_a_link(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            (home / ".zshrc").write_text("my own zshrc\n")
            crlf = (root / "shell/.zprofile").read_text().replace("\n", "\r\n")
            (home / ".zprofile").write_text(crlf.rstrip("\r\n"))  # same text: CRLF and no final newline

            result = install(home, "--apply", "links")

            self.assertEqual(result.returncode, 1)
            self.assertIn("CONFLICT", result.stdout)
            self.assertEqual((home / ".zshrc").read_text(), "my own zshrc\n")
            self.assertTrue((home / ".zprofile").is_symlink())
            self.assertTrue((home / ".bashrc").is_symlink())  # the rest still went through

    def test_snapshots_copy_only_what_is_missing_and_never_a_package_readme(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            (home / ".gitconfig").write_text("[user]\n\tname = someone else\n")

            result = install(home, "--apply", "snapshots")

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual((home / ".gitconfig").read_text(), "[user]\n\tname = someone else\n")
            self.assertIn("differs: ~/.gitconfig", result.stdout)
            self.assertTrue((home / ".claude/settings.json").is_file())
            self.assertFalse((home / "README.md").exists())


    def test_hooks_are_added_to_an_existing_file_without_losing_anything_and_only_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            live = home / ".claude/settings.json"
            live.parent.mkdir()
            live.write_text(
                json.dumps(
                    {
                        "model": "mine",
                        "hooks": {"PreToolUse": [{"matcher": "Bash", "hooks": [{"type": "command", "command": "mine"}]}]},
                    }
                )
            )

            dry = install(home, "hooks")
            self.assertIn("gains the hooks and plugins", dry.stdout)
            self.assertNotIn("agent-baton guard", live.read_text())  # a dry run edits nothing

            install(home, "--apply", "hooks")
            result = json.loads(live.read_text())
            commands = [h["command"] for g in result["hooks"]["PreToolUse"] for h in g["hooks"]]
            self.assertEqual(result["model"], "mine")
            self.assertIn("mine", commands)
            self.assertEqual(commands.count("agent-baton guard"), 2)  # the Bash group and the browser-tool group
            self.assertIn("rtk hook claude", commands)
            self.assertTrue(result["enabledPlugins"]["ponytail@ponytail"])  # the plugin and its marketplace
            self.assertIn("ponytail", result["extraKnownMarketplaces"])
            self.assertTrue((home / ".claude/settings.json.bak-install").is_file())
            self.assertIn("already has the hooks", install(home, "--apply", "hooks").stdout)

    def test_the_cron_line_is_a_valid_five_field_entry(self):
        line = re.search(r"local line='([^']+)'", script.read_text()).group(1)

        self.assertRegex(line, r"^\d+ \* \* \* \* \$HOME/\S+ >/dev/null 2>>\$HOME/\S+$")


if __name__ == "__main__":
    unittest.main()
