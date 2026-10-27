import json
import re
from dataclasses import asdict
from http.cookies import CookieError, SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import BoundedSemaphore
from urllib.parse import parse_qs, urlsplit

from .adapters import adapter
from .catalog import Catalog
from .commands import catalog
from .context import context
from .forms import forms
from .media import MediaCache, decode_images
from .models import DeliveryRejected, NoLongerPending, Outgoing, PairingError, decode_json, fields, text
from .presentation import render_forms, render_snapshot

ASSETS = {"/": ("index.html", "text/html"), "/app.js": ("app.js", "text/javascript"),
          "/controls.js": ("controls.js", "text/javascript"), "/mark.svg": ("mark.svg", "image/svg+xml"),
          "/kit.js": ("kit.js", "text/javascript"), "/context.js": ("context.js", "text/javascript"),
          "/forms.js": ("forms.js", "text/javascript"),
          "/style.css": ("style.css", "text/css")}


class App:
    def __init__(self, store):
        self.store = store
        self.catalog = Catalog(store)
        self.media = MediaCache()

    def dispatch(self, data, fingerprint, prepare, successes, operation="send", subject=None,
                 legacy_fingerprint=None):
        identifier = text(data["target"], "root id", 200)
        fresh, state = self.store.reserve(data["id"], identifier, fingerprint, operation, subject,
                                         legacy_fingerprint)
        if fresh:
            try:
                perform = prepare(self.catalog.target(identifier))
            except NoLongerPending:
                state = "no_longer_pending"
            except Exception:
                state = "failed"
            else:
                try:
                    state = perform()
                    if state not in successes:
                        raise RuntimeError("Unrecognized native receipt")
                except NoLongerPending:
                    state = "no_longer_pending"
                except DeliveryRejected:
                    state = "failed"
                except Exception:  # Native dispatch may have succeeded before a connection failed.
                    state = "unknown"
            self.store.finish(data["id"], state)
        return {"id": data["id"], "status": state}

    def send(self, data):
        fields(data, ("id", "target", "text"), ("images", "delivery"))
        delivery = data.get("delivery", "queue")
        if type(delivery) is not str or delivery not in ("queue", "steer"):
            raise ValueError("Invalid delivery mode")
        images = decode_images(data.get("images", []))
        body = data["text"]
        if not images or body != "":
            text(body, "message")
        message = Outgoing(data["id"], body, images, delivery)
        legacy = json.dumps([body, images], separators=(",", ":")) if images else body
        if delivery == "steer":
            legacy = None
        fingerprint = json.dumps(["send", body, images, delivery], separators=(",", ":"))

        def prepare(target):
            provider = adapter(target)
            if delivery == "steer" and not provider.capabilities.mid_turn_steering:
                raise DeliveryRejected("This connection does not support mid-turn steering")
            if images and not provider.capabilities.images:
                raise DeliveryRejected("This connection does not support images")
            if not provider.snapshot(target).can_send:
                raise DeliveryRejected("This session is not accepting input")
            return lambda: provider.send(target, message)

        return self.dispatch(data, fingerprint, prepare, ("queued", "steered", "forwarded", "completed"),
                             legacy_fingerprint=legacy)

    def command(self, data):
        fields(data, ("id", "target", "command", "value"))
        command = text(data["command"], "command id", 200)
        if type(data["value"]) is not str or len(data["value"]) > 16384 or "\0" in data["value"]:
            raise ValueError("Invalid command argument")
        fingerprint = json.dumps(["command", command, data["value"]], separators=(",", ":"))

        def prepare(target):
            provider = adapter(target)
            catalog(provider, target).selected(command, data["value"])
            return lambda: provider.execute(target, command, data["value"])

        return self.dispatch(data, fingerprint, prepare, ("applied",), "command")

    def answer(self, data):
        fields(data, ("id", "target", "form", "answer"), ("cancel",))
        identifier = text(data["form"], "question id", 200)
        cancel = data.get("cancel", False)
        if type(cancel) is not bool or type(data["answer"]) is not dict or cancel and data["answer"]:
            raise ValueError("Invalid question reply")
        fingerprint = json.dumps(["answer", identifier, data["answer"], cancel],
                                 sort_keys=True, separators=(",", ":"))

        def prepare(target):
            provider = adapter(target)
            if not provider.capabilities.questions:
                raise DeliveryRejected("This connection cannot answer native requests")
            question = forms(provider, target).selected(identifier)
            if not cancel:
                question.validate(data["answer"])
            return lambda: provider.answer(target, identifier, data["answer"], cancel)

        return self.dispatch(data, fingerprint, prepare, ("applied",), "answer", identifier)


