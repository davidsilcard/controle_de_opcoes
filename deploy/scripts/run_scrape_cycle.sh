#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${APP_DIR:-/home/david/apps/controle_de_opcoes}"
CLI_PYTHON="${CLI_PYTHON:-/app/.venv/bin/python}"
SCRAPE_ARGS="${SCRAPE_ARGS:---statusinvest}"
SNAPSHOT_OUTPUT="${SNAPSHOT_OUTPUT:-data/opcoes_latest.csv}"
COMPOSE_HELPER="${COMPOSE_HELPER:-${APP_DIR}/deploy/scripts/opcoes-compose-vps.sh}"
RANKING_CACHE_WARM_USERNAME="${RANKING_CACHE_WARM_USERNAME:-}"
RUN_ID=""

cd "$APP_DIR"

run_cli() {
  /bin/bash "$COMPOSE_HELPER" exec -T web "$CLI_PYTHON" -m opcoes.cli "$@"
}

finish_run() {
  exit_code=$?
  trap - EXIT
  if [[ -n "$RUN_ID" ]]; then
    if [[ $exit_code -eq 0 ]]; then
      run_cli service-run finish \
        --run-id "$RUN_ID" \
        --status success \
        --step done \
        --summary "Ciclo diario concluido com scrape, exportacao, Fundamentus e retencao." || true
    else
      run_cli service-run finish \
        --run-id "$RUN_ID" \
        --status failed \
        --step failed \
        --summary "Ciclo diario interrompido." \
        --message "Falha no ciclo agendado. Consulte o journal do opcoes-scrape.service." || true
    fi
  fi
  exit "$exit_code"
}

trap finish_run EXIT

RUN_ID="$(run_cli service-run start --service scrape_cycle --trigger systemd --step db_check --summary "Ciclo diario iniciado.")"

echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] Validando banco..."
run_cli db check

echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] Rodando scrape..."
run_cli scrape ${SCRAPE_ARGS}

echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] Exportando snapshot CSV..."
run_cli snapshot export --output "${SNAPSHOT_OUTPUT}"

echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] Atualizando Fundamentus..."
run_cli fundamentus
run_cli fundamentus-filter

echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] Aplicando retencao automatica..."
run_cli retention

if [[ -n "$RANKING_CACHE_WARM_USERNAME" ]]; then
  echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] Atualizando cache persistido do ranking para ${RANKING_CACHE_WARM_USERNAME}..."
  run_cli ranking-cache refresh --username "$RANKING_CACHE_WARM_USERNAME"
fi

echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] Ciclo concluido."
