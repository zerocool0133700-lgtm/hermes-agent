"""Bridge: route a Hermes turn to the Ellie (Rust) sidecar over HTTP.

Phase 1 of the Ellie-takes-Hermes plan. Ellie owns the agentic loop; Hermes
owns persistence. Model providers are out of scope — Ellie uses its own
Anthropic-OAuth client.
"""
from __future__ import annotations

import httpx
import json
import logging
from typing import Any, Dict, Iterable, Iterator, List, Optional

logger = logging.getLogger(__name__)


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


def _conversation_id(agent) -> str:
    """Stable id threading the per-conversation digest. Gateway sessions have a
    cross-process key; CLI sessions fall back to the per-run session id."""
    key = getattr(agent, "_gateway_session_key", None)
    if isinstance(key, str) and key:
        return key
    sid = getattr(agent, "session_id", None)
    if isinstance(sid, str) and sid:
        return sid
    return "hermes-unknown"


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


def run_turn_via_ellie(
    agent,
    user_message: str,
    *,
    conversation_history: Optional[List[Dict[str, Any]]] = None,
    task_id: Optional[str] = None,
    stream_callback=None,
    sidecar_url: str = "http://127.0.0.1:3002",
    bearer: str = "",
) -> Dict[str, Any]:
    """Route one Hermes turn to the Ellie sidecar and return Hermes's result dict.

    Note: ``system_message`` and ``persist_user_message`` are intentionally NOT
    forwarded — Ellie uses its own identity prompt in Phase 1. ``task_id`` is
    accepted to mirror ``run_conversation``'s signature but is a Hermes-side
    concept with no wire equivalent, so it is intentionally not sent to Ellie.
    """
    history = conversation_history or []
    payload = {
        "user_text": user_message,
        "history": _history_to_wire(history),
        "skills": [],
        "conversation_id": _conversation_id(agent),
    }
    headers = {"Authorization": f"Bearer {bearer}"} if bearer else {}

    with httpx.Client(timeout=httpx.Timeout(300.0, connect=10.0)) as client:
        with client.stream(
            "POST", f"{sidecar_url}/api/turn", json=payload, headers=headers
        ) as resp:
            resp.raise_for_status()
            events = _drive(parse_sse_events(resp.iter_lines()), stream_callback)

    session_id = getattr(agent, "session_id", None)
    return _events_to_result(user_message, history, events, session_id)


def _session_marker(agent) -> int:
    """Monotonic-across-sessions, stable-within-session marker (epoch millis at
    session start). Lets Ellie order digest updates and dedupe retries."""
    start = getattr(agent, "session_start", None)
    try:
        if start is not None:
            return int(start.timestamp() * 1000)
    except Exception:
        pass
    import time
    return int(time.time() * 1000)


def notify_ellie_session_end(
    agent,
    messages: List[Dict[str, Any]],
    *,
    sidecar_url: str = "http://127.0.0.1:3002",
    bearer: str = "",
) -> None:
    """Best-effort: tell the Ellie sidecar a conversation ended so it can roll
    the digest forward and distill durable facts to the Forest. Fire-and-forget
    (Ellie returns 202). NEVER raises — a shutdown must not fail because Ellie
    is unreachable."""
    try:
        payload = {
            "conversation_id": _conversation_id(agent),
            "history": _history_to_wire(messages or []),
            "marker": _session_marker(agent),
        }
        headers = {"Authorization": f"Bearer {bearer}"} if bearer else {}
        with httpx.Client(timeout=httpx.Timeout(10.0, connect=5.0)) as client:
            resp = client.post(
                f"{sidecar_url}/api/session-end", json=payload, headers=headers
            )
            resp.raise_for_status()
    except Exception as exc:  # noqa: BLE001 — fail-soft by design
        logger.debug("ellie session-end notify failed (ignored): %s", exc)
