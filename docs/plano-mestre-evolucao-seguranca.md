# Plano mestre de evolução, segurança de dados e funcionalidade

Status: plano proposto para revisão; a execução ainda não está autorizada. Nenhuma
alteração funcional ou migração deste documento deve começar sem autorização e sem
iniciar a respectiva fase.

Data-base da revisão: 2026-09-04.

Este é o plano mestre de evolução da aplicação. O documento
`docs/plano-estabilizacao-auditoria.md` continua sendo o registro das contenções já
realizadas, mas não substitui este plano mais amplo.

## 1. Resultado esperado

A aplicação deve continuar simples para quem hoje usaria uma planilha: o usuário
pode declarar uma operação manualmente, sem anexar nota ou outro comprovante. A
liberdade de entrada não pode, porém, permitir datas inválidas, valores convertidos
silenciosamente para zero, duplicação de lançamentos ou perda do histórico.

Ao terminar este plano:

1. toda ação financeira será atômica: ou todos os seus efeitos são gravados, ou
   nenhum é;
2. valores monetários serão exatos e datas usarão tipos próprios no banco;
3. lançamentos automáticos e movimentos históricos não serão apagados nem
   sobrescritos; correções serão rastreáveis;
4. cada estratégia continuará isolada e com contrato funcional próprio;
5. Web e CLI chamarão os mesmos casos de uso e regras;
6. nenhuma atualização será publicada sem migração verificada, testes PostgreSQL,
   smoke funcional e possibilidade real de restauração;
7. a interface mostrará situação, próxima ação, origem e divergências de forma
   didática, sem exigir que o usuário entenda contabilidade ou arquitetura.

## 2. Decisões de arquitetura

### 2.1 Arquitetura escolhida

Manter um **monólito modular em Flask**, renderizado no servidor, organizado por
responsabilidade e estratégia. Não criar microserviços, SPA/React ou uma reescrita
integral. Esses caminhos aumentariam operação e risco sem resolver a integridade dos
dados.

Fluxo obrigatório:

```text
Página Flask ou CLI
        |
        v
Comando da estratégia + validação tipada
        |
        v
Uma unidade de trabalho / transação PostgreSQL
        |
        +--> movimentos da posição
        +--> lançamentos do ledger
        +--> estoque e reservas
        +--> ciclo Wheel, quando aplicável
        `--> trilha de auditoria

Consultas próprias para as páginas <--- projeções e snapshots de mercado
Coleta externa -----------------------> snapshots compartilhados
```

### 2.2 Organização alvo

```text
opcoes/
  app.py
  shared/
    db.py
    money.py
    dates.py
    errors.py
    audit.py
  finance/
    commands.py
    ledger.py
    darf.py
    tax.py
  portfolio/
    commands.py
    queries.py
    repository.py
  holdings/
  audit/
  performance/
  settings/
  strategies/
    cash_covered_put/
    covered_call/
    ranking/
    fundamentus/
    wheel/
  ingestion/
  edge/
  web/
    auth.py
    common.py
    templates/
    static/
  migrations/
    shared/
    auth/
    tenant/
