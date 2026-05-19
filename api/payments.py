"""
Payment handler for Tornado API server.

POST /api/v1/payments/send           - send ETH payment to a peer

Bitswap 1.3.0 payment endpoints:
GET  /api/v1/bitswap/payment/status  - payment mode status & wallet info
GET  /api/v1/bitswap/payment/ledger  - payment ledger stats
GET  /api/v1/bitswap/payment/config  - pricing configuration
PUT  /api/v1/bitswap/payment/config  - update pricing configuration
"""

from .base import BaseHandler
import logging
import os
from decimal import Decimal
from dotenv import load_dotenv
from eth_utils import is_address, to_checksum_address
from payments.agentkit_wallet import get_wallet_provider

logger = logging.getLogger(__name__)


class SendPaymentHandler(BaseHandler):
    """POST /api/v1/payments/send — send ETH to a peer via their payment key"""

    def post(self):
        if not self.require_ready():
            return
        
        body = self.get_json_body()
        peer_id = body.get("peer_id", "").strip()
        amount_eth = body.get("amount_eth", 0.01)
        
        if not peer_id:
            self.send_error_response("'peer_id' field is required.")
            return
        
        # Check if peer has payment key
        recipient_address = self.service.get_payment_key(peer_id)
        if not recipient_address:
            self.send_error_response(f"Peer {peer_id} has not broadcasted a payment key.")
            return

        if not is_address(recipient_address):
            self.send_error_response(f"Peer {peer_id} has an invalid payment address: {recipient_address}")
            return
        
        recipient_address = to_checksum_address(recipient_address)
        
        # Get private key from environment
        load_dotenv()
        private_key = os.environ.get("AGENT_PRIVATE_KEY")
        if not private_key:
            self.send_error_response("AGENT_PRIVATE_KEY not found in .env file.")
            return
        
        try:
            rpc_url = os.environ.get("SEPOLIA_RPC_URL", "https://rpc2.sepolia.org")
            wallet = get_wallet_provider(
                private_key=private_key,
                rpc_url=rpc_url,
                chain_id="11155111",  # Ethereum Sepolia
            )

            logger.info(f"Sending {amount_eth} ETH to {recipient_address} via AgentKit")
            tx_hash_hex = wallet.native_transfer(recipient_address, Decimal(str(amount_eth)))

            logger.info(f"Transaction broadcasted: {tx_hash_hex}. Waiting for receipt...")
            receipt = wallet.wait_for_transaction_receipt(tx_hash_hex, timeout=120)

            if receipt.get("status") != 1:
                self.send_error_response(f"Transaction reverted on-chain. Hash: {tx_hash_hex}")
                return

        except Exception as e:
            self.send_error_response(f"Transaction failed: {str(e)}")
            return
        
        # Send DM with receipt
        receipt_url = f"https://sepolia.etherscan.io/tx/{tx_hash_hex}"
        message = f"💳 Payment of {amount_eth} SEP sent via Sepolia Testnet.\n{receipt_url}"
        dm_sent = self.service.send_direct_message(peer_id, message)
        
        self.send_success({
            "message": "Payment sent successfully",
            "peer_id": peer_id,
            "amount_eth": amount_eth,
            "tx_hash": tx_hash_hex,
            "explorer_url": receipt_url,
            "dm_sent": dm_sent,
            "recipient_address": recipient_address,
        })


# ── Bitswap 1.3.0 payment endpoints ─────────────────────────────────────────


class BitswapPaymentStatusHandler(BaseHandler):
    """
    GET /api/v1/bitswap/payment/status

    Returns whether Bitswap 1.3.0 payment mode is active, the server wallet
    address, network, and whether a payment ledger is attached.
    """

    def get(self):
        if not self.require_ready():
            return

        engine = getattr(self.service, "payment_engine", None)
        client = getattr(self.service, "payment_client_1_3", None)
        ledger = getattr(self.service, "payment_ledger", None)

        enabled = engine is not None

        wallet = ""
        network = ""
        usdc_address = ""
        if engine and engine.facilitator:
            wallet = getattr(engine.facilitator, "server_wallet", "")
            network = getattr(engine.facilitator, "network", "")
            usdc_address = getattr(engine.facilitator, "usdc_address", "")

        max_auto_pay_units = 0
        if client:
            max_auto_pay_units = getattr(client, "max_auto_pay_units", 0)

        self.send_success({
            "payment_enabled": enabled,
            "protocol_version": "/ipfs/bitswap/1.3.0" if enabled else None,
            "server_wallet": wallet,
            "network": network,
            "usdc_address": usdc_address,
            "ledger_attached": ledger is not None,
            "max_auto_pay_units": max_auto_pay_units,
            "max_auto_pay_usdc": max_auto_pay_units / 1_000_000,
        })


