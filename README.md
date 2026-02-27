opcoes – Monitoramento e gestão de opções (CALLs/PUTs)

Projeto para coletar dados de opções, rankear oportunidades, manter histórico e apoiar
decisões com foco didático. A plataforma separa responsabilidades (scraper, ranking,
estratégias, posições, finanças e DARF) e mantém trilha auditável em SQLite (padrão), com suporte gradual a PostgreSQL.

## Visão geral
- Scraper diário do `https://opcoes.net.br/opcoes/bovespa` via Playwright.
- Geração de ranking com critérios de moneyness, liquidez, IV, risco de theta e cenário de 2x.
- Estratégias para Cash-Covered Put e Covered Call, com gestão de posições e fluxo de caixa.
- Aba Fundamentus para filtro fundamentalista e ranking histórico de aprovadas.
- Web app para navegação didática (ranking, posições, DARF, estratégias, settings).

## Requisitos
- Python 3.12+
- uv

## Migração do gerenciador (Poetry -> uv)
Instalar `uv`:
```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```
Remover `poetry` (quando instalado pelo instalador oficial):
```bash
curl -sSL https://install.python-poetry.org | python3 - --uninstall
```
Se o Poetry tiver sido instalado por outro método (apt, pip, pipx etc.), remova pelo mesmo gerenciador de origem.

## Instalação
```bash
uv lock
uv sync
uv run python -m playwright install chromium
```

Se o download do Playwright falhar (ex.: `404`), o scraper tenta usar automaticamente o
Google Chrome do sistema (`/usr/bin/google-chrome`) quando disponível.

## Uso rápido
1) Coletar opções:
```bash
uv run python -m opcoes.cli scrape
```
2) Ver resumo e alertas:
```bash
uv run python -m opcoes.cli report
```
3) Abrir a interface web:
```bash
uv run python -m opcoes.web
```

## Comandos principais (CLI)
Ver ajuda geral:
```bash
uv run python -m opcoes.cli --help
```

### Coleta e enriquecimento
- Coletar tudo (CALL/PUT, todos ativos, strikes e vencimentos):
```bash
uv run python -m opcoes.cli scrape
```
- Limitar por símbolos ou quantidade:
```bash
uv run python -m opcoes.cli scrape --symbols ABEV3,BBAS3 --max-symbols 20
```
- Definir output, headful, timeout e proxy:
```bash
uv run python -m opcoes.cli scrape --output data/opcoes_latest.csv --headful --goto-timeout 90000 --proxy-server http://proxy:3128 --proxy-username usuario --proxy-password senha
```
- Retomar coleta interrompida (checkpoint automatico):
O scraper agora salva progresso automaticamente e retoma na proxima execucao, sem flag.
Opcional: `--resume-file caminho/para/checkpoint.db`. Por padrao, o scraper cria `<output>.checkpoint.db`.
Regras da retomada:
- O checkpoint so e reaproveitado se `--output` for o mesmo da execucao original.
- A validacao da lista de simbolos na retomada ignora ordem e duplicidades (usa assinatura canonica).
- Se a lista atual mudou parcialmente, o scraper reconcilia simbolos/linhas no checkpoint e continua pelos simbolos restantes, sem reset total.
- Se mudar `--output`, o scraper ignora o checkpoint e inicia do zero.
- Use `--no-resume` para desativar checkpoint nesta execucao.
- Backfill de preços (HV/IV Rank):
```bash
uv run python -m opcoes.cli scrape --backfill-days 120
```
Para desabilitar: `--no-backfill`.

### Fundamentos (enriquecimento no CSV)
- Usando CSV de fundamentos:
```bash
uv run python -m opcoes.cli scrape --fundamentals data/fundamentals.csv
```
O CSV deve ter `ticker` e alguma combinação:
`earnings_yield_ttm` (E/P) ou `pe_ttm` (P/L), ou `lpa_ttm + preco`, ou `lucro_liquido_ttm + acoes_total + preco`.
- Usando Status Invest:
```bash
uv run python -m opcoes.cli scrape --statusinvest
```

### Enriquecer CSV existente
```bash
uv run python -m opcoes.cli enrich --fundamentals data/fundamentals.csv --input data/opcoes_latest.csv
uv run python -m opcoes.cli enrich --statusinvest --input data/opcoes_latest.csv
```
Por padrão sobrescreve o input; para salvar em outro lugar use `--output`.