class Server(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, app, port, public_url=""):
        self.app = app
        self.assets = Path(__file__).parent
        self.capacity = BoundedSemaphore(8)
        self.origins = set()
        super().__init__(("127.0.0.1", port), Handler)
        actual = self.server_address[1]
        self.origins.update((f"http://127.0.0.1:{actual}", f"http://localhost:{actual}"))
        if public_url:
            parsed = urlsplit(public_url)
            if (parsed.scheme not in ("https", "http") or not parsed.hostname
                    or parsed.username or parsed.password or parsed.path not in ("", "/")
                    or parsed.query or parsed.fragment):
                self.server_close()
                raise ValueError("public_url must be an HTTP(S) origin without credentials or a path")
            self.origins.add(public_url.rstrip("/"))
        self.hosts = {urlsplit(origin).netloc for origin in self.origins}

    def process_request(self, request, client_address):
        if not self.capacity.acquire(blocking=False):
            request.close()
            return
        try:
            super().process_request(request, client_address)
        except BaseException:
            self.capacity.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self.capacity.release()


class Handler(BaseHTTPRequestHandler):
    server: Server

    def setup(self):
        super().setup()
        self.connection.settimeout(10)

    def log_message(self, *args):
        pass  # no URLs, pairing data or conversation content in HTTP logs

    def response(self, status, value, content_type="application/json", cookie=None):
        body = json.dumps(value).encode() if content_type == "application/json" else value
        self.send_response(status)
        mime = content_type if content_type.startswith("image/") else content_type + "; charset=utf-8"
        for key, item in {
            "Content-Type": mime,
            "Content-Length": str(len(body)),
            "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff",
            "Referrer-Policy": "no-referrer",
            "Content-Security-Policy": (
                "default-src 'self'; img-src 'self' data:; frame-ancestors 'none'; "
                "base-uri 'none'; form-action 'self'"
            ),
        }.items():
            self.send_header(key, item)
        if cookie:
            self.send_header("Set-Cookie", cookie)
        self.end_headers()
        self.wfile.write(body)

    def trusted_origin(self):
        hosts = self.headers.get_all("Host", [])
        if len(hosts) != 1 or hosts[0] not in self.server.hosts:
            return False
        origins = self.headers.get_all("Origin", [])
        return (len(origins) == 1 and origins[0] in self.server.origins
                or not origins and self.command == "GET")

    def authenticated(self):
        cookies = SimpleCookie()
        try:
            cookies.load(self.headers.get("Cookie", ""))
        except CookieError:
            return False
        token = cookies["inbox"].value if "inbox" in cookies else ""
        return self.server.app.store.authenticated(token)

    def route(self):
        if not self.trusted_origin():
            return self.response(403, {"error": "Untrusted request origin"})
        parsed = urlsplit(self.path)
        if self.command == "GET" and parsed.path in ASSETS:
            name, mime = ASSETS[parsed.path]
            path = self.server.assets / name
            if not path.is_file():
                return self.response(404, {"error": "Unknown asset"})
            return self.response(200, path.read_bytes(), mime)
        if self.command == "GET" and parsed.path.startswith("/assets/"):
            name = parsed.path[len("/assets/"):]
            if not re.fullmatch(r"[a-zA-Z0-9_-]+\.(svg|png|webp)", name):
                return self.response(404, {"error": "Unknown asset"})
            path = self.server.assets / "assets" / name
            if not path.is_file():
                return self.response(404, {"error": "Unknown asset"})
            mime = {".svg": "image/svg+xml", ".png": "image/png", ".webp": "image/webp"}[path.suffix]
            return self.response(200, path.read_bytes(), mime)
        if self.command == "POST":
            if self.headers.get("Content-Type", "").split(";")[0] != "application/json":
                return self.response(415, {"error": "JSON required"})
            if self.headers.get("Transfer-Encoding"):
                raise ValueError("Chunked requests are not supported")
            length = self.headers.get_all("Content-Length", [])
            maximum = 12 * 1024 * 1024 if parsed.path == "/api/send" else 65536
            if len(length) != 1 or not length[0].isdigit() or not 0 < int(length[0]) <= maximum:
                raise ValueError("Invalid request length")
            if parsed.path != "/api/pair" and not self.authenticated():
                return self.response(401, {"error": "Pair this device first"})
            raw = self.rfile.read(int(length[0]))
            if len(raw) != int(length[0]):
                raise ValueError("Incomplete request")
            data = decode_json(raw)
            if parsed.path == "/api/pair":
                fields(data, ("code", "name"))
                device, token = self.server.app.store.pair(data["code"], data["name"])
                secure = "; Secure" if self.headers.get("Origin", "").startswith("https://") else ""
                return self.response(200, {"device": device}, cookie=(
                    f"inbox={token}; HttpOnly; SameSite=Strict; Path=/api; Max-Age=2592000{secure}"
                ))
        if not self.authenticated():
            return self.response(401, {"error": "Pair this device first"})
        if self.command == "GET" and parsed.path == "/api/roots":
            return self.response(200, self.server.app.catalog.listing())
        if self.command == "GET" and parsed.path in ("/api/commands", "/api/context", "/api/forms"):
            query = parse_qs(parsed.query, strict_parsing=True, keep_blank_values=True)
            if set(query) != {"id"} or len(query["id"]) != 1:
                raise ValueError("Invalid command catalog query")
            target = self.server.app.catalog.target(query["id"][0])
            read = {"/api/commands": catalog, "/api/context": context, "/api/forms": forms}[parsed.path]
            result = read(adapter(target), target)
            value = render_forms(result) if parsed.path == "/api/forms" else asdict(result)
            if parsed.path == "/api/context":
                origin = next((row.get("origin") for row in self.server.app.catalog.listing()["roots"]
                               if row["id"] == target.id), None)
                value["origin"] = origin
            return self.response(200, value)
        if self.command == "GET" and parsed.path == "/api/image":
            query = parse_qs(parsed.query, strict_parsing=True, keep_blank_values=True)
            if set(query) != {"id"} or len(query["id"]) != 1:
                raise ValueError("Invalid image query")
            identifier = query["id"][0]
            if len(identifier) != 64 or any(c not in "0123456789abcdef" for c in identifier):
                raise ValueError("Invalid image id")
            image = self.server.app.media.get(identifier)
            if image is None:
                return self.response(404, {"error": "Preview expired; reload the conversation"})
            mime, raw = image
            return self.response(200, raw, mime)
        if self.command == "GET" and parsed.path == "/api/view":
            query = parse_qs(parsed.query, strict_parsing=True, keep_blank_values=True)
            if (set(query) - {"id", "cursor", "since"} or any(len(v) != 1 for v in query.values())
                    or "id" not in query or {"cursor", "since"} <= query.keys()):
                raise ValueError("Invalid root query")
            target = self.server.app.catalog.target(query["id"][0])
            cursor = text(query["cursor"][0], "history cursor", 4096) if "cursor" in query else None
            since = text(query["since"][0], "catch-up cursor", 4096) if "since" in query else None
            view = render_snapshot(adapter(target).snapshot(target, cursor, since))
            for message in view["messages"]:
                if message["images"]:
                    message["images"] = [self.server.app.media.publish(target.id, url)
                                         for url in message["images"]]
            return self.response(200, view)
        if self.command == "POST" and parsed.path == "/api/send":
            return self.response(200, self.server.app.send(data))
        if self.command == "POST" and parsed.path == "/api/command":
            return self.response(200, self.server.app.command(data))
        if self.command == "POST" and parsed.path == "/api/answer":
            return self.response(200, self.server.app.answer(data))
        return self.response(404, {"error": "Unknown route"})

    def handle_request(self):
        try:
            self.route()
        except PairingError:
            self.response(403, {"error": "Pairing code is invalid or expired"})
        except (ValueError, KeyError, TypeError):
            self.response(400, {"error": "Invalid request or unsupported session data"})
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception:
            self.response(503, {"error": "Root unavailable; check its native interface"})

    do_GET = handle_request
    do_POST = handle_request
