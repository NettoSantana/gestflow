# Caminho: C:\Users\vlula\OneDrive\Área de Trabalho\Projetos Backup\GESTFLOW\apps\indflow\modules\manutencao\routes.py
# Último recode: 2026-08-21 06:43 (America/Bahia)
# Motivo: Migrar para a estrutura consolidada GESTFLOW + INDFLOW na branch DEV, preservando o conteúdo funcional validado.

from flask import Blueprint, render_template

# =====================================================
# AUTH
# =====================================================
from modules.admin.routes import login_required

manutencao_bp = Blueprint("manutencao", __name__, template_folder="templates")

@manutencao_bp.route("/")
@login_required
def home():
    return render_template("manutencao_home.html")
