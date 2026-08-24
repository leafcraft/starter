"""Global tools for the starter pod.

This is intake's day-0 tool surface — the tool it calls, in the turn, to look a
requester up in the system of record. It reads the dev store (seed requesters) so
the pod runs with NO connector wired, and **it announces itself**: when there is
no real source and no seed, it returns `available: false` and says why — never a
synthetic success that looks like a real read. To go live, wire the CRM `mcp`
block in config.yaml (each named action becomes its own namespaced tool); this
dev tool is the fallback contract.
"""
import os

from leafmesh import global_tool, LeafMeshLogger

try:
    from ._shared import store
except ImportError:  # pragma: no cover — direct-run fallback
    import sys
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from _shared import store  # type: ignore

logger = LeafMeshLogger(__name__)


def _connector_wired() -> bool:
    """True if a real requester connector is configured (CRM mcp URL set)."""
    return bool(os.getenv("CRM_MCP_URL"))


@global_tool(category="intake")
def lookup_requester(requester: str) -> dict:
    """Look a requester up in the system of record (CRM / helpdesk).

    Returns their tier and open-ticket count so intake can prioritise. When no
    real connector is wired, reads the seed store. Announces `available: false`
    (with a reason) when there is genuinely nothing to read — never a confident
    empty record.

    Args:
        requester: The requester's email or display name (e.g. "a.rivera@example.com").
    """
    result = store.lookup_requester(str(requester).strip())
    if not result.get("available") and _connector_wired():
        # A connector IS wired but this requester isn't in it — surface
        # unreachable rather than a confident 'unknown'.
        return {"available": False,
                "reason": "connector wired but returned nothing for this requester"}
    logger.info(f"lookup_requester requester={requester} available={result.get('available')}")
    return result
