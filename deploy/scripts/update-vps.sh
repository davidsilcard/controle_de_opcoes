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
DOCKER_BUILD_CACHE_RESERVED_SPACE="${DOCKER_BUILD_CACHE_RESERVED_SPACE:-2GB}"

cd "$APP_DIR"
SCRIPT_PATH="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/$(basename "${BASH_SOURCE[0]}")"
SCRIPT_DIGEST_BEFORE="$(sha256sum "$SCRIPT_PATH" | awk '{print $1}')"

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

SCRIPT_DIGEST_AFTER="$(sha256sum "$SCRIPT_PATH" | awk '{print $1}')"
if [[ "$SCRIPT_DIGEST_BEFORE" != "$SCRIPT_DIGEST_AFTER" && "${OPCOES_DEPLOY_REEXECED:-0}" != "1" ]]; then
  echo "Script de deploy atualizado; reiniciando antes do rebuild..."
  OPCOES_DEPLOY_REEXECED=1 exec /bin/bash "$SCRIPT_PATH" "$@"
fi

echo "[2/6] Rebuild e restart da stack..."
/bin/bash "$COMPOSE_HELPER" up -d --build

echo "[3/6] Validando containers..."
docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"

echo "[4/6] Smoke test web..."
wait_for_url "web" "$WEB_CHECK_URL" "head"

echo "[5/6] Smoke test edge..."
wait_for_url "edge" "$EDGE_CHECK_URL" "body"
curl -fsS "$EDGE_CHECK_URL"

echo "[6/6] Reservando ${DOCKER_BUILD_CACHE_RESERVED_SPACE} para cache Docker..."
docker builder prune -af --reserved-space "$DOCKER_BUILD_CACHE_RESERVED_SPACE"
echo "Deploy concluido com sucesso."
