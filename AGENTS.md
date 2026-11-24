# Retomada do projeto

1. Leia [continuidade](docs/continuidade.md) e [estado operacional](docs/estado-operacional.md).
2. Confira a árvore e o histórico Git. Consulte a fonte indicada antes de agir sobre dados, produção ou uma pendência antiga.
3. Planeje as alterações antes de escrever. Explique o impacto para quem usa a aplicação e questione propostas que prejudiquem a precisão, o histórico ou a operação.
4. Trabalhe na `main`. Revise e valide a entrega, faça commit e push e, quando a versão da aplicação precisar subir, use o fluxo oficial de release do README.
5. Execute diretamente os comandos da VPS pelo alias SSH `hostinger-opcoes`. Use o acesso PostgreSQL da aplicação para diagnósticos autorizados. Quando só o usuário puder executar uma etapa, passe um comando por vez se o procedimento for complexo.
6. Se a tarefa mudar o estado operacional, uma decisão ou uma pendência, atualize os arquivos de retomada com a evidência, a data e o próximo passo. Registre informações suficientes para continuar sem o histórico do chat.

## Regras do projeto

- Mantenha as operações com opções, seus valores e suas datas compreensíveis para o investidor. Mostre avisos claros sobre os efeitos de cada decisão.
- Divida a aplicação por responsabilidades e estratégias. Cada aba tem contrato funcional próprio. Preserve as funções existentes em alterações de interface, carregamento progressivo, cache e backend.
- Mantenha a implementação específica ou duplique temporariamente o comportamento por estratégia quando faltar paridade. Remova o fluxo legado depois de comprovar a paridade na nova implementação.
- Atualize o README com comandos e melhorias. Registre mudanças de deploy, VPS, Docker, systemd e atualização na seção operacional correspondente.
- Use ou sugira skills, plugins e agentes quando agregarem ao trabalho. Só adicione ou documente uma dependência desse tipo no projeto quando houver necessidade recorrente e reutilizável.
