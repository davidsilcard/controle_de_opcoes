# Workflow: Opções

## Processo de desenvolvimento
1. **Planejamento:** Consulte o [estado operacional](../docs/estado-operacional.md) e defina escopo, efeitos e critérios de aceitação.
2. **Implementação:** Siga os padrões do projeto e preserve os contratos da web e da CLI.
3. **Validação:** Execute `uv run pytest` em ambiente isolado. Consulte a [especificação do CI](../docs/spec-ci-postgresql.md) para validação com PostgreSQL e Chromium.
4. **Documentação e publicação:** Atualize README e estado operacional conforme o impacto, faça commit e push na `main` e confira o CI. Siga o [fluxo de publicação](../README.md#atualizar-a-aplicação) quando houver deploy.

## Padrões de código
- Use tipos nas fronteiras dos módulos e mantenha responsabilidades separadas entre coleta, estratégias, web e apuração.
- PostgreSQL para persistência. Use banco descartável para testes de integração.
