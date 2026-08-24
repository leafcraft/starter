# starter — Starter Pod

The **smallest honest LeafMesh pod**: a triage specialist, a human review gate, a
finisher that produces the real artifact, and a WORM audit terminus — watched by
a supervisor. Not a pipeline; a team. Clone it, rename the roles, and grow your
own department without unlearning anything.

**Read `PRD.md`** for the full agent-by-agent spec. This is a **pod-standard
skeleton** (SDK 2.4.131): every wire is conditional, the human gate default-denies
on silence, the finisher fails closed, and the audit sink is the terminus of every
path.

## Story

A support inbox at a mid-size SaaS receives a message: *"I was charged twice for
my May invoice — please refund one."* It enters at the `new_request` door.
**Intake** looks the sender up in the CRM (`a.rivera@example.com` → enterprise
tier), reads the *intent* — this is money, not a question — and classifies it
`refund / needs_human: true`. Its fail-closed floor would have forced a human
even if the model had waffled. The request is stashed and handed to
**reviewer_human**, who gets a notification in their channel and replies
`approve`. The **resolver** (the finisher) recovers the request across the gate,
re-checks that a human *actually* approved (an unknown or missing verdict would
block), confirms there is a real reply to issue, renders
`./out/req-…_resolution.md`, records the send in the dev outbox, and writes a
hash-chained entry to the **audit log**. A second message the same morning —
*"what are your opening hours?"* — is classified `question / needs_human: false`,
skips the human, and the finisher issues it directly against the auto-resolvable
allowlist. If the reviewer had gone silent on the refund overnight, the gate would
have *default-denied*: the request lands in the audit log as `held_for_review`,
never auto-approved.

## Why it works in an organization

A shared inbox mixes trivial questions with money and complaints, and the cost of
treating them alike runs both ways: routine asks wait behind a human, and
sensitive ones get answered without one. This pod separates them **safely**: the
triage decision is a *safety* decision that fails closed — money, complaints, and
low confidence always reach a person; only genuinely routine items auto-resolve,
and only when there is a real reply to send. The reviewer is a first-class member,
not a rubber stamp, and **silence never advances a request**. The finisher never
trusts that reaching it means "approved" — it re-derives authorisation in code and
**deletes a half-written artifact** if its floor trips, so a partial resolution
never escapes. Every outcome — issued, rejected, or held — is tamper-evident in a
WORM ledger. ROI: routine deflection with zero risk of auto-resolving something
that needed judgment, and a complete audit trail for compliance.

## The team (4 members + supervisor)

| Agent | Role (human job title) | Responsibilities | Can perform |
|---|---|---|---|
| `intake_agent` | Intake & Triage Officer | Reads each incoming request, looks the requester up in the system of record, classifies it, and decides — failing closed — whether a human must see it | LLM (chain) + **playbook** (triage craft, loaded on demand) + dev-store `lookup_requester` tool; `@chain` **triage floor** forces a human on sensitive/high/low-confidence and stashes the request for the finisher |
| `reviewer_human` | Request Reviewer & Accountable Owner (Human) | Approves or declines sensitive requests before any reply goes out; owns everything that leaves the pod | Human gate (webhook, dual boundary); **default-deny** on timeout → `held_for_review` routed to audit; also the Manager's escalation target |
| `resolver_agent` | Resolution Finisher | Produces the real resolution artifact only when genuinely authorised, then records it | Programmatic **finisher**: approve-token allowlist + block-token denylist + auto-resolvable-category allowlist (fail closed on unknown) → invariants → render to `./out` → **delete-on-block** → dev-store outbox + ledger |
| `audit_logger_agent` | Compliance Recorder (WORM) | Hash-chains every issued resolution, rejection, and held gate | External (custom sink), registered via `sdk.intelligence()`; terminus — `can_call: []` |

The **LeafMesh Manager** supervises — it reads every hand-off and escalates
stalls, gate timeouts, and contract violations to the Reviewer automatically
(static routing; this is a control path).

