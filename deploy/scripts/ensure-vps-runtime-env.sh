#!/usr/bin/env bash
set -euo pipefail

# Mantém somente configuração operacional não secreta necessária ao runtime.
# Senhas e chaves permanecem exclusivas em /etc/controle_de_opcoes/app.env.
ENV_FILE="${OPCOES_APP_ENV_FILE:-/etc/controle_de_opcoes/app.env}"
KEY="OPCOES_TRUST_PROXY_HOPS"
VALUE="1"

if ! sudo -n test -f "$ENV_FILE"; then
  echo "Arquivo de ambiente de produção não encontrado ou sem acesso: $ENV_FILE" >&2
  exit 1
fi

if sudo -n grep -qx "${KEY}=${VALUE}" "$ENV_FILE"; then
  echo "Configuração de proxy confiável já validada."
  exit 0
fi

if sudo -n grep -q "^${KEY}=" "$ENV_FILE"; then
  sudo -n sed -i -E "s|^${KEY}=.*$|${KEY}=${VALUE}|" "$ENV_FILE"
else
  printf '%s=%s\n' "$KEY" "$VALUE" | sudo -n tee -a "$ENV_FILE" >/dev/null
fi

echo "Configuração de proxy confiável aplicada sem exibir segredos."
