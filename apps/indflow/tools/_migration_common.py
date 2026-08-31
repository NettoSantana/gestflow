# Caminho: C:\Users\vlula\OneDrive\Área de Trabalho\Projetos Backup\GESTFLOW\apps\indflow\tools\_migration_common.py
# Último recode: 2026-08-31 11:14 (America/Bahia)
# Motivo: Centralizar verificações de integridade e manifesto usadas na migração segura do SQLite do IndFlow.

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


MANIFEST_VERSION = 1

CRITICAL_TABLES = (
    "clientes",
    "usuarios",
    "devices",
    "machine_config",
    "machine_config_tenant",
    "baseline_diario",
    "producao_evento",
    "producao_horaria",
    "producao_diaria",
    "machine_state_event",
    "ordens_producao",
    "ordens_producao_bobina_eventos",
    "ordens_producao_bobina_pendencia",
    "esp_reset_cmd",
    "machine_stop",
    "refugo_horaria",
    "nao_programado_diario",
    "nao_programado_horaria",
    "integracao_gestflow_empresas",
    "integracao_gestflow_usuarios",
)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def railway_default_db_path() -> Path:
    configured = (os.getenv("INDFLOW_DB_PATH") or "").strip()
    if configured:
        return Path(configured)

    if any(
        (os.getenv(k) or "").strip()
        for k in (
            "RAILWAY_ENVIRONMENT",
            "RAILWAY_PROJECT_ID",
            "RAILWAY_SERVICE_ID",
            "RAILWAY_VOLUME_MOUNT_PATH",
        )
    ):
        return Path("/data/indflow.db")

    if Path("/data").exists():
        return Path("/data/indflow.db")

    return Path("indflow.db")


def ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        while True:
            chunk = fh.read(chunk_size)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def connect_readonly(path: Path) -> sqlite3.Connection:
    uri = f"file:{path.resolve().as_posix()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True, timeout=30)
    conn.row_factory = sqlite3.Row
    return conn


def table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=? LIMIT 1",
        (table,),
    ).fetchone()
    return row is not None


