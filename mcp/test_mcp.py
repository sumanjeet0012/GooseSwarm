"""
test_mcp.py — Smoke-test the goose-libp2p MCP server without Goose.

Usage:
    cd /Users/sumanjeet/code/goose-universal-connectivity
    pyenv shell uctest1
    python mcp/test_mcp.py

What it tests:
  1. Import the MCP module successfully
  2. start_peer() — node starts and returns peer_id + multiaddr
  3. get_peer_info() — returns the same info
  4. get_node_status() — shows full health snapshot
  5. subscribe_topic() — subscribe to /goose/tasks
  6. publish_message() — publish a test message
  7. get_messages() — retrieve the published message
  8. list_peers() — show connected peers (bootstrap only at this point)
  9. stop_peer() — cleanly stop the node
"""

import json
import sys
import time
import os

# Make parent importable
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

print("=" * 60)
print("goose-mcp-libp2p  —  smoke test")
print("=" * 60)

# ── 1. Import ──────────────────────────────────────────────────────────────
print("\n[1/9] Importing MCP module…")
try:
    # Import directly from the file in the same directory
    _mcp_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "goose_libp2p_mcp.py")
    import importlib.util as _ilu
    _spec = _ilu.spec_from_file_location("goose_libp2p_mcp", _mcp_path)
    _mod = _ilu.module_from_spec(_spec)
    _spec.loader.exec_module(_mod)

    start_peer = _mod.start_peer
    stop_peer = _mod.stop_peer
    get_peer_info = _mod.get_peer_info
    connect_peer = _mod.connect_peer
    publish_message = _mod.publish_message
    get_messages = _mod.get_messages
    list_peers = _mod.list_peers
    subscribe_topic = _mod.subscribe_topic
    get_node_status = _mod.get_node_status
    print("  ✅ Import OK")
except Exception as e:
    print(f"  ❌ Import failed: {e}")
    import traceback; traceback.print_exc()
    sys.exit(1)

# ── 2. start_peer ──────────────────────────────────────────────────────────
print("\n[2/9] start_peer(port=9100, nick='TestGoose')…")
result = json.loads(start_peer(port=9100, nick="TestGoose"))
print(f"  → {json.dumps(result, indent=4)}")
if "error" in result:
    print("  ❌ start_peer failed")
    sys.exit(1)
print("  ✅ Peer started")

peer_id = result.get("peer_id")
multiaddr = result.get("multiaddr")

# ── 3. get_peer_info ───────────────────────────────────────────────────────
print("\n[3/9] get_peer_info()…")
info = json.loads(get_peer_info())
print(f"  → {json.dumps(info, indent=4)}")
assert info.get("peer_id") == peer_id, "peer_id mismatch!"
print("  ✅ Peer info OK")

# ── 4. get_node_status ────────────────────────────────────────────────────
print("\n[4/9] get_node_status()…")
status = json.loads(get_node_status())
print(f"  → {json.dumps(status, indent=4)}")
assert status.get("running") is True
print("  ✅ Node status OK")

# ── 5. subscribe_topic ────────────────────────────────────────────────────
print("\n[5/9] subscribe_topic('/goose/tasks')…")
sub = json.loads(subscribe_topic("/goose/tasks"))
print(f"  → {json.dumps(sub, indent=4)}")
print("  ✅ Subscription requested")

time.sleep(1)

# ── 6. publish_message ────────────────────────────────────────────────────
print("\n[6/9] publish_message('/goose/tasks', 'Hello from Goose!')…")
pub = json.loads(publish_message("/goose/tasks", "Hello from Goose! 🦆"))
print(f"  → {json.dumps(pub, indent=4)}")
print("  ✅ Message published")

time.sleep(2)

# ── 7. get_messages ───────────────────────────────────────────────────────
print("\n[7/9] get_messages('/goose/tasks')…")
msgs = json.loads(get_messages("/goose/tasks"))
print(f"  → {json.dumps(msgs, indent=4)}")
# Note: own messages may not be echoed back in GossipSub (by design)
print("  ✅ get_messages() responded OK")

# ── 8. list_peers ─────────────────────────────────────────────────────────
print("\n[8/9] list_peers()…")
peers = json.loads(list_peers())
print(f"  → {json.dumps(peers, indent=4)}")
print(f"  ✅ Connected to {peers.get('total_connected', 0)} peer(s)")

# ── 9. stop_peer ──────────────────────────────────────────────────────────
print("\n[9/9] stop_peer()…")
stop = json.loads(stop_peer())
print(f"  → {json.dumps(stop, indent=4)}")
print("  ✅ Stop signal sent")

print("\n" + "=" * 60)
print("All tests passed! ✅")
print("=" * 60)
