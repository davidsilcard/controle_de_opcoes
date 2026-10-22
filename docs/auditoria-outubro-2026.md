# Auditoria operacional de outubro de 2026

Conferência e registros realizados em 22/10/2026 nos formulários autenticados da
aplicação publicada. As notas foram conferidas por texto e pelas cinco páginas
renderizadas. Não houve SQL manual, alteração de código, migração ou deploy.
PDFs, imagens das notas e dados pessoais da corretora não foram adicionados ao Git.

## Escopo e decisões do usuário

- Registrar negócios já executados na corretora; nenhuma ordem de negociação foi enviada.
- CMIGJ124 e HYPEJ26 expiraram sem exercício em 16/10; as ações continuam na carteira.
- PETRT430 é compra nova de PUT, não recompra de posição vendida.
- Recursos das vendas de CAML3, FESA4 e SOJA3 foram direcionados a LFTB11 como
  garantia de PUT. O usuário mantém ETF fora do cadastro e usa o quadro de caixa
  como representação da garantia operacional.
- O usuário confirmou que R$ 21.843,46 líquidos dessas vendas devem ser
  acrescentados ao limite anterior, não estavam incluídos nele.
- Não estimar rateio de despesas. Não confundir garantia com dinheiro bancário,
  crédito de prêmio com lucro realizado ou provisão com imposto devido.

## Notas conferidas

Datas abaixo são de pregão; o sinal do líquido indica crédito ou débito.

| Nota | Pregão | Liquidação | Operações | Despesas | Líquido |
| --- | --- | --- | --- | ---: | ---: |
| 34836403 | 02/10 | 05/10 | Compra 1.000 PETRT430 a 1,50 | 2,00 individuais | -1.502,00 |
| 34860646 | 05/10 | 06/10 | Compra 2.300 BBASJ252 a 2,11; venda 2.300 BBASK266 a 1,76; compra 2.000 BBASV222 e 2.300 CMIGV104 a 0,01 | 11,96 conjuntas | -859,96 |
| 35242486 | 21/10 | 22/10 | Venda 5.100 BBDCW189 a 0,56 e 2.600 CMIGK130 a 0,16 | 4,37 conjuntas | +3.267,63 |
| 35067285 | 13/10 | 15/10 | Venda 1.000 CAML3 a 6,56; 1.000 FESA4 a 6,66; 1.000 SOJA3 a 8,63 | 6,54 conjuntas | +21.843,46 |
| 35103620 | 15/10 | 16/10 | Compra 181 LFTB11 a 128,92 | 6,98 individuais | -23.341,50 |

Fluxo líquido das três notas de opções: **+R$ 905,67**, antes das provisões
internas da aplicação. Não equivale a lucro realizado. IRRF indicado de R$ 0,16
na nota 35242486 e R$ 1,09 na nota 35067285 não foi subtraído novamente dos
líquidos impressos. A conciliação mensal do IRRF continua separada.

## Posições gravadas e verificadas

| ID | Posição | Registro confirmado | Resultado conhecido da baixa |
| --- | --- | --- | ---: |
| 70 | BBASJ252, 2.300 | Recompra total a 2,11 em 05/10 | -3.151,00 bruto |
| 74 | BBASV222, 2.000 | Recompra total a 0,01 em 05/10 | +1.278,27 após despesas individuais conhecidas da entrada |
| 72 | CMIGV104, 2.300 | Recompra total a 0,01 em 05/10 | +322,00 bruto |
| 71 | CMIGJ124, 2.600 | Expiração sem exercício em 16/10, declarada pelo usuário | +390,00 bruto |
| 77 | HYPEJ26, 300 | Expiração sem exercício em 16/10, declarada pelo usuário | +90,00 bruto |
| 78 | BBASK266, 2.300 | Venda a 1,76 em 05/10; Covered Call | Aberta; prêmio bruto 4.048,00 |
| 79 | CMIGK130, 2.600 | Venda a 0,16 em 21/10; Covered Call | Aberta; prêmio bruto 416,00 |
| 80 | BBDCW189, 5.100 | Venda a 0,56 em 21/10; Cash-Covered Put | Aberta; prêmio bruto 2.856,00 |
| 81 | PETRT430, 1.000 | Compra a 1,50 em 02/10; módulo de opções compradas, Aposta/Ranking | Aberta; débito 1.502,00 com despesas |

As três recompras geraram débitos de R$ 4.853,00, R$ 20,00 e R$ 23,00.
As expirações não venderam ações nem geraram nova receita de prêmio.
As despesas conjuntas de R$ 11,96 e R$ 4,37 foram lançadas uma única vez,
como `SHARED_NOTE_FEE`, nas datas de pregão, com referência às posições.
Os custos de setembro já existentes não foram duplicados.

Referências de contrato preservadas:

