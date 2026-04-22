# Opções

Aplicação para controle de estratégias com opções, com foco didático para cliente leigo.
Arquitetura operacional consolidada em **PostgreSQL** para manter histórico único e consistente.

## Pré-requisitos

- Python 3.12+
- `uv`
- PostgreSQL acessível (rede + credenciais)

## Instalação

```bash
uv sync --locked --dev
```

O comando acima cria o `.venv` automaticamente e sincroniza as dependências do projeto e do grupo `dev` a partir do `uv.lock`.

Se quiser ativar o ambiente no PowerShell para rodar binários diretamente:

```powershell
.venv\Scripts\Activate.ps1
python -V
pytest -q
deactivate
```

Se o PowerShell responder que `uv` "is not recognized", o mais comum e a sessao atual ter sido aberta antes da instalacao do `uv`.
Feche e abra o terminal novamente. No Windows, o executavel costuma ficar em:

```text
C:\Users\SEU_USUARIO\.local\bin\uv.exe
```

Validacoes uteis no PowerShell:

```powershell
where.exe uv
Get-Command uv
```

Correcao temporaria para a sessao atual:

```powershell
$env:Path += ";$HOME\\.local\\bin"
uv --version
```

Se o terminal estava aberto antes da instalacao do `uv`, recarregue o `PATH` completo do Windows na sessao atual e ative o ambiente novamente:

```powershell
$env:Path = [System.Environment]::GetEnvironmentVariable('Path', 'Machine') + ';' + [System.Environment]::GetEnvironmentVariable('Path', 'User')
& .\.venv\Scripts\Activate.ps1
uv --version
```

## Configuração de ambiente

Crie um `.env` com:

```bash
DATABASE_URL=postgresql://usuario:senha@host:5432/mercado-opcoes
OPCOES_PG_SCHEMA=admin
OPCOES_AUTH_SCHEMA=auth
OPCOES_SECRET_KEY=uma-chave-longa-unica-e-secreta
OPCOES_TEMP_PASSWORD_TTL_SECONDS=10800
```

Observacao:

- em producao, a aplicacao nao sobe se `OPCOES_SECRET_KEY` estiver ausente ou no valor padrao.
- para desenvolvimento local, defina uma chave propria mesmo em ambiente simples.
- para VPS com varias aplicacoes, prefira guardar segredos fora do projeto, por exemplo em `/etc/controle_de_opcoes/app.env`.
- na VPS, trate `/etc/controle_de_opcoes/app.env` como fonte oficial e evite manter `.env` com valores reais na raiz do projeto.
- `OPCOES_AUTH_SCHEMA` define o schema dedicado de autenticacao web, onde ficam `auth.web_users` e os dados de login.
- `OPCOES_TEMP_PASSWORD_TTL_SECONDS` ajusta por quanto tempo a senha temporaria continua valida antes de expirar no primeiro acesso.
- opcionalmente, use `OPCOES_SHARED_SCHEMA` para separar a base compartilhada de mercado/configuracoes do schema operacional do usuario.
- se `OPCOES_SHARED_SCHEMA` nao for definido, a aplicacao usa `OPCOES_AUTOMATION_SCHEMA` e depois `OPCOES_PG_SCHEMA` como base compartilhada.

### Padrao recomendado para VPS com varias aplicacoes

Estrutura sugerida:

```text
/home/david/apps/controle_de_opcoes      -> codigo da aplicacao
/etc/controle_de_opcoes/app.env          -> segredos e configuracao de producao
/etc/systemd/system/opcoes-scrape.service
/etc/systemd/system/opcoes-scrape.timer
/etc/caddy/Caddyfile
```

Separacao de responsabilidades:

- `/home/david/apps/...`: codigo versionado e pasta `data/` da app
- `/etc/<app>/app.env`: segredos e parametros de producao
- `systemd`: jobs agendados e timers
- `Caddy`: dominio, HTTPS e roteamento por subdominio

Regra de precedencia recomendada:

- desenvolvimento local: use `./.env`
- producao na VPS: use `/etc/controle_de_opcoes/app.env`
- quando `OPCOES_APP_ENV_FILE` estiver definido, o loader Python passa a priorizar esse arquivo antes de tentar `./.env`
- na VPS, isso evita divergencia entre comandos `python -m ...` e os containers Docker

Exemplo de arquivo seguro de producao:

- `deploy/env/app.env.example`

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

### Otimizacao do schema PostgreSQL

```bash
uv run python -m opcoes.cli db optimize --username admin
```

Use este comando depois de preparar um usuario/schema novo ou apos uma migracao integral, para criar os indices recomendados e reduzir a latencia de leitura.

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

Na interface, a tela `Covered Call` passou a destacar o estoque consolidado por ativo com total, reservado e livre. O campo de vinculacao legada continua disponivel apenas como compatibilidade historica para posicoes antigas, nao como referencia principal para novas vendas cobertas.

Fluxo operacional novo para garantia de `Covered Call`:

- o cliente nao precisa mais lancar compras separadas da mesma acao para montar a garantia.
- a tela `Covered Call` agora tem um formulario proprio para salvar o `estoque consolidado` por ativo e por modo (`real` ou `simulado`).
- o usuario informa manualmente `quantidade atual` e `preco medio`; a aplicacao usa esse saldo como fonte oficial da garantia.
- novas calls cobertas sao bloqueadas quando a quantidade vendida ultrapassa o saldo livre, com mensagem explicando o motivo.
- em `PUT` exercida, a aplicacao aumenta o estoque consolidado e sinaliza revisao do preco medio quando necessario.
- em `CALL` exercida, a aplicacao reduz o estoque consolidado automaticamente e gera um historico fechado para manter a trilha de auditoria/resultado.

Baixa e conferencia visual do resultado realizado:

- na tela `/positions`, preencha `Data saida`, `Preco saida` e `Motivo`, depois clique em `Salvar`.
- o painel `Resultados realizados` consolida lucro/prejuizo por ano e por mes, sempre restrito ao usuario autenticado.

