"""
AgentKit wallet factory for payment modules.

Provides a shared factory function that creates an EthAccountWalletProvider
from a raw private key. This centralizes wallet creation so all payment
modules (facilitator, api/payments, mcp) use the same AgentKit abstraction
instead of raw web3.py calls.

Supported networks / chain IDs:
  base-sepolia  → 84532
  base-mainnet  → 8453
  sepolia       → 11155111  (Ethereum Sepolia, used for direct ETH payments)
"""

import logging
from typing import Optional

logger = logging.getLogger(__name__)

# Mapping of chain_id string → default RPC URL
_CHAIN_RPC_DEFAULTS: dict[str, str] = {
    "84532": "https://sepolia.base.org",       # base-sepolia
    "8453": "https://mainnet.base.org",         # base-mainnet
    "11155111": "https://rpc2.sepolia.org",     # Ethereum Sepolia
}


def get_wallet_provider(
    private_key: str,
    rpc_url: Optional[str] = None,
    chain_id: str = "11155111",
):
    """
    Create and return a configured EthAccountWalletProvider.

    Args:
        private_key: Hex-encoded private key (with or without 0x prefix).
        rpc_url:     Optional RPC endpoint. Falls back to a public default for
                     the given chain_id if omitted.
        chain_id:    Chain ID as a string. Defaults to "11155111" (Ethereum
                     Sepolia) to match the existing direct-payment behaviour.

    Returns:
        EthAccountWalletProvider instance ready for send_transaction(),
        native_transfer(), wait_for_transaction_receipt(), etc.

    Raises:
        ImportError: If coinbase-agentkit or eth-account is not installed.
        ValueError:  If private_key is empty or chain_id is unsupported.
    """
    if not private_key:
        raise ValueError("private_key must not be empty")

    # Normalise key format
    if not private_key.startswith("0x"):
        private_key = "0x" + private_key

    from eth_account import Account
    from coinbase_agentkit import (
        EthAccountWalletProvider,
        EthAccountWalletProviderConfig,
    )

    resolved_rpc = rpc_url or _CHAIN_RPC_DEFAULTS.get(chain_id)
    if not resolved_rpc:
        raise ValueError(
            f"No RPC URL provided and no default known for chain_id={chain_id}. "
            f"Known chain IDs: {list(_CHAIN_RPC_DEFAULTS.keys())}"
        )

    account = Account.from_key(private_key)

    wallet_provider = EthAccountWalletProvider(
        config=EthAccountWalletProviderConfig(
            account=account,
            chain_id=chain_id,
            rpc_url=resolved_rpc,
        )
    )

    logger.debug(
        "EthAccountWalletProvider created: address=%s chain_id=%s rpc=%s",
        account.address[:12] + "...",
        chain_id,
        resolved_rpc,
    )
    return wallet_provider
