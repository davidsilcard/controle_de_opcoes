#Objetivo desta aplicacao controlar as aplicacoes financeiras via opcoes, pois facilmente se perde o controle dos dados e datas.
Olhando sempre com a visao cliente leigo, a plataforma deve sempre estar de forma didatica e com avisos claros sobre o que o cliente esta decidindo.

#Sobre arquitetura, sempre a plataforma devera estar dividida por responsabilidades e estrategias.

#cada aba representa uma estrategia operacional com contrato funcional proprio; refatoracoes de UI, shell, partial, cache ou backend nao podem remover funcionalidades existentes da estrategia
#se uma nova arquitetura nao comportar toda a funcionalidade anterior, mantenha implementacao especifica ou duplique temporariamente o comportamento por estrategia ate haver paridade funcional comprovada
#so remover fluxo legado ou funcionalidade depois que a nova implementacao da estrategia estiver completa e validada

#sempre atualize o readme com os comandos novos e melhorias feitas
#mudancas operacionais de deploy, VPS, Docker, systemd e comandos de atualizacao devem refletir no README na secao correspondente
#nao adicionar skills ou plugins ao projeto por padrao; so documente isso quando houver um fluxo recorrente, reutilizavel e realmente necessario

## Continuidade obrigatoria entre chats

Antes de investigar em profundidade ou alterar esta aplicacao:

1. Leia `docs/guia-manutencao.md` por completo.
2. Leia o status e o registro de continuidade de `docs/plano-mestre-evolucao-seguranca.md`,
   e o contrato da estrategia afetada em `docs/contrato-funcional-atual.md`.
3. Confira branch, `git status`, diff e commits recentes. Preserve alteracoes que nao
   sejam suas. Memoria de outro chat nao comprova o estado atual do Git, CI ou VPS.
4. Informe o recorte e o plano de testes antes de editar. Diagnostico nao autoriza
   reparo de dados nem deploy; respeite a autorizacao atual do usuario.

O usuario trabalha sozinho: use `main`, sem criar outra branch por padrao. Para
alteracoes autorizadas, revise, teste, atualize README e registro de continuidade,
faca commit e push. Deploy usa somente `deploy/scripts/update-vps.sh` e exige CI
PostgreSQL e smoke Docker verdes no SHA publicado. Nunca contorne um bloqueio de
permissoes, ownership ou Git para forcar a publicacao.

Explique de forma curta e didatica. Se o usuario precisar executar uma operacao
complexa, passe um comando por vez e aguarde o resultado. Nao adivinhe dados.
Lancamentos manuais nao exigem comprovante; isso nao autoriza inventar uma correcao
historica. Regras duraveis ficam no guia; status e evidencias ficam no plano.
