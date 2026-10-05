# Auditoria documental de setembro de 2026

Conferência somente leitura em 02/10/2026. Nenhuma posição, caixa, estoque ou
apuração fiscal foi alterada nesta auditoria. Este relatório não autoriza
importação automática: consultar novamente a produção antes de cada gravação.

## Escopo e fontes

### Retomada em 05/10/2026 — estado e limite operacional declarado

- Consulta autenticada da UI: KLBNJ196 (#73) encerrada em 25/09/2026 por
  recompra; bruto R$ 280,00, taxas R$ 0,51 e resultado R$ 279,49 antes da
  apuração mensal. Estoque KLBN11: 1.000 totais, zero reservadas, 1.000 livres.
  A baixa deixou de ser pendente; não recriar abertura nem fechamento.
- Filtro `CMIGU105`, todos os status: nenhuma posição registrada. A abertura
  de 27/08 e a recompra de 04/09 continuam pendentes.
- O usuário declarou garantia global de aproximadamente R$ 463 mil, mas
  escolheu acompanhar apenas R$ 68.000 disponíveis **além** dos R$ 24.288
  reservados: limite operacional acompanhado de R$ 92.288. Não importar o
  restante da carteira nem interpretar a declaração como depósito bancário.
- A UI atualmente mostra esse montante no caixa porque o usuário lançou
  um depósito manual de R$ 63.419,40 em 05/10/2026. Disponível R$ 68.000;
  total R$ 92.288; colateral R$ 24.288. Isso é uma representação operacional
  escolhida pelo usuário, não uma funcionalidade separada de garantia em
  investimentos. Não afirmar que o modelo já separa garantia de dinheiro.
- Não alterar ou estornar esse lançamento sem autorização específica.
  A modelagem separada de limite/garantia e caixa continua como melhoria.
- Antes de acrescentar receitas históricas, esclarecer os depósitos de
  R$ 6.503,32 (26/08) e R$ 3.904,66 (04/09): aportes independentes ou ajustes
  de saldo que já incluem negócios? Não presumir duplicidade nem compensar
  automaticamente. A confirmação do limite atual não resolve essa origem.
- Nenhuma gravação financeira foi enviada pelo assistente nesta retomada.
  A despesa compartilhada de R$ 3,44 da nota #34281732 continua observada no
  caixa; não repeti-la na recompra da CMIGU105.

As seções datadas de 02/10 abaixo preservam o diagnóstico anterior. Para
KLBNJ196, prevalece o estado conferido nesta retomada.

Foram conferidas visualmente e por extração textual as quatro páginas de cada
PDF de opções enviado pelo usuário: versão original e versão `Resumo`, com
intervalo nominal de 04/09/2026 a 25/09/2026. Os dois arquivos representam as
**mesmas quatro notas**, não oito notas nem dois conjuntos de negócios.
Também foi comparada a planilha ilustrada pelo usuário e consultada a produção
nas telas `Posições`, `Auditoria` e `Cash-Covered Put`, sem enviar formulários.
Os PDFs e os dados pessoais da corretora não foram copiados para o Git.

O usuário declara setembro fechado. Os arquivos comprovam os negócios abaixo,
mas não comprovam, isoladamente, a inexistência de negócios depois de 25/09,
transferências, proventos, aluguéis ou outros mercados. Esta não é uma
certificação de saldo bancário nem uma apuração definitiva de DARF.

## Conciliação das notas

Valores em reais; sinal positivo é crédito e negativo é débito. Datas de
pregão e liquidação são distintas e precisam permanecer identificadas.

| Nota | Pregão | Liquidação | Fluxo bruto assinado | Despesas | Líquido da nota |
| --- | --- | --- | ---: | ---: | ---: |
| 34281732 | 04/09/2026 | 08/09/2026 | 2.483,00 | 3,44 | +2.479,56 |
| 34573207 | 21/09/2026 | 22/09/2026 | 340,00 | 0,44 | +339,56 |
| 34642300 | 23/09/2026 | 24/09/2026 | 1.300,00 | 1,73 | +1.298,27 |
| 34682203 | 25/09/2026 | 28/09/2026 | -60,00 | 0,07 | -60,07 |
| **Total** | | | **4.063,00** | **5,68** | **+4.057,32** |

Vendas brutas: R$ 4.197,00; compras brutas: R$ 134,00. O crédito líquido de
R$ 4.057,32 é **fluxo de caixa das notas**, não lucro realizado de setembro.
Parte dos prêmios corresponde a opções que continuam abertas.

IRRF indicado nas notas: R$ 0,12 + R$ 0,01 + R$ 0,06 = R$ 0,19. Os líquidos
impressos já fecham com as despesas acima, sem subtrair esses R$ 0,19. Não
deduzir novamente nem confundir IRRF indicado com provisão de DARF. A apuração
mensal permanece separada e depende da conciliação completa.

## Conciliação por execução com a produção

| Pregão | Execução | Bruto | Estado observado / ação pendente |
| --- | --- | ---: | --- |
| 04/09 | Venda 2.300 BBASJ252 a 0,74 | +1.702,00 | #70 aberta; abertura encontrada, não duplicar. |
| 04/09 | Venda 2.600 CMIGJ124 a 0,15 | +390,00 | #71 aberta; abertura encontrada, não duplicar. |
| 04/09 | Compra 2.100 CMIGU105 a 0,02 | -42,00 | Não encontrada. Recompra da venda de 27/08, não compra direcional. A abertura histórica também está pendente. |
| 04/09 | Venda 2.300 CMIGV104 a 0,15 | +345,00 | #72 aberta; abertura encontrada, não duplicar. |
| 04/09 | Venda day trade 100 HYPEJ26 a 0,30 | +30,00 | Não encontrada; ciclo separado da venda regular. |
| 04/09 | Venda regular 300 HYPEJ26 a 0,30 | +90,00 | Não encontrada; 300 HYPE3 livres observadas no estoque. |
| 04/09 | Compra day trade 100 HYPEJ26 a 0,32 | -32,00 | Não encontrada; encerra somente as 100 opções do day trade. |
| 21/09 | Venda 1.000 KLBNJ196 a 0,34 | +340,00 | #73 encontrada, com despesas 0,44 e prêmio líquido 339,56; não duplicar a abertura. |
| 23/09 | Venda 2.000 BBASV222 a 0,65 | +1.300,00 | Não encontrada; despesas individuais 1,73 e prêmio líquido 1.298,27. Conferir contrato e garantia antes de classificar como Cash-Covered Put. |
| 25/09 | Compra 1.000 KLBNJ196 a 0,06 | -60,00 | Não encontrada. #73 continua aberta; registrar recompra total com despesa 0,07 e débito total 60,07. |

São dez execuções nas notas: quatro aberturas encontradas e **seis execuções
pendentes**, agrupadas em cinco tratamentos funcionais. Não há evidência de
duplicidade desses negócios na consulta realizada; ausência na tela não prova
que houve exclusão ou perda de dados. Investigar histórico/recibos se existir
evidência de um envio anterior dos negócios ausentes.

A nota 34281732 agrupada mostra venda de 400 HYPEJ26 e compra de 100, mas o
detalhamento separa explicitamente 100 vendas/100 compras marcadas `D` e a
venda regular de 300. Não cadastrar uma venda regular de 400 nem utilizar a
compra do day trade para reduzir a posição regular.

## Achados e limites de integridade

1. **Estado desatualizado de KLBNJ196 (#73).** A recompra da nota 34682203
   encerra as mesmas 1.000 opções vendidas em 21/09. Resultado bruto do ciclo:
   R$ 280,00; despesas totais: R$ 0,51; resultado líquido antes da apuração
   fiscal: **R$ 279,49**. A produção ainda reserva as 1.000 KLBN11; após a
   baixa correta elas devem ficar livres, salvo outra reserva legítima.
2. **CMIGU105 exige a origem histórica.** A conferência anterior e a declaração
   do usuário identificam venda de 2.100 opções em 27/08 a R$ 0,20, nota
   34011960. Resultado bruto contra a recompra de 04/09: R$ 378,00. A nota de
   agosto não está neste novo par de PDFs: revalidar a fonte anterior e seus
   custos antes de cadastrar. Não inventar resultado líquido nem criar uma
   nova PUT comprada. O crédito de R$ 420,00 pertence a agosto, não ao total
   das quatro notas de setembro.
3. **HYPEJ26 precisa de dois ciclos.** Venda regular de 300 aberta, com
   cobertura declarada pelo usuário e estoque disponível observado; day trade
   separado de 100 encerrado no mesmo dia, com resultado bruto de -R$ 2,00.
   O PDF informa base de day trade de -R$ 2,03, mas o detalhamento impresso de
   taxas mostra apenas R$ 0,01 de registro e demais linhas zero. Não é possível
   reconstruir os três centavos só pelas linhas exibidas. Preservar ambos os
   valores documentais, pedir detalhamento se necessário e não inventar rateio.
4. **BBASV222 não cadastrada e garantia não conciliada.** A nota comprova a
   venda, não o strike nem o saldo disponível para cobrir uma PUT. Caixa
   disponível observado na aplicação: R$ 4.640,67, com R$ 24.288,00 de
   colateral já comprometido na CMIGV104. Não aumentar saldo ou assumir
   cobertura em dinheiro para contornar validação. Confirmar contrato,
   natureza da garantia e extrato/declaração de capital disponível. A venda
   efetivamente ocorrida deve continuar identificada como fato a registrar,
   mesmo se a arquitetura atual ainda não representar uma PUT sem caixa
   integralmente reservado.
5. **Conciliação interna não mede completude externa.** `Auditoria` mostrou
   zero alertas, sem órfãos ou duplicidades pelas regras atuais, enquanto faltam
   negócios documentados. Esse resultado valida apenas o conjunto cadastrado;
   não certifica que todos os negócios da corretora entraram no sistema.
6. **Aportes manuais exigem identificação.** Foram observados depósitos manuais
   de R$ 3.904,66 em 04/09 e R$ 6.503,32 em 26/08. Os PDFs de opções não
   comprovam sua origem. Não concluir que são erros; confirmar se representam
   transferências reais ou ajustes de saldo antes de inserir receitas
   históricas, para não contar o mesmo caixa duas vezes.

As aberturas encontradas e suas despesas de nota representam R$ 2.773,12 de
fluxo correspondente às quatro fontes: 1.702 + 390 + 345 - 3,44 + 339,56.
Faltam **R$ 1.284,20 de fluxo líquido destas notas**: -42 + 90 - 2 + 1.298,27
- 60,07. Essa diferença não é saldo faltante comprovado na corretora e não
inclui provisões fiscais, depósitos manuais ou o crédito histórico de agosto.

A despesa conjunta de R$ 3,44 da nota 34281732 já está no caixa uma vez.
Não repetir o lançamento ao completar CMIGU105/HYPEJ26. Se um rateio vier a
ser comprovado e implementado, deve manter a soma de R$ 3,44, sem somar uma
segunda despesa sobre o valor já registrado.

KLBNI20 (#69), vendida em agosto e declarada expirada sem exercício em 18/09,
é um ciclo distinto de KLBNJ196. Seu encerramento deve continuar preservado;
ausência nos PDFs de negócios de setembro não é motivo para removê-lo.

## Próxima execução proposta — ainda não aplicada

1. Capturar estado anterior e conferir novamente IDs, caixa, histórico,
   estoque e recibos. Usar os fluxos oficiais por estratégia, nunca SQL avulso.
2. Encerrar #73 por recompra em 25/09: 1.000 a 0,06, despesas 0,07. Conferir
   débito 60,07, resultado 279,49, posição fechada e liberação das 1.000 KLBN11.
3. Reconciliar os aportes e a garantia da BBASV222; confirmar contratos
   ausentes por fonte confiável, sem derivar strike do nome do ticker.
4. Completar abertura histórica/recompra da CMIGU105 e a venda regular da
   HYPEJ26, separadamente, verificando caixa e estoque após cada registro.
5. Validar que o fluxo funcional suporta o day trade da HYPEJ26, com venda e
   compra no mesmo dia e sem interferir nas 300 opções abertas. Se não suporta,
   planejar implementação/testes antes de registrar por aproximação.
6. Registrar BBASV222 de acordo com a garantia efetivamente declarada e com
   contrato funcional compatível, sem forçar uma estratégia inadequada.
7. Conciliar as quatro notas para R$ 4.057,32 e despesas para R$ 5,68, conferir
   cada ciclo, reservas, histórico e recibos; só depois revisar DARF mensal.

Critérios de aceite: exatamente um negócio por execução, recompra vinculada à
venda correta, day trade separado, custos únicos, nenhuma alteração de ciclos
alheios, datas históricas preservadas e conciliação externa além dos alertas
internos. Repetir um envio não pode duplicar evento ou efeito financeiro.

## Melhoria funcional recomendada

### Execução iniciada em 02/10/2026 — taxas da recompra

O usuário autorizou atualizar a aplicação após esta auditoria. A inspeção do
fluxo de baixa encontrou uma limitação: `fees` representa taxas da entrada,
enquanto a recompra gerava débito apenas de preço × quantidade. Somar as taxas
da recompra em `fees` tornaria o prêmio de abertura divergente; omiti-las
tornaria caixa e resultado incompletos.

Foi implementado o campo separado `buyback_fees` para a recompra total de
opção vendida. Plano/aceite: preservar taxas de entrada e prêmio original;
incluir taxas da recompra no BUY e no resultado realizado; refletir o mesmo
valor em Auditoria e resumo de posições; rejeitar custo negativo/não finito
ou sem baixa válida; preservar formulários antigos; testar persistência,
repetição e liberação de cobertura no PostgreSQL descartável antes do release.
Para #73, os valores esperados são prêmio 339,56, BUY -60,07 e resultado
279,49. Até publicação e verificação da gravação, a baixa segue pendente.

Validação local da implementação: suíte completa com 294 aprovados e 94
pulados por dependência de PostgreSQL, além de compilação e conferência de
diff. Os skips não validam persistência: o teste novo de PostgreSQL verifica
taxas separadas, resultado, caixa, repetição sem duplicidade e liberação das
1.000 ações. Release exige CI verde do SHA exato pelo script oficial.
O histórico legível também exibe `Taxas da recompra`, além da preservação
integral do valor pelo diário de alterações do PostgreSQL.

Publicação concluída em 02/10/2026 pelo `deploy/scripts/release.ps1`:
implementação `12fd8c7` e complemento do histórico `88a24e5`, ambos com CI
aprovado. Validação final do segundo SHA: 386 testes aprovados e 4 pulados;
VPS em `88a24e5`, login e edge saudáveis. Ao retomar a posição na UI, a sessão
estava expirada por inatividade. **Nenhuma baixa financeira foi enviada.**
Próximo passo após login do usuário: reconsultar #73, registrar fechamento
25/09, preço 0,06, motivo recompra, taxas de entrada preservadas em 0,44 e
taxas da recompra 0,07; manter a fonte das duas notas nas observações. Conferir
BUY -60,07, resultado 279,49, reserva KLBN11 zero, 1.000 livres e histórico.
Não cadastrar outra abertura nem recalcular prêmio/DARF de entrada.

Retomada após login: #73 foi reconsultada aberta, com 1.000 KLBN11 reservadas.
O formulário foi preenchido com os valores acima, mas o controle do navegador
falhou no clique de envio. Uma nova consulta mostrou a posição ainda aberta,
sem baixa persistida. A tentativa de enviar pelo teclado também falhou antes
de despachar a tecla; a captura de tela posteriormente ficou indisponível.
Não houve confirmação de gravação. Não contornar com SQL ou com a CLI legada
de fechamento (ela não recebe as taxas separadas). Retomar pela UI do usuário:
conferir novamente #73 e enviar `Salvar operação` com os valores auditados;
depois validar persistência, caixa, resultado, estoque e histórico. Se já
estiver fechada, não reenviar: conferir os valores existentes primeiro.

### Conciliação por nota/período

Adicionar uma conciliação por nota/período com linhas esperadas, linhas
vinculadas, diferença de caixa, custo único e estado `parcial`/`conciliada`.
Original e resumo devem apontar para a mesma nota, não gerar importações
independentes. Alertar quando uma recompra documentada ainda deixa reserva
aberta e distinguir explicitamente `integridade interna` de `completude do
período`. Isso é uma proposta de evolução, não funcionalidade já implementada.
