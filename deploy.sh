#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
if [ ! -f .env ]; then
  cp .env.example .env
  echo "Fichier .env créé. Modifiez-le puis relancez ./deploy.sh"
  exit 1
fi
docker compose up -d --build
docker compose ps
printf '\nTest local :\n'
curl -fsS http://127.0.0.1:${API_PORT:-8091}/health || true
printf '\n'