```

Essa árvore é um destino, não uma mudança única. Arquivos serão extraídos apenas
quando o comportamento atual estiver coberto por testes.

### 2.3 Regras que não podem ser negociadas

- uma declaração manual é uma origem válida; comprovante é opcional;
- dado inválido é rejeitado antes de gravar, nunca corrigido por adivinhação;
- uma estratégia não altera os dados internos de outra estratégia por conveniência;
- `equity_holdings` é o saldo consolidado de ações e
  `equity_holding_events` é seu histórico;
- DARF oficial permanece separada da análise de desempenho e do ciclo Wheel;
- dados reais e simulados nunca se misturam;
- operação automática não é identificada por texto livre da descrição;
- requisição `GET`, filtro ou simples abertura de página nunca altera configuração
  nem dado financeiro; persistência exige `POST` explícito com CSRF;
- nenhuma migração financeira em lote ocorre sem dry-run, relatório, backup e
  reconciliação posterior;
- campos e fluxos legados só são removidos depois de paridade funcional comprovada.

## 3. Invariantes de segurança dos dados

Essas regras devem existir em validação de aplicação, constraints do PostgreSQL e
testes de regressão, sempre que tecnicamente aplicável:

1. posição e movimento de lote possuem quantidade positiva; estoque consolidado
   aceita zero, nunca negativo; evento sem lote segue a constraint do próprio tipo;
2. datas são válidas e seguem a cronologia da operação;
3. fechamento exige motivo e os dados financeiros correspondentes;
4. dinheiro usa `Decimal` no Python e `NUMERIC` no PostgreSQL;
5. cada comando possui chave idempotente e cada lançamento possui identidade única
   dentro desse comando;
6. soma dos lançamentos compõe o saldo mostrado, sem lançamentos órfãos;
7. exercício de PUT produz, na mesma transação, baixa da opção, `ASSIGN` e evento
   `PUT_ASSIGNMENT` no estoque;
8. exercício de CALL produz baixa da opção, `SELL` e `CALL_EXERCISE` no estoque;
9. ações reservadas por Covered Call nunca superam o saldo consolidado;
10. ciclo Wheel aceita somente pernas do mesmo ativo-base, modo e cadeia auditável;
11. resultado realizado do Wheel só aparece depois da saída final das ações;
12. nenhuma requisição de um usuário lê ou grava schema de outro usuário;
13. correção financeira preserva o valor anterior por estorno ou evento corretivo;
14. exclusão física não é oferecida para posição, movimento ou lançamento financeiro;
15. falha em qualquer efeito da operação causa rollback integral.

## 4. Modelo de dados alvo

### 4.1 Migrações versionadas

Criar uma tabela `schema_migrations` e migrações SQL ordenadas para os schemas
compartilhado, autenticação e de cada usuário. Cada migração terá:

- identificador e checksum;
- função de aplicação, verificação e instrução de recuperação;
- lock para impedir duas execuções concorrentes;
- execução transacional quando o PostgreSQL permitir;
- relatório de linhas examinadas, convertidas e rejeitadas;
- compatibilidade temporária com a versão anterior da aplicação.

O runtime deixará de executar `CREATE TABLE`, `ALTER TABLE` e normalizações globais
durante consultas ou gravações comuns. O usuário PostgreSQL da aplicação só perderá
permissões de DDL quando a versão ativa e a imagem certificada para rollback já não
executarem DDL.

### 4.2 Tipos financeiros

- preços, strikes e preços médios: `NUMERIC(18,4)`;
- caixa, taxas, impostos e resultados: `NUMERIC(18,2)`;
- quantidade: inteiro com constraint por tabela/tipo — posição e movimento de lote
  `> 0`, estoque consolidado `>= 0` e despesa/ajuste sem lote aceita zero ou `NULL`;
- datas de negócio: `DATE`;
- instantes técnicos e de auditoria: `TIMESTAMPTZ` em UTC;
- estados e tipos: `CHECK` versionado ou tabelas de domínio, não texto arbitrário.

Antes da conversão será medido o número máximo de casas já existente em cada campo.
`NUMERIC(18,4)` e `NUMERIC(18,2)` são alvos iniciais, não autorização para truncar
histórico. A regra de arredondamento será documentada por cálculo fiscal/financeiro;
não se arredondará resultado intermediário sem necessidade legal ou operacional.

A conversão será feita por colunas paralelas: adicionar, preencher em dry-run,
comparar, passar a escrever nos dois formatos, trocar a leitura e somente depois
remover o legado.

### 4.3 Movimento operacional

Criar `position_movements`, inicialmente sem remover os campos existentes de
`positions`:

- `id`, `position_id` e `operation_group_id`;
- `movement_type`: `OPEN`, `PARTIAL_CLOSE`, `CLOSE`, `EXPIRE`, `ASSIGN`,
  `CALLAWAY`, `ROLL_OUT`, `ROLL_IN` ou `CORRECTION`;
- data, quantidade, preço e taxas daquele movimento;
- modo real/simulado;
- origem manual, snapshot, importação ou sistema;
- identificador de reversão, quando houver;
- usuário, data de criação e observação opcional.

`positions` continuará como uma projeção rápida para as páginas. Esse modelo resolve
várias parciais, taxas de abertura/fechamento, rolagem e histórico sem reescrever a
operação original.

Em movimentos que alteram lote, `quantity` é sempre positiva e `movement_type`
determina entrada ou saída. Movimentos de taxa/ajuste podem não ter quantidade. A
projeção é reconstruída deterministicamente pela ordem dos movimentos; seus campos
financeiros deixam de aceitar edição direta depois da migração.

A projeção também receberá `row_version` para impedir que duas abas abertas
sobrescrevam silenciosamente alterações concorrentes.

### 4.4 Ledger e auditoria

Criar `command_requests`, único por
`(tenant_schema, command_type, idempotency_key)`, com `payload_hash`, status e
resultado. Reutilizar a chave com payload diferente é erro; uma queda depois do
commit e antes da resposta retorna o resultado já persistido.

Criar também `operation_events`, append-only, como identidade comum dos efeitos de
um comando. Ledger, movimentos, eventos de estoque e eventos fiscais referenciam
esse ID. `origin_type/origin_id` podem permanecer para consulta, mas não serão a
única garantia referencial.

Adicionar ao ledger:

- `occurred_on`, `amount_numeric`, `posting_kind`;
- `origin_type`, `origin_id` e `operation_group_id`;
- `command_id`, `operation_event_id` e sequência; a unicidade será
  `(command_id, posting_kind, sequence)`, pois um comando pode gerar vários lançamentos;
- `created_at`, `created_by` e `reversal_of_id`;
- FKs onde a relação é obrigatória e constraints de sinal/tipo.

O motivo pertence ao novo lançamento de estorno (`reversal_reason`), nunca a uma
edição do lançamento original. Quando necessário, usar FKs concretas opcionais como
`position_movement_id`, `holding_event_id` e `darf_payment_id`, além do evento comum.

Criar uma trilha técnica de comandos com `command_id`, ator, operação, alvo,
resultado, instante e `request_id`. O sucesso é confirmado junto da transação
financeira; falhas e rejeições são registradas depois do rollback em log estruturado
ou trilha de segurança independente. Não registrar senhas, cookies, DSN, segredos ou
payload financeiro completo.

### 4.5 Origem e confiança da marcação

O ciclo de vida (`draft`, `active`, `closed`, `archived`) será separado do estado de
conciliação (`declared`, `reconciled`, `divergent`). Toda informação relevante poderá
declarar:

- origem: `manual`, `snapshot`, `import` ou `system`;
- estado: `declared`, `reconciled` ou `divergent`;
- referência e observação opcionais.

Nenhum fluxo exigirá arquivo ou comprovante. A aplicação exigirá apenas os campos
necessários para uma operação coerente e explicará por que cada campo é necessário.

Para campos críticos que podem ter origens diferentes — strike, vencimento, capital
e preço de exercício — usar `data_assertions` por entidade/campo, valor, origem e
estado. Não reduzir várias fontes diferentes a uma única string na posição.

Rascunhos incompletos ficarão em `operation_drafts`, separados de posições, ledger,
estoque e DARF. O rascunho pode usar um payload flexível e versionado, mas somente o
comando **Declarar operação**, depois da validação completa, cria efeitos financeiros.
Assim a conveniência de uma planilha não introduz linhas incompletas nos totais.
Valor sintaticamente inválido sempre é rejeitado; somente campo ausente pode formar
rascunho.

### 4.6 Eventos fiscais e DARF

Criar `tax_events` imutáveis derivados dos movimentos fechados,
`darf_obligations` como projeção mensal e `darf_payments` append-only. Correção de
pagamento gera estorno. No ledger, `TAX_PROVISION` e `TAX_PAYMENT` são conceitos
distintos; DARF fiscal nunca é reconstruída a partir de uma descrição livre.

## 5. Plano de execução por entregas

Cada entrega é pequena, publicável e reversível no código. A entrega seguinte só
começa após o gate da anterior.

### Entrega 0 — linha de base e rede de proteção

Objetivo: saber exatamente o que precisa continuar funcionando antes de mudar a
arquitetura.

Alterações:

- registrar o inventário atual de schemas, tabelas, constraints e volumes de dados;
- gerar fingerprints por agregados seguros ou HMAC com chave externa para posições,
  ledger, estoque, DARF e Wheel; não usar hash simples de valores previsíveis;
- executar toda a suíte com PostgreSQL isolado e corrigir apenas infraestrutura de
  teste que impeça a medição;
- criar CI com PostgreSQL temporário, `pytest`, `git diff --check`, lint incremental
  e verificação de dependências;
- remover os schemas temporários ao final de cada teste e falhar o pipeline se algum
  teste PostgreSQL for pulado;
- usar Python 3.12, mesma versão principal do PostgreSQL da produção, timezone
  `America/Sao_Paulo` e dependências exclusivamente do `uv.lock`;
- construir e iniciar a imagem Docker na CI, guardar relatórios de teste/migração e
  registrar cobertura sem permitir regressão; módulos financeiros terão meta maior;
- criar `release-check.ps1` para reproduzir localmente os gates compatíveis com
  Windows;
- executar E2E do scraper externo em workflow agendado, sem bloquear release por
  instabilidade do fornecedor;
- congelar somente os contratos **atuais** da matriz da seção 6; contratos-alvo novos
  serão ativados no gate da entrega que os implementar;
- adicionar smoke autenticado e E2E Playwright dos casos de uso principais;
- corrigir documentação divergente, especialmente referências restantes a SQLite.

Gate:

- zero falha na suíte completa PostgreSQL;
- nenhuma página ou interface atual da matriz sem teste de contrato;
- relatório de linha de base revisado;
- nenhuma escrita na base financeira real.

Rollback: somente testes e documentação; revertível pelo commit da entrega.

### Entrega 1 — migrações, conexão e recuperação

Objetivo: criar uma base segura para todas as mudanças de schema.

Alterações:

- implementar migrações SQL versionadas e comandos `status`, `plan`, `apply` e
  `verify`;
- centralizar conexão, transação e seleção segura de schema em `opcoes/shared/db.py`;
- inventariar `auth`, compartilhado, padrão, todos os `app_schema` e schemas legados
  ainda não mapeados;
- usar journal global e o mesmo advisory lock na migração e no provisionamento de
  usuário; usuário criado durante migração recebe somente a versão final;
- quando uma mudança não puder ser globalmente transacional, não liberar login ou
  escrita para schema pendente nem fazer o cutover antes de todos estarem verificados;
- usar `SET LOCAL search_path` em cada transação, nomes qualificados para auth/shared,
  `RESET ALL` ao devolver conexão e retirar `CREATE` do schema `public` para runtime;
- introduzir pool pequeno apenas depois de testes reutilizando a mesma conexão entre
  usuários distintos;
- mover gradualmente DDL de runtime para migrações;
- criar backup PostgreSQL a cada 6 horas em formato restaurável, retenção definida e cópia
  criptografada fora da VPS;
- criar backup obrigatório antes de migração e teste periódico de restauração;
- criar usuário de migração separado do usuário de runtime;
- preparar, migrar e verificar um novo schema de usuário antes de atualizar
  `auth.web_users.app_schema`; uma falha de clonagem não pode trocar o ponteiro;

Gate:

- banco vazio sobe somente pelas migrações;
- banco equivalente à produção migra em cópia isolada;
- segunda execução não produz alteração;
- restauração em banco vazio recupera contagens e fingerprints;
- teste concorrente comprova isolamento de schemas.

Rollback: código volta ao SHA anterior; migrações desta entrega são aditivas. Em
erro antes do cutover, fazer rollback transacional. Restore integral só é aceitável
se não houve nova escrita depois do backup. Depois de novas escritas, usar correção
para frente ou recuperação seletiva; nunca restaurar automaticamente nem improvisar
edição direta em produção.

### Entrega 2 — tipos exatos, entradas válidas e comandos atômicos

Objetivo: impedir gravação parcial ou silenciosamente inválida.

Alterações, em duas subetapas:

**2A — tipos exatos:**

- criar colunas `NUMERIC`/`DATE` paralelas, fazer dry-run por registro, dual-write e
  reconciliação por schema;
- mudar a leitura somente depois de contagens e somas baterem com a linha de base;
- não converter texto inválido nem remover colunas antigas nesta entrega;

**2B — validação e comandos:**

- criar tipos `Money`, `BusinessDate`, `Quantity`, `Ticker` e DTOs de formulário;
- remover conversões que transformam erro em `0.0`, `None` ou data de hoje;
- apresentar mensagem clara, preservar os valores digitados e não gravar nada;
- criar comandos compartilhados por Web e CLI para cadastro, prêmio, parcial,
  fechamento, expiração, exercício, rolagem, DARF e estoque;
- aplicar uma única transação e lock das linhas afetadas em cada comando;
- adicionar controle otimista por `row_version`, recusando edição baseada em uma
  versão antiga com instrução para recarregar;
- adicionar chave idempotente por submissão e padrão Post/Redirect/Get;
- transformar exceções silenciosas em erro visível com `request_id` e log seguro;
- preservar os guards específicos de cada estratégia.

Gate:

- falha induzida em qualquer etapa deixa todas as tabelas inalteradas;
- duplo clique ou repetição da requisição não duplica lançamentos;
- data ou valor inválido nunca vira zero nem hoje;
- somatórios financeiros antes/depois permanecem iguais ao centavo;
- Web e CLI produzem exatamente os mesmos efeitos;
- contratos de todas as páginas continuam verdes.

Rollback: manter os serviços antigos atrás de adaptadores até a equivalência; ativar
um comando por vez, nunca trocar todos os fluxos simultaneamente.

### Entrega 3 — ledger imutável e rastreável

Objetivo: tornar o caixa auditável sem impedir marcações manuais.

Alterações:

- adicionar origem, idempotência, grupo operacional e campos de reversão;
- separar visualmente lançamentos manuais e automáticos;
- substituir editar/excluir por corrigir/estornar;
- impedir alteração direta de prêmio, compra, venda, exercício, DARF e realizado
  gerados por comandos;
- permitir novo depósito ou retirada manual, sempre com histórico;
- adicionar FKs/constraints progressivamente e relatório de órfãos antes de ativá-las;
- tornar a conciliação uma verificação contínua e persistir cada execução/finding.

Gate:

- nenhum **novo** lançamento automático sem origem estruturada; histórico inequívoco
  é vinculado e histórico ambíguo vira `legacy_requires_review`, sem inferência;
- nenhum órfão novo;
- estorno + novo lançamento preservam o original e produzem o saldo corrigido esperado;
- usuário runtime não consegue `UPDATE/DELETE` proibido e a reconciliação detecta as
  corrupções semeadas nos cenários cobertos;
- saldo da página coincide com a soma exata do ledger.

Rollback: novas colunas permanecem; a leitura antiga continua disponível durante a
transição. Não remover dados novos para voltar a versão.

### Entrega 4 — movimentos, taxas e rolagem

Objetivo: representar a realidade operacional sem limitar o usuário a uma única
parcial ou uma única taxa.

Alterações em três subentregas:

**4A — estrutura, sem recurso novo:**

- criar `position_movements` e projeção de estado da posição;
- fazer dual-write das operações que o legado já representa;
- criar backfill por posição, sempre com dry-run, relatório e idempotência;
- reconciliar cada posição com ledger, estoque, DARF e ciclos antes de aceitar o
  backfill;

**4B — nova leitura:**

- reconstruir posição, quantidade aberta e resultado exclusivamente pelos movimentos;
- comparar a projeção nova com a legada por pelo menos duas versões publicadas;

**4C — capacidade adicional:**

- liberar múltiplas parciais, fechamento, expiração e exercício por movimentos;
- armazenar taxas em cada movimento, separando abertura de recompra/venda;
- criar `RollOption` ligando fechamento e nova abertura pelo mesmo
  `operation_group_id`;
- retirar campos legados somente em entrega futura de limpeza.

Gate:

- duas ou mais parciais calculam quantidade e resultado corretamente;
- taxas diferentes por evento são preservadas;
- rolagem nunca deixa apenas uma das pernas gravada;
- backfill repetido não duplica movimentos;
- divergência bloqueia somente a posição afetada e gera finding, sem sincronização
  global.

Rollback: em 4A/4B é possível manter a leitura anterior. Depois que 4C liberar várias
parciais ou rolagem, somente uma imagem que já saiba ler movimentos poderá ser usada;
voltar ao legado puro ocultaria dados válidos e fica proibido.

### Entrega 5 — contratos completos das estratégias

Objetivo: consolidar a nova base sem misturar responsabilidades.

Alterações por domínio:

- **Cash-Covered Put:** prêmio, garantia, recompra, expiração, exercício e estoque
  em comandos próprios; capital e caixa real/simulado separados;
- **Covered Call:** reserva de ações, prêmio, recompra, expiração e chamada vinculados
  ao estoque consolidado;
- **Ranking/opções compradas:** compra, venda/parciais, capital em risco e P&L sem
  reutilizar regras de opções vendidas;
- **Fundamentus:** manter aprovadas/reprovadas, mudanças entre snapshots, histórico,
  setores e oportunidades de PUT, sem gravação provocada por filtro de leitura;
- **Wheel:** manter `strategy_cycles` e `strategy_cycle_legs`, ligar movimentos e
  eventos de estoque e impedir dupla contagem;
- **DARF:** consumir `tax_events`, projetar `darf_obligations`, registrar
  `darf_payments`, controlar prejuízo/IRRF e separar obrigação fiscal de provisão e
  pagamento no caixa;
- **Auditoria:** verificar invariantes por posição/estratégia e oferecer filtros e
  explicação de como corrigir, nunca um sync global automático;
- **Desempenho:** usar projeções derivadas, diferenciar resultado conhecido,
  desconhecido, declarado e conciliado; preservar estados históricos `pending` e
  `documents_exhausted` durante a migração para a referência opcional.

Gate:

- matriz de comandos/tabelas esperadas aprovada para cada estratégia;
- cenários real e simulado cobertos;
- Wheel com múltiplas CALLs, recompra, parcial e saída final sem duplicidade;
- resultado da estratégia reconcilia com seus eventos e com DARF, sem reutilizar
  agregados incompatíveis.

Rollback: ativação por estratégia. Uma estratégia pode permanecer na implementação
específica antiga enquanto outra já usa os novos comandos.

### Entrega 6 — páginas modulares e funcionais

Objetivo: melhorar manutenção e experiência sem remover recursos.

Alterações:

- dividir `web.py` em Blueprints por autenticação, responsabilidade e estratégia;
- extrair templates base, componentes, CSS e JavaScript versionados;
- corrigir formulários inseridos diretamente dentro de `<tr>`, usando HTML válido e
  testes reais de submissão no navegador;
- tornar filtros `GET` somente leitura e oferecer **Salvar como padrão** em `POST`
  separado;
- servir Bootstrap/HTMX e assets essenciais localmente, com fallback renderizado no
  servidor para leitura e gravação quando JavaScript falhar;
- mostrar usuário atual e logout na navegação responsiva;
- mover lógica financeira dos handlers para comandos e queries;
- adotar estados padronizados de carregamento, vazio, erro, dado desatualizado e
  sucesso;
- criar painel **Hoje / Precisa de atenção** com vencimentos, divergências, DARF,
  caixa/estoque insuficiente, serviço parado e snapshot antigo;
- disponibilizar inicialmente esse painel em `/attention`, somente leitura, sem
  substituir a home de Ranking durante a transição;
- criar cartão por operação com situação, origem, próxima ação permitida e impacto
  previsto antes da confirmação;
- criar linha do tempo por posição/ciclo e fluxo didático de correção/estorno;
- tratar `draft` como ciclo de vida separado; `declared`, `reconciled` e `divergent`
  descrevem confiança. Rascunho incompleto fica em armazenamento separado e não
  entra em caixa, estoque, DARF ou desempenho;
- retirar exigência de nota/fonte para marcação manual, preservando-a como referência
  opcional, sem apagar o histórico dos estados documentais antigos;
- manter filtros, posição da tela e valores digitados após erro;
- fornecer URL/formulário completo para toda ação hoje acessível apenas por modal;
- validar como meta WCAG 2.2 AA: uma `<h1>`, `<main>`, pular conteúdo, `label/for`,
  erro associado, `aria-invalid`, foco visível, região viva para partials,
  `aria-current`, informação não dependente de cor, teclado, 320 px e zoom de 200%;
- preservar server-side rendering e carregamento progressivo existente.

Ordem da extração: layout/autenticação, Fundamentus como piloto somente leitura,
Ranking, Cash-Covered Put, Covered Call, Posições, DARF/Auditoria,
Desempenho/Wheel e Configurações. Cada partial acessado sem `HX-Request` retorna ou
redireciona para uma página completa, nunca um fragmento sem navegação.

Gate:

- todos os blocos da matriz funcional aparecem e operam;
- nenhuma rota muda sem redirecionamento/teste de compatibilidade;
- erros não resultam em tela branca ou redirecionamento silencioso;
- formulários funcionam com teclado e em largura móvel;
- nenhum JavaScript é necessário para preservar a gravação financeira básica;
- E2E Playwright cobre desktop e celular, falhando em erro JavaScript, HTTP 500 ou
  navegação quebrada, e inclui execução com JavaScript desativado e CDN bloqueada;
- acessibilidade possui verificação automática e inspeção manual por teclado.

Rollback: migrar um Blueprint e uma página por vez; manter rota e template anteriores
até o teste de contrato demonstrar paridade.

### Entrega 7 — consultas, cache e coleta externa

Objetivo: melhorar velocidade sem arriscar consistência.

Alterações:

- criar query services/read models para cada página e eliminar consultas repetidas;
- paginar ledger, auditoria, histórico e posições fechadas;
- impedir que leitura de posição abra conexões paralelas ou consulte internet;
- mover yfinance e demais fontes exclusivamente para o pipeline de ingestão;
- mostrar fonte e idade do snapshot usado;
- remover cache L1 financeiro por worker ou usar geração compartilhada conferida em
  toda leitura;
- versionar chaves de cache por snapshot e `user_data_version`; incrementar a versão
  do usuário na mesma transação de qualquer gravação e invalidar por evento de domínio;
- medir tempo e número de queries das rotas críticas antes/depois.

Gate:

- gravação fica visível em qualquer worker imediatamente;
- indisponibilidade da fonte externa não derruba as páginas;
- nenhuma página faz chamada de rede externa durante a requisição;
- isolamento de schema permanece comprovado com pool;
- limites de desempenho definidos na linha de base são atendidos.

Rollback: desabilitar pool/cache/read model por configuração segura e voltar à query
anterior, sem alterar o dado persistido.

### Entrega 8 — segurança operacional, observabilidade e deploy

Objetivo: detectar falhas cedo e recuperar a aplicação sem improviso.

Alterações:

- revisar confiança em proxy, rate limit, cookies, sessão, CSRF e primeiro acesso;
- separar papéis de usuário comum, administrador operacional e integração; reparos,
  usuários, configurações e ordens exigem autorização própria;
- manter envio de ordens da Edge desligado por padrão e separar escopos de token para
  `quotes:read`, `orders:preview` e `orders:send`; token de leitura nunca envia ordem;
- comparar tokens em tempo constante, exigir confirmação específica para envio real
  e registrar a tentativa em trilha append-only;
- guardar tokens da Edge somente como digest, com criação, escopos, revogação e último
  uso; aplicar rate limit próprio a preview/envio;
- validar força dos segredos no startup, definir `TRUSTED_HOSTS`, quantidade de proxies
  confiáveis, bind em loopback, timeout absoluto de sessão e rotação documentada;
- aplicar headers/CSP sem `unsafe-inline` depois de extrair assets;
- registrar logs estruturados com `request_id`, `command_id`, estratégia, alvo e
  resultado, sem informações secretas;
- criar healthcheck de processo, readiness de banco/schema e verificação de versão;
- separar `/health` sem dependências, `/ready` com banco/schema/configuração e
  readiness próprio da Edge/gateway, sem expor detalhes internos;
- monitorar idade do backup, espaço, última coleta, jobs travados, banco, erros 5xx e
  sincronização NTP; definir destino e responsável por cada alerta;
- adicionar healthchecks ao Compose;
- adicionar `no-new-privileges`, limites cautelosos e rotação de logs aos containers;
- fixar versão do `uv` e a imagem-base por digest, gerar SBOM e auditar dependências;
- gerar uma única imagem na CI, publicar por digest/SHA e implantar exatamente esse
  artefato; preservar ao menos duas imagens anteriores;
- impedir deploy concorrente com `flock` e usar `trap` para restaurar o container
  anterior se o script morrer depois da parada;
- executar preflight de migração/backup antes da troca de containers;
- implementar rollback automático do container quando smoke falhar; migração de banco
  segue estratégia expand/contract e não recebe downgrade destrutivo automático;
- ampliar smoke pós-deploy para login, health, schema version, comando de leitura e
  páginas críticas usando usuário sintético sem permissão de mutação; nenhuma operação
  financeira real faz parte do smoke de produção;
- validar Caddy/certificado e registrar `OLD_SHA`, `NEW_SHA`, imagem, migrações,
  início, fim e motivo de eventual rollback;
- adotar inicialmente troca simples com breve indisponibilidade e rollback por imagem,
  em vez de blue/green; é suficiente para um operador e reduz complexidade;
- só podar imagens depois do período de observação, nunca logo após o primeiro smoke;
- realizar exercício documentado de recuperação da VPS.

Gate:

- smoke falho restaura a versão anterior da aplicação;
- backup recente e restauração comprovada são condições de migração;
- versão exibida corresponde ao commit publicado;
- logs permitem localizar uma operação pelo identificador sem expor segredos;
- token de leitura recebe `403` em ordem e trading desligado bloqueia inclusive token
  privilegiado;
- runbook executado do zero em ambiente isolado.

Rollback: imagem anterior preservada e comando versionado. Falha exige investigação;
não usar permissões, ownership, `safe.directory` ou edição manual como atalho.

### Entrega 9 — remoção controlada do legado

Objetivo: reduzir complexidade somente depois de a arquitetura nova estar comprovada.

Alterações:

- remover `_DbConn` duplicados e compatibilidade SQLite residual;
- remover DDL e normalizações de runtime remanescentes;
- revogar definitivamente `CREATE`, `ALTER`, `DROP` e `TRUNCATE` do papel de runtime,
  depois de comprovar que a imagem ativa e a de rollback não dependem deles;
- parar o dual-write apenas após período de comparação sem divergências;
- remover campos legados de parcial, fechamento, taxa e datas em migração separada;
- eliminar handlers/templates antigos somente depois de testes de paridade;
- atualizar README, documentação técnica e runbooks para o estado final.

Gate:

- duas versões publicadas consecutivas sem divergência entre legado e projeção nova;
- zero leitura/escrita registrada nos campos antigos;
- backup e restauração final testados;
- suíte, auditoria, páginas e smoke pós-deploy verdes.

Rollback: esta é a única fase destrutiva. Exige backup restaurado em ensaio, janela de
manutenção e autorização específica antes de cada remoção.

## 6. Matriz funcional obrigatória das páginas

Esses elementos não podem desaparecer durante refatoração. A coluna central é o
contrato atual congelado na Entrega 0; a coluna final é contrato-alvo, ativado apenas
quando a entrega correspondente existir. Os testes verificam conteúdo, comportamento
e efeitos no banco, não apenas resposta HTTP 200.

| Página | Funcionalidade que deve permanecer | Evolução prevista |
|---|---|---|
| Login/primeiro acesso | convite, senha temporária, troca de senha, sessão e logout | mensagens seguras, rate limit e auditoria de acesso |
| Ranking | oportunidades, segmentos, watchlist, recorrência, posições reais/simuladas e P&L de opções compradas | idade/fonte do snapshot e ação segura para cadastrar operação |
| Covered Call | cadastro/ajuste de estoque real/simulado, cobertura livre/reservada, sugestões, prêmio, resultado, alertas, recompra, expiração e exercício | cartão da operação, impacto previsto e linha do tempo |
| Cash-Covered Put | caixa, depósitos, retiradas, histórico/correção manual, garantia, oportunidades, posições, prêmio, resultado, alertas, recompra, expiração e exercício | disponibilidade após operação, origem manual e divergências acionáveis |
| Fundamentus | filtros, aprovadas/reprovadas, alterações entre snapshots, ranking histórico, oportunidades de PUT e setores | leitura somente de snapshots e estado de atualização |
| DARF | apuração mensal, prejuízo, IRRF, geração, pagamento e detalhes | conciliação por eventos fiscais e estorno auditável |
| Posições | nova marcação, abertas/fechadas, filtros, estoque consolidado, registro/recálculo de prêmio, realizado bruto/taxas/líquido, edição permitida e encaminhamento de ações protegidas | múltiplos movimentos, rolagem e linha do tempo |
| Auditoria | modos real/simulado/todos, inclusão de fechadas, caixa separado de resultado, alertas por regra, estoque, exercícios e órfãos | findings persistentes, severidade, responsável e instrução de correção |
| Desempenho | estratégias separadas, correção de contrato, garantia histórica, vínculo da venda, custos compartilhados, criação de ciclo/pernas Wheel e reabertura de conferência | origem/confiança por dado e projeções por eventos |
| Configurações | taxas, padrões por estratégia, automação, histórico de serviço e próxima execução | saúde, versão, backup recente e alertas operacionais |
| Central de atenção | nova página inicialmente somente leitura | prioridade, motivo, prazo, entidade, modo, próxima ação e distinção entre visto/resolvido, sem mutação automática |
| API Edge | cotações, métricas, preview e envio de ordem conforme habilitação | escopos separados, trading desligado por padrão e auditoria |

Para cada página devem existir testes de:

- carregamento com dados, sem dados e com dado divergente;
- modo real e simulado quando aplicável;
- erro de validação sem perder o formulário;
- autorização e isolamento entre usuários;
- operação repetida/idempotente;
- renderização móvel mínima;
- contrato dos blocos essenciais e dos botões próprios da estratégia;
- funcionamento sem CDN e degradação segura quando HTMX/JavaScript falhar.

Endpoints auxiliares também fazem parte do contrato:

- `/partial/ranking`;
- `/covered-call/partial/live` e `/covered-call/partial/audit`;
- `/fundamentus/partial/dashboard`;
- `/positions/partial/live`;
- `/live-market/bootstrap`.

Sem `HX-Request`, um endpoint partial retorna/redireciona para página completa. A
linha de base também congela a CLI: nomes, opções, códigos de saída e efeitos de
`position`, `scrape`, `report`, `snapshot`, `fundamentus`, `tax`, `user`,
`service-run`, `db` e `repair`. A Edge congela `/health`, cotações, busca, métricas,
preview, ordens, token e WebSocket antes da introdução de escopos.

## 7. Plano de testes

### 7.1 Pirâmide obrigatória

1. **Unitários:** dinheiro, datas, quantidades, cálculos, transições e guards.
2. **Integração PostgreSQL:** comandos e queries contra schema real temporário.
3. **Contrato por estratégia:** blocos da página e ações disponíveis.
4. **Migração:** banco vazio, cópia equivalente à produção, repetição e dados inválidos.
5. **Concorrência:** duplo clique, duas sessões, locks e idempotência.
6. **Segurança:** CSRF, autenticação, proxy, sessão e isolamento de schemas.
7. **Backup/restauração:** restaurar e comparar contagens/fingerprints.
8. **Performance:** queries, latência e cache multiworker.
9. **Smoke de release:** comandos e páginas críticas depois do deploy.
10. **E2E da aplicação:** login, navegação e mutações críticas em Chromium, desktop
    e celular, usando apenas banco efêmero.

### 7.2 Cenários financeiros mínimos

- Cash-Covered Put expirada, recomprada, parcial e exercida com taxas;
- Covered Call expirada, recomprada, parcial e exercida com baixa do estoque;
- opção comprada com compra, parcial, venda e prejuízo;
- várias operações no mesmo ativo e mês;
- múltiplas CALLs no mesmo ciclo Wheel;
- rolagem real e simulada;
- DARF com lucro, prejuízo compensado, IRRF, pagamento e estorno;
- declaração manual sem comprovante, com e sem observação;
- dados inválidos, duplicados, fora de ordem e de outro usuário;
- falha simulada após cada gravação intermediária para comprovar rollback.

### 7.3 Gate único para cada publicação

Para cada publicação de uma fase:

1. revisar `git status` e diff;
2. executar localmente `release-check.ps1`, testes focados e suíte completa PostgreSQL;
3. executar verificação de migração e reconciliação em cópia isolada;
4. conferir `git diff --check` e verificações estáticas;
5. atualizar README, plano e runbook correspondente;
6. criar commit pequeno e rastreável e fazer push na `main`;
7. aguardar a CI verde para exatamente o mesmo SHA;
8. atualizar a VPS somente com o script oficial;
9. validar containers, login, edge health, versão, schema e smoke funcional somente
   leitura com usuário sintético; mutações rodam apenas em CI/staging efêmero;
10. comparar fingerprints e confirmar ausência de novos findings.

## 8. Backup, restauração e retenção

- backup lógico completo a cada 6 horas em formato custom do PostgreSQL;
- uma execução por dia forma o ponto diário de retenção; manter 7 diários,
  5 semanais e 12 mensais;
- cópia criptografada, versionada/protegida contra exclusão fora da VPS; o provedor
  será escolhido antes da Entrega 1;
- permissões restritas e segredos fora do repositório;
- backup adicional antes de qualquer migração financeira;
- incluir schemas de auth/shared/usuários, roles/globals, extensões, versão do
  PostgreSQL e arquivos persistentes necessários;
- guardar configuração de Caddy, systemd e ambiente por procedimento separado e
  seguro, sem juntar segredos ao dump;
- manter a chave de criptografia fora da VPS e testá-la no exercício de recuperação;
- teste automático de validade e restauração técnica semanal em banco isolado;
- exercício completo mensal de desastre, incluindo aplicação, proxy, configuração,
  login e páginas, medindo o RTO;
- relatório com horário, duração, tamanho, checksum e resultado do restore;
- dados do usuário, ledger, posições, estoque, DARF, Wheel e auditoria não entram na
  retenção agressiva aplicada a snapshots de mercado.

Um backup que nunca foi restaurado não conta como proteção comprovada.

Restore integral nunca é reação automática a falha de deploy. Se houve gravação após
o ponto restaurável, aplicar correção para frente ou recuperação seletiva para não
apagar operações novas.

Objetivos iniciais: perda máxima de até 6 horas de dados (`RPO`) e recuperação em até
2 horas (`RTO`). Se esses limites não forem suficientes, avaliar WAL/PITR antes de
prometer uma janela menor.

## 9. Observabilidade e tratamento de erro

- não usar `except Exception` com redirecionamento silencioso;
- traduzir erro conhecido para mensagem clara e registrar causa técnica;
- retornar identificador de suporte ao usuário sem stack trace ou segredo;
- medir comandos concluídos, rejeitados, duplicados e revertidos;
- alertar quando auditoria piorar, backup atrasar, espaço ficar baixo, coleta parar ou
  healthcheck falhar;
- propagar `request_id` entre Web, Edge e gateway e registrar versão Git/horário do
  deploy; evitar ticker/posição como label de métrica de alta cardinalidade;
- definir ciclo de findings: aberto, reconhecido, resolvido e reaberto;
- definir SLO inicial de disponibilidade, p95 das rotas críticas e taxa de 5xx, com
  retenção/rotação de logs da aplicação, Docker e journald;
- painel de saúde deve ser informativo, mas não expor DSN, paths sensíveis ou tokens.

## 10. Riscos e contenções

| Risco | Contenção obrigatória |
|---|---|
| Migração monetária alterar centavos | colunas paralelas, `Decimal`, relatório por linha e reconciliação de totais |
| Backfill inventar histórico | bloquear linha divergente e exigir declaração; nunca adivinhar |
| Refatoração apagar função de estratégia | contratos da seção 6 e migração uma página por vez |
| Pool vazar schema de usuário | configuração/reset a cada checkout e teste concorrente |
| Cache mostrar saldo antigo | sem L1 financeiro local ou geração compartilhada obrigatória |
| Deploy saudável no HTTP, mas inválido no domínio | mutações em staging efêmero e smoke somente leitura/auditoria em produção |
| Downgrade quebrar schema novo | expand/contract e aplicação anterior compatível durante a janela |
| Backup existir, mas não restaurar | restore técnico semanal e exercício completo mensal |
| Restore apagar operações posteriores | nunca restaurar integralmente após novas escritas; correção para frente ou recuperação seletiva |
| Recurso novo tornar rollback legado inválido | imagem de rollback precisa compreender o schema e os movimentos já liberados |
| Plano se transformar em reescrita longa | entregas pequenas, ativação por comando/estratégia e gate em cada fase |

## 11. Definição de pronto

Uma entrega somente está concluída quando:

- código, migração, testes e documentação fazem parte do mesmo commit lógico;
- todos os testes PostgreSQL e contratos funcionais aplicáveis estão verdes;
- nenhum dado é inferido sem regra ou evidência declarada;
- caminho de erro e rollback foi exercitado;
- página correspondente continua utilizável e didática;
- auditoria não apresenta nova divergência;
- deploy e smoke confirmam exatamente o commit publicado;
- não existe tarefa necessária escondida em comentário ou operação manual não
  documentada.

## 12. Ordem imediata recomendada

Não iniciar pela reorganização visual. A sequência inicial deve ser:

1. Entrega 0: CI PostgreSQL e matriz funcional completa;
2. Entrega 1: migrações/backup/restore;
3. Entrega 2: tipos exatos, validação estrita, transações e idempotência;
4. Entrega 3: ledger rastreável;
5. Entrega 4: movimentos e taxas.

Depois dessas cinco entregas, a modularização e a nova experiência visual poderão
usar uma base confiável. A execução deve ocorrer uma entrega por vez, com revisão do
plano e autorização antes de qualquer migração ou alteração financeira.
