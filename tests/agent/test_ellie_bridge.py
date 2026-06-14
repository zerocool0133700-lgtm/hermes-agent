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
