#!/bin/bash
#
# A simple script to run the FastAPI application using uvicorn.
# This script adapts to Windows environments by using 127.0.0.1.
#
# Usage:
# 1. Make the script executable: chmod +x run.sh
# 2. Run the script: ./run.sh [PORT]
#    Optional: specify a port number if 8000 is in use
#

# Set default port and allow override via command line argument
PORT=${1:-8888}

# For Windows, we'll use 127.0.0.1 instead of 0.0.0.0 to avoid permission issues
HOST="127.0.0.1"

echo "Starting Webhook MCP Service on http://$HOST:$PORT"
echo "API docs will be available at http://$HOST:$PORT/docs"
echo "Press CTRL+C to stop the server."

# Use 127.0.0.1 for Windows environments to avoid permission errors
# Using a higher port number (8888) which is less likely to have permission issues
# --reload enables auto-reloading on code changes, which is great for development.
# run app in app/main.py
uv run uvicorn app.main:app --host $HOST --port $PORT --reload
