/*
Caminho: C:\Users\vlula\OneDrive\Área de Trabalho\Projetos Backup\GESTFLOW\static\js\searchable_select.js
Último recode: 2026-08-25 12:42 (America/Bahia)
Motivo: Levar para a MAIN o padrão validado no DEV de seletores de cadastros como campo único pesquisável, com lista filtrada abaixo e seleção por clique/teclado.
*/

(function () {
    'use strict';

    if (window.GFSearchableSelect) return;

    const MAX_RESULTADOS = 40;
    const SELECTOR_SELECTS = 'select';
    const NOMES_EXATOS = new Set([
        'cliente',
        'responsavel',
        'financeiro_pessoa',
        'material_descricao',
        'mao_funcao',
        'adicional_funcao',
        'empresa_id',
        'usuario_id',
        'orcamento_id',
        'ordem_servico_id',
        'profissional_id'
    ]);

    const SUFIXOS_PESQUISAVEIS = [
        'cliente',
        'cliente_id',
        'cliente_nome',
        'fornecedor',
        'fornecedor_id',
        'fornecedor_nome',
        'produto',
        'produto_id',
        'produto_nome',
        'servico',
        'servico_id',
        'servico_nome',
        'funcionario_id',
        'responsavel',
        'responsavel_id',
        'responsavel_funcionario_id',
        'tecnico',
        'tecnico_id',
        'profissional_id',
        'centro_custo',
        'centro_custo_id',
        'atividade_financeira_id',
        'equipamento',
        'equipamento_id',
        'equipamento_nome',
        'ordem_servico_id',
        'orcamento_id',
        'usuario_id',
        'empresa_id'
    ];

    function nomeBase(select) {
        return String(select?.name || '').replace(/\[\]$/, '').trim().toLowerCase();
    }

    function deveAprimorar(select) {
        if (!(select instanceof HTMLSelectElement)) return false;
        if (select.multiple) return false;
        if (select.dataset.gfSearchable === 'off') return false;
        if (select.dataset.gfSearchable === 'on') return true;
        if (select.classList.contains('material-select') || select.classList.contains('mao-select') || select.classList.contains('adicional-funcao')) return true;
        if (select.classList.contains('quick-cliente-select') || select.classList.contains('quick-fornecedor-select')) return true;

        const nome = nomeBase(select);
        if (!nome) return false;
        if (nome === 'adicional_exibir_cliente' || nome === 'gerador_tipo_servico' || nome.endsWith('_tipo_servico')) return false;
        if (NOMES_EXATOS.has(nome)) return true;
        return SUFIXOS_PESQUISAVEIS.some(function (sufixo) {
            return nome === sufixo || nome.endsWith('_' + sufixo);
        });
    }

    function normalizar(valor) {
        return String(valor || '')
            .normalize('NFD')
            .replace(/[\u0300-\u036f]/g, '')
            .toLocaleUpperCase('pt-BR')
            .trim();
    }

    function escaparHtml(valor) {
        return String(valor ?? '')
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#039;');
    }

    function opcoesDisponiveis(select) {
        return Array.from(select.options || []).filter(function (option) {
            if (option.disabled && !option.selected) return false;
            if (!option.value && option.index === 0) return false;
            return true;
        });
    }

    function ehAcao(option) {
        const valor = String(option?.value || '');
        const texto = String(option?.textContent || '').trim();
        return valor.startsWith('__novo_') || texto.startsWith('+');
    }

    function placeholderDoSelect(select) {
        const configurado = select.dataset.searchPlaceholder || select.dataset.placeholder || '';
        if (configurado) return configurado;
        const primeira = select.options?.[0];
        const texto = String(primeira?.textContent || '').trim();
        if (!primeira?.value && texto && !/^selecione$/i.test(texto)) return texto;
        return 'Digite para buscar';
    }

    function opcaoSelecionadaReal(select) {
        const option = select.selectedOptions?.[0];
        if (!option || !option.value || ehAcao(option)) return null;
        return option;
    }

    function injetarEstilos() {
        if (document.getElementById('gf-searchable-select-style')) return;
        const style = document.createElement('style');
        style.id = 'gf-searchable-select-style';
        style.textContent = `
            .gf-searchable-native {
                position: absolute !important;
                width: 1px !important;
                height: 1px !important;
                margin: -1px !important;
                padding: 0 !important;
                overflow: hidden !important;
                clip: rect(0 0 0 0) !important;
                white-space: nowrap !important;
                border: 0 !important;
                opacity: 0 !important;
                pointer-events: none !important;
            }
            .gf-searchable-wrap {
                position: relative;
                width: 100%;
                min-width: 0;
            }
            .gf-searchable-input-wrap {
                position: relative;
                width: 100%;
            }
            .gf-searchable-input {
                width: 100% !important;
                min-width: 0 !important;
                min-height: 42px;
                padding-right: 38px !important;
                background: #fff !important;
                cursor: text;
            }
            .gf-searchable-input-wrap::after {
                content: '⌄';
                position: absolute;
                top: 50%;
                right: 13px;
                transform: translateY(-53%);
                color: #64748b;
                font-size: 16px;
                font-weight: 900;
                pointer-events: none;
            }
            .gf-searchable-input[disabled] {
                cursor: not-allowed;
                background: #f8fafc !important;
            }
            .gf-searchable-menu {
                position: fixed;
                z-index: 200000;
                max-height: 310px;
                overflow-y: auto;
                border: 1px solid #cbd5e1;
                border-radius: 10px;
                background: #fff;
                box-shadow: 0 18px 36px rgba(15, 23, 42, .18);
            }
            .gf-searchable-menu[hidden] { display: none !important; }
            .gf-searchable-option,
            .gf-searchable-action,
            .gf-searchable-empty {
                width: 100%;
                min-height: 42px;
                display: flex;
                align-items: center;
                padding: 9px 12px;
                border: 0;
                border-bottom: 1px solid #eef2f7;
                background: #fff;
                color: #0f172a;
                font: inherit;
                text-align: left;
            }
            .gf-searchable-option { cursor: pointer; }
            .gf-searchable-option:hover,
            .gf-searchable-option.is-active { background: #f1f5f9; }
            .gf-searchable-option.is-selected {
                background: #eff6ff;
                color: #1d4ed8;
                font-weight: 800;
            }
            .gf-searchable-option strong {
                display: block;
                width: 100%;
                font-size: 13px;
                font-weight: 700;
                line-height: 1.35;
            }
            .gf-searchable-action {
                justify-content: center;
                border-bottom: 0;
                background: #16a34a;
                color: #fff;
                font-size: 13px;
                font-weight: 900;
                cursor: pointer;
            }
            .gf-searchable-action:hover { background: #15803d; }
            .gf-searchable-empty {
                color: #64748b;
                font-size: 12px;
            }
            .gf-searchable-old-filter { display: none !important; }
        `;
        document.head.appendChild(style);
    }

    function posicionarMenu(componente) {
        if (!componente || componente.menu.hidden) return;
        const rect = componente.input.getBoundingClientRect();
        const margem = 8;
        const largura = Math.max(rect.width, 280);
        let esquerda = Math.max(rect.left, margem);
        if (esquerda + largura > window.innerWidth - margem) {
            esquerda = Math.max(margem, window.innerWidth - margem - largura);
        }

        const espacoAbaixo = window.innerHeight - rect.bottom - margem;
        const alturaMaxima = Math.min(310, Math.max(160, window.innerHeight * 0.42));
        let topo = rect.bottom + 4;
        if (espacoAbaixo < 180 && rect.top > espacoAbaixo) {
            topo = Math.max(margem, rect.top - Math.min(alturaMaxima, 310) - 4);
        }

        componente.menu.style.left = esquerda + 'px';
        componente.menu.style.top = topo + 'px';
        componente.menu.style.width = largura + 'px';
        componente.menu.style.maxHeight = alturaMaxima + 'px';
    }

    function fechar(componente) {
        if (!componente) return;
        componente.menu.hidden = true;
        componente.menu.innerHTML = '';
        componente.input.setAttribute('aria-expanded', 'false');
        componente.indiceAtivo = -1;
    }

    function sincronizarDoSelect(componente) {
        const option = opcaoSelecionadaReal(componente.select);
        componente.input.value = option ? String(option.textContent || '').trim() : '';
        componente.input.disabled = componente.select.disabled;
        componente.input.required = componente.select.required;
        componente.valorSelecionado = option?.value || '';
        componente.textoSelecionado = option ? String(option.textContent || '').trim() : '';
    }

    function selecionar(componente, option) {
        if (!option) return;
        componente.select.value = option.value;
        componente.select.dispatchEvent(new Event('input', { bubbles: true }));
        componente.select.dispatchEvent(new Event('change', { bubbles: true }));
        fechar(componente);
        setTimeout(function () {
            sincronizarDoSelect(componente);
            componente.input.focus();
        }, 0);
    }

    function renderizar(componente, termo) {
        const busca = normalizar(termo);
        const opcoes = opcoesDisponiveis(componente.select);
        const normais = [];
        const acoes = [];

        opcoes.forEach(function (option) {
            if (ehAcao(option)) {
                acoes.push(option);
                return;
            }
            if (!busca || normalizar(option.textContent).includes(busca) || normalizar(option.value).includes(busca)) {
                normais.push(option);
            }
        });

        const visiveis = normais.slice(0, MAX_RESULTADOS);
        let html = '';
        visiveis.forEach(function (option, indice) {
            const selecionada = option.value === componente.select.value;
            html += '<button type="button" class="gf-searchable-option' + (selecionada ? ' is-selected' : '') + '" data-gf-index="' + indice + '"><strong>' + escaparHtml(String(option.textContent || '').trim()) + '</strong></button>';
        });

        if (!visiveis.length) {
            html += '<div class="gf-searchable-empty">Nenhum resultado encontrado.</div>';
        }

        acoes.forEach(function (option, indice) {
            html += '<button type="button" class="gf-searchable-action" data-gf-action-index="' + indice + '">' + escaparHtml(String(option.textContent || '').trim()) + '</button>';
        });

        componente.menu.innerHTML = html;
        componente.opcoesRenderizadas = visiveis;
        componente.acoesRenderizadas = acoes;
        componente.indiceAtivo = -1;
        componente.menu.hidden = false;
        componente.input.setAttribute('aria-expanded', 'true');
        posicionarMenu(componente);

        componente.menu.querySelectorAll('.gf-searchable-option').forEach(function (botao) {
            botao.addEventListener('mousedown', function (event) { event.preventDefault(); });
            botao.addEventListener('click', function () {
                selecionar(componente, componente.opcoesRenderizadas[Number(botao.dataset.gfIndex)]);
            });
        });

        componente.menu.querySelectorAll('.gf-searchable-action').forEach(function (botao) {
            botao.addEventListener('mousedown', function (event) { event.preventDefault(); });
            botao.addEventListener('click', function () {
                selecionar(componente, componente.acoesRenderizadas[Number(botao.dataset.gfActionIndex)]);
            });
        });
    }

    function navegar(componente, event) {
        if (event.key === 'Escape') {
            fechar(componente);
            return;
        }
        if (!['ArrowDown', 'ArrowUp', 'Enter'].includes(event.key)) return;
        if (componente.menu.hidden) renderizar(componente, componente.input.value);

        const botoes = Array.from(componente.menu.querySelectorAll('.gf-searchable-option'));
        if (!botoes.length) return;

        if (event.key === 'Enter') {
            event.preventDefault();
            const indice = componente.indiceAtivo >= 0 ? componente.indiceAtivo : 0;
            botoes[indice]?.click();
            return;
        }

        event.preventDefault();
        if (event.key === 'ArrowDown') {
            componente.indiceAtivo = Math.min(componente.indiceAtivo + 1, botoes.length - 1);
        } else {
            componente.indiceAtivo = componente.indiceAtivo <= 0 ? botoes.length - 1 : componente.indiceAtivo - 1;
        }
        botoes.forEach(function (botao, indice) {
            botao.classList.toggle('is-active', indice === componente.indiceAtivo);
        });
        botoes[componente.indiceAtivo]?.scrollIntoView({ block: 'nearest' });
    }

    function limparBuscaAntigaMaterial(select) {
        if (!select.classList.contains('material-select')) return;
        const bloco = select.closest('.gerador-material-busca');
        const filtroAntigo = bloco?.querySelector('.gerador-material-filtro');
        if (filtroAntigo) {
            filtroAntigo.classList.add('gf-searchable-old-filter');
            filtroAntigo.tabIndex = -1;
            filtroAntigo.setAttribute('aria-hidden', 'true');
        }
    }

    function aprimorar(select) {
        if (!deveAprimorar(select) || select.dataset.gfSearchableReady === '1') return;
        select.dataset.gfSearchableReady = '1';
        select.classList.add('gf-searchable-native');
        select.tabIndex = -1;
        select.setAttribute('aria-hidden', 'true');

        const wrap = document.createElement('div');
        wrap.className = 'gf-searchable-wrap';
        const inputWrap = document.createElement('div');
        inputWrap.className = 'gf-searchable-input-wrap';
        const input = document.createElement('input');
        input.type = 'search';
        input.className = 'form-control gf-searchable-input';
        input.autocomplete = 'off';
        input.placeholder = placeholderDoSelect(select);
        input.setAttribute('role', 'combobox');
        input.setAttribute('aria-autocomplete', 'list');
        input.setAttribute('aria-expanded', 'false');
        input.setAttribute('aria-label', select.getAttribute('aria-label') || input.placeholder || 'Buscar');
        if (select.id) {
            input.id = select.id + '__busca';
            document.querySelectorAll('label[for="' + CSS.escape(select.id) + '"]').forEach(function (label) {
                label.setAttribute('for', input.id);
            });
        }

        const menu = document.createElement('div');
        menu.className = 'gf-searchable-menu';
        menu.hidden = true;
        menu.setAttribute('role', 'listbox');

        inputWrap.appendChild(input);
        wrap.appendChild(inputWrap);
        wrap.appendChild(menu);
        select.insertAdjacentElement('afterend', wrap);

        const componente = {
            select: select,
            wrap: wrap,
            input: input,
            menu: menu,
            indiceAtivo: -1,
            opcoesRenderizadas: [],
            acoesRenderizadas: [],
            valorSelecionado: '',
            textoSelecionado: ''
        };
        select._gfSearchable = componente;

        limparBuscaAntigaMaterial(select);
        sincronizarDoSelect(componente);

        input.addEventListener('focus', function () {
            if (input.disabled) return;
            renderizar(componente, input.value);
        });
        input.addEventListener('click', function () {
            if (input.disabled) return;
            renderizar(componente, input.value);
        });
        input.addEventListener('input', function () {
            if (normalizar(input.value) !== normalizar(componente.textoSelecionado)) {
                if (select.value && !String(select.value).startsWith('__novo_')) {
                    select.value = '';
                    componente.valorSelecionado = '';
                    select.dispatchEvent(new Event('input', { bubbles: true }));
                    select.dispatchEvent(new Event('change', { bubbles: true }));
                }
            }
            renderizar(componente, input.value);
        });
        input.addEventListener('keydown', function (event) { navegar(componente, event); });
        input.addEventListener('blur', function () {
            setTimeout(function () {
                if (!wrap.contains(document.activeElement)) {
                    fechar(componente);
                    if (!select.value) input.value = '';
                    else sincronizarDoSelect(componente);
                }
            }, 120);
        });

        select.addEventListener('change', function () {
            setTimeout(function () { sincronizarDoSelect(componente); }, 0);
        });
        select.addEventListener('invalid', function () {
            setTimeout(function () { input.focus(); renderizar(componente, input.value); }, 0);
        });

        const observadorOpcoes = new MutationObserver(function () {
            sincronizarDoSelect(componente);
            if (!menu.hidden) renderizar(componente, input.value);
        });
        observadorOpcoes.observe(select, { childList: true, subtree: true, attributes: true, attributeFilter: ['selected', 'disabled'] });
    }

    function varrer(raiz) {
        const contexto = raiz instanceof Element || raiz instanceof Document ? raiz : document;
        if (contexto instanceof HTMLSelectElement) aprimorar(contexto);
        contexto.querySelectorAll?.(SELECTOR_SELECTS).forEach(aprimorar);
    }

    function fecharTodos(exceto) {
        document.querySelectorAll('select[data-gf-searchable-ready="1"]').forEach(function (select) {
            const componente = select._gfSearchable;
            if (componente && componente !== exceto) fechar(componente);
        });
    }

    function iniciar() {
        injetarEstilos();
        varrer(document);

        const observador = new MutationObserver(function (mutacoes) {
            mutacoes.forEach(function (mutacao) {
                mutacao.addedNodes.forEach(function (node) {
                    if (node instanceof Element) varrer(node);
                });
            });
        });
        observador.observe(document.body, { childList: true, subtree: true });

        document.addEventListener('pointerdown', function (event) {
            const wrap = event.target.closest?.('.gf-searchable-wrap');
            const componente = wrap?.previousElementSibling?._gfSearchable || null;
            fecharTodos(componente);
        }, true);

        window.addEventListener('resize', function () {
            document.querySelectorAll('select[data-gf-searchable-ready="1"]').forEach(function (select) {
                const componente = select._gfSearchable;
                if (componente && !componente.menu.hidden) posicionarMenu(componente);
            });
        });
        window.addEventListener('scroll', function () {
            document.querySelectorAll('select[data-gf-searchable-ready="1"]').forEach(function (select) {
                const componente = select._gfSearchable;
                if (componente && !componente.menu.hidden) posicionarMenu(componente);
            });
        }, true);
    }

    window.GFSearchableSelect = {
        enhance: aprimorar,
        scan: varrer
    };

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', iniciar, { once: true });
    } else {
        iniciar();
    }
})();
