// Caminho: static/js/ponto_offline.js
// Último recode: 2026-07-09 11:30 (America/Bahia)
// Motivo: Permitir ponto offline após validação do celular e respeitar configuração de intervalo/almoço.
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
    const exigeIntervalo = (form.dataset.exigirIntervalo || 'sim') !== 'nao';
    const campos = exigeIntervalo ? ['entrada','saida_intervalo','retorno_intervalo','saida'] : ['entrada','saida'];

    function carregarJson(chave, padrao){
        try{return JSON.parse(localStorage.getItem(chave) || JSON.stringify(padrao));}catch(e){return padrao;}
    }

    function salvarJson(chave, valor){
        localStorage.setItem(chave, JSON.stringify(valor));
    }

    function carregarFila(){
        return carregarJson(storageKey, []);
    }

    function salvarFila(fila){
        salvarJson(storageKey, fila || []);
        atualizarStatus();
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

    function liberarTelaValidada(){
        if(validationForm){validationForm.classList.add('ponto-offline-hidden');}
        if(pointArea){pointArea.classList.remove('ponto-offline-hidden');}
        liberarProximoBotao();
        atualizarStatus();
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

    function marcarTela(acao, hora){
        const campo = document.querySelector(`[data-ponto-campo="${acao}"]`);
        if(campo){campo.textContent = hora;}
        const botao = form.querySelector(`button[name="acao"][value="${acao}"]`);
        if(botao){botao.disabled = true;}
        liberarProximoBotao();
    }

    function campoMarcado(campo){
        const el = document.querySelector(`[data-ponto-campo="${campo}"]`);
        return !!(el && el.textContent.trim() !== '--:--');
    }

    function liberarProximoBotao(){
        const valores = {};
        campos.forEach(campo => {valores[campo] = campoMarcado(campo);});

        const regras = exigeIntervalo ? {
            entrada: true,
            saida_intervalo: valores.entrada,
            retorno_intervalo: valores.saida_intervalo,
            saida: valores.retorno_intervalo
        } : {
            entrada: true,
            saida: valores.entrada
        };

        campos.forEach(campo => {
            const botao = form.querySelector(`button[name="acao"][value="${campo}"]`);
            if(botao && !valores[campo]){botao.disabled = !regras[campo];}
        });
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
                if(resultado.ok){
                    const registro = resultado.registro || {};
                    campos.forEach(campo => {if(registro[campo]){marcarTela(campo, registro[campo]);}});
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
            alert('Primeiro acesso precisa de internet para validar o celular. Depois disso, este aparelho bate ponto offline.');
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
    window.addEventListener('offline', atualizarStatus);

    if('serviceWorker' in navigator){
        navigator.serviceWorker.register('/service-worker.js').catch(function(){});
    }

    liberarProximoBotao();
    atualizarStatus();
    sincronizarFila();
})();
