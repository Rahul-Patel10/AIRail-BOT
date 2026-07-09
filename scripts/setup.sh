#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

echo "Installing Python dependencies..."
pip install -r requirements.txt

echo "Bootstrapping database and vector indexes..."
python backend/bootstrap.py

echo "Installing frontend dependencies..."
cd frontend && npm install

echo "Setup complete. Run scripts/run-backend.sh and scripts/run-frontend.sh to start."
