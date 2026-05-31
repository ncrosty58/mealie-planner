#!/bin/bash
set -e
echo "Updating Mealie MCP Server from upstream repository..."
cd "$(dirname "$0")/../mealie-mcp-server"
git pull origin main
echo "Update complete! The wrapper server will automatically pick up the changes."
