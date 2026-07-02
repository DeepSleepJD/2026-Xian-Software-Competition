#!/bin/bash
set -e

if [ "$#" -ne 3 ]; then
  echo "Usage: $0 <playerId> <host> <port>"
  exit 1
fi

PLAYER_ID="$1"
HOST="$2"
PORT="$3"

python3 basic_client.py \
  --player-id "${PLAYER_ID}" \
  --host "${HOST}" \
  --port "${PORT}" \
  --player-name "codex-py" \
  --version "0.1"
