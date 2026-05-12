"""
Block Pricing Engine for Bitswap 1.3.0.

Determines how much to charge for serving a block based on its size,
with per-CID overrides so individual files can be forced free or forced paid
regardless of their size.

Default model:
  - Blocks <= 4096 bytes: free
  - Larger blocks: 10 USDC micro-units per KB (i.e. $0.00001 per KB)

Per-CID overrides (set via set_cid_policy):
  - "free"  → always serve free, no matter the size
  - "paid"  → always require payment, no matter the size
  - None    → use the default size-based rule
"""

import logging

logger = logging.getLogger(__name__)

# USDC uses 6 decimal places, so 1 unit = $0.000001
# Default pricing: 10 units per KB = $0.00001/KB
DEFAULT_UNITS_PER_KB = 10
FREE_THRESHOLD_BYTES = 4096  # blocks <= 4KB are free

# Policy constants
POLICY_FREE = "free"
POLICY_PAID = "paid"


class BlockPricingEngine:
    """
    Computes the price (in USDC micro-units) for serving a block.

    Per-CID policy overrides take precedence over the size-based rule:
      - set_cid_policy(cid, "free")  → always free
      - set_cid_policy(cid, "paid")  → always paid (minimum 1 unit)
      - clear_cid_policy(cid)        → revert to size-based rule
    """

    def __init__(
        self,
        units_per_kb: int = DEFAULT_UNITS_PER_KB,
        free_threshold_bytes: int = FREE_THRESHOLD_BYTES,
    ):
        self.units_per_kb = units_per_kb
        self.free_threshold_bytes = free_threshold_bytes
        # {cid_str: "free" | "paid"}
        self._cid_policies: dict[str, str] = {}

    def set_cid_policy(self, cid: str, policy: str) -> None:
        """
        Set a per-CID payment policy.

        Args:
            cid: The CID string (hex or base58/base32)
            policy: "free" to always serve free, "paid" to always require payment
        """
        if policy not in (POLICY_FREE, POLICY_PAID):
            raise ValueError(f"policy must be '{POLICY_FREE}' or '{POLICY_PAID}', got '{policy}'")
        self._cid_policies[cid] = policy
        logger.info(f"CID policy set: {cid[:20]}... → {policy}")

    def clear_cid_policy(self, cid: str) -> None:
        """Remove a per-CID override and revert to size-based rule."""
        self._cid_policies.pop(cid, None)

    def get_cid_policy(self, cid: str) -> str | None:
        """Return the override policy for a CID, or None if using default rule."""
        return self._cid_policies.get(cid)

    def compute_price(self, cid: str, block_size_bytes: int) -> int:
        """
        Compute the price for a block.

        Per-CID overrides take precedence:
          - "free"  → return 0
          - "paid"  → return max(1, size-based price)
          - None    → use size-based rule

        Args:
            cid: The CID of the block.
            block_size_bytes: Size of the block in bytes.

        Returns:
            Price in USDC micro-units (0 = free).
        """
        policy = self._cid_policies.get(cid)

        if policy == POLICY_FREE:
            logger.debug(f"CID {str(cid)[:20]}... → FREE (override)")
            return 0

        # Size-based price
        size_price = self._size_based_price(block_size_bytes)

        if policy == POLICY_PAID:
            # Force payment even if the file is tiny — charge at least 1 unit
            price = max(1, size_price)
            logger.debug(f"CID {str(cid)[:20]}... → {price} units (forced paid)")
            return price

        # Default: size-based rule
        logger.debug(
            f"Pricing block {str(cid)[:20]}... size={block_size_bytes}B → {size_price} units"
        )
        return size_price

    def _size_based_price(self, block_size_bytes: int) -> int:
        if block_size_bytes <= self.free_threshold_bytes:
            return 0
        kb = block_size_bytes / 1024
        return int(kb * self.units_per_kb)

    def is_free(self, cid: str, block_size_bytes: int) -> bool:
        return self.compute_price(cid, block_size_bytes) == 0
