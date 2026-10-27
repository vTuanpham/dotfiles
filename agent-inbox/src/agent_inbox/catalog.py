import json
import time
import uuid
from dataclasses import asdict, replace
from threading import Lock

from .adapters import adapter
from .origin import annotate, read
from .store import binding


class Catalog:
    def __init__(self, store):
        self.store = store
        self.lock = Lock()
        self.checked = None
        self.live = {}
        self.rows = []
        self.warnings = []

    def refresh(self):
        with self.lock:
            if self.checked is not None and time.monotonic() - self.checked < 10:
                return
            registered = {binding(t): t for t in self.store.targets()}
            sources = {}
            for target in registered.values():
                key = (target.adapter, target.harness, json.dumps(target.settings, sort_keys=True))
                sources.setdefault(key, []).append(target)
            live, rows, warnings = {}, [], []
            for seeds in sources.values():
                seed = seeds[0]
                try:
                    provider = adapter(seed)
                    capabilities = asdict(provider.capabilities)
                    discovered = provider.discover(seed)
                except (TimeoutError, ConnectionError):
                    warnings.append(seed.harness + " connection unavailable")
                    if seed.adapter != "claude":
                        # A failed probe is not an authoritative list of closed sessions.
                        for identifier, previous in self.live.items():
                            if (previous.adapter, previous.harness, previous.settings) == (
                                seed.adapter, seed.harness, seed.settings,
                            ):
                                live[identifier] = previous
                                row = next(row for row in self.rows if row["id"] == identifier)
                                rows.append({**row, "status": "unknown", "stale": True})
                    continue
                except Exception:
                    warnings.append(seed.harness + " connection unavailable")
                    continue
                if discovered is None:
                    for target in seeds:
                        live[target.id] = target
                        rows.append({**target.public(), "status": "native", "capabilities": capabilities})
                    continue
                for info in discovered:
                    target = replace(seed, session_id=info.session_id, label=info.label)
                    key = binding(target)
                    configured = registered.get(key)
                    target = replace(target, id=configured.id if configured else uuid.uuid5(
                        uuid.NAMESPACE_URL, key).hex)
                    if target.id in live:
                        raise ValueError("Duplicate discovered root")
                    live[target.id] = target
                    rows.append({**target.public(), "status": info.status, "saved": info.saved,
                                 "capabilities": capabilities})
            annotate(live, rows, read())
            registered_ids = {t.id for t in registered.values()}
            rows.sort(key=lambda row: (row["id"] not in registered_ids,
                                       row["label"].casefold(), row["id"]))
            self.live, self.rows, self.warnings = live, rows, warnings
            self.checked = time.monotonic()

    def listing(self):
        self.refresh()
        with self.lock:
            return {"roots": list(self.rows), "warnings": list(self.warnings)}

    def target(self, identifier):
        self.refresh()
        with self.lock:
            target = self.live.get(identifier)
        if target is None:
            raise ValueError("Root is offline or unavailable")
        return target
