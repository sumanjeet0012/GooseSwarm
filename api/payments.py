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
from dotenv import load_dotenv

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
        
        try:
            from web3 import Web3
        except ImportError:
            self.send_error_response("web3 package is not installed. Run: pip install web3")
            return
        
        if not Web3.is_address(recipient_address):
            self.send_error_response(f"Peer {peer_id} has an invalid payment address: {recipient_address}")
            return
        
        recipient_address = Web3.to_checksum_address(recipient_address)
        
        # Get private key from environment
        load_dotenv()
        private_key = os.environ.get("AGENT_PRIVATE_KEY")
        if not private_key:
            self.send_error_response("AGENT_PRIVATE_KEY not found in .env file.")
            return
        
        # Connect to Sepolia RPC
        try:
            rpc_url = "https://rpc2.sepolia.org"
            w3 = Web3(Web3.HTTPProvider(rpc_url, request_kwargs={'timeout': 15}))
            if not w3.is_connected():
                self.send_error_response("Failed to connect to Sepolia RPC node.")
                return
            
            account = w3.eth.account.from_key(private_key)
            amount_wei = w3.to_wei(amount_eth, 'ether')
            balance = w3.eth.get_balance(account.address)
            
            if balance < amount_wei:
                self.send_error_response(
                    f"Insufficient funds. Balance: {w3.from_wei(balance, 'ether')} ETH, required: {amount_eth} ETH"
                )
                return
            
            # Build transaction
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
            tx_hash = w3.eth.send_raw_transaction(signed_tx.rawTransaction)
            tx_hash_hex = w3.to_hex(tx_hash)
            
            logger.info(f"Transaction broadcasted: {tx_hash_hex}. Waiting for receipt...")
            receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
            
            if receipt['status'] != 1:
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
            assert ledger._conn is not None
            row = ledger._conn.execute(
                """
                SELECT COUNT(*) as total_payments,
                       COALESCE(SUM(amount), 0) as total_units,
                       COUNT(DISTINCT peer_id) as unique_payers
                FROM payments
                """
            ).fetchone()

            pending_offers = len(engine._pending_offers) if engine else 0

            self.send_success({
                "payment_enabled": True,
                "total_payment_flows": row["total_payments"],
                "total_usdc_units": row["total_units"],
                "total_usdc": row["total_units"] / 1_000_000,
                "unique_paying_peers": row["unique_payers"],
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

