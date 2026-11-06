# SDD — Ambiente dos testes PostgreSQL e Chromium

## Problema e evidência

Em 06/11/2026, a execução [42296070817](https://github.com/davidsilcard/controle_de_opcoes/actions/runs/42296070817),
no commit `0c656b5e9fccf807aa447bd2e6a7aa24dda209f8`, falhou na instalação
de Chromium, antes da suíte de testes. O job recebeu Ubuntu 26.04.1 porque
`.github/workflows/tests.yml` usa o alias móvel `ubuntu-latest`. O instalador
da versão de Playwright bloqueada pelo projeto recusou esse sistema.

A execução aprovada [39852982376](https://github.com/davidsilcard/controle_de_opcoes/actions/runs/39852982376)
usou Ubuntu 24.04. A especificação adota esse ambiente para executar o contrato
atual de dependências. O suporte de versões recentes do Playwright a outros
sistemas não comprova compatibilidade da versão `1.57.0` do `uv.lock`.

## Requisitos

| ID | Comportamento exigido |
| --- | --- |
| R1 | O job `test` executa em `ubuntu-24.04`, com versão de distribuição explícita. |
| R2 | As dependências são instaladas por `uv sync --locked --dev`, com Python 3.12 e o lock existente. |
| R3 | Chromium é instalado com suas dependências de sistema, e `OPCOES_REQUIRE_BROWSER_TESTS=1` mantém obrigatórios os testes de interface. |
| R4 | A suíte completa executa com o serviço PostgreSQL 16 descartável configurado pelo workflow. |
| R5 | Falha de instalação ou de teste reprova o job. A publicação continua exigindo CI aprovado para o mesmo SHA. |
| R6 | O README explica a escolha do ambiente e como consultar e acompanhar a execução. |

## Decisão de arquitetura

O workflow é responsável pelo ambiente de validação. `pyproject.toml` e
`uv.lock` definem as dependências da aplicação. O script de release usa o
resultado do workflow para autorizar a publicação. A correção fica no ambiente
de CI, preservando os contratos funcionais e de publicação existentes.

Substituir o alias móvel por `ubuntu-24.04` impede a troca automática da versão
da distribuição. A imagem continua recebendo atualizações de manutenção do
GitHub. Uma futura migração de distribuição exige revisão da compatibilidade
do Playwright bloqueado e aprovação da suíte completa no novo ambiente.

A mudança mantém o job e o workflow com os nomes atuais, os gatilhos de push
na `main` e pull request, a instalação obrigatória de Chromium, o PostgreSQL
isolado e a propagação de erros. O comentário junto ao runner aponta para este
contrato.

## Plano de implementação e validação

1. Registrar esta especificação antes de alterar o workflow.
2. Alterar somente a seleção do runner e adicionar o comentário de decisão.
3. Atualizar o README com o ambiente declarado e os comandos de diagnóstico.
4. Revisar o diff, conferir os requisitos R1 a R6 e executar `git diff --check`.
5. Fazer commit e push na `main`, iniciando a execução real do GitHub Actions.
6. Acompanhar a execução do SHA enviado até o término, examinando o runner,
   a instalação de Chromium, a suíte completa e eventuais skips.
7. Em falha, diagnosticar a etapa e corrigir sua causa, preservando os requisitos.

## Critérios de aceite

| Critério | Evidência necessária |
| --- | --- |
| CA1 — Ambiente | Log de inicialização identifica `ubuntu-24.04`. |
| CA2 — Navegador | Etapa de instalação de Chromium concluída com sucesso. |
| CA3 — Suíte | Etapa de pytest executada e aprovada, com PostgreSQL descartável e testes de interface obrigatórios. |
| CA4 — Rastreabilidade | Execução aprovada aponta para o SHA final publicado na `main`. |
| CA5 — Escopo | Diff restrito ao workflow, README e esta especificação. |

A execução real do GitHub Actions é a validação de integração desta mudança.
O histórico de Actions registra o SHA, o ambiente e o resultado de cada etapa.
Testes locais sem PostgreSQL e Chromium não substituem os critérios acima.

## Reversão e manutenção

Uma reversão usa um commit revisado na `main` e passa novamente pelo CI.
Restaurar `ubuntu-latest` reintroduz o risco que originou a falha, portanto
uma revisão do runner deve escolher uma distribuição validada com o lock.

A entrega desta correção é a publicação do workflow e sua execução aprovada
no GitHub. O gate de release existente continua controlando publicações da
aplicação na VPS.

## Referências

- [Runners hospedados pelo GitHub](https://docs.github.com/en/actions/reference/runners/github-hosted-runners).
- [Instalação e requisitos do Playwright Python](https://playwright.dev/python/docs/intro#system-requirements).