### Exportar snapshot (para Excel)
```bash
uv run python -m opcoes.cli snapshot export --output data/opcoes_latest.csv
```
Opcional: `--date YYYY-MM-DD`.

### Relatórios
- Relatório diário (ranking, alertas e posições):
```bash
uv run python -m opcoes.cli report
```
Por padrão persiste ranking do dia; use `--no-persist` para pular.

### Posições
- Adicionar posição:
```bash
uv run python -m opcoes.cli position add --ticker B3SAB150 --underlying B3SA3 --qty 100 --price 0.35 --trade-date 2025-01-01
```
- Listar posições:
```bash
uv run python -m opcoes.cli position list
```
- Encerrar posição:
```bash
uv run python -m opcoes.cli position close --id 10 --exit-date 2025-01-20 --price 0.05
```

### Decisões e histórico
```bash
uv run python -m opcoes.cli decision add --ticker B3SAB150 --notes "Entrada por score e liquidez"
uv run python -m opcoes.cli decision list --limit 20
```

### Limpeza de histórico
```bash
uv run python -m opcoes.cli cleanup --retention-days 180 --purge-snapshots
```
Sem `--purge-snapshots`, remove apenas rankings.

### Fundamentus (filtro fundamentalista)
- Coletar snapshot:
```bash
uv run python -m opcoes.cli fundamentus
```
- Aplicar filtros:
```bash
uv run python -m opcoes.cli fundamentus-filter
```
Os parâmetros do filtro podem ser ajustados com as flags do comando.

### DARF / relatório fiscal
```bash
uv run python -m opcoes.cli tax --year 2025 --month 1
uv run python -m opcoes.cli tax --year 2025 --month 1 --mode simulated
uv run python -m opcoes.cli tax --year 2025 --month 1 --mode all
```
`--mode` aceita `real` (default), `simulated` ou `all`.

### Diagnóstico de banco (pré-migração para servidor)
```bash
uv add psycopg[binary]
uv run python -m opcoes.cli db check
```
Esse comando valida variáveis de ambiente, testa host/porta e executa `SELECT 1` no PostgreSQL.
Observação: o `db check` valida conectividade e prontidão do PostgreSQL antes de ativar/expandir o runtime nesse backend.

### Migração SQLite -> PostgreSQL (fase de preparação)
Criar backup de segurança antes de qualquer troca de runtime:
```bash
uv run python -m opcoes.cli db backup --username admin
```
Simular rollback sem sobrescrever nada:
```bash
uv run python -m opcoes.cli db rollback --backup-dir data/backups/sqlite/<pasta_backup> --dry-run
```
Executar rollback real (restaura SQLite):
```bash
uv run python -m opcoes.cli db rollback --backup-dir data/backups/sqlite/<pasta_backup>
```
Dry-run (não grava no PostgreSQL):
```bash
uv run python -m opcoes.cli db migrate --username admin --dry-run
```
Migração efetiva:
```bash
uv run python -m opcoes.cli db migrate --username admin --replace
```
Validar contagens após migração:
```bash
uv run python -m opcoes.cli db verify --username admin
```
Executar checklist completo de cutover (conectividade + contagens + smoke das camadas):
```bash
uv run python -m opcoes.cli db cutover-check --username admin
```
Aplicar índices recomendados no schema PostgreSQL (otimização de performance pós-migração):
```bash
uv run python -m opcoes.cli db optimize --username admin
```
Opções úteis:
- `db backup`: aceita `--backup-root`, `--source-dir`, `--source-main`, `--source-iv`, `--source-flow`, `--no-aux`, `--dry-run`.
- `db rollback`: aceita `--target-dir`, `--no-aux`, `--no-restore-point`, `--dry-run`.
- `db cutover-check`: aceita `--timeout`, `--schema`, `--source-dir`, `--source-main`, `--source-iv`, `--source-flow`, `--no-aux`.
- `db optimize`: aceita `--schema`, `--no-analyze`.
- `--schema nome_schema`: define schema de destino (default: username).
- `--no-aux`: migra apenas `opcoes_snapshots.db` (sem `iv_history.db` e `flow_history.db`).
- `--batch-size 5000`: ajusta tamanho do lote de leitura para o `COPY`.
- `--source-dir` ou `--source-main/--source-iv/--source-flow`: sobrescreve caminhos padrão.

