# Ellie⟶Hermes Phase 3 — Plan B: the Hermes-side continuity bridge

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Hermes drive Ellie's continuity layer end-to-end: send a stable `conversation_id` on every `/api/turn`, and notify Ellie at session end (`POST /api/session-end`) so Ellie rolls the digest forward and distills durable facts to the Forest — then prove the loop closes with a live smoke.

**Architecture:** Extend `agent/ellie_bridge.py` (the Phase 1 sidecar client) with (1) a shared `conversation_id` derivation, (2) `conversation_id` on the turn payload, and (3) a new best-effort `notify_ellie_session_end()` that POSTs the final transcript + a monotonic `marker`. Wire the notify into the agent's single session-end funnel (`shutdown_memory_provider`), guarded on `backend == "ellie"`, fail-soft, fire-once. Nothing here may ever block or break a turn or a shutdown.

**Tech Stack:** Python 3, `httpx` (already a dep), pytest (`uv run pytest`). No new dependencies.

**Branch:** `feat/ellie-sidecar-bridge` (already checked out, Phase 1 commits present — do NOT switch branches; this extends the same branch/PR line).

**Counterpart:** Ellie gateway PR #64 (`feat/ellie-hermes-memory`) implements `/api/turn` `conversation_id` + `/api/session-end`. This plan is the producer side.

---

## Key design decisions (read first)

1. **`conversation_id` = `agent._gateway_session_key or agent.session_id`.** The gateway key (`"agent:main:telegram:dm:123"`) is stable across processes → the per-thread digest accumulates across sessions. CLI's `session_id` (`"20260614_090714_a1b2c3"`) is per-run → each CLI run is its own thread. Both are acceptable; fall back to a constant if neither exists.

