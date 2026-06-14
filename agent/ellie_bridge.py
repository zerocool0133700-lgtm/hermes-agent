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
