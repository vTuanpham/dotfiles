"""Exercise global filters as an isolated trusted project, including real dispatch."""

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


class FilterTests(unittest.TestCase):
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
