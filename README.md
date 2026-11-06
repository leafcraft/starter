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

Everything is set in `.env` (create-leafmesh wrote it). The **whole flow runs on Tier 1
alone** against the seed system-of-record (`agency/_shared/store.py`); the
requester lookup uses a dev stand-in that **announces itself** (`available:false`)
for anyone not seeded, until you wire Tier 2.

### Tier 1 — required to boot (dev mode)
| Setting | For | Notes |
|---|---|---|
| `LEAFMESH_LICENSE_KEY` | LeafMesh runtime | **Required.** |
| `OPENAI_API_KEY` | Intake + Manager (`gpt-4o-mini`) | **Required** unless you change the models. |
| `REDIS_HOST` / `PORT` / `PASSWORD` | State store | Defaults to `localhost:6379`. Bring your own Redis, or let `create-leafmesh --start .` start one. |
| *(no setting)* — the reviewer | Human review | Answers in Studio's Inbox. To notify an external tool instead, create a vault connection (an "Add custom" record on the Infrastructure page, service type 'Outbound webhook') and set `webhook_config: {connection: <name>}` on the seat. |

### Tier 2 — real system-of-record connector (create the vault connection, uncomment the `mcp` block)
| Setting | Enables |
|---|---|
| vault record `crm_mcp` | Real requester lookups (CRM / helpdesk) instead of the seed store. Create it on Infrastructure → Integrations → MCP; URL + token are entered only there, never in config or `.env`. Its existence is also what tells `agency/tools.py` a real CRM is wired. |

> The block ships **commented** on `intake_agent` in the configuration:
> create the `crm_mcp` vault connection, then uncomment it — in Studio's raw YAML editor (see *Changing the configuration*). Until then the dev-store tool is the
> fallback contract.

### Tier 3 — a real delivery connector so the finisher *sends* resolutions to the customer (today it renders to `./out` and records a dev outbox; it never claims a send it didn't make).

## Run it

```bash
# First, in .env (create-leafmesh wrote it): fill at least Tier 1.

# With Docker — starts Redis, loads the team into it once, starts the agency:
create-leafmesh --start .

# Without Docker — your own Redis (REDIS_* in .env):
pip install -r requirements.txt          # core LeafMesh runs the pod day-0
create-leafmesh --load .                 # loads the team into that Redis (only if it is empty)
python main.py                           # API at http://127.0.0.1:18820/docs
```

API calls (from `/docs`, curl or a script) need your organisation's API key in the `X-API-Key` header: make one in Studio → API Keys → Generate Key, then `export LEAFCRAFT_API_KEY=<the key>` for the examples below. The agency itself runs without it.

Fire a request (day-0, against the seed store — no connector needed):