Importante: essa etapa copia os dados para o PostgreSQL. O runtime já suporta fase gradual em PostgreSQL (com fallback para SQLite), ativada por variável de ambiente.

### Runtime gradual (fase 2 em produção)
- As camadas de **Ranking**, **Configurações** (`settings`), **Posições** (`portfolio`), **Financeiro** (`ledger`) e **DARF** já suportam PostgreSQL.
- Fluxos transacionais (ex.: `assign_put`, `callaway`, sincronização de recompra) usam transação no backend ativo.
- Para ativar:
```bash
export OPCOES_DB_BACKEND=postgres
```
- Fallback automático: se houver falha de conexão/query no PostgreSQL, o runtime volta para SQLite sem derrubar o fluxo.
- Em modo web multiusuário, o schema PostgreSQL é derivado do usuário logado.
- A home (`/`) usa cache curto por usuário para reduzir latência de ranking (TTL configurável).

## Web app
Rode:
```bash
uv run python -m opcoes.web
```
Páginas principais:
- Ranking: oportunidades com/sem bid+ask (watchlist).
- Covered Call e Cash-Covered Put: sugestões e lotes.
- Fundamentus: filtros fundamentalistas + ranking didático de PUTs (score, perfil e alerta de execução).
- Posições: P/L e alertas.
- Auditoria: reconciliação de fluxo de caixa vs posições.
- DARF e configurações.

### Acesso multiusuário (login + isolamento por usuário)
- A web agora pode operar em modo multiusuário com login obrigatório.
- No modo SQLite, cada usuário autenticado usa um banco próprio em `data/users/<usuario>/opcoes_snapshots.db`.
- No modo PostgreSQL, cada usuário autenticado usa schema próprio (derivado do login).
- Isso evita mistura de posições, caixa, DARF e configurações entre clientes.

Criar usuário:
```bash
uv run python -m opcoes.cli user create --username seu_usuario
```
Opcionalmente informar senha por argumento:
```bash
uv run python -m opcoes.cli user create --username seu_usuario --password "SuaSenhaForte"
```
Listar usuários:
```bash
uv run python -m opcoes.cli user list
```
Vincular dados legados (single-user) para um usuário:
```bash
uv run python -m opcoes.cli user migrate-legacy --username admin --force
```
Por padrão usa como origem:
- `data/opcoes_snapshots.db`
- `data/iv_history.db`
- `data/flow_history.db`
Ao usar `--force`, se já houver dados no destino o comando cria backup automático antes de sobrescrever.

## Funcionamento do ranking e scores
- Checklist derivado: `Status_Moneyness`, `%_Alta_p_2x`, `Status_2x`, `Status_Liquidez`, `Status_Theta`.
- Scores contínuos (moneyness, liquidez, theta, IV, cenário 2x) formam `score_total`.
- Regras rápidas:
  - Moneyness: 2 pts em `0-5% OTM`, 1 pt em `5-15% OTM`.
  - Liquidez: 2 pts para Alta, 1 pt para Média.
  - Dobro: 2 pts se precisa <= 20% no ativo, 1 pt se 20–40%.
  - Theta: 1 pt se `Theta baixo`.
  - IV Rank: 2 pts entre 10–60; 1 pt em 0–10 ou 60–80.
  - Movimento implícito x 2x: 2 pts se `relacao_em_2x >= 1`, 1 pt se 0,5–1.

## Fundamentus (aba e cálculos)
- Filtros sequenciais: `liquidez_2m`, `div_bruta_patrim`, `cresc_rec_5a`, `div_yield`,
  `roe`, `margem_liquida` (com exceção de 0% opcional).
- Preço teto: `preco_teto = cotacao * (div_yield / target_yield_pct)`.
- Ranking histórico de aprovadas por janela de dias.

## Dados e arquivos
- `data/opcoes_latest.csv`: export atual para planilhas.
- `data/opcoes_snapshots.db`: snapshots, posições, rankings e histórico.
- `data/iv_history.db`: histórico de IV.
- `data/flow_history.db`: histórico de fluxo.
- `data/opcoes_latest.checkpoint.db`: checkpoint transacional da coleta (retomada por símbolo).

