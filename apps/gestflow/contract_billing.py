# Caminho: C:\Users\vlula\OneDrive\Área de Trabalho\Projetos Backup\GESTFLOW\apps\gestflow\contract_billing.py
# Último recode: 2026-09-01 19:08 (America/Bahia)
# Motivo: Gerar Venda + Conta a Receber por competência de contrato ativo, sem retroagir cobranças anteriores à implantação e com proteção contra duplicidade.

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from typing import Any

from flask import request, session


_RUNTIME: Any = None
_ULTIMO_PROCESSAMENTO: dict[int, str] = {}


def _mesmo_mes(a: date, b: date) -> bool:
    return a.year == b.year and a.month == b.month


def _valor_contrato(contrato: dict[str, Any]) -> Decimal:
    recorrente = _RUNTIME._converter_valor_brl(contrato.get("valor_recorrente"))
    total = _RUNTIME._converter_valor_brl(contrato.get("valor_total"))
    return recorrente if recorrente > 0 else total


def _referencias_faturadas(contrato_id: int) -> list[date]:
    empresa_id = _RUNTIME.empresa_logada_id()
    with _RUNTIME.conectar_db() as conn:
        rows = conn.execute(
            """
            SELECT referencia
            FROM configuracoes_operacoes_automaticas
            WHERE empresa_id = ?
              AND modulo = 'contratos'
              AND entidade = 'contrato'
              AND registro_id = ?
              AND operacao = 'faturamento'
            ORDER BY referencia ASC
            """,
            (empresa_id, contrato_id),
        ).fetchall()

    referencias: list[date] = []
    for row in rows:
        try:
            referencias.append(date.fromisoformat(str(row["referencia"] or "")[:10]))
        except (TypeError, ValueError):
            continue
    return referencias




def _agenda_faturamento(contrato: dict[str, Any], datas: list[date] | None = None) -> list[date]:
    agenda = sorted({d for d in (datas or _RUNTIME._datas_operacoes_contrato(contrato)) if isinstance(d, date)})
    periodicidade = str(contrato.get("periodicidade") or "unica").strip().lower()
    renovacao = str(contrato.get("renovacao_automatica") or "nao").strip().lower()
    intervalo = {
        "mensal": 1,
        "bimestral": 2,
        "trimestral": 3,
        "semestral": 6,
        "anual": 12,
    }.get(periodicidade)

    if intervalo is None or renovacao != "sim":
        return agenda

    hoje = _RUNTIME.hoje_empresa()
    if agenda:
        atual = agenda[-1]
    else:
        dia = int(contrato.get("dia_vencimento") or 10)
        atual = _RUNTIME._data_com_dia_contrato(hoje, dia)
        if atual < hoje:
            atual = _RUNTIME._data_com_dia_contrato(
                _RUNTIME._somar_meses_contrato(hoje, intervalo),
                dia,
            )
        agenda.append(atual)

    limite = _RUNTIME._somar_meses_contrato(hoje, max(12, intervalo))
    while agenda[-1] < limite and len(agenda) < 240:
        agenda.append(_RUNTIME._somar_meses_contrato(agenda[-1], intervalo))

    return sorted(set(agenda))


def _referencias_a_gerar(contrato: dict[str, Any], datas: list[date]) -> list[date]:
    agenda = sorted({d for d in datas if isinstance(d, date)})
    if not agenda:
        return []

    contrato_id = int(contrato["id"])
    hoje = _RUNTIME.hoje_empresa()
    geradas = _referencias_faturadas(contrato_id)

    if not geradas:
        # Primeira execução: não cria histórico retroativo. Gera a competência
        # do mês atual; se ainda não houver uma, prepara a próxima cobrança.
        atual = [d for d in agenda if _mesmo_mes(d, hoje)]
        if atual:
            return [atual[0]]
        futuras = [d for d in agenda if d >= hoje]
        return futuras[:1]

    ultima = max(geradas)
    pendentes = [d for d in agenda if ultima < d <= hoje]
    corrente_futura = [
        d for d in agenda
        if d > ultima and d > hoje and _mesmo_mes(d, hoje)
    ]
    if corrente_futura:
        pendentes.append(corrente_futura[0])
    return sorted(set(pendentes))


