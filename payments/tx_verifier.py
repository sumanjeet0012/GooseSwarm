"""
On-chain transaction verifier for Bitswap 1.3.0 payments.

Replaces the old EIP-3009 / FacilitatorClient approach.

The new flow is simpler:
  1. Client does a real ETH transfer on-chain using their AGENT_PRIVATE_KEY.
  2. Client sends the tx_hash + CID to the server inside a TxReceipt message.
  3. Server calls eth_getTransactionReceipt(tx_hash) to verify:
       - tx.to   == server_wallet
       - tx.value >= required_amount
       - receipt.status == 1 (not reverted)
  4. Server records (peer_id, cid, tx_hash) in the ledger and serves the block.

No EIP-712 signing, no ECDSA recovery, no facilitator complexity.
"""

import logging
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)

RPC_URLS = {
    "sepolia":      "https://rpc2.sepolia.org",
    "base-sepolia": "https://sepolia.base.org",
    "base-mainnet": "https://mainnet.base.org",
}

CHAIN_IDS = {
    "sepolia":      11155111,
    "base-sepolia": 84532,
    "base-mainnet": 8453,
}


@dataclass
class VerificationResult:
    valid: bool
    tx_hash: str = ""
    from_address: str = ""
    amount_wei: int = 0
    error: str = ""


class TxVerifier:
    """
    Verifies on-chain ETH payments by reading transaction receipts via RPC.

    Args:
        network:        "sepolia" | "base-sepolia" | "base-mainnet"
        server_wallet:  The server's ETH address — payments must be sent here.
        rpc_url:        Optional RPC override; falls back to a public default.
        mode:           "OPTIMISTIC" — accept if tx is in mempool (not yet mined).
                        "STRICT"     — wait for receipt.status == 1 (default).
    """

    def __init__(
        self,
        server_wallet: str,
        network: str = "sepolia",
        rpc_url: Optional[str] = None,
        mode: str = "STRICT",
    ):
        self.server_wallet = server_wallet.lower()
        self.network = network
        self.rpc_url = rpc_url or RPC_URLS.get(network, RPC_URLS["sepolia"])
        self.mode = mode
        self._w3 = None

    def _get_w3(self):
        if self._w3 is None:
            from web3 import Web3
            self._w3 = Web3(Web3.HTTPProvider(self.rpc_url, request_kwargs={"timeout": 20}))
        return self._w3

    async def verify(
        self,
        tx_hash: str,
        required_amount_wei: int = 0,
    ) -> VerificationResult:
        """
        Verify that tx_hash is a valid ETH payment to server_wallet.

        Args:
            tx_hash:              The 0x-prefixed transaction hash.
            required_amount_wei:  Minimum acceptable value in wei (0 = any amount).

        Returns:
            VerificationResult with valid=True/False and details.
        """
        if not tx_hash or not tx_hash.startswith("0x"):
            return VerificationResult(valid=False, error="INVALID_TX_HASH")

        try:
            w3 = self._get_w3()

            # Fetch the transaction itself (available before mining)
            tx = w3.eth.get_transaction(tx_hash)
            if tx is None:
                return VerificationResult(valid=False, error="TX_NOT_FOUND")

            # Verify recipient
            if tx["to"] is None or tx["to"].lower() != self.server_wallet:
                return VerificationResult(
                    valid=False,
                    error=f"WRONG_RECIPIENT:got={tx['to']},expected={self.server_wallet}",
                )

            # Verify amount
            if tx["value"] < required_amount_wei:
                return VerificationResult(
                    valid=False,
                    error=f"INSUFFICIENT_AMOUNT:got={tx['value']},need={required_amount_wei}",
                )

            from_addr = tx["from"]
            amount_wei = tx["value"]

            if self.mode == "OPTIMISTIC":
                # Accept immediately — tx exists and looks correct
                logger.info(
                    f"OPTIMISTIC: accepted tx {tx_hash[:12]}... "
                    f"from={from_addr[:12]}... amount={amount_wei} wei"
                )
                return VerificationResult(
                    valid=True,
                    tx_hash=tx_hash,
                    from_address=from_addr,
                    amount_wei=amount_wei,
                )

            # STRICT: wait for mined receipt
            receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=60)
            if receipt["status"] != 1:
                return VerificationResult(valid=False, error="TX_REVERTED")

            logger.info(
                f"STRICT: confirmed tx {tx_hash[:12]}... "
                f"from={from_addr[:12]}... amount={amount_wei} wei "
                f"block={receipt['blockNumber']}"
            )
            return VerificationResult(
                valid=True,
                tx_hash=tx_hash,
                from_address=from_addr,
                amount_wei=amount_wei,
            )

        except Exception as e:
            logger.error(f"TxVerifier.verify error for {tx_hash}: {e}")
            return VerificationResult(valid=False, error=f"RPC_ERROR:{e}")

    async def verify_receipt(
        self,
        tx_hash: str,
        expected_to: str,
        expected_from: str,
        expected_cid: bytes,
        expected_amount: int,
        min_amount: int = 0,
    ) -> tuple[bool, str]:
        """
        Adapter method used by PaymentGatedDecisionEngine.

        Returns (valid: bool, error: str).
        """
        result = await self.verify(
            tx_hash=tx_hash,
            required_amount_wei=min_amount,
        )
        if not result.valid:
            return False, result.error

        # Optionally check sender matches claimed from_address
        if expected_from and result.from_address:
            if result.from_address.lower() != expected_from.lower():
                return False, f"WRONG_SENDER:got={result.from_address},expected={expected_from}"

        return True, ""
