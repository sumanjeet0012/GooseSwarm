# NAT Traversal in GooseSwarm — Complete Integration Guide

> **Repo analysed:** `github.com/sumanjeet0012/goose-universal-connectivity`  
> **py-libp2p source ref:** `github.com/libp2p/py-libp2p` (latest)  
> **Written:** April 2026

---

## 1. Current State of the Repo

After cloning and fully analysing `headless.py`, `api/`, `mcp/`, and the GooseSwarm architecture, here is what exists **today**:

| Component | Status |
|---|---|
| Transport | **TCP only** — `multiaddr.Multiaddr(f"/ip4/0.0.0.0/tcp/{self.port}")` |
| Discovery | Bootstrap peers (hardcoded IPFS nodes) + KadDHT random walk |
| NAT Traversal | ❌ **None whatsoever** |
| Relay | ❌ Not configured |
| AutoNAT | ❌ Not configured |
| UPnP | ❌ Not configured |
| Hole Punching (DCUtR) | ❌ Not configured |
| mDNS | ❌ Not configured |
| QUIC | ❌ Not added |

**What this means in practice:** Any Goose agent running behind a home router, cloud NAT (AWS/GCP private subnet), or any firewall **cannot receive inbound connections** and cannot be reached by other agents for task broadcasting, bidding, or result delivery. The entire multi-agent mesh breaks under real-world network conditions.

---

## 2. What NAT Traversal Methods py-libp2p Provides

py-libp2p has **six distinct NAT traversal mechanisms**, all fully implemented and importable right now.

### 2.1 Circuit Relay v2 (`libp2p.relay.circuit_v2`)

A publicly reachable relay node proxies traffic between two NATed peers. This is the **guaranteed fallback** — it always works regardless of NAT type.

**Key classes:**
```python
from libp2p.relay.circuit_v2.protocol import CircuitV2Protocol, PROTOCOL_ID, STOP_PROTOCOL_ID
from libp2p.relay.circuit_v2.transport import CircuitV2Transport
from libp2p.relay.circuit_v2.config import RelayConfig, RelayRole
from libp2p.relay.circuit_v2.resources import RelayLimits
from libp2p.relay.circuit_v2.discovery import RelayDiscovery
```

**How it works:**
1. A relay node (publicly reachable) registers as a HOP relay.
2. A NATed agent connects to the relay and **reserves** a slot.
3. The relay advertises a **p2p-circuit** multiaddr for that agent via DHT.
4. Another agent dials using: `/ip4/RELAY_IP/tcp/PORT/p2p/RELAY_ID/p2p-circuit/p2p/DEST_ID`

**Three roles in `RelayRole`:**
- `HOP` — the relay itself (forwards traffic)
- `STOP` — destination end of a relayed connection
- `CLIENT` — uses relays to connect and be reachable

### 2.2 DCUtR — Direct Connection Upgrade through Relay (`libp2p.relay.circuit_v2.dcutr`)

After two peers establish a relayed connection, DCUtR attempts **simultaneous TCP/QUIC hole punching** to upgrade to a direct connection. The relay is used only to synchronise the punch timing.

```python
from libp2p.relay.circuit_v2.dcutr import DCUtRProtocol, PROTOCOL_ID as DCUTR_PROTOCOL_ID
```

**How it works:**
1. Both peers share their observed external addresses via the relay.
2. Both simultaneously dial each other's observed addresses at `T + delta`.
3. If either side's NAT is "cone" type, the SYN packets cross and a direct connection forms.
4. The relay connection is then dropped.

**Supports up to `MAX_HOLE_PUNCH_ATTEMPTS = 5` retries** per peer pair.

### 2.3 AutoNAT (`libp2p.host.autonat`)

A diagnostic service that asks connected peers to attempt reverse dials. Based on results it classifies the node as `PUBLIC`, `PRIVATE`, or `UNKNOWN`. Critical for deciding whether Circuit Relay is needed at all.

