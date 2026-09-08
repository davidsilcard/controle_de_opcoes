# Guia de manutenção e continuidade

Este é o ponto de partida técnico para manter esta aplicação, inclusive em novos
chats. `AGENTS.md` exige sua leitura. Atualize este guia junto da mudança quando uma
prática durável mudar; não dependa de uma explicação que existe apenas na conversa.

## 1. Onde está a verdade

- Instruções atuais do usuário e `AGENTS.md`: escopo, autorização e forma de trabalho.
- [Plano mestre](plano-mestre-evolucao-seguranca.md): arquitetura aprovada, sequência,
  critérios de aceite e registro de continuidade com pendências e evidências.
- [Contrato funcional](contrato-funcional-atual.md): funções que cada estratégia deve
  preservar. O plano futuro não significa que essas funções já foram migradas.
- Código, testes e verificações atuais: comportamento efetivo. Se divergirem do
  contrato, investigue e registre a decisão; não escolha silenciosamente um lado.
- [README](../README.md): instalação, comandos oficiais e melhorias disponíveis.
- Memória do assistente: índice para esses arquivos, não substituto deles. Commits,
  resultados de testes, saúde da VPS e configuração operacional devem ser revalidados.

Não existe garantia de que todo assistente lerá uma memória externa. A continuidade
reproduzível está nos arquivos versionados, com decisões e testes verificáveis.
Não salve segredos, extratos ou dados pessoais na memória, documentação ou logs.

## 2. Produto e arquitetura

- O produto é um controle declaratório, mais claro que uma planilha. Cadastro manual
  não exige comprovante. Exigir coerência de valores, datas, modo e estratégia é
  diferente de exigir prova documental.
- Uma correção histórica não pode inventar preço, data, exercício, taxa ou vínculo.
  Quando faltar informação, preserve a incerteza e peça a declaração/evidência
  necessária. Não rateie custos compartilhados sem base individual.
- Manter monólito modular Flask + PostgreSQL, organizado por responsabilidade e
  estratégia. A modularização é incremental; não introduzir microserviços, novo
  frontend ou reescrita geral como atalho para resolver integridade.
- Cada aba tem contrato próprio. Shell, partial, cache ou componente comum não podem
  apagar funções de uma estratégia. Remover legado só com paridade comprovada;
  implementação específica temporária é aceitável.
- Web e CLI devem convergir para os mesmos casos de uso. Centralizar regras em
  serviços transacionais, sem mover toda a lógica de uma vez.
- Não tratar sugestões de mercado como operações realizadas. Real e simulado,
  assim como schemas de usuários distintos, continuam isolados em toda camada.

## 3. Semântica financeira que não pode se perder

- `equity_holdings` é o estoque consolidado usado na cobertura; não é histórico de
  compras nem substituto do `ledger`. Alterar estoque não autoriza alterar caixa.
- Ciclos Wheel usam `strategy_cycles` e `strategy_cycle_legs`. Não reconstruir ciclo
  complexo apenas por `parent_position_id` nem somar agregados independentes de PUT e
  CALL se o preço médio das ações já absorveu prêmios. DARF é separada.
- Em `portfolio._row_to_dict`, `realized_pl` é o resultado bruto realizado;
  `pl` combina realizado e aberto e desconta taxas. Só para posição totalmente
  encerrada corresponde ao líquido final. Não descontar a taxa duas vezes.
- Strike original, strike ajustado e strike de exercício são fatos distintos.
- Cadastro de Aposta/Ranking aceita somente opções compradas; a grade genérica não pode alterar a identidade
  de uma estratégia protegida. Taxas, notas e fechamento permitido são outra coisa.
  Consulte `strategy_contracts.py` e o guard da estratégia antes de mudar testes.
- Dinheiro exato com `Decimal`/`NUMERIC` é objetivo do plano, não uma garantia do
  código legado. Não converter tudo em lote sem migração e reconciliação verificadas.

## 4. Como executar uma mudança

1. Verifique Git e leia o registro de continuidade. Separe trabalho já feito,
   pendências e fatos ainda não verificados; não reinicie o plano em cada chat.
2. Defina um recorte pequeno: problema, regra preservada, arquivos, testes e critério
   de aceite. Auditar/explicar não autoriza escrita externa ou reparo histórico.
3. Para mutação financeira, use uma única transação e propague a mesma conexão a
   todas as escritas. Releia/bloqueie o registro na transação antes de decidir.
   Não deixe helpers fazerem commit próprio ou DDL com commit no meio do fluxo.
4. Teste sucesso, rejeição, repetição, rollback após escrita parcial e isolamento.
   Use concorrência real quando o risco envolver dois comandos sobre o mesmo estado.
5. Reparos de dados são comandos versionados, escopo identificado, dry-run por padrão,
   validação antes/depois e aplicação explícita. Nunca SQL improvisado ou sync global.
6. Revise o diff, documente a mudança, rode os testes e faça commit/push em `main`,
   conforme preferência do usuário. Não inclua alterações alheias ou segredos.
