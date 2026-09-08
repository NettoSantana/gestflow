# Caminho: C:\Users\vlula\OneDrive\Área de Trabalho\Projetos Backup\GESTFLOW\apps\gestflow\wsgi.py
# Último recode: 2026-09-08 03:49 (America/Bahia)
# Motivo: Registrar o módulo Manutenção V1 no runtime do GestFlow, preservando as integrações existentes.

import app as gestflow_runtime
from admin_runtime_actions import instalar_acoes_administrativas
from contract_billing import instalar_integracao_contratos
from maintenance_runtime import instalar_modulo_manutencao

app = gestflow_runtime.app
instalar_integracao_contratos(gestflow_runtime)
instalar_acoes_administrativas(gestflow_runtime)
instalar_modulo_manutencao(gestflow_runtime)
