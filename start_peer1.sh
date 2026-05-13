#!/bin/bash
# Start Peer 1 with its own payment configuration

# Color output
GREEN='\033[0;32m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}═══════════════════════════════════════════════════════════${NC}"
echo -e "${GREEN}Starting Peer 1${NC}"
echo -e "${BLUE}═══════════════════════════════════════════════════════════${NC}"
echo ""
echo "API Port:     8765"
echo "Libp2p Port:  4001"
echo "Seed:         1"
echo "Config:       .env.peer1"
echo ""

# Load environment from .env.peer1
if [ -f .env.peer1 ]; then
    # Export all variables from .env.peer1
    set -a
    source .env.peer1
    set +a
    
    echo -e "${GREEN}✓${NC} Loaded .env.peer1"
    
    # Show wallet address if available
    if [ ! -z "$PAYMENT_ADDRESS" ]; then
        echo -e "${GREEN}✓${NC} Payment wallet: $PAYMENT_ADDRESS"
    fi
    
    # Verify payment settings
    if [ "$BITSWAP_PAYMENT_ENABLED" == "true" ]; then
        echo -e "${GREEN}✓${NC} Payment mode: ENABLED"
    else
        echo -e "${YELLOW}⚠️${NC}  Payment mode: DISABLED"
    fi
else
    echo "❌ Error: .env.peer1 not found"
    exit 1
fi

echo ""
echo -e "${BLUE}═══════════════════════════════════════════════════════════${NC}"
echo ""

# Prevent Python from loading default .env file
export DOTENV_OVERRIDE=1

# Start the peer
python main.py --api --api-port 8765 --port 4001 --seed 1