def list_user_tables(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute(
        """
        SELECT name
        FROM sqlite_master
        WHERE type='table'
          AND name NOT LIKE 'sqlite_%'
        ORDER BY name
        """
    ).fetchall()
    return [str(r[0]) for r in rows]


def table_columns(conn: sqlite3.Connection, table: str) -> list[str]:
    try:
        return [str(r[1]) for r in conn.execute(f'PRAGMA table_info("{table}")').fetchall()]
    except Exception:
        return []


def integrity_check(conn: sqlite3.Connection) -> list[str]:
    try:
        rows = conn.execute("PRAGMA integrity_check").fetchall()
        return [str(r[0]) for r in rows]
    except Exception as exc:
        return [f"ERROR: {exc}"]


def schema_digest(conn: sqlite3.Connection) -> str:
    rows = conn.execute(
        """
        SELECT type, name, tbl_name, COALESCE(sql, '')
        FROM sqlite_master
        WHERE name NOT LIKE 'sqlite_%'
        ORDER BY type, name
        """
    ).fetchall()
    payload = "\n".join("|".join(str(v or "") for v in row) for row in rows)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _count_table(conn: sqlite3.Connection, table: str) -> int | None:
    try:
        row = conn.execute(f'SELECT COUNT(1) FROM "{table}"').fetchone()
        return int(row[0] or 0) if row else 0
    except Exception:
        return None


def _max_numeric(conn: sqlite3.Connection, table: str, column: str) -> int | None:
    if column not in table_columns(conn, table):
        return None
    try:
        row = conn.execute(f'SELECT MAX("{column}") FROM "{table}"').fetchone()
        if not row or row[0] is None:
            return None
        return int(row[0])
    except Exception:
        return None


def _max_text(conn: sqlite3.Connection, table: str, column: str) -> str | None:
    if column not in table_columns(conn, table):
        return None
    try:
        row = conn.execute(f'SELECT MAX("{column}") FROM "{table}"').fetchone()
        if not row or row[0] is None:
            return None
        return str(row[0])
    except Exception:
        return None


def _distinct_count(conn: sqlite3.Connection, table: str, column: str) -> int | None:
    if column not in table_columns(conn, table):
        return None
    try:
        row = conn.execute(
            f'SELECT COUNT(DISTINCT "{column}") FROM "{table}" WHERE "{column}" IS NOT NULL'
        ).fetchone()
        return int(row[0] or 0) if row else 0
    except Exception:
        return None


def collect_summary(path: Path, include_sha256: bool = True) -> dict[str, Any]:
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(f"Banco nao encontrado: {path}")

    conn = connect_readonly(path)
    try:
        tables = list_user_tables(conn)
        counts = {table: _count_table(conn, table) for table in tables}
        critical = {}

        for table in CRITICAL_TABLES:
            exists = table in tables
            critical[table] = {
                "exists": exists,
                "rows": counts.get(table) if exists else None,
            }

        markers: dict[str, Any] = {}
        if "producao_evento" in tables:
            markers["producao_evento"] = {
                "max_id": _max_numeric(conn, "producao_evento", "id"),
                "max_ts_ms": _max_numeric(conn, "producao_evento", "ts_ms"),
                "clientes": _distinct_count(conn, "producao_evento", "cliente_id"),
                "maquinas": _distinct_count(conn, "producao_evento", "machine_id"),
            }
        if "devices" in tables:
            markers["devices"] = {
                "max_last_seen": _max_text(conn, "devices", "last_seen"),
                "clientes": _distinct_count(conn, "devices", "cliente_id"),
                "maquinas": _distinct_count(conn, "devices", "machine_id"),
            }
        if "baseline_diario" in tables:
            markers["baseline_diario"] = {
                "max_id": _max_numeric(conn, "baseline_diario", "id"),
                "max_updated_at": _max_text(conn, "baseline_diario", "updated_at"),
                "clientes": _distinct_count(conn, "baseline_diario", "cliente_id"),
                "maquinas": _distinct_count(conn, "baseline_diario", "machine_id"),
            }
        if "ordens_producao" in tables:
            markers["ordens_producao"] = {
                "max_id": _max_numeric(conn, "ordens_producao", "id"),
                "clientes": _distinct_count(conn, "ordens_producao", "cliente_id"),
                "maquinas": _distinct_count(conn, "ordens_producao", "machine_id"),
            }

        page_count = int(conn.execute("PRAGMA page_count").fetchone()[0] or 0)
        page_size = int(conn.execute("PRAGMA page_size").fetchone()[0] or 0)
        integrity = integrity_check(conn)
        schema_sha = schema_digest(conn)
    finally:
        conn.close()

    result: dict[str, Any] = {
        "manifest_version": MANIFEST_VERSION,
        "generated_at_utc": utc_now_iso(),
        "db_file": path.name,
        "size_bytes": int(path.stat().st_size),
        "page_count": page_count,
        "page_size": page_size,
        "integrity_check": integrity,
        "integrity_ok": integrity == ["ok"],
        "schema_sha256": schema_sha,
        "table_count": len(tables),
        "tables": counts,
        "critical_tables": critical,
        "markers": markers,
    }

    if include_sha256:
        result["sha256"] = sha256_file(path)

    return result


def write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    ensure_parent(path)
    tmp = path.with_name(path.name + ".tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2, sort_keys=True)
        fh.write("\n")
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)


def read_manifest(path: Path) -> dict[str, Any]:
    with Path(path).open("r", encoding="utf-8") as fh:
        data = json.load(fh)
    if not isinstance(data, dict):
        raise ValueError("Manifesto invalido")
    return data


def compare_summary_to_manifest(summary: dict[str, Any], manifest: dict[str, Any]) -> list[str]:
    errors: list[str] = []

    expected_sha = str(manifest.get("sha256") or "").strip()
    actual_sha = str(summary.get("sha256") or "").strip()
    if expected_sha and actual_sha and expected_sha != actual_sha:
        errors.append(f"SHA256 diferente: esperado={expected_sha} atual={actual_sha}")

    expected_schema = str(manifest.get("schema_sha256") or "").strip()
    actual_schema = str(summary.get("schema_sha256") or "").strip()
    if expected_schema and actual_schema and expected_schema != actual_schema:
        errors.append("Schema SHA256 diferente")

    expected_tables = manifest.get("tables") or {}
    actual_tables = summary.get("tables") or {}
    if isinstance(expected_tables, dict) and isinstance(actual_tables, dict):
        for table, expected_count in expected_tables.items():
            if table not in actual_tables:
                errors.append(f"Tabela ausente: {table}")
                continue
            if actual_tables.get(table) != expected_count:
                errors.append(
                    f"Quantidade diferente em {table}: esperado={expected_count} atual={actual_tables.get(table)}"
                )

    if not bool(summary.get("integrity_ok")):
        errors.append(f"PRAGMA integrity_check falhou: {summary.get('integrity_check')}")

    return errors