def _tipo_venda_e_itens(
    contrato: dict[str, Any],
    referencia: date,
    valor: Decimal,
) -> tuple[str, str, str, list[dict[str, str]]]:
    contrato_id = int(contrato["id"])
    numero = str(contrato.get("numero") or contrato_id)
    itens_contrato = _RUNTIME.listar_contrato_itens(contrato_id)
    tem_produto = any(str(item.get("tipo_item") or "").strip().lower() == "produto" for item in itens_contrato)
    tem_servico = any(str(item.get("tipo_item") or "").strip().lower() != "produto" for item in itens_contrato)

    if tem_produto and tem_servico:
        tipo = "misto"
    elif tem_produto:
        tipo = "produto"
    else:
        tipo = "servico"

    valor_texto = _RUNTIME._formatar_moeda_brl(valor)
    total_produtos = valor_texto if tipo == "produto" else "0,00"
    total_servicos = valor_texto if tipo != "produto" else "0,00"
    competencia = referencia.strftime("%m/%Y")

    itens = [
        {
            "tipo_item": "produto" if tipo == "produto" else "servico",
            "descricao": f"Contrato {numero} - competência {competencia}",
            "detalhes": str(contrato.get("objeto") or contrato.get("titulo") or "").strip(),
            "quantidade": "1,00",
            "valor_unitario": valor_texto,
            "desconto": "0,00",
            "subtotal": valor_texto,
        }
    ]
    return tipo, total_produtos, total_servicos, itens


def _limpar_faturamento_parcial(venda_id: int | None, titulo_id: int | None) -> None:
    if not venda_id and not titulo_id:
        return
    empresa_id = _RUNTIME.empresa_logada_id()
    try:
        with _RUNTIME.conectar_db() as conn:
            if titulo_id:
                conn.execute(
                    "DELETE FROM financeiro_titulos WHERE id = ? AND empresa_id = ?",
                    (titulo_id, empresa_id),
                )
            if venda_id:
                conn.execute(
                    "DELETE FROM venda_itens WHERE venda_id = ? AND empresa_id = ?",
                    (venda_id, empresa_id),
                )
                conn.execute(
                    "DELETE FROM vendas WHERE id = ? AND empresa_id = ?",
                    (venda_id, empresa_id),
                )
            conn.commit()
    except Exception:
        _RUNTIME.app.logger.exception(
            "Falha ao limpar faturamento parcial do contrato: venda=%s titulo=%s",
            venda_id,
            titulo_id,
        )


def _gerar_competencia(contrato: dict[str, Any], referencia: date) -> bool:
    contrato_id = int(contrato["id"])
    valor = _valor_contrato(contrato)
    if valor <= 0:
        return False

    referencia_iso = referencia.isoformat()
    if not _RUNTIME._reservar_operacao_automatica_contrato(
        contrato_id,
        "faturamento",
        referencia_iso,
    ):
        return False

    venda_id: int | None = None
    titulo_id: int | None = None
    numero_contrato = str(contrato.get("numero") or contrato_id)
    competencia = referencia.strftime("%m/%Y")
    hoje_iso = _RUNTIME.hoje_empresa().isoformat()
    valor_texto = _RUNTIME._formatar_moeda_brl(valor)

    try:
        tipo, total_produtos, total_servicos, itens = _tipo_venda_e_itens(
            contrato,
            referencia,
            valor,
        )
        forma_pagamento = str(contrato.get("forma_pagamento") or "").strip()
        marcador = f"[CONTRATO:{contrato_id}:{referencia_iso}]"
        venda = {
            "numero": "",
            "cliente": str(contrato.get("cliente") or "").strip(),
            "responsavel": str(contrato.get("responsavel") or "").strip(),
            "data": hoje_iso,
            "prazo_entrega": "",
            "canal_venda": "Contrato",
            "centro_custo": str(contrato.get("centro_custo") or "").strip(),
            "centro_custo_id": str(contrato.get("centro_custo_id") or ""),
            "atividade_financeira_id": "",
            "tipo": tipo,
            "status": _RUNTIME.status_inicial_operacional("vendas"),
            "total_produtos": total_produtos,
            "total_servicos": total_servicos,
            "desconto_valor": "0,00",
            "desconto_percentual": "0,00",
            "valor_total": valor_texto,
            "forma_pagamento": forma_pagamento,
            "condicao_pagamento": "prazo",
            "meio_pagamento": forma_pagamento,
            "valor_entrada": "0,00",
            "meio_pagamento_entrada": "",
            "data_entrada": "",
            "quantidade_parcelas": "1",
            "primeiro_vencimento": referencia_iso,
            "intervalo_parcelas": str(contrato.get("periodicidade") or "mensal"),
            "observacoes": (
                f"Venda gerada automaticamente pelo contrato {numero_contrato} "
                f"referente à competência {competencia}."
            ),
            "observacoes_internas": (
                f"Origem automática: Contrato ID {contrato_id} / Nº {numero_contrato}. "
                f"{marcador}"
            ),
        }
        venda_id = _RUNTIME.salvar_venda_db(venda, itens)
        numero_venda = str(venda.get("numero") or venda_id)

        titulo_id = _RUNTIME.salvar_financeiro_titulo_db(
            {
                "tipo": "receber",
                "descricao": f"Venda Nº {numero_venda} - 1/1",
                "pessoa": str(contrato.get("cliente") or "").strip(),
                "categoria": "Venda",
                "centro_custo_id": str(contrato.get("centro_custo_id") or ""),
                "atividade_financeira_id": "",
                "origem": "venda",
                "origem_id": str(venda_id),
                "documento": f"Venda Nº {numero_venda} - 1/1",
                "data_emissao": hoje_iso,
                "data_vencimento": referencia_iso,
                "data_pagamento": "",
                "valor": valor_texto,
                "forma_pagamento": forma_pagamento,
                "status": "aberto",
                "observacoes": (
                    f"Gerado automaticamente pelo contrato {numero_contrato}, "
                    f"competência {competencia}."
                ),
            }
        )

        _RUNTIME._finalizar_operacao_automatica_contrato(
            contrato_id,
            "faturamento",
            referencia_iso,
            {"venda_id": venda_id, "titulo_id": titulo_id},
        )
        try:
            _RUNTIME.registrar_atividade_usuario(
                "criacao",
                "contratos",
                (
                    f"Gerou venda {numero_venda} e conta a receber do contrato "
                    f"{numero_contrato} - competência {competencia}"
                ),
                request.path,
                registro_id=contrato_id,
            )
        except Exception:
            pass
        return True
    except Exception:
        _limpar_faturamento_parcial(venda_id, titulo_id)
        _RUNTIME._liberar_operacao_automatica_contrato(
            contrato_id,
            "faturamento",
            referencia_iso,
        )
        raise


