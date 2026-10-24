"""Tailscale and systemd boundaries; previews own foreground sessions, never global config."""

import http.client
import re
import shutil
import socket
import subprocess
import sys
from dataclasses import dataclass
from urllib.parse import urlsplit

from .models import Link, Target, loads, port, text


def command(*args, missing_ok=False):
    result = subprocess.run(args, stdin=subprocess.DEVNULL, capture_output=True,
                            text=True, encoding="utf-8", timeout=15)
    if result.returncode and not missing_ok:
        raise RuntimeError(f"{args[0]}: {(result.stderr or result.stdout)[-1200:].strip()}")
    return result.stdout


@dataclass(frozen=True)
class ServeView:
    ports: frozenset[int]
    foreground: dict[int, Target]


def mapping(value, label):
    if type(value) is not dict:
        raise ValueError(f"Invalid {label}")
    return value


def decode_serve(raw):
    if raw is None:  # The CLI emits JSON null when no Serve config exists.
        return ServeView(frozenset(), {})
    root = mapping(raw, "Serve config")
    configs = [(root, False)]
    configs.extend((mapping(item, "foreground config"), True)
                   for item in mapping(root.get("Foreground", {}), "foreground sessions").values())
    ports, targets, public = set(), {}, set()
    for config, foreground in configs:
        tcp = mapping(config.get("TCP", {}), "TCP listeners")
        for value, handler in tcp.items():
            if not isinstance(value, str) or not re.fullmatch(r"[1-9][0-9]{0,4}", value):
                raise ValueError("Invalid Serve port")
            ports.add(port(int(value)))
            handler = mapping(handler, "TCP handler")
            if "HTTPS" in handler and type(handler["HTTPS"]) is not bool:
                raise ValueError("Invalid HTTPS listener flag")
        for origin, enabled in mapping(config.get("AllowFunnel", {}), "Funnel policy").items():
            if type(enabled) is not bool:
                raise ValueError("Invalid Funnel policy")
            parsed = urlsplit("https://" + text(origin, "Serve origin"))
            if enabled:
                public.add(port(parsed.port))
        for origin, web in mapping(config.get("Web", {}), "web listeners").items():
            parsed = urlsplit("https://" + text(origin, "Serve origin"))
            listen = port(parsed.port)
            ports.add(listen)
            handlers = mapping(mapping(web, "web handler").get("Handlers"), "HTTP handlers")
            if not foreground or "/" not in handlers:
                continue
            handler = mapping(handlers["/"], "root handler")
            if tcp.get(str(listen), {}).get("HTTPS") is not True:
                continue  # Plain HTTP sessions still reserve their ports.
            if "Proxy" in handler and "Path" in handler:
                raise ValueError("Ambiguous foreground handler")
            if "Proxy" in handler and "Path" not in handler:
                destination = Target("proxy", text(handler["Proxy"], "proxy target"))
            elif "Path" in handler and "Proxy" not in handler:
                destination = Target("path", text(handler["Path"], "file target"))
            else:
                continue  # Other foreground tools can legitimately serve text.
            if listen in targets:
                raise ValueError("Several foreground routes claim the same port")
            targets[listen] = destination
    return ServeView(frozenset(ports), {p: t for p, t in targets.items() if p not in public})


def serve():
    return decode_serve(loads(command("tailscale", "serve", "status", "--json")))


def hostname():
    raw = mapping(loads(command("tailscale", "status", "--json")), "Tailscale status")
    if raw.get("BackendState") != "Running" or mapping(raw.get("Self"), "node").get("Online") is not True:
        raise RuntimeError("Tailscale is offline; connect it before opening a preview")
    value = text(raw["Self"].get("DNSName"), "Tailscale DNS name").removesuffix(".")
    if not re.fullmatch(r"[a-z0-9-]+\.[a-z0-9-]+\.ts\.net", value):
        raise ValueError("No supported Tailscale HTTPS name; check MagicDNS and HTTPS setup")
    return value


@dataclass(frozen=True)
class Unit:
    loaded: bool
    active: bool
    description: str
    transient: bool


def unit(link: Link):
    output = command("systemctl", "--user", "show", link.unit,
                     "--property=LoadState,ActiveState,Description,Transient", missing_ok=True)
    fields = {}
    for line in output.splitlines():
        key, separator, value = line.partition("=")
        if not separator or key in fields:
            raise ValueError("Invalid systemd unit response")
        fields[key] = value
    if set(fields) != {"LoadState", "ActiveState", "Description", "Transient"}:
        raise RuntimeError("Cannot query user services; check the systemd user manager")
    if fields["Transient"] not in {"yes", "no"}:
        raise ValueError("Invalid transient service state")
    if fields["LoadState"] not in {"loaded", "not-found"}:
        raise RuntimeError("Preview unit has an unexpected load state")
    if fields["ActiveState"] not in {"active", "activating", "reloading", "inactive",
                                    "failed", "deactivating", "maintenance"}:
        raise ValueError("Invalid service activity state")
    active = fields["ActiveState"] in {"active", "activating", "reloading"}
    return Unit(fields["LoadState"] == "loaded", active,
                fields["Description"], fields["Transient"] == "yes")


def check_owner(link: Link, state: Unit):
    if state.loaded and (state.description != link.description or not state.transient):
        raise RuntimeError("Unit ownership changed; refusing to stop or collect it")


def start(link: Link):
    binary = shutil.which("tailscale")
    if binary is None:
        raise RuntimeError("Install tailscale first")
    args = ["systemd-run", "--user", "--no-ask-password", "--quiet", "--collect",
            "--service-type=exec", f"--unit={link.unit}", f"--description={link.description}",
            "--property=TimeoutStopSec=3"]
    if link.expires is not None:
        args.append(f"--property=RuntimeMaxSec={int(link.expires - link.created)}")
    if link.target.kind == "path":
        worker = [sys.executable, "-m", "portlink.static", binary, str(link.port), link.target.value]
    else:
        worker = [binary, "serve", f"--https={link.port}", link.target.value]
    # systemd 249 expands dollars in ExecStart arguments; $$ preserves literal paths.
    command(*args, "--", *(value.replace("$", "$$") for value in worker))


def ready(link: Link, view: ServeView):
    destination = view.foreground.get(link.port)
    if destination is None:
        return False
    if link.target.kind == "proxy":
        return destination == link.target
    if destination.kind != "proxy":
        return False
    parsed = urlsplit(destination.value)
    return (parsed.scheme == "http" and parsed.hostname == "127.0.0.1"
            and parsed.username is None and parsed.password is None and parsed.port is not None
            and parsed.path in {"", "/"} and not parsed.query and not parsed.fragment)


def stop(link: Link):
    state = unit(link)
    check_owner(link, state)
    if state.loaded:
        command("systemctl", "--user", "stop", link.unit)


def backend_ready(destination: Target):
    if destination.kind == "proxy":
        with socket.create_connection(("127.0.0.1", urlsplit(destination.value).port), timeout=2):
            pass


def probe(url, host=None):
    parsed = urlsplit(url)
    connection = (http.client.HTTPSConnection if parsed.scheme == "https" else http.client.HTTPConnection)(
        parsed.hostname, parsed.port, timeout=5)
    try:
        connection.request("HEAD", "/", headers={"Host": host} if host else {})
        status = connection.getresponse().status
        if status >= 500 and status != 501:
            raise RuntimeError(f"HTTP {status}: check the app and reverse-proxy configuration")
        if status in {400, 403, 421}:
            raise RuntimeError(f"HTTP {status}: check the app's allowed Host/Origin for this preview URL")
        return status
    finally:
        connection.close()
