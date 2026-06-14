# Ellie⟶Hermes continuity — live loop-closure smoke runbook

The automated suites (Ellie PR #64, Hermes Plan B Tasks 1–3) prove the **wiring**: the turn carries a `conversation_id`, the digest reads/writes with compare-and-set, distillation writes via `MemoryWriter`, recall reads under a timeout. They do **not** prove the loop **closes** — that a fact distilled at session end is actually retrievable by recall in a later session. Only this smoke, against the real Forest + a real LLM, proves that.

> ⚠️ **Side effects.** This writes real distilled memories into the Forest knowledge graph and bills a real LLM (Anthropic OAuth). Run it against an **isolated scope** (or a throwaway user) unless you intend to seed Dave's live `2/1`. See "Isolation" below.

## Preconditions
- Forest bridge reachable at `http://localhost:3001` (the relay/V3 bridge). Verify: `curl -s -o /dev/null -w '%{http_code}' http://localhost:3001/api/bridge/read -X POST -H 'content-type: application/json' -H 'x-bridge-key: <key>' -d '{"query":"ping","scope_path":"2/1"}'` → `200`.
- An Ellie gateway built from `feat/ellie-hermes-memory` (PR #64).
- A real `users.id` UUID to act as `ELLIE_GATEWAY_USER_ID` (the identity the digest + Forest writes are scoped to). For an isolated run, create/seed a throwaway user.
- Hermes on `feat/ellie-sidecar-bridge`.

## Isolation (recommended)
Point read **and** write at the same throwaway scope so the smoke is self-contained and never touches `2/1`. Because `continuity_write_scope` defaults to `forest_read_scope`, setting just the read scope aligns both:
```
ELLIE_FOREST_READ_SCOPE=2/2/smoke          # any scope you can later delete
# continuity_write_scope auto-defaults to 2/2/smoke → loop still closes
```
(If you instead want to exercise the true default `2/1`, omit this — but then the planted facts land in Dave's live graph.)

## 1. Start a continuity-enabled gateway on a SPARE port
`:3002` is already occupied by the prod gateway — use a spare (e.g. `:3099`).
```bash
cd /home/ellie/L2/ellie
ELLIE_GATEWAY_BIND=127.0.0.1:3099 \              # confirm the real bind env var name in PR #64 config.rs
ELLIE_GATEWAY_TOKEN=smoke-token \
ELLIE_FOREST_BASE_URL=http://localhost:3001 \
ELLIE_FOREST_BRIDGE_KEY=<bridge-key> \
ELLIE_FOREST_LOOP_ENABLED=1 \
ELLIE_WRITE_BACK_ENABLED=1 \
ELLIE_FOREST_READ_SCOPE=2/2/smoke \
ELLIE_GATEWAY_USER_ID=<throwaway users.id uuid> \
cargo run -p ellie-gateway
```
Verify continuity is live: `curl -s http://localhost:3099/metrics | grep gateway_continuity` → counters present at 0.

## 2. Point Hermes at it (temporary config)
In `~/.hermes/config.yaml` under `agent:` (back up first):
```yaml
agent:
  backend: ellie
  ellie_sidecar_url: http://127.0.0.1:3099
  ellie_sidecar_token: smoke-token
```

## 3. Session 1 — plant a durable fact
Run one Hermes conversation where the user states something durable and specific, e.g.:
> "For the record: I always deploy on Fridays, never on Mondays."

Let the turn complete, then **end the session** (CLI exit / `/reset`, or close the gateway conversation) so `shutdown_memory_provider` fires `notify_ellie_session_end`.

Confirm session-end fired:
```bash
curl -s http://localhost:3099/metrics | grep -E 'continuity_session_end|continuity_distill_writes'
# EXPECT: continuity_session_end{result="ok"} >= 1 ; continuity_distill_writes >= 1
```

## 4. Verify the distill landed in the Forest (read it back directly)
```bash
curl -s -X POST http://localhost:3001/api/bridge/read \
  -H 'content-type: application/json' -H 'x-bridge-key: <bridge-key>' \
  -d '{"query":"when does the user deploy","scope_path":"2/2/smoke"}' | python3 -m json.tool
# EXPECT: a memory mentioning "Fridays".
```

## 5. Session 2 — confirm recall surfaces it (the loop closes)
Start a **new** Hermes conversation (a fresh `conversation_id` is fine — recall is user-scoped, not conversation-scoped) and ask:
> "When do I usually deploy?"

Confirm in the gateway logs / response that the turn was primed with the `<recalled-memory>` preamble and Ellie answers "Fridays."
```bash
curl -s http://localhost:3099/metrics | grep continuity_recall_injected
# EXPECT: continuity_recall_injected >= 1
```

## Pass criteria
A fact stated in session 1 is (a) present in the Forest after session-end (step 4) **and** (b) surfaced via recall in session 2 (step 5). That is the loop closing end-to-end.

## Teardown
- Restore `~/.hermes/config.yaml` (`backend` back to its original value).
- Stop the spare gateway.
- If run against a throwaway scope/user, delete the seeded memories (or leave the scope for re-runs).

---

## Run log

**2026-06-14 — PASS (loop closed end-to-end).** Run against an isolated `2/2/smoke` scope with a throwaway user UUID, a continuity-enabled gateway (built from Ellie `feat/ellie-hermes-memory`) on `:3099`, provider=anthropic / claude-sonnet-4-6. Driven directly against the gateway HTTP API with `curl` (the Hermes-side calls that produce these requests are unit-proven in `tests/agent/test_ellie_bridge.py`; the unproven part was the Ellie-side distill→Forest→recall round-trip).

- **Session 1** — `POST /api/session-end` (conversation `smoke-sess-1`, marker 1) with a user turn stating *"I always deploy on Fridays, never Mondays."* → `202`. Spawned task ran: `gateway_continuity_session_end{result="ok"} 1`, `gateway_continuity_distill_writes 1`.
- **Forest verify** — bridge read at `2/2/smoke` returned a gateway-distilled memory created at the session-end time: *"Deployment day preferences: Always deploys on Fridays. Never deploys on Mondays."* (the `{title}: {content}` shape from `distill_to_forest`).
- **Session 2** — `POST /api/turn` (new conversation `smoke-sess-3`, empty history) asking *"which day do I always deploy on, and which do I never deploy on?"* → the turn was primed by the continuity preamble (`gateway_continuity_recall_injected 1`) and Ellie answered: *"Based on what's in your Forest memory: Always deploy on: Friday, Never deploy on: Monday."*

**Pass criteria met:** a fact stated in session 1 was distilled to the Forest at session-end AND surfaced via recall in a later, different session.

**Bug found & fixed by this smoke:** the first attempt used `recall_timeout_ms=250` (the original spec default). The first (cold) Forest recall exceeded 250ms, so the preamble silently timed out — `gateway_continuity_recall_timeout 1`, `recall_injected 0`, and the turn fell back to the agent's own recall tool and answered "I don't have that on record." Warm recall measured ~157ms; cold exceeded 250ms. Re-running with `ELLIE_RECALL_TIMEOUT_MS=3000` closed the loop. The default was raised to **2000ms** in Ellie PR #64 (`fix(continuity): raise recall_timeout_ms default 250→2000`).

**Teardown:** gateway stopped; Hermes config was never modified (drove via curl). Two smoke memories remain in the isolated `2/2/smoke` scope (the bridge has no delete endpoint); they are never read by `2/1` — delete via DB if desired: probe `c98865e0-7edd-4ded-8fe2-36eed03c4c4f` + the distilled "Deployment day preferences" memory.
