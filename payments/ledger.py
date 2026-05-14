"""
Payment Ledger for Bitswap 1.3.0.

Tracks which (peer_id, cid) pairs have been paid for, records nonces to
prevent replay attacks, and stores payment history.
"""

import sqlite3
import time
import logging
from typing import Optional

logger = logging.getLogger(__name__)


class PaymentLedger:
    """
    SQLite-backed ledger that records:
    - Which (peer_id, cid) pairs have been authorized to receive a block
    - Which nonces have been used (replay prevention)
    - Payment history with tx_hash and amounts
    """

    def __init__(self, db_path: str = ":memory:"):
        self.db_path = db_path
        self._conn: Optional[sqlite3.Connection] = None

    async def init(self):
        """Initialize the database schema."""
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._create_tables()
        logger.info(f"PaymentLedger initialized at {self.db_path}")

    def _create_tables(self):
        assert self._conn is not None
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS payments (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                peer_id     TEXT    NOT NULL,
                cid         TEXT    NOT NULL,
                tx_hash     TEXT,
                amount      INTEGER NOT NULL,
                nonce       BLOB    NOT NULL UNIQUE,
                created_at  INTEGER NOT NULL,
                expires_at  INTEGER NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_payments_peer_cid
                ON payments(peer_id, cid);

            CREATE TABLE IF NOT EXISTS used_nonces (
                nonce       BLOB    PRIMARY KEY,
                used_at     INTEGER NOT NULL
            );

            CREATE TABLE IF NOT EXISTS spent_payments (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                peer_id     TEXT    NOT NULL,
                cid         TEXT    NOT NULL,
                amount      INTEGER NOT NULL,
                nonce       TEXT    NOT NULL UNIQUE,
                created_at  INTEGER NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_spent_peer
                ON spent_payments(peer_id);
        """)
        self._conn.commit()

    def is_paid(self, peer_id: str, cid: str, block_size: int = 0) -> bool:
        """
        Return True if this peer has a valid (non-expired) payment for this CID.
        """
        assert self._conn is not None
        now = int(time.time())
        row = self._conn.execute(
            """
            SELECT id FROM payments
            WHERE peer_id = ? AND cid = ? AND expires_at > ?
            LIMIT 1
            """,
            (peer_id, _normalize_cid(cid), now),
        ).fetchone()
        return row is not None

    def is_nonce_used(self, nonce: bytes) -> bool:
        """Return True if this nonce has already been accepted."""
        assert self._conn is not None
        row = self._conn.execute(
            "SELECT 1 FROM used_nonces WHERE nonce = ?", (nonce,)
        ).fetchone()
        return row is not None

    def validate_nonce_unused(self, nonce: bytes):
        """Raise ValueError if the nonce has been used before."""
        if self.is_nonce_used(nonce):
            raise ValueError("NONCE_USED")

    async def record_payment(
        self,
        peer_id: str,
        cid: bytes | str,
        tx_hash: str,
        amount: int,
        nonce: bytes,
        expires_in_seconds: int = 86400 * 7,  # 7 days default
    ):
        """Record a successful payment and mark the nonce as used."""
        assert self._conn is not None
        now = int(time.time())
        cid_str = _normalize_cid(cid)
        expires_at = now + expires_in_seconds

        # Record nonce as used (unique constraint prevents double-spend)
        try:
            self._conn.execute(
                "INSERT INTO used_nonces(nonce, used_at) VALUES(?, ?)",
                (nonce, now),
            )
        except sqlite3.IntegrityError:
            raise ValueError("NONCE_USED")

        # Record payment
        self._conn.execute(
            """
            INSERT INTO payments(peer_id, cid, tx_hash, amount, nonce, created_at, expires_at)
            VALUES(?, ?, ?, ?, ?, ?, ?)
            """,
            (peer_id, cid_str, tx_hash, amount, nonce, now, expires_at),
        )
        self._conn.commit()
        logger.info(
            f"Payment recorded: peer={peer_id[:20]}... cid={cid_str[:20]}... "
            f"amount={amount} tx={tx_hash[:20] if tx_hash else 'optimistic'}..."
        )

    def get_stats(self, peer_id: str) -> dict:
        """Get payment statistics for a specific peer."""
        assert self._conn is not None
        row = self._conn.execute(
            """
            SELECT COUNT(*) as blocks_paid_for,
                   COALESCE(SUM(amount), 0) as total_units
            FROM payments
            WHERE peer_id = ?
            """,
            (peer_id,),
        ).fetchone()
        return {
            "blocks_paid_for": row["blocks_paid_for"],
            "total_usdc": row["total_units"] / 1_000_000,
            "total_units": row["total_units"],
        }

    def record_spent_payment(
        self,
        peer_id: str,
        cid: bytes | str,
        amount: int,
        nonce: bytes,
    ):
        """Record a payment we sent (client-side spending)."""
        assert self._conn is not None
        now = int(time.time())
        cid_str = _normalize_cid(cid)
        nonce_hex = nonce.hex() if isinstance(nonce, bytes) else nonce
        try:
            self._conn.execute(
                """
                INSERT OR IGNORE INTO spent_payments(peer_id, cid, amount, nonce, created_at)
                VALUES(?, ?, ?, ?, ?)
                """,
                (peer_id, cid_str, amount, nonce_hex, now),
            )
            self._conn.commit()
        except Exception as e:
            logger.warning(f"Failed to record spent payment: {e}")

    def get_summary(self) -> dict:
        """Return aggregate earned and spent totals."""
        assert self._conn is not None
        earned_row = self._conn.execute(
            """
            SELECT COUNT(*) as total_flows,
                   COALESCE(SUM(amount), 0) as total_units,
                   COUNT(DISTINCT peer_id) as unique_payers
            FROM payments
            """
        ).fetchone()
        spent_row = self._conn.execute(
            """
            SELECT COUNT(*) as total_flows,
                   COALESCE(SUM(amount), 0) as total_units,
                   COUNT(DISTINCT peer_id) as unique_payees
            FROM spent_payments
            """
        ).fetchone()
        return {
            "earned": {
                "total_flows": earned_row["total_flows"],
                "total_units": earned_row["total_units"],
                "total_usdc": earned_row["total_units"] / 1_000_000,
                "unique_payers": earned_row["unique_payers"],
            },
            "spent": {
                "total_flows": spent_row["total_flows"],
                "total_units": spent_row["total_units"],
                "total_usdc": spent_row["total_units"] / 1_000_000,
                "unique_payees": spent_row["unique_payees"],
            },
        }

    def close(self):
        if self._conn:
            self._conn.close()
            self._conn = None


def _normalize_cid(cid: bytes | str) -> str:
    """Normalize CID to a consistent string form for storage."""
    if isinstance(cid, bytes):
        return cid.hex()
    return cid
