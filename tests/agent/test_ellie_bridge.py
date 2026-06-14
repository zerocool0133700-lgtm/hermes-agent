from agent.ellie_bridge import parse_sse_events


def test_parse_sse_extracts_data_json():
    lines = [
        'data: {"type":"token","text":"He"}',
        '',
        'data: {"type":"token","text":"llo"}',
        '',
        'data: {"type":"turn_end","prose":"Hello"}',
        '',
    ]
    events = list(parse_sse_events(iter(lines)))
    assert events == [
        {"type": "token", "text": "He"},
        {"type": "token", "text": "llo"},
        {"type": "turn_end", "prose": "Hello"},
    ]


def test_parse_sse_ignores_blank_and_comment_lines():
    lines = ["", ": keep-alive", 'data: {"type":"stats","iterations":2}']
    events = list(parse_sse_events(iter(lines)))
    assert events == [{"type": "stats", "iterations": 2}]


from agent.ellie_bridge import _history_to_wire, _drive, _events_to_result


def test_history_to_wire_keeps_text_turns_only():
    history = [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "yo"},
        {"role": "assistant", "content": None, "tool_calls": [{"id": "c1"}]},
        {"role": "tool", "tool_call_id": "c1", "content": "result"},
        {"role": "user", "content": "   "},
    ]
    assert _history_to_wire(history) == [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "yo"},
    ]


def test_drive_streams_tokens_and_collects_events():
    events = [
        {"type": "token", "text": "He"},
        {"type": "token", "text": "llo"},
        {"type": "turn_end", "prose": "Hello"},
        {"type": "stats", "iterations": 1, "prompt_tokens": 5, "completion_tokens": 2, "outcome": "completed"},
    ]
    streamed = []
    collected = _drive(iter(events), streamed.append)
    assert streamed == ["He", "llo", None]  # tokens, then end-of-stream sentinel
    assert collected == events


def test_events_to_result_builds_hermes_dict():
    events = [
        {"type": "turn_end", "prose": "Hello there"},
        {"type": "stats", "iterations": 3, "prompt_tokens": 10, "completion_tokens": 4, "outcome": "completed"},
    ]
    history = [{"role": "user", "content": "earlier"}]
    result = _events_to_result(
        user_message="hi",
        conversation_history=history,
        events=events,
        session_id="sess-1",
    )
    assert result["final_response"] == "Hello there"
    assert result["completed"] is True
    assert result["api_calls"] == 3
    assert result["input_tokens"] == 10
    assert result["output_tokens"] == 4
    assert result["total_tokens"] == 14
    assert result["provider"] == "ellie"
    assert result["session_id"] == "sess-1"
    assert result["messages"][-2] == {"role": "user", "content": "hi"}
    assert result["messages"][-1] == {"role": "assistant", "content": "Hello there"}


def test_events_to_result_marks_incomplete_on_error():
    events = [{"type": "error", "message": "boom"}]
    result = _events_to_result("hi", [], events, None)
    assert result["completed"] is False
    assert "boom" in result["final_response"]