### DARF

```bash
uv run python -m opcoes.cli tax --year 2026 --month 2
```

A partir da baixa da posicao:

- o resultado realizado passa a ser sincronizado no ledger para auditoria.
- a tela `/darf` passa a separar `provisao de caixa` de `DARF oficial do mes`.
- a geracao da DARF usa a apuracao mensal com compensacao de prejuizo e IRRF.

### Web app

```bash
uv run python -m opcoes.web
```

Atualizacao parcial da interface:

- a aplicacao continua em `Flask`, mas agora as telas `Posicoes` e `Covered Call` usam blocos `HTMX` so para leitura dinamica.
- os formularios `POST` continuam server-rendered, o que reduz risco operacional para cadastro, baixa e auditoria.
- os blocos ao vivo consultam rotas parciais internas a cada `15s`:
  - `/positions/partial/live`
  - `/covered-call/partial/live`
- isso melhora a percepcao de fluidez sem forcar uma migracao prematura para SPA.
- a tabela editavel de `Posicoes` nao e mais recarregada pelo polling; o refresh automatico ficou restrito ao painel de monitoramento para evitar perda de digitacao em andamento.
- em `Covered Call`, o cadastro de estoque consolidado voltou a ficar visivel na pagina principal, enquanto o bloco HTMX atua como `painel ao vivo` somente leitura.
- em `Covered Call`, os quadros legados e financeiros agora ficam recolhidos em `Auditoria e detalhes operacionais`, evitando duplicidade visual entre o fluxo principal e a camada de conferência.
- em `Covered Call`, o resumo mensal de `premios liquidos` e `resultado liquido` voltou a ficar sempre visivel na pagina principal, mesmo quando nao existe call aberta no ativo.
- em `Covered Call`, o filtro rapido agora marca com selo `Aberta` os ativos da garantia que ja tem call em aberto, sem esconder o badge de quantidade consolidada.
- em `Covered Call` e `Cash-Covered Put`, os meses dos quadros financeiros passam a ser normalizados para `YYYY-MM`, evitando exibicoes truncadas como `2026-0`.
- a auditoria da `Covered Call` preserva o detalhamento rico de `calls em aberto`, incluindo `recompra`, `% do prêmio`, `extrínseco`, `% p/ 2x`, `P/L` e ações operacionais.
- quando existir call real em aberto, a auditoria da `Covered Call` abre automaticamente e destaca onde estao `recompra`, `P/L` e os botoes operacionais, para o usuario nao precisar procurar essas informacoes.
- a tela `Cash-Covered Put` agora ganhou um `Filtro rapido` com o mesmo padrao visual da `Covered Call`, listando apenas ativos com puts abertas e sinalizando cada um com selo `Aberta`.
- os paineis ao vivo agora mostram de forma explicita a origem do preco (`Ao vivo`, `Atrasado` ou `Snapshot`), a referencia usada (`Bid`, `Ask`, `Ultimo` ou `Snapshot`) e o horario/data util da ultima atualizacao.
- quando a cotacao ao vivo nao estiver disponivel, a aplicacao continua usando o snapshot local, mas sem confundir esse fallback com status `Offline` quando ja existe um preco valido na base.
- quando o gateway informar timestamps com sufixo UTC (`Z`), a UI converte a exibicao para `America/Sao_Paulo`; o valor bruto do provider continua visivel para auditoria.

### Governanca de skills locais e subagentes

Convencao correta para este projeto:

- skills locais e especificas deste repositorio ficam em `./.agents/skills`
- cada skill usa a estrutura `./.agents/skills/<nome-da-skill>/SKILL.md` e `./.agents/skills/<nome-da-skill>/agents/openai.yaml`
- o caminho `agents/.agents/...` foi um artefato local legado e nao deve mais ser usado

Como regra pratica:

- se a skill vale so para este projeto, use `./.agents/skills`
- se a skill for global e reutilizavel em varios projetos, ela deve morar no ambiente global do Codex, nao dentro deste repositorio
- use o termo `skill local` para o pacote de instrucoes especializadas salvo no repositorio
- use o termo `subagente` apenas para uma execucao delegada em paralelo, quando realmente houver necessidade de dividir trabalho

As skills locais em `./.agents/skills` documentam um perfil recomendado de modelo e raciocinio. Como `openai.yaml` aqui e usado mais como metadata de interface, a recomendacao operacional fica registrada nas `SKILL.md`.

Onde colocar skills:

