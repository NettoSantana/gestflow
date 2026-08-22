# Caminho: C:\Users\vlula\OneDrive\Área de Trabalho\Projetos Backup\GESTFLOW\apps\indflow\modules\ativos\routes.py
# Último recode: 2026-08-21 06:43 (America/Bahia)
# Motivo: Migrar para a estrutura consolidada GESTFLOW + INDFLOW na branch DEV, preservando o conteúdo funcional validado.

from flask import Blueprint, render_template

from modules.admin.routes import login_required

ativos_bp = Blueprint("ativos", __name__, template_folder="templates")

@ativos_bp.route("/")
@login_required
def home():
    return render_template("ativos_home.html")
