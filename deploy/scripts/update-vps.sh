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
DOCKER_MIN_FREE_KB="${DOCKER_MIN_FREE_KB:-5242880}"
DOCKER_IMAGE_PRUNE_LABEL="${DOCKER_IMAGE_PRUNE_LABEL:-com.docker.compose.project=controle_de_opcoes}"

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

echo "[1/9] Atualizando codigo do Git..."
git fetch "$REMOTE"
git pull --ff-only "$REMOTE" "$BRANCH"

SCRIPT_DIGEST_AFTER="$(sha256sum "$SCRIPT_PATH" | awk '{print $1}')"
if [[ "$SCRIPT_DIGEST_BEFORE" != "$SCRIPT_DIGEST_AFTER" && "${OPCOES_DEPLOY_REEXECED:-0}" != "1" ]]; then
  echo "Script de deploy atualizado; reiniciando antes do rebuild..."
  OPCOES_DEPLOY_REEXECED=1 exec /bin/bash "$SCRIPT_PATH" "$@"
fi

echo "[2/9] Validando espaco livre para o build..."
if [[ ! "$DOCKER_MIN_FREE_KB" =~ ^[0-9]+$ ]]; then
  echo "DOCKER_MIN_FREE_KB precisa ser um numero inteiro positivo." >&2
  exit 1
fi
docker_root_dir="$(docker info --format '{{.DockerRootDir}}')"
available_kb="$(df -Pk "$docker_root_dir" | awk 'NR == 2 {print $4}')"
if [[ ! "$available_kb" =~ ^[0-9]+$ ]]; then
  echo "Nao foi possivel medir o espaco livre em $docker_root_dir." >&2
  exit 1
fi
if (( available_kb < DOCKER_MIN_FREE_KB )); then
  echo "Espaco livre insuficiente para um deploy seguro em $docker_root_dir." >&2
  echo "Disponivel: ${available_kb} KB; minimo exigido: ${DOCKER_MIN_FREE_KB} KB." >&2
  docker system df
  exit 1
fi
echo "Espaco livre validado: ${available_kb} KB em $docker_root_dir."

echo "[3/9] Rebuild das imagens..."
/bin/bash "$COMPOSE_HELPER" build

echo "[4/9] Trocando containers da stack..."
# O Compose da VPS recria containers em modo start-first. Como os nomes sao
# fixos por servico, remover a stack somente apos o build evita conflito de nome
# sem derrubar a versao em execucao caso o build falhe.
/bin/bash "$COMPOSE_HELPER" down --remove-orphans
/bin/bash "$COMPOSE_HELPER" up -d --no-build --remove-orphans

echo "[5/9] Validando containers..."
docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"

echo "[6/9] Smoke test web..."
wait_for_url "web" "$WEB_CHECK_URL" "head"

echo "[7/9] Smoke test edge..."
wait_for_url "edge" "$EDGE_CHECK_URL" "body"
curl -fsS "$EDGE_CHECK_URL"

echo "[8/9] Removendo imagens antigas e sem uso deste projeto..."
docker image prune -f --filter "label=${DOCKER_IMAGE_PRUNE_LABEL}"

echo "[9/9] Reservando ${DOCKER_BUILD_CACHE_RESERVED_SPACE} para cache Docker..."
docker builder prune -af --reserved-space "$DOCKER_BUILD_CACHE_RESERVED_SPACE"
docker system df
echo "Deploy concluido com sucesso."
