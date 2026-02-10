# Caminho: C:\Users\vlula\OneDrive\Área de Trabalho\Projetos Backup\GESTFLOW\database.py
# Último recode: 2026-02-09 20:43 (America/Bahia)
# Motivo: Implementar núcleo SQLite do GESTFLOW (conexão + init_db com criação de tabelas/índices
#         e seed mínimo DEV), mantendo SQL centralizado e simples.

from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Optional, Tuple

import config


def _utc_iso() -> str:
    return datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")


def _dict_row_factory(cursor: sqlite3.Cursor, row: Tuple[Any, ...]) -> Dict[str, Any]:
    return {col[0]: row[idx] for idx, col in enumerate(cursor.description)}


def _ensure_parent_dir(db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)


def get_connection() -> sqlite3.Connection:
    """
    Abre conexão SQLite no caminho padrão do projeto, com PRAGMAs razoáveis para DEV/MVP.
    """
    db_path = Path(config.SQLITE_DB_PATH)
    _ensure_parent_dir(db_path)

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = _dict_row_factory

    # PRAGMAs simples e seguros para MVP.
    # WAL melhora concorrência (mesmo em SQLite); foreign_keys reforça integridade.
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.execute("PRAGMA journal_mode = WAL;")
    conn.execute("PRAGMA synchronous = NORMAL;")

    return conn


@contextmanager
def db_cursor() -> Iterator[sqlite3.Cursor]:
    """
    Context manager para cursor com commit/rollback.
    """
    conn = get_connection()
    cur = conn.cursor()
    try:
        yield cur
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()
        conn.close()


def _exec_many(cur: sqlite3.Cursor, statements: Iterable[str]) -> None:
    for stmt in statements:
        cur.execute(stmt)


