"""
Direct-message endpoints.

POST /api/v1/dm/{peer_id}            - send a DM to a specific peer
GET  /api/v1/dm/{peer_id}            - retrieve DM history with a peer
GET  /api/v1/dm/{peer_id}/unread     - unread DM count for a peer
PUT  /api/v1/dm/{peer_id}/read       - mark DMs with a peer as read

POST /api/v1/dm/payment-key          - set our own payment key (broadcasts to peers)
GET  /api/v1/dm/payment-keys         - get all known peer payment keys
GET  /api/v1/dm/{peer_id}/payment-key - get payment key for a specific peer
POST /api/v1/dm/{peer_id}/advertise-key - push our key to one peer
"""

from .base import BaseHandler


class DMSendHandler(BaseHandler):
    """
    POST /api/v1/dm/{peer_id} — send a direct message to a peer
    GET  /api/v1/dm/{peer_id} — retrieve DM history with a peer
    """

    def get(self, peer_id):
        if not self.require_ready():
            return
        try:
            limit = int(self.get_argument("limit", 100))
            offset = int(self.get_argument("offset", 0))
        except ValueError:
            self.send_error_response("'limit' and 'offset' must be integers.")
            return
        all_msgs = self.service.get_dm_messages(peer_id)
        page = all_msgs[offset: offset + limit]
        self.send_success({
            "peer_id": peer_id,
            "messages": page,
            "total": len(all_msgs),
            "limit": limit,
            "offset": offset,
        })

    def post(self, peer_id):
        if not self.require_ready():
            return
        body = self.get_json_body()
        msg = body.get("message", "").strip()
        if not msg:
            self.send_error_response("'message' field is required.")
            return
        ok = self.service.send_direct_message(peer_id, msg)
        if ok:
            self.send_success({"message": "DM queued for delivery", "peer_id": peer_id}, status=202)
        else:
            self.send_error_response("Failed to queue DM — service not ready.", status=503)


class DMUnreadHandler(BaseHandler):
    """GET /api/v1/dm/{peer_id}/unread"""

    def get(self, peer_id):
        if not self.require_ready():
            return
        count = self.service.get_dm_unread_count(peer_id)
        self.send_success({"peer_id": peer_id, "unread_count": count})


class DMMarkReadHandler(BaseHandler):
    """PUT /api/v1/dm/{peer_id}/read"""

    def put(self, peer_id):
        if not self.require_ready():
            return
        self.service.mark_dm_as_read(peer_id)
        self.send_success({"peer_id": peer_id, "message": "DMs marked as read"})


# ── Payment key handlers ──────────────────────────────────────────────────────

class SetMyPaymentKeyHandler(BaseHandler):
    """POST /api/v1/dm/payment-key — set our own ETH address"""

    def post(self):
        if not self.require_ready():
            return
        body = self.get_json_body()
        eth_address = body.get("payment_key", "").strip()
        if not eth_address:
            self.send_error_response("'payment_key' field is required.")
            return
        self.service.set_my_payment_key(eth_address)
        self.send_success({
            "message": "Payment key set and broadcast to connected peers",
            "payment_key": eth_address,
        })


class AllPaymentKeysHandler(BaseHandler):
    """GET /api/v1/dm/payment-keys — all known peer payment keys"""

    def get(self):
        if not self.require_ready():
            return
        keys = self.service.get_all_payment_keys()
        my_key = self.service.get_my_payment_key()
        self.send_success({
            "my_payment_key": my_key,
            "peer_keys": keys,
            "count": len(keys),
        })


class PeerPaymentKeyHandler(BaseHandler):
    """GET /api/v1/dm/{peer_id}/payment-key"""

    def get(self, peer_id):
        if not self.require_ready():
            return
        key = self.service.get_payment_key(peer_id)
        self.send_success({"peer_id": peer_id, "payment_key": key})


class AdvertiseKeyToPeerHandler(BaseHandler):
    """POST /api/v1/dm/{peer_id}/advertise-key — push our payment key to one peer"""

    def post(self, peer_id):
        if not self.require_ready():
            return
        ok = self.service.advertise_payment_key_to_peer(peer_id)
        if ok:
            self.send_success({"message": "Payment key advertisement queued", "peer_id": peer_id}, status=202)
        else:
            self.send_error_response(
                "Cannot advertise — no payment key set or service not ready.", status=400
            )
