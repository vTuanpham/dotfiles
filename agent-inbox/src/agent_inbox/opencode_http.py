"""OpenCode's private local service connection; never start or reconfigure it."""

import base64
import http.client
import stat
from pathlib import Path
from urllib.parse import urlencode, urlsplit

from .models import decode_json, fields, text


def location_query(info):
    location = info["location"]
    fields(location, ("directory",))
    return urlencode({"location[directory]": text(location["directory"], "native location", 4096)})


class ApiRejected(RuntimeError):
    def __init__(self, status):
        self.status = status
        super().__init__("OpenCode rejected the request")


class Connection:
    def __init__(self, target):
        fields(target.settings, ("service",))
        path = Path(text(target.settings["service"], "service file", 4096))
        if not path.is_absolute():
            raise ValueError("Absolute service path required")
        info = path.stat()
        if not stat.S_ISREG(info.st_mode) or info.st_size > 65536:
            raise ValueError("Invalid service file")
        data = decode_json(path.read_bytes())
        fields(data, ("url", "password", "version", "pid", "id"))
        parsed = urlsplit(text(data["url"], "service URL", 200))
        if (parsed.scheme != "http" or parsed.hostname != "127.0.0.1"
                or parsed.username or parsed.password or parsed.path or parsed.query or parsed.fragment
                or not parsed.port or type(data["pid"]) is not int or data["pid"] <= 0):
            raise ValueError("Expected a local OpenCode service")
        if data["version"] != "2.2.2":
            raise ValueError("Unsupported OpenCode protocol version")
        password = text(data["password"], "service credential", 1024)
        self.port = parsed.port
        self.headers = {"Authorization": "Basic " + base64.b64encode(
            ("opencode:" + password).encode()).decode()}
        health = self.call("GET", "/api/info")
        fields(health, ("version", "pid", "capabilities", "hostname", "paths", "urls"))
        if (health["version"] != data["version"] or type(health["pid"]) is not int
                or health["pid"] != data["pid"]):
            raise ValueError("OpenCode service identity changed")

    def call(self, method, path, body=None):
        import json

        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=8)
        try:
            headers = {**self.headers, "Content-Type": "application/json"}
            connection.request(method, path, json.dumps(body) if body is not None else None, headers)
            response = connection.getresponse()
            if response.status not in (200, 204):
                raise ApiRejected(response.status)
            if response.status == 204:
                return None
            if response.getheader("Content-Type", "").split(";")[0] != "application/json":
                raise ValueError("Expected native JSON response")
            raw = response.read(24 * 1024 * 1024 + 1)
            if len(raw) > 24 * 1024 * 1024:
                raise ValueError("Native response exceeds the inbox limit")
            return decode_json(raw)
        finally:
            connection.close()
