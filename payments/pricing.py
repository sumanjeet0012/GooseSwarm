"""
Block Pricing Engine for Bitswap 1.3.0.

Determines how much to charge for serving a block based on its size,
with per-CID overrides so individual files can be forced free or forced paid.

Pricing model:
  - Paid blocks: 10 USDC micro-units per KB (i.e. $0.00001 per KB)
  - Files must be explicitly marked as "free" or "paid" by the user

Per-CID policy (set via set_cid_policy):
  - "free"  → always serve free, no matter the size
  - "paid"  → always require payment based on size
"""

import logging

logger = logging.getLogger(__name__)

# USDC uses 6 decimal places, so 1 unit = $0.000001
# Default pricing: 10 units per KB = $0.00001/KB
DEFAULT_UNITS_PER_KB = 10

# Policy constants
POLICY_FREE = "free"
POLICY_PAID = "paid"


class BlockPricingEngine:
    """
    Computes the price (in USDC micro-units) for serving a block.

    Per-CID policy determines pricing:
      - set_cid_policy(cid, "free")  → always free (0 units)
      - set_cid_policy(cid, "paid")  → charged based on size (minimum 1 unit)
      - clear_cid_policy(cid)        → remove policy (will error if accessed)
    """

    def __init__(
        self,
        units_per_kb: int = DEFAULT_UNITS_PER_KB,
    ):
        self.units_per_kb = units_per_kb
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

        Requires explicit policy:
          - "free"  → return 0
          - "paid"  → return max(1, size-based price)
          - None    → default to FREE (file should have been marked explicitly)

        Args:
            cid: The CID of the block.
            block_size_bytes: Size of the block in bytes.

        Returns:
            Price in USDC micro-units (0 = free).
        """
        policy = self._cid_policies.get(cid)

        if policy == POLICY_FREE:
            logger.debug(f"CID {str(cid)[:20]}... → FREE (user set)")
            return 0

        if policy == POLICY_PAID:
            # Charge based on size, minimum 1 unit
            size_price = self._size_based_price(block_size_bytes)
            price = max(1, size_price)
            logger.debug(f"CID {str(cid)[:20]}... → {price} units (user set paid)")
            return price

        # No policy set - default to FREE (should have been set during file share)
        logger.warning(
            f"CID {str(cid)[:20]}... has no payment policy set. "
            f"Defaulting to FREE. File should be explicitly marked when shared."
        )
        # Set it now so we don't warn again
        self._cid_policies[cid] = POLICY_FREE
        return 0

    def _size_based_price(self, block_size_bytes: int) -> int:
        """Calculate price based on size: units_per_kb * KB."""
        kb = block_size_bytes / 1024
        return int(kb * self.units_per_kb)

    def is_free(self, cid: str, block_size_bytes: int) -> bool:
        return self.compute_price(cid, block_size_bytes) == 0