## Configuration — what to set, in three tiers

Everything is set in `.env` (`cp env .env`). The **whole flow runs on Tier 1
alone** against the seed system-of-record (`agency/_shared/store.py`); the
requester lookup uses a dev stand-in that **announces itself** (`available:false`)
for anyone not seeded, until you wire Tier 2.

### Tier 1 — required to boot (dev mode)
| Setting | For | Notes |
|---|---|---|
| `LEAFMESH_LICENSE_KEY` | LeafMesh runtime | **Required.** |
| `OPENAI_API_KEY` | Intake + Manager (`gpt-4o-mini`) | **Required** unless you change the models. |
| `REDIS_HOST` / `PORT` / `PASSWORD` | State store | Defaults to `localhost:6379`. `docker run -d -p 6379:6379 redis:7-alpine`. |
| `HITL_OUTBOUND_URL` | Where the reviewer is notified | Defaults to a local stub. |

### Tier 2 — real system-of-record connector (set the URL, uncomment the `mcp` block)
| Setting | Enables |
|---|---|
| `CRM_MCP_URL` / `CRM_MCP_TOKEN` | Real requester lookups (CRM / helpdesk) instead of the seed store |

> ⚠️ The SDK **rejects an `mcp` block with an empty URL at load**, so the block
> ships **commented** on `intake_agent` in `configs/config.yaml`. Fill the URL,
> then uncomment. Until then the dev-store tool is the fallback contract.

### Tier 3 — a real delivery connector so the finisher *sends* resolutions to the customer (today it renders to `./out` and records a dev outbox; it never claims a send it didn't make).

## Run it

```bash
pip install -r requirements.txt          # core LeafMesh runs the pod day-0
docker run -d -p 6379:6379 redis:7-alpine
cp env .env                              # fill at least Tier 1
python validate_config.py                # pre-flight: wiring, yields, dead-code
python main.py                           # API at http://127.0.0.1:18820/docs
```

Fire a request (day-0, against the seed store — no connector needed):

```bash
# routine → auto-resolved by the finisher
curl -X POST http://127.0.0.1:18820/api/mesh/request \
  -H "Content-Type: application/json" \
  -d '{"entry_point":"new_request",
       "data":{"source":"manual","message":"What are your opening hours?"}}'

# sensitive → forced to the reviewer, then the finisher on approval
curl -X POST http://127.0.0.1:18820/api/mesh/request \
  -H "Content-Type: application/json" \
  -d '{"entry_point":"new_request",
       "data":{"source":"email","requester":"a.rivera@example.com",
               "message":"I was charged twice — please refund one."}}'
```

On an issued resolution the finisher writes `./out/<request_id>_resolution.md` and
appends `./data/resolution_ledger.json`; every path lands in `./logs/audit.jsonl`.

## Test it

```bash
pip install pytest pyyaml
pytest                                   # structural invariants + fail-closed floors
```

`tests/test_config_shape.py` checks the wiring and controls; `tests/test_finisher.py`
drives the intake floor and the finisher directly (no LLM, no Redis) and asserts
they fail closed — the worked example of testing a control at the layer that
decides behaviour.

## Grow into it

The config's foot carries four commented **patterns to grow into**, each a modern
capability shown in place: a second specialist (Pattern A), a fanned-out backlog
worker with `instances` + an atomic claim tool (B), a scheduled `wake_up` agent
with a `timezone` (C), and turning a specialist into a `super_agent` with the dict
tuning form (D). Uncomment, rename, re-run `validate_config.py`.

> Packaging note: `pip install leafmesh` (core) includes all LLM providers and
> runs the pod. For the real CRM connector add `leafmesh[mcp]`. Avoid
> `leafmesh[all]` on Python 3.12+ (it pulls `cchardet`, which has no wheel) — add
> only the specific extras you need.

---

*Built with `create-leafmesh`. The config is the department; the PRD is the brief.*
*Design doctrine: `.claude/skills/leafmesh/building-agents-thoroughly.md`.*
