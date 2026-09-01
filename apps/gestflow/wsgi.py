# Caminho: C:\Users\vlula\OneDrive\Área de Trabalho\Projetos Backup\GESTFLOW\apps\gestflow\wsgi.py
# Último recode: 2026-09-01 19:08 (America/Bahia)
# Motivo: Registrar o faturamento automático de contratos ativos no bootstrap do GestFlow.

import app as gestflow_runtime
from contract_billing import instalar_integracao_contratos

app = gestflow_runtime.app
instalar_integracao_contratos(gestflow_runtime)
