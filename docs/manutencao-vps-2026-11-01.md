# Manutenção da VPS em 01/11/2026

## Objetivo e autorização

Atualizar o sistema da VPS Hostinger após aviso da CVE-2026-98432 e acompanhar
até o kernel corrigido estar em execução com os serviços validados. O usuário
autorizou a instalação das atualizações disponíveis e o reinício atual. Em
resposta específica, autorizou também instalar a correção oficial dessa CVE e
reiniciar futuramente, mesmo em outro dia e sem nova confirmação, com validação
posterior do banco e da aplicação.

Nenhuma ordem de mercado, registro financeiro, migração ou deploy da aplicação
foi realizado nesta manutenção. Não foram alterados firewall, acesso SSH,
repositórios APT, permissões ou bloqueios de pacotes.

## Diagnóstico inicial

- Ubuntu 24.04 LTS, kernel `6.8.0-147-generic`.
- `linux-virtual` e `linux-image-virtual`: instalados e candidatos em
  `6.8.0-147.147`, inclusive após atualizar os índices oficiais.
- PostgreSQL 16/main online; Docker, Caddy e aplicação ativos.
- Sem unidades falhas; aproximadamente 703 MB livres em `/boot`.
- A página oficial Ubuntu da CVE, atualizada em 30/10, ainda informava correção
  em andamento para o kernel genérico do Ubuntu 24.04. O pacote corrigido não
  estava disponível nos repositórios configurados.

Fonte oficial: https://ubuntu.com/security/CVE-2026-98432.
Não usar o aviso de outra distribuição para certificar um pacote Ubuntu.

## Execução

1. Acesso pelo alias SSH existente `hostinger-opcoes`, com validação estrita da
   chave do host e sem expor credenciais.
2. Atualização dos índices com `apt-get update`, simulação e consulta das
   versões de kernel disponíveis. Conferidos `dpkg --audit` e serviços.
3. Confirmado retorno automático: Docker, Caddy e PostgreSQL habilitados;
   `opcoes-web` e `opcoes-edge` com política `unless-stopped`.
4. Instaladas 57 atualizações com configurações existentes preservadas.
   Incluíram Docker, containerd, AppArmor, bibliotecas e componentes do Ubuntu.
   `dpkg --audit` e `apt-get check` não apontaram pacotes quebrados.
5. Reinício controlado com `systemctl reboot`, em aproximadamente 12h27 de
   America/Sao_Paulo. A troca do identificador de boot e o uptime zerado
   comprovaram o reinício. Durante a subida, houve respostas HTTP transitórias
   sem sucesso; a validação aguardou o carregamento da aplicação.
6. Concluída a atualização de `fwupd`, que exigia dependências novas, pelo
   equivalente não interativo de `apt upgrade`:
   `apt-get --with-new-pkgs upgrade`. Foram instalados `libfwupd3` e
   `libdrm-amdgpu1`. Não houve atualização de firmware de hardware.
7. Resultado: **58 pacotes atualizados, duas dependências novas, nenhuma
   remoção**. `cloud-init` permaneceu no bloqueio manual já existente; não foi
   forçada a atualização. Não foi executado `autoremove`.

## Validação final em 12h28, America/Sao_Paulo

| Verificação | Resultado |
| --- | --- |
| `dpkg --audit` | Sem pendências |
| `apt-get check` | Aprovado |
| Simulação posterior | Zero atualizações aplicáveis; somente `cloud-init` retido |
| `systemctl --failed` | Zero unidades falhas |
| Docker, Caddy e PostgreSQL | Ativos |
| PostgreSQL 16/main, `pg_isready` | Aceitando conexões |
| `opcoes-web` e `opcoes-edge` | Em execução após o boot |
| `http://127.0.0.1:8000/login` | HTTP 200 |
| `http://127.0.0.1:8011/health` | `status: ok` |
| `https://opcoes.moven.cloud/login` | HTTP 200 |
| `https://api.moven.cloud/health` | `status: ok` |
| `needrestart` após a última instalação | Sem serviços, containers ou sessões pendentes de reinício |
| Kernel em execução | `6.8.0-147-generic` |

A manutenção geral está concluída. A correção permanente da CVE-2026-98432
**continua pendente**: o kernel em execução não mudou e não foi certificado
como corrigido. O aviso de `needrestart` de que o kernel está atualizado não
equivale a uma certificação de correção desta CVE.

## Acompanhamento até a correção

Automação vinculada a este chat, ativa a cada quatro horas:
`acompanhar-corre-o-do-kernel-da-vps`.

- Consultar o aviso oficial Ubuntu e versões dos repositórios configurados.
- Permanecer em silêncio enquanto não houver correção disponível ou mudança
  que exija ação. Não reiniciar repetidamente nem fazer atualizações gerais a
  cada verificação.
- Quando a correção oficial estiver disponível para esta família de kernel,
  simular e instalar o kernel e dependências necessários, preservando as
  configurações e bloqueios existentes, conforme autorização específica.
- Reiniciar e comprovar kernel corrigido em execução, PostgreSQL acessível e
  aplicação saudável. Somente então informar conclusão e desativar o
  acompanhamento, mantendo o chat aberto.
- Em falha ou bloqueio de aprovação, informar a ação necessária e seu motivo,
  sem contornar proteções.

O acompanhamento depende do computador ligado, aplicativo desktop em execução
e acesso ao projeto e à conexão SSH. Não foi instalado cron ou serviço de
atualização próprio na VPS. A programação fica no aplicativo e não equivale a
monitoramento contínuo do servidor.
