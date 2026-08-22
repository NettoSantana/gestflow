/*
Caminho: C:\Users\vlula\OneDrive\Área de Trabalho\Projetos Backup\GESTFLOW\apps\gestflow\static\js\tour_gestflow.js
Último recode: 2026-08-21 06:43 (America/Bahia)
Motivo: Migrar para a estrutura consolidada GESTFLOW + INDFLOW na branch DEV, preservando o conteúdo funcional validado.
*/

(function () {
    const deveIniciar = Boolean(window.GESTFLOW_INICIAR_TOUR);

    if (!deveIniciar) {
        return;
    }

    const passosBase = [
        {
            titulo: 'Menu principal',
            texto: 'Este é o menu principal. Ele mostra apenas os módulos ativados para esta empresa.',
            seletor: '.sidebar'
        },
        {
            titulo: 'Dashboard',
            texto: 'Aqui você acompanha os principais números do negócio: valores a receber, contas a pagar, vendas, estoque e últimos movimentos.',
            seletor: '.cards-primary'
        },
        {
            titulo: 'Produtos',
            texto: 'Cadastre seus produtos antes de vender. O estoque será movimentado automaticamente quando uma venda for finalizada.',
            seletor: 'a[href="/produtos"]'
        },
        {
            titulo: 'Vendas e PDV',
            texto: 'Use Vendas para registrar vendas completas e Balcão / PDV para atendimento rápido no caixa.',
            seletor: 'a[href="/vendas"]'
        },
        {
            titulo: 'Financeiro',
            texto: 'No financeiro você acompanha contas a receber, contas a pagar e fluxo de caixa.',
            seletor: 'a[href="/financeiro/fluxo-caixa"]'
        },
        {
            titulo: 'Configurações',
            texto: 'Em Configurações você ajusta dados da empresa, usuários, marca, plano e os módulos que aparecem no menu.',
            seletor: 'a[href="/configuracoes"]'
        }
    ];

    const passos = passosBase.filter(function (passo) {
        return document.querySelector(passo.seletor);
    });

    if (!passos.length) {
        finalizarTour();
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

    function posicionarPasso() {
        const passo = passos[indiceAtual];
        const alvo = document.querySelector(passo.seletor);

        if (!alvo) {
            avancarTour();
            return;
        }

        const rect = alvo.getBoundingClientRect();
        const margem = 8;
        const larguraBalao = 310;
        const alturaBalao = 176;

        destaque.style.top = Math.max(rect.top - margem, 8) + 'px';
        destaque.style.left = Math.max(rect.left - margem, 8) + 'px';
        destaque.style.width = Math.min(rect.width + margem * 2, window.innerWidth - 16) + 'px';
        destaque.style.height = Math.min(rect.height + margem * 2, window.innerHeight - 16) + 'px';

        let top = rect.bottom + 14;
        let left = rect.left;

        if (top + alturaBalao > window.innerHeight - 14) {
            top = rect.top - alturaBalao - 14;
        }

        if (left + larguraBalao > window.innerWidth - 14) {
            left = window.innerWidth - larguraBalao - 14;
        }

        if (top < 14) {
            top = 14;
        }

        if (left < 14) {
            left = 14;
        }

        balao.style.top = top + 'px';
        balao.style.left = left + 'px';
        balao.innerHTML = `
            <strong>${passo.titulo}</strong>
            <p>${passo.texto}</p>
            <div class="gestflow-tour-progress">${indiceAtual + 1} de ${passos.length}</div>
            <div class="gestflow-tour-actions">
                <button type="button" class="gestflow-tour-cancel">Cancelar</button>
                <button type="button" class="gestflow-tour-next">${indiceAtual === passos.length - 1 ? 'Entendi' : 'Próximo'}</button>
            </div>
        `;

        const botaoCancelar = balao.querySelector('.gestflow-tour-cancel');
        const botaoProximo = balao.querySelector('.gestflow-tour-next');

        botaoCancelar.addEventListener('click', finalizarTour);
        botaoProximo.addEventListener('click', avancarTour);
    }

    function avancarTour() {
        if (indiceAtual >= passos.length - 1) {
            finalizarTour();
            return;
        }

        indiceAtual += 1;
        posicionarPasso();
    }

    function finalizarTour() {
        fetch('/tour/concluir', { method: 'POST' }).catch(function () {});
        document.body.classList.remove('gestflow-tour-active');
        overlay.remove();
        destaque.remove();
        balao.remove();
    }

    document.addEventListener('keydown', function (event) {
        if (event.key === 'Escape') {
            finalizarTour();
        }
    });

    window.addEventListener('resize', posicionarPasso);
    window.addEventListener('scroll', posicionarPasso, true);

    setTimeout(posicionarPasso, 350);
})();
