# IndFlow — Controle de Acesso: correção de máquinas sem device

Data: 23/10/2026 (America/Bahia)

## Problema
A máquina PLAINA, cadastrada em GestFlow/IndFlow > Devices sem dispositivo de produção,
existia no Painel Industrial, mas não aparecia para vincular leitor no Controle de Acesso.

## Correção
- Controle de Acesso lê máquinas pela mesma função de Devices: `modules.devices.routes._machine_rows`.
- Máquinas sem dispositivo de produção são selecionáveis no cadastro do leitor.
- Permanece obrigatório que a máquina pertença à empresa autenticada e não esteja arquivada.
- Leitor ESP32 de crachá continua independente do sensor/ESP de produção.
- A tela de Controle de Acesso desloca o conteúdo quando o menu lateral é expandido.
- Teste de regressão valida PLAINA, cliente diferente e máquina arquivada.

## Arquivos alterados
- `apps/indflow/modules/acesso/routes.py` (524 para 531 linhas)
- `apps/indflow/templates/base.html` (402 para 404 linhas)
- `apps/indflow/tests/test_acesso_backend.py` (172 para 210 linhas)

## Instalação e validação
Aplicar o ZIP de somente alterações na raiz do repositório `GESTFLOW` e fazer backup dos 3 arquivos.
`python -m compileall -q apps/indflow apps/gestflow/access_runtime.py`
`python -m pytest -q apps/indflow/tests/test_acesso_backend.py`
Resultado esperado: `5 passed`.
Publicar GitHub/Railway apenas depois de a compilação e os testes passarem.

## Após implantação
Abra `IndFlow > Controle de Acesso`, recarregue (`Ctrl+F5`), e verifique PLAINA na seleção
"Máquina" na seção "Leitores ESP32". Crie o leitor `ESP32_CRACHA_01` e salve sua chave
em local seguro. O firmware de leitura remota ainda requer integração separada.
