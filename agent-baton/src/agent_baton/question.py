"""Ordinary answers are readable by agents; secret forms never use this path."""

import json

from agent_baton import core
from agent_baton.ask import NAME

MAX_ANSWER = 2000


def validate_question(prompt, options):
    if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > 2000:
        raise ValueError("question must contain 1–2000 characters")
    if (
        not isinstance(options, list)
        or len(options) > 10
        or any(not isinstance(option, str) or not option.strip() or len(option) > 300 for option in options)
    ):
        raise ValueError("give at most 10 nonempty options, each at most 300 characters")
    if len(set(options)) != len(options):
        raise ValueError("options must be distinct")


def create(prompt, options, reason, by, ttl, *, multiple=False):
    validate_question(prompt, options)
    if multiple and not options:
        raise ValueError("select-many questions need options")
    if len(reason) > 300 or isinstance(ttl, bool) or not isinstance(ttl, int) or ttl <= 0:
        raise ValueError("reason must be at most 300 characters and ttl must be positive")
    return core.create(
        "Question", reason, by, ttl, kind="question", question=prompt, options=options, multiple=multiple
    )


def load_form(path):
    """Strict JSON boundary for agent-created, nonsecret, disposable forms."""

    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate JSON field")
            result[key] = value
        return result

    def invalid_constant(_):
        raise ValueError("non-finite JSON values are not accepted")

    with path.open("rb") as source:
        data = source.read(65537)
    if len(data) > 65536:
        raise ValueError("form definition must be at most 64 KiB")
    spec = json.loads(data.decode("utf-8"), object_pairs_hook=unique, parse_constant=invalid_constant)
    if not isinstance(spec, dict) or set(spec) - {"title", "reason", "questions"}:
        raise ValueError("form accepts only title, reason and questions")
    title, reason, questions = spec.get("title"), spec.get("reason", ""), spec.get("questions")
    if not isinstance(title, str) or not title.strip() or len(title) > 120:
        raise ValueError("title must contain 1–120 characters")
    if not isinstance(reason, str) or len(reason) > 300:
        raise ValueError("reason must be at most 300 characters")
    if not isinstance(questions, list) or not 1 <= len(questions) <= 10:
        raise ValueError("form needs 1–10 questions")
    decoded, names = [], set()
    for item in questions:
        if not isinstance(item, dict) or set(item) - {"id", "question", "type", "options", "required"}:
            raise ValueError("question accepts only id, question, type, options and required")
        name, kind, required = item.get("id"), item.get("type"), item.get("required", True)
        if not isinstance(name, str) or not NAME.fullmatch(name) or name in names:
            raise ValueError("question ids must be unique lowercase field names, at most 32 characters")
        if kind not in ("text", "choice", "multiple") or not isinstance(required, bool):
            raise ValueError("type must be text, choice or multiple; required must be a boolean")
        prompt, options = item.get("question"), item.get("options", [])
        validate_question(prompt, options)
        if (kind == "text" and "options" in item) or (kind != "text" and not options):
            raise ValueError("text questions omit options; choice and multiple questions need options")
        names.add(name)
        decoded.append(
            {
                "id": name,
                "question": prompt,
                "options": options,
                "multiple": kind == "multiple",
                "required": required,
            }
        )
    return {"title": title, "reason": reason, "questions": decoded}


def create_form(spec, by, ttl):
    baton = create(spec["title"], [], spec["reason"], by, ttl)
    baton["site"] = spec["title"]
    baton["form"] = spec["questions"]
    core.save(baton)
    return baton


def decode_answer(baton, form):
    if set(form) - {"answer", "choice"} or len(form.get("answer", [""])) != 1:
        raise ValueError("duplicate or unknown answer fields are not accepted")
    text = form.get("answer", [""])[0]
    if len(text) > MAX_ANSWER:
        raise ValueError(f"answer must be at most {MAX_ANSWER} characters")
    if not baton.get("required", True) and not text and not form.get("choice"):
        return None
    if baton["options"]:
        choices = form.get("choice", [])
        indices = [str(i) for i in range(len(baton["options"]))]
        if not choices or len(set(choices)) != len(choices) or set(choices) - {*indices, "other"}:
            raise ValueError("choose a listed option or Other")
        if not baton["multiple"] and len(choices) != 1:
            raise ValueError("choose exactly one option")
        if "other" in choices:
            if not text.strip():
                raise ValueError("write your Other answer")
        elif text:
            raise ValueError("select Other to include a written answer")
        selected = [option for i, option in enumerate(baton["options"]) if str(i) in choices]
        if "other" in choices:
            if text in baton["options"]:
                raise ValueError("select the listed option instead of repeating it as Other")
            selected.append(text)
        return selected if baton["multiple"] else selected[0]
    elif "choice" in form:
        raise ValueError("this question accepts a written answer")
    if not text.strip():
        raise ValueError("write an answer")
    return text


def decode_form(baton, form):
    allowed = {f"{item['id']}.{field}" for item in baton["form"] for field in ("answer", "choice")}
    if set(form) - allowed:
        raise ValueError("unknown form field")
    answers = {}
    for item in baton["form"]:
        prefix = f"{item['id']}."
        fields = {key.removeprefix(prefix): value for key, value in form.items() if key.startswith(prefix)}
        try:
            answer = decode_answer(item, fields)
        except ValueError as error:
            raise ValueError(f"{item['id']}: {error}") from error
        if answer is not None:
            answers[item["id"]] = answer
    return answers


def complete(baton_id, form=None, *, declined=False):
    """First answer or withdrawal wins, including across the daemon and CLI processes."""
    with core.locked(baton_id):
        baton = core.expire(core.read(baton_id))
        if baton["kind"] != "question":
            raise ValueError("only ordinary questions can be withdrawn")
        if baton["status"] != "held":
            return baton
        if form is None:
            baton["status"] = "cancelled" if declined else "withdrawn"
        else:
            key = "answers" if "form" in baton else "answer"
            baton[key] = decode_form(baton, form) if "form" in baton else decode_answer(baton, form)
            baton["status"] = "returned"
        core.save(baton)
        return baton
