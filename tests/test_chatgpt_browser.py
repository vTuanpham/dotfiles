"""The WSL adapter preserves stdio, limits service forwarding, and refuses stale setup."""

import importlib.machinery
import importlib.util
import json
import os
from pathlib import Path, PureWindowsPath
import tempfile
import unittest
from unittest.mock import patch


script = Path(__file__).resolve().parents[1] / "chrome/.local/bin/chatgpt-browser"
loader = importlib.machinery.SourceFileLoader("chatgpt_browser", str(script))
spec = importlib.util.spec_from_loader(loader.name, loader)
browser = importlib.util.module_from_spec(spec)
loader.exec_module(browser)


class BrowserTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        self.mapper = patch.object(browser, "wsl_path", self.map_path)
        self.mapper.start()
        self.addCleanup(self.mapper.stop)
        self.host = self.map_path("C:/app/extension-host.exe")
        self.host.parent.mkdir()
        self.host_config = {
            "schemaVersion": 1,
            "browserClientPath": "C:/plugin/scripts/browser-client.mjs",
            "codexCliPath": "C:/runtime/codex.exe",
            "nodePath": "C:/runtime/node.exe",
            "nodeReplPath": "C:/runtime/node_repl.exe",
        }
        self.env = {key: "app value" for key in browser.RUNTIME_ENV}
        self.env.update(NODE_REPL_NODE_PATH="C:/runtime/node.exe", CODEX_CLI_PATH="C:/runtime/codex.exe")
        self.manifest = {
            "name": browser.HOST, "description": "ChatGPT", "type": "stdio",
            "path": "C:/app/extension-host.exe",
            "allowed_origins": ["chrome-extension://hehggadaopoacecdllhhajmbjkdcmajg/"],
        }
        for name in ("C:/app/extension-host.exe", "C:/runtime/node.exe", "C:/runtime/codex.exe",
                     "C:/runtime/node_repl.exe", "C:/plugin/scripts/browser-client.mjs",
                     "C:/plugin/scripts/browser-service.mjs", "C:/plugin/skills/control-chrome/SKILL.md"):
            path = self.map_path(name)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.touch()
        self.write_config()

    def map_path(self, value):
        return self.home.joinpath(*PureWindowsPath(value).parts[1:])

    def write_config(self, args="[]"):
        (self.host.parent / "extension-host-config.json").write_text(json.dumps(self.host_config))
        config = self.home / ".codex/config.toml"
        config.parent.mkdir(exist_ok=True)
        config.write_text(
            '[mcp_servers.node_repl]\ncommand = "C:/runtime/node_repl.exe"\nargs = ' + args
            + '\n[mcp_servers.node_repl.env]\n'
            + "\n".join(f"{key} = {json.dumps(value)}" for key, value in self.env.items())
            + '\nSKY_CUA_NATIVE_PIPE = "not a browser service"\n'
            + 'NODE_REPL_TRUSTED_SERVICES = "computer service"\n'
        )

    def test_uses_installed_paths_and_only_forwards_the_browser_service(self):
        host, command, env, paths = browser.load_setup(self.home, self.manifest)
        self.assertEqual(host, self.host)
        self.assertEqual(command, self.map_path(self.host_config["nodeReplPath"]))
        self.assertEqual(json.loads(env["NODE_REPL_TRUSTED_SERVICES"]),
                         {"browser": r"C:\plugin\scripts\browser-service.mjs"})
        self.assertEqual(env["BROWSER_USE_AVAILABLE_BACKENDS"], "chrome")
        self.assertNotIn("SKY_CUA_NATIVE_PIPE", env)
        self.assertEqual(set(env["WSLENV"].split(":")), {key + "/w" for key in env if key != "WSLENV"})
        self.assertEqual(paths["client_url"], "file:///C:/plugin/scripts/browser-client.mjs")

    def test_refuses_stale_runtime_unknown_schema_and_extra_arguments(self):
        for field, value in (("schemaVersion", True), ("schemaVersion", 2),
                             ("nodeReplPath", "C:/old/node_repl.exe")):
            with self.subTest(field=field, value=value):
                original = self.host_config[field]
                self.host_config[field] = value
                self.write_config()
                with self.assertRaises(ValueError):
                    browser.load_setup(self.home, self.manifest)
                self.host_config[field] = original
        self.write_config(args='["--disable-sandbox"]')
        with self.assertRaises(ValueError):
            browser.load_setup(self.home, self.manifest)

    def test_refuses_missing_runtime_and_unrestricted_or_wrong_host_manifests(self):
        for manifest in ({**self.manifest, "allowed_origins": ["*"]},
                         {**self.manifest, "name": "another.host"}, None):
            with self.subTest(manifest=manifest), self.assertRaises(ValueError):
                browser.load_setup(self.home, manifest)
        self.host.unlink()
        with self.assertRaisesRegex(ValueError, "missing"):
            browser.load_setup(self.home, self.manifest)

    def test_register_is_idempotent_and_preserves_an_existing_host(self):
        browser.register_linux(self.home, self.manifest)
        destination = self.home / "NativeMessagingHosts" / (browser.HOST + ".json")
        before = destination.read_bytes()
        browser.register_linux(self.home, self.manifest)
        self.assertEqual(destination.read_bytes(), before)
        changed = {**self.manifest, "path": "/another/host"}
        destination.write_text(json.dumps(changed))
        with self.assertRaisesRegex(ValueError, "left unchanged"):
            browser.register_linux(self.home, self.manifest)
        self.assertEqual(json.loads(destination.read_text()), changed)

    def test_mcp_exec_keeps_protocol_context_and_does_not_attach_flags(self):
        setup = (self.host, self.map_path("C:/runtime/node_repl.exe"), {"BROWSER": "setting"}, {})
        with patch.object(browser, "discover", return_value=(self.home, self.manifest, setup)), \
                patch.object(browser.os, "chdir"), patch.object(browser.os, "execve") as execute, \
                patch.dict(os.environ, {"CONVERSATION_CONTEXT": "retained"}), \
                patch.object(browser.sys, "argv", [str(script), "mcp"]):
            browser.main()
        command, args, env = execute.call_args.args
        self.assertEqual(args, [command])
        self.assertEqual(env["CONVERSATION_CONTEXT"], "retained")
        self.assertEqual(env["BROWSER"], "setting")

    def test_discovery_cannot_consume_the_protocol_input(self):
        registration = self.home / "registration.json"
        registration.write_text(json.dumps(self.manifest))
        result = json.dumps({"home": "C:/Users/ảnh ·", "manifest": "C:/ảnh/registration.json"}, ensure_ascii=False)
        with patch.object(browser.subprocess, "check_output", return_value=result) as run, \
                patch.object(browser, "wsl_path", side_effect=[self.home, registration]), \
                patch.object(browser, "load_setup", return_value="setup"):
            self.assertEqual(browser.discover()[2], "setup")
        self.assertEqual(run.call_args.kwargs["stdin"], browser.subprocess.DEVNULL)
        self.assertEqual(run.call_args.kwargs["encoding"], "utf-8")
        self.assertIn("[Console]::OutputEncoding", run.call_args.args[0][-1])


if __name__ == "__main__":
    unittest.main()
