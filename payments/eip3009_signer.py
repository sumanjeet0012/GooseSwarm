"""
EIP-3009 Signer for Bitswap 1.3.0 payment authorizations.

Signs USDC transferWithAuthorization messages using EIP-712 typed data.
This is used by the CLIENT side when paying for blocks.

Uses AgentKit's EthAccountWalletProvider for wallet management.
"""

import logging
from typing import Tuple, TYPE_CHECKING

if TYPE_CHECKING:
    from coinbase_agentkit import EthAccountWalletProvider

logger = logging.getLogger(__name__)

# USDC contract on Base Sepolia
USDC_BASE_SEPOLIA = "0x036CbD53842c5426634e7929541eC2318f3dCF7e"
USDC_BASE_MAINNET = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"

# Chain IDs
CHAIN_IDS = {
    "base-sepolia": 84532,
    "base-mainnet": 8453,
}

# EIP-712 domain type hash for USDC transferWithAuthorization
TRANSFER_WITH_AUTHORIZATION_TYPEHASH = bytes.fromhex(
    "7c7c6cdb67a18743f49ec6fa9b35f50d52ed05cbed4cc592e13b44501c1a2267"
)


class EIP3009Signer:
    """
    Signs EIP-3009 transferWithAuthorization typed data using AgentKit.

    Uses AgentKit's EthAccountWalletProvider for consistent wallet abstraction
    across the payment system.
    """

    def __init__(self, private_key: str, network: str = "base-sepolia"):
        from payments.agentkit_wallet import get_wallet_provider

        self.network = network
        self.chain_id = CHAIN_IDS.get(network, 84532)
        self.usdc_address = (
            USDC_BASE_SEPOLIA if "sepolia" in network else USDC_BASE_MAINNET
        )

        # Create AgentKit wallet provider
        self.wallet: "EthAccountWalletProvider" = get_wallet_provider(
            private_key=private_key,
            chain_id=str(self.chain_id),
        )
        
        # Access the underlying eth_account.Account for signing
        self._account = self.wallet.config.account
        self.address: str = self._account.address

    def sign_transfer_authorization(
        self,
        to: str,
        value: int,
        nonce: bytes,
        valid_before: int,
        valid_after: int = 0,
    ) -> Tuple[int, bytes, bytes]:
        """
        Sign a USDC transferWithAuthorization EIP-712 message using AgentKit wallet.

        Args:
            to: Recipient address (server wallet)
            value: Amount in USDC micro-units
            nonce: 32-byte unique nonce
            valid_before: Unix timestamp for expiry
            valid_after: Unix timestamp for activation (usually 0)

        Returns:
            Tuple of (v, r, s) where v is int, r and s are 32-byte values.
        """
        # EIP-712 domain
        domain_data = {
            "name": "USD Coin",
            "version": "2",
            "chainId": self.chain_id,
            "verifyingContract": self.usdc_address,
        }

        # EIP-3009 TransferWithAuthorization type
        message_types = {
            "TransferWithAuthorization": [
                {"name": "from", "type": "address"},
                {"name": "to", "type": "address"},
                {"name": "value", "type": "uint256"},
                {"name": "validAfter", "type": "uint256"},
                {"name": "validBefore", "type": "uint256"},
                {"name": "nonce", "type": "bytes32"},
            ]
        }

        # Ensure nonce is 32 bytes
        nonce_bytes32 = nonce[:32].ljust(32, b'\x00') if len(nonce) < 32 else nonce[:32]

        message_data = {
            "from": self.address,
            "to": to,
            "value": value,
            "validAfter": valid_after,
            "validBefore": valid_before,
            "nonce": nonce_bytes32,
        }

        # Sign using the eth_account.Account from AgentKit wallet
        # The account is accessed via wallet.config.account
        signed = self._account.sign_typed_data(
            domain_data=domain_data,
            message_types=message_types,
            message_data=message_data,
        )

        v = signed.v
        r = signed.r.to_bytes(32, "big")
        s = signed.s.to_bytes(32, "big")

        logger.info(
            f"Signed EIP-3009 auth via AgentKit: from={self.address[:10]}... "
            f"to={to[:10]}... value={value} nonce={nonce_bytes32.hex()[:10]}... "
            f"network={self.network}"
        )

        return v, r, s
