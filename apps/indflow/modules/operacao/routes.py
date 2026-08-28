# Caminho: C:\Users\vlula\OneDrive\Área de Trabalho\Projetos Backup\GESTFLOW\apps\indflow\modules\operacao\routes.py
# Último recode: 2026-08-21 06:43 (America/Bahia)
# Motivo: Migrar para a estrutura consolidada GESTFLOW + INDFLOW na branch DEV, preservando o conteúdo funcional validado.

from __future__ import annotations

from flask import Blueprint, jsonify, render_template, request, session

from modules.admin.routes import admin_required, login_required
from modules.paradas.services import normalize_machine_id
from modules.operacao.services import (
    classify_pending_occurrence,
    get_operational_config,
    get_operational_state,
    list_operational_machines,
    list_operational_reasons,
    save_operational_config,
)

operacao_bp = Blueprint("operacao", __name__, template_folder="templates")


def _cliente_id() -> str:
    return str(session.get("cliente_id") or "").strip()


def _resolve_machine(cid: str, raw_machine: str | None) -> tuple[str, list[str]]:
    machines = list_operational_machines(cid)
    machine_id = normalize_machine_id(raw_machine or "", cid)
    known = {m.casefold(): m for m in machines}
    if machine_id and machine_id.casefold() in known:
        machine_id = known[machine_id.casefold()]
    elif machines:
        machine_id = machines[0]
    else:
        machine_id = ""
    return machine_id, machines


@operacao_bp.get("/")
@login_required
def home():
    cid = _cliente_id()
    machine_id, machines = _resolve_machine(cid, request.args.get("machine_id"))
    return render_template(
        "operacao_home.html",
        machine_id=machine_id,
        machines=machines,
    )


@operacao_bp.get("/api/contexto")
@login_required
def api_contexto():
    cid = _cliente_id()
    if not cid:
        return jsonify({"ok": False, "error": "Cliente da sessão não identificado."}), 403
    machine_id, machines = _resolve_machine(cid, request.args.get("machine_id"))
    if not machine_id:
        return jsonify({"ok": True, "machine_id": "", "machines": [], "config": None, "reasons": []})
    config = get_operational_config(cid, machine_id)
    return jsonify(
        {
            "ok": True,
            "machine_id": machine_id,
            "machines": machines,
            "config": config,
            "reasons": list_operational_reasons(cid, machine_id, config["ordenacao"]),
        }
    )


@operacao_bp.get("/api/estado")
@login_required
def api_estado():
    cid = _cliente_id()
    if not cid:
        return jsonify({"ok": False, "error": "Cliente da sessão não identificado."}), 403
    machine_id, _ = _resolve_machine(cid, request.args.get("machine_id"))
    if not machine_id:
        return jsonify({"ok": False, "error": "Nenhuma máquina disponível para a empresa atual."}), 404
    try:
        return jsonify({"ok": True, "data": get_operational_state(cid, machine_id)})
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400


@operacao_bp.post("/api/classificar")
@login_required
def api_classificar():
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
        result = classify_pending_occurrence(
            cid,
            occurrence_id,
            motivo_id,
            str(session.get("email") or session.get("user_id") or ""),
        )
        return jsonify({"ok": True, "classificacao": result})
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400


@operacao_bp.post("/api/config")
@admin_required
def api_config():
    cid = _cliente_id()
    payload = request.get_json(silent=True) or {}
    machine_id = normalize_machine_id(payload.get("machine_id") or "", cid)
    if not machine_id:
        return jsonify({"ok": False, "error": "Máquina é obrigatória."}), 400
    known = {m.casefold(): m for m in list_operational_machines(cid)}
    if machine_id.casefold() not in known:
        return jsonify({"ok": False, "error": "Máquina não pertence à empresa atual."}), 400
    machine_id = known[machine_id.casefold()]
    try:
        config = save_operational_config(cid, machine_id, payload)
        return jsonify({"ok": True, "config": config})
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
