# Opções

Aplicação para controle de estratégias com opções, com foco didático para cliente leigo.
Arquitetura operacional consolidada em **PostgreSQL** para manter histórico único e consistente.

## Pré-requisitos

- Python 3.12+
- `uv`
- PostgreSQL acessível (rede + credenciais)

## Instalação

```bash
uv sync --dev
```

## Configuração de ambiente

Crie um `.env` com:

```bash
DATABASE_URL=postgresql://usuario:senha@host:5432/mercado-opcoes
OPCOES_PG_SCHEMA=admin
OPCOES_SECRET_KEY=troque-esta-chave-em-producao
```

Alternativa sem `DATABASE_URL`:

```bash
POSTGRES_DB=mercado-opcoes
POSTGRES_USER=usuario
POSTGRES_PASSWORD=senha
DB_HOST=host
DB_PORT=5432
OPCOES_PG_SCHEMA=admin
```

## Comandos principais

### Diagnóstico de banco

```bash
uv run python -m opcoes.cli db check
```

### Scrape diário

```bash
uv run python -m opcoes.cli scrape
```

Exemplo com proxy e navegador visível:

```bash
uv run python -m opcoes.cli scrape \
  --headful \
  --goto-timeout 90000 \
  --proxy-server http://192.168.21.246:3128 \
  --proxy-username seu_usuario \
  --proxy-password sua_senha
```

O scraper usa:

- PostgreSQL para snapshots e dados funcionais.
- arquivo local de checkpoint (`.checkpoint.json`) apenas para retomada de execução.

### Exportar snapshot para CSV

```bash
uv run python -m opcoes.cli snapshot export --output data/opcoes_latest.csv
```

Opcional:

```bash
uv run python -m opcoes.cli snapshot export --output data/opcoes_latest.csv --date 2026-03-02
```

### Fundamentus

```bash
uv run python -m opcoes.cli fundamentus
uv run python -m opcoes.cli fundamentus-filter
```

### Relatório / ranking

```bash
uv run python -m opcoes.cli report
```

### Posições

```bash
uv run python -m opcoes.cli position add --ticker PETR4 --underlying PETR4 --trade-date 2026-03-02 --qty 100 --price 34.10 --fees 2.5 --side long
uv run python -m opcoes.cli position list
uv run python -m opcoes.cli position close --id 1 --exit-date 2026-03-10 --price 35.20
```

### DARF

```bash
uv run python -m opcoes.cli tax --year 2026 --month 2
```

### Web app

```bash
uv run python -m opcoes.web
```

## Usuários (acesso web)

```bash
uv run python -m opcoes.cli user create --username admin
uv run python -m opcoes.cli user list
```

Migrar usuários legados do `auth.db` para PostgreSQL:

```bash
uv run python -m opcoes.cli user migrate-auth-sqlite --source-db data/auth.db
```

## Variáveis de ambiente relevantes

- `DATABASE_URL`
- `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, `DB_HOST`, `DB_PORT`
- `OPCOES_PG_SCHEMA`
- `OPCOES_AUTH_SCHEMA` (schema da autenticação web; default: `auth`)
- `OPCOES_SECRET_KEY`
- `OPCOES_AUTH_ENABLED`
- `OPCOES_AUTH_LEGACY_DB_PATH` (somente migração do legado SQLite)
- `OPCOES_USERS_DB_DIR`
- `OPCOES_ADMIN_USER`
- `OPCOES_ADMIN_PASSWORD`
- `OPCOES_ADMIN_REPLACE_PASSWORD`
- `OPCOES_WEB_DEBUG`
- `OPCOES_SESSION_IDLE_MINUTES`
- `OPCOES_SESSION_COOKIE_SECURE`
- `OPCOES_SESSION_COOKIE_SAMESITE`
- `OPCOES_RANKING_CACHE_SECONDS`

## Testes

```bash
uv run pytest -q
```

E2E opcional:

```bash
RUN_E2E_TESTS=1 uv run pytest tests/test_scraper_e2e.py
```

## Melhorias recentes

- Runtime consolidado em PostgreSQL, sem fallback operacional.
- `snapshot export` usa o backend ativo da aplicação.
- backfill pós-scrape grava no mesmo backend principal.
- checkpoint do scraper migrado para arquivo JSON local de retomada.
- mensagens de execução atualizadas para deixar claro onde os dados são persistidos.
- autenticação web migrada para PostgreSQL (`auth.web_users`) com comando de import do `auth.db` legado.
