"""Intake & triage desk (LLM) — with a fail-closed @chain floor.

auto_discover matches `intake_agent` to the YAML agent by NAME. The MODEL reads
the request, looks the requester up, and classifies; this CODE fails closed.

@chain enforce_triage_floor — the deterministic floor a prompt can't waive:
  • a sensitive category (money / complaint) or a high-priority item ALWAYS
    needs a human, whatever the model decided;
  • a low-confidence read (confidence below MIN_CONFIDENCE = 0.7, or no
    confidence at all) needs a human;
  • a 'routine' item with nothing to say can't be auto-resolved → send it to a
    human;
  • every request gets an addressable id (minted if missing);
  • the request is stashed (session + dev store) so the finisher can recover it
    AFTER the HITL gate, when the SDK re-delivers only human_* meta.

Note the signatures: an `llm` agent function takes EXACTLY three params
(llm_response, input_data, context) or it is silently never called; a @chain
floor function takes (result, context).
"""
from __future__ import annotations

import os
import sys
import uuid
from typing import Any

from leafmesh import LeafMeshLogger, chain

try:
    from ._shared import store
    from ._shared.session_stash import resolve_session_id, stash_put
except ImportError:  # pragma: no cover — direct-run fallback
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from _shared import store  # type: ignore
    from _shared.session_stash import resolve_session_id, stash_put  # type: ignore

logger = LeafMeshLogger(__name__)

# Categories that ALWAYS require a human, whatever the model says.
_SENSITIVE = frozenset({"complaint", "refund", "money", "legal", "billing"})
# Below this the model is guessing; a person reads it. Keep equal to the
# prompt, the playbook and the README (0.7).
MIN_CONFIDENCE = 0.7
_STASH_KEYS = ("request_id", "category", "priority", "needs_human", "draft_reply",
               "summary", "confidence")


def _confidence(value: Any) -> float:
    """The model's confidence as a number; anything unreadable is 0.0 (fail closed)."""
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return 0.0


def enforce_triage_floor(result: Any, context: dict) -> dict:
    """Fail closed: never auto-resolve something a human should see."""
    result = result if isinstance(result, dict) else {}

    # Normalise to the yields contract so downstream conditions never read a
    # missing field (conditions FAIL CLOSED on absence — an absent needs_human
    # would make BOTH wires false and strand the request).
    result.setdefault("category", "other")
    result.setdefault("priority", "normal")
    result.setdefault("needs_human", True)      # fail-closed default
    result.setdefault("draft_reply", "")
    result.setdefault("summary", "")
    result.setdefault("request_id", "")
    result["confidence"] = _confidence(result.get("confidence"))

    # Mint an addressable id if the model didn't echo one (an id is plumbing,
    # not a fabricated fact).
    if not str(result.get("request_id") or "").strip():
        result["request_id"] = f"req-{uuid.uuid4().hex[:10]}"

    # Deterministic fail-closed overrides the prompt cannot talk past.
    cat = str(result.get("category") or "").lower()
    pri = str(result.get("priority") or "").lower()
    if cat in _SENSITIVE or pri == "high":
        result["needs_human"] = True
    if result["confidence"] < MIN_CONFIDENCE:
        # A guess is not a decision — a person reads it.
        result["needs_human"] = True
    if result.get("needs_human") is False and not str(result.get("draft_reply") or "").strip():
        # A routine item with nothing to say can't be auto-resolved.
        result["needs_human"] = True

    # Stash the request so the finisher can recover it across the HITL gate.
    sid = resolve_session_id({}, context)
    parcel = {k: result.get(k) for k in _STASH_KEYS}
    stash_put(sid, parcel)
    store.put_request(result["request_id"], parcel)

    logger.info(f"[intake] {result['request_id']} category={cat} "
                f"confidence={result['confidence']:.2f} needs_human={result['needs_human']}")
    return result


@chain(enforce_triage_floor)
async def intake_agent(llm_response: Any, input_data: dict, context: dict) -> dict:
    """Return the model's classification; the floor re-checks and fails closed."""
    out = llm_response if isinstance(llm_response, dict) else {}
    # Carry the request_id through from the input if the model dropped it.
    if not out.get("request_id") and isinstance(input_data, dict):
        rid = input_data.get("request_id")
        if rid:
            out["request_id"] = rid
    return out
