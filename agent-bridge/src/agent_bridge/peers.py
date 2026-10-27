"""Peer delivery records live beside existing message text, in each job's event log."""

import os
import re

from .core import SECRET_ENV
from .status_inputs import timestamp
from .status_model import PeerMessage

PREVIEW_LIMIT = 160


def preview(text):
    if any(ord(c) < 32 and c not in "\n\r\t" or ord(c) == 127 for c in text):
        return None
    # A secret-like label is enough to omit the entire preview; don't guess where its value ends.
    if any(SECRET_ENV.search(word) for word in re.findall(r"[A-Za-z_][A-Za-z_0-9]*", text)):
        return None
    if re.search(r"(?i)bearer\s|-----BEGIN|\b(?:sk-|gh[pousr]_|github_pat_|AIza)", text):
        return None
    for name, value in os.environ.items():
        if SECRET_ENV.search(name) and value and value in text:
            return None
    return " ".join(text.split())[:PREVIEW_LIMIT]


def fields(job, peer, text):
    return {
        "source": f"{job.parent.name}/{job.name}",
        "target": f"{job.parent.name}/{peer}",
        "to": peer,
        "message_kind": "steer",
        "size": len(text.encode("utf-8")),
        "preview": preview(text),
    }


def decode(event, identity, source, nodes):
    """Legacy peer_sent rows lack size/time contracts: leave them as ordinary history."""
    if event.get("kind") != "peer_sent" or "source" not in event:
        return None
    target = event.get("target")
    if (
        event["source"] != source
        or target not in nodes
        or target == source
        or target.split("/")[0] != source.split("/")[0]
        or type(event.get("size")) is not int
        or event["size"] < 0
        or event.get("message_kind") != "steer"
        or event.get("preview") is not None
        and (type(event["preview"]) is not str or len(event["preview"]) > PREVIEW_LIMIT)
    ):
        raise ValueError("invalid peer event")
    timestamp(event.get("at"))
    text = event.get("preview")
    return PeerMessage(
        identity,
        source,
        target,
        event["at"],
        event["message_kind"],
        event["size"],
        preview(text) if text is not None else None,
    )
