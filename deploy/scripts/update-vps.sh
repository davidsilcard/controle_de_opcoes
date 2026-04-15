#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${APP_DIR:-/home/david/apps/controle_de_opcoes}"
REMOTE="${REMOTE:-origin}"
BRANCH="${BRANCH:-main}"
COMPOSE_HELPER="${COMPOSE_HELPER:-${APP_DIR}/deploy/scripts/opcoes-compose-vps.sh}"
WEB_CHECK_URL="${WEB_CHECK_URL:-http://127.0.0.1:8000/login}"
EDGE_CHECK_URL="${EDGE_CHECK_URL:-http://127.0.0.1:8011/health}"

cd "$APP_DIR"

if [[ ! -f ".git/HEAD" ]]; then
  echo "Repositorio Git nao encontrado em $APP_DIR" >&2
  exit 1
fi

dirty_files="$(git status --porcelain --untracked-files=no)"
if [[ -n "$dirty_files" ]]; then
  echo "Worktree com alteracoes locais. Limpe antes de atualizar:" >&2
  echo "$dirty_files" >&2
  exit 1
fi

echo "[1/5] Atualizando codigo do Git..."
git fetch "$REMOTE"
git pull --ff-only "$REMOTE" "$BRANCH"

echo "[2/5] Rebuild e restart da stack..."
/bin/bash "$COMPOSE_HELPER" up -d --build

echo "[3/5] Validando containers..."
docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"

echo "[4/5] Smoke test web..."
curl -fsS -I "$WEB_CHECK_URL" >/dev/null
echo "web ok -> $WEB_CHECK_URL"

echo "[5/5] Smoke test edge..."
curl -fsS "$EDGE_CHECK_URL"
echo
echo "Deploy concluido com sucesso."
