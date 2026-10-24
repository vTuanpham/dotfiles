import io
import json
import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import urlopen

import pytest

from portlink import backend, cli, core, models, static
from portlink.models import Link, Target


def link(**values):
    return replace(Link("a" * 32, "demo", "https://example.tailnet.ts.net:18000",
                        Target("proxy", "http://127.0.0.1:3000"), 18000, 100, 3700), **values)


class FakeBackend:
    def __init__(self):
        self.units = {}
        self.reserved = {80, 443, 8443}
        self.stopped = []

    def serve(self):
        return backend.ServeView(frozenset(self.reserved | {item.port for item in self.units.values()}),
                                 {item.port: item.target for item in self.units.values()})

    def unit(self, value):
        owned = self.units.get(value.id)
        return backend.Unit(owned is not None, owned is not None,
                            owned.description if owned else "", owned is not None)

    def start(self, value):
        assert value.port not in self.serve().ports
        self.units[value.id] = value

    def stop(self, value):
        backend.check_owner(value, self.unit(value))
        self.stopped.append(value.id)
        self.units.pop(value.id, None)


@pytest.fixture
def setup(tmp_path, monkeypatch):
    fake = FakeBackend()
    for field in ("unit", "serve", "start", "stop"):
        monkeypatch.setattr(backend, field, getattr(fake, field))
    monkeypatch.setattr(backend, "hostname", lambda: "example.tailnet.ts.net")
    monkeypatch.setattr(backend, "backend_ready", lambda _: None)
    return core.Store(tmp_path / "state"), fake


def test_parallel_previews_allocate_separate_ports_and_close_only_the_named_link(setup):
    store, fake = setup
    with ThreadPoolExecutor(max_workers=6) as pool:
        links = list(pool.map(lambda n: store.open("3000", f"demo-{n}"), range(6)))
    assert len({item.port for item in links}) == 6
    assert not ({item.port for item in links} & fake.reserved)
    store.close(links[0].name)
    assert len(store.list()) == 5
    assert fake.reserved == {80, 443, 8443}
    assert fake.stopped == [links[0].id]
    assert not store.qr(links[0]).exists()


def test_conflicts_do_not_modify_existing_routes(setup):
    store, fake = setup
    first = store.open("3000", "same")
    for options in ({"label": "same"}, {"listen": 443}, {"listen": first.port}):
        with pytest.raises(ValueError):
            store.open("3000", **options)
    assert store.list() == [first]
    assert not fake.stopped


def test_expiry_collects_records_qr_and_abandoned_writes_without_stopping_other_links(setup):
    store, fake = setup
    short = store.open("3000", "short", ttl=1)
    keep = store.open("3000", "keep", ttl=None)
    assert keep.expires is None
    fake.units.pop(short.id)  # Native RuntimeMaxSec collected this unit.
    pending = store.root / ".pending-crash"
    pending.write_text("partial")
    assert store.list() == [keep]
    assert not (store.root / (short.id + ".json")).exists()
    assert not store.qr(short).exists()
    assert not pending.exists()
    assert keep.id in fake.units


def test_failed_start_rolls_back_only_its_own_record(setup, monkeypatch):
    store, fake = setup
    first = store.open("3000", "existing")

    def failure(value):
        fake.start(value)
        raise RuntimeError("startup failed")

    monkeypatch.setattr(backend, "start", failure)
    with pytest.raises(RuntimeError, match="startup failed"):
        store.open("3000", "failed")
    assert store.list() == [first]
    assert len(list(store.root.glob("*.json"))) == 1


def test_changed_unit_ownership_is_preserved(setup, monkeypatch):
    store, fake = setup
    value = store.open("3000", "owned")
    monkeypatch.setattr(backend, "unit", lambda _: backend.Unit(True, True, "someone-else", True))
    with pytest.raises(RuntimeError, match="ownership"):
        store.list()
    with patch.object(backend, "command") as command:
        with pytest.raises(RuntimeError, match="ownership"):
            backend.check_owner(value, backend.unit(value))
        command.assert_not_called()
    assert value.id in fake.units
    assert store.qr(value).exists()


def test_records_and_qr_are_private_and_json_round_trips(setup):
    store, _ = setup
    value = store.open("3000")
    assert store.root.stat().st_mode & 0o777 == 0o700
    for path in store.root.iterdir():
        assert path.stat().st_mode & 0o777 == 0o600
    assert models.decode_link(value.encode()) == value
    assert "<svg" in store.qr(value).read_text()
    assert not list(store.root.glob(".pending-*"))


