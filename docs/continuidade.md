# Continuidade da aplicação

A aplicação acompanha operações de opções da B3, estoque de ações, garantia,
caixa, desempenho e apuração fiscal. Conduza alterações, auditorias e
atualizações da investigação até a validação final. Explique ao investidor, em
cada ação, o que será gravado e qual efeito ele verá. As decisões de manutenção
devem favorecer precisão, rastreabilidade e preservação dos fluxos de cada
estratégia.

## Ao retomar

1. Leia o [estado operacional](estado-operacional.md) e execute `git status --short --branch` e `git log -10 --oneline`. O SHA do checkout, o SHA publicado no GitHub e a versão em produção são verificações distintas.
2. Leia a fonte do assunto no [README](../README.md) e neste índice. Confira código e testes quando um documento descrever um plano ou uma observação antiga.
3. Para uma ação em produção, confira a saúde, a versão e o estado atual do alvo. Antes de gravar dados, compare a fonte com registros e recibos já existentes. A data de um relatório delimita o que ele comprova.
4. Planeje a mudança, preserve o comportamento por estratégia e valide o caminho que o usuário usa. Quando faltar uma evidência que altere o resultado, consulte as fontes disponíveis e peça somente o dado ou a decisão indispensável.
5. Atualize o README quando houver mudança de uso ou comando. Atualize o estado operacional quando houver evidência nova, decisão ou pendência. Para auditorias de um período, mantenha o relatório detalhado e aponte para ele a partir do estado operacional.

## Onde cada dado vive

| Responsabilidade | Fonte para conferir |
| --- | --- |
| Web, sessão e formulários | [`web.py`](../opcoes/web.py), templates Jinja e arquivos estáticos. Gunicorn serve o Flask em produção. |
| Posições e identidade de estratégia | [`portfolio.py`](../opcoes/portfolio.py), [`strategy_contracts.py`](../opcoes/strategy_contracts.py) e `opcoes/strategies/`. `positions` guarda o registro e seu estado. |
| Caixa, estoque e garantia | [`finance.py`](../opcoes/finance.py) registra eventos no `ledger`. [`holdings.py`](../opcoes/holdings.py) mantém o estoque consolidado e seus eventos. Contrato, quantidade, modo e reserva definem o efeito de garantia da estratégia. |
| Auditoria e histórico | [`audit_reconciliation.py`](../opcoes/audit_reconciliation.py) e [`integrity_report.py`](../opcoes/integrity_report.py) reconciliam os registros. `record_history` preserva revisões e `operation_receipts` identifica envios idempotentes nos fluxos que usam recibos. |
| Desempenho, Wheel e fiscal | [`strategy_performance.py`](../opcoes/strategy_performance.py), [`wheel_cycles.py`](../opcoes/wheel_cycles.py), [`tax.py`](../opcoes/tax.py) e [`darf.py`](../opcoes/darf.py). Resultado, provisão, IRRF e pagamento são conceitos distintos. |
| Dados diários | [`scraper/run.py`](../opcoes/scraper/run.py) e [`snapshot_repository.py`](../opcoes/snapshot_repository.py) cuidam dos snapshots de mercado. [`fundamentus.py`](../opcoes/fundamentus.py) mantém a coleta, filtros e integridade da Fundamentus. O CSV é uma exportação do snapshot. |
| Cotações ao vivo | [`edge.py`](../opcoes/edge.py) serve FastAPI REST/WebSocket com o gateway MT5 privado. Confira origem e horário de referência da cotação. O snapshot diário continua disponível nas telas que usam dados ao vivo como apoio. |

O banco operacional é PostgreSQL. O schema de autenticação usa
`OPCOES_AUTH_SCHEMA`. As operações da web usam o schema resolvido para o
usuário autenticado. Para mercado e configurações compartilhadas, a ordem é
`OPCOES_SHARED_SCHEMA`, `OPCOES_AUTOMATION_SCHEMA`, `OPCOES_PG_SCHEMA` e o
fallback definido em [`config.py`](../opcoes/config.py). O histórico de coletas
prioriza `OPCOES_AUTOMATION_SCHEMA`. A CLI resolve seus alvos pelo ambiente,
sem a sessão do navegador. Confirme o ambiente e os schemas antes de executar.

## Contratos das telas

