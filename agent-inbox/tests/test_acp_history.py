"""ACP transcript projection regressions, including valid streams without message IDs."""

from test_acp import image_url

from agent_inbox import acp_history


def update(history, kind, **values):
    history.update({"sessionId": "root", "update": {"sessionUpdate": kind, **values}})


def test_tool_results_keep_images_but_do_not_publish_text_resources_or_arguments():
    history = acp_history.History("root")
    url = image_url()
    mime, _, encoded = url[5:].partition(";base64,")
    update(history, "tool_call", toolCallId="tool", title="Reading a file", rawInput={"secret": "input"},
           rawOutput={"secret": "output"}, content=[
               {"type": "content", "content": {"type": "text", "text": "private tool output"}},
               {"type": "content", "content": {"type": "resource", "resource": {
                   "uri": "file:///project/credentials.txt", "text": "private embedded resource",
               }}},
               {"type": "content", "content": {"type": "image", "mimeType": mime, "data": encoded}},
           ])
    messages, activity, *_ = history.page()
    assert [(message.text, message.images) for message in messages] == [("", [url])]
    assert [item.label for item in activity] == ["Reading a file"]


def test_idless_chunks_merge_until_role_tool_or_turn_boundary():
    history = acp_history.History("root")
    update(history, "user_message_chunk", content={"type": "text", "text": "Please "})
    update(history, "user_message_chunk", content={"type": "text", "text": "help"})
    update(history, "agent_message_chunk", content={"type": "text", "text": "I will "})
    update(history, "agent_message_chunk", content={"type": "text", "text": "check"})
    update(history, "tool_call", toolCallId="tool", title="Checking")
    update(history, "agent_message_chunk", content={"type": "text", "text": "Done"})
    history.end_turn()
    update(history, "agent_message_chunk", content={"type": "text", "text": "Next turn"})
    messages, activity, timeline, *_ = history.page()
    assert [message.text for message in messages] == ["Please help", "I will check", "Done", "Next turn"]
    assert timeline == [messages[0].id, messages[1].id, activity[0].id, messages[2].id, messages[3].id]


def test_generated_chunk_ids_cannot_collide_with_native_message_ids():
    history = acp_history.History("root")
    update(history, "agent_message_chunk", content={"type": "text", "text": "Generated"})
    update(history, "user_message_chunk", messageId="chunk-1", content={"type": "text", "text": "Native"})
    assert [message.text for message in history.page()[0]] == ["Generated", "Native"]


def test_tool_image_ids_cannot_collide_with_native_ids_or_reject_a_valid_long_tool_id():
    history = acp_history.History("root")
    url = image_url()
    mime, _, encoded = url[5:].partition(";base64,")
    update(history, "user_message_chunk", messageId="tool-inspect-0",
           content={"type": "text", "text": "Native"})
    for tool_id in ("inspect", "x" * 200):
        update(history, "tool_call", toolCallId=tool_id, title="Image result", content=[{
            "type": "content", "content": {"type": "image", "mimeType": mime, "data": encoded},
        }])
    messages = history.page()[0]
    assert [message.text for message in messages] == ["Native", "", ""]
    assert len({message.id for message in messages}) == 3
    assert messages[1].images == messages[2].images == [url]