- skill local deste projeto: `C:\projetos-python\controle_de_opcoes\.agents\skills\<nome-da-skill>\`
- skill global reutilizavel em varios projetos: `C:\Users\david\.codex\skills\<nome-da-skill>\`
- caminho legado que nao deve mais ser usado: `C:\projetos-python\controle_de_opcoes\agents\.agents\...`

Exemplo local valido:

- `C:\projetos-python\controle_de_opcoes\.agents\skills\perito-mercado-opcoes\SKILL.md`
- `C:\projetos-python\controle_de_opcoes\.agents\skills\perito-mercado-opcoes\agents\openai.yaml`

Perfis adotados:

- `orquestrador`: `gpt-5.4` com `high`
- `arquiteto-software`: `gpt-5.4` com `high`
- `arquiteto-seguranca`: `gpt-5.4` com `high`
- `revisor-codigo`: `gpt-5.4` com `high`
- `revisor-seguranca`: `gpt-5.4` com `high`
- `diretor-ux`: `gpt-5.4-mini` com `medium`
- `diretor-frontend-ui`: `gpt-5.4-mini` com `medium`
- `perito-mercado-opcoes`: `gpt-5.4` com `high`

### Edge API publica

Servico separado para `api.moven.cloud`, com cache curto, bearer token e WebSocket:

```bash
uv run python -m opcoes.edge
```

Responsabilidades da edge:

- autenticar clientes publicos com bearer token
- consumir o `mt5-gateway` privado via HMAC
- cachear quotes por poucos milissegundos
- emitir tickets curtos para WebSocket

Variaveis minimas para a edge:

```bash
MT5_GATEWAY_BASE_URL=http://100.64.0.10:8000
MT5_GATEWAY_KEY_ID=edge=1
MT5_GATEWAY_SHARED_SECRET=troque-por-um-segredo-forte
MT5_GATEWAY_SCOPES=quotes:read,symbols:read
OPCOES_EDGE_API_TOKENS=excel=troque-este-token,app=troque-outro-token
```

Contrato atual do `mt5-gateway` consumido pela edge:

- autenticacao HMAC com `X-Key-Id`, `X-Timestamp`, `X-Nonce` e `X-Signature`
- `GET /ready` agora deve ser interpretado principalmente por `status`, `provider`, `connected` e `state`
- `mt5_connected` e `mt5_state` ainda podem aparecer, mas so como compatibilidade retroativa
- `POST /internal/v1/quotes/batch` pode retornar sucesso parcial; a edge preserva itens com erro no batch publico e cacheia apenas os itens validos
- `GET /internal/v1/metrics` fica disponivel para monitoramento do gateway privado
- `POST /internal/v1/orders/preview` e `POST /internal/v1/orders` podem responder `501 not_supported` nesta fase e nao devem ser tratados como fluxo operacional disponivel

Exemplo rapido de uso do cliente interno:

```python
from opcoes.mt5_gateway import Mt5GatewayClient

