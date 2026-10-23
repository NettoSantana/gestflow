# IndFlow — Controle de Acesso por Crachá

Atualizado em 23/10/2026. Este pacote altera exclusivamente o módulo web GestFlow/IndFlow. Não altera firmware ESP32, relés ou emergência.

## O que está pronto

- Subitem **Controle de Acesso** no IndFlow, com liberação por permissões do GestFlow.
- Cadastro de funcionários e matrícula/setor.
- Cadastro de leitor vinculado a uma máquina do cliente.
- Chave de acesso individual de cada leitor, gerada uma única vez.
- Solicitação de captura válida por 45 segundos, com tela aguardando confirmação.
- Fluxo **ESP32 consulta -> aproxima crachá -> ESP32 grava -> confirma**; somente depois há mensagem de sucesso.
- Bloqueio de crachá mestre, de duplicatas, de acesso entre empresas e de comando expirado.
- Permissões por máquina (autorizar/revogar) somente concluídas após confirmação do leitor.
- Histórico de eventos pela nova API, com deduplicação e fonte de horário.

## O que ainda NÃO está funcionando no ESP32 atual

O ESP32 instalado não implementa as novas rotas `/acesso/iot/`. Por isso, antes de uma atualização específica do firmware, **o painel não poderá receber uma leitura real** e mostrará 'aguardando dispositivo' ou 'prazo esgotado'. Não apresente a função como liberada em produção antes dessa segunda etapa.

O histórico no Google Sheets e a segurança de operação continuam inalterados. A migração dos eventos para o novo backend é opcional após testes.

## Onde estão os arquivos

- `apps/indflow/modules/acesso/routes.py` — rotas HTTP e tabelas SQLite.
- `apps/indflow/modules/acesso/templates/acesso_home.html` — tela de cadastro.
- `apps/indflow/static/acesso.js` — leitura aguardando confirmação do ESP32.
- `apps/indflow/static/acesso.css` — interface responsiva.
- `apps/indflow/modules/acesso/INTEGRACAO_ESP32.md` — contrato de APIs para o firmware.
- `apps/indflow/tests/test_acesso_backend.py` — testes SQLite e fluxo de confirmação.
- `apps/indflow/server.py` — registro do novo módulo.
- `apps/indflow/modules/access_control.py` — telas e ações autorizadas.
- `apps/indflow/templates/base.html` — menu lateral.
- `apps/gestflow/access_runtime.py` — permissão do novo subitem.

## Como validar

1. Instale os arquivos nos dois serviços e faça backup dos bancos persistentes.
2. Configure permissão `Controle de Acesso / Crachás` na área de perfis do GestFlow.
3. No IndFlow, teste cadastrar funcionário e leitor; guarde a chave exibida.
4. Tente vincular um crachá sem atualizar o ESP: a ação DEVE aguardar e expirar, SEM sucesso falso.
5. Após atualizar o firmware: teste autorização, mestre, duplicidade, leitor desconectado, revogação, reenvio de log e retorno da internet.
6. Só depois valide com a potência da máquina, seguindo o procedimento de segurança industrial da instalação.

## Testes executados

Testes locais isolados do SQLite: cadastro, captura e confirmação, bloqueio de mestre e duplicatas, revogação, idempotência do log, isolamento básico entre empresas e proteção CSRF. Quatro testes passaram. O aplicativo Flask completo **não foi iniciado** no ambiente de preparação por falta das dependências instaladas; compile e execute os testes de integração no seu ambiente antes de publicar no Railway.
