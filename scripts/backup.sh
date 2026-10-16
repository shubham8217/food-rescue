#!/usr/bin/env bash
# Linux/macOS backup of PostgreSQL and MongoDB.  Usage: ./scripts/backup.sh [compose-file] [env-file]
set -euo pipefail
COMPOSE_FILE="${1:-docker-compose.yml}"
ENV_ARGS=()
[ -n "${2:-}" ] && ENV_ARGS=(--env-file "$2")
DIR="backups/$(date +%Y%m%d-%H%M%S)"
mkdir -p "$DIR"
docker compose -f "$COMPOSE_FILE" "${ENV_ARGS[@]}" exec -T postgres pg_dump -U "${POSTGRES_USER:-foodrescue}" -d "${POSTGRES_DB:-foodrescue}" --format=custom > "$DIR/postgres.dump"
docker compose -f "$COMPOSE_FILE" "${ENV_ARGS[@]}" exec -T mongo mongodump --db foodrescue --archive --gzip > "$DIR/mongo.archive.gz"
echo "Backup written to $DIR"
