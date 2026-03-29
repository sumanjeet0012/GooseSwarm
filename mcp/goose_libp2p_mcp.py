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


def _ok(action: str, data: Optional[dict[str, Any]] = None, **extra: Any) -> str:
    payload: dict[str, Any] = {
        "ok": True,
        "action": action,
        "timestamp": time.time(),
    }
    if data is not None:
        payload["data"] = data
    payload.update(extra)
    return json.dumps(payload)


def _error(action: str, message: str, **extra: Any) -> str:
    payload: dict[str, Any] = {
        "ok": False,
        "action": action,
        "error": {
            "message": message,
        },
        "timestamp": time.time(),
    }
    payload.update(extra)
    return json.dumps(payload)


def _require_service(action: str, require_ready: bool = True) -> tuple[Optional[Any], Optional[str]]:
    svc = _service
    if svc is None:
        return None, _error(action, "No peer running. Call start_peer() first.")
    if require_ready and not svc.ready:
        return None, _error(action, "Peer is not ready yet. Wait for startup to complete.")
    return svc, None


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
            return _ok(
                "start_peer",
                {
                    "status": "already_running",
                    "peer_id": str(_service.host.get_id()),
                    "multiaddr": _service.full_multiaddr,
                },
            )

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
        return _error("start_peer", "Peer failed to become ready within 30 s. Check logs.")

    svc = _service
    return _ok(
        "start_peer",
        {
            "status": "started",
            "peer_id": str(svc.host.get_id()),
            "multiaddr": svc.full_multiaddr,
            "nick": nick,
            "port": port,
        },
    )


@mcp.tool()
def stop_peer() -> str:
    """
    Stop the running libp2p peer node.

    Returns:
        Confirmation message or error if no peer is running.
    """
    global _service, _service_thread

    svc, err = _require_service("stop_peer", require_ready=False)
    if err:
        return err

    try:
        if hasattr(svc, "stop_event") and hasattr(svc.stop_event, "set"):
            try:
                svc.stop_event.set()
            except Exception:
                logger.warning("Could not set trio stop_event from MCP thread; falling back to running flag")

        svc.running = False

        if _service_thread is not None and _service_thread.is_alive():
            _service_thread.join(timeout=5)

        thread_alive = _service_thread.is_alive() if _service_thread else False
        if not thread_alive:
            _service = None
            _service_thread = None

        return _ok(
            "stop_peer",
            {
                "status": "stopping" if thread_alive else "stopped",
                "thread_alive": thread_alive,
            },
        )
    except Exception as exc:
        return _error("stop_peer", str(exc))


@mcp.tool()
def get_peer_info() -> str:
    """
    Return the running peer's ID and multiaddr.

    Returns:
        JSON with peer_id, multiaddr, nick, and ready status.
    """
    svc, err = _require_service("get_peer_info", require_ready=False)
    if err:
        return err

    return _ok(
        "get_peer_info",
        {
            "peer_id": str(svc.host.get_id()) if svc.host else None,
            "multiaddr": svc.full_multiaddr,
            "nick": svc.nickname,
            "ready": svc.ready,
        },
    )


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
    svc, err = _require_service("connect_peer")
    if err:
        return err

    try:
        queued = svc.connect_to_peer(multiaddr)
        if not queued:
            return _error("connect_peer", "Failed to queue connection request.")

        return _ok(
            "connect_peer",
            {
                "status": "connection_requested",
                "target": multiaddr,
            },
        )
    except Exception as exc:
        return _error("connect_peer", str(exc))


