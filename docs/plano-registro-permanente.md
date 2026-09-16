# Plano de execução — registros permanentes e operação confiável

## Decisão arquitetural

Manter o sistema como monólito modular em Flask/PostgreSQL. Não introduzir
microserviços: cada área terá uma responsabilidade explícita e continuará
preservando os contratos funcionais de Cash-Covered Put, Covered Call e Wheel.

| Módulo | Responsabilidade | Não pode fazer |
| --- | --- | --- |
| Mercado | snapshots, IV e retenção | alterar registros financeiros do usuário |
| Operações | contrato, ciclo e estado por estratégia | calcular DARF diretamente |
| Razão financeiro | eventos de caixa e resultado | apagar ou sobrescrever eventos publicados |
| Estoque | eventos e saldo consolidado | inferir exercício sem evento confirmado |
| Apuração | desempenho, auditoria e DARF como projeções | corrigir a origem silenciosamente |
| Histórico | revisões, anulações e autoria | excluir o registro original |

Fonte declarada pelo usuário é válida para registrar uma operação. Comprovante
continua opcional; o sistema deve distinguir `declaração manual`, `fonte
documental` e `campo pendente`, sem impedir o uso da plataforma.

## Fase 0 — contenção imediata

1. Alterar a retenção de mercado para três meses-calendário após o vencimento.
   Snapshots sem vencimento válido não serão apagados automaticamente.
2. Produzir inventário somente leitura de posições, razão, estoque e candidatos
   a duplicidade antes de qualquer reparo de dados.
3. Não executar reparo financeiro, SQL manual, exclusão ou backfill contra a
   base real sem simulação, validação e aplicação explícita.

**Aceitação:** retenção nunca consulta nem remove `positions`, `ledger`,
`darf_months`, `equity_holdings` ou eventos de estoque; o corte para contratos
vencidos é calculado por meses-calendário, não por 30 dias.

## Fase 1 — razão permanente e correção rastreável (em andamento)

1. Criar um diário de alterações imutável com data, usuário, motivo, origem e
   vínculo do evento corrigido.
2. Substituir exclusão física por anulação com motivo e evento de reversão.
   O lançamento e a posição originais permanecem consultáveis.
3. Introduzir vínculos entre posição, razão e eventos de estoque, além de
   chaves de idempotência para evitar duplicidade por reenvio ou clique duplo.
4. Migrar o histórico existente como `importado_legado`, sem reescrever valores.

Primeira entrega da fase: `record_history` registra a versão anterior de cada
`UPDATE` e `DELETE` de posições ou razão. A tabela é append-only por trigger
do PostgreSQL. A interface exige o motivo e atribui a anulação ao usuário
autenticado. As rotinas de reversão financeira por estratégia continuam sendo
implementadas antes de qualquer substituição de cálculo automático.

Segunda entrega da fase: `operation_receipts` associa cada envio de cadastro a
uma chave única e a uma impressão criptográfica dos campos. Posição/opção e
movimentação manual de caixa são gravadas junto do recibo, na mesma transação.
Reenviar o mesmo formulário reaproveita o recibo; usar sua chave com dados
distintos é bloqueado. Exercício, expiração, encerramento e edição serão
migrados em recortes próprios, pois cada um tem regras financeiras diferentes.

**Aceitação:** uma tentativa repetida não cria novo evento; uma correção deixa
o original, a reversão e o motivo visíveis; não existe rota operacional de
`DELETE` para dados publicados.

## Fase 2 — registro seguro por estratégia

1. Criar fluxo de confirmação para compra e venda de opção: prévia, confirmação
   e recibo com identificador da operação.
2. Escrever posição, contrato e eventos de caixa em uma transação única.
3. Validar regras específicas sem misturar estratégias: prêmio, recompra,
   expiração e exercício na Cash-Covered Put; cobertura, exercício e estoque na
   Covered Call; pernas explícitas no Wheel.
4. Manter a grade legada até que o novo fluxo tenha paridade comprovada.

**Aceitação:** falha no meio do cadastro desfaz tudo; o recibo permite localizar
a operação; declaração manual registra o fato sem exigir nota.

## Fase 3 — telas e projeções didáticas

1. Agrupar pendências por posição. Uma posição como `#47` aparecerá uma vez,
   com estados de contrato e garantia identificados separadamente.
2. Transformar `Posições` em histórico consultável e fluxo de correção
   controlado, preservando os filtros e a leitura por estratégia.
3. Exibir em cada resultado a origem: cálculo conhecido, declaração manual,
   pendência documental ou auditoria concluída sem prova.

**Aceitação:** nenhuma tela dá aparência de duplicidade para a mesma posição;
campos ausentes não escondem resultado financeiro conhecido.

## Fase 4 — auditoria e publicação

1. Criar relatório de integridade: órfãos, duplicidades candidatas, estados
   incompatíveis e totais divergentes por estratégia.
2. Testar PostgreSQL descartável, incluindo rollback, repetição de POST,
   anulação, expiração, exercício e DARF.
3. Publicar somente após backup restaurável verificado, testes verdes, commit e
   push na `main`; usar exclusivamente `deploy/scripts/update-vps.sh`.

## Ordem de entrega

1. Fase 0 (iniciada nesta alteração).
2. Diário imutável e anulação da Fase 1.
3. Registro seguro da Cash-Covered Put; em seguida Covered Call; Wheel somente
   com as pernas explícitas já existentes.
4. Agrupamento visual e relatório de integridade.

Não há reparo automático dos strikes ausentes. Cada caso histórico permanece
pendente até fonte documental ou declaração manual explícita.
