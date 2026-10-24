import shlex
from dataclasses import dataclass, field
from pathlib import PurePath

from .media import MAX_BYTES, ImageBudget, native_image
from .models import Activity, Answer, Message, decode_json, fields, text

REPLY_OPEN = "<send_user_message_question_reply>"
REPLY_CLOSE = "</send_user_message_question_reply>"


@dataclass(frozen=True)
class Page:
    messages: list[Message]
    identifiers: list[str]
    older: str | None
    newer: str | None
    catching_up: bool = False
    activity: list[Activity] = field(default_factory=list)
    timeline: list[str] = field(default_factory=list)


def command_label(command):
    """Show the executable/subcommand, never inline code, arguments or environment values."""
    if type(command) is not str:
        raise ValueError("Invalid native command")
    lexer = shlex.shlex(command, posix=True)
    lexer.whitespace_split, lexer.commenters = True, ""
    try:
        program = next(lexer, "")
        for _ in range(4):
            if PurePath(program).name not in ("sh", "bash", "zsh", "dash", "ksh"):
                break
            if next(lexer, "") not in ("-c", "-lc", "-ic", "-lic"):
                break
            lexer = shlex.shlex(next(lexer, ""), posix=True)
            lexer.whitespace_split, lexer.commenters = True, ""
            program = next(lexer, "")
        if PurePath(program).name == "rtk":
            program = next(lexer, "")
            if program in ("proxy", "summary", "test", "err"):
                program = next(lexer, "")
        if PurePath(program).name == "uv":
            if next(lexer, "") == "run":
                program = next(lexer, "")
        name = PurePath(program).name
        if not name or "=" in name or len(name) > 100 or any(c.isspace() for c in name):
            return "Terminal command"
        if name in ("git", "gh", "agent-bridge", "systemctl"):
            subcommand = next(lexer, "")
            if subcommand and len(subcommand) < 50 and all(c.isalnum() or c in "_-" for c in subcommand):
                return name + " " + subcommand
        return name
    except ValueError:
        return "Terminal command"


def question_reply(body):
    value = body.strip()
    if not value.startswith(REPLY_OPEN):
        return None
    if not value.endswith(REPLY_CLOSE):
        raise ValueError("Incomplete question reply")
    rows = decode_json(value[len(REPLY_OPEN):-len(REPLY_CLOSE)])
    if type(rows) is not list or not rows:
        raise ValueError("Invalid question reply")
    replies = []
    for row in rows:
        fields(row, ("answer", "question", "questionItemId"))
        text(row["questionItemId"], "question reference", 4096)
        replies.append(Answer(text(row["question"], "question"), text(row["answer"], "answer")))
    return replies


def cursor(value):
    return None if value is None else text(value, "history cursor", 4096)


