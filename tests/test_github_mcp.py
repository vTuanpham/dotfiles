"""The credential adapter never places tokens in output or process arguments."""

import importlib.machinery
import importlib.util
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

script = Path(__file__).resolve().parents[1] / "github/.local/bin/github-mcp"
loader = importlib.machinery.SourceFileLoader("github_mcp", str(script))
spec = importlib.util.spec_from_loader(loader.name, loader)
adapter = importlib.util.module_from_spec(spec)
loader.exec_module(adapter)


class CredentialTests(unittest.TestCase):
    def test_token_only_reaches_the_official_servers_environment(self):
        with patch.object(adapter.shutil, "which", side_effect=["/bin/gh", "/bin/github-mcp-server"]), \
                patch.object(adapter.subprocess, "run", return_value=SimpleNamespace(
                    returncode=0, stdout="held-canary\n", stderr="")) as lookup, \
                patch.object(adapter.os, "execve") as execute, \
                patch.object(adapter.sys, "argv", [str(script), "--read-only"]):
            adapter.main()
        command, args, env = execute.call_args.args
        self.assertEqual(command, "/bin/github-mcp-server")
        self.assertEqual(args, [command, "stdio", "--read-only"])
        self.assertEqual(env["GITHUB_PERSONAL_ACCESS_TOKEN"], "held-canary")
        self.assertNotIn("held-canary", str(lookup.call_args))
        self.assertEqual(lookup.call_args.kwargs["stdin"], adapter.subprocess.DEVNULL)

    def test_missing_auth_and_malformed_output_fail_without_echoing_values(self):
        for code, output in ((1, "held-canary\n"), (0, ""), (0, "held canary\n"),
                             (0, "held-canary\n\n"), (0, "held-canary\0\n")):
            with self.subTest(code=code, output=output), \
                    patch.object(adapter.shutil, "which", return_value="/bin/tool"), \
                    patch.object(adapter.subprocess, "run", return_value=SimpleNamespace(
                        returncode=code, stdout=output, stderr="held-canary")), \
                    patch.object(adapter.os, "execve") as execute, self.assertRaises(SystemExit) as error:
                adapter.main()
            execute.assert_not_called()
            self.assertNotIn("held-canary", str(error.exception))


if __name__ == "__main__":
    unittest.main()
