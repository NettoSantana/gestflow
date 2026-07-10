// Caminho: C:\Users\vlula\OneDrive\Área de Trabalho\Projetos Backup\GESTFLOW\static\js\ponto_offline.js
// Último recode: 2026-07-10 10:05 (America/Bahia)
// Motivo: Persistir validação do celular e reforçar abertura offline pelo link do navegador Android/iPhone.
(function(){
    const caminhoPonto = window.location.pathname.startsWith('/ponto/');
    const tokenPagina = caminhoPonto ? decodeURIComponent(window.location.pathname.split('/ponto/')[1] || '').split('/')[0] : '';

    function chaveSeguraToken(token){
        return String(token || '').replace(/[^a-zA-Z0-9_-]/g, '_');
    }

    function carregarJson(chave, padrao){
        try{return JSON.parse(localStorage.getItem(chave) || JSON.stringify(padrao));}catch(e){return padrao;}
    }

    function salvarJson(chave, valor){
        try{localStorage.setItem(chave, JSON.stringify(valor));}catch(e){}
    }

    function setCookieValidacao(token){
        try{
            const nome = `gestflow_ponto_validado_${chaveSeguraToken(token)}`;
            document.cookie = `${nome}=sim; Max-Age=31536000; Path=/ponto/${encodeURIComponent(token)}; SameSite=Lax`;
        }catch(e){}
    }

    function getCookieValidacao(token){
        try{
            const nome = `gestflow_ponto_validado_${chaveSeguraToken(token)}=`;
            return document.cookie.split(';').map(p => p.trim()).some(p => p.indexOf(nome) === 0 && p.slice(nome.length) === 'sim');
        }catch(e){return false;}
    }

    function salvarTokenValidadoGlobal(token){
        const chave = 'gestflow_ponto_validado_tokens';
        const dados = carregarJson(chave, {});
        dados[token] = {validado: true, validado_em: new Date().toISOString()};
        salvarJson(chave, dados);
    }

    function tokenValidadoGlobal(token){
        const dados = carregarJson('gestflow_ponto_validado_tokens', {});
        return !!(dados[token] && dados[token].validado);
    }

    async function registrarServiceWorkerPonto(){
        if(!('serviceWorker' in navigator) || !caminhoPonto){return;}

        try{
            const registro = await navigator.serviceWorker.register('/service-worker.js', {scope: '/'});
            if(registro.waiting){registro.waiting.postMessage({tipo:'SKIP_WAITING'});}

            if(!navigator.serviceWorker.controller && navigator.onLine){
                const reloadKey = `gestflow_sw_reload_${tokenPagina}`;
                navigator.serviceWorker.addEventListener('controllerchange', function(){
                    if(localStorage.getItem(reloadKey) === 'sim'){return;}
                    localStorage.setItem(reloadKey, 'sim');
                    window.location.reload();
                });
            }
        }catch(e){}
    }

    function enviarHtmlAtualParaCache(){
        if(!navigator.serviceWorker || !navigator.serviceWorker.controller || !caminhoPonto){return;}
        try{
            navigator.serviceWorker.controller.postMessage({
                tipo: 'CACHE_PONTO_HTML',
                url: window.location.href,
                html: '<!doctype html>\n' + document.documentElement.outerHTML
            });
        }catch(e){}
    }

    registrarServiceWorkerPonto();

    const form = document.getElementById('ponto-form-batida');
    const validationForm = document.getElementById('ponto-form-validacao');
    const pointArea = document.getElementById('ponto-area-batida');
    const statusBox = document.getElementById('ponto-sync-status');
    const pendingList = document.getElementById('ponto-pendente-lista');

    if(!form || !statusBox){
        window.addEventListener('load', enviarHtmlAtualParaCache);
        return;
    }

    const token = form.dataset.token || tokenPagina || '';
    const storageKey = `gestflow_ponto_offline_${token}`;
    const authKey = `gestflow_ponto_validado_${token}`;
    const bloqueioKey = `gestflow_ponto_bloqueio_entrada_${token}`;
    const exigeIntervalo = (form.dataset.exigirIntervalo || 'sim') !== 'nao';
    const campos = exigeIntervalo ? ['entrada','saida_intervalo','retorno_intervalo','saida'] : ['entrada','saida'];
    let timerBloqueio = null;

    function carregarFila(){
        return carregarJson(storageKey, []);
    }

    function salvarFila(fila){
        salvarJson(storageKey, fila || []);
        atualizarStatus();
        setTimeout(enviarHtmlAtualParaCache, 80);
    }

    function salvarValidacaoLocal(){
        salvarJson(authKey, {
            validado: true,
            token: token,
            funcionario_nome: form.dataset.funcionarioNome || '',
            empresa_nome: form.dataset.empresaNome || '',
            exigir_intervalo: exigeIntervalo ? 'sim' : 'nao',
            validado_em: new Date().toISOString()
        });
        salvarTokenValidadoGlobal(token);
        setCookieValidacao(token);
        setTimeout(enviarHtmlAtualParaCache, 80);
    }

    function validacaoLocalExiste(){
        const dados = carregarJson(authKey, {});
        return (!!dados.validado && dados.token === token) || tokenValidadoGlobal(token) || getCookieValidacao(token);
    }

    function liberarTelaValidada(){
        if(validationForm){validationForm.classList.add('ponto-offline-hidden');}
        if(pointArea){pointArea.classList.remove('ponto-offline-hidden');}
        liberarProximoBotao();
        atualizarStatus();
        setTimeout(enviarHtmlAtualParaCache, 80);
    }

    function uuid(){
        if(window.crypto && crypto.randomUUID){return crypto.randomUUID();}
        return `${Date.now()}-${Math.random().toString(16).slice(2)}`;
    }

    function dataHoje(){
        const agora = new Date();
        return `${agora.getFullYear()}-${String(agora.getMonth()+1).padStart(2,'0')}-${String(agora.getDate()).padStart(2,'0')}`;
    }

    function horaAgora(){
        const agora = new Date();
        return `${String(agora.getHours()).padStart(2,'0')}:${String(agora.getMinutes()).padStart(2,'0')}`;
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

    function campoElemento(campo){
        return document.querySelector(`[data-ponto-campo="${campo}"]`);
    }

    function campoMarcado(campo){
        const el = campoElemento(campo);
        return !!(el && el.textContent.trim() !== '--:--');
    }

    function setCampo(campo, valor){
        const el = campoElemento(campo);
        if(el){el.textContent = valor || '--:--';}
    }

    function setBotao(campo, desabilitado){
        const botao = form.querySelector(`button[name="acao"][value="${campo}"]`);
        if(botao){botao.disabled = !!desabilitado;}
    }

    function limparCamposParaNovaJornada(){
        campos.forEach(campo => setCampo(campo, '--:--'));
    }

    function bloqueioEntradaRestante(){
        const ate = parseInt(localStorage.getItem(bloqueioKey) || '0', 10);
        if(!ate){return 0;}
        const restante = Math.ceil((ate - Date.now()) / 1000);
        if(restante <= 0){
            localStorage.removeItem(bloqueioKey);
            return 0;
        }
        return restante;
    }

    function iniciarBloqueioEntrada(){
        localStorage.setItem(bloqueioKey, String(Date.now() + 60000));
        liberarProximoBotao();
        if(timerBloqueio){clearInterval(timerBloqueio);}
        timerBloqueio = setInterval(function(){
            liberarProximoBotao();
            if(bloqueioEntradaRestante() <= 0){
                clearInterval(timerBloqueio);
                timerBloqueio = null;
                limparCamposParaNovaJornada();
                liberarProximoBotao();
                enviarHtmlAtualParaCache();
            }
        }, 1000);
    }

    function marcarTela(acao, hora){
        setCampo(acao, hora);
        setBotao(acao, true);
        if(acao === 'saida'){
            iniciarBloqueioEntrada();
        }else{
            liberarProximoBotao();
        }
        setTimeout(enviarHtmlAtualParaCache, 80);
    }

    function liberarProximoBotao(){
        const restanteBloqueio = bloqueioEntradaRestante();
        const valores = {};
        campos.forEach(campo => {valores[campo] = campoMarcado(campo);});

        campos.forEach(campo => setBotao(campo, true));

        if(valores.saida){
            if(restanteBloqueio > 0){
                if(statusBox){
                    statusBox.className = 'ponto-sync-box pending';
                    statusBox.textContent = `Nova entrada liberada em ${restanteBloqueio}s para evitar batida acidental.`;
                }
                return;
            }
            limparCamposParaNovaJornada();
            setBotao('entrada', false);
            atualizarStatus();
            return;
        }

        if(!valores.entrada){
            if(restanteBloqueio > 0){
                setBotao('entrada', true);
                if(statusBox){
                    statusBox.className = 'ponto-sync-box pending';
                    statusBox.textContent = `Nova entrada liberada em ${restanteBloqueio}s para evitar batida acidental.`;
                }
                return;
            }
            setBotao('entrada', false);
            return;
        }

        if(exigeIntervalo){
            if(!valores.saida_intervalo){setBotao('saida_intervalo', false);return;}
            if(!valores.retorno_intervalo){setBotao('retorno_intervalo', false);return;}
            if(!valores.saida){setBotao('saida', false);return;}
        }else{
            if(!valores.saida){setBotao('saida', false);return;}
        }
    }

    function atualizarStatus(){
        const fila = carregarFila();
        const online = navigator.onLine;
        const restanteBloqueio = bloqueioEntradaRestante();

        statusBox.className = 'ponto-sync-box';

        if(restanteBloqueio > 0){
            statusBox.classList.add('pending');
            statusBox.textContent = `Nova entrada liberada em ${restanteBloqueio}s para evitar batida acidental.`;
        }else if(fila.length > 0){
            statusBox.classList.add(online ? 'pending' : 'offline');
            statusBox.textContent = `${online ? 'Online' : 'Offline'} · ${fila.length} batida(s) pendente(s) de sincronização.`;
        }else{
            statusBox.classList.add(online ? 'online' : 'offline');
            statusBox.textContent = online ? 'Online · tudo sincronizado.' : 'Offline · as batidas serão salvas neste celular.';
        }

        if(pendingList){
            pendingList.innerHTML = '';
            fila.slice(-4).forEach(item => {
                const div = document.createElement('div');
                div.className = 'ponto-pendente-item';
                div.innerHTML = `<span>${nomeAcao(item.acao)}</span><small>${item.data_ponto} ${item.hora_ponto}</small>`;
                pendingList.appendChild(div);
            });
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
            (dados.resultados || []).forEach(resultado => {
                if(resultado.ok){
                    const registro = resultado.registro || {};
                    campos.forEach(campo => {if(registro[campo]){setCampo(campo, registro[campo]);}});
                    liberarProximoBotao();
                }else{
                    const original = fila.find(item => item.uuid === resultado.uuid);
                    if(original){falhas.push(original);}
                }
            });
            salvarFila(falhas);
        }catch(e){
            atualizarStatus();
        }
    }

    if((form.dataset.telefoneValidado || '') === 'sim'){
        salvarValidacaoLocal();
    }

    if(validacaoLocalExiste()){
        liberarTelaValidada();
    }else if(!navigator.onLine && validationForm){
        validationForm.classList.remove('ponto-offline-hidden');
    }

    if(validationForm){
        validationForm.addEventListener('submit', function(event){
            if(navigator.onLine){return;}
            event.preventDefault();
            if(validacaoLocalExiste()){
                liberarTelaValidada();
                return;
            }
            alert('Primeiro acesso precisa de internet para validar o celular. Depois disso, este aparelho bate ponto offline pelo link do navegador.');
        });
    }

    form.addEventListener('submit', function(event){
        const botao = event.submitter;
        if(!botao || navigator.onLine){return;}
        event.preventDefault();

        if(!validacaoLocalExiste()){
            alert('Valide este celular com internet antes de usar o ponto offline.');
            return;
        }

        const acao = botao.value;
        if(!acao || !campos.includes(acao)){return;}

        if(acao === 'entrada' && bloqueioEntradaRestante() > 0){
            atualizarStatus();
            return;
        }

        const hora = horaAgora();
        const batida = {
            uuid: uuid(),
            acao: acao,
            data_ponto: dataHoje(),
            hora_ponto: hora,
            exigir_intervalo: exigeIntervalo ? 'sim' : 'nao',
            dispositivo: navigator.userAgent || ''
        };
        const fila = carregarFila();
        fila.push(batida);
        salvarFila(fila);
        marcarTela(acao, hora);
    });

    window.addEventListener('online', function(){
        if(validacaoLocalExiste()){liberarTelaValidada();}
        sincronizarFila();
    });
    window.addEventListener('offline', function(){
        atualizarStatus();
        enviarHtmlAtualParaCache();
    });
    window.addEventListener('load', function(){
        liberarProximoBotao();
        atualizarStatus();
        setTimeout(enviarHtmlAtualParaCache, 250);
    });

    if('serviceWorker' in navigator){
        navigator.serviceWorker.ready.then(function(){
            setTimeout(enviarHtmlAtualParaCache, 250);
        }).catch(function(){});
    }

    liberarProximoBotao();
    atualizarStatus();
    sincronizarFila();
})();