```python
from libp2p.host.autonat import AutoNATService, AutoNATStatus
# AutoNATStatus.PUBLIC  = 1
# AutoNATStatus.PRIVATE = 2
# AutoNATStatus.UNKNOWN = 0
```

**Protocol ID:** `/ipfs/autonat/1.0.0`

### 2.4 UPnP Port Mapping (`libp2p.discovery.upnp`)

If the router at the agent's location supports UPnP/IGD, py-libp2p can **automatically open a port** on the router, converting a NATed node into a publicly reachable one without any relay.

```python
from libp2p.discovery.upnp.upnp import UpnpManager
```

Works via `miniupnpc`. Fails silently on routers where UPnP is disabled (most cloud VMs, ISP-grade CGNAT, corporate networks). Should always be tried first — it's zero-latency overhead if it works.

### 2.5 mDNS Local Discovery (`libp2p.discovery.mdns`)

Discovers peers on the **same LAN segment** without any external infrastructure by broadcasting mDNS packets. Useful for multi-agent setups within a single machine or data centre VLAN.

```python
from libp2p.discovery.mdns.broadcaster import MDNSBroadcaster
from libp2p.discovery.mdns.listener import MDNSListener
```

### 2.6 QUIC Transport (`libp2p.transport.quic`)

QUIC runs over UDP and has **inherent NAT traversal advantages** over TCP:
- UDP hole punching is easier (stateless NAT traversal)
- Connection migration (works across IP changes, e.g. mobile devices)
- Multiplexed streams without head-of-line blocking

```python
from libp2p.transport.quic.transport import QUICTransport
```

Multiaddr format: `/ip4/0.0.0.0/udp/9095/quic-v1`

---

## 3. How to Integrate Each Method into GooseSwarm

### 3.1 Step 0 — Add AutoNAT (detect your situation first)

Modify `_run_service` in `headless.py` to initialise AutoNAT right after the host is created:

```python
from libp2p.host.autonat import AutoNATService, AutoNATStatus
from libp2p.host.basic_host import BasicHost
from typing import cast

# Inside _run_service, after: self.host = new_host(...)
self.autonat = AutoNATService(cast(BasicHost, self.host))
self.host.set_stream_handler(
    "/ipfs/autonat/1.0.0",
    self.autonat.handle_stream
)
logger.info("✅ AutoNAT service initialised")
```

Then add a helper to check and log the result after bootstrap:

```python
async def _log_nat_status(self):
    await trio.sleep(15)  # let bootstrap peers connect first
    status = self.autonat.get_status()
    label = {
        AutoNATStatus.PUBLIC: "PUBLIC (no relay needed)",
        AutoNATStatus.PRIVATE: "PRIVATE (Circuit Relay required)",
        AutoNATStatus.UNKNOWN: "UNKNOWN (insufficient peers to determine)"
    }.get(status, "UNKNOWN")
    logger.info(f"🌐 AutoNAT status: {label}")
    self.nat_status = status  # store for later decisions
```

Call it from the nursery in `_run_service`:
```python
nursery.start_soon(self._log_nat_status)
```

---

### 3.2 Step 1 — UPnP (try before everything else)

Add this to `_run_service`, **before** `host.run()`:

```python
from libp2p.discovery.upnp.upnp import UpnpManager

self.upnp = UpnpManager()
upnp_ok = await self.upnp.discover()
if upnp_ok:
    mapped = await self.upnp.add_port_mapping(
        internal_port=self.port,
        external_port=self.port,
        protocol="TCP",
        description="GooseSwarm Agent"
    )
    if mapped:
        ext_ip = await self.upnp.get_external_ip()
        logger.info(f"✅ UPnP: external TCP port {self.port} opened on {ext_ip}")
        self.full_multiaddr = f"/ip4/{ext_ip}/tcp/{self.port}/p2p/{self.host.get_id()}"
    else:
        logger.warning("⚠️  UPnP: port mapping failed — will fall back to relay")
else:
    logger.info("ℹ️  UPnP not available on this network")
```

Clean up on stop:
```python
# In stop():
if self.upnp:
    await self.upnp.remove_port_mapping(self.port, "TCP")
```