class BitswapPaymentLedgerHandler(BaseHandler):
    """
    GET /api/v1/bitswap/payment/ledger

    Returns aggregate payment statistics from the ledger:
    total blocks paid, USDC earned, pending offers count.
    """

    def get(self):
        if not self.require_ready():
            return

        ledger = getattr(self.service, "payment_ledger", None)
        engine = getattr(self.service, "payment_engine", None)

        if ledger is None:
            self.send_success({
                "payment_enabled": False,
                "message": "Payment mode is not enabled.",
            })
            return

        # Aggregate stats across all peers
        try:
            summary = ledger.get_summary()
            pending_offers = len(engine._pending_offers) if engine else 0

            self.send_success({
                "payment_enabled": True,
                # Earned (server received payments for serving blocks)
                "earned_flows": summary["earned"]["total_flows"],
                "earned_usdc_units": summary["earned"]["total_units"],
                "earned_usdc": summary["earned"]["total_usdc"],
                "unique_payers": summary["earned"]["unique_payers"],
                # Spent (client sent payments to download blocks)
                "spent_flows": summary["spent"]["total_flows"],
                "spent_usdc_units": summary["spent"]["total_units"],
                "spent_usdc": summary["spent"]["total_usdc"],
                "unique_payees": summary["spent"]["unique_payees"],
                # Legacy field for backward compat
                "total_payment_flows": summary["earned"]["total_flows"],
                "total_usdc_units": summary["earned"]["total_units"],
                "total_usdc": summary["earned"]["total_usdc"],
                "unique_paying_peers": summary["earned"]["unique_payers"],
                "pending_offers": pending_offers,
            })
        except Exception as e:
            self.send_error_response(f"Failed to read ledger: {e}", status=500)


class BitswapPaymentConfigHandler(BaseHandler):
    """
    GET  /api/v1/bitswap/payment/config  — read pricing config
    PUT  /api/v1/bitswap/payment/config  — update pricing config

    Configurable fields (PUT body JSON):
      units_per_kb        int   — price units per KB (default 10)
      free_threshold_kb   int   — blocks <= this KB are free (default 4)
      max_auto_pay_usdc   float — client max auto-pay in USDC (default 0.001)
    """

    def get(self):
        if not self.require_ready():
            return

        engine = getattr(self.service, "payment_engine", None)
        client = getattr(self.service, "payment_client_1_3", None)

        if engine is None:
            self.send_success({
                "payment_enabled": False,
                "message": "Payment mode is not enabled.",
            })
            return

        pricing = engine.pricing
        self.send_success({
            "payment_enabled": True,
            "units_per_kb": getattr(pricing, "units_per_kb", 10),
            "free_threshold_bytes": getattr(pricing, "free_threshold_bytes", 4096),
            "free_threshold_kb": getattr(pricing, "free_threshold_bytes", 4096) // 1024,
            "max_auto_pay_units": getattr(client, "max_auto_pay_units", 0) if client else 0,
            "max_auto_pay_usdc": (
                getattr(client, "max_auto_pay_units", 0) / 1_000_000 if client else 0.0
            ),
        })

    def put(self):
        if not self.require_ready():
            return

        engine = getattr(self.service, "payment_engine", None)
        client = getattr(self.service, "payment_client_1_3", None)

        if engine is None:
            self.send_error_response(
                "Payment mode is not enabled. Set BITSWAP_PAYMENT_ENABLED=true.",
                status=409,
            )
            return

        body = self.get_json_body()
        pricing = engine.pricing
        changed = {}

        if "units_per_kb" in body:
            val = int(body["units_per_kb"])
            if val < 0:
                self.send_error_response("units_per_kb must be >= 0")
                return
            pricing.units_per_kb = val
            changed["units_per_kb"] = val

        if "free_threshold_kb" in body:
            val = int(body["free_threshold_kb"]) * 1024
            if val < 0:
                self.send_error_response("free_threshold_kb must be >= 0")
                return
            pricing.free_threshold_bytes = val
            changed["free_threshold_bytes"] = val

        if "max_auto_pay_usdc" in body and client:
            val = float(body["max_auto_pay_usdc"])
            if val < 0:
                self.send_error_response("max_auto_pay_usdc must be >= 0")
                return
            client.max_auto_pay_units = int(val * 1_000_000)
            changed["max_auto_pay_units"] = client.max_auto_pay_units

        if not changed:
            self.send_error_response(
                "No valid fields provided. "
                "Accepted: units_per_kb, free_threshold_kb, max_auto_pay_usdc"
            )
            return

        logger.info(f"Bitswap payment config updated: {changed}")
        self.send_success({"updated": changed})

