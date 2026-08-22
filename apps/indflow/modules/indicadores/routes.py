# Caminho: C:\Users\vlula\OneDrive\Área de Trabalho\Projetos Backup\GESTFLOW\apps\indflow\modules\indicadores\routes.py
# Último recode: 2026-08-21 06:43 (America/Bahia)
# Motivo: Migrar para a estrutura consolidada GESTFLOW + INDFLOW na branch DEV, preservando o conteúdo funcional validado.

from __future__ import annotations

from datetime import date, datetime, timedelta
from flask import Blueprint, jsonify, render_template, request, session

from modules.admin.routes import login_required
from modules.paradas.services import general_indicator_summary, list_tenant_machines, machine_indicator_summary, normalize_machine_id, now_local

indicadores_bp = Blueprint("indicadores", __name__, template_folder="templates")


def _cliente_id() -> str:
    return str(session.get("cliente_id") or "").strip()


def _period() -> tuple[date, date]:
    today = now_local().date()
    try:
        end = datetime.strptime(request.args.get("fim") or today.isoformat(), "%Y-%m-%d").date()
    except Exception:
        end = today
    try:
        start = datetime.strptime(request.args.get("inicio") or (end - timedelta(days=6)).isoformat(), "%Y-%m-%d").date()
    except Exception:
        start = end - timedelta(days=6)
    if end < start:
        start, end = end, start
    if (end - start).days > 62:
        start = end - timedelta(days=62)
    return start, end


@indicadores_bp.get("/")
@login_required
def home():
    return render_template("indicadores_home.html")


@indicadores_bp.get("/maquina/<machine_id>")
@login_required
def machine_page(machine_id: str):
    return render_template("indicadores_maquina.html", machine_id=normalize_machine_id(machine_id, _cliente_id()))


@indicadores_bp.get("/api/resumo")
@login_required
def api_general():
    cid = _cliente_id()
    if not cid:
        return jsonify({"ok": False, "error": "Cliente da sessão não identificado."}), 403
    start, end = _period()
    include_test = request.args.get("teste") == "1"
    machines = list_tenant_machines(cid, include_test=include_test)
    data = general_indicator_summary(cid, start, end, machines=machines)
    data["inclui_teste"] = include_test
    return jsonify({"ok": True, "data": data})


@indicadores_bp.get("/api/maquina/<machine_id>")
@login_required
def api_machine(machine_id: str):
    cid = _cliente_id()
    if not cid:
        return jsonify({"ok": False, "error": "Cliente da sessão não identificado."}), 403
    start, end = _period()
    data = machine_indicator_summary(cid, normalize_machine_id(machine_id, cid), start, end)
    return jsonify({"ok": True, "data": data})