2. **`marker` = `int(session_start_epoch_millis)`, computed once per session.** The marker must be monotonic **across sessions sharing a channel** (so a later session's digest wins Ellie's compare-and-set `WHERE marker < EXCLUDED.marker`), AND stable across retries of the *same* session-end (so Ellie's dedupe `claim_session_end` blocks double-fire). `len(history)` fails the first property (a fresh session has a smaller count → rejected). Wall-clock ms at session start satisfies both: later session → larger marker; same session → same marker. Millisecond resolution avoids same-second collisions.

3. **`/api/turn` needs only `conversation_id`, NOT `marker`.** Ellie's turn handler only *reads* the digest; the digest is *written* solely by `/api/session-end`. So the marker lives only on the session-end payload.

4. **Loop closure does NOT require matching `conversation_id` across sessions.** Ellie's Forest recall is scoped by *user* + read-scope + semantic query — not by conversation. A fact distilled to the Forest in session 1 is recalled in session 2 even under a different `conversation_id`. `conversation_id` only threads the per-thread digest ("what we covered last time"). The live smoke (Task 4) relies on this.

5. **Absolute fail-soft.** `notify_ellie_session_end` swallows every exception (network, timeout, bad status) — a shutdown must never raise because Ellie was unreachable. The hook is also fire-once per agent instance.

---

## File map

- `agent/ellie_bridge.py` — add `_conversation_id()`, add `conversation_id` to the turn payload, add `notify_ellie_session_end()`. (Tasks 1, 2)
- `run_agent.py` — call `notify_ellie_session_end()` from `shutdown_memory_provider()` (the session-end funnel, ~line 2962), guarded + fail-soft + fire-once. (Task 3)
- `tests/agent/test_ellie_bridge.py` — extend with the new cases, reusing the `patch("agent.ellie_bridge.httpx.Client")` + `MagicMock` agent pattern. (Tasks 1–3)
- `docs/plans/2026-06-14-ellie-continuity-smoke-runbook.md` — the live loop-closure runbook (Task 4).

---

## Task 1: `conversation_id` on the turn payload

**Files:** `agent/ellie_bridge.py`, `tests/agent/test_ellie_bridge.py`

- [ ] **Step 1 — write the failing test** (append to `tests/agent/test_ellie_bridge.py`, mirroring `test_run_turn_via_ellie_posts_and_translates`):
```python
def test_run_turn_sends_conversation_id_prefers_gateway_key():
    agent = MagicMock()
    agent._gateway_session_key = "agent:main:telegram:dm:123"
    agent.session_id = "20260614_090714_abc"
    fake_client = MagicMock()
    fake_client.__enter__.return_value = fake_client
    fake_client.__exit__.return_value = False
    fake_client.stream.return_value = _FakeStream(['data: {"type":"turn_end","prose":"hi"}'])
    with patch("agent.ellie_bridge.httpx.Client", return_value=fake_client):
        run_turn_via_ellie(agent, "hello", sidecar_url="http://x", bearer="t")
    _, kwargs = fake_client.stream.call_args
    assert kwargs["json"]["conversation_id"] == "agent:main:telegram:dm:123"


def test_run_turn_conversation_id_falls_back_to_session_id():
    agent = MagicMock()
    agent._gateway_session_key = None
    agent.session_id = "20260614_090714_abc"
    fake_client = MagicMock()
    fake_client.__enter__.return_value = fake_client
    fake_client.__exit__.return_value = False
    fake_client.stream.return_value = _FakeStream(['data: {"type":"turn_end","prose":"hi"}'])
    with patch("agent.ellie_bridge.httpx.Client", return_value=fake_client):
        run_turn_via_ellie(agent, "hello", sidecar_url="http://x", bearer="t")
    _, kwargs = fake_client.stream.call_args
    assert kwargs["json"]["conversation_id"] == "20260614_090714_abc"
```
- [ ] **Step 2 — run, expect FAIL:** `uv run pytest tests/agent/test_ellie_bridge.py -k conversation_id -q` → fails (`conversation_id` not in payload).
- [ ] **Step 3 — add the helper** near the top of `agent/ellie_bridge.py` (after the imports / `_history_to_wire`):
```python
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
```
- [ ] **Step 4 — add it to the payload** in `run_turn_via_ellie` (the `payload = {...}` block ~line 124):
```python
    payload = {
        "user_text": user_message,
        "history": _history_to_wire(history),
        "skills": [],
        "conversation_id": _conversation_id(agent),
    }
```
- [ ] **Step 5 — run, expect PASS:** `uv run pytest tests/agent/test_ellie_bridge.py -k conversation_id -q` → 2 pass. Then the whole file: `uv run pytest tests/agent/test_ellie_bridge.py -q` → all green (the existing `test_run_turn_via_ellie_posts_and_translates` still passes; it doesn't assert the exact key set, only specific fields — confirm; if it asserts `kwargs["json"] == {...}` exactly, update that expected dict to include `conversation_id`).
- [ ] **Step 6 — commit:** `git add agent/ellie_bridge.py tests/agent/test_ellie_bridge.py && git commit -m "feat(ellie-bridge): send conversation_id on /api/turn"`

---

## Task 2: `notify_ellie_session_end()`

**Files:** `agent/ellie_bridge.py`, `tests/agent/test_ellie_bridge.py`

- [ ] **Step 1 — write the failing tests:**
```python
def test_notify_session_end_posts_transcript_and_marker():
    from datetime import datetime
    agent = MagicMock()
    agent._gateway_session_key = "agent:main:telegram:dm:9"
    agent.session_start = datetime(2026, 6, 14, 9, 0, 0)
    messages = [
        {"role": "user", "content": "remember I use worktrees"},
        {"role": "assistant", "content": "noted"},
        {"role": "tool", "content": "ignored"},
    ]
    fake_client = MagicMock()
    fake_client.__enter__.return_value = fake_client
    fake_client.__exit__.return_value = False
    fake_resp = MagicMock()
    fake_resp.raise_for_status.return_value = None
    fake_client.post.return_value = fake_resp
    with patch("agent.ellie_bridge.httpx.Client", return_value=fake_client):
        notify_ellie_session_end(agent, messages, sidecar_url="http://x", bearer="t")
    args, kwargs = fake_client.post.call_args
    assert args[0] == "http://x/api/session-end"
    body = kwargs["json"]
    assert body["conversation_id"] == "agent:main:telegram:dm:9"
    # tool message filtered out by _history_to_wire
    assert body["history"] == [
        {"role": "user", "content": "remember I use worktrees"},
        {"role": "assistant", "content": "noted"},
    ]
    assert body["marker"] == int(datetime(2026, 6, 14, 9, 0, 0).timestamp() * 1000)
    assert kwargs["headers"]["Authorization"] == "Bearer t"


def test_notify_session_end_swallows_network_error():
    agent = MagicMock()
    agent._gateway_session_key = "c"
    agent.session_start = None  # exercises the time.time() fallback path
    fake_client = MagicMock()
    fake_client.__enter__.return_value = fake_client
    fake_client.__exit__.return_value = False
    fake_client.post.side_effect = RuntimeError("connection refused")
    with patch("agent.ellie_bridge.httpx.Client", return_value=fake_client):
        # must NOT raise
        notify_ellie_session_end(agent, [{"role": "user", "content": "hi"}],
                                 sidecar_url="http://x", bearer="t")
```
- [ ] **Step 2 — run, expect FAIL:** `uv run pytest tests/agent/test_ellie_bridge.py -k session_end -q` → fails (`notify_ellie_session_end` undefined).
- [ ] **Step 3 — implement** in `agent/ellie_bridge.py`:
```python
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
    (Ellie returns 202 immediately). NEVER raises — a shutdown must not fail
    because Ellie is unreachable."""
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
```
(Confirm the module already has a `logger`; if not, reuse the existing logging pattern in the file or add `import logging; logger = logging.getLogger(__name__)` near the top — check first.)
- [ ] **Step 4 — run, expect PASS:** `uv run pytest tests/agent/test_ellie_bridge.py -k session_end -q` → 2 pass. Whole file green.
- [ ] **Step 5 — commit:** `git add agent/ellie_bridge.py tests/agent/test_ellie_bridge.py && git commit -m "feat(ellie-bridge): notify_ellie_session_end (best-effort distill trigger)"`

---

## Task 3: wire the hook into `shutdown_memory_provider`

**Files:** `run_agent.py`, `tests/agent/test_ellie_bridge.py` (or a sibling test for the agent method)

- [ ] **Step 1 — READ** `run_agent.py` `shutdown_memory_provider(self, messages=None)` (~line 2962) and the forwarder (~5205–5233) to confirm: how `backend` is read on `self` (is it `self.backend`?), and how config is loaded (`from hermes_cli.config import load_config_readonly; load_config_readonly().get("agent", {})` with keys `ellie_sidecar_url`, `ellie_sidecar_token`). Match those EXACTLY.
- [ ] **Step 2 — write the failing test** (in `tests/agent/test_ellie_bridge.py`; test the agent method by importing the real class is heavy — instead test a small extracted helper OR patch at the method. Pragmatic approach: extract the firing logic into a module function in `ellie_bridge.py` so it's unit-testable, and have `shutdown_memory_provider` call it):
```python
def test_maybe_notify_fires_only_for_ellie_backend():
    sent = []
    agent = MagicMock()
    agent.backend = "ellie"
    agent._gateway_session_key = "c"
    agent.session_start = None
    with patch("agent.ellie_bridge.notify_ellie_session_end",
               side_effect=lambda *a, **k: sent.append(k)):
        maybe_notify_ellie_session_end(agent, [{"role": "user", "content": "hi"}],
                                       sidecar_url="http://x", bearer="t")
        maybe_notify_ellie_session_end(agent, [{"role": "user", "content": "hi"}],
                                       sidecar_url="http://x", bearer="t")  # fire-once
    assert len(sent) == 1  # second call deduped by the instance flag

    native = MagicMock()
    native.backend = "native"
    with patch("agent.ellie_bridge.notify_ellie_session_end") as m:
        maybe_notify_ellie_session_end(native, [], sidecar_url="http://x", bearer="t")
        m.assert_not_called()
```
- [ ] **Step 3 — run, expect FAIL** (`maybe_notify_ellie_session_end` undefined): `uv run pytest tests/agent/test_ellie_bridge.py -k maybe_notify -q`.
- [ ] **Step 4 — implement the guard helper** in `agent/ellie_bridge.py`:
```python
def maybe_notify_ellie_session_end(
    agent, messages, *, sidecar_url="http://127.0.0.1:3002", bearer=""
) -> None:
    """Fire the session-end notify exactly once per agent, only when routing to
    the Ellie backend. Fully guarded — never raises."""
    try:
        if getattr(agent, "backend", None) != "ellie":
            return
        if getattr(agent, "_ellie_session_end_sent", False):
            return
        agent._ellie_session_end_sent = True
        notify_ellie_session_end(
            agent, messages, sidecar_url=sidecar_url, bearer=bearer
        )
    except Exception:  # noqa: BLE001
        pass
```
- [ ] **Step 5 — run, expect PASS:** `uv run pytest tests/agent/test_ellie_bridge.py -k maybe_notify -q` → 2 pass.
- [ ] **Step 6 — call it from `shutdown_memory_provider`.** At the START of `run_agent.py`'s `shutdown_memory_provider(self, messages=None)`, add (matching the file's import + config-read style):
```python
        # Ellie continuity: tell the sidecar this conversation ended so it can
        # roll the digest forward + distill to the Forest. Best-effort, fire-once.
        try:
            if getattr(self, "backend", None) == "ellie":
                from agent.ellie_bridge import maybe_notify_ellie_session_end
                from hermes_cli.config import load_config_readonly
                _cfg = load_config_readonly().get("agent", {})
                maybe_notify_ellie_session_end(
                    self,
                    messages if isinstance(messages, list) else getattr(self, "_session_messages", []),
                    sidecar_url=_cfg.get("ellie_sidecar_url", "http://127.0.0.1:3002"),
                    bearer=_cfg.get("ellie_sidecar_token", ""),
                )
        except Exception:
            pass
```
(Place it before the memory-manager shutdown calls. Use the EXACT config keys/import the forwarder uses — confirm in Step 1.)
- [ ] **Step 7 — verify nothing regressed:** `uv run pytest tests/agent/test_ellie_bridge.py -q` → all green. Also run any existing `shutdown_memory_provider` / run_agent tests touched: `uv run pytest tests/agent -q -k "shutdown or ellie"`.
- [ ] **Step 8 — commit:** `git add agent/ellie_bridge.py run_agent.py tests/agent/test_ellie_bridge.py && git commit -m "feat(agent): fire Ellie session-end from shutdown_memory_provider (fail-soft, once)"`

---

## Task 4: live loop-closure smoke (the proof)

This is the end-to-end verification that Plan A + Plan B actually close the memory loop against real services. It is a **documented manual runbook** + an execution attempt (automated CI cannot stand up the Forest + a real LLM). Write the runbook, then run it if the services are reachable; capture the result.

**Files:** `docs/plans/2026-06-14-ellie-continuity-smoke-runbook.md` (new)

- [ ] **Step 1 — write the runbook** with these exact contents (commands adapted to the real binary/flag names — confirm the Ellie gateway run command and env var names against PR #64's `crates/ellie-wiring/src/config.rs`):

  **Preconditions**
  - Forest bridge reachable at `http://localhost:3001` with a valid bridge key.
  - An Ellie gateway built from `feat/ellie-hermes-memory` (PR #64).
  - Hermes on `feat/ellie-sidecar-bridge` with config `agent.backend=ellie`, `agent.ellie_sidecar_url=http://127.0.0.1:3002`, `agent.ellie_sidecar_token=<token>`.

  **1. Start the Ellie gateway with continuity ENABLED** (both flags default off):
  ```bash
  cd /home/ellie/L2/ellie
  ELLIE_GATEWAY_TOKEN=<token> \
  ELLIE_FOREST_BASE_URL=http://localhost:3001 \
  ELLIE_FOREST_BRIDGE_KEY=<bridge-key> \
  ELLIE_FOREST_LOOP_ENABLED=1 \
  ELLIE_WRITE_BACK_ENABLED=1 \
  ELLIE_GATEWAY_USER_ID=<a real users.id uuid> \
  cargo run -p ellie-gateway   # serves :3002
  # continuity_write_scope defaults to forest_read_scope (2/1) → loop closes.
  ```
  **2. Session 1 — plant a durable fact.** Run a Hermes conversation (CLI or gateway) where the user states something memorable and durable, e.g. *"For the record, I always deploy on Fridays and I hate Mondays."* Let the turn complete, then end the session (CLI exit / `/reset`, or gateway session close) so `shutdown_memory_provider` fires.
  **3. Verify the distill landed in the Forest** (read it back directly via the bridge):
  ```bash
  curl -s -X POST http://localhost:3001/api/bridge/read \
    -H "Content-Type: application/json" -H "x-bridge-key: <bridge-key>" \
    -d '{"query": "when does the user deploy", "scope_path": "2/1"}' | python3 -m json.tool
  # EXPECT: a memory mentioning "Fridays" (or the planted fact).
  ```
  **4. Session 2 — confirm recall surfaces it.** Start a NEW Hermes conversation (new session id is fine — recall is user-scoped, not conversation-scoped) and ask something adjacent: *"When do I usually deploy?"* In the gateway logs / response, confirm the turn was primed with the recalled fact (the `<recalled-memory>` preamble), and that Ellie answers with "Fridays."
  **5. Verify the digest rolled forward** (optional): a second turn in the same conversation as session 1's thread should show the *"## What we covered last time"* digest. Check Ellie's `/metrics`:
  ```bash
  curl -s http://localhost:3002/metrics | grep gateway_continuity
  # EXPECT: continuity_session_end{result="ok"} >= 1, continuity_distill_writes >= 1,
  #         and on session-2 turn: continuity_recall_injected >= 1.
  ```

  **Pass criteria:** a fact stated in session 1 is (a) present in the Forest after session-end, and (b) surfaced via recall in session 2. That is the loop closing end-to-end.

- [ ] **Step 2 — attempt the run.** If the Forest (`:3001`) and a build of PR #64 are available, execute the runbook and capture the actual outputs (the curl read in step 3, the `/metrics` counters in step 5). If services are NOT available, record that explicitly in the runbook under a "Run log" section with the date and what was/wasn't reachable — do NOT claim a pass that wasn't observed. (Honesty gate: a green automated suite does NOT prove loop closure; only this smoke does.)
- [ ] **Step 3 — commit:** `git add docs/plans/2026-06-14-ellie-continuity-smoke-runbook.md && git commit -m "docs(ellie-bridge): live loop-closure smoke runbook + run log"`

---

## Final verification
- [ ] `uv run pytest tests/agent/test_ellie_bridge.py -q` → all green (Phase 1 tests + the new conversation_id / session_end / maybe_notify tests).
- [ ] `git log --oneline feat/ellie-sidecar-bridge` shows Tasks 1–4 commits on top of the Phase 1 bridge.
- [ ] Smoke run log recorded honestly (pass observed, or "services unavailable" noted).

## Self-review notes
- **Spec coverage:** conversation_id on turn ✓ T1; session-end notify ✓ T2; lifecycle hook (fail-soft, fire-once, backend-gated) ✓ T3; live loop-closure smoke ✓ T4.
- **Fail-soft:** `notify_ellie_session_end` and `maybe_notify_ellie_session_end` both swallow all exceptions; the `shutdown_memory_provider` call site is additionally try/except-wrapped — three layers, because a shutdown must never raise.
- **marker correctness:** epoch-ms at session start → monotonic across sessions (CAS picks the newer digest), stable within a session (dedupe blocks double-fire). Documented why `len(history)` was rejected.
- **No new deps; no venv install** (httpx already present). Branch is the Phase 1 feature branch (not main).
- **Honesty:** Task 4 forbids claiming a pass that wasn't observed; the automated suite proves wiring, the smoke proves closure.
