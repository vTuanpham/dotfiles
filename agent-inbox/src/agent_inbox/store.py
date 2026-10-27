"""Private pairing, root registry and duplicate-safe submission receipts."""

import hashlib
import json
import os
import secrets
import sqlite3
import time
import uuid
from contextlib import contextmanager
from dataclasses import asdict
from pathlib import Path
from typing import Literal, get_args

from .models import PairingError, Target, decode_json, text

ReceiptStatus = Literal[
    "sending", "queued", "steered", "forwarded", "completed", "applied", "unknown", "failed",
    "already_answered", "no_longer_pending",
]


def receipt_status(value) -> ReceiptStatus:
    if type(value) is not str or value not in get_args(ReceiptStatus):
        raise ValueError("Invalid submission status")
    return value


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def binding(target):
    return digest(json.dumps([target.adapter, target.harness, target.session_id, target.settings],
                             sort_keys=True))


class Store:
    def __init__(self, home):
        self.home = Path(home)
        self.home.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.home.chmod(0o700)
        self.path = self.home / "inbox.sqlite3"
        descriptor = os.open(self.path, os.O_CREAT | os.O_RDWR, 0o600)
        os.close(descriptor)
        self.path.chmod(0o600)
        with self.connection() as db:
            version = db.execute("PRAGMA user_version").fetchone()[0]
            if version not in (0, 1, 2, 3):
                raise ValueError("Unsupported inbox database version")
            db.executescript("""
                CREATE TABLE IF NOT EXISTS targets
                    (id TEXT PRIMARY KEY, binding TEXT UNIQUE NOT NULL, data TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS devices
                    (id TEXT PRIMARY KEY, name TEXT NOT NULL, hash TEXT NOT NULL, created REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS pairing
                    (id INTEGER PRIMARY KEY CHECK(id=1), hash TEXT NOT NULL, expires REAL NOT NULL,
                     attempts INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS receipts
                    (id TEXT PRIMARY KEY, target TEXT NOT NULL, hash TEXT NOT NULL,
                     status TEXT NOT NULL, created REAL NOT NULL);
            """)
            db.execute("BEGIN IMMEDIATE")
            if "operation" not in {row[1] for row in db.execute("PRAGMA table_info(receipts)")}:
                db.execute("ALTER TABLE receipts ADD COLUMN operation TEXT NOT NULL DEFAULT 'send'")
            columns = {row[1] for row in db.execute("PRAGMA table_info(receipts)")}
            for column in ("subject", "original"):
                if column not in columns:
                    db.execute(f"ALTER TABLE receipts ADD COLUMN {column} TEXT")
            if "encoding" not in columns:
                db.execute("ALTER TABLE receipts ADD COLUMN encoding INTEGER NOT NULL DEFAULT 1")
            db.execute("CREATE INDEX IF NOT EXISTS receipt_subject ON receipts(target,subject) "
                       "WHERE operation='answer' AND original IS NULL")
            db.execute("PRAGMA user_version=3")

    @contextmanager
    def connection(self):
        db = sqlite3.connect(self.path, timeout=10)
        try:
            with db:
                yield db
        finally:
            db.close()

    def register(self, target):
        key = binding(target)
        with self.connection() as db:
            db.execute("INSERT OR IGNORE INTO targets VALUES (?, ?, ?)",
                       (target.id, key, json.dumps(asdict(target))))
            row = db.execute("SELECT data FROM targets WHERE binding=?", (key,)).fetchone()
        if row is None:
            raise ValueError("Root id was used for a different session")
        return Target.decode(decode_json(row[0]))

    def remove(self, target_id):
        with self.connection() as db:
            db.execute("DELETE FROM targets WHERE id=?", (target_id,))

    def targets(self):
        with self.connection() as db:
            return [Target.decode(decode_json(row[0])) for row in db.execute("SELECT data FROM targets")]

    def target(self, target_id):
        with self.connection() as db:
            row = db.execute("SELECT data FROM targets WHERE id=?", (target_id,)).fetchone()
        if row is None:
            raise ValueError("Unknown root session")
        return Target.decode(decode_json(row[0]))

    def pair_code(self):
        code = secrets.token_hex(5).upper()
        with self.connection() as db:
            db.execute("INSERT OR REPLACE INTO pairing VALUES (1, ?, ?, 0)",
                       (digest(code), time.time() + 300))
        return code

    def pair(self, code, name):
        text(code, "pairing code", 32)
        text(name, "device name", 60)
        device, token = uuid.uuid4().hex, secrets.token_urlsafe(32)
        accepted = False
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT hash, expires, attempts FROM pairing WHERE id=1").fetchone()
            if row and row[1] > time.time() and row[2] < 8:
                db.execute("UPDATE pairing SET attempts=attempts+1 WHERE id=1")
                if secrets.compare_digest(row[0], digest(code)):
                    db.execute("DELETE FROM pairing")
                    db.execute("INSERT INTO devices VALUES (?, ?, ?, ?)",
                               (device, name, digest(token), time.time()))
                    accepted = True
        if not accepted:
            raise PairingError("Pairing code is invalid or expired")
        return device, token

    def authenticated(self, token):
        if not token:
            return False
        with self.connection() as db:
            return db.execute("SELECT 1 FROM devices WHERE hash=? AND created>?",
                              (digest(token), time.time() - 2592000)).fetchone() is not None

    def devices(self):
        with self.connection() as db:
            return list(db.execute("SELECT id, name FROM devices ORDER BY created"))

    def revoke(self, device_id):
        with self.connection() as db:
            db.execute("DELETE FROM devices WHERE id=?", (device_id,))

    def recover(self):
        with self.connection() as db:
            db.execute("UPDATE receipts SET status='unknown' WHERE status='sending'")

    def reserve(self, message_id, target_id, message, operation="send", subject=None, legacy_message=None):
        if operation not in ("send", "command", "answer"):
            raise ValueError("Unknown receipt operation")
        if subject is not None:
            if operation != "answer":
                raise ValueError("Only answers can claim a pending request")
            text(subject, "question id", 200)
        try:
            if str(uuid.UUID(message_id)) != message_id:
                raise ValueError
        except (ValueError, AttributeError):
            raise ValueError("Invalid message id") from None
        fingerprint = digest(message)
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT target, hash, status, operation, subject, original, encoding "
                             "FROM receipts WHERE id=?",
                             (message_id,)).fetchone()
            if row:
                if type(row[6]) is not int or row[6] not in (1, 2):
                    raise ValueError("Invalid receipt encoding")
                matches = row[1] == fingerprint or (
                    row[6] == 1 and legacy_message is not None and row[1] == digest(legacy_message)
                )
                if (row[0] != target_id or not matches or row[3] != operation
                        or row[4] is not None and row[4] != subject):
                    raise ValueError("Message id was used for different content or a different root")
                if row[6] == 1 and legacy_message is not None:
                    db.execute("UPDATE receipts SET hash=?, encoding=2 WHERE id=?", (fingerprint, message_id))
                if operation == "answer" and row[4] is None and subject is not None:
                    # Old receipts contain the form in their hash; bind it on an exact replay only.
                    db.execute("UPDATE receipts SET subject=? WHERE id=?", (subject, message_id))
                if row[5] is not None:
                    original = db.execute(
                        "SELECT status FROM receipts WHERE id=? AND original IS NULL "
                        "AND operation='answer' AND target=? AND subject=?",
                        (row[5], target_id, subject),
                    ).fetchone()
                    if original is None:
                        raise ValueError("Missing original answer receipt")
                    state = receipt_status(original[0])
                    return False, "already_answered" if state == "applied" else state
                return False, receipt_status(row[2])
            original, state = None, "sending"
            if subject is not None:
                previous = db.execute(
                    "SELECT id, status FROM receipts WHERE target=? AND subject=? "
                    "AND operation='answer' AND original IS NULL AND status!='failed' "
                    "ORDER BY created LIMIT 1", (target_id, subject),
                ).fetchone()
                if previous:
                    original, state = previous[0], receipt_status(previous[1])
            db.execute("INSERT INTO receipts "
                       "(id,target,hash,status,created,operation,subject,original,encoding) "
                       "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 2)",
                       (message_id, target_id, fingerprint, state, time.time(), operation,
                        subject, original))
            if original is not None:
                return False, "already_answered" if state == "applied" else state
        return True, "sending"

    def finish(self, message_id, status):
        receipt_status(status)
        if status in ("sending", "already_answered"):
            raise ValueError("Invalid submission status")
        with self.connection() as db:
            db.execute("UPDATE receipts SET status=? WHERE id=?", (status, message_id))
