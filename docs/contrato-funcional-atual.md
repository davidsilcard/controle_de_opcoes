# Contrato funcional atual

Este documento congela o comportamento existente antes da modularização da Web. Ele
não descreve a arquitetura-alvo nem autoriza remoção de telas, endpoints ou campos.
Cada mudança de estratégia deve preservar o contrato aplicável ou criar uma transição
testada e documentada.

## Regras transversais

- dados reais e simulados permanecem separados;
- cada usuário vê apenas o próprio schema;
- tela de estratégia mantém seus guards e sua forma própria de exercício, expiração
  e fechamento;
- marcação manual não exige comprovante, mas exige dados coerentes para produzir
  efeito financeiro;
- auditoria denuncia divergência e não aplica correção global automaticamente;
- filtros atuais continuam disponíveis com seus parâmetros; a persistência legada em
  `GET` será migrada para ação explícita em `POST`, sem perder o resultado filtrado;
- nenhum refactor pode remover uma seção existente só porque ela migrou para partial
  ou shell diferente.

## Páginas e ações obrigatórias

| Rota | Blocos e ações que devem continuar disponíveis | Proteção atual |
|---|---|---|
| `/login`, `/first-access`, `/logout` | login, primeiro acesso, troca de senha, expiração de sessão e logout | CSRF, rate limit e cookie de sessão |
| `/` e `/partial/ranking` | oportunidades, watchlist, recorrência, segmentos, posições reais/simuladas e resultado de opções compradas | filtros e dados de snapshot |
| `/covered-call` | estoque consolidado, ações livres/reservadas, sugestões, calls abertas, prêmio, resultado, recompra, expiração e exercício | guarda de cobertura e estoque consolidado |
| `/covered-call/partial/live`, `/covered-call/partial/audit` | atualização de mercado e auditoria da estratégia | dados não podem cruzar modo real/simulado |
| `/cash-covered-put` | caixa, garantia, depósitos/retiradas, histórico financeiro, puts abertas, oportunidades, recompra, expiração e exercício | guarda de PUT, garantia e caixa |
| `/fundamentus`, `/fundamentus/partial/dashboard` | aprovadas/reprovadas, histórico, setores e oportunidades de PUT | integridade do snapshot publicado |
| `/positions`, `/positions/partial/live` | cadastro, filtros, posições abertas/fechadas, estoque, prêmio, realizado bruto/taxas/líquido e edição permitida | campos protegidos por estratégia não usam a grade genérica |
| `/darf` | competência, resultado mensal, prejuízo, IRRF, geração e pagamento | DARF separada do fluxo didático de caixa |
| `/audit` | posição, ledger, estoque, exercícios, resultado e órfãos | achado aponta para a origem, sem sync global |
| `/performance` | Cash-Covered Put, Covered Call, contrato, garantia, resultado, custos e ciclo Wheel | ciclo Wheel não soma agregados incompatíveis |
| `/settings` | parâmetros, automação, execuções recentes e próxima execução | dados isolados por usuário |

## Endpoints de mutação que exigem teste de efeito

- `/finance/add`, `/finance/assign`, `/finance/callaway`, `/finance/expire`;
- `/finance/update/<id>` e `/finance/delete/<id>` enquanto ainda existirem;
- `/darf/generate` e `/darf/pay`;
- `/positions/add`, `/positions/update/<id>`, `/positions/delete/<id>`;
- `/positions/register-premium/<id>` e `/positions/recalc-premium/<id>`;
- `/holdings/upsert`;
- operações de contrato, evidência e ciclos Wheel em `/performance`.

Toda alteração nesses endpoints deve ter, no mínimo, teste de sucesso, rejeição de
entrada inválida, rollback em falha simulada, repetição/idempotência, isolamento
real/simulado e isolamento entre usuários quando aplicável.

## Interfaces não-Web

| Interface | Contrato preservado |
|---|---|
| CLI | nomes, opções, códigos de saída e efeitos de `position`, `scrape`, `report`, `snapshot`, `fundamentus`, `tax`, `user`, `service-run`, `db` e `repair` |
| Edge | `/health`, cotações, busca, métricas, preview, ordens, token e WebSocket; mudanças de escopo não removem leitura de cotações autorizada |

## Evidência de regressão

Os testes existentes de contratos de estratégia, guards, auditoria, fluxos de
exercício, DARF, Posições e Wheel são parte deste contrato. A Entrega 0 adiciona CI
com PostgreSQL 16 para que os testes marcados `requires_postgres` sejam executados,
e não apenas ignorados.
