"""Decode user input and private records once, before lifecycle operations."""

import json
import math
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from urllib.parse import urlsplit


def text(value, label):
    if (not isinstance(value, str) or not value or len(value) > 4096
            or any(ord(char) < 32 or ord(char) == 127 for char in value)):
        raise ValueError(f"Invalid {label}")
    return value


def name(value):
    if not isinstance(value, str) or not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,47}", value):
        raise ValueError("Name must be 1–48 lowercase letters, digits, hyphens or underscores")
    return value


def port(value):
    if type(value) is not int or not 1 <= value <= 65535:
        raise ValueError("Port must be an integer from 1 to 65535")
    return value


def duration(value):
    match = re.fullmatch(r"([1-9][0-9]{0,5})(s|m|h|d)", value)
    if match is None:
        raise ValueError("Use a positive duration such as 30s, 15m or 1h")
    return int(match[1]) * {"s": 1, "m": 60, "h": 3600, "d": 86400}[match[2]]


def loads(data):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("Duplicate JSON field")
            result[key] = value
        return result

    def constant(_):
        raise ValueError("Non-finite JSON number")

    return json.loads(data, object_pairs_hook=pairs, parse_constant=constant)


@dataclass(frozen=True)
class Target:
    kind: str
    value: str


def target(value):
    text(value, "target")
    if re.fullmatch(r"[0-9]+", value):
        return Target("proxy", f"http://127.0.0.1:{port(int(value))}")
    if "://" in value:
        parsed = urlsplit(value)
        if (parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost"}
                or parsed.username is not None or parsed.password is not None
                or parsed.path not in {"", "/"} or parsed.query or parsed.fragment):
            raise ValueError("Use a loopback HTTP origin or a local port")
        return Target("proxy", f"http://127.0.0.1:{port(parsed.port)}")
    path = Path(value).expanduser().resolve(strict=True)
    if not (path.is_file() or path.is_dir()) or path in {Path("/"), Path.home()}:
        raise ValueError("Select a file or preview directory, not the filesystem root or home directory")
    return Target("path", text(str(path), "path"))


@dataclass(frozen=True)
class Link:
    id: str
    name: str
    url: str
    target: Target
    port: int
    created: float
    expires: float | None

    @property
    def unit(self):
        return f"portlink-{self.id}.service"

    @property
    def description(self):
        return f"portlink:{self.id}"

    def encode(self):
        return {"version": 1, **asdict(self)}


def decode_link(raw):
    if type(raw) is not dict or set(raw) != {"version", "id", "name", "url", "target", "port",
                                           "created", "expires"}:
        raise ValueError("Invalid preview record fields")
    if type(raw["version"]) is not int or raw["version"] != 1:
        raise ValueError("Unsupported preview record version")
    if not isinstance(raw["id"], str) or not re.fullmatch(r"[0-9a-f]{32}", raw["id"]):
        raise ValueError("Invalid preview identity")
    value = raw["target"]
    if type(value) is not dict or set(value) != {"kind", "value"}:
        raise ValueError("Invalid preview target")
    target_value = text(value["value"], "target")
    if value["kind"] == "proxy":
        if target(target_value) != Target("proxy", target_value):
            raise ValueError("Noncanonical proxy target")
    elif value["kind"] != "path" or not Path(target_value).is_absolute():
        raise ValueError("Invalid saved target")
    created, expires = raw["created"], raw["expires"]
    if type(created) not in {int, float} or not math.isfinite(created) or created <= 0:
        raise ValueError("Invalid creation time")
    if expires is not None and (type(expires) not in {int, float}
                                or not math.isfinite(expires) or expires <= created):
        raise ValueError("Invalid expiry time")
    parsed = urlsplit(text(raw["url"], "URL"))
    listen = port(raw["port"])
    if (parsed.scheme != "https" or not parsed.hostname or not parsed.hostname.endswith(".ts.net")
            or parsed.username is not None or parsed.password is not None or parsed.query or parsed.fragment
            or parsed.path or (parsed.port or 443) != listen):
        raise ValueError("Invalid private preview origin")
    return Link(raw["id"], name(raw["name"]), raw["url"], Target(**value), listen, created, expires)
