"""Resolver — the FINISHER / actuator (the artifact-producing executor).

auto_discover matches `resolver_agent`. The resolver sits AFTER the human gate.
It never decides policy — it re-checks that it is genuinely authorised, renders
the real resolution record, and records an append-only ledger entry. It is the
concrete "@chain fails closed":

  a) authorisation RE-CHECK — reaching this agent does not mean allowed. An
     approve-token ALLOWLIST + a block-token DENYLIST; the routine path is gated
     by an auto-resolvable-category ALLOWLIST. An UNKNOWN verdict or category
     fails closed.
  b) deterministic invariants a prompt can't waive (a recovered request, an
     addressable id, something to actually say).
  c) render the real artifact to ./out; on a tripped floor, DELETE the partial
     and record status:blocked with reasons — never a half-issued result.
  d) dev-store recovery — after the HITL gate the upstream payload is dropped,
     so the finisher recovers the request from the session stash / dev store,
     and its outbox record ANNOUNCES it is a dev-store record (never a fake ack).

Two ways in: from intake with needs_human == false (routine → allowlist gate);
from reviewer_human with 'approve' (approve-token gate).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

from leafmesh import LeafMeshLogger, chain

try:
    from ._shared import store
    from ._shared.session_stash import resolve_session_id, stash_get, stash_put
except ImportError:  # pragma: no cover — direct-run fallback
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from _shared import store  # type: ignore
    from _shared.session_stash import resolve_session_id, stash_get, stash_put  # type: ignore

logger = LeafMeshLogger(__name__)

_OUT_DIR = Path("./out")
_APPROVE_TOKENS = frozenset({"approve", "approved", "yes", "ok", "sign", "signed"})
_BLOCK_TOKENS = frozenset({"reject", "rejected", "no", "deny", "denied",
                           "held", "held_for_review", "hold", "halt_for_review"})
# Categories intake may auto-resolve WITHOUT a human. Anything else fails closed.
_AUTO_RESOLVABLE = frozenset({"question", "other"})


def _signal(input_data: dict) -> str:
    """The human verdict, from wherever the SDK delivered it (shape-tolerant)."""
    sources = [input_data]
    up = input_data.get("upstream_yields")
    if isinstance(up, dict):
        sources.extend(v for v in up.values() if isinstance(v, dict))
    for src in sources:
        for key in ("human_message", "human_decision", "decision", "message"):
            val = src.get(key)
            if isinstance(val, str) and val.strip():
                return val.strip().lower()
    return ""


def _recover_request(input_data: dict, context: dict) -> dict:
    """Recover the request across the HITL boundary: upstream -> stash -> dev store."""
    up = input_data.get("upstream_yields") or {}
    candidates = [input_data]
    if isinstance(up, dict):
        candidates.append(up.get("intake_agent"))
    for src in candidates:
        if isinstance(src, dict) and src.get("request_id") and (
            src.get("draft_reply") or src.get("summary") or src.get("category")
        ):
            return {k: src.get(k) for k in
                    ("request_id", "category", "priority", "needs_human", "draft_reply", "summary")}
    sid = resolve_session_id(input_data, context)
    stashed = stash_get(sid)
    if stashed.get("request_id"):
        return stashed
    rid = str(input_data.get("request_id") or "")
    return store.get_request(rid) or {"request_id": rid}


def _render_artifact(req: dict) -> str:
    _OUT_DIR.mkdir(parents=True, exist_ok=True)
    rid = str(req.get("request_id") or "request")
    path = _OUT_DIR / f"{rid}_resolution.md"
    body = str(req.get("draft_reply") or req.get("summary") or "").strip()
    lines = [
        f"# Resolution — {rid}",
        f"Category: {req.get('category', '')}   Priority: {req.get('priority', '')}",
        "",
        "## Reply",
        body or "_(no reply body)_",
        "",
        "_Rendered by the finisher. Delivery to the customer requires a real "
        "connector; until then this is recorded in the dev outbox, not sent._",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")
    return str(path)


def _delete_partial(result: dict) -> None:
    p = result.get("artifact_path")
    if p:
        Path(p).unlink(missing_ok=True)
        result["artifact_path"] = ""


def enforce_issuance_floor(result: Any, context: dict) -> dict:
    """The finisher floor — issue ONLY on a real authorisation; delete on a block."""
    result = result if isinstance(result, dict) else {}
    result.setdefault("block_reasons", [])
    result.setdefault("artifact_path", "")

    if not result.get("approved"):
        result["status"] = "blocked"
        if not result["block_reasons"]:
            result["block_reasons"].append("not authorised to issue (fail closed)")
        _delete_partial(result)
        logger.info(f"[resolver] issuance floor BLOCKED: {result['block_reasons']}")
        result.pop("_request", None)
        result.pop("_input", None)
        return result

    req = result.get("_request") or {}
    if not str(req.get("request_id") or "").strip():
        result.update(status="blocked", approved=False, issued=False)
        result["block_reasons"].append("no recoverable request (nothing to issue)")
        _delete_partial(result)
        result.pop("_request", None)
        result.pop("_input", None)
        return result
    if not (str(req.get("draft_reply") or "").strip() or str(req.get("summary") or "").strip()):
        result.update(status="blocked", approved=False, issued=False)
        result["block_reasons"].append("nothing to say — no draft or summary to issue")
        _delete_partial(result)
        result.pop("_request", None)
        result.pop("_input", None)
        return result

    # Passed the floor — render, record, ledger.
    result["artifact_path"] = _render_artifact(req)
    store.record_outbox({"request_id": req.get("request_id"), "action": "resolve_request",
                         "artifact_path": result["artifact_path"]})
    store.append_ledger({"request_id": req.get("request_id"), "event": "resolved",
                         "category": req.get("category", "")})
    result.update(issued=True, status="issued")
    logger.info(f"[resolver] issued request {req.get('request_id')} -> {result['artifact_path']}")
    result.pop("_request", None)
    result.pop("_input", None)
    return result


@chain(enforce_issuance_floor)
async def resolver_agent(llm_response: Any, input_data: dict, context: dict) -> dict:
    input_data = input_data if isinstance(input_data, dict) else {}
    req = _recover_request(input_data, context)
    sid = resolve_session_id(input_data, context)
    if req.get("request_id"):
        stash_put(sid, req)   # keep it recoverable if the floor re-runs

    out: dict[str, Any] = {
        "issued": False, "approved": False, "artifact_path": "",
        "status": "", "block_reasons": [], "_input": input_data, "_request": req,
    }

    verdict = _signal(input_data)
    if verdict in _BLOCK_TOKENS:
        out["status"] = "blocked"
        out["block_reasons"] = ["reviewer rejected / held"]
    elif verdict in _APPROVE_TOKENS:
        out["approved"] = True                         # human-approved path
    elif verdict:
        # A human verdict arrived but it is neither approve nor block — UNKNOWN.
        out["status"] = "blocked"
        out["block_reasons"] = [f"unknown reviewer verdict {verdict!r} — fail closed"]
    else:
        # Routine path (no human verdict) — allowlist gate, fail closed on unknown.
        category = str(req.get("category") or "").lower()
        needs_human = req.get("needs_human")
        if needs_human is False and category in _AUTO_RESOLVABLE:
            out["approved"] = True
        else:
            out["status"] = "blocked"
            out["block_reasons"] = [
                f"not auto-resolvable (category={category!r}, needs_human={needs_human}) — fail closed"
            ]
    return out
