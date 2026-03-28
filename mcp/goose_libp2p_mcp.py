"""
goose-mcp-libp2p — MVP A
========================
A FastMCP server that gives Goose tools to operate a libp2p peer node.

Tools exposed to Goose:
  • start_peer(port, nick, seed)        — start a libp2p node
  • stop_peer()                         — stop the running node
  • get_peer_info()                     — return peer ID + multiaddr
  • connect_peer(multiaddr)             — connect to another peer
  • publish_message(topic, message)     — publish via GossipSub
  • get_messages(topic)                 — retrieve received messages
  • list_peers()                        — list connected peers
  • subscribe_topic(topic)              — subscribe to a new topic
  • get_node_status()                   — health / readiness check

Architecture
------------
The libp2p HeadlessService runs in a background thread (trio event loop).
FastMCP exposes synchronous tool wrappers that communicate with it via
thread-safe queues (janus), mirroring the pattern used by the Tornado API.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import threading
import time
from typing import Any, Optional

import trio

# ── Make the parent package importable when run directly ──────────────────────
_MCP_DIR = os.path.dirname(os.path.abspath(__file__))
_ROOT_DIR = os.path.dirname(_MCP_DIR)
if _ROOT_DIR not in sys.path:
    sys.path.insert(0, _ROOT_DIR)

from mcp.server.fastmcp import FastMCP

# ── Logging ───────────────────────────────────────────────────────────────────
_LOG_FILE = os.path.join(_MCP_DIR, "mcp_logs.log")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

# Add a file handler so all MCP logs are persisted to mcp_logs.log
_file_handler = logging.FileHandler(_LOG_FILE, mode="a", encoding="utf-8")
_file_handler.setLevel(logging.INFO)
_file_handler.setFormatter(
    logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
)
logging.getLogger().addHandler(_file_handler)

logger = logging.getLogger("goose-libp2p-mcp")
logger.info(f"MCP server starting — logs will be saved to: {_LOG_FILE}")

# ── Global node state ─────────────────────────────────────────────────────────
_service: Optional[Any] = None          # HeadlessService instance
_service_thread: Optional[threading.Thread] = None
_service_lock = threading.Lock()

# ── FastMCP server ────────────────────────────────────────────────────────────
mcp = FastMCP(
    "goose-libp2p",
    instructions=(
        "This MCP server lets you operate a libp2p peer node. "
        "Use start_peer() first, then connect_peer(), publish_message(), "
        "get_messages(), list_peers() to interact with the p2p network."
    ),
)


# ─────────────────────────────────────────────────────────────────────────────
# Internal helpers
# ─────────────────────────────────────────────────────────────────────────────

def _run_service_in_thread(nickname: str, port: int, connect_addrs: list[str], seed: str = None) -> None:
    """Target function for the background thread that owns the trio event loop."""
    global _service

    # Import here so the module can be loaded without the full py-peer deps
    # installed (e.g. during unit tests that only test the MCP layer).
    from headless import HeadlessService  # noqa: PLC0415

    seed = f"goose-mcp-{nickname}" if seed is None else seed
    svc = HeadlessService(
        nickname=nickname,
        port=port,
        connect_addrs=connect_addrs,
        ui_mode=False,
        strict_signing=False,
        seed=seed,
    )
    _service = svc

    try:
        trio.run(svc.start)
    except Exception as exc:
        logger.error(f"HeadlessService crashed: {exc}")
    finally:
        _service = None


def _wait_for_ready(timeout: float = 30.0) -> bool:
    """Block (in the calling thread) until the service is ready or timeout."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        svc = _service
        if svc is not None and getattr(svc, "ready", False):
            return True
        time.sleep(0.2)
    return False


# ─────────────────────────────────────────────────────────────────────────────
# MCP Tools
# ─────────────────────────────────────────────────────────────────────────────

