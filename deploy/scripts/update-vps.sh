#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${APP_DIR:-/home/david/apps/controle_de_opcoes}"
REMOTE="${REMOTE:-origin}"
BRANCH="${BRANCH:-main}"
COMPOSE_HELPER="${COMPOSE_HELPER:-${APP_DIR}/deploy/scripts/opcoes-compose-vps.sh}"
WEB_CHECK_URL="${WEB_CHECK_URL:-http://127.0.0.1:8000/login}"
EDGE_CHECK_URL="${EDGE_CHECK_URL:-http://127.0.0.1:8011/health}"
SMOKE_RETRIES="${SMOKE_RETRIES:-20}"
SMOKE_SLEEP_SECONDS="${SMOKE_SLEEP_SECONDS:-2}"
DOCKER_BUILD_CACHE_KEEP_STORAGE="${DOCKER_BUILD_CACHE_KEEP_STORAGE:-2GB}"

cd "$APP_DIR"

wait_for_url() {
  local label="$1"
  local url="$2"
  local mode="${3:-body}"
  local attempt=1

  while (( attempt <= SMOKE_RETRIES )); do
    if [[ "$mode" == "head" ]]; then
      if curl -fsS -I "$url" >/dev/null 2>&1; then
        echo "$label ok -> $url"
        return 0
      fi
    else
      if curl -fsS "$url" >/dev/null 2>&1; then
        echo "$label ok -> $url"
        return 0
      fi
    fi

    echo "$label ainda indisponivel (tentativa ${attempt}/${SMOKE_RETRIES}); aguardando ${SMOKE_SLEEP_SECONDS}s..."
    sleep "$SMOKE_SLEEP_SECONDS"
    attempt=$((attempt + 1))
  done

  echo "$label falhou apos ${SMOKE_RETRIES} tentativas: $url" >&2
  return 1
}

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

echo "[1/6] Atualizando codigo do Git..."
git fetch "$REMOTE"
git pull --ff-only "$REMOTE" "$BRANCH"

echo "[2/6] Rebuild e restart da stack..."
/bin/bash "$COMPOSE_HELPER" up -d --build

echo "[3/6] Validando containers..."
docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"

echo "[4/6] Smoke test web..."
wait_for_url "web" "$WEB_CHECK_URL" "head"

echo "[5/6] Smoke test edge..."
wait_for_url "edge" "$EDGE_CHECK_URL" "body"
curl -fsS "$EDGE_CHECK_URL"

echo "[6/6] Limitando cache Docker nao utilizado a ${DOCKER_BUILD_CACHE_KEEP_STORAGE}..."
docker builder prune -af --keep-storage "$DOCKER_BUILD_CACHE_KEEP_STORAGE"
echo "Deploy concluido com sucesso."
