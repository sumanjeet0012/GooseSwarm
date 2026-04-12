"""
Payment handler for Tornado API server.

POST /api/v1/payments/send  - send ETH payment to a peer
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
