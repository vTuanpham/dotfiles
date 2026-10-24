"""Human and machine interfaces to the same private preview lifecycle."""

import argparse
import http.client
import json
import os
import socket
import subprocess
import sys
import time
from urllib.parse import urlsplit

import segno

from . import backend
from .core import Store
from .models import duration


def remaining(link):
    if link.expires is None:
        return "until closed"
    seconds = max(0, int(link.expires - time.time()))
    return f"{seconds // 60}m" if seconds >= 60 else f"{seconds}s"


def show(link, store, machine=False):
    if machine:
        print(json.dumps({**link.encode(), "private": True, "qr": str(store.qr(link))}))
        return
    print(f"{link.name} · Private · {remaining(link)}\n{link.url}")
    if sys.stdout.isatty():
        segno.make_qr(link.url).terminal(compact=True)
    print(f"QR: {store.qr(link)}")


def doctor(store, label, machine):
    checks = []

    def check(title, action):
        try:
            detail = str(action())
            checks.append({"check": title, "ok": True, "detail": detail})
        except (OSError, ValueError, RuntimeError, http.client.HTTPException,
                subprocess.SubprocessError) as error:
            checks.append({"check": title, "ok": False, "detail": str(error)})

    check("Tailscale", backend.hostname)
    check("User services", lambda: backend.command(
        "systemctl", "--user", "show", "--property=Version").strip())
    check("Serve config", lambda: f"{len(backend.serve().ports)} occupied ports")
    if label:
        links = store.list()
        link = next((item for item in links if item.name == label), None)
        if link is None:
            raise ValueError("No active preview with that name")
        if link.target.kind == "proxy":
            check("Local app", lambda: backend.probe(link.target.value, host=urlsplit(link.url).netloc))
        check("Host DNS", lambda: socket.getaddrinfo(urlsplit(link.url).hostname, None) and "resolved")
        check("HTTPS", lambda: f"HTTP {backend.probe(link.url)}")
    if machine:
        print(json.dumps(checks))
    else:
        for item in checks:
            print(f"{'✓' if item['ok'] else '✗'} {item['check']} · {item['detail']}")
    return int(any(not item["ok"] for item in checks))


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(
        prog="portlink", description="Private, expiring links to local previews.",
        epilog="Phone and host need Tailscale. Links expire after 1h by default; use open --ttl or --keep.")
    sub = parser.add_subparsers(dest="command", required=True)
    opening = sub.add_parser("open", help="share a local HTTP port, file or directory")
    opening.add_argument("target")
    opening.add_argument("--name")
    opening.add_argument("--listen", type=int, help="fixed HTTPS port; refuses occupied ports")
    lifetime = opening.add_mutually_exclusive_group()
    lifetime.add_argument("--ttl", type=duration, default=3600, help="default 1h; accepts 30s, 15m, 2h")
    lifetime.add_argument("--keep", action="store_true",
                          help="no expiry; lasts until closed or host shutdown")
    closing = sub.add_parser("close", help="stop only the named preview's process and remove its state")
    closing.add_argument("name")
    listing = sub.add_parser("list", help="list managed previews and collect expired records")
    qr = sub.add_parser("qr", help="show the URL and QR for an existing preview")
    qr.add_argument("name")
    checking = sub.add_parser("doctor", help="check Tailscale, services and optionally a preview's access")
    checking.add_argument("name", nargs="?")
    for child in (opening, closing, listing, qr, checking):
        child.add_argument("--json", action="store_true", help="machine-readable output")
    args = parser.parse_args()
    store = Store()
    try:
        if args.command == "open":
            link = store.open(args.target, args.name, args.listen, None if args.keep else args.ttl)
            show(link, store, args.json)
        elif args.command == "close":
            link = store.close(args.name)
            print(json.dumps({"closed": link.name}) if args.json else f"Closed {link.name}")
        elif args.command == "list":
            links = store.list()
            if args.json:
                print(json.dumps([link.encode() for link in links]))
            else:
                for link in links:
                    print(f"{link.name:24} {remaining(link):14} {link.url}")
        elif args.command == "qr":
            link = next((item for item in store.list() if item.name == args.name), None)
            if link is None:
                raise ValueError("No active preview with that name")
            show(link, store, args.json)
        else:
            return doctor(store, args.name, args.json)
        return 0
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        print(f"portlink: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
