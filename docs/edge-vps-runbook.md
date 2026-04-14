# Edge API VPS runbook

Este runbook descreve a publicacao de `api.moven.cloud` na VPS, usando a edge FastAPI deste repositorio e o `mt5-gateway` privado rodando na maquina Windows.

## Topologia

- Windows local:
  - terminal MetaTrader 5
  - `api-metatrader5` em `127.0.0.1:8000`
- Tailscale/WireGuard:
  - conecta VPS <-> Windows em rede privada
- VPS:
  - app Flask em `127.0.0.1:8000`
  - edge FastAPI em `127.0.0.1:8001`
  - Caddy publica `opcoes.moven.cloud` e `api.moven.cloud`

## Variaveis minimas na VPS

No `/etc/controle_de_opcoes/app.env`:

```bash
DATABASE_URL=postgresql://usuario:senha@host.docker.internal:5432/mercado_opcoes
OPCOES_SECRET_KEY=troque-por-uma-chave-longa-e-forte

MT5_GATEWAY_BASE_URL=http://100.64.0.10:8000
MT5_GATEWAY_KEY_ID=edge=1
MT5_GATEWAY_SHARED_SECRET=troque-por-um-segredo-forte
MT5_GATEWAY_SCOPES=quotes:read,symbols:read,orders:preview
MT5_GATEWAY_TIMEOUT_SECONDS=10

OPCOES_EDGE_API_TOKENS=excel=troque-este-token,app=troque-outro-token
OPCOES_EDGE_QUOTE_CACHE_MS=500
OPCOES_EDGE_WS_TOKEN_TTL_SECONDS=60
OPCOES_EDGE_WS_POLL_INTERVAL_MS=1000
```

## Docker Compose

O `compose.yaml` agora sobe:

- `web` em `127.0.0.1:8000`
- `edge` em `127.0.0.1:8001`

Bind recomendado na VPS:

```bash
export OPCOES_WEB_BIND=127.0.0.1:8000:8000
export OPCOES_EDGE_BIND=127.0.0.1:8001:8001
docker compose up -d --build
```

Com o helper do projeto:

```bash
cd ~/apps/controle_de_opcoes
export OPCOES_EDGE_BIND=127.0.0.1:8001:8001
deploy/scripts/opcoes-compose-vps.sh up -d --build
docker compose logs -f edge
```

Observacao:

- o helper `deploy/scripts/opcoes-compose-vps.sh` agora le `OPCOES_EDGE_BIND` do arquivo definido em `OPCOES_APP_ENV_FILE`
- isso permite deixar a porta do `edge` configurada diretamente no `/etc/controle_de_opcoes/app.env`, por exemplo `OPCOES_EDGE_BIND=127.0.0.1:8011:8001`

## Caddy

Exemplo minimo:

```caddy
opcoes.moven.cloud {
    reverse_proxy 127.0.0.1:8000
}

api.moven.cloud {
    reverse_proxy 127.0.0.1:8001
}
```

Aplicacao do arquivo na VPS:

```bash
sudo mkdir -p /etc/caddy
sudo cp deploy/caddy/Caddyfile.example /etc/caddy/Caddyfile
sudo systemctl reload caddy
```

## Fluxos

### REST

1. cliente chama `https://api.moven.cloud/v1/quotes/PETR4`
2. envia `Authorization: Bearer <token>`
3. edge valida bearer token
4. edge consulta o `mt5-gateway` por HMAC na rede privada
5. edge responde em JSON

### WebSocket

1. cliente chama `POST /v1/ws/token` com bearer token
2. edge responde com ticket curto
3. cliente conecta em `wss://api.moven.cloud/v1/ws/quotes?token=...`
4. cliente envia `{"action":"subscribe","symbols":["PETR4","BBDCG189"]}`
5. edge faz polling do gateway privado e envia snapshots

## Observacoes operacionais

- mantenha o relogio do Windows e da VPS sincronizados por NTP
- nao exponha o `mt5-gateway` diretamente na internet
- mantenha `MT5_ENABLE_ORDER_SEND=0` no Windows ate fechar o fluxo de ordens
- `GET /ready` do gateway agora so sinaliza prontidao e conexao do MT5; nao espere mais detalhes sensiveis de conta/terminal nesse endpoint
- a edge usa cache em memoria; em multi-worker esse cache nao e compartilhado
- para WebSocket, prefira uma unica instancia/worker da edge

## Sequencia pratica de deploy

1. subir o `mt5-gateway` no Windows
2. validar `http://127.0.0.1:8000/ready` no Windows
3. estabelecer a rede privada VPS <-> Windows
4. ajustar `/etc/controle_de_opcoes/app.env` na VPS
5. subir `web` e `edge` com Docker Compose
6. publicar `opcoes.moven.cloud` e `api.moven.cloud` no Caddy
7. testar:
   - `https://api.moven.cloud/health`
   - `http://100.64.0.10:8000/ready`
   - `POST /v1/ws/token`
   - `GET /v1/quotes/PETR4`
