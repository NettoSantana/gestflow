# Caminho: C:\Users\vlula\OneDrive\Área de Trabalho\Projetos Backup\GESTFLOW\config.py
# Último recode: 2026-02-09 19:56 (America/Bahia)
# Motivo: Criação do arquivo central de configuração do GESTFLOW (DEV),
#         com carregamento de variáveis de ambiente (.env), Twilio Sandbox,
#         SQLite, PDF e parâmetros gerais do sistema.

import os
from pathlib import Path
from dotenv import load_dotenv

# ============================================================
# CARREGAMENTO DO .ENV
# ============================================================

BASE_DIR = Path(__file__).resolve().parent
ENV_PATH = BASE_DIR / ".env"

if ENV_PATH.exists():
    load_dotenv(ENV_PATH)
else:
    raise FileNotFoundError(f"Arquivo .env não encontrado em {ENV_PATH}")

# ============================================================
# AMBIENTE
# ============================================================

ENV = os.getenv("ENV", "DEV")
DEBUG = os.getenv("DEBUG", "true").lower() == "true"
TIMEZONE = os.getenv("TIMEZONE", "America/Bahia")

# ============================================================
# TWILIO / WHATSAPP (SANDBOX)
# ============================================================

TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
TWILIO_WHATSAPP_FROM = os.getenv("TWILIO_WHATSAPP_FROM")  # ex: whatsapp:+14155238886
WEBHOOK_PATH = os.getenv("WEBHOOK_PATH", "/bot")

if not TWILIO_ACCOUNT_SID or not TWILIO_AUTH_TOKEN or not TWILIO_WHATSAPP_FROM:
    raise RuntimeError("Variáveis do Twilio não configuradas corretamente no .env")

# ============================================================
# BANCO DE DADOS (SQLITE)
# ============================================================

DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)

SQLITE_DB_PATH = DATA_DIR / "gestflow.db"

# ============================================================
# BACKUPS
# ============================================================

BACKUP_DIR = BASE_DIR / "backups"
BACKUP_DIR.mkdir(exist_ok=True)

BACKUP_RETENTION_DAYS = int(os.getenv("BACKUP_RETENTION_DAYS", "30"))

# ============================================================
# PDF / ORÇAMENTOS
# ============================================================

PDF_TEMP_DIR = BASE_DIR / "tmp"
PDF_TEMP_DIR.mkdir(exist_ok=True)

ORCAMENTO_VALIDADE_DIAS = int(os.getenv("ORCAMENTO_VALIDADE_DIAS", "7"))

PDF_RODAPE_PADRAO = os.getenv(
    "PDF_RODAPE_PADRAO",
    "Orçamento gerado via GESTFLOW"
)

# ============================================================
# NUMERAÇÃO
# ============================================================

ORCAMENTO_PREFIX = "ORC"
VENDA_PREFIX = "VEN"

# ============================================================
# LIMITES / UX WHATSAPP
# ============================================================

MAX_MESSAGE_LENGTH = int(os.getenv("MAX_MESSAGE_LENGTH", "1500"))

# ============================================================
# FLAGS DO SISTEMA (MVP)
# ============================================================

CONFIRMAR_TODAS_ACOES = True
ESTOQUE_POR_MOVIMENTACAO = True
GERAR_PDF_ORCAMENTO = True
