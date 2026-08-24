"""Dev store — a working stand-in for the system of record, so the pod runs
day-0 with NO connector wired.

This is a DEV STAND-IN, not a system of record. In production the requester
lookup comes from your CRM / helpdesk (the `mcp` block in config.yaml), and the
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


# ── Seed requesters — a tiny CRM stand-in so intake can demonstrate a
#    system-of-record lookup on first run. Replace with a real CRM read
#    (see the mcp block in config.yaml). Keyed by email OR display name. ──
SEED_REQUESTERS: dict[str, dict[str, Any]] = {
    "a.rivera@example.com": {"name": "A. Rivera", "tier": "enterprise", "open_tickets": 1},
    "m.osei@example.com":   {"name": "M. Osei",   "tier": "standard",   "open_tickets": 0},
}


# ── Requester lookup (dev-store fallback for the CRM/mcp connector path) ──
def lookup_requester(identifier: str) -> dict[str, Any]:
    """Look a requester up in the dev CRM. Announces `available: false` when the
    identifier is not seeded — never a synthetic 'unknown but fine' record."""
    key = (identifier or "").strip().lower()
    rec = SEED_REQUESTERS.get(key)
    if not rec:
        return {"available": False,
                "reason": f"no seed requester for {identifier!r}; wire CRM_MCP_URL to look up real customers"}
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
