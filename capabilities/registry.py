"""
CapabilityRegistry — modular capability advertisement and discovery.

Design
------
Each capability is mapped to a deterministic CIDv1 derived from the SHA-256 of
the capability key string.  The DHT `provide` / `find_providers` API is used so
that any node can:

  1. Announce itself as a provider of a capability.
  2. Discover all peers that offer a given capability.

Capability keys are plain strings.  A set of well-known constants is provided in
``CapabilityKey`` so callers don't have to hard-code strings.

DHT provider records expire after ~24 h in libp2p implementations, so the
registry re-announces all active capabilities every ``REANNOUNCE_INTERVAL``
seconds.

Example
-------
    registry = CapabilityRegistry(dht, host)
    await registry.announce(CapabilityKey.GOOSE_AGENT)
    peers = await registry.find_providers(CapabilityKey.GOOSE_AGENT)
    for peer in peers:
        print(peer)  # PeerInfo with id + addrs
"""

from __future__ import annotations

import hashlib
import logging
from typing import List, Set

import trio

logger = logging.getLogger("capabilities.registry")

# How often (seconds) to re-announce all active capabilities so DHT records
# don't expire.  Kademlia records typically expire after 24 h; re-announcing
# every 10 min is conservative and cheap.
REANNOUNCE_INTERVAL = 600  # 10 minutes


class CapabilityKey:
    """
    Well-known capability key constants.

    These strings are the canonical names used when computing CIDs and when
    advertising / querying the DHT.  Callers may also use arbitrary freeform
    strings for custom capabilities.
    """

    CHAT_PEER      = "chat-peer/v1.0"
    GOOSE_AGENT    = "goose-agent/v1.0"
    RAG_PROVIDER   = "rag-provider/v1.0"
    BITSWAP_SERVER = "bitswap-server/v1.0"
    COMPUTE_NODE   = "compute-node/v1.0"

    # Convenience list of all well-known keys
    ALL: List[str] = [
        CHAT_PEER,
        GOOSE_AGENT,
        RAG_PROVIDER,
        BITSWAP_SERVER,
        COMPUTE_NODE,
    ]


def capability_to_cid(capability_key: str) -> str:
    """
    Derive a deterministic DHT key from a capability key string.

    The key is the lowercase hex encoding of the SHA-256 digest of the
    capability string, prefixed with ``/capability/`` to namespace it
    away from other DHT records.

    The KadDHT ``provide`` / ``find_providers`` API expects a plain ``str``
    key, so we return a string rather than raw bytes.

    Returns
    -------
    str
        A deterministic, collision-resistant DHT key string.
    """
    digest = hashlib.sha256(capability_key.encode("utf-8")).hexdigest()
    return f"/capability/{digest}"


class CapabilityRegistry:
    """
    Manages capability advertisement and discovery for a libp2p node.

    Parameters
    ----------
    dht : KadDHT
        The running Kademlia DHT instance (must support ``provide`` and
        ``find_providers`` coroutines).
    host : IHost
        The libp2p host (used for logging the local peer ID).
    """

    def __init__(self, dht, host) -> None:
        self._dht = dht
        self._host = host
        self._announced: Set[str] = set()

    # ── Public API ────────────────────────────────────────────────────────────

    async def announce(self, capability_key: str) -> None:
        """
        Advertise this node as a provider of *capability_key* via the DHT.

        The capability key is added to the active set so it will be
        re-announced automatically by ``re_announce_all``.

        Parameters
        ----------
        capability_key : str
            A capability string, e.g. ``CapabilityKey.GOOSE_AGENT``.
        """
        self._announced.add(capability_key)
        await self._provide(capability_key)

    async def revoke(self, capability_key: str) -> None:
        """
        Stop advertising *capability_key*.

        The DHT has no explicit un-provide mechanism; this merely removes the
        key from the active set so it won't be re-announced.  The existing
        provider record will expire naturally (typically within 24 h).

        Parameters
        ----------
        capability_key : str
            The capability key to stop advertising.
        """
        self._announced.discard(capability_key)
        logger.info(
            "🔕 Capability revoked (will expire from DHT): %s", capability_key
        )

    async def find_providers(
        self, capability_key: str, count: int = 20
    ) -> List[object]:
        """
        Query the DHT for peers that provide *capability_key*.

        Parameters
        ----------
        capability_key : str
            The capability to search for.
        count : int
            Maximum number of providers to return (default 20).

        Returns
        -------
        list
            A list of ``PeerInfo``-like objects (each has ``.peer_id`` and
            ``.addrs``).  Returns an empty list on error.
        """
        cid_bytes = capability_to_cid(capability_key)
        logger.info(
            "🔍 Querying DHT for providers of capability: %s", capability_key
        )
        try:
            providers = await self._dht.find_providers(cid_bytes, count)
            logger.info(
                "✅ Found %d provider(s) for capability: %s",
                len(providers),
                capability_key,
            )
            return providers
        except Exception as exc:
            logger.warning(
                "⚠️  find_providers failed for %s: %s", capability_key, exc
            )
            return []

    def get_announced(self) -> List[str]:
        """Return a sorted list of currently announced capability keys."""
        return sorted(self._announced)

    async def re_announce_all(self) -> None:
        """Re-announce every active capability to refresh DHT provider records."""
        if not self._announced:
            return
        logger.debug(
            "🔄 Re-announcing %d capability/ies…", len(self._announced)
        )
        for key in list(self._announced):
            await self._provide(key)

    # ── Background refresh loop ───────────────────────────────────────────────

    async def run_refresh_loop(self) -> None:
        """
        Long-running trio task: re-announces all active capabilities every
        ``REANNOUNCE_INTERVAL`` seconds.

        Start this with ``nursery.start_soon(registry.run_refresh_loop)``.
        """
        while True:
            await trio.sleep(REANNOUNCE_INTERVAL)
            try:
                await self.re_announce_all()
            except Exception as exc:
                logger.warning("⚠️  Capability re-announce error: %s", exc)

    # ── Internal helpers ──────────────────────────────────────────────────────

    async def _provide(self, capability_key: str) -> None:
        """Call dht.provide() for the given capability key."""
        cid_bytes = capability_to_cid(capability_key)
        peer_id = self._host.get_id() if self._host else "unknown"
        try:
            await self._dht.provide(cid_bytes)
            logger.info(
                "📢 Announced capability '%s' (peer=%s)", capability_key, peer_id
            )
        except Exception as exc:
            logger.warning(
                "⚠️  DHT provide failed for capability '%s': %s",
                capability_key,
                exc,
            )
