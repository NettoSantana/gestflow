/*
Caminho: C:\Users\vlula\OneDrive\Área de Trabalho\Projetos Backup\GESTFLOW\apps\gestflow\static\js\configuracoes_modulos.js
Último recode: 2026-08-21 06:43 (America/Bahia)
Motivo: Migrar para a estrutura consolidada GESTFLOW + INDFLOW na branch DEV, preservando o conteúdo funcional validado.
*/

(function () {
    'use strict';

    const fonte = document.getElementById('gestflow-configuracoes-runtime');
    if (!fonte) return;

    let runtime = {};
    try {
        runtime = JSON.parse(fonte.textContent || '{}');
    } catch (erro) {
        console.error('GestFlow: configurações inválidas.', erro);
        return;
    }

    const valores = runtime.valores || {};
    const caminho = window.location.pathname;
    const normalizar = (valor) => String(valor == null ? '' : valor)
        .normalize('NFD').replace(/[\u0300-\u036f]/g, '')
        .toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_+|_+$/g, '');
    const lista = (modulo, chave) => {
        const valor = ((valores[modulo] || {})[chave]);
        if (Array.isArray(valor)) return valor.map(String).map(item => item.trim()).filter(Boolean);
        return String(valor == null ? '' : valor).split(/\r?\n/).map(item => item.trim()).filter(Boolean);
    };
    const obter = (modulo, chave, padrao) => {
        const moduloValores = valores[modulo] || {};
        return Object.prototype.hasOwnProperty.call(moduloValores, chave) ? moduloValores[chave] : padrao;
    };
    const booleano = (modulo, chave, padrao) => {
        const valor = obter(modulo, chave, padrao);
        if (typeof valor === 'boolean') return valor;
        return ['1', 'sim', 'true', 'ativo', 'obrigatorio'].includes(String(valor).toLowerCase());
    };

    function moduloAtual() {
        if (/^\/clientes|^\/fornecedores|^\/funcionarios/.test(caminho)) return 'cadastros';
        if (/^\/produtos/.test(caminho)) return 'produtos';
        if (/^\/servicos/.test(caminho)) return 'servicos';
        if (/^\/orcamentos/.test(caminho)) return 'orcamentos';
        if (/^\/vendas\/.*devol|^\/vendas\/devolucoes/.test(caminho)) return 'devolucoes';
        if (/^\/vendas/.test(caminho)) return 'vendas';
        if (/^\/ordens-servico|^\/os\//.test(caminho)) return 'ordens_servico';
        if (/^\/estoque\/compras/.test(caminho)) return 'compras';
        if (/^\/estoque/.test(caminho)) return 'estoque';
        if (/^\/financeiro\/centros|^\/financeiro\/atividades/.test(caminho)) return 'centros_custo_dre';
        if (/^\/financeiro/.test(caminho)) return 'financeiro';
        if (/^\/contratos/.test(caminho)) return 'contratos';
        if (/^\/gestao-atividades/.test(caminho)) return 'gestao_atividades';
        if (/^\/agendamentos|^\/agendar\//.test(caminho)) return 'agendamentos';
        if (/^\/registro-ponto|^\/ponto\//.test(caminho)) return 'registro_ponto';
        if (/^\/vitrine/.test(caminho)) return 'vitrine';
        return '';
    }

    const modulo = moduloAtual();
    if (!modulo) return;

    const campo = (nome, raiz) => (raiz || document).querySelector(`[name="${nome}"]`);
    const campos = (nome, raiz) => Array.from((raiz || document).querySelectorAll(`[name="${nome}"]`));
    const preencherSeVazio = (nome, valor, raiz) => {
        if (valor == null || valor === '') return;
        campos(nome, raiz).forEach(elemento => {
            if (!String(elemento.value || '').trim()) elemento.value = String(valor);
        });
    };
    const definirMaximo = (nome, valor) => {
        campos(nome).forEach(elemento => elemento.max = String(valor));
    };
    const exigir = (nome, ativo) => {
        campos(nome).forEach(elemento => {
            elemento.required = Boolean(ativo);
            elemento.setAttribute('aria-required', ativo ? 'true' : 'false');
        });
    };
    const esconder = (seletor, esconderElemento) => {
        document.querySelectorAll(seletor).forEach(elemento => {
            const alvo = elemento.closest('label, .form-group, .field, .card, .action-item') || elemento;
            alvo.hidden = Boolean(esconderElemento);
        });
    };

    function valorOption(rotulo, nomeCampo) {
        const mapa = {
            ativo: 'ativo', inativo: 'inativo', pendente: 'pendente', bloqueado: 'bloqueado',
            aberto: 'aberto', aberta: 'aberta', enviado: 'enviado', aprovada: 'aprovado', aprovado: 'aprovado',
            reprovado: 'reprovado', cancelado: 'cancelado', cancelada: 'cancelada', concluida: 'concluida',
            concluido: 'concluido', em_andamento: 'andamento', aguardando: 'aguardando', pausada: 'pausada',
            planejada: 'planejada', normal: 'normal', baixa: 'baixa', alta: 'alta', urgente: 'urgente',
            dinheiro: 'dinheiro', pix: 'pix', boleto: 'boleto', transferencia: 'transferencia',
            cartao_de_debito: 'cartao_debito', cartao_de_credito: 'cartao_credito',
            a_vista: 'avista', a_prazo: 'prazo', parcelado: 'parcelado', entrada_parcelas: 'entrada_parcelas'
            , servico_recorrente: 'recorrente', cobranca_unica: 'unica', aguardando_assinatura: 'aguardando_assinatura'
        };
        const chave = normalizar(rotulo);
        if (/unidade|categoria|motivo|forma_pagamento/.test(nomeCampo) && !Object.prototype.hasOwnProperty.call(mapa, chave)) {
            return String(rotulo);
        }
        return mapa[chave] || chave;
    }

    function aplicarOpcoes(nomeCampo, moduloConfig, chave, manterVazio) {
        const opcoes = lista(moduloConfig, chave);
        if (!opcoes.length) return;
        campos(nomeCampo).forEach(select => {
            if (select.tagName !== 'SELECT') {
                const id = `lista_config_${normalizar(nomeCampo)}_${Math.random().toString(36).slice(2, 7)}`;
                const datalist = document.createElement('datalist');
                datalist.id = id;
                opcoes.forEach(rotulo => {
                    const option = document.createElement('option');
                    option.value = rotulo;
                    datalist.appendChild(option);
                });
                document.body.appendChild(datalist);
                select.setAttribute('list', id);
                return;
            }
            const atual = select.value;
            const vazioOriginal = Array.from(select.options).find(option => !option.value);
            select.innerHTML = '';
            if (manterVazio !== false) {
                const vazio = document.createElement('option');
                vazio.value = '';
                vazio.textContent = vazioOriginal ? vazioOriginal.textContent : 'Selecione';
                select.appendChild(vazio);
            }
            opcoes.forEach(rotulo => {
                const option = document.createElement('option');
                option.value = valorOption(rotulo, nomeCampo);
                option.textContent = rotulo;
                select.appendChild(option);
            });
            const compativel = Array.from(select.options).find(option =>
                option.value === atual || normalizar(option.textContent) === normalizar(atual)
            );
            if (compativel) select.value = compativel.value;
        });
    }

    const mapasOpcoes = {
        cadastros: [
            ['cliente_status', 'cadastros', 'status_padrao'],
            ['fornecedor_categoria', 'cadastros', 'categorias_fornecedores'],
        ],
        produtos: [
            ['produto_categoria', 'produtos', 'categorias'], ['produto_unidade', 'produtos', 'unidades_medida'],
        ],
        servicos: [
            ['servico_categoria', 'servicos', 'categorias'], ['servico_unidade', 'servicos', 'unidades_cobranca'],
        ],
        orcamentos: [
            ['orcamento_status', 'orcamentos', 'situacoes'], ['orcamento_forma_pagamento', 'vendas', 'formas_pagamento'],
        ],
        vendas: [
            ['venda_status', 'vendas', 'situacoes'], ['venda_forma_pagamento', 'vendas', 'formas_pagamento'],
            ['venda_meio_pagamento', 'vendas', 'formas_pagamento'], ['venda_meio_pagamento_entrada', 'vendas', 'formas_pagamento'],
            ['forma_pagamento', 'vendas', 'formas_pagamento'], ['condicao_pagamento', 'vendas', 'condicoes_pagamento'],
        ],
        devolucoes: [['devolucao_motivo', 'devolucoes', 'motivos'], ['devolucao_condicao', 'devolucoes', 'condicoes_produto']],
        ordens_servico: [
            ['os_status', 'ordens_servico', 'situacoes'], ['os_prioridade', 'ordens_servico', 'prioridades'],
            ['os_tipo', 'ordens_servico', 'tipos_os'], ['os_forma_pagamento', 'vendas', 'formas_pagamento'],
        ],
        estoque: [['estoque_tipo', 'estoque', 'tipos_movimentacao'], ['estoque_motivo', 'estoque', 'motivos_ajuste']],
        compras: [['config_extra__compras__tipo_compra', 'compras', 'tipos_compra'], ['config_extra__compras__forma_pagamento', 'compras', 'formas_pagamento']],
        financeiro: [
            ['financeiro_categoria', 'financeiro', 'categorias_receitas'], ['financeiro_forma_pagamento', 'financeiro', 'formas_pagamento'],
            ['financeiro_status', 'financeiro', 'situacoes_lancamentos'],
        ],
        contratos: [
            ['tipo', 'contratos', 'tipos'], ['status', 'contratos', 'situacoes'],
            ['periodicidade', 'contratos', 'frequencia_cobranca'], ['forma_pagamento', 'financeiro', 'formas_pagamento'],
        ],
        gestao_atividades: [
            ['tipo', 'gestao_atividades', 'tipos'], ['prioridade', 'gestao_atividades', 'prioridades'],
            ['status', 'gestao_atividades', 'situacoes'],
        ],
        agendamentos: [['status', 'agendamentos', 'situacoes'], ['servico_nome', 'agendamentos', 'servicos_disponiveis']],
        registro_ponto: [['editar_justificativa', 'registro_ponto', 'justificativas']],
        vitrine: [['categoria', 'vitrine', 'categorias_publicas']],
    };
    (mapasOpcoes[modulo] || []).forEach(item => aplicarOpcoes(item[0], item[1], item[2]));

    function aplicarPadroes() {
        const aplicarModeloImpressao = (moduloConfig) => {
            const modelo = String(obter(moduloConfig, 'modelo_impressao', 'a4'));
            if (!['a4', 'cupom'].includes(modelo)) return;
            document.querySelectorAll('a[href*="/imprimir/"]').forEach(link => {
                link.href = link.href.replace(/\/imprimir\/(?:a4|cupom)(?=$|[?#])/, `/imprimir/${modelo}`);
            });
        };
        if (modulo === 'cadastros') {
            preencherSeVazio('cliente_status', obter('cadastros', 'status_padrao', 'ativo'));
            preencherSeVazio('fornecedor_status', obter('cadastros', 'status_padrao', 'ativo'));
            preencherSeVazio('cliente_observacoes', obter('cadastros', 'observacoes_padrao', ''));
        }
        if (modulo === 'produtos') {
            preencherSeVazio('produto_estoque_minimo', obter('produtos', 'estoque_minimo_padrao', 0));
            preencherSeVazio('produto_unidade', lista('produtos', 'unidades_medida')[0] || 'UN');
            esconder('[name="componente_produto_id"], [name="composicao_custo_descricao"]', !booleano('produtos', 'produto_composto', true));
        }
        if (modulo === 'servicos') {
            preencherSeVazio('servico_unidade', lista('servicos', 'unidades_cobranca')[0] || 'Serviço');
            preencherSeVazio('servico_tempo_estimado', obter('servicos', 'tempo_estimado_horas', 1));
            preencherSeVazio('servico_valor_venda', obter('servicos', 'valor_padrao', 0));
            preencherSeVazio('servico_custo', obter('servicos', 'custo_estimado_padrao', 0));
        }
        if (modulo === 'orcamentos') {
            aplicarModeloImpressao('orcamentos');
            preencherSeVazio('orcamento_prazo_entrega', obter('orcamentos', 'prazo_execucao_padrao', 'A combinar'));
            preencherSeVazio('orcamento_forma_pagamento', obter('orcamentos', 'condicoes_pagamento_padrao', ''));
            preencherSeVazio('orcamento_observacoes', obter('orcamentos', 'observacoes_padrao', ''));
            preencherSeVazio('orcamento_modo_apresentacao', obter('orcamentos', 'modo_apresentacao_padrao', 'agrupado'));
            preencherSeVazio('gerador_prazo', obter('orcamentos', 'prazo_execucao_padrao', 'A combinar'));
            preencherSeVazio('gerador_forma_pagamento', obter('orcamentos', 'condicoes_pagamento_padrao', ''));
            definirMaximo('orcamento_desconto_percentual', obter('orcamentos', 'desconto_maximo_percentual', 100));
            definirMaximo('item_desconto', obter('orcamentos', 'desconto_maximo_percentual', 100));
            document.querySelectorAll('a[href*="/gerar/venda"]').forEach(a => a.hidden = !booleano('orcamentos', 'converter_venda', true));
            document.querySelectorAll('a[href*="/gerar/os"]').forEach(a => a.hidden = !booleano('orcamentos', 'converter_os', true));
        }
        if (modulo === 'vendas') {
            aplicarModeloImpressao('vendas');
            definirMaximo('venda_desconto_percentual', obter('vendas', 'desconto_maximo_percentual', 100));
            definirMaximo('quantidade_parcelas', obter('vendas', 'maximo_parcelas', 12));
            definirMaximo('venda_quantidade_parcelas', obter('vendas', 'maximo_parcelas', 12));
            preencherSeVazio('venda_responsavel', obter('vendas', 'vendedor_padrao', ''));
            preencherSeVazio('venda_observacoes', obter('vendas', 'observacoes_padrao', ''));
            exigir('venda_cliente', booleano('vendas', 'cliente_obrigatorio', false));
        }
        if (modulo === 'ordens_servico') {
            aplicarModeloImpressao('ordens_servico');
            preencherSeVazio('os_tecnico', obter('ordens_servico', 'tecnico_padrao', ''));
            preencherSeVazio('os_termos', obter('ordens_servico', 'termos_padrao', ''));
            exigir('os_serie', booleano('ordens_servico', 'exigir_numero_serie', false));
            esconder('a[href*="qrcode"], button[data-action*="qrcode"]', !booleano('ordens_servico', 'usar_qrcode', true));
            esconder('[name="os_equipamentos_json"]', !booleano('ordens_servico', 'permitir_varios_equipamentos', true));
            exigir('foto_os_antes', booleano('ordens_servico', 'exigir_fotos_antes', false));
            exigir('foto_os_depois', booleano('ordens_servico', 'exigir_fotos_depois', false));
        }
        if (modulo === 'financeiro') {
            preencherSeVazio('financeiro_categoria', lista('financeiro', 'categorias_receitas')[0] || 'Vendas');
        }
        if (modulo === 'contratos') {
            preencherSeVazio('forma_pagamento', lista('financeiro', 'formas_pagamento')[0] || 'PIX');
            preencherSeVazio('dia_vencimento', obter('contratos', 'dia_vencimento', 10));
        }
        if (modulo === 'gestao_atividades') {
            esconder('a[href*="cronograma"]', !booleano('gestao_atividades', 'exibir_gantt', true));
            esconder('[name="depende_etapa_id"]', !booleano('gestao_atividades', 'permitir_dependencias', true));
        }
        if (modulo === 'agendamentos') {
            const hoje = new Date();
            const minimo = new Date(hoje.getTime() + Number(obter('agendamentos', 'antecedencia_minima_horas', 2)) * 3600000);
            const maximo = new Date(hoje.getTime() + Number(obter('agendamentos', 'antecedencia_maxima_dias', 90)) * 86400000);
            campos('data_agendamento').forEach(input => {
                input.min = minimo.toISOString().slice(0, 10);
                input.max = maximo.toISOString().slice(0, 10);
            });
            campos('hora_inicio').forEach(input => {
                input.min = String(obter('agendamentos', 'horario_inicio', '08:00'));
                input.max = String(obter('agendamentos', 'horario_fim', '18:00'));
                input.step = String(Number(obter('agendamentos', 'intervalo_minutos', 30)) * 60);
            });
            exigir('cliente_nome', booleano('agendamentos', 'cliente_obrigatorio', true));
        }
        if (modulo === 'registro_ponto') {
            const exigirGps = booleano('registro_ponto', 'gps_obrigatorio', true);
            exigir('latitude', exigirGps); exigir('longitude', exigirGps);
            esconder('[data-offline], .offline-status', !booleano('registro_ponto', 'permitir_offline', true));
            if (!booleano('registro_ponto', 'validacao_celular', true)) exigir('telefone', false);
        }
        if (modulo === 'vitrine') {
            preencherSeVazio('nome_loja', obter('vitrine', 'nome_publico', ''));
            preencherSeVazio('slug', obter('vitrine', 'slug', ''));
            preencherSeVazio('cor_principal', obter('vitrine', 'cor_primaria', '#1458f5'));
            preencherSeVazio('cor_secundaria', obter('vitrine', 'cor_secundaria', '#0f172a'));
            preencherSeVazio('whatsapp', obter('vitrine', 'whatsapp', ''));
            esconder('[data-preco], [name="preco"]', !booleano('vitrine', 'exibir_preco', true));
        }
    }

    const descritores = {
        cadastros: [['categoria_cliente', 'Categoria do cliente'], ['origem_cliente', 'Origem do cliente'], ['segmento_atuacao', 'Segmento de atuação'], ['limite_credito', 'Limite de crédito']],
        produtos: [['grupo', 'Grupo'], ['subgrupo', 'Subgrupo'], ['marca', 'Marca'], ['cor', 'Cor'], ['tamanho', 'Tamanho'], ['lote', 'Lote'], ['validade', 'Validade'], ['numero_serie', 'Número de série'], ['localizacao', 'Localização'], ['estoque_maximo', 'Estoque máximo']],
        servicos: [['grupo', 'Grupo'], ['garantia_dias', 'Garantia (dias)'], ['comissao', 'Comissão (%)'], ['responsavel_padrao', 'Responsável padrão']],
        orcamentos: [['tabela_preco', 'Tabela de preço'], ['modelo_escopo', 'Modelo de escopo']],
        vendas: [['tabela_preco', 'Tabela de preço'], ['comissao_vendedor', 'Comissão do vendedor (%)']],
        devolucoes: [['motivo', 'Motivo'], ['condicao_produto', 'Condição do produto'], ['local_estoque', 'Local de estoque']],
        ordens_servico: [['tipo_atendimento', 'Tipo de atendimento'], ['setor_responsavel', 'Setor responsável'], ['garantia_dias', 'Garantia (dias)'], ['categoria_equipamento', 'Categoria do equipamento']],
        estoque: [['local_entrada', 'Local de entrada'], ['local_saida', 'Local de saída'], ['lote', 'Lote'], ['validade', 'Validade'], ['numero_serie', 'Número de série']],
        compras: [['numero', 'Número da compra'], ['situacao', 'Situação'], ['tipo_compra', 'Tipo de compra'], ['condicao_pagamento', 'Condição de pagamento'], ['forma_pagamento', 'Forma de pagamento'], ['frete', 'Frete'], ['impostos', 'Impostos'], ['despesas', 'Outras despesas']],
        financeiro: [['subcategoria', 'Subcategoria'], ['conta_caixa', 'Conta/Caixa'], ['tipo_documento', 'Tipo de documento'], ['competencia', 'Competência']],
        contratos: [['modelo', 'Modelo de contrato'], ['indice_reajuste', 'Índice de reajuste'], ['carencia_dias', 'Carência (dias)'], ['multa_cancelamento', 'Multa de cancelamento']],
        gestao_atividades: [['categoria', 'Categoria'], ['equipe', 'Equipe'], ['checklist', 'Checklist']],
        agendamentos: [['tipo', 'Tipo de agendamento'], ['sinal', 'Valor do sinal']],
        registro_ponto: [['escala', 'Escala'], ['jornada', 'Jornada'], ['trabalho_especial', 'Trabalho especial']],
        vitrine: [['regiao_entrega', 'Região de entrega'], ['taxa_entrega', 'Taxa de entrega']],
    };

    function entidadeAtual() {
        if (modulo === 'cadastros') {
            if (/fornecedores/.test(caminho)) return 'fornecedor';
            if (/funcionarios/.test(caminho)) return 'funcionario';
            return 'cliente';
        }
        return ({produtos: 'produto', servicos: 'servico', orcamentos: 'orcamento', vendas: 'venda', devolucoes: 'devolucao', ordens_servico: 'ordem_servico', estoque: 'movimentacao', compras: 'compra', financeiro: 'titulo', contratos: 'contrato', gestao_atividades: 'atividade', agendamentos: 'agendamento', registro_ponto: 'registro', vitrine: 'publicacao'})[modulo] || modulo;
    }

    function formularioPrincipal() {
        const primarios = {
            cadastros: ['cliente_nome', 'fornecedor_nome', 'funcionario_nome'], produtos: ['produto_nome'],
            servicos: ['servico_nome'], orcamentos: ['orcamento_cliente'], vendas: ['venda_cliente'],
            devolucoes: ['devolucao_responsavel'], ordens_servico: ['os_cliente'], estoque: ['estoque_produto_id'],
            compras: ['compra_produto_id'], financeiro: ['financeiro_descricao'], contratos: ['titulo'],
            gestao_atividades: ['titulo'], agendamentos: ['cliente_nome'], registro_ponto: ['ajuste_funcionario_id'],
            vitrine: ['nome_loja']
        };
        for (const nome of (primarios[modulo] || [])) {
            const elemento = campo(nome);
            if (elemento && elemento.form) return elemento.form;
        }
        return null;
    }

    function opcoesAvancadas(chave) {
        const mapa = {
            grupo: ['produtos', 'grupos'], subgrupo: ['produtos', 'subgrupos'], marca: ['produtos', 'marcas'],
            cor: ['produtos', 'cores'], tamanho: ['produtos', 'tamanhos'], categoria_cliente: ['cadastros', 'categorias_clientes'],
            origem_cliente: ['cadastros', 'origens_cliente'], segmento_atuacao: ['cadastros', 'segmentos_atuacao'],
            tipo_atendimento: ['ordens_servico', 'tipos_atendimento'], setor_responsavel: ['ordens_servico', 'setores_responsaveis'],
            tipo_compra: ['compras', 'tipos_compra'], situacao: ['compras', 'situacoes'],
            conta_caixa: ['financeiro', 'contas_caixas'], tipo_documento: ['financeiro', 'tipos_documento'],
            modelo: ['contratos', 'modelos'], indice_reajuste: ['contratos', 'indices_reajuste'],
            equipe: ['gestao_atividades', 'equipes'], escala: ['registro_ponto', 'escalas'],
            trabalho_especial: ['registro_ponto', 'trabalhos_especiais']
        };
        const origem = mapa[chave];
        return origem ? lista(origem[0], origem[1]) : [];
    }

    async function injetarCamposConfiguraveis() {
        const form = formularioPrincipal();
        if (!form || form.querySelector('.gestflow-campos-configuraveis')) return;
        const configurados = lista(modulo, 'campos_extras').map(nome => [normalizar(nome), nome]);
        const todos = [...(descritores[modulo] || []), ...configurados];
        const unicos = [];
        const vistos = new Set();
        todos.forEach(item => {
            if (!item[0] || vistos.has(item[0])) return;
            vistos.add(item[0]); unicos.push(item);
        });
        if (!unicos.length) return;

        const bloco = document.createElement('fieldset');
        bloco.className = 'gestflow-campos-configuraveis';
        bloco.innerHTML = `
            <legend class="gestflow-config-title">
                <span class="gestflow-config-title-icon" aria-hidden="true">⚙</span>
                <span>Campos definidos nas configurações</span>
            </legend>
            <p class="gestflow-config-description">
                Estes campos seguem as opções configuradas para este módulo.
            </p>
            <div class="gestflow-config-grid"></div>
        `;
        const grid = bloco.querySelector('.gestflow-config-grid');
        unicos.forEach(([chave, rotulo]) => {
            const label = document.createElement('label');
            label.textContent = rotulo;
            const opcoes = opcoesAvancadas(chave);
            let input;
            if (opcoes.length) {
                input = document.createElement('select');
                input.innerHTML = '<option value="">Selecione</option>' + opcoes.map(item => `<option value="${String(item).replace(/"/g, '&quot;')}">${item}</option>`).join('');
            } else {
                input = document.createElement('input');
                input.type = /data|validade|competencia/.test(chave) ? 'date' : (/valor|preco|limite|comissao|margem|frete|imposto|despesa|taxa|dias/.test(chave) ? 'number' : 'text');
                if (input.type === 'number') input.step = '0.01';
            }
            input.name = `config_extra__${modulo}__${chave}`;
            input.classList.add('form-control', 'gestflow-config-control');
            label.classList.add('gestflow-config-field');
            label.appendChild(input);
            grid.appendChild(label);
        });
        const acoes = form.querySelector('.form-actions, .actions, [type="submit"]');
        if (acoes && acoes.matches('[type="submit"]')) form.insertBefore(bloco, acoes);
        else if (acoes) form.insertBefore(bloco, acoes);
        else form.appendChild(bloco);

        const ids = caminho.match(/\/(\d+)(?:\/editar)?\/?$/);
        if (!ids) return;
        try {
            const resposta = await fetch(`/api/configuracoes/entidade/${modulo}/${entidadeAtual()}/${ids[1]}`, {credentials: 'same-origin'});
            const payload = await resposta.json();
            Object.entries(payload.dados || {}).forEach(([chave, valor]) => {
                const input = form.querySelector(`[name="config_extra__${modulo}__${chave}"]`);
                if (input) input.value = valor == null ? '' : String(valor);
            });
        } catch (erro) {
            console.warn('GestFlow: não foi possível carregar os campos configuráveis.', erro);
        }
    }

    function iniciar() {
        aplicarPadroes();
        injetarCamposConfiguraveis();
        document.documentElement.dataset.gestflowModuloConfigurado = modulo;
    }

    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', iniciar);
    else iniciar();
})();
