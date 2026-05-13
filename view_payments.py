#!/usr/bin/env python3
"""
View payment records from the Bitswap payment ledger.

Shows all payment authorizations that have been verified and recorded.
"""

import argparse
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

def format_timestamp(ts: float) -> str:
    """Format Unix timestamp to readable string."""
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")

def format_usdc(value: int) -> str:
    """Format USDC micro-units to dollars."""
    return f"${value / 1_000_000:.6f}"

def format_address(addr: str) -> str:
    """Shorten address for display."""
    if len(addr) > 12:
        return f"{addr[:6]}...{addr[-4:]}"
    return addr

def view_payments(db_path: str, limit: int = None, verbose: bool = False):
    """View payment records from the ledger."""
    
    if not Path(db_path).exists():
        print(f"❌ Payment ledger not found: {db_path}")
        print()
        print("The ledger is created when:")
        print("  1. BITSWAP_PAYMENT_ENABLED=true")
        print("  2. A peer starts with payment mode enabled")
        print("  3. The first payment is processed")
        return
    
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # Get schema info
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = cursor.fetchall()
        
        if not tables:
            print("⚠️  Payment ledger is empty (no tables)")
            return
        
        print("=" * 100)
        print("Payment Ledger Records")
        print("=" * 100)
        print(f"Database: {db_path}")
        print()
        
        # Show tables
        print("📊 Tables:")
        for table in tables:
            cursor.execute(f"SELECT COUNT(*) FROM {table[0]}")
            count = cursor.fetchone()[0]
            print(f"  - {table[0]}: {count} records")
        print()
        
        # Query payment_authorizations table
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='payment_authorizations'")
        if not cursor.fetchone():
            print("⚠️  No 'payment_authorizations' table found")
            return
        
        # Get column names
        cursor.execute("PRAGMA table_info(payment_authorizations)")
        columns = [col[1] for col in cursor.fetchall()]
        
        # Query payments
        query = "SELECT * FROM payment_authorizations ORDER BY timestamp DESC"
        if limit:
            query += f" LIMIT {limit}"
        
        cursor.execute(query)
        payments = cursor.fetchall()
        
        if not payments:
            print("📭 No payment records found")
            print()
            print("This means either:")
            print("  1. No payments have been processed yet")
            print("  2. All downloaded files were <4KB (free)")
            print("  3. Payment mode was not enabled during downloads")
            return
        
        print(f"💰 Payment Records ({len(payments)} total):")
        print()
        
        # Create column mapping
        col_map = {col: i for i, col in enumerate(columns)}
        
        for i, payment in enumerate(payments, 1):
            print(f"Payment #{i}")
            print("-" * 100)
            
            # Extract fields
            from_addr = payment[col_map.get('from_address', 0)]
            to_addr = payment[col_map.get('to_address', 1)]
            value = payment[col_map.get('value', 2)]
            nonce = payment[col_map.get('nonce', 3)]
            timestamp = payment[col_map.get('timestamp', 4)]
            
            # Display
            if verbose:
                print(f"  From:      {from_addr}")
                print(f"  To:        {to_addr}")
            else:
                print(f"  From:      {format_address(from_addr)}")
                print(f"  To:        {format_address(to_addr)}")
            
            print(f"  Amount:    {format_usdc(value)} USDC")
            print(f"  Time:      {format_timestamp(timestamp)}")
            
            if verbose:
                print(f"  Nonce:     {nonce.hex() if isinstance(nonce, bytes) else nonce}")
                
                # Show all columns
                print(f"  All fields:")
                for col, idx in col_map.items():
                    val = payment[idx]
                    if isinstance(val, bytes):
                        val = val.hex()
                    print(f"    {col}: {val}")
            
            print()
        
        # Summary
        total_value = sum(p[col_map.get('value', 2)] for p in payments)
        print("=" * 100)
        print(f"📊 Summary: {len(payments)} payment(s), Total: {format_usdc(total_value)} USDC")
        print("=" * 100)
        print()
        
        # Payment mode info
        print("ℹ️  Payment Mode: OPTIMISTIC")
        print("   • Signatures verified locally (no gas fees)")
        print("   • Blocks served immediately after verification")
        print("   • No on-chain transactions submitted")
        print("   • Perfect for testing without spending testnet funds")
        print()
        
        conn.close()
        
    except sqlite3.Error as e:
        print(f"❌ Database error: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"❌ Error: {e}")
        sys.exit(1)

def main():
    parser = argparse.ArgumentParser(description="View Bitswap payment records")
    parser.add_argument(
        "--db",
        default="~/Downloads/payment_ledger.db",
        help="Path to payment ledger database (default: ~/Downloads/payment_ledger.db)"
    )
    parser.add_argument(
        "--limit",
        type=int,
        help="Limit number of records to show"
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Show full details (addresses, nonces, etc.)"
    )
    
    args = parser.parse_args()
    
    # Expand ~ in path
    db_path = str(Path(args.db).expanduser())
    
    view_payments(db_path, args.limit, args.verbose)

if __name__ == "__main__":
    main()
