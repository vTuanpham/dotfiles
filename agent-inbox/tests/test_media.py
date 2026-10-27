import base64
import io
import json
import os

import pytest
from PIL import Image
from test_inbox import SteeringRpc, codex_target, history_page, submission, use_rpc

from agent_inbox import codex, codex_history, media
from agent_inbox.media import MAX_BYTES, ImageBudget, MediaCache, decode_images, native_image, raster
from agent_inbox.models import Outgoing, Snapshot
from agent_inbox.presentation import render_snapshot


def image_bytes(format="PNG"):
    buffer = io.BytesIO()
    Image.new("RGB", (12, 8), "#87e1c0").save(buffer, format=format)
    return buffer.getvalue()


@pytest.mark.parametrize("format", ["PNG", "JPEG", "WEBP", "GIF"])
def test_raster_validation_preserves_original_bytes(format):
    raw = image_bytes(format)
    url = raster(raw)
    assert decode_images([url]) == [url]
    assert base64.b64decode(url.partition(",")[2]) == raw


@pytest.mark.parametrize("urls", [None, "image", ["https://example.test/image.png"],
                                 ["file:///etc/passwd"], ["data:image/svg+xml;base64,PHN2Zy8+"],
                                 ["data:image/png;base64,@@"], ["data:image/png;base64,YmFk"],
                                 ["data:image/png;base64,"] * 5])
def test_invalid_media_fails_closed(urls):
    with pytest.raises(ValueError):
        decode_images(urls)


def test_spoofed_mime_and_resource_limits_are_rejected():
    with pytest.raises(ValueError):
        decode_images([raster(image_bytes()).replace("image/png", "image/jpeg")])
    with pytest.raises(ValueError):
        raster(b"0" * (MAX_BYTES + 1))
    buffer = io.BytesIO()
    Image.new("1", (5001, 5000)).save(buffer, format="PNG")
    with pytest.raises(ValueError):
        raster(buffer.getvalue())


def test_native_previews_do_not_expose_paths_or_fetch_remote_urls(tmp_path):
    path = tmp_path / "picture.png"
    path.write_bytes(image_bytes())
    url = native_image({"type": "localImage", "path": str(path)})
    assert url == raster(path.read_bytes())
    assert native_image({"type": "image", "url": "https://example.test/private"}) is None
    assert native_image({"type": "localImage", "path": str(path)}, ImageBudget(bytes=1)) is None
    page = history_page([
        {"id": "user-image", "type": "userMessage", "content": [{"type": "localImage", "path": str(path)}]},
        {"id": "view", "type": "imageView", "path": str(path)},
        {"id": "generated", "type": "imageGeneration", "savedPath": str(path), "status": "completed"},
        {"id": "file", "type": "imageGeneration", "fileId": "private-file-id", "status": "completed"},
    ])
    messages = codex_history.decode_page(page).messages
    result = render_snapshot(Snapshot("idle", True, messages))
    assert sum(bool(message["images"]) for message in result["messages"]) == 3
    assert str(path) not in json.dumps(result) and "private-file-id" not in json.dumps(result)
    link = tmp_path / "link.png"
    link.symlink_to(path)
    assert native_image({"type": "localImage", "path": str(link)}) is None
    pipe = tmp_path / "pipe.png"
    os.mkfifo(pipe)
    assert native_image({"type": "localImage", "path": str(pipe)}) is None


def test_busy_image_input_uses_same_turn_and_stable_client_id(monkeypatch):
    rpc = SteeringRpc([[{"id": "current", "status": "inProgress"}]])
    use_rpc(monkeypatch, rpc)
    message = Outgoing(submission()["id"], "What is this?", [raster(image_bytes())], "steer")
    assert codex.Codex().send(codex_target(), message) == "steered"
    params = rpc.calls[-1][1]
    assert params["clientUserMessageId"] == message.id
    assert params["input"] == [{"type": "text", "text": message.text},
                               {"type": "image", "url": message.images[0]}]