## Variáveis de ambiente
- `OPCOES_DB_BACKEND`: backend de dados (`sqlite` padrão, `postgres` para fase gradual das camadas web/CLI).
- `OPCOES_POSTGRES_STRICT`: quando `1`, desativa fallback para SQLite se `OPCOES_DB_BACKEND=postgres` (fail-fast para garantir runtime 100% PostgreSQL).
- `OPCOES_PG_SCHEMA`: schema PostgreSQL padrão quando não houver contexto de usuário web (default: `public`).
- `DATABASE_URL`: string de conexão PostgreSQL (recomendado para `db check`).
- `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, `DB_HOST`, `DB_PORT`: alternativa ao `DATABASE_URL` para `db check`.
- `OPCOES_DB_PATH`: define outro caminho para o SQLite (default: `data/opcoes_snapshots.db`).
- `OPCOES_AUTH_ENABLED`: ativa/desativa login web (`1` por padrão; use `0` para desativar).
- `OPCOES_SECRET_KEY`: chave de sessão Flask (obrigatório definir em produção).
- `OPCOES_AUTH_DB_PATH`: caminho do banco de autenticação (default: `data/auth.db`).
- `OPCOES_USERS_DB_DIR`: diretório raiz dos bancos por usuário (default: `data/users`).
- `OPCOES_ADMIN_USER` e `OPCOES_ADMIN_PASSWORD`: cria usuário inicial no startup da web.
- `OPCOES_ADMIN_REPLACE_PASSWORD`: se `1`, atualiza senha do usuário bootstrap no startup.
- `OPCOES_WEB_DEBUG`: habilita debug local da web (`0` por padrão).
- `OPCOES_SQLITE_TIMEOUT_SECONDS`: tempo de espera em operações SQLite quando houver lock (default: `30`).
- `OPCOES_SESSION_IDLE_MINUTES`: expiração por inatividade da sessão web (default: `15` minutos).
- `OPCOES_SESSION_COOKIE_SECURE`: envia cookie de sessão apenas em HTTPS (`1` recomendado em produção).
- `OPCOES_SESSION_COOKIE_SAMESITE`: política SameSite do cookie (`Lax` por padrão; opções comuns: `Lax`/`Strict`).
- `OPCOES_RANKING_CACHE_SECONDS`: TTL do cache da home/ranking por usuário (default: `45`; use `0` para desativar).

## Testes
```bash
uv sync --dev
RUN_E2E_TESTS=1 uv run pytest tests/test_scraper_e2e.py
```
Sem `RUN_E2E_TESTS`, os testes e2e são ignorados.

## Observações
- A coleta é sequencial (ritmo humano), pensada para execução diária.
- Se o navegador fechar durante o scrape, o coletor tenta reiniciar e continuar no mesmo símbolo.
- Bid/ask podem não estar disponíveis na fonte. Quando ausentes, o app trata como watchlist
  e usa último/preço teórico apenas como referência.
- O CSV mantém unicidade por `ticker` e normaliza números no padrão pt-BR.
- Melhorias recentes:
  - Scraper ganhou fallback automático de navegador: se o binário do Playwright não estiver instalado, tenta abrir com `channel=chrome` (Google Chrome do sistema), reduzindo bloqueio por falha de download de browser.
  - Novo modo estrito de banco: `OPCOES_POSTGRES_STRICT=1` desativa fallback automático para SQLite quando backend ativo for PostgreSQL, garantindo operação somente em Postgres (SQLite fica apenas para rastreio/forense manual).
  - Fluxos `scrape` e `fundamentus` do CLI agora respeitam o backend ativo (`OPCOES_DB_BACKEND=postgres`) para leitura/gravação em PostgreSQL, com fallback automático para SQLite em falhas.
  - Estratégia/tela `Fundamentus` passou a consultar `option_snapshots`, `underlying_snapshots` e `ticker_metadata` no backend ativo (`postgres`/`sqlite`), mantendo isolamento por schema no PostgreSQL.
  - Home/ranking (`/`) passou a usar cache curto por usuário com invalidação automática após ações de escrita (`POST`) nas abas financeiras/posições/DARF/configurações, reduzindo latência em banco remoto.
  - Novo comando `uv run python -m opcoes.cli db optimize` para criar índices recomendados no schema PostgreSQL (`option_snapshots`, `underlying_snapshots`, `positions`, `ledger`) e reduzir latência no runtime web/CLI.
  - Novo comando `uv run python -m opcoes.cli db cutover-check` com validação de prontidão para ativar runtime PostgreSQL (conectividade, consistência de contagens e smoke das camadas `portfolio/finance/darf/settings/report`).
  - Fase gradual ampliada para PostgreSQL nas camadas de `portfolio`, `finance` e `darf`, com fallback automático para SQLite.
  - Transações da camada `db` (`db_transaction`) agora respeitam o backend ativo (`postgres`/`sqlite`) para manter consistência dos fluxos de estratégia.
  - Fase gradual ampliada: módulo de `settings` passou a ler/gravar em PostgreSQL quando `OPCOES_DB_BACKEND=postgres`, com fallback automático para SQLite em falhas.
  - Fase 1 da troca de runtime iniciada: Ranking passou a suportar leitura via PostgreSQL (`OPCOES_DB_BACKEND=postgres`) com fallback automático para SQLite em falhas de conexão/query.
  - Novos comandos `uv run python -m opcoes.cli db backup` e `db rollback` para automação de backup/retorno dos SQLite antes da troca de runtime, com manifesto e `--dry-run`.
  - Novo comando `uv run python -m opcoes.cli db verify` para comparar contagens SQLite x PostgreSQL por tabela e validar integridade pós-migração.
  - Novo comando `uv run python -m opcoes.cli db migrate` para migrar bases SQLite por usuário (incluindo `iv_history`/`flow_history`) para PostgreSQL em schema dedicado, com modo `--dry-run` e cópia em streaming.
  - Novo comando `uv run python -m opcoes.cli db check` para validar prontidão de conexão com PostgreSQL (env + TCP + `SELECT 1`) antes da migração de banco.
  - Runtime agora carrega automaticamente `.env` na inicialização via CLI/Web (`python -m opcoes.cli ...` e `python -m opcoes.web`), sem sobrescrever variáveis já exportadas no shell.
  - Base multiusuário adicionada na web: login/senha, sessão e isolamento de dados por usuário (um SQLite por conta), além de comando CLI para gestão de usuários (`user create`, `user list`).
  - CLI ganhou migração legada por usuário (`user migrate-legacy`) para vincular histórico anterior ao banco isolado de uma conta (com backup automático em sobrescrita).
  - Primeiro acesso de usuário novo agora exibe estado inicial guiado no Ranking (sem erro 500) quando ainda não houver snapshots coletados.
  - Camada de posições/auditoria ficou resiliente para contas novas sem snapshots, evitando erro 500 quando `option_snapshots` ainda não existe no banco do usuário.
  - Isolamento multiusuário validado também nas abas `Configurações`, `Fundamentus`, `Auditoria` e `DARF`, garantindo que cada usuário visualize e altere apenas os próprios dados.
  - Isolamento multiusuário validado na aba `Cash-Covered Put`, incluindo dados da estratégia e persistência dos filtros/configurações por usuário logado.
  - Isolamento multiusuário validado na aba `Covered Call`, incluindo dados, filtro rápido lateral e persistência dos filtros/configurações por usuário logado.
  - Isolamento multiusuário validado na aba `Posições`, incluindo listagem e filtros (`ticker`, `estratégia`, `status`, `simulado`) por usuário logado.
  - Aba `Ranking` agora persiste preferências de filtros por usuário logado (`score`, `limite`, `recorrência`, `recurring_limit`, `underlying`, `tipo CALL/PUT`), mantendo isolamento entre contas.
  - Camadas de `settings`, `portfolio` e `finance` passaram a evitar escrita de schema em leituras (sem `CREATE TABLE` em todo request), reduzindo risco de `sqlite3.OperationalError: database is locked`; gravações mantêm criação automática quando necessário.
  - Sessão web endurecida: login obrigatório em novo navegador/fechamento, expiração por inatividade (sliding session, default 15 min) e renovação automática de atividade sem derrubar usuário ativo.
  - Recalculo de score/IV no scraper aplicado em todos os casos (com e sem preço do ativo).
  - Segmentação de ranking por delta usando `abs(delta)` (corrige classificação de PUTs).
  - Cálculo de prêmio/DARF centralizado e DARF sempre arredondado em centavos.
  - Relatório fiscal (`tax`) agora suporta filtro de modo `real/simulated/all`.
  - Recalculo final do snapshot consolidado para `iv_rank_180d`, `iv_score`, `vol_fluxo_5d` e `score_total` (evita divergência em retomadas/checkpoints).
  - `iv_history.db` e `flow_history.db` agora seguem o mesmo diretório do `OPCOES_DB_PATH`, evitando mistura entre contextos.
  - Retomada do scraper migrada para checkpoint SQLite transacional por símbolo (mais resiliente a quedas e reinícios).
  - Aba `Cash-Covered Put` agora filtra prêmios/movimentações por estratégia (`cash_put`) para não misturar lançamentos de `covered_call`.
  - Aba `Ranking` agora exibe alerta didático automático quando faltar `bid+ask` em massa (ou 100% dos casos), explicando por que o Top pode ficar vazio e os itens irem para Watchlist.
  - Aba `Fundamentus` agora traduz motivos de reprovação para texto didático, mostra alerta de defasagem entre snapshots e prioriza preço conservador em PUT (`best_bid` antes de `ultimo`).
  - Ranking de PUTs na aba `Fundamentus` ganhou score didático (segurança/renda/qualidade/execução), perfil (`Conservadora/Equilibrada/Agressiva`) e novos parâmetros na tela de configurações.
  - Aba `Posições` ganhou novos motivos de encerramento/parcial no dropdown (`Recompra para encerrar`, `Rolagem`, `Exercício`, `Vencimento sem valor`, `Ajuste manual`), mantendo compatibilidade com motivos antigos já salvos.
  - Encerramento manual de opção vendida na aba `Posições` agora sincroniza automaticamente a recompra no `ledger` (tipo `BUY`), sem duplicar lançamento em salvamentos repetidos.
  - Fluxos de prêmio/DARF passaram a validar se o ticker é realmente opção (`infer_option_type`), evitando tratar lote de ação como opção quando houver ticker/ativo divergente por erro de cadastro.
  - Aba `Auditoria` agora mostra também visão de caixa operacional por posição (`Prêmio + DARF + Recompra`), além da visão fiscal, para refletir melhor o efeito real no caixa do cliente.
  - Aba `Covered Call` ganhou visão didática de performance no caixa com cards mensais de `Prêmios líquidos` e `Resultado líquido` (`Prêmio + DARF + Recompra`) para real e simulado.
  - Aba `Covered Call` ganhou filtro lateral rápido por ticker de garantia (ações em estoque e ativos com call em aberto), mantendo a navegação individual por ativo e preservando os filtros ao trocar o alvo.
  - Filtro lateral da `Covered Call` foi reforçado para considerar ações em estoque mesmo quando o campo `Ativo` estiver vazio/divergente; a referência da navegação passou a ser o `Ticker` da ação.
  - Aba `Posições` ganhou a estratégia `Estoque (garantia)` para classificar lotes de ações elegíveis para cobertura de call.
  - Aba `Posições` agora permite editar o campo `Ativo` e o backend passou a persistir essa alteração; quando `Ativo` vier vazio em posição de ação, o sistema auto-preenche com o próprio `Ticker` (incluindo migração automática de registros antigos).
  - Aba `Covered Call` passou a calcular meta didática de venda usando o maior valor entre `preço médio livre` e `spot`, com `% alvo` configurável na tela (default 12%), avaliando oportunidades por `preço efetivo = strike + prêmio de referência`.
  - Aba `Covered Call` ganhou o checkbox `Mostrar só oportunidades que batem meta`; quando marcado, a tabela exibe apenas linhas que realmente atingem a meta e o estado do checkbox fica salvo para a próxima abertura da tela.
  - Coluna `Meta` da `Covered Call` agora mostra também `% do prêmio sobre a base` e `% de folga/defasagem vs meta`, para facilitar leitura de vantagem além do status `Atinge/Não`.
  - Aba `Covered Call` passou a calcular `Extr.% Spot` (e o filtro de extrínseco mínimo) usando a mesma referência de prêmio da linha (`bid`/`último`/`teórico`), evitando divergência entre filtro e preço efetivo exibido.
