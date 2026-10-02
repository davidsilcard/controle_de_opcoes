# Conferência parcial de setembro de 2026

Estado em 22/09/2026. Este inventário **não é uma ordem de importação**. Conferir
novamente a produção antes de cada gravação; não recriar operação existente.

## Atualização conferida em 02/10/2026 — KLBNJ196

- Nota BTG #34573207, pregão 21/09/2026, fornecida pelo usuário: venda de
  1.000 CALLs KLBNJ196 sobre KLBN11 a R$ 0,34; bruto R$ 340,00.
- Despesas individualizadas da única negociação: liquidação R$ 0,09,
  registro R$ 0,23 e emolumentos R$ 0,12; total R$ 0,44 e crédito líquido
  R$ 339,56. IRRF de R$ 0,01 registrado separadamente.
- Contrato consultado na B3 em 02/10/2026: strike exibido R$ 19,63 e
  vencimento 16/10/2026. Fonte:
  https://bvmf.bmfbovespa.com.br/cias-listadas/Titulos-Negociaveis/DetalheTitulosNegociaveis.aspx?cb=KLBN&idioma=pt-BR&or=res&tip=I
  A nota comprova a negociação, mas não informa o strike; a referência do
  cadastro identifica a data da consulta do contrato.
- Antes de gravar, o filtro de todos os status não encontrou KLBNJ196 e o
  estoque consolidado mostrou 1.000 KLBN11 livres. Cadastro realizado pela UI
  como posição **#73**, real, vendida, Covered Call, aberta em 21/09/2026.
- Após gravar: 1.000 KLBN11 totais, 1.000 reservadas e zero livres; prêmio
  esperado e no caixa R$ 339,56; provisão DARF esperada e no caixa R$ 50,93;
  saldo após provisão R$ 288,63. Diferenças da posição iguais a zero.
- Auditoria de produção: zero alertas pelas regras atuais. As 11 referências
  anteriores de despesas compartilhadas seguem sem rateio documental; isso
  impede certificar os totais de DARF, mas não a conciliação individual da #73.
- **Não recriar esta negociação.** O cadastro não encerra as pendências
  anteriores de CMIGU105 e HYPEJ26 descritas abaixo. Sem mudança de código
  ou necessidade de deploy para esta inclusão de dados.

## Fontes

- Nota BTG #34281732, pregão 04/09/2026, no arquivo local
  `C:\Users\david\Downloads\setembro-parcial.zip`.
- Nota BTG #34011960, pregão 27/08/2026, no arquivo local
  `C:\Users\david\Downloads\008256788_04_08_2026_27_08_2026.zip`.
- Strike e vencimento consultados por ticker em Opções.net em 22/09/2026.
  A nota de corretagem não prova o strike individual.
- Declarações do usuário sobre as quantidades de CMIG4 e HYPE3 em 04/09.

## Reconciliação antes dos próximos lançamentos

| Operação | Nota e valor bruto | Situação em 22/09 | Próxima ação |
| --- | --- | --- | --- |
| KLBNI20, 1.000 CALLs | #33944386 de 24/08, R$ 240,00 | Já registrada como posição #69 e encerrada por expiração em 18/09; taxa individual R$ 0,30 | Não duplicar. Sem exercício conforme declaração do usuário, não nota de baixa. |
| BBASJ252, venda de 2.300 CALLs | #34281732, R$ 1.702,00 | Cadastrada na produção em 22/09 como posição #70, aberta em 04/09, Covered Call; prêmio bruto registrado e despesa compartilhada marcada | 2.300 BBAS3 reservadas na aba Covered Call; não duplicar. |
| CMIGJ124, venda de 2.600 CALLs | #34281732, R$ 390,00 | Cadastrada na produção em 22/09 como posição #71, aberta em 04/09, Covered Call; prêmio bruto registrado e despesa compartilhada marcada | 2.600 CMIG4 reservadas na aba Covered Call; não duplicar. |
| CMIGU105, recompra de 2.100 PUTs | #34281732, débito bruto R$ 42,00 | A venda de 27/08 não está cadastrada; #34011960 comprova crédito bruto R$ 420,00 | Cadastrar primeiro a abertura histórica e depois a recompra em 04/09. Resultado bruto R$ 378,00, antes de custos da nota de 04/09. |
| CMIGV104, venda de 2.300 PUTs | #34281732, R$ 345,00 | Cadastrada na produção em 22/09 como posição #72, aberta em 04/09, Cash-Covered Put; prêmio bruto e provisão DARF de R$ 51,75 no caixa | Colateral teórico R$ 24.288,00 e caixa livre R$ 4.352,04 após lançar a despesa compartilhada; não duplicar. |
| HYPEJ26, venda líquida de 300 CALLs | #34281732, R$ 90,00 | Não cadastrada; 300 HYPE3 livres | Confirmar strike do contrato por fonte confiável. A nota também tem day trade separado de 100 vendas a R$ 0,30 e 100 compras a R$ 0,32. Não fundir as duas operações. |

A nota #34281732 registra R$ 3,44 de despesas conjuntas (liquidação R$ 0,71,
registro R$ 1,78 e emolumentos R$ 0,95) e IRRF indicado R$ 0,12. Não existe
rateio documental por ticker. Os resultados individuais devem permanecer antes
desse custo, com a referência comum marcada. O custo da nota precisa entrar
**uma única vez** no caixa por fluxo auditável. Foi lançado em 22/09/2026 como
despesa de R$ 3,44 datada de 04/09/2026, com a referência da nota #34281732;
o caixa diminuiu de R$ 4.355,48 para R$ 4.352,04. O IRRF indicado de R$ 0,12
não foi atribuído a uma posição. A provisão automática de DARF não substitui
a apuração mensal.

A tela `Posições` filtrada por ticker exibia reserva de estoque apenas das
posições visíveis e podia fazer outros ativos parecerem livres. O cálculo global
foi corrigido no código e ganhou teste de regressão; conferir o deploy antes de
usar esse quadro como saldo operacional. A aba `Covered Call` já mostrou as
2.300 BBAS3 reservadas independentemente do filtro.

As notas à vista do pacote incluem VRTA11, LFTB11, BTCI11 e XPML11; não são
opções e não devem entrar nas abas PUT/CALL por aproximação. Definir escopo
específico de estoque/ativos antes de importá-las.

## Ordem segura

1. Publicar e testar a marcação de despesas compartilhadas no cadastro.
2. Validar em produção a ausência de cada ticker e a cobertura/garantia.
3. Cadastrar operações uma a uma pela UI, verificando posição, histórico,
   caixa, estoque e DARF após cada gravação.
4. Registrar o custo compartilhado uma vez; conciliar o total da nota sem
   atribuí-lo artificialmente aos resultados individuais.
5. Manter HYPEJ26 e o day trade em conferência até haver contrato e fluxo
   funcional inequívocos.