@mcp.tool()
def disconnect_peer(peer_id: str = "", multiaddr: str = "") -> str:
    """
    Request disconnection from a peer.

    Args:
        peer_id: Target peer ID (base58).
        multiaddr: Optional target multiaddr; peer ID will be derived if needed.

    Returns:
        Structured JSON with disconnect request status.
    """
    svc, err = _require_service("disconnect_peer")
    if err:
        return err

    if not peer_id and not multiaddr:
        return _error("disconnect_peer", "Either peer_id or multiaddr is required.")

    try:
        queued = svc.disconnect_peer(peer_id=peer_id, multiaddr=multiaddr)
        if not queued:
            return _error("disconnect_peer", "Failed to queue disconnect request.")

        return _ok(
            "disconnect_peer",
            {
                "status": "disconnect_requested",
                "peer_id": peer_id,
                "multiaddr": multiaddr,
            },
        )
    except Exception as exc:
        return _error("disconnect_peer", str(exc))


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
    svc, err = _require_service("publish_message")
    if err:
        return err

    try:
        svc.outgoing_queue.sync_q.put_nowait({
            "message": message,
            "topic": topic,
        })
        return _ok(
            "publish_message",
            {
                "status": "published",
                "topic": topic,
                "message": message,
            },
        )
    except Exception as exc:
        return _error("publish_message", str(exc))


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
    svc, err = _require_service("get_messages")
    if err:
        return err

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

        return _ok(
            "get_messages",
            {
                "topic": topic or "all",
                "count": len(result),
                "messages": result,
            },
        )
    except Exception as exc:
        return _error("get_messages", str(exc))


@mcp.tool()
def list_peers() -> str:
    """
    List all currently connected libp2p peers.

    Returns:
        JSON array of peer IDs and their PubSub status.
    """
    svc, err = _require_service("list_peers")
    if err:
        return err

    try:
        connected = [str(p) for p in svc.host.get_connected_peers()]
        pubsub_peers = [str(p) for p in svc.pubsub.peers.keys()]

        peers = []
        for pid in connected:
            peers.append({
                "peer_id": pid,
                "in_pubsub_mesh": pid in pubsub_peers,
            })

        return _ok(
            "list_peers",
            {
                "total_connected": len(connected),
                "total_pubsub": len(pubsub_peers),
                "peers": peers,
            },
        )
    except Exception as exc:
        return _error("list_peers", str(exc))


@mcp.tool()
def get_gossipsub_peers() -> str:
    """
    Return the current GossipSub peers.

    Returns:
        Structured JSON with peer list and count.
    """
    svc, err = _require_service("get_gossipsub_peers")
    if err:
        return err

    try:
        peers = [str(p) for p in svc.pubsub.peers.keys()] if svc.pubsub else []
        return _ok(
            "get_gossipsub_peers",
            {
                "peers": peers,
                "count": len(peers),
            },
        )
    except Exception as exc:
        return _error("get_gossipsub_peers", str(exc))


@mcp.tool()
def get_gossipsub_mesh() -> str:
    """
    Return GossipSub mesh peers grouped by topic.

    Returns:
        Structured JSON mesh map to support intelligent topic routing.
    """
    svc, err = _require_service("get_gossipsub_mesh")
    if err:
        return err

    try:
        raw_mesh = getattr(svc.gossipsub, "mesh", {}) if svc.gossipsub else {}
        mesh = {topic: [str(p) for p in peer_set] for topic, peer_set in raw_mesh.items()}
        total_mesh_peers = sum(len(v) for v in mesh.values())
        return _ok(
            "get_gossipsub_mesh",
            {
                "mesh": mesh,
                "topic_count": len(mesh),
                "total_mesh_peers": total_mesh_peers,
            },
        )
    except Exception as exc:
        return _error("get_gossipsub_mesh", str(exc))


@mcp.tool()
def subscribe_topic(topic: str) -> str:
    """
    Subscribe to a new GossipSub topic to receive messages on it.

    Args:
        topic: The topic string to subscribe to (e.g. /goose/results).

    Returns:
        JSON confirmation.
    """
    svc, err = _require_service("subscribe_topic")
    if err:
        return err

    try:
        svc.topic_subscription_queue.sync_q.put_nowait({"topic": topic})
        return _ok(
            "subscribe_topic",
            {
                "status": "subscription_requested",
                "topic": topic,
            },
        )
    except Exception as exc:
        return _error("subscribe_topic", str(exc))