7. Atualize o registro de continuidade com resultado real, pendências e próximo passo.

Não usar `except Exception` para fingir sucesso. Falhas conhecidas devem ter aviso
didático; falhas inesperadas devem reverter a transação, ser registradas sem segredos
e não expor detalhes internos ao usuário.

## 5. Testes: o que conta como evidência

- PostgreSQL de testes deve ser descartável e separado da produção. Nunca rodar
  `pytest` apontando para o banco financeiro da VPS, mesmo usando schemas aleatórios.
- A CI provisiona PostgreSQL 16. A fixture prepara schemas aleatórios para aplicação
  e autenticação, isola também configuração compartilhada/automação e limpa somente
  nomes validados. Não depender da ordem dos testes para inicializar o banco.
- Uma suíte local com `requires_postgres` ignorados não comprova fluxos financeiros.
  Informe separadamente aprovados, falhas e ignorados. CI vermelha bloqueia deploy.
- Consulte relatório JUnit/artefato e anotações da CI. Não remover asserts, ignorar
  testes ou enfraquecer guards para obter verde. Se a fixture contrariar um contrato
  confirmado, ajuste-a e teste também a rejeição que protege o contrato.
- HTTP 302 não comprova gravação: confira estado persistido e efeitos financeiros.
  HTML 200/smoke de login não comprova uma estratégia funcional nem isolamento.
- Testes de presença de texto/código complementam, mas não substituem testes de
  comportamento. Testes em `app.testing=True` não comprovam autenticação/CSRF.
- `GET /` é o shell do Ranking; `/partial/ranking` calcula seu conteúdo. Ao testar
  cache, observe a camada realmente utilizada e preserve invalidação e isolamento.

Comandos e gates completos estão na seção Testes do README. No Windows, se o cache
do `uv` bloquear a execução, use `.venv\Scripts\python.exe` sem alterar permissões
globais. Bash de Git para Windows pode validar sintaxe quando o WSL não está instalado.

## 6. Publicação e proteção de dados

- Fluxo oficial: revisar/testar, commit/push `main`, confirmar CI verde para o SHA e
  então executar somente:

  ```bash
  cd /home/david/apps/controle_de_opcoes && bash deploy/scripts/update-vps.sh
  ```

- Antes do deploy, verificar checkout/usuário operacional da VPS e alterações locais.
  Não forçar com `safe.directory`, `chmod`, `chown`, reset ou outro worktree. Se houver
  bloqueio, investigar a causa e pedir a decisão necessária.
  Não inferir o operador apenas pelo dono de `.git`: divergência entre checkout,
  script e lock exige decisão explícita, não troca automática para `root`.
- Configuração oficial da VPS: `/etc/controle_de_opcoes/app.env`, carregada pelo helper
  `deploy/scripts/opcoes-compose-vps.sh`. Não criar outra fonte de segredos nem imprimir
  variáveis/`docker inspect` completo. Verificar presença sem mostrar o valor.
- O `ProxyFix` atual confia em um proxy. Preservar backend inacessível externamente
  e cabeçalhos saneados pelo proxy; um teste que chama Flask diretamente não testa
  essa proteção de borda. Revalidar a topologia antes de alterar essa confiança.
- Acompanhar o processo até obter código de saída. Guardar identificador da sessão e
  continuar lendo a mesma execução. Saída silenciosa ou build lento de Chromium não
  prova travamento. Não iniciar outro deploy para tentar obter mais saída; o script
  também usa lock para recusar concorrência.
- Após concluir, conferir `opcoes-web`, `opcoes-edge`, `/login`, `/health` do Edge e
  correspondência do código publicado. Se não houver credenciais para smoke
  autenticado, declarar essa limitação; não dizer que todas as páginas foram validadas.
- Inventário HMAC de estrutura/contagens não é backup, não reconcilia valores
  financeiros e não detecta alteração de valor mantendo a contagem. Não prometer
  snapshot consistente sem isolamento de leitura adequado.
- Chave HMAC, cópia de backup e teste de restauração precisam de proteção independente
  da VPS. Uma chave guardada na própria máquina não atende proteção fora dela.
- Migração, restore e correção histórica exigem o gate e a autorização específicos do
  plano. Não restaurar banco inteiro sobre operações novas sem plano de recuperação.

## 7. Encerramento de cada entrega

Registrar no plano: data, escopo, decisão e motivo, referência ao código/testes, CI e
deploy verificados (ou não executados), pendências e próximo recorte. README recebe
comandos e melhorias; este guia recebe apenas práticas reutilizáveis.

O resumo ao usuário deve explicar o que mudou, o que foi efetivamente validado e o
que ainda falta. Não declarar a aplicação segura por completo com base em um lote de
correções. Se faltar contexto, consultar arquivos/ferramentas antes de corrigir e
perguntar quando a decisão não puder ser inferida com segurança.

Agentes paralelos podem revisar áreas independentes, com arquivos e escopo definidos;
o responsável integra e valida o conjunto. Skills/plugins não entram no repositório
por padrão: sugerir apenas quando houver fluxo recorrente e benefício concreto.
