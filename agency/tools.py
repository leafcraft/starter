"""Global tools for the starter pod.

This is intake's day-0 tool surface — the tool it calls, in the turn, to look a
requester up in the system of record. It reads the dev store (seed requesters) so
the pod runs with NO connector wired, and **it announces itself**: when there is
no real source and no seed, it returns `available: false` and says why — never a
synthetic success that looks like a real read. To go live, wire the CRM `mcp`
block in config.yaml (each named action becomes its own namespaced tool); this
dev tool is the fallback contract.

"Is a real CRM wired?" is answered by the vault, not by .env: the vault record
'crm_mcp' (Infrastructure → Integrations → MCP) existing means wired. Its
address and token are read only by the `mcp` block, never here.
"""
import os

from leafmesh import LeafMeshLogger, connection_rows, global_tool
from leafmesh.vault.refs import UnresolvedVaultRef

try:
    from ._shared import store
except ImportError:  # pragma: no cover — direct-run fallback
    import sys
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from _shared import store  # type: ignore

logger = LeafMeshLogger(__name__)


CRM_VAULT_RECORD = "crm_mcp"


async def _connector_wired() -> bool:
    """True if the CRM's vault record exists (the same record the `mcp` block
    names). No record — or no running mesh, as in the unit tests — is
    "not wired"; a record this agent may not read still counts as wired."""
    try:
        await connection_rows(CRM_VAULT_RECORD)
        return True
    except UnresolvedVaultRef:
        return False
    except PermissionError:  # SecretNotAllowed: the record exists; it only limits which agents read it
        return True


@global_tool(category="intake")
async def lookup_requester(requester: str) -> dict:
    """Look a requester up in the system of record (CRM / helpdesk).

    Returns their tier and open-ticket count so intake can prioritise. When no
    real connector is wired, reads the seed store. Announces `available: false`
    (with a reason) when there is genuinely nothing to read — never a confident
    empty record.

    Args:
        requester: The requester's email or display name (e.g. "a.rivera@example.com").
    """
    result = store.lookup_requester(str(requester).strip())
    if not result.get("available") and await _connector_wired():
        # A connector IS wired but this requester isn't in it — surface
        # unreachable rather than a confident 'unknown'.
        return {"available": False,
                "reason": "connector wired but returned nothing for this requester"}
    logger.info(f"lookup_requester requester={requester} available={result.get('available')}")
    return result
