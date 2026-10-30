"""Exercise global filters as an isolated trusted project, including real dispatch."""

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


class FilterTests(unittest.TestCase):
    def test_hook_preserves_intermediate_data_and_shell_control_flow(self):
        rtk = shutil.which("rtk")
        self.assertIsNotNone(rtk, "install RTK before running filter checks")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            env = {**os.environ, "HOME": str(root), "XDG_CONFIG_HOME": str(root / "config"),
                   "XDG_DATA_HOME": str(root / "data")}
            env.pop("RTK_REWRITE_HOST", None)

            def rewrite(command):
                result = subprocess.run(
                    [rtk, "hook", "claude"], input=json.dumps({
                        "tool_name": "Bash", "tool_input": {"command": command}, "cwd": str(root)}),
                    cwd=root, env=env, capture_output=True, text=True, timeout=30,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                output = json.loads(result.stdout) if result.stdout.strip() else {}
                hook = output.get("hookSpecificOutput", {})
                self.assertNotEqual(hook.get("permissionDecision"), "deny", output)
                return hook.get("updatedInput", {}).get("command", command)

            self.assertEqual(rewrite("find . -type f | rg keep | rg jsonl"),
                             "find . -type f | rg keep | rtk rg jsonl")
            self.assertEqual(rewrite("git status; find . -type f | rg jsonl && git diff --stat"),
                             "rtk git status; find . -type f | rtk rg jsonl && rtk git diff --stat")
            for command in ("find . -type f | rg keep | sort", "find . -type f > inventory.txt",
                            'printf "%s\\n" "$(find . -type f | wc -l)"'):
                self.assertEqual(rewrite(command), command)

            for number in range(120):
                (root / f"keep-{number:03d}.jsonl").touch()
            pipeline = "find . -maxdepth 1 -name 'keep-*.jsonl' | rg keep | wc -l"
            result = subprocess.run(["bash", "-o", "pipefail", "-c", rewrite(pipeline)],
                                    cwd=root, env=env, capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout.strip(), "120")
            for command, expected in (("false && git status", 1), ("true || git status", 0)):
                result = subprocess.run(["bash", "-c", rewrite(command)], cwd=root, env=env,
                                        capture_output=True, text=True, timeout=30)
                self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
                self.assertEqual(result.stdout, "")

    def test_inline_fixtures_dispatch_and_failed_exit_code(self):
        rtk = shutil.which("rtk")
        self.assertIsNotNone(rtk, "install RTK before running filter checks")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / ".rtk").mkdir()
            (root / ".rtk/filters.toml").write_bytes(
                (Path(__file__).resolve().parents[1] / "rtk/.config/rtk/filters.toml").read_bytes()
            )
            (root / "uvx").write_text(
                '#!/bin/sh\nprintf "Resolved 2 packages in 120ms\\nerror: fixture failure\\n" >&2\nexit 7\n'
            )
            (root / "uvx").chmod(0o755)
            env = {**os.environ, "XDG_CONFIG_HOME": str(root / "config"),
                   "XDG_DATA_HOME": str(root / "data"),
                   "PATH": str(root) + os.pathsep + os.environ["PATH"]}
            env.pop("RTK_NO_TOML", None)
            env.pop("RTK_TRUST_ALL", None)
            options = dict(cwd=root, env=env, capture_output=True, text=True, timeout=30)
            subprocess.run([rtk, "trust", "--yes"], check=True, **options)
            verified = subprocess.run(
                [rtk, "verify", "--filter", "uvx-progress", "--require-all"], check=True, **options
            )
            self.assertIn("3/3 tests passed", verified.stdout)
            output = subprocess.run([rtk, "uvx", "fixture"], **options)
            self.assertEqual(output.returncode, 7, output.stdout + output.stderr)
            self.assertIn("error: fixture failure", output.stdout + output.stderr)
            self.assertNotIn("Resolved", output.stdout + output.stderr)


if __name__ == "__main__":
    unittest.main()
