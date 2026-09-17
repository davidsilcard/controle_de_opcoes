# Diagnóstico funcional — operação e registros financeiros

Data da linha de base: 2026-09-17.  Este documento separa a confiabilidade
da aplicação publicada da investigação dos dados já existentes. Não autoriza
reparo financeiro, migração de histórico nem exclusão.

## Resultado da inspeção somente leitura

O PostgreSQL da produção respondeu ao `db check`. A leitura feita pela própria
aplicação encontrou:

| Item | Resultado |
| --- | --- |
| posições visíveis | 50 |
| posições abertas / fechadas | 19 / 31 |
| estratégias | 10 Cash-Covered Put, 19 Covered Call, 14 estoque, 7 Ranking |
| eventos de estoque | 19 |
| lançamentos sem posição | 0 |
| relatório de integridade | 0 achados |
| DARF sem rateio individual verificável | 8 |

Os gatilhos de histórico estão ativos para `positions` e `ledger`, e o
histórico é imutável. A tabela de recibos idempotentes também existe. Ambos
ainda estão sem linhas, o que é coerente com operações anteriores à instalação,
mas não explica o passado.

### Limite da evidência histórica

Não há posição anulada na tabela atual. Também não existem os IDs `1–3`,
`10–23` e `50`, nem revisões em `record_history` que expliquem essas lacunas.
Uma lacuna de ID pode decorrer de importação antiga, transação revertida ou
remoção anterior à trilha de auditoria. Portanto, **não se deve concluir que
houve exclusão nem recriar esses registros por estimativa**. A única fonte que
pode decidir isso é um backup/exportação datada ou uma nota correspondente.

O relatório de integridade não detecta essa classe de problema porque ele
reconcilia os registros que ainda existem; ele não consegue reconstruir uma
linha apagada antes de haver histórico.

## Fases seguintes

### Fase A — prova de registro novo (próxima, sem tocar nos dados reais)

Executar no PostgreSQL descartável do CI um teste completo de formulário para
cada operação que grava: venda/compra de opção, movimentação manual, exercício
de PUT, exercício de CALL, expiração e baixa. Para cada caso, repetir o mesmo
POST e provar que existem exatamente uma posição, os eventos financeiros
esperados e um recibo; uma falha no meio deve deixar zero gravações.

**Aceitação:** o CI verde demonstra que um clique duplo, reenvio do navegador
ou erro intermediário não produz duplicidade nem registro parcial. Não será
criado registro de teste na base financeira real.

### Fase B — entrada guiada por estratégia

Começar pela Cash-Covered Put, que possui regras completas de prêmio, garantia,
expiração e exercício. O usuário preencherá uma prévia e confirmará o resumo
econômico antes de gravar. Compra de opção (Ranking) e Covered Call recebem
fluxos equivalentes, porém próprios; a grade genérica de Posições permanece
até a paridade ser comprovada.

**Aceitação:** cada tela explica o efeito em opção, caixa, estoque, DARF e
resultado antes da confirmação; uma declaração manual continua permitida sem
comprovante obrigatório.

### Fase C — localizar sem confundir com desaparecimento

Em `Posições`, exibir claramente o estado `aberta`, `fechada` ou `anulada`, o
recibo da operação e a linha do tempo. Incluir busca por ID e, para um registro
anulado, mostrar o motivo e o original em vez de simplesmente ocultá-lo.

**Aceitação:** uma posição aparece uma vez na visão operacional e seu estado é
explicável sem o usuário ter de comparar tabelas.

### Fase D — investigação dos dados legados

Inventariar backups fora da VPS e comparar apenas contagens, IDs e hashes antes
de abrir qualquer dado. Para cada lacuna comprovada, produzir um plano por
posição com fonte, simulação, efeito em caixa/estoque/DARF e reversão. A
aplicação só escreve após aprovação explícita com `--apply`.

**Aceitação:** nenhum dado histórico é inventado, sobrescrito ou restaurado em
produção por cima do estado atual.

## Ordem de execução

1. Fase A: testes de prova de novos registros e recibos.
2. Fase B: fluxo guiado da Cash-Covered Put.
3. Fase C: consulta didática de estado, recibo e histórico.
4. Fase D: somente se surgir backup ou fonte documental para uma lacuna.

Segurança e publicação continuam como guardas transversais: toda mudança passa
por testes PostgreSQL, `main`, CI do SHA exato e `release.ps1`. Elas não
substituem nem redefinem as regras funcionais acima.
