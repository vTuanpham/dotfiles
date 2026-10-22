"""check_public.py: what it refuses, what it lets through, and that this repository passes it."""

import os
from pathlib import Path
import subprocess
import tempfile
import unittest

root = Path(__file__).resolve().parents[1]
script = root / "tests" / "check_public.py"


def run(repo, terms, *args):
    env = {**os.environ, "DOTFILES_PRIVATE_TERMS": str(terms)}
    return subprocess.run(
        ["python3", "-B", str(script), "--root", str(repo), *args], capture_output=True, text=True, env=env
    )


class CheckPublicTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self.tmp.name) / "repo"
        self.repo.mkdir()
        self.terms = Path(self.tmp.name) / "terms.txt"
        self.terms.write_text("# comments are ignored\nMy Real Name\nsecret-project\n")
        subprocess.run(["git", "-C", str(self.repo), "init", "-q"], check=True)
        subprocess.run(["git", "-C", str(self.repo), "config", "user.email", "a@b.c"], check=True)
        subprocess.run(["git", "-C", str(self.repo), "config", "user.name", "a"], check=True)

    def tearDown(self):
        self.tmp.cleanup()

    def stage(self, name, text):
        path = self.repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        subprocess.run(["git", "-C", str(self.repo), "add", name], check=True)

    def test_public_facing_content_passes(self):
        self.stage("a/README.md", "Dotfiles for a WSL machine.\nContact: me@users.noreply.github.com\n")
        self.stage("a/key.py", "token = secrets.token_urlsafe(32)\n")  # a call, not a value

        self.assertEqual(run(self.repo, self.terms, "--staged").returncode, 0)

    def test_binary_files_are_not_read_as_text_in_a_full_scan(self):
        (self.repo / "pic.gif").write_bytes(b"GIF89a\0\0x@y.zz\0")  # pixels that happen to look like an address
        subprocess.run(["git", "-C", str(self.repo), "add", "pic.gif"], check=True)

        self.assertEqual(run(self.repo, self.terms).returncode, 0)

    def test_each_kind_of_leak_is_refused_with_its_file_and_line_but_never_the_text(self):
        leaks = {
            "a.sh": "export GITHUB_TOKEN=ghp_" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8",
            "b.md": "write to someone@gmail.com",
            "c.toml": '[projects."/home/me/work"]\ntrust_level = "trusted"',
            "d.md": "Notes about My Real Name here",
            "e.md": "see the secret-project repo",
            "auth.json": "{}",
        }
        for name, text in leaks.items():
            self.stage(name, text + "\n")

        result = run(self.repo, self.terms, "--staged")

        self.assertEqual(result.returncode, 1)
        for name in ("a.sh:1", "b.md:1", "c.toml:1", "d.md:1", "e.md:1", "auth.json:0"):
            self.assertIn(name, result.stderr)
        self.assertNotIn("ghp_", result.stderr)  # it says where, never what
        self.assertNotIn("someone@gmail.com", result.stderr)

    def test_only_added_lines_are_judged_so_old_content_never_blocks_a_commit(self):
        self.stage("old.md", "My Real Name wrote this long ago\n")
        subprocess.run(["git", "-C", str(self.repo), "commit", "-qm", "old"], check=True)
        self.stage("old.md", "My Real Name wrote this long ago\nand a clean line\n")

        self.assertEqual(run(self.repo, self.terms, "--staged").returncode, 0)

    def test_changed_mode_catches_what_a_tool_wrote_before_anything_is_staged(self):
        self.stage("shellrc", "export PATH=$HOME/bin:$PATH\n")
        subprocess.run(["git", "-C", str(self.repo), "commit", "-qm", "base"], check=True)
        (self.repo / "shellrc").write_text("export PATH=$HOME/bin:$PATH\nexport KEY=sk-" + "a1" * 15 + "\n")  # an installer appended it
        (self.repo / "generated.md").write_text("notes on secret-project\n")  # a new, untracked file

        result = run(self.repo, self.terms, "--changed")
        clean = run(self.repo, self.terms, "--staged")  # nothing is staged, so the hook would not see either

        self.assertEqual(result.returncode, 1)
        self.assertIn("shellrc:2", result.stderr)
        self.assertIn("generated.md:1", result.stderr)
        self.assertEqual(clean.returncode, 0)

    def test_this_repository_is_public_facing(self):
        result = run(root, Path(self.tmp.name) / "none.txt")  # the built-in rules; private terms are per machine

        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
