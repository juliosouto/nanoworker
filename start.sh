#!/bin/bash

echo "=========================================================="
echo "                 Starting NanoWorker                      "
echo "=========================================================="

# Check if docker is installed
if ! command -v docker &> /dev/null
then
    echo "Error: docker could not be found. Please install Docker and Docker Compose plugin first."
    exit 1
fi

# Detect public IP
echo "[1/3] Detecting public IP address..."
PUBLIC_IP=$(curl -s --max-time 5 ifconfig.me)

# Ensure required files and directories exist so Docker doesn't mount them as directories
touch .env
touch nanoworker.db
mkdir -p .store

if [ -z "$PUBLIC_IP" ]; then
    echo "⚠️ Warning: Could not detect public IP. Starting in local mode (HTTP only)."
    echo "[2/3] Building and starting containers..."
    docker compose up --build -d
    echo "[3/3] Done!"
    echo ""
    echo "NanoWorker is running!"
    echo "Access your panel locally at: http://localhost"
else
    if [[ "$PUBLIC_IP" == *":"* ]]; then
        FORMATTED_IP=$(echo "$PUBLIC_IP" | tr ':' '-')
        DOMAIN="${FORMATTED_IP}.sslip.io"
    else
        DOMAIN="${PUBLIC_IP}.nip.io"
    fi
    echo "✅ Public IP detected: $PUBLIC_IP"
    echo "✅ Automatic HTTPS domain: $DOMAIN"
    
    echo "[2/3] Building and starting containers with Caddy SSL..."
    # Run docker compose with the DOMAIN environment variable
    DOMAIN=$DOMAIN docker compose up --build -d
    
    echo "[3/3] Done!"
    echo ""
    echo "=========================================================="
    echo "NanoWorker is successfully running in the background!"
    echo "🔒 Access your panel securely at:"
    echo "   https://$DOMAIN"
    echo ""
    echo "Note: It may take a few seconds for the SSL certificate to "
    echo "be generated on the very first run."
    echo "=========================================================="
fi
