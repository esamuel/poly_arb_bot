#!/bin/bash
# Run tests in Docker (avoids numpy segfault on some local Anaconda setups)
set -e
cd "$(dirname "$0")"
echo "Running tests in Docker..."
docker compose run --rm polybot python -m pytest tests/ -v
echo "Tests complete."