def test_refuses_symlink_records_and_public_state_directories(setup, tmp_path):
    store, _ = setup
    value = store.open("3000")
    record = store.root / (value.id + ".json")
    outside = tmp_path / "outside"
    record.rename(outside)
    record.symlink_to(outside)
    with pytest.raises(OSError):
        store.list()
    record.unlink()
    store.root.chmod(0o755)
    with pytest.raises(ValueError, match="private"):
        store.list()


@pytest.mark.parametrize("value", [True, 0, -1, 65536, "3000", 3.5])
def test_rejects_invalid_ports(value):
    with pytest.raises(ValueError):
        models.port(value)


@pytest.mark.parametrize("value", ["http://example.com:3000", "http://localhost:3000/path",
                                  "http://user:pass@localhost:3000", "https://localhost:3000",
                                  "http://localhost:3000?x", "0", "65536", "/", "x\n"])
def test_rejects_nonlocal_or_ambiguous_targets(value):
    with pytest.raises((ValueError, OSError)):
        models.target(value)


def test_accepts_explicit_static_paths_and_normalizes_loopback_urls(tmp_path):
    assert models.target("http://localhost:3000/") == models.target("3000")
    folder = tmp_path / "demo $literal with spaces"
    folder.mkdir()
    assert models.target(str(folder)) == Target("path", str(folder))


@pytest.mark.parametrize("value", ["NaN", "Infinity", '{"x":1,"x":2}'])
def test_rejects_ambiguous_json(value):
    with pytest.raises(ValueError):
        models.loads(value)


@pytest.mark.parametrize("values", [{"created": float("nan")}, {"expires": float("inf")},
                                   {"expires": 1}, {"id": "../other"}, {"port": True},
                                   {"url": "https://user:pass@example.tailnet.ts.net:18000"}])
def test_rejects_malformed_saved_records(values):
    with pytest.raises(ValueError):
        models.decode_link(link(**values).encode())


def test_serve_decoder_reserves_background_foreground_and_public_ports():
    raw = {"TCP": {"443": {"HTTPS": True}, "80": {"TCPForward": "127.0.0.1:9000"}},
           "Foreground": {"session": {
               "TCP": {"18000": {"HTTPS": True}, "18001": {"HTTPS": False}},
               "Web": {"example.tailnet.ts.net:18000": {"Handlers": {
                   "/": {"Proxy": "http://127.0.0.1:3000"}}}}
           }}}
    decoded = backend.decode_serve(raw)
    assert decoded.ports == {80, 443, 18000, 18001}
    assert decoded.foreground == {18000: Target("proxy", "http://127.0.0.1:3000")}
    raw["AllowFunnel"] = {"example.tailnet.ts.net:18000": True}
    assert not backend.decode_serve(raw).foreground


@pytest.mark.parametrize("raw", [[], {"TCP": []}, {"Foreground": []},
                                {"TCP": {"65536": {}}}, {"TCP": {"080": {}}},
                                {"TCP": {"80": {"HTTPS": "true"}}},
                                {"AllowFunnel": {"example.tailnet.ts.net:443": "false"}}])
def test_rejects_unknown_or_malformed_status_instead_of_assuming_ports_are_free(raw):
    with pytest.raises(ValueError):
        backend.decode_serve(raw)


def test_json_null_and_empty_object_are_the_native_unconfigured_state():
    for raw in (None, {}):
        assert backend.decode_serve(raw) == backend.ServeView(frozenset(), {})


def test_systemd_launch_owns_a_foreground_process_and_preserves_literal_dollars():
    value = link(target=Target("path", "/tmp/demo $HOME with spaces"))
    with patch.object(backend.shutil, "which", return_value="/usr/bin/tailscale"), \
            patch.object(backend, "command") as command:
        backend.start(value)
    args = command.call_args.args
    assert "--bg" not in args
    assert "--property=RuntimeMaxSec=3600" in args
    assert args[-1] == "/tmp/demo $$HOME with spaces"
    assert f"--unit={value.unit}" in args
    assert f"--description={value.description}" in args


