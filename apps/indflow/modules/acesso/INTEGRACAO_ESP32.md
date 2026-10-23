# IndFlow — Controle de Acesso por Crachá (integração ESP32)

Atualização: 23/10/2026. Módulo backend/UI preparado. **O firmware ESP32 existente NÃO foi alterado** neste pacote. Assim, as operações ficarão aguardando o leitor até existir firmware compatível. Não há cadastro fictício.

## Configuração inicial

1. No GestFlow, permita a tela **Controle de Acesso / Crachás** ao perfil do usuário IndFlow (ações visualizar, criar e editar), ou use perfil administrativo.
2. No IndFlow, cadastre uma máquina em `/devices/` caso ainda não exista.
3. Acesse `/acesso/`, cadastre o funcionário e o leitor ESP32 daquela máquina.
4. Copie a chave individual do leitor: é exibida UMA vez e armazenada no banco somente como hash SHA-256.
5. A chave deverá ser configurada no firmware ESP32 futuro (sem hardcode em repositório público); a API deve ser acessada por HTTPS.
6. Selecione **Vincular crachá**, o funcionário e o leitor: abre uma janela de 45 segundos.
7. Só depois do ESP confirmar a gravação local, a tela exibirá **Funcionário cadastrado com sucesso**.

## Protocolo do dispositivo (requer novo firmware)

Endpoints estão sob o prefixo `/acesso` do IndFlow. Todas as rotas `/acesso/iot/*` exigem `Authorization: Bearer <CHAVE_INDIVIDUAL_DO_LEITOR>` em cada requisição. O header opcional `X-Firmware-Version` informa a versão.

### 1. Consultar comando (polling, por exemplo a cada 2 segundos)

`GET /acesso/iot/comandos`

Resposta sem comando: `{"ok":true,"comando":null}`.

Resposta com captura:

`{"ok":true,"comando":{"id":"UUID","operacao":"capturar","estado":"aguardando_leitura","acao":"aguardar_cracha", "expira_em":"ISO-UTC", "funcionario_id":"UUID"}}`

**Regras para captura:** após receber `aguardar_cracha`, entrar em modo de vinculação somente enquanto a janela estiver válida. A leitura Wiegand deve conter 26 bits válidos. O leitor não deve acionar relés nem liberar partida durante esse modo. Após concluir ou expirar, voltar imediatamente à operação normal. Cartão mestre não pode ser capturado.

### 2. Relatar captura do cartão ao IndFlow

`POST /acesso/iot/captura`

`{"comando_id":"UUID","cracha_uid":"00D0C49D","bits":26}`

Se aceito, servidor retorna `{"ok":true,"comando_id":"UUID","acao":"gravar_cracha","cracha_uid":"00D0C49D", "aviso":"..."}`.

**Regra:** somente após gravar de forma persistente na memória local, confirmar abaixo. Se falhar, responder `gravado:false` e explicar. O servidor valida duplicidade, cliente, leitor, comando e expiração.

### 3. Confirmar gravação no ESP

`POST /acesso/iot/confirmacao`

`{"comando_id":"UUID","gravado":true}`

OU, em caso de falha:

`{"comando_id":"UUID","gravado":false,"erro":"Falha ao gravar memória local"}`

Após o servidor gravar a confirmação, `GET /acesso/api/comandos/{id}` passa a mostrar `estado=confirmado` e a UI exibe sucesso. Nunca simular essa confirmação na interface.

### 4. Permissões em outras máquinas

Um funcionário possui apenas um UID por empresa. Para liberar o mesmo crachá em outra máquina, o painel cria comando `operacao=permitir`, `acao=gravar_cracha`, `cracha_uid=<UID>`. O leitor correspondente consulta seu próprio comando, grava a autorização local, confirma pelo endpoint 3, e a permissão vira `ativa`. Para revogar, `operacao=revogar`, `acao=remover_cracha`, confirmando somente após remoção persistente. Quando a rede está indisponível, a permissão permanece pendente; não informar que foi aplicada.

### 5. Envio de eventos (opcional até migrar do Google Sheets)

`POST /acesso/iot/eventos`

`{"evento_id":"UUID_UNICO_POR_EVENTO","evento":"CARTAO_LIDO","cracha_uid":"00D0C49D","status":"OK","epoch":1792773301,"fonte_hora":"ntp_recuperado","observacao":"Bits Wiegand: 26"}`

O campo `evento_id` deve ser persistente e idempotente em reenvios. A API grava a hora informada e separadamente a hora de recepção UTC. Resposta indica `duplicado` quando o evento já existe. Eventos offline com timestamp ainda impreciso NÃO devem ser publicados como confiáveis. O módulo antigo de Google Sheets permanece operando até migrar, com validação dos logs.

## Segurança e operação industrial

- A identidade do leitor é autenticada por chave diferente para cada leitor; mantenha HTTPS, proteja os segredos e substitua a chave se houver vazamento.
- Sempre validar o estado do comando e a persistência local antes da confirmação.
- Não usar autorização de crachá como substituto de circuito de segurança NR-12, emergência e intertravamentos físicos.
- Após interrupção de energia, a máquina não pode religar automaticamente devido a uma autorização armazenada.
- Antes de conectar aos relés reais, testar captura, expiração, bloqueio de crachá mestre, duplicidade, reconexão, permissões e histórico em bancada.
- Cuidado: cadastro pelo cartão mestre físico anterior e alterações online devem ser conciliados para evitar listas divergentes quando o firmware de integração for desenvolvido.

## Implantação

Serviço IndFlow: incorporar os arquivos alterados a `apps/indflow/`; serviço GestFlow: incorporar `apps/gestflow/access_runtime.py` atualizado. Os bancos permanecem separados; apenas o IndFlow cria tabelas novas `acesso_*` em seu SQLite.

**Não instalar nenhum `.ino` deste pacote:** o pacote contém somente o software web e documentação do protocolo. Será necessário o firmware completo ESP32 atual para a segunda fase da integração física.
