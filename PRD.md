# PRD — starter — Starter Pod

## Overview / Story

The starter is a **teaching skeleton built to the pod standard**: the smallest
LeafMesh department that is still a *team*, not a pipeline. It runs a generic
request-triage operation — the shape under most support, intake, and
request-handling workflows — so you can clone it, rename the roles to your domain,
and keep every property that makes a pod safe.

A request arrives at one of several doors. The **intake officer** (an LLM with a
fail-closed floor) looks the requester up in the system of record, reads the
*intent*, and classifies it. Its `@chain` floor is the point of the whole design:
a sensitive category (money, a complaint), a high priority, a confidence below 0.7,
or a routine item with no draft is FORCED to a human regardless of what the model
said, and the request is stashed so it survives the human gate. Routine items with a real reply go straight
to the **resolution finisher**; sensitive ones go to **reviewer_human** first. The
finisher never trusts that reaching it means "approved" — it re-derives
authorisation in code, enforces invariants a prompt can't waive, renders the real
artifact to `./out`, and **deletes it on a tripped floor**. Every decided
path — issued, blocked, rejected, held — is recorded in a hash-chained WORM
ledger. The **Manager** supervises and escalates real failures (an error retrying
cannot fix, 2 agents failing in one session, restarts used up) to the reviewer.
A request nobody answers is not escalated: after 24 hours its Inbox card closes
and the ticket records that no reply came.

## Why it works in an organization

The triage decision is treated as a **safety** decision, not a convenience one, so
the failure mode that matters — auto-resolving something that needed judgment —
cannot happen quietly: it fails closed to a human. Routine work still deflects
without a person. The reviewer is a first-class member and **silence never
advances a request**: nothing is sent or approved without a person's answer. The finisher's two-layer defense (body
short-circuits; `@chain` floor re-checks independently) means a partial artifact
never escapes. And because the whole thing runs day-0 against a dev store that
*announces itself*, a team can adopt the shape before wiring a single connector.

## Flow diagram

```
 new_request ─┐
 direct_call ─┤──> intake_agent ──(needs_human == false)──> resolver_agent ─┐
              │    (LLM triage;                                 (FINISHER)   │
              │     @chain floor                                             │
              │     fails closed;         (needs_human == true)             │
              │     CRM lookup;                    │                        │
              │     playbook)                      ▼                        │
              │                              reviewer_human  (HITL,          │
 reviewer_reply ─────────────────────────>  dual boundary,   never approves │
   (HITL resume)                             Inbox)           on silence)    │
                                                │                            │
                              ('approve')───────┼───────> resolver_agent ────┤
                                                │          (re-check         │
                              ('reject' /       │           approve token,   │
                               'held_for_review')          invariants,       │
                                                │           render ./out,    │
                                                ▼           delete-on-block) │
                                        audit_logger_agent <─────────────────┘
                                        (WORM terminus, can_call: [])

 SUPERVISOR: the LeafMesh Manager watches every hand-off; an error retrying
 cannot fix, 2 failed agents in a session, or restarts used up escalate to
 reviewer_human (static routing). Contract violations only alert people. An
 unanswered gate is not escalated (2.4.486): after 24 h its card closes and
 nothing is sent.
```

The only cycle is the Manager's escalation back-edge, bounded by
`auto_escalate.max_retries` / `max_errors_per_session`; the
intake self-correction loop is bounded by `enforce_yields_retry`. Work flows
forward, every branch terminates in audit.

## Actor inventory

### AI agents (members)

**`intake_agent` — Intake & Triage Officer** (LLM, `chain`, `gpt-4o-mini`)
- One job: classify an incoming request and decide, fail-closed, if a human must
  see it. (No "and" — it does not resolve, approve, or send.)
- Tools: `lookup_requester` (dev-store CRM stand-in, category `intake`,
  announces `available:false` for unknown requesters).
- Playbook: `triage` — only the `description` is resident; the craft body
  (`responsibility`) loads on demand. Demonstrates the per-agent playbook
  registry (requires `leafmesh>=2.4.130`).
- Backing module `agency/intake_agent.py`: `@chain(enforce_triage_floor)`.
  Forces `needs_human` on sensitive categories / high priority / confidence
  below `MIN_CONFIDENCE` (0.7; a missing confidence counts as 0) / no-draft;
  normalises the yields contract; mints a `request_id` if missing; stashes the
  request (session stash + dev store) for the finisher to recover post-gate.
- Wires: `needs_human == true → reviewer_human`; `needs_human == false →
  resolver_agent`.