client = Mt5GatewayClient()
print(client.ready())
print(client.metrics())
print(client.get_quote("PETR4"))
print(client.get_quotes_batch(["PETR4", "VALE3"]))
```

Camada interna de market data ao vivo:

- a aplicacao web principal continua dona das formulas e das decisoes didaticas
- o gateway privado segue como fonte bruta de mercado, mesmo com backend local mudando de MT5 para `BTG Trader Desk`
- o `opcoes-edge` distribui quotes com cache curto e autenticacao interna
- `Posicoes` e `Covered Call` agora tentam usar quotes ao vivo no backend a cada carregamento da pagina
- se o edge ou o gateway falharem, a UI volta para os snapshots sem quebrar a tela

Variaveis opcionais para a camada live do backend:

```bash
OPCOES_EDGE_BASE_URL=http://127.0.0.1:8011
OPCOES_MARKET_DATA_TOKEN=token-interno-opcional
OPCOES_MARKET_DATA_TIMEOUT_SECONDS=15
OPCOES_MARKET_DATA_STALE_AFTER_SECONDS=60
OPCOES_PERF_TIMING_ENABLED=1
RANKING_CACHE_WARM_USERNAME=
OPCOES_STRATEGY_PAGE_CACHE_SECONDS=30
OPCOES_WEB_WORKERS=4
OPCOES_WEB_WORKER_CLASS=gthread
OPCOES_WEB_THREADS=4
OPCOES_WEB_TIMEOUT_SECONDS=120
```

Observacoes:

- se `OPCOES_MARKET_DATA_TOKEN` nao for definido, a aplicacao tenta reutilizar o token `app` de `OPCOES_EDGE_API_TOKENS`
- para backend via `BTG Trader Desk`, `OPCOES_MARKET_DATA_TIMEOUT_SECONDS=15` tende a ser um valor inicial mais seguro que `5`, porque alguns lotes parciais podem levar varios segundos antes de fechar com timeout por item
- a marcacao padrao usa `last` para acoes e regra hibrida para opcoes: `ask` em posicoes vendidas e `bid` em posicoes compradas, com fallback para `last`
- a UI marca cada preco como `Ao vivo`, `Atrasado`, `Snapshot` ou `Offline`
- com `OPCOES_PERF_TIMING_ENABLED=1`, a app Flask emite `Server-Timing` nas respostas web e log estruturado `web_request_timing`
- `OPCOES_RANKING_CACHE_SECONDS` agora funciona como cache L1 em memoria + cache L2 persistido em PostgreSQL para a home de ranking
- `OPCOES_STRATEGY_PAGE_CACHE_SECONDS` controla o cache L1/L2 persistido das paginas cheias de estrategia, reduzindo o custo de troca entre abas
- `RANKING_CACHE_WARM_USERNAME` permite aquecer o cache persistido do ranking ao final do ciclo agendado para um usuario/schema especifico
- `OPCOES_WEB_WORKERS`, `OPCOES_WEB_WORKER_CLASS`, `OPCOES_WEB_THREADS` e `OPCOES_WEB_TIMEOUT_SECONDS` controlam o runtime do `gunicorn` no container `web`

Fluxo recomendado:

- `opcoes.moven.cloud` continua na app Flask
- `api.moven.cloud` publica a edge FastAPI
- a edge chama o gateway privado rodando na maquina Windows, agora podendo usar `BTG Trader Desk` como backend de cotacao

Arquivos principais:

- `opcoes/mt5_gateway.py`
- `opcoes/edge.py`
- `docs/edge-vps-runbook.md`

### Teste de estresse da API

Para medir throughput, latencia e taxa de erro da API live, use:

```bash
uv run python -m opcoes.stress_api --mode quote --symbol PETR4 --requests 200 --concurrency 20
```

Exemplos uteis:

```bash
uv run python -m opcoes.stress_api --mode health --base-url http://127.0.0.1:8011 --requests 300 --concurrency 30
uv run python -m opcoes.stress_api --mode metrics --base-url http://127.0.0.1:8011 --requests 120 --concurrency 12
uv run python -m opcoes.stress_api --mode batch --symbols PETR4,VALE3,ITUB4,BBAS3 --requests 150 --concurrency 15
uv run python -m opcoes.stress_api --mode search --query PETR --limit 10 --requests 100 --concurrency 10
uv run python -m opcoes.stress_api --mode quote --symbol PETR4 --requests 200 --concurrency 20 --json
```

Observacoes:

- o comando tenta reutilizar o token `app` de `OPCOES_EDGE_API_TOKENS`
- se preferir, informe `--token` ou configure `OPCOES_MARKET_DATA_TOKEN`
- o resumo mostra `req/s`, `p50`, `p95`, `p99`, codigos HTTP e erros mais frequentes
- para medir a stack completa em producao, aponte `--base-url` para o `opcoes-edge` publicado na VPS

## Deploy Docker no VPS

Fluxo recomendado para producao no VPS Linux:

- codigo versionado no GitHub
- aplicacao web em container Docker
- PostgreSQL rodando no host do VPS
- proxy HTTPS configurado depois, quando o dominio estiver pronto

Arquivos de deploy incluidos no repositorio:

- `Dockerfile`
- `compose.yaml`
- `.dockerignore`

### Variaveis para Docker no VPS

Ao usar `compose.yaml`, o container precisa enxergar o PostgreSQL do host.
No Linux, use `host.docker.internal` como host do banco dentro do `.env`:

```bash
DATABASE_URL=postgresql://opcoes_app:sua_senha_forte@host.docker.internal:5432/mercado_opcoes
OPCOES_PG_SCHEMA=admin
OPCOES_SECRET_KEY=troque-por-uma-chave-longa-e-unica
OPCOES_AUTH_SCHEMA=auth
OPCOES_AUTH_ENABLED=1
OPCOES_WEB_DEBUG=0
OPCOES_SESSION_COOKIE_SECURE=1
OPCOES_SESSION_COOKIE_SAMESITE=Lax
```

Observacao:

- use `OPCOES_SESSION_COOKIE_SECURE=0` enquanto estiver acessando por IP/HTTP
- troque para `1` quando colocar HTTPS com proxy reverso
- o login aplica rate limit por IP e usa o IP percebido pelo Flask depois do `ProxyFix`; em ambiente com proxy reverso, o proxy precisa ser confiavel.
- o rate limit agora fica persistido no schema de autenticacao (`OPCOES_AUTH_SCHEMA`), entao continua valendo mesmo com multiplos workers/instancias da web.
- ajustes opcionais:

```bash
OPCOES_LOGIN_MAX_ATTEMPTS=5
OPCOES_LOGIN_WINDOW_SECONDS=900
OPCOES_LOGIN_BLOCK_SECONDS=900
```

- formularios `POST` agora validam token CSRF. Se aparecer mensagem de formulario expirado, recarregue a pagina e envie novamente.
- snapshots, ranking, Fundamentus e configuracoes didaticas agora sao lidos da base compartilhada; posicoes, ledger, DARF e dados fiscais continuam isolados por usuario autenticado.

### Subir a aplicacao com Docker

Build e subida inicial:

```bash
docker compose build
docker compose up -d
```

Ver logs:

```bash
docker compose logs -f web
```

Checar banco de dentro do container:

```bash
docker compose exec web /app/.venv/bin/python -m opcoes.cli db check
```

Se o `db check` falhar com `host.docker.internal` em `timed out`, o PostgreSQL do host
normalmente ainda nao esta aceitando conexoes vindas da rede Docker. Corrija assim:

```bash
docker network inspect controle_de_opcoes_default --format '{{range .IPAM.Config}}{{.Subnet}}{{end}}'
sudo nano /etc/postgresql/16/main/postgresql.conf
```

No `postgresql.conf`, ajuste:

```bash
listen_addresses = '*'
```

Depois libere a sub-rede Docker no `pg_hba.conf`, trocando `<SUBNET_DOCKER>` pelo valor
retornado no `docker network inspect`:

```bash
echo "host    mercado_opcoes    opcoes_app    <SUBNET_DOCKER>    scram-sha-256" | sudo tee -a /etc/postgresql/16/main/pg_hba.conf
sudo ufw allow from <SUBNET_DOCKER> to any port 5432 proto tcp
sudo systemctl restart postgresql
docker compose exec web /app/.venv/bin/python -m opcoes.cli db check
```

Criar usuario inicial da aplicacao web:

```bash
docker compose exec web /app/.venv/bin/python -m opcoes.cli user create --username admin
```

Convidar um cliente com senha temporaria de primeiro acesso:

```bash
docker compose exec web /app/.venv/bin/python -m opcoes.cli user invite --username alice
```

Fluxo recomendado:

- o comando imprime uma senha temporaria forte uma unica vez no terminal
- voce copia `usuario + senha temporaria` e envia ao cliente por canal seguro
- no primeiro login, o sistema obriga o cliente a cadastrar a senha pessoal antes de acessar a plataforma
- depois da troca, a senha temporaria deixa de valer
- a senha temporaria expira em `3 horas`; se vencer, reemita com `user invite --replace`

Se quiser convidar e ja preparar o schema inicial do cliente no mesmo passo:

```bash
docker compose exec web /app/.venv/bin/python -m opcoes.cli user invite --username alice --bootstrap --from-schema admin
```

Preparar um segundo usuario sem copiar posicoes/DARF do `admin`:

```bash
docker compose exec web /app/.venv/bin/python -m opcoes.cli user bootstrap --username alice --from-schema admin
```

Observacoes:

- a base de mercado, relatorios indicados, Fundamentus e configuracoes didaticas agora e compartilhada por todos os usuarios.
- o schema do usuario continua reservado para posicoes, ledger, DARF, premios, exercicios e demais dados pessoais.
- o modo padrao `market` continua disponivel para compatibilidade operacional, sem misturar posicoes, ledger e DARF de outro usuario.
- se voce realmente quiser clonar tudo do schema base, use `--mode full`.
- cada usuario agora recebe um `app_schema` exclusivo e persistido no cadastro em `auth.web_users`, evitando colisao entre usernames como `ana.silva` e `ana_silva`.
- o schema de destino padrao do bootstrap usa esse `app_schema` exclusivo; se precisar, sobrescreva com `--target-schema`.
- depois de atualizar uma base antiga, rode `uv run python -m opcoes.cli user audit-schemas` para revisar o mapeamento e `uv run python -m opcoes.cli user migrate-schemas` para gravar/replicar os schemas legados de usuarios existentes.

Smoke test HTTP local no VPS:

```bash
curl http://127.0.0.1:8000/login
```

### Atualizar a aplicacao no VPS

```bash
cd ~/apps/controle_de_opcoes
bash deploy/scripts/update-vps.sh
```

Se quiser acompanhar a subida logo depois:

```bash
cd ~/apps/controle_de_opcoes
deploy/scripts/opcoes-compose-vps.sh logs -f web
```

### Migracao integral do PostgreSQL local para a VPS

Quando a origem local ja esta em PostgreSQL e voce quer levar **todas as tabelas da aplicacao**
para a VPS, use o fluxo abaixo. O comando faz copia **table-to-table via `COPY` streaming**,
preserva IDs/identidades e valida a contagem no final.

Tabelas migradas a partir dos schemas da aplicacao:

- `auth.web_users`
- `admin.settings`
- `admin.positions`
- `admin.ledger`
- `admin.darf_months`
- `admin.option_snapshots`
- `admin.underlying_snapshots`
- `admin.flow_history`
- `admin.iv_history`
- `admin.ranking_runs`
- `admin.ranking_entries`
- `admin.decisions`
- `admin.fundamentus_runs`
- `admin.fundamentus_snapshots`
- `admin.fundamentus_filter_runs`
- `admin.fundamentus_signals`
- `admin.ticker_metadata`
- `admin.service_runs`

Recomendacao operacional:

1. no VPS, pare momentaneamente a escrita da aplicacao:

```bash
cd ~/apps/controle_de_opcoes
deploy/scripts/opcoes-compose-vps.sh stop web
```

2. da sua maquina local, abra um tunel SSH para o PostgreSQL da VPS:

```bash
ssh -L 15432:127.0.0.1:5432 david@SEU_IP_DA_VPS
```

3. ainda na maquina local, com o `.env` apontando para o PostgreSQL de origem, rode:

```bash
uv run python -m opcoes.cli db migrate \
  --target-dsn postgresql://opcoes_app:SUA_SENHA_DA_VPS@127.0.0.1:15432/mercado_opcoes \
  --source-app-schema admin \
  --target-app-schema admin \
  --source-auth-schema auth \
  --target-auth-schema auth
