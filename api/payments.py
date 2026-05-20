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
from eth_account import Account
from web3 import Web3

# trio-asyncio replaces the asyncio event loop, so ThreadPoolExecutor is rejected
# by loop.run_in_executor (it asserts isinstance(executor, TrioExecutor)).
# Use TrioExecutor — it has the same interface but runs threads under trio's limiter.
from trio_asyncio import TrioExecutor

logger = logging.getLogger(__name__)

# Thread pool for blocking wallet I/O (sign + broadcast + wait for receipt)
_executor = TrioExecutor(max_workers=4)

# Fallback RPC list — tried in order if the primary fails
_SEPOLIA_RPC_FALLBACKS = [
    "https://sepolia.drpc.org",
    "https://ethereum-sepolia-rpc.publicnode.com",
    "https://1rpc.io/sepolia",
]


def _make_web3(rpc_url: str) -> Web3:
    """Create a Web3 instance with a 30-second timeout."""
    return Web3(Web3.HTTPProvider(rpc_url, request_kwargs={"timeout": 30}))


def _do_transfer(private_key: str, rpc_url: str, recipient: str, amount_eth: float) -> str:
    """
    Blocking helper — runs in a thread pool so Tornado's event loop is never blocked.

    Uses raw web3.py sign_transaction + send_raw_transaction instead of agentkit's
    native_transfer, which internally calls eth_sendTransaction (an unlocked-account
    RPC method that public nodes reject with 400 Bad Request).

    Steps:
      1. Derive sender address from private key
      2. Connect to RPC and fetch chain state (chain_id, nonce, gas price)
      3. Build + sign an EIP-1559 transaction
      4. Broadcast via eth_sendRawTransaction
      5. Wait for on-chain confirmation (up to 120s)
      6. Return confirmed tx hash
    """
    if not private_key.startswith("0x"):
        private_key = "0x" + private_key

    account = Account.from_key(private_key)
    sender = account.address
    logger.info("[payment] Step 1/4 — sender wallet: %s", sender)

    # Try primary RPC, fall back to alternatives on connection errors
    rpcs_to_try = [rpc_url] + [r for r in _SEPOLIA_RPC_FALLBACKS if r != rpc_url]
    w3 = None
    for rpc in rpcs_to_try:
        try:
            candidate = _make_web3(rpc)
            if candidate.is_connected():
                w3 = candidate
                logger.info("[payment] Step 2/4 — connected to RPC: %s", rpc)
                break
            logger.warning("[payment] RPC not connected: %s — trying next", rpc)
        except Exception as e:
            logger.warning("[payment] RPC error %s: %s — trying next", rpc, e)

    if w3 is None:
        raise RuntimeError("All Sepolia RPC endpoints failed. Check network connectivity.")

    chain_id = w3.eth.chain_id
    nonce = w3.eth.get_transaction_count(sender)
    value_wei = w3.to_wei(Decimal(str(amount_eth)), "ether")

    # EIP-1559 fee estimation
    latest = w3.eth.get_block("latest")
    base_fee = latest.get("baseFeePerGas", w3.to_wei(10, "gwei"))
    max_priority_fee = w3.to_wei(2, "gwei")
    max_fee = base_fee * 2 + max_priority_fee

    tx = {
        "from": sender,
        "to": recipient,
        "value": value_wei,
        "nonce": nonce,
        "gas": 21000,
        "maxFeePerGas": max_fee,
        "maxPriorityFeePerGas": max_priority_fee,
        "chainId": chain_id,
        "type": 2,
    }
    logger.info(
        "[payment] Step 3/4 — signing tx: %s ETH → %s  nonce=%s gas=%s maxFee=%s",
        amount_eth, recipient, nonce, tx["gas"], max_fee,
    )

    signed = account.sign_transaction(tx)
    tx_hash_hex = w3.eth.send_raw_transaction(signed.raw_transaction).hex()
    logger.info("[payment] Step 4/4 — broadcast OK, waiting for receipt: %s", tx_hash_hex)

    receipt = w3.eth.wait_for_transaction_receipt(tx_hash_hex, timeout=120, poll_latency=2)
    if receipt.get("status") != 1:
        raise RuntimeError(f"Transaction reverted on-chain. Hash: {tx_hash_hex}")

    logger.info("[payment] ✅ Confirmed in block %s — tx: %s", receipt["blockNumber"], tx_hash_hex)
    return tx_hash_hex


