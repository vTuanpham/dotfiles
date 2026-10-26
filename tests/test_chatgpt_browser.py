"""The WSL adapter preserves stdio, limits service forwarding, and refuses stale setup."""

import concurrent.futures
import importlib.machinery
import importlib.util
import io
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
        state = patch.dict(os.environ, {"XDG_STATE_HOME": str(self.home / "state")})
        state.start()
        self.addCleanup(state.stop)
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

    def test_repairs_retired_paths_with_private_backup_and_preserves_access_settings(self):
        self.host_config.update(
            nodePath="C:/retired/node.exe", codexCliPath="C:/retired/codex.exe",
            nodeReplPath="C:/retired/node_repl.exe", proxyHost="127.0.0.1", proxyPort=12345,
        )
        self.write_config()
        destination = self.host.parent / "extension-host-config.json"
        original = destination.read_bytes()
        state = self.home / "state"
        with patch.dict(os.environ, {"XDG_STATE_HOME": str(state)}), patch("builtins.print"):
            browser.repair_runtime(self.home, self.manifest)
            browser.load_setup(self.home, self.manifest)
            browser.repair_runtime(self.home, self.manifest)
        repaired = json.loads(destination.read_text())
        self.assertEqual(repaired["nodeReplPath"], r"C:\runtime\node_repl.exe")
        for field in set(self.host_config) - {"nodePath", "codexCliPath", "nodeReplPath"}:
            self.assertEqual(repaired[field], self.host_config[field])
        backups = list((state / "backups/chrome").iterdir())
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].stat().st_mode & 0o777, 0o700)
        saved = backups[0] / "extension-host-config.json"
        self.assertEqual(saved.read_bytes(), original)
        self.assertEqual(saved.stat().st_mode & 0o777, 0o600)

    def test_refuses_ambiguous_existing_runtimes_and_missing_replacement(self):
        self.host_config["nodeReplPath"] = "C:/older/node_repl.exe"
        older = self.map_path(self.host_config["nodeReplPath"])
        older.parent.mkdir()
        older.touch()
        self.write_config()
        destination = self.host.parent / "extension-host-config.json"
        before = destination.read_bytes()
        with self.assertRaisesRegex(ValueError, "still exist"):
            browser.repair_runtime(self.home, self.manifest)
        self.assertEqual(destination.read_bytes(), before)
        older.unlink()
        self.map_path("C:/runtime/node_repl.exe").unlink()
        with self.assertRaisesRegex(ValueError, "missing"):
            browser.repair_runtime(self.home, self.manifest)
        self.assertEqual(destination.read_bytes(), before)

    def test_startup_recovers_retired_paths_without_polluting_mcp_stdout(self):
        self.host_config.update(nodePath="C:/retired/node.exe", codexCliPath="C:/retired/codex.exe",
                                nodeReplPath="C:/retired/node_repl.exe", proxyPort=12345)
        self.write_config()
        destination = self.host.parent / "extension-host-config.json"
        before = destination.read_bytes()
        with patch.object(browser, "read_registration", return_value=(self.home, self.manifest)), \
                patch.dict(os.environ, {"XDG_STATE_HOME": str(self.home / "state")}), \
                patch.object(browser.sys, "stdout", io.StringIO()) as output, \
                patch.object(browser.sys, "stderr", io.StringIO()) as errors:
            with self.assertRaises(ValueError):
                browser.discover()
            self.assertEqual(destination.read_bytes(), before)
            setup = browser.discover(recover=True)[2]
            self.assertEqual(setup[1], self.map_path("C:/runtime/node_repl.exe"))
            self.assertEqual(json.loads(destination.read_text())["proxyPort"], 12345)
            self.assertIn("Updated retired runtime paths", errors.getvalue())
            errors.truncate(0)
            errors.seek(0)
            browser.discover(recover=True)
            self.assertEqual(errors.getvalue(), "")
            self.assertEqual(output.getvalue(), "")

    def test_startup_recovers_again_after_a_subsequent_app_update(self):
        with patch.object(browser, "read_registration", return_value=(self.home, self.manifest)), \
                patch.dict(os.environ, {"XDG_STATE_HOME": str(self.home / "state")}), \
                patch.object(browser.sys, "stderr", io.StringIO()):
            previous = "runtime"
            for release in ("runtime-2", "runtime-3"):
                config = self.home / ".codex/config.toml"
                config.write_text(config.read_text().replace(f"C:/{previous}/", f"C:/{release}/"))
                for name in ("node.exe", "codex.exe", "node_repl.exe"):
                    old = self.map_path(f"C:/{previous}/{name}")
                    new = self.map_path(f"C:/{release}/{name}")
                    new.parent.mkdir(exist_ok=True)
                    old.rename(new)
                setup = browser.discover(recover=True)[2]
                self.assertEqual(setup[1], self.map_path(f"C:/{release}/node_repl.exe"))
                previous = release

    def test_recovery_preserves_any_still_installed_runtime(self):
        self.host_config.update(nodePath="C:/older/node.exe", nodeReplPath="C:/retired/node_repl.exe")
        older = self.map_path("C:/older/node.exe")
        older.parent.mkdir()
        older.touch()
        self.write_config()
        destination = self.host.parent / "extension-host-config.json"
        before = destination.read_bytes()
        with patch.object(browser, "read_registration", return_value=(self.home, self.manifest)), \
                patch.dict(os.environ, {"XDG_STATE_HOME": str(self.home / "state")}):
            with self.assertRaisesRegex(ValueError, "still exist"):
                browser.discover(recover=True)
        self.assertEqual(destination.read_bytes(), before)

    def test_concurrent_startups_recover_once(self):
        self.host_config.update(nodePath="C:/retired/node.exe", codexCliPath="C:/retired/codex.exe",
                                nodeReplPath="C:/retired/node_repl.exe")
        self.write_config()
        state = self.home / "state"
        with patch.object(browser, "read_registration", return_value=(self.home, self.manifest)), \
                patch.dict(os.environ, {"XDG_STATE_HOME": str(state)}), \
                patch.object(browser.sys, "stderr", io.StringIO()), \
                concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            setups = list(pool.map(lambda _: browser.discover(recover=True), range(8)))
        self.assertEqual(len(setups), 8)
        self.assertEqual(len(list((state / "backups/chrome").iterdir())), 1)

    def test_native_origin_is_checked_before_recovery(self):
        with patch.object(browser, "read_registration", return_value=(self.home, self.manifest)), \
                patch.object(browser, "repair_runtime") as repair:
            with self.assertRaisesRegex(ValueError, "origin"):
                browser.discover(recover=True, origin="chrome-extension://unapproved/")
        repair.assert_not_called()

    def test_recovery_does_not_rewrite_invalid_setup(self):
        for field, value in (("schemaVersion", 2), ("browserClientPath", "C:/missing/client.mjs")):
            with self.subTest(field=field):
                original = self.host_config[field]
                self.host_config[field] = value
                self.host_config["nodeReplPath"] = "C:/retired/node_repl.exe"
                self.write_config()
                destination = self.host.parent / "extension-host-config.json"
                before = destination.read_bytes()
                with patch.object(browser, "read_registration", return_value=(self.home, self.manifest)), \
                        self.assertRaises(ValueError):
                    browser.discover(recover=True)
                self.assertEqual(destination.read_bytes(), before)
                self.host_config[field] = original

    def test_invalid_state_directories_use_the_home_state_directory(self):
        for value in ("", ".", "relative/state"):
            with self.subTest(value=value):
                self.host_config["nodeReplPath"] = "C:/retired/node_repl.exe"
                self.write_config()
                with patch.dict(os.environ, {"XDG_STATE_HOME": value}), \
                        patch.object(browser.Path, "home", return_value=self.home), \
                        patch("builtins.print"):
                    browser.repair_runtime(self.home, self.manifest)
        backups = list((self.home / ".local/state/backups/chrome").iterdir())
        self.assertEqual(len(backups), 3)

    def test_mcp_exec_keeps_protocol_context_and_does_not_attach_flags(self):
        setup = (self.host, self.map_path("C:/runtime/node_repl.exe"), {"BROWSER": "setting"}, {})
        with patch.object(browser, "discover", return_value=(self.home, self.manifest, setup)) as discover, \
                patch.object(browser.os, "chdir"), patch.object(browser.os, "execve") as execute, \
                patch.dict(os.environ, {"CONVERSATION_CONTEXT": "retained"}), \
                patch.object(browser.sys, "argv", [str(script), "mcp"]):
            browser.main()
        discover.assert_called_once_with(recover=True)
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

    def test_native_host_startup_recovers_before_exec(self):
        setup = (self.host, self.map_path("C:/runtime/node_repl.exe"), {}, {})
        origin = self.manifest["allowed_origins"][0]
        with patch.object(browser, "discover", return_value=(self.home, self.manifest, setup)) as discover, \
                patch.object(browser.os, "chdir"), \
                patch.object(browser.os, "execv", side_effect=SystemExit(0)) as execute, \
                patch.object(browser.sys, "argv", [str(script), origin]):
            with self.assertRaises(SystemExit) as exited:
                browser.main()
            self.assertEqual(exited.exception.code, 0)
        discover.assert_called_once_with(recover=True, origin=origin)
        execute.assert_called_once_with(str(self.host), [str(self.host), origin])

    def test_explicit_kernel_exception_preserves_approval_context(self):
        setup = (self.host, self.map_path("C:/runtime/node_repl.exe"), {"BROWSER": "setting"}, {})
        with patch.object(browser, "discover", return_value=(self.home, self.manifest, setup)), \
                patch.object(browser.os, "chdir"), patch.object(browser.os, "execve") as execute, \
                patch.dict(os.environ, {"CONVERSATION_CONTEXT": "retained"}), \
                patch.object(browser.sys, "argv", [str(script), "mcp", "--disable-sandbox"]):
            browser.main()
        command, args, env = execute.call_args.args
        self.assertEqual(args, [command, "--disable-sandbox"])
        self.assertEqual(env["CONVERSATION_CONTEXT"], "retained")
        self.assertEqual(env["BROWSER"], "setting")

    def test_kernel_exception_is_not_a_registration_or_discovery_option(self):
        for mode in ("paths", "register-linux"):
            with self.subTest(mode=mode), \
                    patch.object(browser.sys, "argv", [str(script), mode, "--disable-sandbox"]), \
                    patch.object(browser, "discover") as discover, \
                    patch.object(browser.sys, "stderr"), self.assertRaises(SystemExit) as error:
                browser.main()
            self.assertEqual(error.exception.code, 2)
            discover.assert_not_called()

    def doctor_setup(self):
        setup = browser.load_setup(self.home, self.manifest)
        (self.home / ".codex/config.toml").write_text(
            '[mcp_servers.node_repl]\ncommand = ' + json.dumps(str(script)) + '\nargs = ["mcp"]\n'
        )
        return setup

    def test_doctor_distinguishes_optional_profiles_from_required_registration(self):
        setup = self.doctor_setup()
        profile = self.home / ".config/google-chrome"
        profile.mkdir(parents=True)
        with patch.object(browser.Path, "home", return_value=self.home), \
                patch.object(browser, "discover", return_value=(self.home, self.manifest, setup)), \
                patch.object(browser.shutil, "which", side_effect=lambda value: value), \
                patch("builtins.print") as output:
            self.assertEqual(browser.doctor(), 0)
            self.assertIn("not configured", str(output.call_args_list))
            self.assertEqual(browser.doctor(profile), 1)
            browser.register_linux(profile, self.manifest)
            self.assertEqual(browser.doctor(profile), 0)

    def test_doctor_reports_runtime_failure_and_rejects_an_unrelated_mcp_launcher(self):
        self.doctor_setup()
        (self.home / ".codex/config.toml").write_text(
            '[mcp_servers.node_repl]\ncommand = "/unrelated"\nargs = ["mcp"]\n'
        )
        with patch.object(browser.Path, "home", return_value=self.home), \
                patch.object(browser, "discover", side_effect=ValueError("stale runtime")), \
                patch.object(browser.shutil, "which", side_effect=lambda value: value), \
                patch("builtins.print") as output:
            self.assertEqual(browser.doctor(), 1)
        self.assertIn("stale runtime", str(output.call_args_list))
        self.assertIn("Codex MCP launcher", str(output.call_args_list))


if __name__ == "__main__":
    unittest.main()
