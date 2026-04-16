#!/bin/bash
# Cobblestone Pub Management App
# Run this script to start the app, then open http://localhost:5000

cd "$(dirname "$0")"

# Check for .env
if [ ! -f .env ] || grep -q "YOUR_TOKEN_HERE" .env; then
    echo ""
    echo "  ================================================"
    echo "  Square access token not configured!"
    echo "  ================================================"
    echo ""
    echo "  1. Go to https://developer.squareup.com/apps"
    echo "  2. Select your app (or create one)"
    echo "  3. Go to Credentials > Access Token"
    echo "  4. Copy the token and paste it in the .env file:"
    echo "     SQUARE_ACCESS_TOKEN=EAAAl..."
    echo ""
    echo "  The app will start but data pages will show errors"
    echo "  until the token is configured."
    echo ""
fi

# Install dependencies if needed
pip3 install -q flask python-dotenv openpyxl requests 2>/dev/null

echo "Starting Cobblestone Pub Management App..."
echo "Open http://localhost:5000 in your browser"
echo ""

python3 app.py
