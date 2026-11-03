# starter — Starter Pod

The **smallest honest LeafMesh pod**: a triage specialist, a human review gate, a
finisher that produces the real artifact, and a WORM audit terminus — watched by
a supervisor. Not a pipeline; a team. Clone it, rename the roles, and grow your
own department without unlearning anything.

**Read `PRD.md`** for the full agent-by-agent spec. This is a **pod-standard
skeleton** (leafmesh 2.4.486): every wire is conditional, the human gate never
approves on silence, the finisher fails closed, and every decision ends in the
audit sink.

## Story

A support inbox at a mid-size SaaS receives a message: *"I was charged twice for
my May invoice — please refund one."* It enters at the `new_request` door.
**Intake** looks the sender up in the CRM (`a.rivera@example.com` → Ana Rivera,
Brightwater Logistics, enterprise tier, invoice INV-2026-0518 flagged as charged
twice), reads the *intent* — this is money, not a question — and classifies it
`refund / needs_human: true`. Its fail-closed floor would have forced a human
even if the model had waffled. The request is stashed and handed to
**reviewer_human**, who gets it in Studio's Inbox and answers
`approve`. The **resolver** (the finisher) recovers the request across the gate,
re-checks that a human *actually* approved (an unknown or missing verdict would
block), confirms there is a real reply to issue, renders
`./out/req-…_resolution.md`, records the send in the dev outbox, and writes a
hash-chained entry to the **audit log**. A second message the same morning —
*"what are your opening hours?"* — is classified `question / needs_human: false`,
skips the human, and the finisher issues it directly against the auto-resolvable
allowlist. If the reviewer had not answered the refund within 24 hours, nothing
would have gone out: the Inbox card closes, the ticket records that no reply came,
and nobody is chased automatically. Silence never approves anything.

## Why it works in an organization

A shared inbox mixes trivial questions with money and complaints, and the cost of
treating them alike runs both ways: routine asks wait behind a human, and
sensitive ones get answered without one. This pod separates them **safely**: the
triage decision is a *safety* decision that fails closed — money, complaints, high
priority and low confidence (below 0.7) always reach a person; only genuinely
routine items auto-resolve, and only when there is a real reply to send. The reviewer is a first-class member,
not a rubber stamp, and **silence never advances a request**. The finisher never
trusts that reaching it means "approved" — it re-derives authorisation in code and
**deletes a half-written artifact** if its floor trips, so a partial resolution
never escapes. Every decision — issued, blocked, rejected — is tamper-evident in a
WORM ledger. ROI: routine deflection with zero risk of auto-resolving something
that needed judgment, and a complete audit trail for compliance.

## The team (4 members + supervisor)

| Agent | Role (human job title) | Responsibilities | Can perform |
|---|---|---|---|
| `intake_agent` | Intake & Triage Officer | Reads each incoming request, looks the requester up in the system of record, classifies it, and decides — failing closed — whether a human must see it | LLM (chain) + **playbook** (triage craft, loaded on demand) + dev-store `lookup_requester` tool; `@chain` **triage floor** forces a human on a refund/complaint, high priority, confidence below 0.7, or a routine item with no draft, and stashes the request for the finisher |
| `reviewer_human` | Support Team Lead — request reviewer & accountable owner (Human) | Approves or declines sensitive requests before any reply goes out; owns everything that leaves the pod. Answers within one business day (24 h) | Human gate (Studio Inbox, dual boundary); replies `approve` / `reject`; **never approves on silence** — after 24 h the card closes unanswered (see *If nobody answers*); also the Manager's escalation target |
| `resolver_agent` | Resolution Finisher | Produces the real resolution artifact only when genuinely authorised, then records it | Programmatic **finisher**: approve-token allowlist + block-token denylist + auto-resolvable-category allowlist (fail closed on unknown) → invariants → render to `./out` → **delete-on-block** → dev-store outbox + ledger |
| `audit_logger_agent` | Compliance Recorder (WORM) | Hash-chains every issued resolution, rejection, and held gate | External (custom sink), registered via `sdk.intelligence()`; terminus — `can_call: []` |

The **LeafMesh Manager** supervises (static routing; this is a control path). On
leafmesh 2.4.486 it escalates to the Reviewer only when an agent hits an error
retrying cannot fix (auth, bad request, out of credit, bad config), when 2
different agents fail in one session (`max_errors_per_session: 2`), or when an
agent's restarts are used up. A broken output contract only alerts people.

### If nobody answers

`reviewer_human` waits 24 hours (`human_timeout_seconds: 86400`). If nobody
answers, the request waits no longer: its Inbox card closes and the ticket records
that no reply came. Nothing is sent or approved on silence, and nobody is chased
automatically — the Manager does not escalate an unanswered question. The seat's
`fallback_response` (`held_for_review`, which matches the route to audit) is kept
as the declared intent; on 2.4.486 a dual seat's timeout does not send it on. A
real support team would escalate an unanswered refund to the **Support Manager**
after one business day; that route is not wired yet.

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
| *(no setting)* — the reviewer | Human review | Answers in Studio's Inbox. To notify an external tool instead, create a vault connection (an "Add custom" record on the Infrastructure page, service type 'Outbound webhook') and set `webhook_config: {connection: <name>}` on the seat. |

### Tier 2 — real system-of-record connector (create the vault connection, uncomment the `mcp` block)
| Setting | Enables |
|---|---|
| vault record `crm_mcp` | Real requester lookups (CRM / helpdesk) instead of the seed store. Create it on Infrastructure → Integrations → MCP; URL + token are entered only there, never in config or `.env`. Its existence is also what tells `agency/tools.py` a real CRM is wired. |

