"""Decode native v2 chat records and explicit image attachments once."""

import json
import math

from .media import ImageBudget, native_image
from .models import Activity, Message, decode_json, fields, text


def page(value):
    fields(value, ("data", "cursor"))
    fields(value["cursor"], (), ("previous", "next"))
    if type(value["data"]) is not list:
        raise ValueError("Invalid message page")
    for item in value["data"]:
        if type(item) is not dict:
            raise ValueError("Invalid message record")
        text(item["id"], "message id", 200)
    for cursor in value["cursor"].values():
        if cursor is not None:
            text(cursor, "native cursor", 4096)
    return value["data"], value["cursor"].get("previous"), value["cursor"].get("next")


def anchor(cursor, last):
    return json.dumps({"cursor": cursor, "last": last}, separators=(",", ":"))


def decode_anchor(raw):
    value = decode_json(raw)
    fields(value, ("cursor", "last"))
    return text(value["cursor"], "native cursor", 4096), text(value["last"], "message id", 200)


def messages(rows, budget=None):
    budget, result = budget if budget is not None else ImageBudget(), []
    for row in rows:
        kind = row["type"]
        if kind not in ("user", "assistant"):
            continue
        images, notices = [], []

        def image(part):
            if type(part) is not dict:
                raise ValueError("Invalid native attachment")
            mime = text(part["mime"], "attachment MIME", 200)
            if not mime.startswith("image/"):
                notices.append("[Attachment available in the native session.]")
                return
            if "data" in part:
                normalized = {"type": "image", "url": "data:" + mime + ";base64," + part["data"]}
            else:
                normalized = {"type": "image", "url": part["uri"]}
            url = native_image(normalized, budget)
            if url:
                images.append(url)
            else:
                notices.append("[Image unavailable here; open the native session.]")

        if kind == "user":
            body = row["text"]
            if type(body) is not str:
                raise ValueError("Invalid user text")
            files = row.get("files", [])
            if type(files) is not list:
                raise ValueError("Invalid native attachments")
            for part in files:
                image(part)
        else:
            content, texts = row["content"], []
            if type(content) is not list:
                raise ValueError("Invalid assistant content")
            for part in content:
                if type(part) is not dict:
                    raise ValueError("Invalid assistant block")
                if part["type"] == "text":
                    if type(part["text"]) is not str:
                        raise ValueError("Invalid assistant text")
                    texts.append(part["text"])
                elif part["type"] == "tool" and part["state"]["status"] == "completed":
                    for output in part["state"]["content"]:
                        if output["type"] == "file":
                            image(output)
            body = "\n\n".join(texts)
        if body or images or notices:
            result.append(Message(row["id"], kind, "\n\n".join([body, *notices]).strip(),
                                  images=images or None))
    return result


def projection(rows):
    """Keep tool events at their native content-block boundary, including streaming updates."""
    result, activity, timeline, budget = [], [], [], ImageBudget()
    for row in rows:
        if row["type"] != "assistant" or not any(p["type"] == "tool" for p in row["content"]):
            decoded = messages([row], budget)
            result.extend(decoded)
            timeline.extend(message.id for message in decoded)
            continue
        pending, start = [], 0

        def flush(parts, offset):
            identifier = row["id"] if offset == 0 and parts and parts[0]["type"] != "tool" else (
                row["id"] + ":block:" + str(offset))
            decoded = messages([{**row, "id": identifier, "content": parts}], budget)
            result.extend(decoded)
            timeline.extend(message.id for message in decoded)

        for index, part in enumerate(row["content"]):
            if part["type"] != "tool":
                pending.append(part)
                continue
            flush(pending, start)
            pending, start = [], index + 1
            identifier = "activity:" + row["id"] + ":" + text(part["id"], "tool id", 200)
            label = text(part["name"], "tool name", 200)
            status = {"streaming": "running", "running": "running", "completed": "completed",
                      "error": "failed"}.get(part["state"]["status"])
            if status is None:
                raise ValueError("Unknown native tool state")
            time = part["time"]
            if type(time) is not dict or any(type(v) not in (int, float) or not math.isfinite(v)
                                            or v < 0 for v in time.values()):
                raise ValueError("Invalid native tool timestamps")
            duration = None
            if "ran" in time and "completed" in time:
                if time["completed"] < time["ran"]:
                    raise ValueError("Native tool completion precedes its start")
                duration = time["completed"] - time["ran"]
            activity.append(Activity(identifier, label, status, duration, time.get("ran")))
            timeline.append(identifier)
            flush([part], index)
        flush(pending, start)
    return result, activity, timeline
