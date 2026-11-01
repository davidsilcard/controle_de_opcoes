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

## Fechamento retomado em 01/11/2026

Esta seção atualiza o estado operacional acima. A apuração fiscal permanece
incompleta pelos motivos identificados abaixo; não interpretar o mês como
fiscalmente conciliado.

### Fontes, declarações e plano executado

- Conferidos por extração textual e visualmente os dois PDFs enviados nesta
  retomada: cinco páginas de opções e duas páginas de operações à vista.
  São sete notas distintas; as três primeiras de opções e as duas à vista
  repetem fontes já conferidas em 22/10. Não foram importadas novamente.
- SHA-256 do PDF de opções:
  `5e01cd23945efe536363681bafe49e0da29925b27f55ccc16d627dbba1b84b9d`.
- SHA-256 do PDF à vista:
  `e3dc83bbc61e3c32b68220cc7d1acbefe01c21993184bd5c77f283d4d2a43da5`.
- O usuário confirmou ausência de exercícios, a compra nova de CALL VALEJ693
  de longo prazo e a venda de KLBNK196 coberta pelas suas 1.000 KLBN11.
  Autorizou usar os PMs cadastrados para calcular o resultado das ações.
  Essa autorização é uma declaração de custo, não prova das aquisições.
- Plano anterior às gravações: consultar produção e duplicidades; comparar as
  notas; cadastrar somente as duas opções ausentes pelo formulário oficial;
  conferir posição, ledger, recibo, cobertura e quadro operacional; documentar
  separadamente a incompletude fiscal. Nenhuma ordem de mercado foi enviada.