def init_db() -> None:
    """
    Cria tabelas e índices se não existirem e faz seed mínimo para DEV.
    """
    with db_cursor() as cur:
        # ------------------------------------------------------------
        # TABELAS BASE
        # ------------------------------------------------------------
        _exec_many(
            cur,
            [
                """
                CREATE TABLE IF NOT EXISTS companies (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                """,
                """
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    company_id INTEGER NOT NULL,
                    whatsapp TEXT NOT NULL,
                    name TEXT NOT NULL,
                    role TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (company_id) REFERENCES companies(id)
                );
                """,
                """
                CREATE TABLE IF NOT EXISTS customers (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    company_id INTEGER NOT NULL,
                    name TEXT NOT NULL,
                    phone TEXT,
                    active INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (company_id) REFERENCES companies(id)
                );
                """,
                """
                CREATE TABLE IF NOT EXISTS products (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    company_id INTEGER NOT NULL,
                    code TEXT NOT NULL,
                    name TEXT NOT NULL,
                    price_sale REAL NOT NULL,
                    active INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (company_id) REFERENCES companies(id)
                );
                """,
                """
                CREATE TABLE IF NOT EXISTS services (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    company_id INTEGER NOT NULL,
                    code TEXT NOT NULL,
                    name TEXT NOT NULL,
                    price_sale REAL NOT NULL,
                    active INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (company_id) REFERENCES companies(id)
                );
                """,
            ],
        )

        # ------------------------------------------------------------
        # ORÇAMENTOS
        # ------------------------------------------------------------
        _exec_many(
            cur,
            [
                """
                CREATE TABLE IF NOT EXISTS budgets (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    company_id INTEGER NOT NULL,
                    code TEXT NOT NULL,
                    customer_id INTEGER NOT NULL,
                    status TEXT NOT NULL, -- draft | confirmed | cancelled | approved
                    total REAL NOT NULL DEFAULT 0,
                    created_by INTEGER,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY (company_id) REFERENCES companies(id),
                    FOREIGN KEY (customer_id) REFERENCES customers(id),
                    FOREIGN KEY (created_by) REFERENCES users(id)
                );
                """,
                """
                CREATE TABLE IF NOT EXISTS budget_items (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    company_id INTEGER NOT NULL,
                    budget_id INTEGER NOT NULL,
                    item_type TEXT NOT NULL, -- product | service
                    item_id INTEGER NOT NULL,
                    description_snapshot TEXT NOT NULL,
                    unit_price REAL NOT NULL,
                    qty REAL NOT NULL,
                    subtotal REAL NOT NULL,
                    FOREIGN KEY (company_id) REFERENCES companies(id),
                    FOREIGN KEY (budget_id) REFERENCES budgets(id)
                );
                """,
            ],
        )

        # ------------------------------------------------------------
        # VENDAS
        # ------------------------------------------------------------
        _exec_many(
            cur,
            [
                """
                CREATE TABLE IF NOT EXISTS sales (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    company_id INTEGER NOT NULL,
                    code TEXT NOT NULL,
                    budget_id INTEGER,
                    customer_id INTEGER NOT NULL,
                    status TEXT NOT NULL, -- open | paid | cancelled
                    total REAL NOT NULL DEFAULT 0,
                    created_by INTEGER,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (company_id) REFERENCES companies(id),
                    FOREIGN KEY (budget_id) REFERENCES budgets(id),
                    FOREIGN KEY (customer_id) REFERENCES customers(id),
                    FOREIGN KEY (created_by) REFERENCES users(id)
                );
                """,
                """
                CREATE TABLE IF NOT EXISTS sale_items (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    company_id INTEGER NOT NULL,
                    sale_id INTEGER NOT NULL,
                    item_type TEXT NOT NULL, -- product | service
                    item_id INTEGER NOT NULL,
                    description_snapshot TEXT NOT NULL,
                    unit_price REAL NOT NULL,
                    qty REAL NOT NULL,
                    subtotal REAL NOT NULL,
                    FOREIGN KEY (company_id) REFERENCES companies(id),
                    FOREIGN KEY (sale_id) REFERENCES sales(id)
                );
                """,
            ],
        )

        # ------------------------------------------------------------
        # ESTOQUE (MOVIMENTAÇÕES)
        # Regra MVP: qty sempre positivo, direction vem do movement_type.
        # movement_type: in | out | sale
        # ------------------------------------------------------------
        _exec_many(
            cur,
            [
                """
                CREATE TABLE IF NOT EXISTS stock_movements (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    company_id INTEGER NOT NULL,
                    product_id INTEGER NOT NULL,
                    movement_type TEXT NOT NULL, -- in | out | sale
                    qty REAL NOT NULL, -- sempre positivo
                    reason TEXT,
                    ref_type TEXT, -- sale | manual | other
                    ref_id INTEGER,
                    created_by INTEGER,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (company_id) REFERENCES companies(id),
                    FOREIGN KEY (product_id) REFERENCES products(id),
                    FOREIGN KEY (created_by) REFERENCES users(id)
                );
                """,
            ],
        )

        # ------------------------------------------------------------
        # FINANCEIRO
        # Regra MVP: contas a receber só para fiado.
        # ------------------------------------------------------------
        _exec_many(
            cur,
            [
                """
                CREATE TABLE IF NOT EXISTS accounts_receivable (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    company_id INTEGER NOT NULL,
                    sale_id INTEGER NOT NULL,
                    status TEXT NOT NULL, -- open | partial | paid | cancelled
                    due_date TEXT NOT NULL, -- YYYY-MM-DD
                    total REAL NOT NULL,
                    paid_total REAL NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (company_id) REFERENCES companies(id),
                    FOREIGN KEY (sale_id) REFERENCES sales(id)
                );
                """,
                """
                CREATE TABLE IF NOT EXISTS accounts_payable (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    company_id INTEGER NOT NULL,
                    supplier_name TEXT NOT NULL,
                    description TEXT,
                    status TEXT NOT NULL, -- open | partial | paid | cancelled
                    due_date TEXT NOT NULL, -- YYYY-MM-DD
                    total REAL NOT NULL,
                    paid_total REAL NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (company_id) REFERENCES companies(id)
                );
                """,
                """
                CREATE TABLE IF NOT EXISTS payments (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    company_id INTEGER NOT NULL,
                    direction TEXT NOT NULL, -- in | out
                    origin_type TEXT NOT NULL, -- receivable | payable | sale_direct | manual
                    origin_id INTEGER,
                    method TEXT NOT NULL, -- pix | cash | card | transfer
                    amount REAL NOT NULL,
                    paid_at TEXT NOT NULL, -- ISO
                    created_by INTEGER,
                    note TEXT,
                    FOREIGN KEY (company_id) REFERENCES companies(id),
                    FOREIGN KEY (created_by) REFERENCES users(id)
                );
                """,
            ],
        )

        # ------------------------------------------------------------
        # SESSÃO WHATSAPP (ESTADO DA CONVERSA)
        # ------------------------------------------------------------
        _exec_many(
            cur,
            [
                """
                CREATE TABLE IF NOT EXISTS wa_sessions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    company_id INTEGER NOT NULL,
                    whatsapp TEXT NOT NULL,
                    state TEXT NOT NULL,
                    context_json TEXT,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY (company_id) REFERENCES companies(id)
                );
                """,
            ],
        )

        # ------------------------------------------------------------
        # SEQUÊNCIAS (POR ANO)
        # key: BUDGET | SALE
        # year: AAAA
        # next_number: próximo inteiro a emitir
        # ------------------------------------------------------------
        _exec_many(
            cur,
            [
                """
                CREATE TABLE IF NOT EXISTS sequences (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    company_id INTEGER NOT NULL,
                    key TEXT NOT NULL,
                    year INTEGER NOT NULL,
                    next_number INTEGER NOT NULL,
                    UNIQUE(company_id, key, year),
                    FOREIGN KEY (company_id) REFERENCES companies(id)
                );
                """,
            ],
        )

        # ------------------------------------------------------------
        # BACKUPS
        # ------------------------------------------------------------
        _exec_many(
            cur,
            [
                """
                CREATE TABLE IF NOT EXISTS backups (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    company_id INTEGER NOT NULL,
                    backup_date TEXT NOT NULL, -- YYYY-MM-DD
                    file_name TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (company_id) REFERENCES companies(id)
                );
                """,
            ],
        )

        # ------------------------------------------------------------
        # ÍNDICES / CONSTRAINTS ÚTEIS
        # ------------------------------------------------------------
        _exec_many(
            cur,
            [
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_users_company_whatsapp ON users(company_id, whatsapp);",
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_products_company_code ON products(company_id, code);",
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_services_company_code ON services(company_id, code);",
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_budgets_company_code ON budgets(company_id, code);",
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_sales_company_code ON sales(company_id, code);",
                "CREATE INDEX IF NOT EXISTS idx_budget_items_budget_id ON budget_items(budget_id);",
                "CREATE INDEX IF NOT EXISTS idx_sale_items_sale_id ON sale_items(sale_id);",
                "CREATE INDEX IF NOT EXISTS idx_stock_movements_product_id ON stock_movements(product_id);",
                "CREATE INDEX IF NOT EXISTS idx_payments_paid_at ON payments(paid_at);",
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_sessions_company_whatsapp ON wa_sessions(company_id, whatsapp);",
                "CREATE INDEX IF NOT EXISTS idx_ar_sale_id ON accounts_receivable(sale_id);",
            ],
        )

        # ------------------------------------------------------------
        # SEED MÍNIMO (DEV)
        # - cria 1 company se não existir
        # - cria 1 user owner se variáveis existirem e ainda não existir
        # ------------------------------------------------------------
        now = _utc_iso()

        existing_company = cur.execute("SELECT id FROM companies ORDER BY id LIMIT 1;").fetchone()
        if not existing_company:
            company_name = os.getenv("GESTFLOW_COMPANY_NAME", "GESTFLOW")
            cur.execute(
                "INSERT INTO companies (name, created_at) VALUES (?, ?);",
                (company_name, now),
            )
            company_id = int(cur.lastrowid)
        else:
            company_id = int(existing_company["id"])

        owner_whatsapp = (os.getenv("GESTFLOW_OWNER_WHATSAPP") or "").strip()
        owner_name = (os.getenv("GESTFLOW_OWNER_NAME") or "Dono").strip()

        if owner_whatsapp:
            exists_owner = cur.execute(
                "SELECT id FROM users WHERE company_id=? AND whatsapp=? LIMIT 1;",
                (company_id, owner_whatsapp),
            ).fetchone()

            if not exists_owner:
                cur.execute(
                    "INSERT INTO users (company_id, whatsapp, name, role, created_at) VALUES (?, ?, ?, ?, ?);",
                    (company_id, owner_whatsapp, owner_name, "owner", now),
                )


def fetch_one(sql: str, params: Tuple[Any, ...] = ()) -> Optional[Dict[str, Any]]:
    with db_cursor() as cur:
        row = cur.execute(sql, params).fetchone()
        return row


def fetch_all(sql: str, params: Tuple[Any, ...] = ()) -> List[Dict[str, Any]]:
    with db_cursor() as cur:
        rows = cur.execute(sql, params).fetchall()
        return list(rows or [])


def execute(sql: str, params: Tuple[Any, ...] = ()) -> int:
    """
    Executa INSERT/UPDATE/DELETE e retorna lastrowid (0 se não aplicável).
    """
    with db_cursor() as cur:
        cur.execute(sql, params)
        try:
            return int(cur.lastrowid or 0)
        except Exception:
            return 0
