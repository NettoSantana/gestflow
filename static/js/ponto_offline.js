// Caminho: static/js/ponto_offline.js
// Último recode: 2026-07-10 10:20 (America/Bahia)
// Motivo: Persistir batidas offline no navegador, restaurar jornada ao reabrir o link e manter bloqueio de 60 segundos após saída.
(function(){
    const form = document.getElementById('ponto-form-batida');
    const validationForm = document.getElementById('ponto-form-validacao');
    const pointArea = document.getElementById('ponto-area-batida');
    const statusBox = document.getElementById('ponto-sync-status');
    const pendingList = document.getElementById('ponto-pendente-lista');
    if(!form || !statusBox){return;}

    const token = form.dataset.token || '';
    const storageKey = `gestflow_ponto_offline_${token}`;
    const authKey = `gestflow_ponto_validado_${token}`;
    const statePrefix = `gestflow_ponto_estado_${token}_`;
    const exigeIntervalo = (form.dataset.exigirIntervalo || 'sim') !== 'nao';
    const campos = exigeIntervalo ? ['entrada','saida_intervalo','retorno_intervalo','saida'] : ['entrada','saida'];
    const BLOQUEIO_ENTRADA_SEGUNDOS = 60;
    let timerBloqueio = null;

    function carregarJson(chave, padrao){
        try{return JSON.parse(localStorage.getItem(chave) || JSON.stringify(padrao));}catch(e){return padrao;}
    }

    function salvarJson(chave, valor){
        try{localStorage.setItem(chave, JSON.stringify(valor));}catch(e){}
    }

    function cookieSet(nome, valor, dias){
        try{
            const maxAge = Math.max(1, Number(dias || 365)) * 24 * 60 * 60;
            document.cookie = `${encodeURIComponent(nome)}=${encodeURIComponent(valor)}; Max-Age=${maxAge}; Path=/; SameSite=Lax`;
        }catch(e){}
    }

    function cookieGet(nome){
        try{
            const alvo = `${encodeURIComponent(nome)}=`;
            return document.cookie.split(';').map(p => p.trim()).find(p => p.indexOf(alvo) === 0)?.slice(alvo.length) || '';
        }catch(e){return '';}
    }

    function carregarFila(){
        return carregarJson(storageKey, []);
    }

    function salvarFila(fila){
        salvarJson(storageKey, fila || []);
        atualizarStatus();
    }

    function dataHoje(){
        const agora = new Date();
        return `${agora.getFullYear()}-${String(agora.getMonth()+1).padStart(2,'0')}-${String(agora.getDate()).padStart(2,'0')}`;
    }

    function horaAgora(){
        const agora = new Date();
        return `${String(agora.getHours()).padStart(2,'0')}:${String(agora.getMinutes()).padStart(2,'0')}`;
    }

    function agoraIso(){
        return new Date().toISOString();
    }

    function stateKey(data){
        return `${statePrefix}${data || dataHoje()}`;
    }

    function estadoVazio(data){
        return {
            versao: 2,
            token: token,
            data_ponto: data || dataHoje(),
            exigir_intervalo: exigeIntervalo ? 'sim' : 'nao',
            jornadas: [],
            atualizado_em: agoraIso()
        };
    }

    function carregarEstado(data){
        const chave = stateKey(data || dataHoje());
        const estado = carregarJson(chave, estadoVazio(data));
        if(!Array.isArray(estado.jornadas)){estado.jornadas = [];}
        estado.data_ponto = estado.data_ponto || data || dataHoje();
        estado.token = estado.token || token;
        return estado;
    }

    function salvarEstado(estado){
        if(!estado){return;}
        estado.atualizado_em = agoraIso();
        salvarJson(stateKey(estado.data_ponto || dataHoje()), estado);
    }

    function limparEstadosAntigos(){
        try{
            const hoje = dataHoje();
            Object.keys(localStorage).forEach(function(chave){
                if(chave.indexOf(statePrefix) === 0 && chave !== stateKey(hoje)){
                    const sufixo = chave.slice(statePrefix.length);
                    if(/^\d{4}-\d{2}-\d{2}$/.test(sufixo)){
                        const diff = (new Date(`${hoje}T00:00:00`) - new Date(`${sufixo}T00:00:00`)) / 86400000;
                        if(diff > 7){localStorage.removeItem(chave);}
                    }
                }
            });
        }catch(e){}
    }

    function jornadaTemSaida(jornada){
        return !!(jornada && String(jornada.saida || '').trim());
    }

    function ultimaJornada(estado){
        if(!estado || !estado.jornadas || estado.jornadas.length === 0){return null;}
        return estado.jornadas[estado.jornadas.length - 1];
    }

    function jornadaAberta(estado){
        const ultima = ultimaJornada(estado);
        return ultima && !jornadaTemSaida(ultima) ? ultima : null;
    }

    function segundosRestantesBloqueio(estado){
        const ultima = ultimaJornada(estado);
        if(!jornadaTemSaida(ultima)){return 0;}
        const referenciaTexto = ultima.finalizado_em || ultima.atualizado_em || estado.atualizado_em;
        const referencia = new Date(referenciaTexto || 0).getTime();
        if(!referencia){return 0;}
        const decorrido = Math.floor((Date.now() - referencia) / 1000);
        return Math.max(BLOQUEIO_ENTRADA_SEGUNDOS - decorrido, 0);
    }

    function proximaAcao(estado){
        const aberta = jornadaAberta(estado);
        if(!aberta){return 'entrada';}
        return campos.find(campo => !aberta[campo]) || '';
    }

    function nomeAcao(acao){
        const nomes = {
            entrada: 'Entrada',
            saida_intervalo: 'Saída intervalo',
            retorno_intervalo: 'Retorno intervalo',
            saida: 'Saída'
        };
        return nomes[acao] || 'Ponto';
    }

    function uuid(){
        if(window.crypto && crypto.randomUUID){return crypto.randomUUID();}
        return `${Date.now()}-${Math.random().toString(16).slice(2)}`;
    }

    function lerCamposDaTela(){
        const jornada = {};
        let temValor = false;
        campos.forEach(function(campo){
            const el = document.querySelector(`[data-ponto-campo="${campo}"]`);
            const valor = el ? String(el.textContent || '').trim() : '';
            if(valor && valor !== '--:--' && valor !== '-'){
                jornada[campo] = valor;
                temValor = true;
            }
        });
        return temValor ? jornada : null;
    }

    function semearEstadoPelaTela(){
        const estado = carregarEstado();
        const fila = carregarFila();
        if((estado.jornadas || []).length > 0 || fila.length > 0){return estado;}

        const jornadaTela = lerCamposDaTela();
        if(jornadaTela){
            jornadaTela.data_ponto = dataHoje();
            jornadaTela.origem = 'servidor';
            jornadaTela.atualizado_em = agoraIso();
            if(jornadaTela.saida){jornadaTela.finalizado_em = agoraIso();}
            estado.jornadas = [jornadaTela];
            salvarEstado(estado);
        }
        return estado;
    }

    function aplicarJornadaNaTela(jornada){
        campos.forEach(function(campo){
            const el = document.querySelector(`[data-ponto-campo="${campo}"]`);
            if(el){el.textContent = jornada && jornada[campo] ? jornada[campo] : '--:--';}
        });
    }

    function desabilitarTodosBotoes(){
        form.querySelectorAll('button[name="acao"]').forEach(function(botao){botao.disabled = true;});
    }

    function mensagemBloqueio(segundos){
        segundos = Math.max(1, Number(segundos || 1));
        return segundos === 1 ? 'Aguarde 1 segundo para iniciar nova entrada.' : `Aguarde ${segundos} segundos para iniciar nova entrada.`;
    }

    function atualizarBotoesPeloEstado(){
        const estado = carregarEstado();
        const aberta = jornadaAberta(estado);
        const restante = segundosRestantesBloqueio(estado);
        const proxima = proximaAcao(estado);

        desabilitarTodosBotoes();

        if(!aberta && restante <= 0){
            aplicarJornadaNaTela(null);
        }else{
            aplicarJornadaNaTela(aberta || ultimaJornada(estado));
        }

        if(restante > 0){
            const entrada = form.querySelector('button[name="acao"][value="entrada"]');
            if(entrada){
                entrada.disabled = true;
                entrada.title = mensagemBloqueio(restante);
            }
            iniciarTimerBloqueio();
            atualizarStatus();
            return;
        }

        const botao = form.querySelector(`button[name="acao"][value="${proxima}"]`);
        if(botao){
            botao.disabled = false;
            botao.title = '';
        }
        pararTimerBloqueio();
        atualizarStatus();
    }

    function iniciarTimerBloqueio(){
        if(timerBloqueio){return;}
        timerBloqueio = setInterval(function(){
            const estado = carregarEstado();
            if(segundosRestantesBloqueio(estado) <= 0){
                pararTimerBloqueio();
            }
            atualizarBotoesPeloEstado();
        }, 1000);
    }

    function pararTimerBloqueio(){
        if(timerBloqueio){
            clearInterval(timerBloqueio);
            timerBloqueio = null;
        }
    }

    function registrarBatidaLocal(acao, hora, idBatida){
        const data = dataHoje();
        const estado = carregarEstado(data);
        let jornada = jornadaAberta(estado);

        if(acao === 'entrada'){
            const restante = segundosRestantesBloqueio(estado);
            if(!jornada && restante > 0){
                alert(mensagemBloqueio(restante));
                atualizarBotoesPeloEstado();
                return false;
            }
            if(!jornada){
                jornada = {
                    data_ponto: data,
                    origem: 'offline',
                    criado_em: agoraIso()
                };
                estado.jornadas.push(jornada);
            }
        }

        if(!jornada){
            alert('Registre a entrada antes dos demais horários.');
            atualizarBotoesPeloEstado();
            return false;
        }

        const esperada = proximaAcao(estado);
        if(acao !== esperada){
            alert(`A próxima marcação deve ser: ${nomeAcao(esperada)}.`);
            atualizarBotoesPeloEstado();
            return false;
        }

        jornada[acao] = hora;
        jornada.atualizado_em = agoraIso();
        if(idBatida){jornada[`${acao}_uuid`] = idBatida;}
        if(acao === 'saida'){
            jornada.finalizado_em = agoraIso();
        }
        salvarEstado(estado);
        atualizarBotoesPeloEstado();
        return true;
    }

    function salvarValidacaoLocal(){
        const dados = {
            validado: true,
            token: token,
            funcionario_nome: form.dataset.funcionarioNome || '',
            empresa_nome: form.dataset.empresaNome || '',
            exigir_intervalo: exigeIntervalo ? 'sim' : 'nao',
            validado_em: agoraIso()
        };
        salvarJson(authKey, dados);
        cookieSet(authKey, 'sim', 365);
    }

    function validacaoLocalExiste(){
        const dados = carregarJson(authKey, {});
        if(!!dados.validado && dados.token === token){return true;}
        return cookieGet(authKey) === 'sim';
    }

    function liberarTelaValidada(){
        if(validationForm){validationForm.classList.add('ponto-offline-hidden');}
        if(pointArea){pointArea.classList.remove('ponto-offline-hidden');}
        atualizarBotoesPeloEstado();
    }

    function atualizarStatus(){
        const fila = carregarFila();
        const online = navigator.onLine;
        const estado = carregarEstado();
        const restante = segundosRestantesBloqueio(estado);
        statusBox.className = 'ponto-sync-box';

        if(restante > 0){
            statusBox.classList.add('pending');
            statusBox.textContent = `${online ? 'Online' : 'Offline'} · nova entrada bloqueada por ${restante}s para evitar batida acidental.`;
        }else if(fila.length > 0){
            statusBox.classList.add(online ? 'pending' : 'offline');
            statusBox.textContent = `${online ? 'Online' : 'Offline'} · ${fila.length} batida(s) pendente(s) de sincronização.`;
        }else{
            statusBox.classList.add(online ? 'online' : 'offline');
            statusBox.textContent = online ? 'Online · tudo sincronizado.' : 'Offline · as batidas serão salvas neste celular.';
        }

        if(pendingList){
            pendingList.innerHTML = '';
            fila.slice(-6).forEach(function(item){
                const div = document.createElement('div');
                div.className = 'ponto-pendente-item';
                div.innerHTML = `<span>${nomeAcao(item.acao)}</span><small>${item.data_ponto} ${item.hora_ponto}</small>`;
                pendingList.appendChild(div);
            });
        }
    }

    function aplicarRegistroServidor(registro){
        if(!registro || !registro.data_ponto){return;}
        const estado = carregarEstado(registro.data_ponto);
        const jornada = {
            data_ponto: registro.data_ponto,
            entrada: registro.entrada || '',
            saida_intervalo: registro.saida_intervalo || '',
            retorno_intervalo: registro.retorno_intervalo || '',
            saida: registro.saida || '',
            origem: registro.origem || 'servidor',
            atualizado_em: registro.atualizado_em || agoraIso()
        };
        if(jornada.saida){jornada.finalizado_em = registro.atualizado_em || agoraIso();}

        const existente = (estado.jornadas || []).find(function(item){
            return item.entrada === jornada.entrada && item.saida === jornada.saida && item.data_ponto === jornada.data_ponto;
        });
        if(!existente && jornada.entrada){
            estado.jornadas.push(jornada);
            salvarEstado(estado);
        }
    }

    async function sincronizarFila(){
        const fila = carregarFila();
        if(!navigator.onLine || fila.length === 0){atualizarStatus();return;}

        try{
            const resposta = await fetch('/api/ponto/offline/sincronizar', {
                method: 'POST',
                headers: {'Content-Type':'application/json'},
                body: JSON.stringify({token: token, batidas: fila})
            });
            const dados = await resposta.json();
            if(!resposta.ok || !dados.ok){throw new Error(dados.erro || 'Falha ao sincronizar.');}

            const falhas = [];
            (dados.resultados || []).forEach(function(resultado){
                if(resultado.ok){
                    aplicarRegistroServidor(resultado.registro || {});
                }else{
                    const original = fila.find(item => item.uuid === resultado.uuid);
                    if(original){falhas.push(original);}
                }
            });
            salvarFila(falhas);
            atualizarBotoesPeloEstado();
        }catch(e){
            atualizarStatus();
        }
    }

    async function salvarPaginaAtualNoCache(){
        if(!('caches' in window) || !navigator.onLine){return;}
        try{
            const cache = await caches.open('gestflow-ponto-offline-v5');
            const resposta = await fetch(window.location.href, {credentials: 'include', cache: 'no-store'});
            if(resposta && resposta.ok){
                await cache.put(window.location.href, resposta.clone());
                await cache.put(window.location.origin + window.location.pathname, resposta.clone());
            }
        }catch(e){}
    }

    if((form.dataset.telefoneValidado || '') === 'sim'){
        salvarValidacaoLocal();
    }

    limparEstadosAntigos();
    semearEstadoPelaTela();

    if(validacaoLocalExiste()){
        liberarTelaValidada();
    }else if(!navigator.onLine && validationForm){
        validationForm.classList.remove('ponto-offline-hidden');
    }

    if(validationForm){
        validationForm.addEventListener('submit', function(event){
            if(navigator.onLine){return;}
            event.preventDefault();
            alert('Primeiro acesso precisa de internet para validar o celular. Depois disso, este aparelho bate ponto offline.');
        });
    }

    form.addEventListener('submit', function(event){
        const botao = event.submitter || document.activeElement;
        if(!botao || navigator.onLine){return;}
        event.preventDefault();

        if(!validacaoLocalExiste()){
            alert('Valide este celular com internet antes de usar o ponto offline.');
            return;
        }

        const acao = botao.value;
        if(!acao || !campos.includes(acao)){return;}

        const hora = horaAgora();
        const idBatida = uuid();
        const okLocal = registrarBatidaLocal(acao, hora, idBatida);
        if(!okLocal){return;}

        const batida = {
            uuid: idBatida,
            acao: acao,
            data_ponto: dataHoje(),
            hora_ponto: hora,
            exigir_intervalo: exigeIntervalo ? 'sim' : 'nao',
            dispositivo: navigator.userAgent || ''
        };
        const fila = carregarFila();
        fila.push(batida);
        salvarFila(fila);
    });

    window.addEventListener('online', function(){
        if(validacaoLocalExiste()){liberarTelaValidada();}
        salvarPaginaAtualNoCache();
        sincronizarFila();
    });
    window.addEventListener('offline', atualizarStatus);
    window.addEventListener('beforeunload', function(){salvarEstado(carregarEstado());});

    if('serviceWorker' in navigator){
        navigator.serviceWorker.register('/service-worker.js').then(function(reg){
            if(reg && reg.update){reg.update().catch(function(){});}
        }).catch(function(){});
    }

    salvarPaginaAtualNoCache();
    atualizarBotoesPeloEstado();
    atualizarStatus();
    sincronizarFila();
})();
