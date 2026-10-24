from markdown_it import MarkdownIt

from .models import Snapshot

MARKDOWN = MarkdownIt("commonmark", {"html": False}).disable("image")


def render_snapshot(snapshot: Snapshot):
    value = snapshot.json()
    for message in value["messages"]:
        message["html"] = MARKDOWN.render(message["text"])
    return value