```

Observacoes:

- por padrao, o destino sofre `TRUNCATE` antes da copia. Isso e o modo correto para migracao integral.
- use `--no-truncate` apenas em cenario muito controlado.
- para tabelas grandes como `option_snapshots` e `flow_history`, o processo pode levar algum tempo.

4. ao terminar, religue a aplicacao no VPS:

```bash
cd ~/apps/controle_de_opcoes
deploy/scripts/opcoes-compose-vps.sh up -d
```

5. valide a aplicacao:

```bash
deploy/scripts/opcoes-compose-vps.sh exec -T web /app/.venv/bin/python -m opcoes.cli db check
deploy/scripts/opcoes-compose-vps.sh exec -T web /app/.venv/bin/python -m opcoes.cli db optimize --username admin
deploy/scripts/opcoes-compose-vps.sh exec -T web /app/.venv/bin/python -m opcoes.cli user list
```

### Scraper com Docker

O mesmo container inclui Playwright + Chromium, entao o scraper pode rodar assim:

```bash
docker compose run --rm web uv run python -m opcoes.cli scrape
```

Se quiser exportar o snapshot atual:

```bash
docker compose run --rm web uv run python -m opcoes.cli snapshot export --output data/opcoes_latest.csv
```

### Compose para producao na VPS

O `compose.yaml` agora aceita tres variaveis para separar o ambiente de producao do ambiente local:

- `OPCOES_APP_ENV_FILE`: caminho do arquivo com segredos da app
- `OPCOES_WEB_BIND`: bind da porta HTTP interna da aplicacao
- `OPCOES_DATA_DIR`: pasta persistente do host para `data/`

Exemplo local:

```bash
docker compose up -d --build
```

Exemplo de producao na VPS:

```bash
export OPCOES_APP_ENV_FILE=/etc/controle_de_opcoes/app.env
export OPCOES_WEB_BIND=127.0.0.1:8000:8000
export OPCOES_DATA_DIR=/home/david/apps/controle_de_opcoes/data
docker compose up -d --build
```

Para evitar repetir essas variaveis na VPS, use o helper versionado:

```bash
deploy/scripts/opcoes-compose-vps.sh up -d --build
deploy/scripts/opcoes-compose-vps.sh exec -T web /app/.venv/bin/python -m opcoes.cli db check
```

Observacao:

- o helper `deploy/scripts/opcoes-compose-vps.sh` exporta `OPCOES_APP_ENV_FILE`, `OPCOES_WEB_BIND` e `OPCOES_EDGE_BIND`
- antes de chamar o Compose, ele le `OPCOES_WEB_BIND` e `OPCOES_EDGE_BIND` do arquivo apontado por `OPCOES_APP_ENV_FILE`
- isso permite fixar portas diferentes para `web` e `edge` diretamente no `/etc/controle_de_opcoes/app.env`
- em VPS com outra aplicacao ocupando `127.0.0.1:8001`, use por exemplo `OPCOES_EDGE_BIND=127.0.0.1:8011:8001`

### Agendamento do scraper na VPS com systemd

Arquivos versionados:

- `deploy/scripts/run_scrape_cycle.sh`
- `deploy/scripts/check_scrape_watchdog.sh`
- `deploy/systemd/opcoes-scrape.service`
- `deploy/systemd/opcoes-scrape.timer`
- `deploy/systemd/opcoes-scrape-watchdog.service`
- `deploy/systemd/opcoes-scrape-watchdog.timer`

O script faz este ciclo:

1. valida o banco com `db check`
2. executa `scrape --statusinvest`
3. exporta o snapshot consolidado para `data/opcoes_latest.csv`
4. executa `fundamentus`
5. executa `fundamentus-filter`
6. aplica `retention` para remover market data envelhecida

## Runbook Rápido da VPS

### Atualizar a aplicação

A forma recomendada agora é um comando unico:

```bash
cd ~/apps/controle_de_opcoes
bash deploy/scripts/update-vps.sh
```

O script:

- falha cedo se a worktree estiver suja
- roda `git fetch` + `git pull --ff-only`
- rebuilda a stack Docker
- espera `web` e `edge` responderem antes de concluir
- valida `web` e `edge`

Importante:

- `git pull` sozinho nao e suficiente, porque ele nao rebuilda os containers nem faz smoke test
- usamos `bash deploy/scripts/update-vps.sh` em vez de executar o arquivo diretamente para nao depender do bit de execucao preservado apos `git pull` feito a partir de ambientes Windows

Se a VPS estiver com arquivos locais fora do Git, limpe primeiro. O caso mais comum deve ser resolvido resetando o arquivo divergente para a versao do repositório:

```bash
cd ~/apps/controle_de_opcoes
git checkout -- deploy/scripts/opcoes-compose-vps.sh
bash deploy/scripts/update-vps.sh
```

### Subir e parar a stack

Subir sem rebuild:

```bash
cd ~/apps/controle_de_opcoes
deploy/scripts/opcoes-compose-vps.sh up -d
```

Subir com rebuild:

```bash
cd ~/apps/controle_de_opcoes
deploy/scripts/opcoes-compose-vps.sh up -d --build
```

Parar:

```bash
cd ~/apps/controle_de_opcoes
deploy/scripts/opcoes-compose-vps.sh down
```

### Logs e status

Containers e portas:

```bash
docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"
```

Logs da web:

```bash
cd ~/apps/controle_de_opcoes
deploy/scripts/opcoes-compose-vps.sh logs -f web
```

Logs do edge:

```bash
cd ~/apps/controle_de_opcoes
deploy/scripts/opcoes-compose-vps.sh logs -f edge
```

### Testes rápidos

Web:

```bash
curl -i http://127.0.0.1:8000/login
```

Edge:

```bash
curl -i http://127.0.0.1:8011/health
```

 Gateway privado pela tailnet:

```bash
curl -i http://100.70.177.96:8000/health
curl -i http://100.70.177.96:8000/ready
curl -i http://100.70.177.96:8000/internal/v1/metrics
```

Quote via edge com bearer token:

```bash
TOKEN=$(sudo sed -n 's/^OPCOES_EDGE_API_TOKENS=app=//p' /etc/controle_de_opcoes/app.env)
curl -i -H "Authorization: Bearer $TOKEN" http://127.0.0.1:8011/v1/quotes/PETR4
```

### Variáveis principais

Arquivo principal de produção:

```bash
/etc/controle_de_opcoes/app.env
```

Valores importantes no ambiente atual:

```env
MT5_GATEWAY_BASE_URL=http://100.70.177.96:8000
OPCOES_WEB_BIND=127.0.0.1:8000:8000
OPCOES_EDGE_BIND=127.0.0.1:8011:8001
```

O helper `deploy/scripts/opcoes-compose-vps.sh` lê `OPCOES_WEB_BIND` e `OPCOES_EDGE_BIND` diretamente desse arquivo antes de chamar o Docker Compose.

### Diagnóstico rápido

Se o edge não subir:

```bash
sudo ss -ltnp | grep :8011
```

Se o gateway MT5 parar de responder:

```bash
tailscale status
curl -i http://100.70.177.96:8000/health
```

Painel web:

- a aba `Configuracoes` passa a mostrar o status do ciclo agendado, com ultima execucao, inicio, fim, duracao e proxima execucao prevista.
- as marcacoes usam a tabela `service_runs`, gravada automaticamente pelo proprio job agendado.
- se uma execucao ficar tempo demais sem finalizar, o painel sinaliza `Possivel travamento`.
- um watchdog do host reconcilia execucoes que morrerem fora do fluxo normal e evita deixar o painel preso em `Em andamento`.

Observacoes importantes:

- o timer atualiza dados; ele nao sobe `opcoes.web`, porque a aplicacao web ja fica publicada continuamente via `docker compose up -d`.
- o fluxo da VPS nao usa `--headful` nem o proxy legado da maquina antiga.
- o CSV exportado diariamente pode ser usado para download/conferencia operacional.

Instalacao no VPS:

```bash
cd ~/apps/controle_de_opcoes
sudo mkdir -p /etc/controle_de_opcoes
sudo cp deploy/env/app.env.example /etc/controle_de_opcoes/app.env
sudo chown root:david /etc/controle_de_opcoes/app.env
sudo chmod 640 /etc/controle_de_opcoes/app.env
chmod +x deploy/scripts/opcoes-compose-vps.sh
chmod +x deploy/scripts/run_scrape_cycle.sh
chmod +x deploy/scripts/check_scrape_watchdog.sh
sudo cp deploy/systemd/opcoes-scrape.service /etc/systemd/system/
sudo cp deploy/systemd/opcoes-scrape.timer /etc/systemd/system/
sudo cp deploy/systemd/opcoes-scrape-watchdog.service /etc/systemd/system/
sudo cp deploy/systemd/opcoes-scrape-watchdog.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now opcoes-scrape.timer
sudo systemctl enable --now opcoes-scrape-watchdog.timer
sudo systemctl list-timers opcoes-scrape.timer
sudo systemctl list-timers opcoes-scrape-watchdog.timer
```

Antes de subir a aplicacao, edite `/etc/controle_de_opcoes/app.env` e troque todos os placeholders de senha/chave.

O unit `opcoes-scrape.service` chama o script via `/bin/bash`, entao o agendamento nao depende do bit de execucao continuar preservado apos `git pull` feito em ambientes Windows.
O helper `deploy/scripts/opcoes-compose-vps.sh` centraliza o uso de `/etc/controle_de_opcoes/app.env`, bind local `127.0.0.1:8000:8000` e a pasta persistente `/home/david/apps/controle_de_opcoes/data`.

Logs da ultima execucao:

```bash
sudo journalctl -u opcoes-scrape.service -n 200 --no-pager
sudo journalctl -u opcoes-scrape-watchdog.service -n 50 --no-pager
```

Consulta rapida das execucoes registradas no banco:

```bash
deploy/scripts/opcoes-compose-vps.sh exec -T web /app/.venv/bin/python -m opcoes.cli service-run list
```

Execucao manual do job agendado:

```bash
sudo systemctl start opcoes-scrape.service
sudo systemctl start opcoes-scrape-watchdog.service
```

Diagnostico rapido para distinguir rodando de travado:

```bash
sudo systemctl status opcoes-scrape.service
sudo systemctl show opcoes-scrape.service -p ActiveState -p SubState -p Result
sudo journalctl -u opcoes-scrape.service -f
```

### Como validar se o scrape esta funcionando

Checklist operacional rapido:

1. confirme se o job esta ativo no `systemd`:

```bash
sudo systemctl status opcoes-scrape.service --no-pager
```

Leitura esperada:

- `Active: activating (start)` ou `active` enquanto o ciclo ainda estiver em execucao
- `Active: inactive (dead)` logo depois que terminar com sucesso
- se houver `failed`, investigue o `journalctl`

2. confirme se o log continua avancando:

```bash
sudo journalctl -u opcoes-scrape.service -f
```

Leitura esperada:

- novas linhas com etapas como `Rodando scrape`, `Exportando snapshot CSV`, `Atualizando Fundamentus` e `Ciclo concluido`
- mensagens repetidas de download e `OK (...)` tambem indicam progresso real
- se o log parar por muito tempo no mesmo ponto, vale investigar possivel travamento

3. confira o timer do agendamento:

```bash
sudo systemctl status opcoes-scrape.timer --no-pager
```

Leitura esperada:

- o `.service` pode aparecer como `disabled` sem problema
- quem precisa estar habilitado e ativo e o `opcoes-scrape.timer`

4. confira o reflexo no painel web:

- em `Configuracoes > Automacao e servicos`, o status deve mudar de `Em andamento` para `Concluido` ao final
- `Ultimo fim`, `Duracao` e `Resumo` devem ser preenchidos quando o ciclo terminar

5. se quiser confirmar pelo banco da aplicacao:

```bash
cd ~/apps/controle_de_opcoes
deploy/scripts/opcoes-compose-vps.sh exec -T web /app/.venv/bin/python -m opcoes.cli service-run list
```

Leitura esperada:

- a execucao atual aparece como `running` enquanto roda
- ao final, deve virar `success`
- se morrer fora do fluxo normal, o watchdog pode marcar como `failed`

Observacao de horario:

- o timer versionado roda em `Mon..Fri *-*-* 05:00:00 UTC`, que equivale a `02:00` em `America/Sao_Paulo` no cenario atual.
- esse horario foi antecipado para evitar sobreposicao com o `apt-daily-upgrade`, que reinicia o PostgreSQL na janela da manha.
- se voce mudar a politica de horario depois, ajuste o `OnCalendar` e rode `sudo systemctl daemon-reload`.
- depois de atualizar o repositorio na VPS com `git pull`, rode `deploy/scripts/opcoes-compose-vps.sh up -d --build` para que o container use os comandos e telas novos.
- na tela de configuracoes, o painel de automacao separa `Ultimo horario previsto` de `Ultimo inicio real`, evitando confundir o horario agendado do servico com um disparo manual ou atrasado.
- timestamps de cotacao agora sao exibidos para o usuario em `America/Sao_Paulo`, enquanto o timestamp bruto do provider continua visivel para auditoria.

## Usuários (acesso web)

```bash
uv run python -m opcoes.cli user create --username admin
uv run python -m opcoes.cli user list
uv run python -m opcoes.cli user invite --username alice --bootstrap --from-schema admin
uv run python -m opcoes.cli user bootstrap --username alice --from-schema admin
uv run python -m opcoes.cli user audit-schemas
uv run python -m opcoes.cli user migrate-schemas
```

Use `user invite` para emitir senha temporaria e `user bootstrap` quando quiser criar o acesso e preparar o schema inicial do cliente na mesma operacao. O schema de destino padrao agora segue o `app_schema` exclusivo gravado para cada usuario.

## Variáveis de ambiente relevantes

- `DATABASE_URL`
- `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, `DB_HOST`, `DB_PORT`
- `OPCOES_PG_SCHEMA`
- `OPCOES_SHARED_SCHEMA`
- `OPCOES_AUTH_SCHEMA` (schema da autenticação web; default: `auth`)
- `OPCOES_SECRET_KEY`
- `OPCOES_AUTH_ENABLED`
- `OPCOES_TEMP_PASSWORD_TTL_SECONDS`
- `OPCOES_ADMIN_USER`
- `OPCOES_ADMIN_PASSWORD`
- `OPCOES_ADMIN_REPLACE_PASSWORD`
- `OPCOES_WEB_DEBUG`
- `OPCOES_SESSION_IDLE_MINUTES`
- `OPCOES_SESSION_COOKIE_SECURE`
- `OPCOES_SESSION_COOKIE_SAMESITE`
- `OPCOES_LOGIN_MAX_ATTEMPTS`
- `OPCOES_LOGIN_WINDOW_SECONDS`
- `OPCOES_LOGIN_BLOCK_SECONDS`
- `OPCOES_RANKING_CACHE_SECONDS`
- `OPCOES_PERF_TIMING_ENABLED`
- `OPCOES_WEB_WORKERS`
- `OPCOES_WEB_WORKER_CLASS`
- `OPCOES_WEB_THREADS`
- `OPCOES_WEB_TIMEOUT_SECONDS`