def test_stop_cannot_target_a_foreign_or_nontransient_service():
    for state in (backend.Unit(True, True, "foreign", True),
                  backend.Unit(True, True, link().description, False)):
        with patch.object(backend, "unit", return_value=state), patch.object(backend, "command") as command:
            with pytest.raises(RuntimeError, match="ownership"):
                backend.stop(link())
            command.assert_not_called()


def test_command_never_runs_a_shell_and_surfaces_failure():
    failed = subprocess.CompletedProcess([], 1, "", "denied")
    with patch.object(backend.subprocess, "run", return_value=failed):
        with pytest.raises(RuntimeError, match="denied"):
            backend.command("tailscale", "serve", "status")


def test_cli_emits_machine_output_without_qr_spam(setup, monkeypatch, capsys):
    store, _ = setup
    monkeypatch.setattr(cli, "Store", lambda: store)
    monkeypatch.setattr(cli.sys, "argv", ["portlink", "open", "3000", "--name", "demo", "--json"])
    assert cli.main() == 0
    result = json.loads(capsys.readouterr().out)
    assert result["private"] is True
    assert result["name"] == "demo"
    assert Path(result["qr"]).is_file()


def test_human_output_shows_expiry_and_tty_qr(setup):
    store, _ = setup
    value = store.open("3000", "demo")
    stream = io.StringIO()
    with patch.object(cli.sys, "stdout", stream), patch.object(stream, "isatty", return_value=True):
        cli.show(value, store)
    assert "Private" in stream.getvalue()
    assert value.url in stream.getvalue()
    assert "▄" in stream.getvalue() or "▀" in stream.getvalue()


def test_duration_parsing_and_invalid_state_home(monkeypatch):
    assert models.duration("15m") == 900
    for value in ("0s", "-1h", "NaN", "1.5h", "1h2m"):
        with pytest.raises(ValueError):
            models.duration(value)
    monkeypatch.setenv("XDG_STATE_HOME", "relative")
    assert core.default_state() == Path.home() / ".local/state/portlink"


@pytest.fixture
def static_site(tmp_path):
    root = tmp_path / "public $literal"
    root.mkdir()
    (root / "index.html").write_text("<h1>preview</h1>")
    (root / "asset.txt").write_text("asset")
    (root / ".env").write_text("private fixture")
    outside = tmp_path / "outside.txt"
    outside.write_text("outside fixture")
    (root / "escape.txt").symlink_to(outside)
    with static.server(root) as http:
        thread = threading.Thread(target=http.serve_forever, daemon=True)
        thread.start()
        try:
            yield root, f"http://127.0.0.1:{http.server_port}"
        finally:
            http.shutdown()
            thread.join(timeout=2)


def test_static_previews_serve_assets_but_confine_files_and_hide_dotfiles(static_site):
    root, url = static_site
    with urlopen(url, timeout=2) as response:
        assert b"preview" in response.read()
    with urlopen(url + "/asset.txt", timeout=2) as response:
        assert response.read() == b"asset"
    for path in ("/.env", "/%2eenv", "/escape.txt"):
        with pytest.raises(HTTPError) as error:
            urlopen(url + path, timeout=2)
        assert error.value.code == 404
    with pytest.raises(HTTPError) as error:
        urlopen(url + "/%00", timeout=2)
    assert error.value.code == 400
    (root / "index.html").unlink()
    (root / "index.html").symlink_to(root.parent / "outside.txt")
    with pytest.raises(HTTPError) as error:
        urlopen(url, timeout=2)
    assert error.value.code == 404


def test_single_file_sharing_does_not_expose_siblings_or_misparse_special_names(tmp_path):
    selected = tmp_path / "demo #%.html"
    selected.write_text("selected")
    (tmp_path / "sibling.txt").write_text("sibling")
    with static.server(selected) as http:
        thread = threading.Thread(target=http.serve_forever, daemon=True)
        thread.start()
        try:
            url = f"http://127.0.0.1:{http.server_port}"
            with urlopen(url, timeout=2) as response:
                assert response.read() == b"selected"
            with pytest.raises(HTTPError) as error:
                urlopen(url + "/sibling.txt", timeout=2)
            assert error.value.code == 404
            selected.unlink()
            with pytest.raises(HTTPError) as error:
                urlopen(url + "/sibling.txt", timeout=2)
            assert error.value.code == 404
        finally:
            http.shutdown()
            thread.join(timeout=2)
