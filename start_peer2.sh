#!/bin/bash
# Start Peer 2 with its own payment configuration

# Color output
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${BLUE}═══════════════════════════════════════════════════════════${NC}"
echo -e "${GREEN}Starting Peer 2${NC}"
echo -e "${BLUE}═══════════════════════════════════════════════════════════${NC}"
echo ""
echo "API Port:     8766"
echo "Libp2p Port:  4002"
echo "Seed:         2"
echo "Config:       .env.peer2"
echo ""

# Load environment from .env.peer2
if [ -f .env.peer2 ]; then
    # Export all variables from .env.peer2
    set -a
    source .env.peer2
    set +a
    
    echo -e "${GREEN}✓${NC} Loaded .env.peer2"
    
    # Check if wallet is configured
    if [ "$AGENT_PRIVATE_KEY" == "YOUR_PEER2_PRIVATE_KEY_HERE" ]; then
        echo -e "${YELLOW}⚠️  Warning: Using placeholder private key${NC}"
        echo -e "${YELLOW}   Run: python generate_wallet.py${NC}"
        echo -e "${YELLOW}   Then update .env.peer2 with the new credentials${NC}"
        echo ""
    elif [ ! -z "$PAYMENT_ADDRESS" ]; then
        echo -e "${GREEN}✓${NC} Payment wallet: $PAYMENT_ADDRESS"
    fi
    
    # Verify payment settings
    if [ "$BITSWAP_PAYMENT_ENABLED" == "true" ]; then
        echo -e "${GREEN}✓${NC} Payment mode: ENABLED"
    else
        echo -e "${YELLOW}⚠️${NC}  Payment mode: DISABLED"
    fi
else
    echo "❌ Error: .env.peer2 not found"
    exit 1
fi

echo ""
echo -e "${BLUE}═══════════════════════════════════════════════════════════${NC}"
echo ""

# Prevent Python from loading default .env file
export DOTENV_OVERRIDE=1

# Start the peer
python main.py --api --api-port 8766 --port 4002 --seed 2
