# Caminho: C:\Users\vlula\OneDrive\Área de Trabalho\Projetos Backup\GESTFLOW\apps\gestflow\wsgi.py
# Último recode: 2026-11-14 06:47:08 (America/Bahia)
# Motivo: Unir DEV e MAIN preservando as funções existentes dos dois sistemas.

import app as gestflow_runtime
from admin_runtime_actions import instalar_acoes_administrativas
from contract_billing import instalar_integracao_contratos
from maintenance_runtime import instalar_modulo_manutencao

app = gestflow_runtime.app
instalar_integracao_contratos(gestflow_runtime)
instalar_acoes_administrativas(gestflow_runtime)
instalar_modulo_manutencao(gestflow_runtime)

from access_runtime import instalar_controle_acesso
instalar_controle_acesso(gestflow_runtime)
