"""Bridge: route a Hermes turn to the Ellie (Rust) sidecar over HTTP.

Phase 1 of the Ellie-takes-Hermes plan. Ellie owns the agentic loop; Hermes
owns persistence. Model providers are out of scope — Ellie uses its own
Anthropic-OAuth client.
"""
from __future__ import annotations

import json
from typing import Any, Dict, Iterable, Iterator, List, Optional


def parse_sse_events(lines: Iterable[str]) -> Iterator[Dict[str, Any]]:
    """Yield decoded JSON objects from SSE ``data:`` lines. Ignores blanks
    and comment (``:``-prefixed) lines."""
    for raw in lines:
        line = raw.decode("utf-8") if isinstance(raw, (bytes, bytearray)) else raw
        line = line.strip()
        if not line or line.startswith(":"):
            continue
        if line.startswith("data:"):
            payload = line[len("data:"):].strip()
            if payload:
                yield json.loads(payload)


def _history_to_wire(history: List[Dict[str, Any]]) -> List[Dict[str, str]]:
    """Phase 1: forward only plain user/assistant text turns. Tool-call and
    tool-result history is intentionally dropped (documented limitation)."""
    out: List[Dict[str, str]] = []
    for m in history or []:
        role = m.get("role")
        content = m.get("content")
        if role in ("user", "assistant") and isinstance(content, str) and content.strip():
            out.append({"role": role, "content": content})
    return out


def _drive(events: Iterable[Dict[str, Any]], stream_callback) -> List[Dict[str, Any]]:
    """Fire ``stream_callback`` for each token (then a final ``None`` end-of-stream
    sentinel, matching Hermes convention) and return all events collected."""
    collected: List[Dict[str, Any]] = []
    for ev in events:
        if ev.get("type") == "token" and stream_callback is not None:
            try:
                stream_callback(ev.get("text", ""))
            except Exception:
                pass
        collected.append(ev)
    if stream_callback is not None:
        try:
            stream_callback(None)
        except Exception:
            pass
    return collected


def _events_to_result(
    user_message: str,
    conversation_history: List[Dict[str, Any]],
    events: List[Dict[str, Any]],
    session_id: Optional[str],
) -> Dict[str, Any]:
    """Assemble Hermes's standard run_conversation result dict from Ellie events."""
    prose = ""
    completed = False
    api_calls = 0
    in_tok = 0
    out_tok = 0
    model = "ellie"
    error_msg = None
    for ev in events:
        t = ev.get("type")
        if t == "turn_end":
            prose = ev.get("prose", "")
        elif t == "stats":
            api_calls = int(ev.get("iterations", 0) or 0)
            in_tok = int(ev.get("prompt_tokens", 0) or 0)
            out_tok = int(ev.get("completion_tokens", 0) or 0)
            model = ev.get("model", "ellie")
            completed = ev.get("outcome") == "completed"
        elif t == "error":
            error_msg = ev.get("message", "ellie error")
    if error_msg and not prose:
        prose = f"[ellie error] {error_msg}"
        completed = False

    messages = list(conversation_history or [])
    messages.append({"role": "user", "content": user_message})
    messages.append({"role": "assistant", "content": prose})

    return {
        "final_response": prose,
        "messages": messages,
        "api_calls": api_calls,
        "completed": completed,
        "session_id": session_id,
        "model": f"ellie:{model}",
        "provider": "ellie",
        "input_tokens": in_tok,
        "output_tokens": out_tok,
        "total_tokens": in_tok + out_tok,
    }