| Tela | O que preservar |
| --- | --- |
| Ranking diário `/` | Oportunidades, apostas racionais, loterias, watchlist, recorrência, perfis e acompanhamento das compras direcionais, em modo real e simulado. |
| Cash-Covered Put `/cash-covered-put` | Caixa operacional, colateral, disponível, oportunidades, recompra e baixa. O exercício gera aquisição e entrada no estoque; a expiração encerra a opção. |
| Covered Call `/covered-call` | Estoque total, reservado e livre por ativo e modo, sugestões, filtros, prêmios, resultado mensal e conferência. O exercício registra venda e baixa de estoque. |
| Fundamentus `/fundamentus` | Referência do snapshot válido, filtros, rankings, setores, alertas, calendário e seleção/exportação das tabelas. Veja o [contrato da interface](plano-ux-fundamentus.md). |
| Posições `/positions` | Registro e consulta por estratégia, grade, resultados e histórico por ID. O estoque consolidado considera todas as posições abertas, mesmo com filtro ativo na grade. |
| Auditoria `/audit` | Conferência entre posição, eventos financeiros, estoque e resultado. Um relatório sem alertas confirma apenas as regras executadas sobre os registros disponíveis. |
| Desempenho `/performance` | Resultados e proveniência por estratégia, provas pendentes e Wheel com vínculos explícitos. Mantenha separados os modos real e simulado. |
| DARF `/darf` | Resultado por competência, compensações, IRRF, geração e pagamento. Antes de fechar um mês, reconcilie o conjunto de operações e a cobertura da apuração. |
| Configurações `/settings` | Parâmetros da aplicação e acompanhamento do ciclo de coleta. O disparo do ciclo é feito pela VPS. |

## Atualização e auditoria

- **Mercado.** O timer da VPS inicia a coleta de segunda a sexta às 02h de Brasília. O ciclo verifica o banco, coleta, exporta o snapshot, atualiza a Fundamentus e aplica retenção de mercado. O watchdog sinaliza falhas ou travamentos. Verifique status, journal, data e cobertura das fontes. Se estiver desatualizado e houver indicação para reprocessar, use o mesmo serviço, conforme o [runbook do README](../README.md#como-validar-se-o-scrape-esta-funcionando). Ele usa o bloqueio do ciclo agendado.
- **Operações do usuário.** O usuário pode cadastrar e atualizar pelas telas autenticadas. Ao cuidar de registros, confira conta, modo, data de pregão, posição, nota ou declaração, custos e eventuais recibos. Use mesmo fluxo e verifique depois os efeitos em posição, caixa, estoque e apuração. Diferencie declaração, comprovação documental e campo pendente. Uma cotação posterior ao negócio precisa de data e fonte próprias.
- **Conciliação.** Compare com as notas e demais fontes do período. Custos compartilhados entram uma vez por nota, sem rateio estimado. Confira capital em garantia, saldo de caixa, prêmio, resultado realizado e apuração no contexto de suas origens. Para inspeção SQL estrita, use acesso somente leitura. Alguns helpers de consulta inicializam estruturas PostgreSQL.
- **Reparos.** Use a prévia versionada, com impacto por registro e evidência da correção. Valide idempotência e rollback com PostgreSQL descartável. A execução em produção segue a autorização e o escopo específicos do reparo. Preserve os originais e a proveniência.
- **Persistência entre conversas.** O timer da VPS executa a coleta automática. Acompanhe a saúde e trate falhas nas tarefas de manutenção. Registre o que foi verificado e o que depende de uma fonte ou acesso futuro. Mantenha senhas, conexões completas, notas de corretagem e dados pessoais fora do Git.

## Validação e publicação

- Use `uv run pytest -q` com ambiente revisado. Para mudanças de tela ou backend que afetem abas, consulte [`test_strategy_contracts.py`](../tests/test_strategy_contracts.py). Para escrita financeira, verifique a transação, o recibo e as projeções afetadas.
- Execute integração com banco descartável, conferindo a conexão e os schemas herdados de mercado e automação. O CI testa com PostgreSQL 16 e Chromium no Ubuntu 24.04. A suíte de coleta E2E com fontes reais é separada. Veja a [especificação do CI](spec-ci-postgresql.md).
- Revise o diff, faça commit e push na `main` e acompanhe o CI do SHA enviado. Quando houver publicação de aplicação, execute `.\deploy\scripts\release.ps1` no PowerShell local, conforme o [README](../README.md#atualizar-a-aplicação). Confira o SHA e a saúde da web e da Edge ao final.

## Histórico técnico e operacional

- [Diagnóstico da operação](diagnostico-funcional-operacao.md), [plano de registros permanentes](plano-registro-permanente.md) e [plano de estabilização](plano-estabilizacao-auditoria.md) explicam a evolução do histórico, recibos e limites de dados legados.
- [Auditoria de setembro](auditoria-setembro-2026.md) e [auditoria de outubro](auditoria-outubro-2026.md) registram fontes, decisões e reconciliações financeiras. Use as seções de execução mais recentes de cada relatório.
- [Manutenção da VPS](manutencao-vps-2026-11-01.md) e [runbook da Edge](edge-vps-runbook.md) registram infraestrutura e validações. Use a configuração efetiva da VPS para conferir portas e serviços.