@mcp.tool()
def share_file_bitswap(file_path: str, topic: str) -> str:
    """
    Queue a file sharing request using Bitswap + MerkleDag.

    Args:
        file_path: Local file path to share.
        topic: Topic where file metadata should be announced.

    Returns:
        Structured JSON with queue status.
    """
    svc, err = _require_service("share_file_bitswap")
    if err:
        return err

    if not file_path:
        return _error("share_file_bitswap", "file_path is required.")
    if not topic:
        return _error("share_file_bitswap", "topic is required.")
    if not os.path.exists(file_path):
        return _error("share_file_bitswap", f"File not found: {file_path}")

    try:
        subscribed = svc.get_subscribed_topics()
        if topic not in subscribed:
            return _error(
                "share_file_bitswap",
                f"Not subscribed to topic '{topic}'. Subscribe before sharing.",
            )

        queued = svc.share_file(file_path, topic)
        if not queued:
            return _error("share_file_bitswap", "Failed to queue file share request.")

        return _ok(
            "share_file_bitswap",
            {
                "status": "share_queued",
                "file_path": file_path,
                "file_name": os.path.basename(file_path),
                "size_bytes": os.path.getsize(file_path),
                "topic": topic,
            },
        )
    except Exception as exc:
        return _error("share_file_bitswap", str(exc))


@mcp.tool()
def get_file_bitswap(file_cid: str, file_name: str = "unknown") -> str:
    """
    Improved version of get_file_bitswap with better error handling and support for optional filename hints.
    Queue a file download request by CID via Bitswap.

    Args:
        file_cid: Hex CID of target file.
        file_name: Optional expected filename hint.

    Returns:
        Structured JSON with queue status.
    """
    svc, err = _require_service("get_file_bitswap")
    if err:
        return err

    if not file_cid:
        return _error("get_file_bitswap", "file_cid is required.")

    try:
        queued = svc.download_file(file_cid, file_name)
        if not queued:
            return _error("get_file_bitswap", "Failed to queue file download request.")

        return _ok(
            "get_file_bitswap",
            {
                "status": "download_queued",
                "file_cid": file_cid,
                "file_name": file_name,
            },
        )
    except Exception as exc:
        return _error("get_file_bitswap", str(exc))


@mcp.tool()
def list_shared_files_bitswap() -> str:
    """
    Return all files currently shared by this node.

    Returns:
        Structured JSON listing local shared file metadata.
    """
    svc, err = _require_service("list_shared_files_bitswap")
    if err:
        return err

    try:
        shared_files = [{"cid": cid, **meta} for cid, meta in svc.shared_files.items()]
        return _ok(
            "list_shared_files_bitswap",
            {
                "shared_files": shared_files,
                "count": len(shared_files),
            },
        )
    except Exception as exc:
        return _error("list_shared_files_bitswap", str(exc))


@mcp.tool()
def get_dht_routing_table() -> str:
    """
    Return DHT routing table peer IDs.

    Returns:
        Structured JSON with routing table peers and count.
    """
    svc, err = _require_service("get_dht_routing_table")
    if err:
        return err

    try:
        if not svc.dht:
            return _error("get_dht_routing_table", "DHT is not initialised.")

        peers = [str(p) for p in svc.dht.routing_table.get_peer_ids()]
        return _ok(
            "get_dht_routing_table",
            {
                "routing_table": peers,
                "total_peers": len(peers),
            },
        )
    except Exception as exc:
        return _error("get_dht_routing_table", str(exc))


@mcp.tool()
def get_node_status() -> str:
    """
    Return a full health/status snapshot of the running libp2p node.

    Returns:
        JSON with readiness, peer counts, subscribed topics, and uptime info.
    """
    svc = _service
    if svc is None:
        return _ok(
            "get_node_status",
            {
                "running": False,
                "ready": False,
                "message": "No peer started yet.",
            },
        )

    try:
        connected = svc.host.get_connected_peers() if svc.host else []
        pubsub_peers = list(svc.pubsub.peers.keys()) if svc.pubsub else []
        topics = list(svc.topic_messages.keys())

        mesh = {}
        if svc.gossipsub and hasattr(svc.gossipsub, "mesh"):
            for t, peer_set in svc.gossipsub.mesh.items():
                mesh[t] = len(peer_set)

        return _ok(
            "get_node_status",
            {
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
            },
        )
    except Exception as exc:
        return _error("get_node_status", str(exc))


# ─────────────────────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    logger.info("🚀 Starting goose-libp2p MCP server (stdio transport)…")
    mcp.run(transport="stdio")
