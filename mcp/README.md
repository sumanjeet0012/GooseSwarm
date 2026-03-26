# goose-mcp-libp2p 🦆🌐

> **MVP A** of the Goose Grant Strategy — gives Goose AI agents a real libp2p peer-to-peer networking layer via the Model Context Protocol (MCP).

## What it does

This MCP server wraps the `HeadlessService` from [py-peer](../README.md) and exposes nine tools to Goose:

| Tool | Description |
|---|---|
| `start_peer(port, nick)` | Start a libp2p node, returns peer ID + multiaddr |
| `stop_peer()` | Gracefully stop the running node |
| `get_peer_info()` | Return peer ID + multiaddr |
| `connect_peer(multiaddr)` | Connect to another libp2p peer |
| `publish_message(topic, message)` | Publish via GossipSub |
| `get_messages(topic)` | Retrieve received messages |
| `list_peers()` | List connected peers |
| `subscribe_topic(topic)` | Subscribe to a new GossipSub topic |
| `get_node_status()` | Full health snapshot |

## Architecture

```
┌──────────────────────────────────────┐
│           Goose Agent (LLM)          │
└──────────────┬───────────────────────┘
               │ MCP stdio protocol
               ▼
┌──────────────────────────────────────┐
│   goose_libp2p_mcp.py (FastMCP)      │
│   tools: start_peer, publish, …      │
└──────────────┬───────────────────────┘
               │ thread-safe janus queues
               ▼
┌──────────────────────────────────────┐
│  HeadlessService (py-peer/headless.py)│
│  GossipSub · DHT · Bitswap · TCP     │
└──────────────┬───────────────────────┘
               │ libp2p network
               ▼
┌──────────────────────────────────────┐
│  P2P Network (other Goose agents,    │
│  IPFS nodes, Universal Connectivity) │
└──────────────────────────────────────┘
```

## Quick start

### Prerequisites

- Python 3.12 via pyenv (`uctest1` venv)
- Goose CLI installed (`goose`)

### 1 — Install dependencies

```bash
cd /Users/sumanjeet/code/goose-universal-connectivity
pyenv shell uctest1
pip install "mcp[cli]>=1.6.0"
```

### 2 — Smoke test (no Goose needed)

```bash
pyenv shell uctest1
python mcp/test_mcp.py
```

### 3 — Configure Goose

The Goose profile is pre-written at `mcp/goose_profile.yaml`. Register it:

```bash
# Option A — goose configure (interactive)
goose configure

# Option B — copy profile directly
mkdir -p ~/.config/goose/profiles
cp mcp/goose_profile.yaml ~/.config/goose/profiles/libp2p.yaml
```

### 4 — Run the demo

**Terminal 1 — Agent A:**
```bash
pyenv shell uctest1
goose session --profile libp2p
```
Then tell Goose:
```
Start a libp2p peer on port 9000 with nick "AgentA".
Subscribe to topic /goose/tasks.
Publish a message: "I need help writing a Python web scraper"
```

**Terminal 2 — Agent B:**
```bash
pyenv shell uctest1
goose session --profile libp2p
```
Then tell Goose:
```
Start a libp2p peer on port 9001 with nick "AgentB".
Connect to the multiaddr from AgentA.
Subscribe to /goose/tasks and check for messages.
```

## File layout

```
mcp/
├── goose_libp2p_mcp.py   ← MCP server (main file)
├── goose_profile.yaml    ← Goose profile / extension config
├── test_mcp.py           ← Smoke test (no Goose needed)
├── pyproject.toml        ← Package metadata
└── README.md             ← This file
```
