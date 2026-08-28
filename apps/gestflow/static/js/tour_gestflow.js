/*
Caminho: C:\Users\vlula\OneDrive\Área de Trabalho\Projetos Backup\GESTFLOW\apps\gestflow\static\js\tour_gestflow.js
Último recode: 2026-08-27 23:12 (America/Bahia)
Motivo: Corrigir o cancelamento do tutorial para não tratar o PointerEvent do clique como URL de redirecionamento.
*/

(function () {
    const deveIniciar = Boolean(window.GESTFLOW_INICIAR_TOUR);
    if (!deveIniciar) return;

    const missoes = Array.isArray(window.GESTFLOW_TOUR_PASSOS) ? window.GESTFLOW_TOUR_PASSOS : [];
    const proximaMissao = missoes.find(function (missao) {
        return missao && !missao.concluido && missao.seletor && document.querySelector(missao.seletor);
    });

    const passos = [];
    if (document.querySelector('#primeiros-passos')) {
        passos.push({
            titulo: 'Vamos fazer juntos?',
            texto: 'Você não precisa aprender o GestFlow inteiro agora. Vamos começar por uma tarefa simples e, quando terminar, mostramos a próxima.',
            seletor: '#primeiros-passos',
            botao: proximaMissao ? 'Mostrar meu primeiro passo' : 'Entendi'
        });
    }

    if (proximaMissao) {
        let texto = proximaMissao.descricao || 'Comece por aqui. O GestFlow vai guiando os próximos passos conforme você usa o sistema.';
        if (proximaMissao.codigo === 'indflow') {
            texto = 'Esta é sua área de produção. Ela se chama IndFlow e concentra produção, paradas e indicadores das máquinas. Você pode conhecer essa área agora.';
        }
        passos.push({
            titulo: proximaMissao.titulo || 'Seu próximo passo',
            texto: texto,
            seletor: proximaMissao.seletor,
            botao: 'Fazer agora',
            acaoUrl: proximaMissao.url || ''
        });
    }

    if (!passos.length) {
        concluirTour();
        return;
    }

    let indiceAtual = 0;
    const overlay = document.createElement('div');
    overlay.className = 'gestflow-tour-overlay';
    const destaque = document.createElement('div');
    destaque.className = 'gestflow-tour-highlight';
    const balao = document.createElement('div');
    balao.className = 'gestflow-tour-balloon';

    document.body.appendChild(overlay);
    document.body.appendChild(destaque);
    document.body.appendChild(balao);
    document.body.classList.add('gestflow-tour-active');

    function tornarAlvoVisivel(alvo) {
        const details = alvo.closest('details');
        if (details) details.open = true;
        alvo.scrollIntoView({block: 'center', inline: 'nearest'});
    }

    function posicionarPasso() {
        const passo = passos[indiceAtual];
        const alvo = document.querySelector(passo.seletor);
        if (!alvo) {
            avancarTour();
            return;
        }

        tornarAlvoVisivel(alvo);
        window.setTimeout(function () {
            const rect = alvo.getBoundingClientRect();
            if (rect.width <= 0 || rect.height <= 0) {
                avancarTour();
                return;
            }

            const margem = 8;
            const larguraBalao = Math.min(340, window.innerWidth - 28);
            const alturaBalao = 185;
            destaque.style.top = Math.max(rect.top - margem, 8) + 'px';
            destaque.style.left = Math.max(rect.left - margem, 8) + 'px';
            destaque.style.width = Math.min(rect.width + margem * 2, window.innerWidth - 16) + 'px';
            destaque.style.height = Math.min(rect.height + margem * 2, window.innerHeight - 16) + 'px';

            let top = rect.bottom + 14;
            let left = rect.left;
            if (top + alturaBalao > window.innerHeight - 14) top = rect.top - alturaBalao - 14;
            if (left + larguraBalao > window.innerWidth - 14) left = window.innerWidth - larguraBalao - 14;
            if (top < 14) top = 14;
            if (left < 14) left = 14;

            balao.style.width = larguraBalao + 'px';
            balao.style.top = top + 'px';
            balao.style.left = left + 'px';
            balao.innerHTML = `
                <strong>${passo.titulo}</strong>
                <p>${passo.texto}</p>
                <div class="gestflow-tour-progress">${indiceAtual + 1} de ${passos.length}</div>
                <div class="gestflow-tour-actions">
                    <button type="button" class="gestflow-tour-cancel">Agora não</button>
                    <button type="button" class="gestflow-tour-next">${passo.botao || 'Continuar'}</button>
                </div>
            `;
            balao.querySelector('.gestflow-tour-cancel').addEventListener('click', function () {
                finalizarTour();
            });
            balao.querySelector('.gestflow-tour-next').addEventListener('click', function () {
                if (passo.acaoUrl) {
                    finalizarTour(passo.acaoUrl);
                    return;
                }
                avancarTour();
            });
        }, 120);
    }

    function avancarTour() {
        if (indiceAtual >= passos.length - 1) {
            finalizarTour();
            return;
        }
        indiceAtual += 1;
        posicionarPasso();
    }

    function concluirTour() {
        fetch('/tour/concluir', {method: 'POST', keepalive: true}).catch(function () {});
    }

    function finalizarTour(destino) {
        concluirTour();
        document.body.classList.remove('gestflow-tour-active');
        overlay.remove();
        destaque.remove();
        balao.remove();
        if (typeof destino === 'string' && destino) window.location.href = destino;
    }

    document.addEventListener('keydown', function (event) {
        if (event.key === 'Escape') finalizarTour();
    });
    window.addEventListener('resize', posicionarPasso);
    setTimeout(posicionarPasso, 350);
})();
