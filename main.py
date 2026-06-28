"""starter — Starter mesh entry point.

This file boots the mesh and registers the one piece of Python the
starter ships: the WORM audit sink. Everything else lives in
configs/config.yaml. You rarely need to touch this file.
"""
import asyncio
import signal
import sys

from dotenv import load_dotenv
from leafmesh import EventType, LeafMesh, LeafMeshLogger

# The audit sink is a custom external agent — SDK 2.4+ runs it via an
# intelligence function registered on the instance (see config + module).
from agency._shared import audit_logger as _audit_logger

load_dotenv()
logger = LeafMeshLogger(__name__)

leafmesh = LeafMesh.from_yaml("configs/config.yaml")

# Register the WORM audit sink for the external audit_logger_agent.
# Must happen after from_yaml() and before start().
_audit_logger.register(leafmesh, "audit_logger_agent")


# Event-bus subscribers — observe the stream without blocking the mesh.
async def _on_agent_error(e):            logger.warning(f"[starter] AGENT_ERROR {e.session_id}")
async def _on_manager_intervention(e):   logger.warning(f"[starter] MANAGER_INTERVENTION {e.session_id}")
async def _on_intervention_needed(e):    logger.error(f"[starter] INTERVENTION_NEEDED {e.session_id}")
async def _on_human_input_timeout(e):    logger.warning(f"[starter] HITL TIMEOUT {e.session_id}")


async def main():
    await leafmesh.start()

    leafmesh.event_bus.subscribe(EventType.AGENT_ERROR,          _on_agent_error)
    leafmesh.event_bus.subscribe(EventType.MANAGER_INTERVENTION, _on_manager_intervention)
    leafmesh.event_bus.subscribe(EventType.INTERVENTION_NEEDED,  _on_intervention_needed)
    leafmesh.event_bus.subscribe(EventType.HUMAN_INPUT_TIMEOUT,  _on_human_input_timeout)

    try:
        await leafmesh.enable_self_healing()
    except AttributeError:
        pass

    logger.info("starter — starter mesh running")
    logger.info("API docs: http://127.0.0.1:18820/docs")

    # ── Try it without curl — uncomment to fire one request on boot ──
    # result = await leafmesh.mesh_call(
    #     "new_request",
    #     input_data={"source": "manual", "message": "What are your hours?"},
    # )
    # logger.info(f"Result: {result}")

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    if sys.platform != "win32":
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, stop.set)
        await stop.wait()
    else:
        try:
            await stop.wait()
        except KeyboardInterrupt:
            pass

    await leafmesh.stop()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