@mcp.tool()
def start_peer(port: int = 9000, nick: str = "GooseAgent", seed: str = None) -> str:
    """
    Start a libp2p peer node.

    Args:
        port: TCP port to listen on (default 9000).
        nick: Human-readable nickname for this peer (default "GooseAgent").
        seed: Optional seed for the peer's identity.

    Returns:
        JSON string with peer_id and multiaddr on success, or an error message.
    """
    global _service, _service_thread

    with _service_lock:
        if _service is not None and getattr(_service, "ready", False):
            return json.dumps({
                "status": "already_running",
                "peer_id": str(_service.host.get_id()),
                "multiaddr": _service.full_multiaddr,
            })

        logger.info(f"Starting libp2p peer — nick={nick}, port={port}")
        t = threading.Thread(
            target=_run_service_in_thread,
            args=(nick, port, [], seed),
            daemon=True,
            name="libp2p-service",
        )
        _service_thread = t
        t.start()

    if not _wait_for_ready(timeout=30.0):
        return json.dumps({"error": "Peer failed to become ready within 30 s. Check logs."})

    svc = _service
    return json.dumps({
        "status": "started",
        "peer_id": str(svc.host.get_id()),
        "multiaddr": svc.full_multiaddr,
        "nick": nick,
        "port": port,
    })


@mcp.tool()
def stop_peer() -> str:
    """
    Stop the running libp2p peer node.

    Returns:
        Confirmation message or error if no peer is running.
    """
    svc = _service
    if svc is None:
        return json.dumps({"error": "No peer is currently running."})

    try:
        # stop_event is a trio.Event — set it from the trio thread via the
        # thread-safe sync wrapper if available, otherwise use a flag.
        if hasattr(svc.stop_event, "set"):
            # trio.Event.set() must be called from the trio thread.
            # We signal it by putting a sentinel on the outgoing queue instead.
            try:
                svc.outgoing_queue.sync_q.put_nowait({"_stop": True})
            except Exception:
                pass
        svc.running = False
        return json.dumps({"status": "stopping", "message": "Stop signal sent to peer."})
    except Exception as exc:
        return json.dumps({"error": str(exc)})


@mcp.tool()
def get_peer_info() -> str:
    """
    Return the running peer's ID and multiaddr.

    Returns:
        JSON with peer_id, multiaddr, nick, and ready status.
    """
    svc = _service
    if svc is None:
        return json.dumps({"error": "No peer running. Call start_peer() first."})

    return json.dumps({
        "peer_id": str(svc.host.get_id()) if svc.host else None,
        "multiaddr": svc.full_multiaddr,
        "nick": svc.nickname,
        "ready": svc.ready,
    })


@mcp.tool()
def connect_peer(multiaddr: str) -> str:
    """
    Connect to another libp2p peer using its multiaddr.

    Args:
        multiaddr: Full multiaddr string, e.g.
                   /ip4/127.0.0.1/tcp/9001/p2p/<PEER_ID>

    Returns:
        JSON with connection result.
    """
    svc = _service
    if svc is None or not svc.ready:
        return json.dumps({"error": "Peer not running. Call start_peer() first."})

    try:
        # Push connection request via the thread-safe queue
        svc.peer_connection_queue.sync_q.put_nowait(multiaddr)
        # Give the service a moment to attempt the connection
        time.sleep(5)
        return json.dumps({
            "status": "connection_requested",
            "target": multiaddr,
            "message": "Connection request sent. Use list_peers() to verify.",
        })
    except Exception as exc:
        return json.dumps({"error": str(exc)})


@mcp.tool()
def publish_message(topic: str, message: str) -> str:
    """
    Publish a message to a GossipSub topic.

    Args:
        topic: The GossipSub topic string (e.g. /goose/tasks).
        message: The message content to publish.

    Returns:
        JSON with publish result.
    """
    svc = _service
    if svc is None or not svc.ready:
        return json.dumps({"error": "Peer not running. Call start_peer() first."})

    try:
        svc.outgoing_queue.sync_q.put_nowait({
            "message": message,
            "topic": topic,
        })
        return json.dumps({
            "status": "published",
            "topic": topic,
            "message": message,
        })
    except Exception as exc:
        return json.dumps({"error": str(exc)})


