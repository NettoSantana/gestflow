# Caminho: C:\Users\vlula\OneDrive\Área de Trabalho\Projetos Backup\GESTFLOW\apps\indflow\modules\producao\data.py
# Último recode: 2026-08-31 11:14 (America/Bahia)
# Motivo: Unificar o histórico diário no mesmo banco SQLite central do IndFlow antes da migração do ambiente antigo para GESTFLOW/INDFLOW.

from datetime import date

try:
    from modules.db_indflow import get_db as _get_db, init_db as _init_main_db
except Exception:
    from ..db_indflow import get_db as _get_db, init_db as _init_main_db


# ============================================
# CONEXÃO
# ============================================
def get_conn():
    """Usa a conexão central do IndFlow.

    Em Railway, modules.db_indflow resolve INDFLOW_DB_PATH e usa /data/indflow.db
    como fallback persistente. Isso evita a criação acidental de um segundo
    arquivo relativo ./indflow.db apenas para o histórico diário.
    """
    return _get_db()


# ============================================
# INIT DB
# ============================================
def init_db():
    """Delega a criação/migração de schema ao inicializador central.

    Isso é importante porque este módulo é importado antes do server.py chamar
    init_db(). Se criássemos aqui uma tabela producao_diaria simplificada, ela
    poderia nascer com schema incompleto no banco principal.
    """
    _init_main_db()


# ============================================
# SALVAR PRODUÇÃO DO DIA
# ============================================
def salvar_producao_diaria(machine_id, produzido, meta):
    conn = get_conn()
    try:
        cur = conn.cursor()
        hoje = date.today().isoformat()

        cur.execute(
            """
            INSERT INTO producao_diaria (machine_id, data, produzido, meta)
            VALUES (?, ?, ?, ?)
            """,
            (machine_id, hoje, produzido, meta),
        )

        conn.commit()
    finally:
        conn.close()


# ============================================
# LER HISTÓRICO
# ============================================
def listar_historico(machine_id=None, limit=30):
    conn = get_conn()
    try:
        cur = conn.cursor()

        if machine_id:
            cur.execute(
                """
                SELECT machine_id, data, produzido, meta
                FROM producao_diaria
                WHERE machine_id = ?
                ORDER BY data DESC
                LIMIT ?
                """,
                (machine_id, limit),
            )
        else:
            cur.execute(
                """
                SELECT machine_id, data, produzido, meta
                FROM producao_diaria
                ORDER BY data DESC
                LIMIT ?
                """,
                (limit,),
            )

        rows = cur.fetchall()
    finally:
        conn.close()

    return [
        {
            "machine_id": r[0],
            "data": r[1],
            "produzido": r[2],
            "meta": r[3],
            "percentual": round((r[2] / r[3]) * 100) if r[3] > 0 else 0,
        }
        for r in rows
    ]
