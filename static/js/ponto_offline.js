// Caminho: static/js/ponto_offline.js
// Último recode: 2026-07-09 10:00 (America/Bahia)
// Motivo: Criar fila offline do registro de ponto com sincronização automática ao voltar internet.
(function(){
    const form = document.getElementById('ponto-form-batida');
    const statusBox = document.getElementById('ponto-sync-status');
    const pendingList = document.getElementById('ponto-pendente-lista');
    if(!form || !statusBox){return;}

    const token = form.dataset.token || '';
    const storageKey = `gestflow_ponto_offline_${token}`;
    const campos = ['entrada','saida_intervalo','retorno_intervalo','saida'];

    function carregarFila(){
        try{return JSON.parse(localStorage.getItem(storageKey) || '[]') || [];}catch(e){return [];}
    }

    function salvarFila(fila){
        localStorage.setItem(storageKey, JSON.stringify(fila || []));
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

    function liberarProximoBotao(){
        const valores = {};
        campos.forEach(campo => {
            const el = document.querySelector(`[data-ponto-campo="${campo}"]`);
            valores[campo] = el && el.textContent.trim() !== '--:--';
        });
        const regras = {
            entrada: true,
            saida_intervalo: valores.entrada,
            retorno_intervalo: valores.saida_intervalo,
            saida: valores.retorno_intervalo
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

    form.addEventListener('submit', function(event){
        const botao = event.submitter;
        if(!botao || navigator.onLine){return;}
        event.preventDefault();

        const acao = botao.value;
        if(!acao){return;}
        const hora = horaAgora();
        const batida = {
            uuid: uuid(),
            acao: acao,
            data_ponto: dataHoje(),
            hora_ponto: hora,
            dispositivo: navigator.userAgent || ''
        };
        const fila = carregarFila();
        fila.push(batida);
        salvarFila(fila);
        marcarTela(acao, hora);
    });

    window.addEventListener('online', sincronizarFila);
    window.addEventListener('offline', atualizarStatus);

    if('serviceWorker' in navigator){
        navigator.serviceWorker.register('/service-worker.js').catch(function(){});
    }

    atualizarStatus();
    sincronizarFila();
})();
