# Caminho: C:\Users\vlula\OneDrive\Área de Trabalho\Projetos Backup\GESTFLOW\apps\indflow\modules\teste\routes.py
# Último recode: 2026-09-02 21:45 (America/Bahia)
# Motivo: Desativar a página Dados de teste, preservando as APIs técnicas internas para não afetar o restante do IndFlow.

from __future__ import annotations

from flask import Blueprint, jsonify, redirect, render_template, session

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
    return redirect("/")


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
