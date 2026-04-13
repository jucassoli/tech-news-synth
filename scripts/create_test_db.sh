#!/usr/bin/env bash
# Phase 2: Create the integration-test database. Idempotent — safe to re-run.
#
# Requires `docker compose up -d postgres` to be running beforehand. The
# `|| true` swallows "database already exists" errors so repeat runs are ok.
set -euo pipefail

DB_NAME="${POSTGRES_DB:-tech_news_synth}_test"
USER_NAME="${POSTGRES_USER:-app}"

docker compose exec -T postgres psql -U "${USER_NAME}" -d postgres \
  -c "CREATE DATABASE ${DB_NAME};" || true

echo "Test database ensured: ${DB_NAME}"
