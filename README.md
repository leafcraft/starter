# starter — Starter Mesh

A **blank canvas** for building a LeafMesh agent mesh from scratch. It
ships a tiny, working 3-agent mesh and — more importantly — a
`configs/config.yaml` written as a guided tutorial. Read that file top
to bottom; this README is the 5-minute quick start.

> New here? This is the template to pick when none of the business
> templates (finance-ops, customer-support, …) match what you're
> building. Start from this and grow it into your own department.

## What's in the box

```
configs/config.yaml     ← the mesh + the tutorial (READ THIS)
main.py                 ← boots the mesh, registers the audit sink
agency/_shared/         ← the WORM audit sink (the only Python shipped)
validate_config.py      ← pre-flight checker — run before main.py
env                     ← copy to .env and fill in
Dockerfile / compose    ← container assets
tests/                  ← a config-shape test you can extend
```

The mesh itself is three agents:

| Agent | Kind | Role |
|---|---|---|
| `intake_agent` | LLM | Reads a request, classifies it, decides if a human is needed |
| `reviewer_human` | Human | Approves/rejects sensitive requests (HITL gate) |
| `audit_logger_agent` | External | Hash-chained, append-only audit log (terminus) |

Routine requests: `intake → audit`. Sensitive ones: `intake → reviewer → audit`.

## Run it

```bash
pip install -r requirements.txt

# state store
docker run -d -p 6379:6379 redis:7-alpine

# config
cp env .env        # then edit: LEAFMESH_LICENSE_KEY, OPENAI_API_KEY

# pre-flight — catches YAML / wiring / contract mistakes before boot
python validate_config.py

# go — API + docs at http://127.0.0.1:18820/docs
python main.py
```

Fire a request (new terminal):

```bash
# routine → answered + logged, no human
curl -X POST http://127.0.0.1:18820/api/mesh/call \
  -H "Content-Type: application/json" \
  -d '{"entry_point":"new_request",
       "input_data":{"source":"manual","message":"What are your hours?"}}'

# sensitive → parked at the reviewer (approve it from the Studio inbox)
curl -X POST http://127.0.0.1:18820/api/mesh/call \
  -H "Content-Type: application/json" \
  -d '{"entry_point":"new_request",
       "input_data":{"source":"manual","message":"Please refund order 1234"}}'
```

Watch the audit trail build:

```bash
tail -f logs/audit.jsonl
```

## How to grow it

Everything you add is a few lines of YAML. The config file has three
ready-to-uncomment patterns:

- **PATTERN A — a second LLM agent.** Add a teammate (e.g. a reply
  writer) and a `can_call` wire to hand off to it.
- **PATTERN B — a connector agent.** Point an agent at *your* system of
  record (CRM/ERP/ticketing) via `integration: mcp` (or zapier / n8n /
  composio). No Python — the mesh never keeps a private copy of your data.
- **PATTERN C — a scheduled agent.** Give an agent a `wake_up:` cron and
  a matching entry point for time-driven work.

The golden rules (from the LeafMesh skill):

1. **One role, multiple responsibilities** — an agent is a person you'd
   hire. Don't split one job across two agents.
2. **Wires are the policy** — put routing rules in `can_call` conditions
   where anyone can read them, not in code.
3. **YAML-first** — reach for a Python module only for actuators with
   side effects, domain math that must not be hallucinated, or controls
   like the audit sink. If you find yourself writing glue, the SDK
   probably already does it.

After any change: `python validate_config.py` → `python main.py`.

## Deploy

When you're ready for the cloud, the bundled `leafmesh-deploy` pushes
this project to AWS / Azure / GCP:

```bash
leafmesh-deploy --plan          # see what would be created
leafmesh-deploy --apply         # build + deploy
```

---

*Built with `create-leafmesh`. The config is the department.*
