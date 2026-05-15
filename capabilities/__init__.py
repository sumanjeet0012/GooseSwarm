"""
Capability advertisement and discovery via Kademlia DHT provider records.

Nodes announce what they *are* (goose-agent, rag-provider, bitswap-server, etc.)
by calling dht.provide(capability_cid) on startup.  Other nodes discover peers by
calling dht.find_providers(capability_cid).

Usage
-----
    from capabilities import CapabilityKey, CapabilityRegistry

    registry = CapabilityRegistry(dht=my_dht, host=my_host)
    await registry.announce(CapabilityKey.GOOSE_AGENT)
    providers = await registry.find_providers(CapabilityKey.GOOSE_AGENT)
"""

from .registry import CapabilityKey, CapabilityRegistry, capability_to_cid

__all__ = ["CapabilityKey", "CapabilityRegistry", "capability_to_cid"]