---

### 3.3 Step 2 — QUIC Transport (add alongside TCP)

Change the listen address section in `_run_service`:

```python
# Before — TCP only:
listen_addr = multiaddr.Multiaddr(f"/ip4/0.0.0.0/tcp/{self.port}")

# After — TCP + QUIC:
listen_addrs = [
    multiaddr.Multiaddr(f"/ip4/0.0.0.0/tcp/{self.port}"),
    multiaddr.Multiaddr(f"/ip4/0.0.0.0/udp/{self.port}/quic-v1"),
]
```

Then in `host.run(...)`:
```python
async with self.host.run(listen_addrs=listen_addrs):
    ...
```

Update `full_multiaddr` to advertise both:
```python
self.full_multiaddr = (
    f"/ip4/0.0.0.0/tcp/{self.port}/p2p/{self.host.get_id()}"
    f"\n/ip4/0.0.0.0/udp/{self.port}/quic-v1/p2p/{self.host.get_id()}"
)
```

---

### 3.4 Step 3 — Circuit Relay v2 (the main NAT fix)

This is the most impactful change. You need two pieces: a **relay setup** (can be your EC2 runner from `py-libp2p-runners`) and **client code** in every agent.

#### 3.4a — Relay Node (runs on your EC2 / public server)

Create `goose_relay_node.py` (standalone script):

```python
import multiaddr
import trio
from libp2p import new_host
from libp2p.crypto.ed25519 import create_new_key_pair
from libp2p.relay.circuit_v2.protocol import (
    CircuitV2Protocol, PROTOCOL_ID, STOP_PROTOCOL_ID
)
from libp2p.relay.circuit_v2.transport import CircuitV2Transport
from libp2p.relay.circuit_v2.config import RelayConfig, RelayRole
from libp2p.relay.circuit_v2.resources import RelayLimits
from libp2p.tools.anyio_service import background_trio_service

async def run_relay(port: int = 4002):
    key_pair = create_new_key_pair()
    host = new_host(key_pair=key_pair)

    limits = RelayLimits(
        duration=7200,            # 2 hours per circuit
        data=512 * 1024 * 1024,   # 512 MB per circuit
        max_circuit_conns=100,    # 100 simultaneous circuits
        max_reservations=50,      # 50 agent reservations
    )
    relay_config = RelayConfig(
        roles=RelayRole.HOP | RelayRole.STOP | RelayRole.CLIENT,
        limits=limits,
    )
    protocol = CircuitV2Protocol(host, limits=limits, allow_hop=True)

    async with host.run(listen_addrs=[multiaddr.Multiaddr(f"/ip4/0.0.0.0/tcp/{port}")]):
        host.set_stream_handler(PROTOCOL_ID, protocol._handle_hop_stream)
        host.set_stream_handler(STOP_PROTOCOL_ID, protocol._handle_stop_stream)
        async with background_trio_service(protocol):
            CircuitV2Transport(host, protocol, relay_config)
            print(f"GooseSwarm Relay running: /ip4/YOUR_EC2_IP/tcp/{port}/p2p/{host.get_id()}")
            await trio.sleep_forever()

trio.run(run_relay)
```

#### 3.4b — Agent Client Code (in `headless.py`)

Add relay setup inside `_run_service`, after pubsub starts:

