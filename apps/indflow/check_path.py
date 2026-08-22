# Caminho: C:\Users\vlula\OneDrive\Área de Trabalho\Projetos Backup\GESTFLOW\apps\indflow\check_path.py
# Último recode: 2026-08-21 06:43 (America/Bahia)
# Motivo: Migrar para a estrutura consolidada GESTFLOW + INDFLOW na branch DEV, preservando o conteúdo funcional validado.

import os
from modules.db_indflow import _default_db_path

print("DB PATH:", _default_db_path())
print("ENV INDFLOW_DB_PATH:", os.getenv("INDFLOW_DB_PATH"))
