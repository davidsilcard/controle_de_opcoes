# Execução: UX e compartilhamento da Fundamentus

Plano aprovado para execução em 09/10/2026. Destino prioritário: Google
Planilhas, localidade Brasil. Proposta escolhida: tabela ampla.

## Contrato e escopo

Manter 27 colunas fundamentais e 13 de PUT, filtros por coluna (AND, texto e
operadores numéricos), ordenação ascendente/descendente, ausentes ao final e
Score PUT inicialmente decrescente. Preservar status/data/limite/janela,
rankings, entradas/saídas, setores, avisos, calendário e fonte bid/último.
Não modificar coleta, regras financeiras ou banco de dados.

## Etapas de execução

1. Separar CSS/JS da aba e identificar colunas por chave estável, com valores
   numéricos brutos. Inicialização idempotente após HTMX, por tabela.
2. Usar largura fluida, manter cabeçalhos/Papel fixos, oferecer Todas,
   Essenciais e escolha individual; persistir apenas preferência de colunas.
   Indicar filtros ativos em colunas ocultas e manter todas acessíveis.
3. Adicionar seleção, TSV para Google Planilhas, texto por ativo para WhatsApp
   e CSV. Escopo explícito: selecionadas que passaram nos filtros, ou todas
   filtradas quando não há seleção. Uma seleção totalmente oculta não pode
   copiar outras linhas silenciosamente. Escolher colunas exibidas ou todas.
   Tratar nulos, zero, negativos, percentuais, acentos e fórmulas em texto.
   Se a Clipboard API falhar, oferecer texto selecionável para cópia manual.
4. Validar comportamento real no navegador, contratos Python e layout;
   documentar, commit/push na main, CI verde no SHA publicado. Fornecer
   publicação pelo fluxo oficial, sem comandos Docker improvisados.

## Critérios de aceitação

- Os filtros e ordenações continuam funcionando nas duas tabelas, inclusive
  depois de adicionar seleção ou esconder colunas; seus estados são separados.
- Seleção, ordem e valores da saída correspondem exatamente ao recorte atual.
  Zero não vira ausência; negativos e percentuais conservam seu significado.
- Cópia não inclui botões, setas, HTML ou campos de filtro. Texto inclui datas
  de referência; PUT inclui vencimento e fonte/execução.
- Preferências visuais persistem, mas seleção/filtros de outro snapshot não.
- A página aproveita telas largas; rolagem horizontal fica nas tabelas, com
  cabeçalhos/Papel visíveis e sem sobreposição em zoom 200%.
- Botões, filtros e seleção acessíveis por teclado; aria-sort e feedback.
- Avisos e blocos funcionais anteriores continuam presentes após HTMX.
- Validar números no Google Planilhas Brasil. Não afirmar colagem real sem
  verificação no aplicativo; testes de serialização não equivalem a isso.
- Testes de banco usam somente PostgreSQL descartável; skips locais são
  relatados e não substituem a suíte completa do CI.

## Validação e resultado

- Implementados layout amplo, preferências visuais por tabela, seleção e
  serializadores TSV/texto/CSV, com identificação por chave e valores tipados.
- Regressão direcionada: 35 testes aprovados e 7 ignorados por ausência de
  PostgreSQL local (calendário, estratégia, progressive pages, contratos e cache).
- Suíte local completa: 325 aprovados e 94 ignorados; os skips locais não
  equivalem à validação PostgreSQL do CI. Um cenário adicional de HTMX foi
  acrescentado depois dessa execução completa e passou na suíte de UI final.
- UI final em Chrome headless com templates e CSS reais: 9 testes aprovados. Inclui
  independência entre tabelas, operadores/AND, ordem, seleção oculta, exportação
  com zero/negativos/nulos/percentuais, CSV e fórmulas em texto, recusa do clipboard,
  preferências, inicialização repetida e substituição real do painel HTMX,
  colunas personalizadas e larguras 375/1366/1920/3440 com zoom 200%.
- Capturas dos templates reais revisadas em tela larga e celular; filtros
  têm largura controlada e a navegação móvel não cobre os controles da tabela.
- CI da entrega principal `ac9ac3d`: 416 aprovados e 4 ignorados, com PostgreSQL
  descartável e Chromium. Revisão complementar: gráfico de setores responsivo
  incluído nos dados dos 9 testes de UI, todos aprovados novamente. O CI do
  commit final é conferido antes de fornecer a publicação.
- Os testes validam a serialização brasileira e o comportamento do navegador;
  ainda não houve colagem em uma conta real do Google Planilhas ou WhatsApp.
  Conferir isso após publicação; não representar esse teste como realizado.
- A suíte completa com PostgreSQL descartável e Chromium é obrigatória no CI
  do commit publicado. O resultado do SHA exato será informado na entrega.

Reversão: git revert do commit e release oficial; nenhuma migração de banco
é necessária.