```python
from libp2p.relay.circuit_v2.protocol import (
    CircuitV2Protocol, PROTOCOL_ID as RELAY_PROTOCOL_ID,
    STOP_PROTOCOL_ID as RELAY_STOP_PROTOCOL_ID
)
from libp2p.relay.circuit_v2.transport import CircuitV2Transport
from libp2p.relay.circuit_v2.config import RelayConfig, RelayRole
from libp2p.relay.circuit_v2.resources import RelayLimits
from libp2p.relay.circuit_v2.discovery import RelayDiscovery

# GooseSwarm relay nodes (your EC2 instances)
GOOSESWARM_RELAYS = [
    "/ip4/YOUR_EC2_IP/tcp/4002/p2p/RELAY_PEER_ID",
]

# Add these inside _run_service, inside the nested async withs:
relay_limits = RelayLimits(
    duration=3600,
    data=100 * 1024 * 1024,
    max_circuit_conns=10,
    max_reservations=3,
)
relay_config = RelayConfig(
    roles=RelayRole.STOP | RelayRole.CLIENT,
    limits=relay_limits,
)
self.relay_protocol = CircuitV2Protocol(
    self.host, limits=relay_limits, allow_hop=False
)
self.host.set_stream_handler(
    RELAY_PROTOCOL_ID, self.relay_protocol._handle_hop_stream
)
self.host.set_stream_handler(
    RELAY_STOP_PROTOCOL_ID, self.relay_protocol._handle_stop_stream
)

async with background_trio_service(self.relay_protocol):
    self.relay_transport = CircuitV2Transport(
        self.host, self.relay_protocol, relay_config
    )
    self.relay_discovery = RelayDiscovery(self.host, auto_reserve=True)
    self.relay_transport.discovery = self.relay_discovery

    async with background_trio_service(self.relay_discovery):
        # Connect to GooseSwarm relay nodes
        for relay_addr in GOOSESWARM_RELAYS:
            try:
                rinfo = info_from_p2p_addr(multiaddr.Multiaddr(relay_addr))
                await self.host.connect(rinfo)
                logger.info(f"✅ Connected to GooseSwarm relay: {rinfo.peer_id}")
            except Exception as e:
                logger.warning(f"⚠️  Relay connection failed: {e}")

        # Continue with the rest of the service...
        await self._setup_chat_room()
        await self._setup_connections()
        ...
```

To **dial another agent through the relay**, construct the circuit address:
```python
circuit_addr = multiaddr.Multiaddr(
    f"/ip4/RELAY_IP/tcp/4002/p2p/RELAY_PEER_ID"
    f"/p2p-circuit/p2p/{target_agent_peer_id}"
)
connection = await self.relay_transport.dial(circuit_addr)
```

---

### 3.5 Step 4 — DCUtR Hole Punching (upgrade relayed → direct)

Add alongside Circuit Relay setup:

```python
from libp2p.relay.circuit_v2.dcutr import DCUtRProtocol

self.dcutr = DCUtRProtocol(self.host)

async with background_trio_service(self.dcutr):
    await self.dcutr.event_started.wait()
    logger.info("✅ DCUtR hole-punching service ready")
    # ... rest of service continues
```

After connecting to a peer via relay, attempt a direct upgrade:

```python
async def _try_hole_punch(self, peer_id: ID) -> bool:
    """Attempt DCUtR hole punching after establishing relay connection."""
    try:
        logger.info(f"🕳️  Attempting DCUtR hole punch to {str(peer_id)[:12]}...")
        success = await self.dcutr.initiate_hole_punch(peer_id)
        if success:
            logger.info(f"✅ Direct connection established with {str(peer_id)[:12]}")
        else:
            logger.info(f"ℹ️  Hole punch failed, staying on relay for {str(peer_id)[:12]}")
        return success
    except Exception as e:
        logger.warning(f"⚠️  DCUtR error: {e}")
        return False
```

Call this after any relayed task assignment or bid connection.

---

### 3.6 Step 5 — mDNS (local agent discovery)

For GooseSwarm agents running on the same machine or LAN (e.g. multiple workers on one EC2):

```python
from libp2p.discovery.mdns.broadcaster import MDNSBroadcaster
from libp2p.discovery.mdns.listener import MDNSListener

# In _run_service, after host.run():
mdns_broadcaster = MDNSBroadcaster(
    self.host,
    service_name="_gooseswarm._tcp.local.",
    port=self.port
)
mdns_listener = MDNSListener(
    self.host,
    service_name="_gooseswarm._tcp.local.",
    on_peer_found=self._on_mdns_peer_found
)

nursery.start_soon(mdns_broadcaster.run)
nursery.start_soon(mdns_listener.run)
```

