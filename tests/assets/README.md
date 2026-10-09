# CSS de referência para testes offline

`bootstrap-5.3.3.min.css` é uma cópia sem modificações do CSS distribuído em:
https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css

É a mesma versão referenciada pela página Fundamentus. Os testes de UI
interceptam a requisição do CDN e respondem com este arquivo para verificar
layout real sem rede. A aplicação continua usando sua referência original.

Bootstrap é Copyright 2011–2024 The Bootstrap Authors, sob licença MIT.
O cabeçalho de copyright/licença original foi preservado no arquivo.
Ao atualizar a versão da página, atualizar este fixture e o teste de UI juntos.
