"""
Capability advertisement and discovery endpoints.

GET    /api/v1/capabilities                       - List this node's announced capabilities
POST   /api/v1/capabilities                       - Announce a new capability at runtime
POST   /api/v1/capabilities/reannounce            - Re-announce all active capabilities to DHT
GET    /api/v1/capabilities/well-known            - Return all well-known capability key constants
GET    /api/v1/capabilities/providers/{cap}       - Find DHT peers that offer a capability
DELETE /api/v1/capabilities/{capability}          - Revoke a capability (stop re-announcing)

All handlers extend BaseHandler and access ``self.service.capability_registry``.
"""

import json
import logging
import urllib.parse

from .base import BaseHandler
from capabilities import CapabilityKey

logger = logging.getLogger("api.capabilities")


def _get_registry(service):
    """Helper: return the CapabilityRegistry or None."""
    return getattr(service, "capability_registry", None)


class CapabilityListHandler(BaseHandler):
    """
    GET  /api/v1/capabilities  — List this node's announced capabilities.
    POST /api/v1/capabilities  — Announce a new capability at runtime.

    POST body (JSON): ``{"capability": "goose-agent/v1.0"}``
    """

    def get(self):
        if not self.require_ready():
            return
        registry = _get_registry(self.service)
        if registry is None:
            self.send_error_response("Capability registry not available", status=503)
            return
        self.send_success({
            "announced": registry.get_announced(),
            "count": len(registry.get_announced()),
        })

    def post(self):
        if not self.require_ready():
            return
        registry = _get_registry(self.service)
        if registry is None:
            self.send_error_response("Capability registry not available", status=503)
            return

        try:
            body = json.loads(self.request.body)
        except (json.JSONDecodeError, ValueError):
            self.send_error_response("Invalid JSON body", status=400)
            return

        capability = body.get("capability", "").strip()
        if not capability:
            self.send_error_response(
                "Missing required field: 'capability'", status=400
            )
            return

        try:
            self.service.schedule_capability_announce(capability)
            self.send_success({
                "announced": capability,
                "message": f"Capability '{capability}' queued for DHT announcement",
            })
        except Exception as exc:
            logger.error("Failed to schedule capability announce: %s", exc)
            self.send_error_response(str(exc), status=500)


class CapabilityRevokeHandler(BaseHandler):
    """
    DELETE /api/v1/capabilities/{capability}

    Revokes a capability (stops re-announcing; DHT record expires naturally).
    URL-encoded capability key is expected in the path.
    """

    def delete(self, capability_encoded: str):
        if not self.require_ready():
            return
        registry = _get_registry(self.service)
        if registry is None:
            self.send_error_response("Capability registry not available", status=503)
            return

        capability = urllib.parse.unquote(capability_encoded).strip()
        if not capability:
            self.send_error_response("Invalid capability key in path", status=400)
            return

        try:
            self.service.schedule_capability_revoke(capability)
            self.send_success({
                "revoked": capability,
                "message": (
                    f"Capability '{capability}' revoked. "
                    "Existing DHT provider record will expire naturally."
                ),
            })
        except Exception as exc:
            logger.error("Failed to schedule capability revoke: %s", exc)
            self.send_error_response(str(exc), status=500)


class ReannounceHandler(BaseHandler):
    """
    POST /api/v1/capabilities/reannounce

    Re-announces all currently active capabilities to the DHT.
    Useful after new peers connect so provider records propagate.
    """

    def post(self):
        if not self.require_ready():
            return
        registry = _get_registry(self.service)
        if registry is None:
            self.send_error_response("Capability registry not available", status=503)
            return
        announced = registry.get_announced()
        if not announced:
            self.send_success({"message": "No capabilities to reannounce", "reannounced": []})
            return
        try:
            self.service.schedule_reannounce_all()
            self.send_success({
                "message": f"Reannounce queued for {len(announced)} capability/ies",
                "reannounced": announced,
            })
        except Exception as exc:
            logger.error("Failed to schedule reannounce: %s", exc)
            self.send_error_response(str(exc), status=500)


class WellKnownCapabilitiesHandler(BaseHandler):
    """
    GET /api/v1/capabilities/well-known

    Returns all well-known capability key constants defined in CapabilityKey.
    """

    def get(self):
        self.send_success({
            "well_known": CapabilityKey.ALL,
            "description": {
                CapabilityKey.CHAT_PEER:      "Basic chat peer (default for all nodes)",
                CapabilityKey.GOOSE_AGENT:    "Goose AI agent node",
                CapabilityKey.RAG_PROVIDER:   "Retrieval-Augmented Generation provider",
                CapabilityKey.BITSWAP_SERVER: "Bitswap file-sharing server (with optional payments)",
                CapabilityKey.COMPUTE_NODE:   "General compute / task execution node",
            },
        })


class CapabilityProvidersHandler(BaseHandler):
    """
    GET /api/v1/capabilities/providers/{capability}

    Queries the Kademlia DHT for peers that advertise the given capability.
    Returns a list of peer records (peer_id + multiaddrs).

    Query params:
        count (int, default 20) — maximum number of providers to return.
    """

    def get(self, capability_encoded: str):
        if not self.require_ready():
            return
        registry = _get_registry(self.service)
        if registry is None:
            self.send_error_response("Capability registry not available", status=503)
            return

        capability = urllib.parse.unquote(capability_encoded).strip()
        if not capability:
            self.send_error_response("Invalid capability key in path", status=400)
            return

        try:
            count = int(self.get_argument("count", "20"))
        except ValueError:
            count = 20

        try:
            # Blocking call — submits to trio via queue, waits up to 30s
            providers_raw = self.service.find_capability_providers(capability, count)
            providers = []
            for p in providers_raw:
                peer_id_str = str(getattr(p, "peer_id", p))
                addrs = [str(a) for a in getattr(p, "addrs", [])]
                providers.append({"peer_id": peer_id_str, "addrs": addrs})

            self.send_success({
                "capability": capability,
                "providers": providers,
                "count": len(providers),
            })
        except Exception as exc:
            logger.error(
                "Error querying providers for capability '%s': %s", capability, exc
            )
            self.send_error_response(
                f"DHT query failed: {exc}", status=500
            )
