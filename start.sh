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

if [ -z "$PUBLIC_IP" ]; then
    echo "⚠️ Warning: Could not detect public IP. Starting in local mode (HTTP only)."
    echo "[2/3] Starting containers..."
    docker compose up -d
    echo "[3/3] Done!"
    echo ""
    echo "NanoWorker is running!"
    echo "Access your panel locally at: http://localhost"
else
    DOMAIN="${PUBLIC_IP}.nip.io"
    echo "✅ Public IP detected: $PUBLIC_IP"
    echo "✅ Automatic HTTPS domain: $DOMAIN"
    
    echo "[2/3] Starting containers with Caddy SSL..."
    # Run docker compose with the DOMAIN environment variable
    DOMAIN=$DOMAIN docker compose up -d
    
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
