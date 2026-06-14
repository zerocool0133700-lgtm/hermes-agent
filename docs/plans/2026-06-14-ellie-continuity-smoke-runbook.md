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

**2026-06-14 — NOT YET EXECUTED.** Reachability checked: Forest bridge `:3001` is **up**; `:3002` is occupied by the existing (non-continuity) gateway; Hermes config is currently `backend: local` (not `ellie`). Executing the smoke requires: building/running a continuity-enabled gateway on a spare port, a throwaway `users.id` UUID, temporarily repointing Hermes to `backend: ellie`, and writing to the Forest (billing a real LLM). Deferred pending Dave's go-ahead and choice of target Forest/scope. **No pass has been observed; the loop is proven only at the wiring level so far.**