def _processar_contrato(contrato: dict[str, Any], datas: list[date] | None = None) -> int:
    if str(contrato.get("status") or "").strip().lower() != "ativo":
        return 0
    agenda = _agenda_faturamento(contrato, datas)
    total = 0
    for referencia in _referencias_a_gerar(contrato, agenda):
        if _gerar_competencia(contrato, referencia):
            total += 1
    return total


def _gerar_cobrancas_via_venda(
    contrato: dict[str, Any],
    datas: list[date],
) -> int:
    # Substitui a geração antiga de título isolado: a cobrança do contrato
    # agora nasce como Venda e a Conta a Receber fica vinculada a essa venda.
    return _processar_contrato(contrato, datas)


def _processar_recorrencias_do_dia() -> None:
    if not session.get("usuario_id") or not session.get("empresa_id"):
        return
    if request.path.startswith(("/static/", "/login", "/logout")):
        return

    empresa_id = _RUNTIME.empresa_logada_id()
    hoje_iso = _RUNTIME.hoje_empresa().isoformat()
    if _ULTIMO_PROCESSAMENTO.get(empresa_id) == hoje_iso:
        return
    try:
        with _RUNTIME.conectar_db() as conn:
            rows = conn.execute(
                """
                SELECT *
                FROM contratos
                WHERE empresa_id = ? AND status = 'ativo'
                ORDER BY id ASC
                """,
                (empresa_id,),
            ).fetchall()
        for row in rows:
            contrato = dict(row)
            try:
                _processar_contrato(contrato)
            except Exception:
                _RUNTIME.app.logger.exception(
                    "Falha ao processar faturamento recorrente do contrato %s.",
                    contrato.get("id"),
                )
        _ULTIMO_PROCESSAMENTO[empresa_id] = hoje_iso
    except Exception:
        _RUNTIME.app.logger.exception(
            "Falha ao verificar contratos ativos para faturamento recorrente."
        )


def instalar_integracao_contratos(runtime_module: Any) -> None:
    global _RUNTIME
    _RUNTIME = runtime_module

    # A função original gerava apenas financeiro e dependia de uma opção que
    # vinha desligada por padrão. A partir daqui, contrato ativo gera
    # Venda + Conta a Receber com idempotência por competência.
    runtime_module._gerar_cobrancas_contrato_configuradas = _gerar_cobrancas_via_venda
    runtime_module.app.before_request(_processar_recorrencias_do_dia)
