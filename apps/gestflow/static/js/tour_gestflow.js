/*
Caminho: C:\Users\vlula\OneDrive\Área de Trabalho\Projetos Backup\GESTFLOW\apps\gestflow\static\js\tour_gestflow.js
Último recode: 2026-08-22 11:56 (America/Bahia)
Motivo: Transformar o tutorial inicial em roteiro guiado pelas missões e módulos realmente ativos para a empresa.
*/

(function () {
    const deveIniciar = Boolean(window.GESTFLOW_INICIAR_TOUR);
    if (!deveIniciar) return;

    const missoes = Array.isArray(window.GESTFLOW_TOUR_PASSOS) ? window.GESTFLOW_TOUR_PASSOS : [];
    const passosBase = [
        {
            titulo: 'Seu GestFlow foi configurado',
            texto: 'O menu agora mostra o núcleo da gestão e os módulos que fazem sentido para a sua operação.',
            seletor: '.sidebar'
        }
    ];

    if (document.querySelector('#primeiros-passos')) {
        passosBase.push({
            titulo: 'Primeiros passos',
            texto: 'Este roteiro acompanha o que você já configurou. Cada missão é concluída automaticamente conforme você usa o sistema.',
            seletor: '#primeiros-passos'
        });
    } else if (document.querySelector('.cards-primary')) {
        passosBase.push({
            titulo: 'Dashboard',
            texto: 'Aqui você acompanha os principais números da empresa e os atalhos para a operação diária.',
            seletor: '.cards-primary'
        });
    }

    missoes.slice(0, 6).forEach(function (missao) {
        if (!missao || !missao.seletor) return;
        passosBase.push({
            titulo: missao.titulo || 'Próximo passo',
            texto: missao.descricao || 'Use este módulo para avançar na configuração e operação da empresa.',
            seletor: missao.seletor
        });
    });

    if (document.querySelector('a[href="/indflow"]')) {
        passosBase.push({
            titulo: 'IndFlow',
            texto: 'Para a operação industrial, o IndFlow concentra produção, paradas, histórico e indicadores de chão de fábrica.',
            seletor: 'a[href="/indflow"]'
        });
    } else if (document.querySelector('a[href="/vitrine"]')) {
        passosBase.push({
            titulo: 'Vitrine Online',
            texto: 'Se este módulo estiver ativo, você pode publicar produtos ou serviços e receber pedidos e agendamentos pelo link da empresa.',
            seletor: 'a[href="/vitrine"]'
        });
    }

    if (document.querySelector('a[href="/configuracoes"]')) {
        passosBase.push({
            titulo: 'Configurações e módulos',
            texto: 'Você pode refazer a anamnese ou ajustar módulos operacionais e especializados quando a rotina da empresa mudar.',
            seletor: 'a[href="/configuracoes"]'
        });
    }

    const passos = passosBase.filter(function (passo, indice, lista) {
        if (!document.querySelector(passo.seletor)) return false;
        return lista.findIndex(function (item) { return item.seletor === passo.seletor; }) === indice;
    });

    if (!passos.length) {
        finalizarTourSemInterface();
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
            const larguraBalao = Math.min(330, window.innerWidth - 28);
            const alturaBalao = 190;
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
                    <button type="button" class="gestflow-tour-cancel">Encerrar</button>
                    <button type="button" class="gestflow-tour-next">${indiceAtual === passos.length - 1 ? 'Começar a usar' : 'Próximo'}</button>
                </div>
            `;
            balao.querySelector('.gestflow-tour-cancel').addEventListener('click', finalizarTour);
            balao.querySelector('.gestflow-tour-next').addEventListener('click', avancarTour);
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

    function finalizarTourSemInterface() {
        fetch('/tour/concluir', {method: 'POST'}).catch(function () {});
    }

    function finalizarTour() {
        finalizarTourSemInterface();
        document.body.classList.remove('gestflow-tour-active');
        overlay.remove();
        destaque.remove();
        balao.remove();
    }

    document.addEventListener('keydown', function (event) {
        if (event.key === 'Escape') finalizarTour();
    });
    window.addEventListener('resize', posicionarPasso);
    setTimeout(posicionarPasso, 350);
})();