def tool_image_parts(item):
    kind = item["type"]
    if kind == "imageView":
        return [{"type": "localImage", "path": item.get("path")}]
    if kind == "imageGeneration":
        if item.get("savedPath"):
            return [{"type": "localImage", "path": item["savedPath"]}]
        return [{"type": "inlineImage", "data": item.get("result")}]
    if kind == "mcpToolCall":
        result = item.get("result")
        content = result.get("content", []) if type(result) is dict else []
    elif kind == "dynamicToolCall":
        content = item.get("contentItems") or []
    else:
        content = item.get("output", [])
        if type(content) is str:
            return []
    if type(content) is not list:
        raise ValueError("Invalid tool content")
    parts = []
    for part in content:
        if type(part) is not dict:
            raise ValueError("Invalid tool content item")
        if kind == "mcpToolCall" and part.get("type") == "image":
            parts.append({"type": "image", "url": "data:" + text(part.get("mimeType"), "image type", 100)
                          + ";base64," + text(part.get("data"), "image data", MAX_BYTES * 4 // 3 + 4)})
        elif kind == "dynamicToolCall" and part.get("type") == "inputImage":
            parts.append({"type": "image", "url": part.get("imageUrl")})
        elif kind == "functionCallOutput" and part.get("type") == "input_image":
            parts.append({"type": "image", "url": part.get("image_url")})
    return parts


def decode_page(page, descending=True, budget=None):
    rows = page["data"]
    if type(rows) is not list:
        raise ValueError("Invalid harness message page")
    out, identifiers, activity, timeline_groups = [], [], [], []
    budget = budget if budget is not None else ImageBudget()
    for record in rows:
        if type(record) is not dict or type(record.get("item")) is not dict:
            raise ValueError("Invalid harness message record")
        item = record["item"]
        identifier = text(record["turnId"], "turn id", 200) + ":" + text(item["id"], "item id", 200)
        identifiers.append(identifier)
        kind = item.get("type")
        timeline_group = []
        timeline_groups.append(timeline_group)
        if kind in ("commandExecution", "mcpToolCall", "dynamicToolCall") and "status" in item:
            states = {"inProgress": "running", "completed": "completed", "failed": "failed",
                      "declined": "declined"}
            if item["status"] not in states:
                raise ValueError("Unknown native activity status")
            label = command_label(item["command"]) if kind == "commandExecution" else text(
                item["tool"], "tool name", 200)
            duration = item.get("durationMs")
            if duration is not None and (type(duration) is not int or duration < 0):
                raise ValueError("Invalid activity duration")
            started = record.get("startedAtMs")
            if started is not None and (type(started) is not int or started < 0):
                raise ValueError("Invalid native activity timestamp")
            activity_id = "activity:" + identifier
            activity.append(Activity(activity_id, label, states[item["status"]], duration, started))
            timeline_group.append(activity_id)
        if kind in ("imageView", "imageGeneration", "mcpToolCall", "dynamicToolCall", "functionCallOutput"):
            parts = tool_image_parts(item)
            if not parts:
                continue
            images = []
            for part in parts:
                image = native_image(part, budget)
                if image:
                    images.append(image)
            body = "" if len(images) == len(parts) else (
                "[Image unavailable here; open the native conversation.]"
            )
            out.append(Message(identifier, "assistant", body, images=images or None))
            timeline_group.append(identifier)
            continue
        if kind not in ("userMessage", "agentMessage"):
            continue  # tool output and reasoning aren't chat messages
        phase, replies, images = None, None, []
        if kind == "agentMessage":
            body = item["text"]
            if type(body) is not str:
                raise ValueError("Invalid assistant message")
            phase = item.get("phase")
            if phase not in (None, "commentary", "partial_answer", "final_answer"):
                raise ValueError("Invalid assistant message phase")
            role = "assistant"
        else:
            if type(item.get("content")) is not list:
                raise ValueError("Invalid user message")
            parts = []
            for part in item["content"]:
                if type(part) is not dict:
                    raise ValueError("Invalid user message content")
                if part.get("type") == "text":
                    if type(part.get("text")) is not str:
                        raise ValueError("Invalid user text")
                    parts.append(part["text"])
                elif part.get("type") in ("image", "localImage"):
                    image = native_image(part, budget)
                    if image:
                        images.append(image)
                    else:
                        parts.append("[Image unavailable here; open the native conversation.]")
                elif part.get("type") in ("audio", "localAudio"):
                    parts.append("[Audio attachment; open the native conversation.]")
            body, role = "\n".join(parts), "user"
            try:
                replies = question_reply(body)
            except ValueError:
                body = ("A question reply could not be displayed. "
                        "Open the native conversation for the original.")
            if replies:
                body = "\n\n".join(f"{reply.question}\nAnswer: {reply.answer}" for reply in replies)
        if body or images:
            out.append(Message(identifier, role, body, phase, replies, images or None))
            timeline_group.append(identifier)
    if descending:
        out.reverse()
        activity.reverse()
        timeline_groups.reverse()
    return Page(out, identifiers, cursor(page["nextCursor"]), cursor(page["backwardsCursor"]),
                activity=activity, timeline=[identifier for group in timeline_groups for identifier in group])


def history(rpc, thread_id, older=None, since=None):
    if older is not None and since is not None:
        raise ValueError("Choose older history or forward catch-up")
    params = {"threadId": thread_id, "limit": 100, "sortDirection": "desc"}
    budget = ImageBudget()
    if since is not None:
        head = decode_page(rpc.call("thread/items/list", {**params, "limit": 1}),
                           budget=ImageBudget(bytes=0))
        page = decode_page(rpc.call("thread/items/list", {
            **params, "sortDirection": "asc", "cursor": cursor(since),
        }), descending=False, budget=budget)
        reached = not head.identifiers or head.identifiers[0] in page.identifiers
        if not reached and page.older is None:
            raise ValueError("History changed during catch-up; reload the conversation")
        if not reached and page.older == since:
            raise ValueError("History cursor did not advance")
        return Page(page.messages, page.identifiers, None,
                    head.newer if reached else page.older, not reached, page.activity, page.timeline)
    if older is not None:
        params["cursor"] = cursor(older)
    page = decode_page(rpc.call("thread/items/list", params), budget=budget)
    # A tool-heavy turn should still open with a useful recent conversation.
    for _ in range(2):
        if len(page.messages) >= 12 or page.older is None:
            break
        previous = decode_page(rpc.call("thread/items/list", {**params, "cursor": page.older}), budget=budget)
        page = Page(previous.messages + page.messages, page.identifiers,
                    previous.older, page.newer, activity=previous.activity + page.activity,
                    timeline=previous.timeline + page.timeline)
    return page
