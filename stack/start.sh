#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

if [ $# -eq 0 ]; then
  set -- up -d --build
fi

docker compose -f docker-compose.yml -f docker-compose.gpu.yml -f docker-compose.live-code.yml "$@"
