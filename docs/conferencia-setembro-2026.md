# Conferência parcial de setembro de 2026

Estado em 22/09/2026. Este inventário **não é uma ordem de importação**. Conferir
novamente a produção antes de cada gravação; não recriar operação existente.

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
| BBASJ252, venda de 2.300 CALLs | #34281732, R$ 1.702,00 | Não cadastrada; 2.300 BBAS3 livres na aplicação | Strike R$ 24,79, vencimento 16/10; cadastrar com despesa compartilhada marcada, sem rateio inventado. |
| CMIGJ124, venda de 2.600 CALLs | #34281732, R$ 390,00 | Não cadastrada; 2.600 CMIG4 livres | Strike R$ 12,31, vencimento 16/10; mesma regra de despesa. |
| CMIGU105, recompra de 2.100 PUTs | #34281732, débito bruto R$ 42,00 | A venda de 27/08 não está cadastrada; #34011960 comprova crédito bruto R$ 420,00 | Cadastrar primeiro a abertura histórica e depois a recompra em 04/09. Resultado bruto R$ 378,00, antes de custos da nota de 04/09. |
| CMIGV104, venda de 2.300 PUTs | #34281732, R$ 345,00 | Não cadastrada | Strike R$ 10,56, vencimento 16/10; conferir garantia antes de gravar. |
| HYPEJ26, venda líquida de 300 CALLs | #34281732, R$ 90,00 | Não cadastrada; 300 HYPE3 livres | Confirmar strike do contrato por fonte confiável. A nota também tem day trade separado de 100 vendas a R$ 0,30 e 100 compras a R$ 0,32. Não fundir as duas operações. |

A nota #34281732 registra R$ 3,44 de despesas conjuntas (liquidação R$ 0,71,
registro R$ 1,78 e emolumentos R$ 0,95) e IRRF indicado R$ 0,12. Não existe
rateio documental por ticker. Os resultados individuais devem permanecer antes
desse custo, com a referência comum marcada. O custo da nota precisa entrar
**uma única vez** no caixa por fluxo auditável; ainda não foi lançado por esta
conferência. A provisão automática de DARF não substitui a apuração mensal.

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
