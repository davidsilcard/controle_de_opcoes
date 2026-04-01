#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${APP_DIR:-/home/david/controle_de_opcoes}"
COMPOSE_BIN="${COMPOSE_BIN:-/usr/bin/docker}"
SCRAPE_ARGS="${SCRAPE_ARGS:---statusinvest}"
SNAPSHOT_OUTPUT="${SNAPSHOT_OUTPUT:-data/opcoes_latest.csv}"

cd "$APP_DIR"

echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] Validando banco..."
"$COMPOSE_BIN" compose exec -T web uv run python -m opcoes.cli db check

echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] Rodando scrape..."
"$COMPOSE_BIN" compose exec -T web uv run python -m opcoes.cli scrape ${SCRAPE_ARGS}

echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] Exportando snapshot CSV..."
"$COMPOSE_BIN" compose exec -T web uv run python -m opcoes.cli snapshot export --output "${SNAPSHOT_OUTPUT}"

echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] Atualizando Fundamentus..."
"$COMPOSE_BIN" compose exec -T web uv run python -m opcoes.cli fundamentus
"$COMPOSE_BIN" compose exec -T web uv run python -m opcoes.cli fundamentus-filter

echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] Ciclo concluído."
