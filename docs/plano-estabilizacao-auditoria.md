# Plano de estabilização do controle de opções

## Objetivo e limites

Separar o que aconteceu na operação, o cadastro do contrato, a garantia declarada,
o estoque e o caixa. Uma confirmação não deve reabrir outra nem recalcular valores
financeiros sem mudança financeira explícita. Cada estratégia mantém seu próprio
fluxo operacional. Não preencher históricos por inferência ou refazer o ledger em lote.

## Etapa 1 — contenção e clareza (esta entrega)

- Separar filas de contrato, garantia declarada e vínculo da ação exercida.
- Tratar despesas sem rateio como informação; não certificar contabilização no caixa
  nem conciliação fiscal individual apenas pela existência de uma marca no cadastro.
- Derivar garantia da Cash-Covered Put por strike × quantidade quando não preservada.
  Para Covered Call, aceitar declaração histórica, sem exigir nota para o capital.
- Não excluir resultado conhecido por faltar strike, vencimento ou capital. Calcular
  retorno apenas com resultado e base disponíveis. `REALIZED` ausente não significa zero.
- Preservar valores zero e motivos ao editar observações. Gravar posição e sincronização
  financeira na mesma transação, comparando com a posição bloqueada na transação.
- Não remover edição legada de recompra antes de existir fluxo específico equivalente.

### Testes e aceitação

1. Confirmação parcial não apaga campos anteriores nem usa fonte antiga para novo dado.
2. Declarar garantia não reabre auditoria documental concluída.
3. Nota sem rateio não exige novo preenchimento de strike, vencimento ou capital.
4. Resultado desconhecido fica fora do ponderado; zero efetivamente lançado entra.
5. Editar observação de expiração, exercício ou recompra não altera o ledger.
6. Falha na sincronização financeira desfaz a atualização da posição.
7. Simular a nova classificação com dados atuais antes da publicação, sem gravações.
8. Publicar via procedimento versionado, verificar versão, saúde, lista e impressão
   digital do ledger. Sem reparo histórico financeiro nesta etapa.

Validação da entrega: 96 testes das áreas alteradas aprovados com PostgreSQL isolado,
incluindo rollback real da posição e do ledger após falha simulada de sincronização.
Nenhum teste foi executado contra a base financeira real. A suíte geral ainda possui
falhas legadas descritas abaixo; a aprovação deste recorte não certifica toda a aplicação.

## Etapa 2 — fronteiras de gravação e migrações (próxima entrega)

- Corrigir separadamente o limitador de login para limite de uma tentativa e revisar
  confiança em cabeçalhos de proxy, preservando o backend restrito à interface local.
- Introduzir migrações versionadas explícitas. Retirar DDL e normalizações globais
  das consultas e gravações usuais, preservando compatibilidade com a base existente.
- Criar comandos específicos por estratégia para recompra total/parcial, exercício e
  expiração, com validação, atomicidade e idempotência.
- Só restringir a grade genérica após testes comprovarem paridade funcional.
- Criar vínculo estruturado de despesa compartilhada com a nota e posições; conferir
  existência/unicidade no caixa, sem estimar rateio individual.

Antes de executar: especificar migração/reversão, testar em cópia isolada e apresentar
o impacto. Migrações ou backfills financeiros exigem simulação e evidência por posição.

### Dívida de testes identificada na comparação com a versão publicada

A suíte completa da versão `2b96eb9` também falha no ambiente PostgreSQL isolado.
Não confundir essas falhas com certificação de toda a aplicação. Foram identificados:
expectativas antigas de resultado bruto versus líquido e de HTML/carregamento parcial;
fixtures que tentam editar campos protegidos ou usar ação na estratégia Ranking;
inicialização de settings em schema ainda inexistente; e limite de login igual a um.
A próxima etapa deve corrigir os testes com fixtures válidas e tratar defeitos reais
em mudanças separadas, sem enfraquecer validações financeiras para fazer testes passarem.

## Etapa 3 — fechar o histórico com evidência

- Pedir somente informações que continuem faltando após a separação dos estados.
- Guardar fonte por campo e evento, distinguindo nota, cadastro de mercado e declaração.
- Para strike histórico ajustado, conferir a data da fonte; não usar um preço atual
  como prova automática do valor válido no passado.
- Aplicar correções isoladas, conferir caixa/estoque/DARF e testar repetição idempotente.

## Publicação e espaço na VPS

Revisar diff, testar, fazer commit e push na `main`; executar somente:

```bash
cd /home/david/apps/controle_de_opcoes && bash deploy/scripts/update-vps.sh
```

O script verifica espaço, recompila, substitui os containers da aplicação e remove
imagens antigas sem uso do projeto, limitando o cache de build. Não apagar volumes,
dados ou backups para forçar publicação. Em falha, investigar sem contornar permissões.