- BBASK266: strike de referência 26,54 e vencimento 19/11/2026, snapshot de
  21/10 consultado na Covered Call. Não comprova o strike original em 05/10.
- CMIGK130: strike 12,80 e vencimento 19/11/2026, Opções.net com fechamento
  de 21/10, consultado em 22/10.
- BBDCW189: strike 18,22 e vencimento 19/11/2026, mesma fonte e datas.
  Obrigação teórica: 5.100 × 18,22 = R$ 92.922,00.
- PETRT430: vencimento 18/08/2028, compatível com prazo 08/28 da nota;
  strike atual 41,81 no Opções.net consultado em 22/10. Não comprova o
  strike original de 02/10. Não deduzir o strike pelo código do ticker.

Fonte externa consultada: https://opcoes.net.br/opcoes/bovespa.
As referências posteriores à abertura são explicitadas nas observações;
eventuais ajustes históricos de contrato continuam sujeitos a prova datada.

## Estoque e garantia operacional

- BBAS3: 2.300 totais, 2.300 reservadas para BBASK266, zero livres.
- CMIG4: 2.600 totais, 2.600 reservadas para CMIGK130, zero livres.
- HYPE3: 300 totais, zero reservadas, 300 livres.
- CAML3, FESA4 e SOJA3: saldo consolidado zerado pelo formulário oficial,
  documentando as vendas integrais de 13/10 e preservando o histórico.
- LFTB11 não foi cadastrado nem debitado, por decisão expressa do usuário:
  integra a garantia em investimentos representada no quadro operacional.

Foi registrado acréscimo operacional de **R$ 21.843,46**, com data de liquidação
15/10 e observação da confirmação em 22/10. A categoria existente é depósito,
mas a descrição informa que representa aumento da garantia declarada, originado
das vendas, e não aporte bancário novo nem lucro fiscal. Não somar novamente
um SELL dessas mesmas vendas ao limite sem reconciliar esse registro.
Não descontar novamente R$ 6,54 de despesas já incluídas no valor líquido.

Após as opções e antes desse acréscimo: total R$ 93.582,23, colateral
R$ 92.922,00, disponível R$ 660,23. Estado final conferido:

| Quadro operacional | Valor |
| --- | ---: |
| Total acompanhado | R$ 115.425,69 |
| Colateral de PUT | R$ 92.922,00 |
| Disponível após colateral | R$ 22.503,69 |

É a representação operacional escolhida pelo usuário, com investimentos em
garantia; não é certificação do saldo financeiro da conta da corretora.
As provisões automáticas das três vendas novas somam R$ 1.098,00 e afetam o
quadro; não foram tratadas como imposto mensal apurado ou pago.

## Verificação e limites remanescentes

A Auditoria publicada terminou com **zero alertas** nas regras atuais,
sem divergência em prêmio, recompra, compra de opção ou resultado realizado.
Prêmios acumulados: R$ 15.646,91; recompras: -R$ 5.067,07;
compras de opções: -R$ 2.779,47; resultado realizado acumulado: R$ 7.286,53.
As cinco baixas de outubro acrescentaram -R$ 1.070,73 ao realizado,
antes dos custos compartilhados ainda sem atribuição por operação.

Isso comprova consistência interna do recorte lançado, não completude fiscal:

1. Há 16 posições sinalizadas com despesas compartilhadas sem rateio. Não
   interpretar zero alerta como DARF certificada ou lucro líquido individual final.
2. Em #74, a abertura tinha despesas individuais; a recompra tem custo conjunto.
   O modelo não separa perfeitamente a pendência por perna: observações e este
   relatório registram a limitação, mesmo que a Auditoria ainda mostre essa
   posição como verificável. O resultado 1.278,27 não desconta sua parcela
   desconhecida dos R$ 11,96.
3. Atualizar o estoque consolidado não registra venda à vista ou resultado fiscal.
   As três vendas à vista ainda precisam de conciliação fiscal própria e de fluxo
   que preserve estoque, SELL, custo de aquisição e despesas. Não criar compras
   fictícias nem editar um depósito para simular uma venda.
4. PM consolidado é declaração operacional, não prova do custo fiscal integral.
   Não calcular lucro tributável das ações somente a partir do PM exibido.
5. A compra de LFTB11 excede o líquido das três vendas em R$ 1.498,04; isso
   não autoriza acrescentar essa diferença à garantia sem nova declaração.
6. Os depósitos históricos e a distinção arquitetural entre garantia aplicada e
   caixa real continuam pendentes conforme a auditoria de setembro. Não foram
   estornados ou compensados nesta execução.

Próximo trabalho funcional: separar garantia de dinheiro e criar registro de
venda à vista com prévia, idempotência e efeitos atômicos. Exige plano específico
e validação em banco isolado antes de qualquer reparo ou publicação.