class SendPaymentHandler(BaseHandler):
    """
    POST /api/v1/payments/send

    Body JSON:
      { "peer_id": "<libp2p peer id>", "amount_eth": 0.01 }

    Flow:
      1. Validate peer_id and amount
      2. Look up recipient Ethereum address from peer's advertised payment key
      3. Load AGENT_PRIVATE_KEY from .env
      4. Sign + broadcast + confirm the ETH transfer in a background thread
      5. Send a DM to the peer with the Etherscan receipt link
    """

    async def post(self):
        if not self.require_ready():
            return

        body = self.get_json_body()
        peer_id = body.get("peer_id", "").strip()
        amount_eth = float(body.get("amount_eth", 0.01))

        logger.info("[payment] Incoming request — peer_id=%s amount_eth=%s", peer_id, amount_eth)

        # ── 1. Validate inputs ────────────────────────────────────────────────
        if not peer_id:
            logger.warning("[payment] Rejected: missing peer_id")
            self.send_error_response("'peer_id' field is required.")
            return

        if amount_eth <= 0:
            logger.warning("[payment] Rejected: invalid amount %s", amount_eth)
            self.send_error_response("'amount_eth' must be greater than 0.")
            return

        # ── 2. Resolve recipient address from peer's advertised payment key ───
        logger.info("[payment] Looking up payment key for peer %s", peer_id)
        recipient_address = self.service.get_payment_key(peer_id)
        if not recipient_address:
            logger.warning("[payment] No payment key found for peer %s", peer_id)
            self.send_error_response(
                f"Peer {peer_id} has not advertised a payment key. "
                "Ask them to set one via Settings → Payment Key."
            )
            return

        if not is_address(recipient_address):
            logger.warning("[payment] Invalid Ethereum address for peer %s: %s", peer_id, recipient_address)
            self.send_error_response(
                f"Peer {peer_id} has an invalid payment address: {recipient_address}"
            )
            return

        recipient_address = to_checksum_address(recipient_address)
        logger.info("[payment] Recipient address resolved: %s", recipient_address)

        # ── 3. Load private key ───────────────────────────────────────────────
        load_dotenv()
        private_key = os.environ.get("AGENT_PRIVATE_KEY", "").strip()
        if not private_key:
            logger.error("[payment] AGENT_PRIVATE_KEY not set in environment / .env")
            self.send_error_response(
                "AGENT_PRIVATE_KEY is not configured. Add it to your .env file."
            )
            return

        rpc_url = os.environ.get("SEPOLIA_RPC_URL", "https://sepolia.drpc.org")
        logger.info("[payment] Using RPC: %s", rpc_url)

        # ── 4. Sign + broadcast + wait for receipt (in thread pool) ──────────
        import asyncio
        loop = asyncio.get_event_loop()
        try:
            tx_hash = await loop.run_in_executor(
                _executor,
                _do_transfer,
                private_key,
                rpc_url,
                recipient_address,
                amount_eth,
            )
        except Exception as exc:
            logger.exception("[payment] Transfer failed: %s", exc)
            self.send_error_response(f"Transaction failed: {exc}")
            return

        # ── 5. Notify peer via DM ─────────────────────────────────────────────
        explorer_url = f"https://sepolia.etherscan.io/tx/{tx_hash}"
        dm_text = (
            f"💳 Payment of {amount_eth} SEP sent on Sepolia Testnet.\n"
            f"Tx: {explorer_url}"
        )
        logger.info("[payment] Sending DM receipt to peer %s", peer_id)
        dm_sent = self.service.send_direct_message(peer_id, dm_text, source='mcp')
        logger.info("[payment] DM sent: %s", dm_sent)

        self.send_success({
            "message": "Payment sent and confirmed on-chain",
            "peer_id": peer_id,
            "amount_eth": amount_eth,
            "tx_hash": tx_hash,
            "explorer_url": explorer_url,
            "dm_sent": dm_sent,
            "from_address": None,   # populated below if needed
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
        if engine:
            wallet = getattr(engine, "server_wallet", "")
            network = getattr(engine, "network", "")
            # USDC address is not stored in the engine, leave empty for now
            usdc_address = ""

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

