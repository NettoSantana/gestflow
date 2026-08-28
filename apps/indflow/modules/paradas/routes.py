# Caminho: C:\Users\vlula\OneDrive\Área de Trabalho\Projetos Backup\GESTFLOW\apps\indflow\modules\paradas\routes.py
# Último recode: 2026-08-21 06:43 (America/Bahia)
# Motivo: Migrar para a estrutura consolidada GESTFLOW + INDFLOW na branch DEV, preservando o conteúdo funcional validado.

from __future__ import annotations

from datetime import date, datetime, timedelta
from flask import Blueprint, jsonify, render_template, request, session

from modules.admin.routes import admin_required, login_required
from modules.paradas.services import (
    classify_occurrence,
    ensure_catalog_seed,
    list_categories,
    list_occurrences,
    list_reasons,
    list_tenant_machines,
    normalize_machine_id,
    now_local,
    save_category,
    save_reason,
    sync_detected_stops,
    resolve_detected_occurrence,
)

paradas_bp = Blueprint("paradas", __name__, template_folder="templates")


def _cliente_id() -> str:
    return str(session.get("cliente_id") or "").strip()


def _parse_day(value: str | None, fallback: date) -> date:
    try:
        return datetime.strptime(str(value or ""), "%Y-%m-%d").date()
    except Exception:
        return fallback


def _period_from_request(default_days: int = 1) -> tuple[date, date]:
    today = now_local().date()
    end = _parse_day(request.args.get("fim") or request.args.get("date"), today)
    start = _parse_day(request.args.get("inicio"), end - timedelta(days=max(0, default_days - 1)))
    if end < start:
        start, end = end, start
    if (end - start).days > 62:
        start = end - timedelta(days=62)
    return start, end


@paradas_bp.get("/")
@login_required
def home():
    cid = _cliente_id()
    ensure_catalog_seed(cid)
    return render_template("paradas_home.html")


@paradas_bp.get("/catalogo")
@admin_required
def catalogo_page():
    cid = _cliente_id()
    ensure_catalog_seed(cid)
    return render_template("paradas_catalogo.html")


@paradas_bp.get("/api/contexto")
@login_required
def api_contexto():
    cid = _cliente_id()
    if not cid:
        return jsonify({"ok": False, "error": "Cliente da sessão não identificado."}), 403
    ensure_catalog_seed(cid)
    include_test = request.args.get("teste") == "1"
    return jsonify(
        {
            "ok": True,
            "machines": list_tenant_machines(cid, include_test=include_test),
            "categories": list_categories(cid),
            "reasons": list_reasons(cid),
        }
    )


@paradas_bp.get("/api/catalogo")
@login_required
def api_catalogo():
    cid = _cliente_id()
    if not cid:
        return jsonify({"ok": False, "error": "Cliente da sessão não identificado."}), 403
    machine_id = normalize_machine_id(request.args.get("machine_id") or "", cid)
    category_id = request.args.get("categoria_id")
    try:
        category_id_int = int(category_id) if category_id else None
    except Exception:
        category_id_int = None
    return jsonify(
        {
            "ok": True,
            "categories": list_categories(cid, include_inactive=request.args.get("todos") == "1"),
            "reasons": list_reasons(
                cid,
                machine_id=machine_id or None,
                category_id=category_id_int,
                include_inactive=request.args.get("todos") == "1",
            ),
            "machines": list_tenant_machines(cid, include_test=request.args.get("teste") == "1"),
        }
    )


@paradas_bp.post("/api/categorias")
@admin_required
def api_save_category():
    cid = _cliente_id()
    try:
        result = save_category(cid, request.get_json(silent=True) or {})
        return jsonify({"ok": True, "categoria": result})
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400


@paradas_bp.post("/api/motivos")
@admin_required
def api_save_reason():
    cid = _cliente_id()
    try:
        result = save_reason(cid, request.get_json(silent=True) or {})
        return jsonify({"ok": True, "motivo": result})
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400


@paradas_bp.get("/api/ocorrencias")
@login_required
def api_occurrences():
    cid = _cliente_id()
    if not cid:
        return jsonify({"ok": False, "error": "Cliente da sessão não identificado."}), 403
    start, end = _period_from_request(default_days=1)
    machine_id = normalize_machine_id(request.args.get("machine_id") or "", cid)
    only_unclassified = request.args.get("nao_classificadas") == "1"

    if machine_id:
        sync_detected_stops(cid, machine_id, start, end)
        rows = list_occurrences(cid, machine_id, start, end, sync=False, only_unclassified=only_unclassified)
    else:
        rows = []
        for mid in list_tenant_machines(cid, include_test=request.args.get("teste") == "1")[:50]:
            sync_detected_stops(cid, mid, start, end)
            rows.extend(list_occurrences(cid, mid, start, end, sync=False, only_unclassified=only_unclassified))
        rows.sort(key=lambda x: int(x.get("started_at_ms") or 0), reverse=True)

    return jsonify({"ok": True, "inicio": start.isoformat(), "fim": end.isoformat(), "rows": rows})


@paradas_bp.post("/api/ocorrencias/garantir")
@login_required
def api_ensure_occurrence():
    cid = _cliente_id()
    payload = request.get_json(silent=True) or {}
    machine_id = normalize_machine_id(payload.get("machine_id") or "", cid)
    try:
        start_ms = int(payload.get("started_at_ms"))
        end_raw = payload.get("ended_at_ms")
        end_ms = int(end_raw) if end_raw not in (None, "") else None
    except Exception:
        return jsonify({"ok": False, "error": "Intervalo de parada inválido."}), 400
    if not machine_id or start_ms <= 0:
        return jsonify({"ok": False, "error": "Máquina e início são obrigatórios."}), 400
    try:
        occurrence_id = resolve_detected_occurrence(cid, machine_id, start_ms, end_ms)
        return jsonify({"ok": True, "id": occurrence_id})
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400


@paradas_bp.post("/api/ocorrencias/classificar")
@login_required
def api_classify_occurrence():
    cid = _cliente_id()
    payload = request.get_json(silent=True) or {}
    try:
        occurrence_id = int(payload.get("id") or 0)
        motivo_id = int(payload.get("motivo_id") or 0)
    except Exception:
        occurrence_id = 0
        motivo_id = 0
    if occurrence_id <= 0 or motivo_id <= 0:
        return jsonify({"ok": False, "error": "Parada e motivo são obrigatórios."}), 400
    try:
        result = classify_occurrence(
            cid,
            occurrence_id,
            motivo_id,
            str(payload.get("observacao") or ""),
            str(payload.get("responsavel") or ""),
            str(session.get("email") or session.get("user_id") or ""),
        )
        return jsonify({"ok": True, "classificacao": result})
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
