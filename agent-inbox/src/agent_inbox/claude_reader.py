"""Read-only SDK helper, isolated so each native profile retains its own environment."""

import json
import sys
import uuid
from dataclasses import asdict

from claude_agent_sdk import get_session_info, get_session_messages, list_subagents

from .models import decode_json, fields, text


def read(request):
    fields(request, ("session", "directory", "operation"))
    identifier = text(request["session"], "Claude session id", 200)
    if str(uuid.UUID(identifier)) != identifier:
        raise ValueError("Invalid native session id")
    directory = text(request["directory"], "project directory", 4096)
    info = get_session_info(identifier, directory=directory)
    if info is None or info.session_id != identifier:
        raise ValueError("Only existing main sessions can be read")
    if request["operation"] == "info":
        return {"info": asdict(info)}
    if request["operation"] != "history":
        raise ValueError("Unknown SDK read operation")
    if type(info.file_size) is not int or not 0 <= info.file_size <= 16 * 1024 * 1024:
        raise ValueError("Native history is outside the inbox read limit")
    # These documented helpers read files only; never query(), resume(), or launch a model.
    messages = get_session_messages(identifier, directory=directory)
    children = list_subagents(identifier, directory=directory)
    return {"info": asdict(info), "messages": [asdict(message) for message in messages], "children": children}


def main():
    try:
        raw = sys.stdin.buffer.read(65537)
        if len(raw) > 65536:
            raise ValueError("Oversized SDK read request")
        result = json.dumps(read(decode_json(raw)), ensure_ascii=False).encode()
        if len(result) > 24 * 1024 * 1024:
            raise ValueError("Native SDK response is outside the inbox limit")
        sys.stdout.buffer.write(result)
    except (OSError, ValueError, TypeError, KeyError):
        sys.exit(1)  # private paths, transcript contents and native diagnostics never go to logs


if __name__ == "__main__":
    main()
