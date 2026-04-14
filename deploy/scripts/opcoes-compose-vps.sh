#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${APP_DIR:-/home/david/apps/controle_de_opcoes}"
COMPOSE_BIN="${COMPOSE_BIN:-/usr/bin/docker}"

export OPCOES_APP_ENV_FILE="${OPCOES_APP_ENV_FILE:-/etc/controle_de_opcoes/app.env}"
export OPCOES_WEB_BIND="${OPCOES_WEB_BIND:-127.0.0.1:8000:8000}"
export OPCOES_EDGE_BIND="${OPCOES_EDGE_BIND:-127.0.0.1:8001:8001}"
export OPCOES_DATA_DIR="${OPCOES_DATA_DIR:-${APP_DIR}/data}"

cd "$APP_DIR"
exec "$COMPOSE_BIN" compose "$@"
