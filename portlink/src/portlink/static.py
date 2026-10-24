"""Unprivileged static preview; systemd owns this server and its Serve child together."""

import subprocess
import sys
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import quote

from .models import target


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, selected, file_only, **kwargs):
        self.selected = selected
        self.file_only = file_only
        self.root = selected.parent if file_only else selected
        super().__init__(*args, directory=str(self.root), **kwargs)

    def log_message(self, *_):
        pass

    def send_head(self):
        root = self.root
        try:
            resolved = Path(self.translate_path(self.path)).resolve()
        except (ValueError, OSError, RuntimeError):
            self.send_error(400)
            return None
        if self.file_only and resolved == root:
            resolved = self.selected
            self.path = "/" + quote(self.selected.name)
        if resolved.is_dir():
            for filename in ("index.html", "index.htm"):
                if (resolved / filename).is_file():
                    resolved = (resolved / filename).resolve()
                    break
        if (not resolved.is_relative_to(root)
                or any(part.startswith(".") for part in resolved.relative_to(root).parts)
                or self.file_only and resolved != self.selected):
            self.send_error(404)
            return None
        return super().send_head()

    def list_directory(self, _):
        self.send_error(404, "Add an index.html to preview this directory")
        return None


def server(path):
    destination = target(str(path))
    if destination.kind != "path":
        raise ValueError("Static previews require a file or directory")
    selected = Path(destination.value)
    return ThreadingHTTPServer(("127.0.0.1", 0),
                               partial(Handler, selected=selected, file_only=selected.is_file()))


def main():
    binary, listen, path = sys.argv[1:]
    with server(path) as http:
        thread = threading.Thread(target=http.serve_forever, daemon=True)
        thread.start()
        try:
            return subprocess.call([binary, "serve", f"--https={listen}",
                                    f"http://127.0.0.1:{http.server_port}"], stdin=subprocess.DEVNULL)
        finally:
            http.shutdown()
            thread.join(timeout=2)


if __name__ == "__main__":
    sys.exit(main())
