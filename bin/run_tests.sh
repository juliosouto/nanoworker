#!/bin/bash
# script to run tests locally

# Go to project root
cd "$(dirname "$0")/.."

# Activate virtual environment if it exists and we're not in one
if [[ -z "$VIRTUAL_ENV" && -d ".venv" ]]; then
    source .venv/bin/activate
fi

# Make sure testing dependencies are installed
# npm equivalent would be "pip install -r requirements.txt" but we assume it's done.
# You can uncomment the line below if you want it to auto-install:
# pip install -r requirements.txt

# Run pytest
echo "Running pytest..."
pytest

echo "Tests finished."