- Versão publicada consultada: `44ce33f59ac078815894c744b464e13853e0685d`, com
  [CI Testes PostgreSQL aprovado](https://github.com/davidsilcard/controle_de_opcoes/actions/runs/37975174133).
  Nenhuma alteração de código, migração ou deploy foi necessária nesta retomada.

### Novas notas e registros persistidos

| Nota | Pregão | Liquidação | Operação | Despesas individuais | Líquido |
| --- | --- | --- | --- | ---: | ---: |
| 35319063 | 23/10 | 26/10 | Compra 300 VALEJ693 a 12,02 | 4,82 | -3.610,82 |
| 35410533 | 26/10 | 27/10 | Venda 1.000 KLBNK196 a 0,20 | 0,25 | +199,75 |

- **#82 VALEJ693:** aberta, comprada, `ranking`; BUY #162 de -R$ 3.610,82;
  recibo #22, `positions.add`. Taxas 0,99 + 2,50 + 1,33 = 4,82.
  Não gerou prêmio, provisão nem resultado realizado. A consulta da UI mostra
  vencimento 20/10/2028 pelo snapshot; o cadastro de opção comprada não preserva
  `contract_strike`/`contract_expiry` nesse formulário. A referência documental
  posterior foi mantida nas observações, sem afirmar preservação estruturada.
- **#83 KLBNK196:** aberta, vendida, `covered_call`; PREMIUM #163 de
  +R$ 199,75 e provisão DARF #164 de -R$ 29,96; recibo #23, `positions.add`.
  Taxas 0,05 + 0,13 + 0,07 = 0,25. Reserva de 1.000 KLBN11, saldo livre zero;
  PM operacional 17,96 e capital de referência 17.960,00. Não gerou resultado
  realizado nem venda de ações. IRRF indicado de 0,01 ficou nas observações;
  não foi novamente deduzido ou certificado como retenção efetiva.

Referências consultadas em 01/11/2026: a B3 informa
[VALEJ693, strike 69,30 / 20/10/2028](https://bvmf.bmfbovespa.com.br/cias-listadas/Titulos-Negociaveis/DetalheTitulosNegociaveis.aspx?cb=VALE&idioma=en-US&or=res&tip=I)
e [KLBNK196, strike 19,63 / 19/11/2026](https://bvmf.bmfbovespa.com.br/cias-listadas/Titulos-Negociaveis/DetalheTitulosNegociaveis.aspx?cb=KLBN&idioma=pt-BR&or=res&tip=I).
São referências posteriores, compatíveis com os prazos das notas, sem certificar
automaticamente o strike original de abertura. A fonte e essa ressalva constam
nas observações. Não deduzir strike pelo ticker.

### Conciliação de fluxos e garantia

As cinco notas de opções totalizam vendas brutas de R$ 7.520,00, compras brutas
de R$ 10.002,00, despesas de R$ 23,40 e fluxo líquido de **-R$ 2.505,40**.
As duas notas novas acrescentam -R$ 3.411,07 a esse fluxo; a provisão interna
adicional de R$ 29,96 reduz o quadro operacional em R$ 3.441,03.
Não confundir nenhum desses totais com lucro realizado.

A venda de ações permanece em R$ 21.850,00 bruto e R$ 21.843,46 líquido.
As despesas de R$ 6,54 incluem CCP 4,89, emolumentos 1,09 e transferência 0,56.
A compra de LFTB11 permanece em R$ 23.341,50, com despesas de R$ 6,98
(CCP 5,22 + emolumentos 1,16 + transferência 0,60). O fluxo conjunto das sete
notas é -R$ 4.003,44; não reconcilia sozinho a conta da corretora.
IRRF indicado nas cinco notas de opções soma R$ 0,17; na venda de ações, R$ 1,09.
Os líquidos impressos não descontam esses valores novamente.

O depósito que representa acréscimo de garantia de R$ 21.843,46 foi preservado,
assim como a decisão anterior de manter LFTB11 fora do cadastro. Não houve
novo depósito, SELL manual, débito de ETF, estorno ou rateio estimado.

| Quadro operacional após as duas opções | Valor |
| --- | ---: |
| Total acompanhado | R$ 111.984,66 |
| Colateral de PUT | R$ 92.922,00 |
| Disponível após colateral | R$ 19.062,66 |

### Resultado das ações pelo PM declarado e divergência fiscal

Os eventos de estoque #21, #22 e #23 preservam os PMs imediatamente anteriores
à baixa declarada em 22/10. Usados por instrução expressa do usuário:

| Ativo | Quantidade vendida | PM declarado | Venda unitária | Resultado antes da despesa conjunta |
| --- | ---: | ---: | ---: | ---: |
| CAML3 | 1.000 | 6,60 | 6,56 | -40,00 |
| FESA4 | 1.000 | 6,39 | 6,66 | +270,00 |
| SOJA3 | 1.000 | 6,31 | 8,63 | +2.320,00 |
| Total | 3.000 | | | +2.550,00 |

Resultado conjunto pelo PM declarado: **R$ 2.550,00 - R$ 6,54 = R$ 2.543,46**.
O custo conjunto declarado é R$ 19.300,00. A despesa foi subtraída somente do
total desta nota; não foi inventada uma parcela líquida por ativo.

**Divergência de completude:** a tela DARF de outubro continua mostrando
-R$ 1.070,73 de resultado, R$ 0,00 de imposto, R$ 0,06 de IRRF e prejuízo
acumulado total de R$ 1.072,73, pois lê as cinco baixas de opções e não as três
vendas à vista. Esse zero não é uma conclusão fiscal válida para o mês completo.
As vendas de ações de R$ 21.850,00 excedem o limite mensal de R$ 20 mil descrito
pela [Receita Federal](https://www.gov.br/receitafederal/pt-br/assuntos/meu-imposto-de-renda/pagamento/renda-variavel/bolsa-de-valores-1/isencoes);
não presumir isenção por terem sido destinadas à garantia.

A soma de referência é +R$ 1.472,73 (ações +2.543,46 e opções -1.070,73),
**antes das despesas compartilhadas de opções ainda não atribuídas aos ciclos
encerrados**. Não equivale a base tributável final ou DARF autorizada. A nota de
05/10 mistura operações fechadas e abertas; despesas de abertura de setembro
também continuam sem rateio. A tela atribui R$ 0,06 de IRRF a BBASV222 na baixa,
embora a origem documental seja a abertura de setembro. A conciliação do IRRF
efetivamente retido e de sua competência permanece necessária.

### Validação e continuação necessária

- Auditoria autenticada após as gravações: zero alertas nas regras atuais e
  os mesmos 16 casos sem rateio. Prêmios acumulados 15.846,66; compras de
  opções -6.390,29; recompras -5.067,07; realizado acumulado 7.286,53.
- Consulta direta adicional em transação PostgreSQL obrigatoriamente somente
  leitura confirmou #82/#83, seus três lançamentos e seus dois recibos.
  Não houve UPDATE/INSERT por SQL, criação de posição fictícia ou reenvio de
  operação real para testar idempotência.
- Os PDFs cobrem negócios até 26/10, não comprovam ausência de outros negócios,
  transferências ou proventos no restante do mês. A declaração de que houve
  vendas para garantia foi confrontada com as três vendas do PDF; eventuais
  fontes adicionais devem ser conciliadas antes de certificar completude.
- A próxima alteração funcional deve oferecer venda à vista com custo
  declarado identificado, evento fiscal próprio e despesa única da nota,
  preservando estoque já baixado e crédito de garantia já contabilizado.
  Não usar depósito ou REALIZED avulso como substituto: a apuração atual lê
  posições e isso não resolveria a origem fiscal.
- Antes de qualquer reparo: versionar a prévia por nota/evento, explicitar os
  efeitos sobre estoque, caixa, garantia e apuração, provar rollback e
  idempotência em PostgreSQL isolado e cumprir o release do SHA exato.
  A presente retomada atualizou as opções e documentou o resultado declarado
  das ações; **não aplicou reparo fiscal das vendas à vista nem gerou DARF**.
