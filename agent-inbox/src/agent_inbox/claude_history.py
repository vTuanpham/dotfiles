"""A strict projection of the SDK's documented SessionMessage boundary."""

import json
import xml.etree.ElementTree as ElementTree

from .media import ImageBudget, native_image
from .models import Activity, Message, decode_json, fields, text


def cursor(raw):
    value = decode_json(raw)
    fields(value, ("offset", "anchor"))
    if type(value["offset"]) is not int or value["offset"] < 0:
        raise ValueError("Invalid native history offset")
    text(value["anchor"], "native history anchor", 200)
    return value["offset"], value["anchor"]


def encode_cursor(offset, identifier):
    return json.dumps({"offset": offset, "anchor": identifier}, separators=(",", ":"))


def channel_message(body):
    if not body.startswith('<channel source="agent-inbox" '):
        return None
    opening, separator, content = body.partition(">")
    if not separator or not content.rstrip().endswith("</channel>"):
        return None
    try:
        element = ElementTree.fromstring(opening + "></channel>")
        return element.attrib.get("message_id"), content.rstrip()[:-len("</channel>")].strip()
    except ElementTree.ParseError:
        return None


def decode(rows, session_id, outgoing=(), append_outgoing=True):
    budget, messages, activity, timeline = ImageBudget(), [], [], []
    sent = {message["id"]: message for message in outgoing}
    seen = set()
    for row in rows:
        if row["session_id"] != session_id:
            raise ValueError("SDK message belongs to another session")
        if row.get("parent_tool_use_id") is not None or row.get("parent_agent_id") is not None:
            continue
        if row["type"] not in ("user", "assistant") or type(row["message"]) is not dict:
            raise ValueError("Invalid SDK message")
        identifier = "claude:" + text(row["uuid"], "message id", 200)
        content = row["message"]["content"]
        if type(content) is str:
            content = [{"type": "text", "text": content}]
        if type(content) is not list:
            raise ValueError("Invalid SDK content")
        body, images, tool_result = [], [], False

        def image(part):
            source = part.get("source")
            if type(source) is not dict or source.get("type") != "base64":
                body.append("[Image unavailable here; open the native session.]")
                return
            url = native_image({"type": "image", "url": "data:"
                                + text(source["media_type"], "image MIME", 100)
                                + ";base64," + source["data"]}, budget)
            if url:
                images.append(url)
            else:
                body.append("[Image unavailable here; open the native session.]")

        for block in content:
            if type(block) is not dict:
                raise ValueError("Invalid SDK content block")
            if block["type"] == "text":
                if type(block["text"]) is not str:
                    raise ValueError("Invalid SDK text")
                channel = channel_message(block["text"]) if row["type"] == "user" else None
                reference = channel[0] if channel else None
                if reference in sent:
                    message = sent[reference]
                    identifier = "channel:" + reference
                    body.append(message["text"])
                    for url in message["images"]:
                        normalized = native_image({"type": "image", "url": url}, budget)
                        if normalized:
                            images.append(normalized)
                    seen.add(reference)
                else:
                    body.append(channel[1] if channel else block["text"])
            elif block["type"] == "image":
                image(block)
            elif block["type"] == "tool_result":
                tool_result = True
                outputs = block.get("content", [])
                if type(outputs) is list:
                    for part in outputs:
                        if type(part) is dict and part.get("type") == "image":
                            image(part)
            elif block["type"] == "tool_use":
                activity_id = "activity:claude:" + text(block["id"], "tool call id", 200)
                activity.append(Activity(activity_id, text(block["name"], "tool name", 200), "observed"))
                timeline.append(activity_id)
        if body or images:
            messages.append(Message(identifier, "assistant" if tool_result else row["type"],
                                    "\n\n".join(body), images=images or None))
            timeline.append(identifier)
    for identifier, message in (sent.items() if append_outgoing else ()):
        if identifier in seen or message.get("status") != "forwarded":
            continue
        images = [image for url in message["images"]
                  if (image := native_image({"type": "image", "url": url}, budget))]
        messages.append(Message("channel:" + identifier, "user", message["text"], images=images or None))
        timeline.append("channel:" + identifier)
    return messages, activity, timeline
