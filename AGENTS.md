#Objetivo desta aplicacao controlar as aplicacoes financeiras via opcoes, pois facilmente se perde o controle dos dados e datas.
Olhando sempre com a visao cliente leigo, a plataforma deve sempre estar de forma didatica e com avisos claros sobre o que o cliente esta decidindo.

#Sobre arquitetura, sempre a plataforma devera estar dividida por responsabilidades e estrategias.

#cada aba representa uma estrategia operacional com contrato funcional proprio; refatoracoes de UI, shell, partial, cache ou backend nao podem remover funcionalidades existentes da estrategia
#se uma nova arquitetura nao comportar toda a funcionalidade anterior, mantenha implementacao especifica ou duplique temporariamente o comportamento por estrategia ate haver paridade funcional comprovada
#so remover fluxo legado ou funcionalidade depois que a nova implementacao da estrategia estiver completa e validada

#sempre atualize o readme com os comandos novos e melhorias feitas
#mudancas operacionais de deploy, VPS, Docker, systemd e comandos de atualizacao devem refletir no README na secao correspondente
#nao adicionar skills ou plugins ao projeto por padrao; so documente isso quando houver um fluxo recorrente, reutilizavel e realmente necessario
