# Caminho: C:\Users\vlula\OneDrive\Área de Trabalho\Projetos Backup\GESTFLOW\apps\indflow\modules\api\routes.py
# Último recode: 2026-08-21 06:43 (America/Bahia)
# Motivo: Migrar para a estrutura consolidada GESTFLOW + INDFLOW na branch DEV, preservando o conteúdo funcional validado.

from flask import Blueprint, jsonify

from modules.admin.routes import login_required

api_bp = Blueprint("api", __name__)

@api_bp.route("/ping")
@login_required
def ping():
    return jsonify({"status": "ok", "msg": "API IndFlow ativa"})
