# Estado operacional

Última revisão em 24/11/2026. Horários em `America/Sao_Paulo`. Atualize este
arquivo quando houver evidência nova ou uma decisão que mude o próximo passo.

## Verificado nesta retomada

| Área | Evidência |
| --- | --- |
| Repositório | A revisão começou com `main` limpa, em `bf767da`, igual à referência local `origin/main`. O histórico contém auditorias e decisões de implantação que permitem retomar o trabalho. |
| VPS | Consulta por SSH confirmou checkout limpo em `44ce33f`, containers web e Edge em execução, `/login` local HTTP 200 e `/health` local com `status: ok`. |
| Coleta da VPS | O timer disparou às 02h00 e o serviço concluiu com sucesso às 04h24 de 24/11. O journal registrou exportação de `data/opcoes_latest.csv` e snapshot Fundamentus de 24/11 com 280 linhas, 32 aprovadas no filtro. Também houve avisos de cotações ausentes no Yahoo. O próximo disparo constava para 25/11 às 02h00. |
| Dados financeiros | Esta retomada analisou código e relatórios. A última conferência financeira disponível no Git é o fechamento de outubro retomado em 01/11. Consulte a base autenticada e as notas do período antes de registrar novos fatos. |

## Pendências com evidência

| Prioridade | Próximo passo e critério |
| --- | --- |
| 1. Apuração de outubro de 2026 | A [auditoria de outubro](auditoria-outubro-2026.md#validação-e-continuação-necessária) documenta três vendas à vista que ficaram fora da tela DARF. O estoque já foi baixado e o acréscimo de garantia já foi lançado. Planejar evento fiscal da venda com custo declarado identificado, despesa única por nota, prévia e prova de idempotência e rollback. Conciliar IRRF, despesas e completude documental antes do fechamento. |
| 2. Garantia e despesas compartilhadas | Separar garantia em investimentos de dinheiro e representar pendências de despesa por perna. Preservar os lançamentos já conciliados e pedir evidência antes de interpretar depósitos históricos como duplicidade. Veja as decisões da [auditoria de setembro](auditoria-setembro-2026.md#execução-em-05102026--registros-sincronizados-após-autorização) e da auditoria de outubro. |
| 3. Atualização de mercado | O [coletor](../opcoes/scraper/run.py) pode concluir com itens pendentes no checkpoint ou falha na inicialização da persistência. O [ciclo](../deploy/scripts/run_scrape_cycle.sh) marca sucesso pelo código de saída. Planejar status de cobertura parcial e confirmar a persistência da data esperada. Os formulários já cobrem posições e estoque. Para disparar a coleta pela web, ainda é preciso definir quem pode usar a função e reaproveitar o ciclo com bloqueio e acompanhamento. |
| 4. Gravação e migrações | Alguns acessos inicializam schema/tabelas. A CLI `position add/close` ainda usa caminhos legados; na baixa, posição e efeito financeiro são chamadas separadas. Evoluir para migrações explícitas e para as mesmas garantias transacionais dos formulários. Veja [`cli.py`](../opcoes/cli.py), [`portfolio.py`](../opcoes/portfolio.py) e o [plano de estabilização](plano-estabilizacao-auditoria.md). |
| 5. Publicação e recuperação | O `release.ps1` consulta o CI do SHA local no GitHub antes de chamar a VPS. O script remoto busca a ponta de `main` e a comparação do SHA ocorre depois do rebuild. Planejar que a VPS receba e confira o SHA aprovado antes de trocar os containers. Registrar também a prova de restauração do backup em ambiente isolado. |

Para setembro, prevalece a seção de [execução de 05/10](auditoria-setembro-2026.md#execução-em-05102026--registros-sincronizados-após-autorização). Ela confirma a baixa de `KLBNJ196` e a representação das dez execuções das quatro notas conferidas. Use a [continuidade](continuidade.md) para localizar comandos, regras e testes.
