# Caminho: C:\Users\vlula\OneDrive\Área de Trabalho\Projetos Backup\GESTFLOW\apps\indflow\modules\teste\routes.py
# Último recode: 2026-08-21 06:43 (America/Bahia)
# Motivo: Migrar para a estrutura consolidada GESTFLOW + INDFLOW na branch DEV, preservando o conteúdo funcional validado.

from __future__ import annotations

from flask import Blueprint, jsonify, render_template, session

from modules.admin.routes import admin_required
from modules.paradas.services import ensure_catalog_seed
from modules.teste.services import (
    TEST_MACHINE_ID,
    activate_test_scenario,
    is_test_machine,
    remove_test_scenario,
    test_default_day,
    test_period,
)


teste_bp = Blueprint("teste", __name__, template_folder="templates")


def _cliente_id() -> str:
    return str(session.get("cliente_id") or "").strip()


@teste_bp.get("/")
@admin_required
def home():
    cid = _cliente_id()
    active = is_test_machine(cid, TEST_MACHINE_ID)
    start, end = test_period()
    return render_template(
        "teste_home.html",
        machine_id=TEST_MACHINE_ID,
        ativo=active,
        inicio=start.isoformat(),
        fim=end.isoformat(),
        data_teste=test_default_day().isoformat(),
    )


@teste_bp.post("/api/ativar")
@admin_required
def api_activate():
    cid = _cliente_id()
    try:
        ensure_catalog_seed(cid)
        return jsonify({"ok": True, "data": activate_test_scenario(cid)})
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400


@teste_bp.post("/api/remover")
@admin_required
def api_remove():
    cid = _cliente_id()
    try:
        return jsonify({"ok": True, "data": remove_test_scenario(cid)})
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
