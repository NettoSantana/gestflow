// Caminho: C:\Users\vlula\OneDrive\Área de Trabalho\Projetos Backup\GESTFLOW\static\js\ponto_offline.js
// Último recode: 2026-07-14 20:05 (America/Bahia)
// Motivo: Executar a contagem de 10 segundos enviada pelo backend e recarregar a nova jornada.
(function(){
    const form = document.getElementById('ponto-form-batida');
    const validationForm = document.getElementById('ponto-form-validacao');
    const pointArea = document.getElementById('ponto-area-batida');
    const statusBox = document.getElementById('ponto-sync-status');
    const pendingList = document.getElementById('ponto-pendente-lista');
    const avisoBloqueio = document.getElementById('ponto-bloqueio-aviso');
    if(!form || !statusBox){return;}

    const token = form.dataset.token || '';
    const storageKey = `gestflow_ponto_offline_${token}`;
    const authKey = `gestflow_ponto_validado_${token}`;
    const stateKey = `gestflow_ponto_estado_${token}`;
    const exigeIntervalo = (form.dataset.exigirIntervalo || 'sim') !== 'nao';
    const campos = exigeIntervalo ? ['entrada','saida_intervalo','retorno_intervalo','saida'] : ['entrada','saida'];
    const BLOQUEIO_SEGUNDOS = 10;
    let bloqueioTimer = null;
    let enviandoOnline = false;

    function carregarJson(chave, padrao){
        try{return JSON.parse(localStorage.getItem(chave) || JSON.stringify(padrao));}catch(e){return padrao;}
    }

    function salvarJson(chave, valor){
        localStorage.setItem(chave, JSON.stringify(valor));
    }

    function carregarFila(){return carregarJson(storageKey, []);}
    function salvarFila(fila){salvarJson(storageKey, fila || []); atualizarStatus();}

    function dataHoje(){
        const agora = new Date();
        return `${agora.getFullYear()}-${String(agora.getMonth()+1).padStart(2,'0')}-${String(agora.getDate()).padStart(2,'0')}`;
    }

    function horaAgora(){
        const agora = new Date();
        return `${String(agora.getHours()).padStart(2,'0')}:${String(agora.getMinutes()).padStart(2,'0')}`;
    }

    function uuid(){
        if(window.crypto && crypto.randomUUID){return crypto.randomUUID();}
        return `${Date.now()}-${Math.random().toString(16).slice(2)}`;
    }

    function estadoPadrao(){
        return {data: dataHoje(), campos: {}, bloqueioAte: 0};
    }

    function carregarEstado(){
        const estado = carregarJson(stateKey, estadoPadrao());
        if(estado.data !== dataHoje()){
            return estadoPadrao();
        }
        estado.campos = estado.campos || {};
        estado.bloqueioAte = Number(estado.bloqueioAte || 0);
        return estado;
    }

    function salvarEstado(estado){
        estado.data = dataHoje();
        salvarJson(stateKey, estado);
    }

    function campoEl(campo){return document.querySelector(`[data-ponto-campo="${campo}"]`);}

    function valorDom(campo){
        const el = campoEl(campo);
        const texto = el ? el.textContent.trim() : '';
        return texto && texto !== '--:--' ? texto : '';
    }

    function escreverCampo(campo, valor){
        const el = campoEl(campo);
        if(el){el.textContent = valor || '--:--';}
    }

    function estadoServidorAtual(){
        const estado = estadoPadrao();
        campos.forEach(campo => {
            const valor = valorDom(campo);
            if(valor){estado.campos[campo] = valor;}
        });

        const bloqueioServidor = parseInt(form.dataset.bloqueioSegundos || '0', 10) || 0;
        if(bloqueioServidor > 0){
            estado.bloqueioAte = Date.now() + (bloqueioServidor * 1000);
        }

        return estado;
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
    }

    function validacaoLocalExiste(){
        const dados = carregarJson(authKey, {});
        return !!dados.validado && dados.token === token;
    }

    function limparValidacaoLocal(){
        localStorage.removeItem(authKey);
    }

    function mostrarTelaNaoValidada(){
        if(validationForm){validationForm.classList.remove('ponto-offline-hidden');}
        if(pointArea){pointArea.classList.add('ponto-offline-hidden');}
        atualizarStatus();
    }

    function nomeAcao(acao){
        const nomes = {entrada:'Entrada', saida_intervalo:'Saída intervalo', retorno_intervalo:'Retorno intervalo', saida:'Saída'};
        return nomes[acao] || 'Ponto';
    }

    function botaoAcao(acao){return form.querySelector(`button[name="acao"][value="${acao}"]`);}

    function desabilitarTodos(){
        campos.forEach(campo => {
            const botao = botaoAcao(campo);
            if(botao){botao.disabled = true;}
        });
    }

    function bloqueioRestanteSegundos(estado){
        const restanteMs = Number(estado.bloqueioAte || 0) - Date.now();
        return Math.max(Math.ceil(restanteMs / 1000), 0);
    }

    function limparJornadaConcluidaSeLiberada(estado){
        if(estado.campos && estado.campos.saida && bloqueioRestanteSegundos(estado) <= 0){
            estado.campos = {};
            estado.bloqueioAte = 0;
            salvarEstado(estado);
        }
    }

    function atualizarAvisoBloqueio(segundos){
        if(!avisoBloqueio){return;}
        if(segundos > 0){
            avisoBloqueio.textContent = `Nova entrada para hora extra liberada em ${segundos} segundo(s).`;
            avisoBloqueio.classList.remove('ponto-offline-hidden');
        }else{
            avisoBloqueio.classList.add('ponto-offline-hidden');
        }
    }

    function agendarFimBloqueio(estado){
        if(bloqueioTimer){clearTimeout(bloqueioTimer);}
        const segundos = bloqueioRestanteSegundos(estado);
        atualizarAvisoBloqueio(segundos);

        if(segundos <= 0){
            const atual = carregarEstado();
            atual.campos = {};
            atual.bloqueioAte = 0;
            salvarEstado(atual);

            if(navigator.onLine){
                window.location.replace(window.location.pathname);
                return;
            }

            renderizarEstadoOffline();
            return;
        }

        bloqueioTimer = setTimeout(function(){
            const atual = carregarEstado();
            agendarFimBloqueio(atual);
        }, 1000);
    }

    function renderizarEstadoOffline(){
        const estado = carregarEstado();
        limparJornadaConcluidaSeLiberada(estado);
        campos.forEach(campo => escreverCampo(campo, estado.campos[campo] || ''));

        const segundos = bloqueioRestanteSegundos(estado);
        if(segundos > 0){
            desabilitarTodos();
            atualizarAvisoBloqueio(segundos);
            agendarFimBloqueio(estado);
            return;
        }

        atualizarAvisoBloqueio(0);
        const v = estado.campos || {};
        campos.forEach(campo => { const botao = botaoAcao(campo); if(botao){botao.disabled = true;} });

        if(!v.entrada){
            const entrada = botaoAcao('entrada');
            if(entrada){entrada.disabled = false;}
            return;
        }

        if(exigeIntervalo){
            if(!v.saida_intervalo){ const b = botaoAcao('saida_intervalo'); if(b){b.disabled = false;} return; }
            if(!v.retorno_intervalo){ const b = botaoAcao('retorno_intervalo'); if(b){b.disabled = false;} return; }
            if(!v.saida){ const b = botaoAcao('saida'); if(b){b.disabled = false;} return; }
        }else{
            if(!v.saida){ const b = botaoAcao('saida'); if(b){b.disabled = false;} return; }
        }
    }

    function prepararEstadoOnline(){
        const estado = estadoServidorAtual();
        salvarEstado(estado);

        const segundos = bloqueioRestanteSegundos(estado);
        atualizarAvisoBloqueio(segundos);

        if(segundos > 0){
            desabilitarTodos();
            agendarFimBloqueio(estado);
        }
    }

    function liberarTelaValidada(){
        if(validationForm){validationForm.classList.add('ponto-offline-hidden');}
        if(pointArea){pointArea.classList.remove('ponto-offline-hidden');}
        atualizarStatus();
        if(navigator.onLine){prepararEstadoOnline();}
        else{renderizarEstadoOffline();}
    }

    function iniciarBloqueio(estado, segundos){
        estado.bloqueioAte = Date.now() + (Number(segundos || BLOQUEIO_SEGUNDOS) * 1000);
        salvarEstado(estado);
        renderizarEstadoOffline();
    }

    function marcarTelaOffline(acao, hora){
        const estado = carregarEstado();
        estado.campos[acao] = hora;
        salvarEstado(estado);
        escreverCampo(acao, hora);
        if(acao === 'saida'){
            iniciarBloqueio(estado, BLOQUEIO_SEGUNDOS);
        }else{
            renderizarEstadoOffline();
        }
    }

    function atualizarStatus(){
        const fila = carregarFila();
        const online = navigator.onLine;
        statusBox.className = 'ponto-sync-box';
        if(fila.length > 0){
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
                if(!resultado.ok){
                    const original = fila.find(item => item.uuid === resultado.uuid);
                    if(original){falhas.push(original);}
                }
            });
            salvarFila(falhas);

            if(falhas.length === 0){
                window.location.reload();
                return;
            }

            prepararEstadoOnline();
            atualizarStatus();
        }catch(e){
            atualizarStatus();
            if(!navigator.onLine){renderizarEstadoOffline();}
        }
    }

    const telefoneValidadoServidor = (form.dataset.telefoneValidado || '') === 'sim';

    if(telefoneValidadoServidor){
        salvarValidacaoLocal();
        liberarTelaValidada();
    }else if(navigator.onLine){
        limparValidacaoLocal();
        mostrarTelaNaoValidada();
    }else if(validacaoLocalExiste()){
        liberarTelaValidada();
    }else{
        mostrarTelaNaoValidada();
    }

    if(validationForm){
        validationForm.addEventListener('submit', function(event){
            if(navigator.onLine){return;}
            event.preventDefault();
            alert('Primeiro acesso precisa de internet para validar o celular. Depois disso, este aparelho bate ponto offline.');
        });
    }

    function garantirAcaoAntesDoSubmit(acao){
        let input = form.querySelector('input[data-ponto-acao-hidden="sim"]');
        if(!input){
            input = document.createElement('input');
            input.type = 'hidden';
            input.name = 'acao';
            input.setAttribute('data-ponto-acao-hidden', 'sim');
            form.appendChild(input);
        }
        input.value = acao || '';
    }

    form.addEventListener('submit', function(event){
        const botao = event.submitter;
        if(!botao){return;}
        if(botao.disabled || enviandoOnline){event.preventDefault(); return;}

        const acao = botao.value || botao.getAttribute('value') || '';
        if(!acao || !campos.includes(acao)){
            event.preventDefault();
            return;
        }

        if(navigator.onLine){
            garantirAcaoAntesDoSubmit(acao);
            enviandoOnline = true;
            botao.setAttribute('aria-disabled', 'true');
            botao.style.opacity = '.55';
            botao.style.pointerEvents = 'none';
            return;
        }

        event.preventDefault();

        if(!validacaoLocalExiste()){
            alert('Valide este celular com internet antes de usar o ponto offline.');
            return;
        }

        const hora = horaAgora();
        const batida = {uuid: uuid(), acao: acao, data_ponto: dataHoje(), hora_ponto: hora, exigir_intervalo: exigeIntervalo ? 'sim' : 'nao', dispositivo: navigator.userAgent || ''};
        const fila = carregarFila();
        fila.push(batida);
        salvarFila(fila);
        marcarTelaOffline(acao, hora);
    });

    window.addEventListener('online', function(){
        if((form.dataset.telefoneValidado || '') === 'sim'){
            salvarValidacaoLocal();
            window.location.reload();
            return;
        }

        limparValidacaoLocal();
        mostrarTelaNaoValidada();
    });
    window.addEventListener('offline', function(){atualizarStatus(); renderizarEstadoOffline();});

    if('serviceWorker' in navigator){navigator.serviceWorker.register('/service-worker.js').catch(function(){});}

    if(!navigator.onLine){renderizarEstadoOffline();}
    atualizarStatus();
    sincronizarFila();
})();