> The block ships **commented** on `intake_agent` in `configs/config.yaml`:
> create the `crm_mcp` vault connection, then uncomment it — in the file before
> the first start, in Studio's YAML editor after it (see *Changing the
> configuration after the first start*). Until then the dev-store tool is the
> fallback contract.

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

# sensitive → forced to the reviewer (answer it in Studio → Inbox), then the finisher on approval
curl -X POST http://127.0.0.1:18820/api/mesh/request \
  -H "Content-Type: application/json" \
  -d '{"entry_point":"new_request",
       "data":{"source":"email","requester":"a.rivera@example.com",
               "message":"I was charged twice — please refund one."}}'
```

On an issued resolution the finisher writes `./out/<request_id>_resolution.md` and
appends `./data/resolution_ledger.json`; every decided path lands in `./logs/audit.jsonl`.

### Seed data (day 0)

`agency/_shared/store.py` seeds six fictional customer accounts so the lookup has
real-looking records to read (by email or full name):

| requester | Account (lookup returns) | Try it with |
|---|---|---|
| `a.rivera@example.com` | Brightwater Logistics, enterprise, USD 4,800/mo; INV-2026-0518 charged twice | "Please refund the duplicate charge" → refund → reviewer (floor) |
| `m.osei@example.com` | Osei & Partners Architects, standard, no open tickets | "What are your support hours?" → routine → finisher |
| `l.chen@example.com` | Fernhill Dental Group, standard, 3 open tickets on calendar sync | "Third time asking, sync is still broken" → complaint → reviewer (floor) |
| `r.haddad@example.com` | Cedar Point Retail, enterprise, credit hold, INV-2026-1004 19 days overdue | A billing question — the model sees the hold in the lookup |
| `s.novak@example.com` | Novak Bakery Co., 14-day trial, no history | A first question from a new customer |
| `j.okafor@example.com` | Okafor Freight Brokers, standard, 1 open ticket | "Change our billing contact" |

The floor guarantees only the money / complaint / high-priority / low-confidence
rules; for the rest, intake's model decides and the finisher re-checks.
Anyone else (or a name that is not seeded) returns `available: false` with the
reason — never an invented record.

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
worker with `scaling.copies` + an atomic claim tool (B), a scheduled `wake_up` agent
with a `timezone` (C), and turning a specialist into a `super_agent` with the dict
tuning form (D). Before the first start: uncomment, rename, re-run
`validate_config.py`. After it, make the same change in Studio's YAML editor
(or `PUT /api/yaml/raw`) — editing the file then is not applied.

> Packaging note: `pip install leafmesh` (core) includes all LLM providers and
> runs the pod. For the real CRM connector add `leafmesh[mcp]`. Avoid
> `leafmesh[all]` on Python 3.12+ (it pulls `cchardet`, which has no wheel) — add
> only the specific extras you need.

---

*Built with `create-leafmesh`. The config is the department; the PRD is the brief.*
*Design doctrine: `.claude/skills/leafmesh/building-agents-thoroughly.md`.*

## Changing the configuration after the first start

`configs/config.yaml` is only the first-start seed. On the first start (an empty store) the agency imports it as version 1 and from then on keeps its configuration in the store. After that the file is not read again: an edit to it is **not** applied, even after a restart (the boot log says "that edit was NOT applied").

To change a running agency:

- **Studio** — its settings pages, or the raw YAML editor.
- **API** — `PUT /api/yaml/raw` with an `X-API-Key` header and the body `{"yaml_content": "<the whole YAML>", "save_to_disk": true}`, or `PATCH /api/yaml/config` with `{"updates": {...}, "save_to_disk": true}`.

Each save is a new version and applies live on every pod — no restart. (A few settings, such as brokers, make the agency reload itself in place within seconds.) So wherever this README or a comment says "uncomment X in `configs/config.yaml`", do it in the file before the first start, or in Studio's YAML editor after it.

## Where the data store is set

From leafmesh 2.4.482 the store (Redis or Postgres) is set **only in `.env`** — never in `configs/config.yaml`. A `persistence:` block in the YAML is ignored with a warning on leafmesh 2.4.482–2.4.485; from 2.4.486 the agency refuses to start if that block differs from `.env`, and names each `.env` line to add. The project's `.env` sets the store explicitly (`LEAFMESH_STORE`, `LEAFMESH_AGENCY_NAME`, `REDIS_*`).

- Redis (default): `REDIS_HOST`, `REDIS_PORT`, `REDIS_PASSWORD`, `REDIS_DB`; optional `REDIS_DEFAULT_TTL`, `REDIS_SESSION_TTL`, `REDIS_SSL*`, `REDIS_CLUSTER_NODES`.
- Postgres instead: `LEAFMESH_STORE=postgres` plus `POSTGRES_HOST`, `POSTGRES_PORT`, `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD` (optional `POSTGRES_SSLMODE`).
- Or the whole server in one value: `REDIS_URL=redis://user:pw@host:6379/0` (`rediss://` turns TLS on) or `DATABASE_URL=postgresql://user:pw@host:5432/db`. The single names fill in what the URL leaves out.
- With Docker Compose the app reaches Redis as `redis` (the service name); compose sets that for you.
- Check it in Studio → **Infrastructure → Datastores**: it shows whether the store is reachable (never the address or password).

## Your vault key — back it up

`create-leafmesh` put a `LEAFMESH_VAULT_KEY` in your `.env` when it made this project. It is the master key that encrypts every connection and credential you store in the vault (in Redis / Postgres).

- **Back it up like a master password.** Lose it and every stored connection has to be entered again.
- **Never change or regenerate it** for an existing project — a new key locks the existing vault. To change it, use `leafmesh vault rotate-key`.
- Every copy of the app (every replica) must get the **same** value. Docker Compose passes it in from `.env` as an environment variable.
- Never commit `.env` (it is already in `.gitignore`).