```bash
# routine → auto-resolved by the finisher
curl -X POST http://127.0.0.1:18820/api/mesh/request \
  -H "X-API-Key: $LEAFCRAFT_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"entry_point":"new_request",
       "data":{"source":"manual","message":"What are your opening hours?"}}'

# sensitive → forced to the reviewer (answer it in Studio → Inbox), then the finisher on approval
curl -X POST http://127.0.0.1:18820/api/mesh/request \
  -H "X-API-Key: $LEAFCRAFT_API_KEY" \
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
tuning form (D). Uncomment and rename one in Studio's raw YAML editor (or
`PUT /api/yaml/raw`), then run `leafmesh config check`.

> Packaging note: `pip install leafmesh` (core) includes all LLM providers and
> runs the pod. For the real CRM connector add `leafmesh[mcp]`. Avoid
> `leafmesh[all]` on Python 3.12+ (it pulls `cchardet`, which has no wheel) — add
> only the specific extras you need.

---

*Built with `create-leafmesh`. The config is the department; the PRD is the brief.*
*Design doctrine: `.claude/skills/leafmesh/building-agents-thoroughly.md`.*

## Changing the configuration

The agency's configuration lives in its store (Redis), not in a file: this project ships no configuration file. `create-leafmesh --start` loads the team's configuration into the store once, while the store is still empty (`leafmesh config import --if-empty`). `main.py` reads it from the store at start (`LeafMesh.from_store()`). A later start never replaces it, so what you change in Studio is kept.

To change it:

- **Studio** — its settings pages, or the raw YAML editor.
- **CLI** — `leafmesh config export > config.yaml`, edit it, then `leafmesh config import config.yaml` (it is checked before it is saved). `leafmesh config check`, `versions` and `rollback` check, list and restore versions.
- **API** — `PUT /api/yaml/raw` with an `X-API-Key` header and the body `{"yaml_content": "<the whole YAML>", "save_to_disk": true}`, or `PATCH /api/yaml/config` with `{"updates": {...}, "save_to_disk": true}`. Despite its name, `save_to_disk: true` saves the change to the store as a new version; without it the change is held only in memory and lost on restart.

Each save is a new version and applies live on every pod — no restart. (A few settings, such as brokers, make the agency reload itself in place within seconds.)

## Changing a running project (Docker)

What reaches a project that is already running (leafmesh 2.4.497). The
image holds the Python code (no configuration file); `.env` is passed in
when the container is created; the store (Redis) keeps the configuration
and the data on its own volume.

| You change | When it applies |
|---|---|
| An agent in Studio (prompt, model, tools, routes, human seats, schedules, …) | At once, no restart |
| A human seat's `channels` (Slack, email, …) | The agency reloads itself in place within seconds |
| Add or delete an agent in Studio | At once, including routes and schedules |
| A connection in the vault (model keys, MCP, webhooks, connectors, Slack, email) | At once. An agent switched off for a missing connection or address switches back on by itself |
| Anything in `.env` (licence, agency name, store, ports) | After `docker compose up -d` (the container is recreated) |
| Python code (`agency/*.py`: programmatic agents, tools, `@pre_compose`) | After a rebuild: `docker compose up -d --build` |
| The team's starting configuration | Loaded once by `create-leafmesh --start` into an empty store; after that, change it in Studio |
| Several app containers on one store | A Studio save reaches every one within about 15 seconds |

- Keep model keys in the vault. A key there wins over the same key in
  `.env` (the log warns), and a change applies at once. From 2.4.497 that
  holds for every value the vault holds (endpoints, organisation / project
  ids, cloud identities); the `.env` value returns when the record goes.
- Code the image does not have: an agent marked pure Python
  (`integration: python`) is switched off until its function is in the image;
  any other programmatic agent stays on, and each call to code it does not
  have fails. Rebuild the image with the code first.
- A new Redis volume is an empty store, so `create-leafmesh --start` loads
  the team again as version 1.
- **If the agency refuses to start after an upgrade** (a new leafmesh pin,
  then a rebuild: "Configuration has N error(s) in the stored
  configuration"), repair the stored configuration with the agency stopped:

  ```bash
  docker compose run --rm app leafmesh config check      # each problem, with its line
  docker compose run --rm app leafmesh config versions   # kept versions: which pass, which is in use
  docker compose run --rm app leafmesh config rollback   # back to the newest version that passes (saved as a new version)
  ```

  Or `leafmesh config export > config.yaml`, fix it by hand, then
  `leafmesh config import config.yaml` (it is checked before it is saved).

## Where the data store is set

From leafmesh 2.4.482 the store (Redis or Postgres) is set **only in `.env`** — never in the agency's configuration. A `persistence:` block in the YAML is ignored with a warning on leafmesh 2.4.482–2.4.485; from 2.4.486 the agency refuses to start if that block differs from `.env`, and names each `.env` line to add. The project's `.env` sets the store explicitly (`LEAFMESH_STORE`, `LEAFMESH_AGENCY_NAME`, `REDIS_*`).

- Redis (default): `REDIS_HOST`, `REDIS_PORT`, `REDIS_PASSWORD`, `REDIS_DB`; optional `REDIS_DEFAULT_TTL`, `REDIS_SESSION_TTL`, `REDIS_SSL*`, `REDIS_CLUSTER_NODES`.
- Postgres instead: `LEAFMESH_STORE=postgres` plus `POSTGRES_HOST`, `POSTGRES_PORT`, `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD` (optional `POSTGRES_SSLMODE`).
- Or the whole server in one value: `REDIS_URL=redis://user:pw@host:6379/0` (`rediss://` turns TLS on) or `DATABASE_URL=postgresql://user:pw@host:5432/db`. The single names fill in what the URL leaves out.
- With Docker Compose the app reaches Redis as `redis` (the service name); compose sets that for you.
- Check it in Studio → **Infrastructure → Datastores**: it shows whether the store is reachable (never the address or password).

## This mesh's sign-in (leafmesh 2.4.497)

From leafmesh 2.4.497 each mesh signs in to LeafCraft with its own key, not
a key shared by every install.

- **First start.** The mesh makes a key pair and registers it with
  `LEAFMESH_LICENSE_KEY` and `LEAFMESH_ENV_TOKEN` from `.env` (copy the
  environment token from Studio — a placeholder such as `development` is
  refused). With both valid it works at once. If your organisation turned on
  "require approval", the first start stops and says so: approve it in
  Studio → **Keys → SDK access**, then start again. Organisation admins get an
  email for every new registration.
- **Where the key lives.** In the vault, in the store, encrypted with
  `LEAFMESH_VAULT_KEY`: it survives rebuilds and every copy of the app shares
  it. A new Redis volume, or a new vault key, makes a new key pair that
  registers again — revoke the old one in Studio.
- **Check or change it** (in Docker: `docker compose run --rm app leafmesh auth status`):
  - `leafmesh auth status` — credential id, key fingerprint, registration and
    mode, never a key; `--check` signs in now and reports the tokens.
  - `leafmesh auth register` — register now.
  - `leafmesh auth rotate` — a new key pair: once it is active the mesh
    switches to it and revokes the old one. A revoked or expired key is never
    revived; rotate instead.
- **Lost the environment token?** From 5 Dec 2026 Studio shows the licence
  key and environment token only once, when they are made (then only a hint).
  Rotate the environment token in Studio and put the new one in `.env`.
  Rotating it changes where the agency's data is kept in the store, so do it
  before the agency holds data.
- **An existing project whose `.env` says `LEAFMESH_ENV_TOKEN=development`.**
  2.4.497 needs the real token. The token also names where the agency's data
  sits in the store, so with the real token the agency starts on an empty
  store (vault, sessions, board) — the old data stays under the old name. Set
  the real token before you put data in the agency, or contact us to move it.

## Your vault key — back it up

`create-leafmesh` put a `LEAFMESH_VAULT_KEY` in your `.env` when it made this project. It is the master key that encrypts every connection and credential you store in the vault (in Redis / Postgres).

- **Back it up like a master password.** Lose it and every stored connection has to be entered again.
- **Never change or regenerate it** for an existing project — a new key locks the existing vault. To change it, use `leafmesh vault rotate-key`.
- Every copy of the app (every replica) must get the **same** value. Docker Compose passes it in from `.env` as an environment variable.
- Never commit `.env` (it is already in `.gitignore`).