**`resolver_agent` — Resolution Finisher** (programmatic, `chain`)
- One job: produce the real resolution artifact only when genuinely authorised.
- Backing module `agency/resolver_agent.py`: `@chain(enforce_issuance_floor)`.
  The finisher pattern in full:
  1. **Authorisation re-check** — approve-token allowlist + block-token denylist;
     routine path gated by the auto-resolvable-category allowlist. Unknown verdict
     or category → **fail closed**.
  2. **Invariants** — a recovered request, an addressable id, a non-empty reply.
  3. **Render** the real artifact to `./out/<request_id>_resolution.md`.
  4. **Delete-on-block** — a tripped floor removes the partial and records
     `status: blocked` + `block_reasons`.
  5. **Two-layer defense** — the async body decides `approved`; the floor
     re-checks and issues independently.
  6. **Dev-store fallback that announces itself** — records to `./data/outbox.json`
     with `dev_store_fallback: true`; never fakes a real send ack.
- Wire: `always → audit_logger_agent`.

### Human members

**`reviewer_human` — Support Team Lead (Request Reviewer & Accountable Owner)** (human, `dual`, Studio Inbox)
- Approves / declines sensitive requests; owns everything that leaves the pod;
  the Manager's escalation target. SLA: one business day
  (`human_timeout_seconds: 86400`).
- **Never approves on silence.** On 2.4.486 a dual seat's timeout routes nothing:
  the Inbox card closes and the ticket records that no reply came. The declared
  `fallback_on_timeout: true` / `human_message: held_for_review` matches the route
  to audit and is kept for when the SDK sends a dual seat's fallback on.
- On silence a real team escalates to the **Support Manager** after one business
  day — not wired yet.
- Wires (on `human_message`): `'approve' → resolver_agent`;
  `'reject' or 'held_for_review' → audit_logger_agent`.
- `dual` is confined to this boundary agent (AI peers are `chain`) — no
  `dual → dual` ping-pong.

### Controls

**`audit_logger_agent` — Compliance Recorder** (external, `framework: custom`,
`chain`)
- Hash-chained, append-only WORM sink registered via
  `sdk.intelligence("audit_logger_agent")` in `main.py`. Terminus of every path;
  `can_call: []`.

### Supervisor

**LeafMesh Manager** (`gpt-4o-mini`, static routing) — reads every hand-off;
escalates to `reviewer_human` on an error retrying cannot fix, on 2 failed agents
in one session (`max_errors_per_session: 2`), or when restarts are used up. It
does not escalate an unanswered question; a broken output contract only alerts.

## Entry points (the doors)

| Door | Target | Opens when |
|---|---|---|
| `new_request` | `intake_agent` | A request arrives (form, email, manual). |
| `direct_call_intake` | `intake_agent` | Debug / replay / programmatic ingest of one payload. |
| `reviewer_reply` | `reviewer_human` | The reviewer answers a held request — HITL resume. |

## Persistence (where data lives)

- **Session / working state** — Redis (ships with the SDK) + the in-process
  `session_stash` that bridges the HITL gap. No provisioning needed.
- **System of record** — the dev store `agency/_shared/store.py` (`./data`) is a
  **dev stand-in only**, never authoritative. Going live = swap its function
  bodies for real calls (CRM via the `mcp` block; a durable store such as
  Supabase for the ledger/outbox). The function signatures are the contract; the
  mesh does not change.
- **WORM ledger** — `./logs/audit.jsonl` in dev; an insert-only table (RLS/triggers
  blocking update/delete) or S3 Object Lock in production.

## Modern capabilities demonstrated

| Capability | Where | Form |
|---|---|---|
| **playbook** | `intake_agent` | **Live** — `description` resident, `responsibility` on demand. |
| **dev-store tools** | `agency/tools.py` + `store.py` | **Live** — `lookup_requester`, announces `available:false`. |
| **finisher** | `resolver_agent` | **Live** — allow/deny + fail-closed + render + delete-on-block. |
| **default-deny HITL** | `reviewer_human` | **Live** — nothing approved on silence; the `held_for_review` fallback is declared (a dual seat's timeout does not send it on in 2.4.486). |
| **WORM sink** | `audit_logger_agent` | **Live** — hash-chained, `sdk.intelligence()`. |
| **mcp** | `intake_agent` | Commented (picks vault connection `crm_mcp`) + dev-store fallback. |
| **scaling.copies** + atomic claim | Pattern B | Commented grow-into. |
| **wake_up** + `timezone` | Pattern C | Commented grow-into (UTC trap called out). |
| **super_agent** (dict form) | Pattern D | Commented grow-into (dict-only tuning). |

## Controls & verification

- Default-deny gate, every wire conditional, bounded escalation/retry loops, WORM
  terminus.
- `leafmesh config check` clean (structure); starts on leafmesh 2.4.486; both
  backing modules bind by name (no dead code); the fail-closed floors and the
  seed lookup are unit-tested with no LLM/Redis in `tests/test_finisher.py`.
- The pod's discipline in one sentence: **agents produce, the human decides, the
  system records — and silence never advances anything.**
