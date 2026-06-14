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


from unittest.mock import patch, MagicMock
from agent.ellie_bridge import run_turn_via_ellie


class _FakeStream:
    def __init__(self, lines):
        self._lines = lines

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def raise_for_status(self):
        pass

    def iter_lines(self):
        return iter(self._lines)


def test_run_turn_via_ellie_posts_and_translates():
    lines = [
        'data: {"type":"token","text":"Hi"}',
        'data: {"type":"turn_end","prose":"Hi"}',
        'data: {"type":"stats","iterations":1,"prompt_tokens":3,"completion_tokens":1,"outcome":"completed"}',
    ]
    agent = MagicMock()
    agent.session_id = "s1"
    streamed = []

    fake_client = MagicMock()
    fake_client.__enter__.return_value = fake_client
    fake_client.__exit__.return_value = False
    fake_client.stream.return_value = _FakeStream(lines)

    with patch("agent.ellie_bridge.httpx.Client", return_value=fake_client):
        result = run_turn_via_ellie(
            agent,
            "hello",
            conversation_history=[{"role": "user", "content": "earlier"}],
            stream_callback=streamed.append,
            sidecar_url="http://127.0.0.1:3002",
            bearer="secret-token",
        )

    _, kwargs = fake_client.stream.call_args
    assert kwargs["json"]["user_text"] == "hello"
    assert kwargs["json"]["history"] == [{"role": "user", "content": "earlier"}]
    assert kwargs["headers"]["Authorization"] == "Bearer secret-token"
    assert streamed == ["Hi", None]
    assert result["final_response"] == "Hi"
    assert result["completed"] is True
    assert result["session_id"] == "s1"
