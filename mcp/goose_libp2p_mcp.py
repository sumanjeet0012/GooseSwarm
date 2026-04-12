"""
goose-mcp-libp2p — MVP A
========================
A FastMCP server that gives Goose tools to operate a libp2p peer node.

Tools exposed to Goose:
  • start_peer(port, nick, seed, with_api, api_port) — start a libp2p node (optionally with API)
  • stop_peer()                         — stop the running node
  • start_api(api_port)                 — start the REST/WS API server for an existing peer
  • stop_api()                          — stop the API server (peer keeps running)
  • get_api_status()                    — check if the API server is running
  • get_peer_info()                     — return peer ID + multiaddr
  • connect_peer(multiaddr)             — connect to another peer
  • publish_message(topic, message)     — publish via GossipSub
  • get_messages(topic)                 — retrieve received messages
  • list_peers()                        — list connected peers
  • subscribe_topic(topic)              — subscribe to a new topic
  • get_node_status()                   — health / readiness check
  • get_payment_keys()                  — list all peers' payment addresses
  • set_payment_address(eth_addr)       — set your address + broadcast to peers
  • get_my_payment_address()            — check your current payment address
  • send_direct_message(peer_id, msg)  — send a 1-to-1 DM over a libp2p stream
  • get_direct_messages(peer_id)       — read DM history with a peer
  • mark_direct_messages_read(peer_id) — clear unread badge for a peer
  • list_dm_peers()                    — list all DM conversations + unread counts
  • send_payment_to_peer(peer_id, amt) — send Sepolia ETH + DM receipt

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

# ── Tornado API server state ──────────────────────────────────────────────────
_tornado_server: Optional[Any] = None   # TornadoServer instance
_api_thread: Optional[threading.Thread] = None

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
def start_peer(
    port: int = 9000,
    nick: str = "GooseAgent",
    seed: str = None,
    with_api: bool = False,
    api_port: int = 8765,
) -> str:
    """
    Start a libp2p peer node, optionally also starting the REST/WebSocket API server.

    Args:
        port: TCP port for the libp2p node to listen on (default 9000).
        nick: Human-readable nickname for this peer (default "GooseAgent").
        seed: Optional seed string for deterministic peer identity.
        with_api: If True, also start the Tornado REST/WebSocket API server
                  so the React frontend and other HTTP clients can connect.
                  If False (default), only the libp2p node is started — useful
                  for headless / agent-only operation.
        api_port: Port for the Tornado API server (default 8765, only used when
                  with_api=True).

    Returns:
        JSON string with peer_id, multiaddr, and api_url (if started) on success,
        or an error message.
    """
    global _service, _service_thread, _tornado_server, _api_thread

    with _service_lock:
        if _service is not None and getattr(_service, "ready", False):
            result = {
                "status": "already_running",
                "peer_id": str(_service.host.get_id()),
                "multiaddr": _service.full_multiaddr,
            }
            if _tornado_server is not None:
                result["api_url"] = f"http://localhost:{_tornado_server.port}"
            return _ok("start_peer", result)

        logger.info(f"Starting libp2p peer — nick={nick}, port={port}, with_api={with_api}")
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
    result: dict[str, Any] = {
        "status": "started",
        "peer_id": str(svc.host.get_id()),
        "multiaddr": svc.full_multiaddr,
        "nick": nick,
        "port": port,
        "api_started": False,
    }

    # Optionally start the Tornado API server
    if with_api:
        try:
            from tornado_server import TornadoServer  # noqa: PLC0415

            def _run_api():
                global _tornado_server
                server = TornadoServer(svc, port=api_port)
                _tornado_server = server
                logger.info(f"Tornado API server starting on port {api_port}")
                server.start()  # blocks until IOLoop stops

            api_t = threading.Thread(target=_run_api, daemon=True, name="tornado-api")
            _api_thread = api_t
            api_t.start()

            # Give Tornado a moment to bind the port
            time.sleep(1.5)

            result["api_started"] = True
            result["api_url"] = f"http://localhost:{api_port}"
            result["api_port"] = api_port
        except Exception as exc:
            result["api_error"] = str(exc)
            logger.error(f"Failed to start Tornado API: {exc}")

    return _ok("start_peer", result)


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
def start_api(api_port: int = 8765) -> str:
    """
    Start the Tornado REST/WebSocket API server for an already-running peer node.

    Use this if you called start_peer(with_api=False) and later want to expose
    the HTTP API (e.g. so the React frontend can connect).

    Args:
        api_port: Port to listen on (default 8765).

    Returns:
        JSON with api_url on success, or an error message.
    """
    global _tornado_server, _api_thread

    svc, err = _require_service("start_api")
    if err:
        return err

    if _tornado_server is not None and _api_thread is not None and _api_thread.is_alive():
        return _ok("start_api", {
            "status": "already_running",
            "api_url": f"http://localhost:{_tornado_server.port}",
        })

    try:
        from tornado_server import TornadoServer  # noqa: PLC0415

        def _run_api():
            global _tornado_server
            server = TornadoServer(svc, port=api_port)
            _tornado_server = server
            logger.info(f"Tornado API server starting on port {api_port}")
            server.start()  # blocks until IOLoop stops

        api_t = threading.Thread(target=_run_api, daemon=True, name="tornado-api")
        _api_thread = api_t
        api_t.start()

        time.sleep(1.5)  # give Tornado a moment to bind

        return _ok("start_api", {
            "status": "started",
            "api_url": f"http://localhost:{api_port}",
            "api_port": api_port,
        })
    except Exception as exc:
        return _error("start_api", str(exc))


@mcp.tool()
def stop_api() -> str:
    """
    Stop the Tornado REST/WebSocket API server (the libp2p peer keeps running).

    Returns:
        Confirmation or error message.
    """
    global _tornado_server, _api_thread

    if _tornado_server is None:
        return _error("stop_api", "API server is not running.")

    try:
        import tornado.ioloop  # noqa: PLC0415
        ioloop = tornado.ioloop.IOLoop.current()
        ioloop.add_callback(ioloop.stop)

        if _api_thread and _api_thread.is_alive():
            _api_thread.join(timeout=5)

        _tornado_server = None
        _api_thread = None

        return _ok("stop_api", {"status": "stopped"})
    except Exception as exc:
        return _error("stop_api", str(exc))


@mcp.tool()
def get_api_status() -> str:
    """
    Return the current status of the Tornado REST/WebSocket API server.

    Returns:
        JSON with running status and api_url if active.
    """
    if _tornado_server is None or _api_thread is None or not _api_thread.is_alive():
        return _ok("get_api_status", {"running": False})

    return _ok("get_api_status", {
        "running": True,
        "api_url": f"http://localhost:{_tornado_server.port}",
        "api_port": _tornado_server.port,
    })


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


@mcp.tool()
def send_payment_to_peer(peer_id: str, amount_eth: float = 0.01) -> str:
    """
    Send Sepolia ETH to a peer if they have broadcasted their payment key,
    and automatically send them the transaction receipt in a direct message.

    Args:
        peer_id: The peer ID to send the payment to.
        amount_eth: Amount in ETH to send (default 0.01).
    """
    import os
    from dotenv import load_dotenv

    svc = _service
    if svc is None:
        return _error("send_payment_to_peer", "No peer running. Call start_peer() first.")
    if not svc.ready:
        return _error("send_payment_to_peer", "Peer is not ready yet.")

    # 1. Check if peer has broadcasted payment key
    recipient_address = svc.payment_keys.get(peer_id)
    if not recipient_address:
        return _error("send_payment_to_peer", f"Peer {peer_id} has not broadcasted a payment key.")

    try:
        from web3 import Web3, exceptions
    except ImportError:
        return _error("send_payment_to_peer", "web3 package is not installed. Run: pip install web3")

    if not Web3.is_address(recipient_address):
        return _error("send_payment_to_peer", f"Peer {peer_id} has an invalid payment address: {recipient_address}")

    recipient_address = Web3.to_checksum_address(recipient_address)

    # 2. Get private key
    load_dotenv(os.path.join(_ROOT_DIR, ".env"))
    private_key = os.environ.get("AGENT_PRIVATE_KEY")
    if not private_key:
        return _error("send_payment_to_peer", "AGENT_PRIVATE_KEY not found in .env file.")

    # 3. Connect to Sepolia RPC
    # Priority: SEPOLIA_RPC_URL env var → fallback public nodes
    _SEPOLIA_RPC_FALLBACKS = [
        "https://rpc2.sepolia.org",
        "https://sepolia.drpc.org",
        "https://ethereum-sepolia-rpc.publicnode.com",
    ]

    rpc_url = os.environ.get("SEPOLIA_RPC_URL") or ""
    rpc_candidates = ([rpc_url] if rpc_url else []) + _SEPOLIA_RPC_FALLBACKS

    try:
        w3 = None
        for candidate in rpc_candidates:
            try:
                _w3 = Web3(Web3.HTTPProvider(candidate, request_kwargs={'timeout': 15}))
                if _w3.is_connected():
                    w3 = _w3
                    logger.info(f"Connected to Sepolia RPC: {candidate}")
                    break
            except Exception:
                continue

        if w3 is None:
            return _error("send_payment_to_peer", f"Failed to connect to any Sepolia RPC node. Tried: {rpc_candidates}")

        account = w3.eth.account.from_key(private_key)
        amount_wei = w3.to_wei(amount_eth, 'ether')
        balance = w3.eth.get_balance(account.address)

        if balance < amount_wei:
            return _error("send_payment_to_peer", f"Insufficient funds. Balance: {w3.from_wei(balance, 'ether')} ETH, required: {amount_eth} ETH")

        # Fallback to simple gas price to avoid EIP-1559 base fee fetching issues on some testnets
        base_fee = w3.eth.get_block('latest').get('baseFeePerGas', None)
        tx = {
            'nonce': w3.eth.get_transaction_count(account.address, 'pending'),
            'to': recipient_address,
            'value': amount_wei,
            'chainId': 11155111,  # Sepolia
        }

        if base_fee is not None:
            max_priority = w3.eth.max_priority_fee or w3.to_wei(1, 'gwei')
            tx['maxFeePerGas'] = int(base_fee * 1.5) + max_priority
            tx['maxPriorityFeePerGas'] = max_priority
        else:
            tx['gasPrice'] = w3.eth.gas_price

        # Estimate gas
        gas_estimate = w3.eth.estimate_gas(tx)
        tx['gas'] = int(gas_estimate * 1.2)

        logger.info(f"Signing transaction to send {amount_eth} ETH to {recipient_address}")
        signed_tx = w3.eth.account.sign_transaction(tx, private_key)

        logger.info("Broadcasting transaction...")
        # Handle both old (rawTransaction) and new (raw_transaction) web3.py versions
        raw_tx = getattr(signed_tx, 'raw_transaction', None) or getattr(signed_tx, 'rawTransaction', None)
        tx_hash = w3.eth.send_raw_transaction(raw_tx)
        tx_hash_hex = w3.to_hex(tx_hash)

        logger.info(f"Transaction broadcasted: {tx_hash_hex}. Waiting for receipt...")
        receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)

        if receipt['status'] != 1:
            return _error("send_payment_to_peer", f"Transaction reverted on-chain. Hash: {tx_hash_hex}")

    except Exception as e:
        return _error("send_payment_to_peer", f"Transaction failed: {str(e)}")

    # 4. DM the receipt
    receipt_url = f"https://sepolia.etherscan.io/tx/{tx_hash_hex}"
    message = f"💳 Payment of {amount_eth} SEP sent via Sepolia Testnet.\n{receipt_url}"
    success = svc.send_direct_message(peer_id, message, source='mcp')

    if not success:
        return _ok("send_payment_to_peer", {
            "tx_hash": tx_hash_hex, 
            "explorer_url": receipt_url,
            "warning": "Transaction succeeded, but failed to queue DM to peer."
        })

    return _ok("send_payment_to_peer", {
        "tx_hash": tx_hash_hex,
        "explorer_url": receipt_url,
        "message": message,
        "dm_sent": True
    })

# ─────────────────────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────────────────────

@mcp.tool()
def get_payment_keys() -> str:
    """
    Return all payment keys (Ethereum addresses) broadcasted by peers.

    Returns:
        JSON with peer_id -> eth_address mapping.
    """
    svc, err = _require_service("get_payment_keys", require_ready=True)
    if err:
        return err

    return _ok("get_payment_keys", {
        "payment_keys": dict(svc.payment_keys),
        "count": len(svc.payment_keys)
    })


@mcp.tool()
def set_payment_address(eth_address: str) -> str:
    """
    Set your own Ethereum payment address and broadcast it to all connected peers.
    
    This allows peers to see your address and send you direct payments via MetaMask.
    The address will be shared with every connected peer and advertised to new peers
    when they connect.

    Args:
        eth_address: Valid Ethereum address (0x..., 40 hex chars).

    Returns:
        JSON with the set address and broadcast status.
    """
    try:
        from web3 import Web3  # noqa: PLC0415
    except ImportError:
        return _error("set_payment_address", "web3 package is not installed. Run: pip install web3")

    svc, err = _require_service("set_payment_address", require_ready=True)
    if err:
        return err

    # Validate Ethereum address format
    if not Web3.is_address(eth_address):
        return _error("set_payment_address", f"Invalid Ethereum address: {eth_address}. Expected format: 0x<40 hex chars>")

    # Normalize to checksum address
    checksum_address = Web3.to_checksum_address(eth_address)

    try:
        svc.set_my_payment_key(checksum_address)
        logger.info(f"Payment address set and broadcast: {checksum_address}")
        return _ok("set_payment_address", {
            "status": "set_and_broadcast",
            "address": checksum_address,
            "message": f"Your payment address has been broadcast to {len(svc.chat_room.get_connected_peers()) if svc.chat_room else 0} connected peers",
        })
    except Exception as exc:
        return _error("set_payment_address", f"Failed to set payment address: {str(exc)}")


@mcp.tool()
def get_my_payment_address() -> str:
    """
    Retrieve your current payment address.

    Returns:
        JSON with your payment address, or empty string if not set.
    """
    svc, err = _require_service("get_my_payment_address", require_ready=True)
    if err:
        return err

    return _ok("get_my_payment_address", {
        "address": svc.my_payment_key,
        "is_set": bool(svc.my_payment_key),
    })


@mcp.tool()
def send_direct_message(peer_id: str, message: str) -> str:
    """
    Send a direct message to a specific peer over a dedicated libp2p stream
    (bypasses GossipSub — only you and the recipient see this message).

    Args:
        peer_id: The peer ID to send the message to.
        message: The message content to send.

    Returns:
        JSON with send status.
    """
    svc, err = _require_service("send_direct_message", require_ready=True)
    if err:
        return err

    success = svc.send_direct_message(peer_id, message, source='mcp')

    if success:
        return _ok("send_direct_message", {
            "status": "queued",
            "peer_id": peer_id,
            "message": message,
        })
    else:
        return _error("send_direct_message", "Failed to queue direct message. Peer may not be connected.")


@mcp.tool()
def get_direct_messages(peer_id: str, limit: int = 50) -> str:
    """
    Retrieve the DM history with a specific peer.

    Args:
        peer_id: The peer ID whose conversation you want to read.
        limit: Maximum number of messages to return, most-recent last (default 50).

    Returns:
        JSON with the message list, total count, and unread count.
    """
    svc, err = _require_service("get_direct_messages")
    if err:
        return err

    messages = svc.get_dm_messages(peer_id)
    unread = svc.get_dm_unread_count(peer_id)

    # Return last `limit` messages
    result = messages[-limit:] if len(messages) > limit else messages

    return _ok("get_direct_messages", {
        "peer_id": peer_id,
        "messages": result,
        "total": len(messages),
        "returned": len(result),
        "unread": unread,
    })


@mcp.tool()
def mark_direct_messages_read(peer_id: str) -> str:
    """
    Mark all DMs from a specific peer as read (clears the unread badge).

    Args:
        peer_id: The peer ID whose messages should be marked read.

    Returns:
        JSON confirmation.
    """
    svc, err = _require_service("mark_direct_messages_read")
    if err:
        return err

    svc.mark_dm_as_read(peer_id)
    return _ok("mark_direct_messages_read", {
        "peer_id": peer_id,
        "status": "marked_read",
    })


@mcp.tool()
def list_dm_peers() -> str:
    """
    List all peers you have an existing DM conversation with,
    along with unread counts and the last message preview.

    Returns:
        JSON with a list of peer conversations sorted by most recent activity.
    """
    svc, err = _require_service("list_dm_peers")
    if err:
        return err

    conversations = []
    for pid, msgs in svc.dm_messages.items():
        if not msgs:
            continue
        last = msgs[-1]
        conversations.append({
            "peer_id": pid,
            "message_count": len(msgs),
            "unread": svc.get_dm_unread_count(pid),
            "last_message": last.get("message", ""),
            "last_timestamp": last.get("timestamp", 0),
            "payment_key": svc.payment_keys.get(pid, ""),
        })

    # Sort by most recent activity
    conversations.sort(key=lambda c: c["last_timestamp"], reverse=True)

    return _ok("list_dm_peers", {
        "conversations": conversations,
        "total": len(conversations),
    })


if __name__ == "__main__":
    logger.info("🚀 Starting goose-libp2p MCP server (stdio transport)…")
    mcp.run(transport="stdio")
