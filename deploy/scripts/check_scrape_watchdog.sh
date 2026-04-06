#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${APP_DIR:-/home/david/apps/controle_de_opcoes}"
CLI_PYTHON="${CLI_PYTHON:-/app/.venv/bin/python}"
COMPOSE_HELPER="${COMPOSE_HELPER:-${APP_DIR}/deploy/scripts/opcoes-compose-vps.sh}"
SERVICE_UNIT="${SERVICE_UNIT:-opcoes-scrape.service}"
SERVICE_KEY="${SERVICE_KEY:-scrape_cycle}"

cd "$APP_DIR"

run_cli() {
  /bin/bash "$COMPOSE_HELPER" exec -T web "$CLI_PYTHON" -m opcoes.cli "$@"
}

active_state="$(systemctl show "$SERVICE_UNIT" -p ActiveState --value 2>/dev/null || true)"
sub_state="$(systemctl show "$SERVICE_UNIT" -p SubState --value 2>/dev/null || true)"

if [[ "$active_state" == "active" || "$active_state" == "activating" ]]; then
  exit 0
fi

run_cli service-run watchdog \
  --service "$SERVICE_KEY" \
  --step watchdog \
  --summary "Watchdog marcou a execucao como interrompida." \
  --message "O unit ${SERVICE_UNIT} nao esta ativo (${active_state:-desconhecido}/${sub_state:-desconhecido}), mas o painel ainda mostrava a execucao em andamento."
