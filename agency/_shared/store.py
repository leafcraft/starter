"""Dev store — a working stand-in for the system of record, so the pod runs
day-0 with NO connector wired.

This is a DEV STAND-IN, not a system of record. In production the requester
lookup comes from your CRM / helpdesk (the `mcp` block in the configuration), and the
outbox + ledger are your real systems. **The function signatures are the contract
you swap real systems into** — the mesh does not change (see the doctrine,
`where data lives`).

Nothing here is authoritative: it holds seed requesters (so intake has something
to look up), and appends the pod's own outbox + append-only ledger under ./data.
A real store enforces its own invariants — this file is dev only, and every read
that has no answer says so (`available: false`) rather than inventing one.
"""
from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_LOCK = threading.Lock()
_DATA_DIR = Path("./data")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_json(name: str, default: Any) -> Any:
    p = _DATA_DIR / name
    if not p.exists():
        return default
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def _write_json(name: str, data: Any) -> None:
    _DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp = _DATA_DIR / (name + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
    tmp.replace(_DATA_DIR / name)


# ── Seed requesters — a small CRM stand-in so intake has real-looking
#    accounts to look up on first run. Fictional companies and people only.
#    Replace with a real CRM read (see the mcp block in the configuration). Keyed by
#    email; lookup_requester() also matches the contact's full name.
#    The mix exercises every route: enterprise + standard tiers, an account
#    with a billing dispute open (refund/complaint → human), an account on
#    credit hold, and a brand-new trial with no history.
#    open_tickets counts the account's open support tickets; mrr_usd is the
#    monthly recurring revenue on the current plan. ──
SEED_REQUESTERS: dict[str, dict[str, Any]] = {
    "a.rivera@example.com": {
        "name": "Ana Rivera", "company": "Brightwater Logistics", "account_id": "ACC-10042",
        "tier": "enterprise", "plan": "Enterprise (annual)", "mrr_usd": 4800,
        "open_tickets": 1, "customer_since": "2022-03-14", "account_status": "active",
        "notes": "Invoice INV-2026-0518 (USD 4,800.00) charged twice on 2026-05-01.",
    },
    "m.osei@example.com": {
        "name": "Michael Osei", "company": "Osei & Partners Architects", "account_id": "ACC-10317",
        "tier": "standard", "plan": "Team (monthly)", "mrr_usd": 290,
        "open_tickets": 0, "customer_since": "2024-08-02", "account_status": "active",
        "notes": "",
    },
    "l.chen@example.com": {
        "name": "Lena Chen", "company": "Fernhill Dental Group", "account_id": "ACC-10588",
        "tier": "standard", "plan": "Team (annual)", "mrr_usd": 410,
        "open_tickets": 3, "customer_since": "2023-11-20", "account_status": "active",
        "notes": "Three open tickets about failed calendar sync; asked for a call-back twice.",
    },
    "r.haddad@example.com": {
        "name": "Rami Haddad", "company": "Cedar Point Retail", "account_id": "ACC-10931",
        "tier": "enterprise", "plan": "Enterprise (annual)", "mrr_usd": 7250,
        "open_tickets": 0, "customer_since": "2021-06-07", "account_status": "credit_hold",
        "notes": "Credit hold since 2026-10-15: invoice INV-2026-1004 (USD 7,250.00) 19 days overdue.",
    },
    "s.novak@example.com": {
        "name": "Sara Novak", "company": "Novak Bakery Co.", "account_id": "ACC-11204",
        "tier": "trial", "plan": "Trial (14 days)", "mrr_usd": 0,
        "open_tickets": 0, "customer_since": "2026-10-28", "account_status": "trial",
        "notes": "",
    },
    "j.okafor@example.com": {
        "name": "James Okafor", "company": "Okafor Freight Brokers", "account_id": "ACC-10766",
        "tier": "standard", "plan": "Team (monthly)", "mrr_usd": 290,
        "open_tickets": 1, "customer_since": "2025-01-09", "account_status": "active",
        "notes": "Open ticket: asked to change the billing contact.",
    },
}


# ── Requester lookup (dev-store fallback for the CRM/mcp connector path) ──
def lookup_requester(identifier: str) -> dict[str, Any]:
    """Look a requester up in the dev CRM by email or full name. Announces
    `available: false` when nothing matches — never a synthetic 'unknown but
    fine' record."""
    key = (identifier or "").strip().lower()
    rec = SEED_REQUESTERS.get(key)
    if not rec and key:
        for email, r in SEED_REQUESTERS.items():
            if str(r.get("name", "")).lower() == key:
                key, rec = email, r
                break
    if not rec:
        return {"available": False,
                "reason": (f"no seed requester for {identifier!r}; create the vault record "
                           f"'crm_mcp' and wire the mcp block to look up real customers")}
    return {"available": True, "requester": key, **rec}


# ── Request recovery across the HITL gate (finisher reads this post-review) ──
def put_request(request_id: str, req: dict[str, Any]) -> None:
    if not request_id:
        return
    with _LOCK:
        reqs = _read_json("requests.json", {})
        reqs[request_id] = {"stored_at": _now(), **req}
        _write_json("requests.json", reqs)


def get_request(request_id: str) -> dict[str, Any]:
    return _read_json("requests.json", {}).get(request_id, {})


# ── Outbox (the finisher's sends) + append-only ledger ───────────────────────
def record_outbox(entry: dict[str, Any]) -> dict[str, Any]:
    """Record an outbound action to the dev outbox. This is a VERIFIABLE dev-store
    record, not a real send — a real delivery connector replaces it, and until
    then the finisher never claims a request was actually sent to the customer."""
    with _LOCK:
        outbox = _read_json("outbox.json", [])
        rec = {"recorded_at": _now(), "dev_store_fallback": True, **entry}
        outbox.append(rec)
        _write_json("outbox.json", outbox)
    return rec


def append_ledger(entry: dict[str, Any]) -> dict[str, Any]:
    """Append-only resolution ledger (dev mirror of the WORM sink for local demo)."""
    with _LOCK:
        ledger = _read_json("resolution_ledger.json", [])
        rec = {"recorded_at": _now(), **entry}
        ledger.append(rec)
        _write_json("resolution_ledger.json", ledger)
    return rec