```python
async def _on_mdns_peer_found(self, peer_info):
    """Auto-connect to locally discovered agents."""
    try:
        await self.host.connect(peer_info)
        logger.info(f"✅ mDNS: connected to local agent {peer_info.peer_id}")
    except Exception as e:
        logger.debug(f"mDNS connect failed: {e}")
```

---

## 4. Complete Integration Architecture

```
GooseSwarm Agent (behind NAT)
│
├── Transport Layer
│   ├── TCP /ip4/0.0.0.0/tcp/9095          ← direct if reachable
│   └── QUIC /ip4/0.0.0.0/udp/9095/quic-v1 ← UDP hole punching
│
├── AutoNAT Service
│   └── Asks peers to dial back → determines PUBLIC/PRIVATE/UNKNOWN
│
├── UPnP Manager
│   └── Opens router port if IGD available → becomes directly reachable
│
├── mDNS Discovery
│   └── Finds other GooseSwarm agents on same LAN instantly
│
├── Circuit Relay v2 Client
│   ├── Connects to GooseSwarm relay (EC2)
│   ├── Reserves relay slot → gets /p2p-circuit multiaddr
│   └── Advertises relayed address in DHT
│
└── DCUtR Protocol
    └── After relay connect → simultaneous hole punch → direct connection
```

**Decision flow at startup:**
```
[Start] → Try UPnP → Success? → Use direct address, skip relay
                   → Fail?    → Check AutoNAT
                                  PUBLIC?  → Use direct TCP/QUIC
                                  PRIVATE? → Activate Circuit Relay v2
                                             → After relay conn → Try DCUtR
                                  UNKNOWN? → Activate relay defensively
```

---

## 5. Real Benefits for GooseSwarm Specifically

### 5.1 Task Broadcasting Reaches All Agents

**Without NAT traversal:** A Goose agent publishing to `/gooseswarm/tasks/available` via GossipSub only reaches agents it can directly dial. Agents behind NAT never hear about tasks.

**With Circuit Relay v2:** Every agent reserves a relay slot at startup. GossipSub mesh is built over these relay connections. Tasks broadcast to **all** agents regardless of network topology.

**Concrete win:** Your GooseSwarm cluster on EC2 + local dev machines + cloud workers all see the same task stream.

---

### 5.2 Bidding and Assignment Work Under Real Network Conditions

**Without:** `/gooseswarm/tasks/bids` messages from NATed agents either never arrive or arrive with high latency (DHT routing only).

**With DCUtR:** After the first relay-mediated bid exchange, DCUtR upgrades to a direct connection. Subsequent task assignment messages on `/gooseswarm/tasks/assigned` travel at wire speed, not through an intermediary.

**Concrete win:** Bid→assign round trip drops from ~500ms (relay) to ~20ms (direct) for agents that successfully hole-punch.

---

### 5.3 x402 Payment Negotiation is Reliable

The x402 HTTP payment flow (Base Sepolia → Tornado API) requires the paying agent to reach the serving agent's HTTP endpoint. If the serving agent is NATed:

- **Without relay:** `402 Payment Required` response never delivered; agent cannot initiate payment.
- **With Circuit Relay:** The serving agent's `/p2p-circuit` multiaddr is reachable → libp2p stream carries the 402 challenge → payment flow completes.
- **After DCUtR:** Payment HTTP requests go direct, reducing latency and eliminating relay bandwidth cost (critical for high-frequency micropayments).

---

### 5.4 NaCl-Encrypted Result Delivery is Guaranteed

Results on `/gooseswarm/results/{taskId}` are NaCl-encrypted and sent point-to-point. If the task requester is NATed:

- **Without:** Result delivery silently fails.
- **With relay:** Result is delivered via relay connection → decrypted → reputation update applied.

---

### 5.5 Reputation Staking Nodes Stay Connected

Reputation staking requires persistent peer connections for heartbeats on `/gooseswarm/agents/heartbeat`. Connection drops from NAT timeouts (typically 30–120s for TCP NAT) corrupt the heartbeat timeline.

