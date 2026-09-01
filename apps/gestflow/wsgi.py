# Caminho: C:\Users\vlula\OneDrive\Área de Trabalho\Projetos Backup\GESTFLOW\apps\gestflow\wsgi.py
# Último recode: 2026-09-01 19:39 (America/Bahia)
# Motivo: Registrar faturamento automático de contratos e as novas ações administrativas de Financeiro e Usuários.

import app as gestflow_runtime
from admin_runtime_actions import instalar_acoes_administrativas
from contract_billing import instalar_integracao_contratos

app = gestflow_runtime.app
instalar_integracao_contratos(gestflow_runtime)
instalar_acoes_administrativas(gestflow_runtime)
