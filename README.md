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
- PostgreSQL também para os históricos de métricas (`iv_history` e `flow_history`).
- arquivo local de checkpoint (`.checkpoint.json`) apenas para retomada de execução.

Com isso, o runtime oficial não deve mais criar `iv_history.db`/`flow_history.db`.
Persistências de ranking/decisão e cálculo fiscal (DARF) também rodam no backend principal (PostgreSQL).

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

Cadastro manual de venda de opcao pela nota de corretagem:

```bash
uv run python -m opcoes.cli position add --ticker BBASP226 --underlying BBAS3 --trade-date 2026-03-23 --qty 400 --price 0.20 --fees 0.19 --side short
```

Depois do cadastro, recalcule o premio/DARF na tela de posicoes e valide em `/audit` se o premio liquido bate com a nota.

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

## Variáveis de ambiente relevantes

- `DATABASE_URL`
- `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, `DB_HOST`, `DB_PORT`
- `OPCOES_PG_SCHEMA`
- `OPCOES_AUTH_SCHEMA` (schema da autenticação web; default: `auth`)
- `OPCOES_SECRET_KEY`
- `OPCOES_AUTH_ENABLED`
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

Observação: testes marcados com `requires_postgres` são pulados automaticamente quando não há `DATABASE_URL`/`POSTGRES_*` configurado.

E2E opcional:

```bash
RUN_E2E_TESTS=1 uv run pytest tests/test_scraper_e2e.py
```

## Melhorias recentes

- Runtime consolidado em PostgreSQL, sem fallback operacional.
- `snapshot export` usa o backend ativo da aplicação.
- backfill pós-scrape grava no mesmo backend principal.
- checkpoint do scraper migrado para arquivo JSON local de retomada.
- históricos auxiliares do scraper (`iv_history` e `flow_history`) migrados para tabelas no PostgreSQL.
- histórico de ranking/decisões (`history`) e apuração fiscal (`tax`) migrados para fluxo PostgreSQL.
- comandos e módulos legados de migração/backup SQLite removidos da CLI.
- mensagens de execução atualizadas para deixar claro onde os dados são persistidos.
- autenticação web migrada para PostgreSQL (`auth.web_users`).
- runtime sem suporte a `db_path`/`OPCOES_DB_PATH` e sem diretórios de usuário por arquivo (`OPCOES_USERS_DB_DIR`).
- testes legados acoplados a SQLite removidos/ajustados; integração de banco agora usa marcador `requires_postgres`.

- cadastro web de `covered_call`/`cash_put` agora normaliza a perna da opcao como `Vendida` no backend e reforca a orientacao do formulario para evitar registro incoerente.
- painel de `covered_call` agora usa o ativo-base normalizado dos lotes em estoque, evitando sumir cobertura quando o ticker da acao foi digitado errado mas o `underlying` esta correto.
- fluxo de PUT exercida agora destaca, na tela de `cash-covered-put`, o debito do exercicio, o lote de acoes gerado e os proximos passos de conferencia.
- auditoria agora inclui o impacto de `ASSIGN` no caixa, reconcilia o lote criado no exercicio da PUT e mostra o liquido total da operacao incluindo exercicio.
- artefatos Python compilados (`__pycache__` e `*.pyc`) deixaram de ser versionados, evitando ruido local no `git status`.
- README agora documenta o cadastro manual de venda de opcao a partir da nota de corretagem e a conferencia posterior na auditoria.

## Troubleshooting Playwright (uv)

Se `uv run playwright install chromium` falhar com 404 em URL `chrome-for-testing-public/...`:

```bash
uv run playwright --version
uv add "playwright==1.57.0"
uv run playwright install chromium
```

Smoke test rapido:

```bash
uv run python -c "from playwright.sync_api import sync_playwright; p=sync_playwright().start(); b=p.chromium.launch(headless=True); page=b.new_page(); page.goto('https://example.com'); print(page.title()); b.close(); p.stop()"
```