## Testes

```bash
uv run pytest -q
```

Observação: testes marcados com `requires_postgres` são pulados automaticamente quando não há `DATABASE_URL`/`POSTGRES_*` configurado.
Artefatos locais de apoio, como `.agents/` e diretórios temporários de teste, não fazem parte do versionamento padrão do projeto.

E2E opcional:

```bash
RUN_E2E_TESTS=1 uv run pytest tests/test_scraper_e2e.py
```

## Melhorias recentes

- higiene de repositório reforçada para ignorar artefatos locais de `.agents/` e temporários de teste, evitando ruído no Git e no VS Code.
- autenticacao web agora fica em schema dedicado de auth, com provisionamento via `user invite`/`user bootstrap`, `auth.web_users` incluido no `db migrate` e TTL configuravel para senha temporaria.
- README agora documenta `db optimize` para criar os indices recomendados apos bootstrap ou migracao.
- README detalha melhor o rate limit de login por IP, incluindo a dependencia de `ProxyFix` e a persistencia no schema de autenticacao.
- deploy base para VPS com `Dockerfile`, `compose.yaml` e `.dockerignore`.
- README agora documenta fluxo de deploy Docker usando PostgreSQL no host do VPS.
- README agora consolida um bloco unico de atualizacao rapida da VPS com `git pull origin main`, rebuild e `db check`.
- painel de `Configuracoes` agora sinaliza `Possivel travamento` quando um ciclo fica tempo demais sem finalizar, e o host passa a ter um watchdog para reconciliar status `running` orfao.
- web app endurecida com exigencia de `OPCOES_SECRET_KEY` segura em producao, CSRF em formularios, headers HTTP de seguranca e rate limit no login.
- CLI `db migrate` agora faz migracao integral entre PostgreSQLs com bootstrap do destino, `COPY` streaming e validacao de contagem.
- assets versionados de `systemd` agora permitem agendar o ciclo de scrape/fundamentus diretamente na VPS, incluindo export diario de `data/opcoes_latest.csv` as 02:00 de `America/Sao_Paulo`.
- CLI `retention` agora aplica politica automatica de expiracao para snapshots e historicos de mercado, preservando dados do usuario, auditoria e DARF.
- aba `Configuracoes` agora inclui um painel de automacao com historico do job agendado, inicio, fim, duracao, status e proxima execucao prevista.
- CLI `service-run` registra e lista execucoes do ciclo agendado para alimentar esse painel.

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
- fluxo de `covered_call` agora usa estoque consolidado por ativo como referencia operacional, sem depender do `lote pai` para validar garantia.
- shell cache de `covered_call` agora invalida depois de atualizar estoque consolidado, os filtros voltaram a persistir entre visitas e o parsing do ranking shell foi consolidado para evitar drift entre a home e o dashboard parcial.
- painel de `Automacao e servicos` agora destaca o horario previsto em `America/Sao_Paulo` separado do inicio real da execucao, corrigindo a leitura do horario de inicio do ciclo agendado.
- fluxo de PUT exercida agora destaca, na tela de `cash-covered-put`, o debito do exercicio, a atualizacao do estoque consolidado e os proximos passos de conferencia.
- exercicio de CALL agora baixa o estoque consolidado automaticamente e preserva historico fechado para auditoria fiscal.
- inferencia de ticker agora nao confunde acoes como `BBAS3` com opcoes, evitando que lotes em estoque aparecam indevidamente na lista de `Cash-Covered Put`.
- auditoria agora inclui o impacto de `ASSIGN` no caixa, reconcilia o lote criado no exercicio da PUT e mostra o liquido total da operacao incluindo exercicio.
- artefatos Python compilados (`__pycache__` e `*.pyc`) deixaram de ser versionados, evitando ruido local no `git status`.
- README agora documenta o cadastro manual de venda de opcao a partir da nota de corretagem e a conferencia posterior na auditoria.
- tela de `positions` agora traz um painel didatico de resultados realizados por ano e por mes, com lista das baixas do periodo e isolamento por usuario autenticado.
- painel de `positions` agora separa resultado bruto, taxas e resultado fiscal liquido, alinhando a visao do usuario com o `Resultado mes` da DARF.
- rota `/positions` agora tem teste de regressao para garantir que o template sempre receba `realized_summary` e nao quebre em tempo de execucao.
- baixa/parcial da posicao agora sincroniza `resultado realizado` no ledger para auditoria fiscal.
- sincronizacao de baixa entre `positions` e `ledger` foi ajustada para nao falhar por wrapper de conexao cruzado entre modulos.
- auditoria agora separa `caixa` de `resultado realizado`, evitando misturar fluxo financeiro com lucro/prejuizo tributavel.
- DARF agora usa apuracao mensal com compensacao de prejuizo e IRRF, mantendo a provisao de caixa apenas como apoio didatico.
- CLI `tax` agora mostra base tributavel, prejuizo acumulado e DARF liquida do mes.

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

## Retencao automatica

Comando principal:

```bash
uv run python -m opcoes.cli retention
uv run python -m opcoes.cli retention --dry-run
```

Politica padrao por tabela:

- `positions`, `ledger`, `darf_months`, `settings`, `web_users`, `decisions`, `ticker_metadata` e `service_runs`: preservados para sempre.
- `option_snapshots`: 120 dias de historico + 30 dias de graca apos vencimento recente.
- `underlying_snapshots`: 400 dias para suportar HV longa (ate 252 dias com folga).
- `iv_history`: 240 dias + 30 dias de graca apos vencimento recente.
- `flow_history`: 60 dias.
- `ranking_entries` e `ranking_runs`: 60 dias.
- `fundamentus_*`: 365 dias.

Observacoes:

- a retencao limpa apenas dados de mercado e apoio operacional; nao toca nos dados fiscais nem nas operacoes do usuario.
- o script `deploy/scripts/run_scrape_cycle.sh` agora aplica essa retencao ao final do ciclo agendado.