@pytest.mark.parametrize("change", [None, {"id": ""}, {"input": []}, {"clientUserMessageId": "wrong"}])
def test_idle_image_queue_checks_the_native_receipt(monkeypatch, change):
    calls = []
    message = Outgoing(submission()["id"], "", [raster(image_bytes())])

    class QueueRpc:
        def call(self, method, params):
            calls.append((method, params))
            if method == "thread/read":
                return {"thread": {"id": "root-id", "sessionId": "root-id", "parentThreadId": None,
                                   "canAcceptDirectInput": True, "status": {"type": "idle"}}}
            assert method == "thread/queue/add"
            return {"queuedSubmission": {"id": "queue-entry", "clientUserMessageId": message.id,
                                         "input": params["input"], **(change or {})}}

    use_rpc(monkeypatch, QueueRpc())
    if change is None:
        assert codex.Codex().send(codex_target(), message) == "queued"
    else:
        with pytest.raises((ValueError, RuntimeError)):
            codex.Codex().send(codex_target(), message)
    assert calls[-1][1]["input"] == [{"type": "image", "url": message.images[0]}]
    assert sum(method == "thread/queue/add" for method, _ in calls) == 1


def test_tool_images_render_without_exposing_other_tool_content():
    url = raster(image_bytes())
    encoded = url.partition(",")[2]
    page = history_page([
        {"id": "mcp", "type": "mcpToolCall", "result": {"content": [
            {"type": "text", "text": "private tool output"},
            {"type": "image", "data": encoded, "mimeType": "image/png"}]}},
        {"id": "dynamic", "type": "dynamicToolCall", "contentItems": [
            {"type": "inputImage", "imageUrl": url}]},
        {"id": "function", "type": "functionCallOutput", "output": [
            {"type": "input_image", "image_url": url}]},
        {"id": "generated", "type": "imageGeneration", "result": encoded},
    ])
    messages = codex_history.decode_page(page).messages
    assert len(messages) == 4 and all(m.images == [url] for m in messages)
    assert "private tool output" not in json.dumps(Snapshot("idle", True, messages).json())


def test_pixel_and_animation_limits_apply_to_the_whole_submission():
    url = raster(image_bytes())
    with pytest.raises(ValueError):
        decode_images([url, url], ImageBudget(pixels=100))
    buffer = io.BytesIO()
    Image.new("RGB", (12, 8), "red").save(buffer, format="GIF", save_all=True,
                                          append_images=[Image.new("RGB", (12, 8), "blue")])
    with pytest.raises(ValueError):
        raster(buffer.getvalue())


def test_three_history_pages_share_one_image_budget(monkeypatch):
    raw = image_bytes()
    url = raster(raw)
    monkeypatch.setattr(codex_history, "ImageBudget", lambda **kwargs: media.ImageBudget(
        bytes=kwargs.get("bytes", len(raw) * 2), pixels=1000,
    ))

    class Pages:
        def call(self, method, params):
            index = int(params.get("cursor", 0))
            return history_page([{"id": str(index), "type": "userMessage", "content": [
                {"type": "image", "url": url}]}], str(index + 1) if index < 2 else None)

    messages = codex_history.history(Pages(), "root").messages
    assert len(messages) == 3 and sum(bool(m.images) for m in messages) == 2
    assert "unavailable" in messages[0].text


def test_forward_head_does_not_read_its_image_twice(monkeypatch):
    budgets, actual = [], codex_history.native_image

    def decode(part, budget):
        budgets.append(budget.bytes)
        return actual(part, budget)

    class Pages:
        def call(self, method, params):
            return history_page([{"id": "same", "type": "imageView", "path": "/does/not/exist.png"}],
                                previous="same")

    monkeypatch.setattr(codex_history, "native_image", decode)
    codex_history.history(Pages(), "root", since="same")
    assert budgets == [0, MAX_BYTES]


def test_preview_cache_is_memory_bounded_and_root_scoped():
    cache = MediaCache()
    url = raster(image_bytes())
    first = cache.publish("first", url)
    assert cache.publish("first", url) == first
    assert cache.publish("second", url) != first
    assert cache.get(first.partition("=")[2]) == ("image/png", image_bytes())
    assert cache.size == len(image_bytes()) * 2
    large = "data:image/png;base64," + base64.b64encode(b"0" * MAX_BYTES).decode()
    for index in range(5):
        cache.publish(str(index), large)
    assert cache.size <= 32 * 1024 * 1024 and len(cache.entries) == 4
