from dataclasses import asdict

from markdown_it import MarkdownIt

from .forms import Forms
from .models import Snapshot

MARKDOWN = MarkdownIt("commonmark", {"html": False, "linkify": True}).disable("image").enable("linkify")
MARKDOWN.linkify.set({"fuzzy_link": False, "fuzzy_email": False})


def render_link(renderer, tokens, index, options, env):
    tokens[index].attrSet("target", "_blank")
    tokens[index].attrSet("rel", "noopener noreferrer")
    return renderer.renderToken(tokens, index, options, env)


MARKDOWN.add_render_rule("link_open", render_link)


def render_snapshot(snapshot: Snapshot):
    value = snapshot.json()
    for message in value["messages"]:
        if message.get("answers"):
            message["html"] = "".join(
                f'<p class="answer-question">{MARKDOWN.renderInline(reply["question"])}</p>'
                f'<p class="answer-choice">{MARKDOWN.renderInline(reply["answer"])}</p>'
                for reply in message["answers"]
            )
        else:
            message["html"] = MARKDOWN.render(message["text"])
    return value


def render_forms(forms: Forms):
    value = asdict(forms)
    for form in value["forms"]:
        form["title_html"] = MARKDOWN.renderInline(form["title"])
        for field in form["fields"]:
            for key in ("label", "description"):
                field[key + "_html"] = MARKDOWN.renderInline(field[key])
            for choice in field["choices"]:
                choice["label_html"] = MARKDOWN.renderInline(choice["label"])
    return value