@mcp.tool()
def get_messages(topic: str = "", limit: int = 20) -> str:
    """
    Retrieve messages received on a specific topic (or all topics).

    Args:
        topic: GossipSub topic to filter by. Empty string returns all topics.
        limit: Maximum number of messages to return (default 20).

    Returns:
        JSON array of message objects.
    """
    svc = _service
    if svc is None or not svc.ready:
        return json.dumps({"error": "Peer not running. Call start_peer() first."})

    try:
        if topic:
            messages = svc.topic_messages.get(topic, [])
        else:
            # Flatten all topics
            messages = []
            for msgs in svc.topic_messages.values():
                messages.extend(msgs)
            messages.sort(key=lambda m: m.get("timestamp", 0))

        # Return the last `limit` messages
        result = messages[-limit:]
        # Mark as read
        for msg in result:
            msg["read"] = True

        return json.dumps({
            "topic": topic or "all",
            "count": len(result),
            "messages": result,
        })
    except Exception as exc:
        return json.dumps({"error": str(exc)})


@mcp.tool()
def list_peers() -> str:
    """
    List all currently connected libp2p peers.

    Returns:
        JSON array of peer IDs and their PubSub status.
    """
    svc = _service
    if svc is None or not svc.ready:
        return json.dumps({"error": "Peer not running. Call start_peer() first."})

    try:
        connected = [str(p) for p in svc.host.get_connected_peers()]
        pubsub_peers = [str(p) for p in svc.pubsub.peers.keys()]

        peers = []
        for pid in connected:
            peers.append({
                "peer_id": pid,
                "in_pubsub_mesh": pid in pubsub_peers,
            })

        return json.dumps({
            "total_connected": len(connected),
            "total_pubsub": len(pubsub_peers),
            "peers": peers,
        })
    except Exception as exc:
        return json.dumps({"error": str(exc)})


@mcp.tool()
def subscribe_topic(topic: str) -> str:
    """
    Subscribe to a new GossipSub topic to receive messages on it.

    Args:
        topic: The topic string to subscribe to (e.g. /goose/results).

    Returns:
        JSON confirmation.
    """
    svc = _service
    if svc is None or not svc.ready:
        return json.dumps({"error": "Peer not running. Call start_peer() first."})

    try:
        svc.topic_subscription_queue.sync_q.put_nowait({"topic": topic})
        return json.dumps({
            "status": "subscription_requested",
            "topic": topic,
            "message": "Subscription request sent. Messages will appear in get_messages().",
        })
    except Exception as exc:
        return json.dumps({"error": str(exc)})


@mcp.tool()
def get_node_status() -> str:
    """
    Return a full health/status snapshot of the running libp2p node.

    Returns:
        JSON with readiness, peer counts, subscribed topics, and uptime info.
    """
    svc = _service
    if svc is None:
        return json.dumps({"running": False, "message": "No peer started yet."})

    try:
        connected = svc.host.get_connected_peers() if svc.host else []
        pubsub_peers = list(svc.pubsub.peers.keys()) if svc.pubsub else []
        topics = list(svc.topic_messages.keys())

        mesh = {}
        if svc.gossipsub and hasattr(svc.gossipsub, "mesh"):
            for t, peer_set in svc.gossipsub.mesh.items():
                mesh[t] = len(peer_set)

        return json.dumps({
            "running": True,
            "ready": svc.ready,
            "peer_id": str(svc.host.get_id()) if svc.host else None,
            "multiaddr": svc.full_multiaddr,
            "nick": svc.nickname,
            "connected_peers": len(connected),
            "pubsub_peers": len(pubsub_peers),
            "subscribed_topics": topics,
            "gossipsub_mesh": mesh,
            "message_counts": {t: len(msgs) for t, msgs in svc.topic_messages.items()},
        })
    except Exception as exc:
        return json.dumps({"error": str(exc)})


# ─────────────────────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    logger.info("🚀 Starting goose-libp2p MCP server (stdio transport)…")
    mcp.run(transport="stdio")
