#!/usr/bin/env bash

set -euo pipefail

SERVICE_NAME="${1:-app}"

if docker compose version >/dev/null 2>&1; then
  exec docker compose logs -f "$SERVICE_NAME"
fi

if command -v docker-compose >/dev/null 2>&1; then
  exec docker-compose logs -f "$SERVICE_NAME"
fi

echo "Erro: nem 'docker compose' nem 'docker-compose' estao disponiveis." >&2
exit 1