- **QUIC** keeps connections alive with built-in keep-alive and handles IP changes (e.g. mobile agent or EC2 spot instance replacement).
- **mDNS** reconnects local agents within milliseconds of a NAT table flush.

---

### 5.6 GooseDaemon Process Survives Network Changes

The persistent `GooseDaemon` you designed must handle EC2 instance restarts, spot interruptions, and IP changes.

- **QUIC connection migration** handles IP changes transparently at the transport layer.
- **Auto-reconnect to relay** after disconnect means the daemon re-announces itself without losing its peer ID or reputation history.

---

### 5.7 Multi-Agent Coordination Without Central Servers

A core GooseSwarm goal is **censorship-resistant, serverless** coordination. NAT traversal is what makes this real:

| Scenario | Without NAT traversal | With all 5 methods |
|---|---|---|
| 2 home laptops coordinating | ❌ Neither can dial the other | ✅ Both reach relay, DCUtR punches direct hole |
| EC2 private subnet agents | ❌ Only public agents reachable | ✅ Relay on public EC2, all agents reach it |
| Mobile Goose agent | ❌ IP changes break connection | ✅ QUIC migration keeps session alive |
| Local dev cluster (same machine) | ⚠️ Bootstrap-only | ✅ mDNS finds all local agents in <1s |
| Agent behind corporate firewall | ❌ All inbound blocked | ✅ Relay handles all traffic (outbound-only required) |

---

## 6. Recommended Implementation Order

1. **AutoNAT** — zero risk, diagnostic only, tells you the exact problem (30 min)
2. **UPnP** — try first, costs nothing if it fails (1 hour)
3. **QUIC transport** — add alongside TCP, no breaking changes (2 hours)
4. **Circuit Relay v2** — deploy relay on your EC2 runner, integrate client in headless.py (1 day)
5. **DCUtR** — add after relay works, async upgrade, non-blocking (2 hours)
6. **mDNS** — only needed if running multi-agent on same LAN (1 hour)

Total estimated effort: **~2 days** to full NAT traversal stack.

---

## 7. Key py-libp2p Import Summary

```python
# AutoNAT
from libp2p.host.autonat import AutoNATService, AutoNATStatus

# UPnP
from libp2p.discovery.upnp.upnp import UpnpManager

# Circuit Relay v2
from libp2p.relay.circuit_v2.protocol import CircuitV2Protocol, PROTOCOL_ID, STOP_PROTOCOL_ID
from libp2p.relay.circuit_v2.transport import CircuitV2Transport
from libp2p.relay.circuit_v2.config import RelayConfig, RelayRole
from libp2p.relay.circuit_v2.resources import RelayLimits
from libp2p.relay.circuit_v2.discovery import RelayDiscovery

# DCUtR hole punching
from libp2p.relay.circuit_v2.dcutr import DCUtRProtocol

# mDNS
from libp2p.discovery.mdns.broadcaster import MDNSBroadcaster
from libp2p.discovery.mdns.listener import MDNSListener

# QUIC (already in libp2p transport registry — just change the multiaddr)
# /ip4/0.0.0.0/udp/PORT/quic-v1
```

---

## 8. Files to Modify in the Repo

| File | Change |
|---|---|
| `headless.py` | Add AutoNAT, UPnP, relay client, DCUtR, mDNS initialisation inside `_run_service` and `_run_service` nursery |
| `headless.py` | Change listen addr to include QUIC multiaddr |
| `api/node.py` | Expose `nat_status` and `relay_addr` in `NodeInfoHandler` response |
| `api/peers.py` | Add relay address to peer multiaddr display |
| `main.py` / entrypoint | Add `--relay-addr` CLI arg for deploying a relay node |
| New: `goose_relay_node.py` | Standalone relay deployment script for EC2 |
| `mcp/goose_libp2p_mcp.py` | Add MCP tools: `get_nat_status`, `get_relay_addr`, `force_hole_punch` |

---

*Generated from deep analysis of `goose-universal-connectivity` source code and `py-libp2p` relay/nat/autonat/upnp/dcutr module internals.*
