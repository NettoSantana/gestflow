# Caminho: C:\Users\vlula\OneDrive\Área de Trabalho\Projetos Backup\GESTFLOW\apps\indflow\modules\tenant_runtime_safety.py
# Último recode: 2026-08-31 13:45 (America/Bahia)
# Motivo: Aplicar isolamento multi-tenant no legado sem alterar o contrato HTTP do ESP durante a migracao para o GestFlow.

from __future__ import annotations

import json
import sqlite3
import sys

from modules.db_indflow import get_db

_INSTALLED = False


def _clean(value) -> str:
    return str(value or "").strip()


def _mid(value) -> str:
    raw = _clean(value).lower()
    if "::" in raw:
        raw = raw.split("::", 1)[1]
    return raw.strip()


def _request_cliente_id(machine_routes_module) -> str | None:
    """Resolve o tenant usando os mesmos mecanismos ja validados pelo modulo."""
    try:
        cid = machine_routes_module._get_cliente_id_for_request()
        if cid:
            return _clean(cid) or None
    except Exception:
        pass
    return None


def _ensure_stop_tenant(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS machine_stop_tenant (
            cliente_id TEXT NOT NULL,
            machine_id TEXT NOT NULL,
            stopped_since_ms INTEGER NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (cliente_id, machine_id)
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS ix_machine_stop_tenant_updated_at "
        "ON machine_stop_tenant(updated_at)"
    )


def _install_machine_routes_guards() -> bool:
    # Nao importa o modulo aqui: init_db() tambem roda durante imports iniciais.
    # Patch somente quando server.py ja carregou machine_routes por completo.
    mr = sys.modules.get("modules.machine_routes")
    if mr is None:
        return False

    if getattr(mr, "_TENANT_RUNTIME_SAFETY_INSTALLED", False):
        return True

    original_get_stop = mr._get_stopped_since_ms
    original_set_stop = mr._set_stopped_since_ms
    original_clear_stop = mr._clear_stopped_since
    original_cfg_load = mr._cfgv2_db_load
    original_cfg_upsert = mr._cfgv2_db_upsert
    original_legacy_upsert = mr.upsert_machine_config

    def safe_get_stop(machine_id: str):
        cid = _request_cliente_id(mr)
        if not cid:
            return original_get_stop(machine_id)
        mid = _mid(machine_id)
        if not mid:
            return None
        conn = get_db()
        try:
            _ensure_stop_tenant(conn)
            row = conn.execute(
                "SELECT stopped_since_ms FROM machine_stop_tenant "
                "WHERE cliente_id=? AND machine_id=? LIMIT 1",
                (cid, mid),
            ).fetchone()
            if not row:
                return None
            try:
                value = int(row[0] or 0)
            except Exception:
                return None
            return value if value > 0 else None
        finally:
            conn.close()

    def safe_set_stop(machine_id: str, stopped_since_ms: int, updated_at: str):
        cid = _request_cliente_id(mr)
        if not cid:
            return original_set_stop(machine_id, stopped_since_ms, updated_at)
        mid = _mid(machine_id)
        if not mid:
            return None
        conn = get_db()
        try:
            _ensure_stop_tenant(conn)
            conn.execute(
                """
                INSERT INTO machine_stop_tenant
                    (cliente_id, machine_id, stopped_since_ms, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(cliente_id, machine_id) DO UPDATE SET
                    stopped_since_ms=excluded.stopped_since_ms,
                    updated_at=excluded.updated_at
                """,
                (cid, mid, int(stopped_since_ms), _clean(updated_at)),
            )
            conn.commit()
        finally:
            conn.close()

    def safe_clear_stop(machine_id: str, updated_at: str = ""):
        cid = _request_cliente_id(mr)
        if not cid:
            return original_clear_stop(machine_id, updated_at)
        mid = _mid(machine_id)
        if not mid:
            return None
        conn = get_db()
        try:
            _ensure_stop_tenant(conn)
            conn.execute(
                "DELETE FROM machine_stop_tenant WHERE cliente_id=? AND machine_id=?",
                (cid, mid),
            )
            conn.commit()
        finally:
            conn.close()

    def safe_cfg_load(machine_id: str, cliente_id: str | None = None):
        cid = _clean(cliente_id)
        mid = _mid(machine_id)
        if not cid:
            return original_cfg_load(machine_id, cliente_id)
        if not mid:
            return None

        conn = sqlite3.connect(mr._cfgv2_db_path(), check_same_thread=False)
        try:
            row = None
            try:
                row = conn.execute(
                    "SELECT config_json FROM machine_config_tenant "
                    "WHERE cliente_id=? AND machine_id=? LIMIT 1",
                    (cid, mid),
                ).fetchone()
            except Exception:
                row = None

            if not row:
                try:
                    row = conn.execute(
                        "SELECT config_json FROM machine_config "
                        "WHERE machine_id=? AND cliente_id=? LIMIT 1",
                        (mid, cid),
                    ).fetchone()
                except Exception:
                    row = None

            if not row or not row[0]:
                return None
            try:
                parsed = json.loads(row[0])
            except Exception:
                return None
            return parsed if isinstance(parsed, dict) else None
        finally:
            conn.close()

    def safe_cfg_global_upsert(machine_id: str, cfg_v2: dict):
        # A rota /machine/config e autenticada. Em contexto tenant nao escreve
        # mais na chave global machine_id; a gravacao oficial ocorre logo depois
        # em _machine_config_tenant_upsert(cliente_id, machine_id, ...).
        if _request_cliente_id(mr):
            return None
        return original_cfg_upsert(machine_id, cfg_v2)

    def safe_legacy_config_upsert(machine_id: str, machine: dict):
        if _request_cliente_id(mr):
            return True
        return original_legacy_upsert(machine_id, machine)

    mr._get_stopped_since_ms = safe_get_stop
    mr._set_stopped_since_ms = safe_set_stop
    mr._clear_stopped_since = safe_clear_stop
    # Corrige tambem a chamada antiga existente em /machine/status.
    mr._clear_stopped_since_ms = safe_clear_stop
    mr._cfgv2_db_load = safe_cfg_load
    mr._cfgv2_db_upsert = safe_cfg_global_upsert
    mr.upsert_machine_config = safe_legacy_config_upsert
    mr._TENANT_RUNTIME_SAFETY_INSTALLED = True
    return True


def _install_machine_state_guards() -> bool:
    ms = sys.modules.get("modules.machine_state")
    if ms is None or not hasattr(ms, "_load_machine_config"):
        return False

    if getattr(ms, "_TENANT_RUNTIME_SAFETY_INSTALLED", False):
        return True

    original_load = ms._load_machine_config

    def safe_load_machine_config(machine_id: str, cliente_id: str | None = None):
        cid = _clean(cliente_id)
        mid = _mid(machine_id)
        if not cid:
            return original_load(machine_id, cliente_id)
        if not mid:
            return None

        try:
            ms._ensure_machine_config_table()
        except Exception:
            pass
        try:
            ms.ensure_machine_config_tenant_table()
        except Exception:
            pass

        conn = get_db()
        try:
            row = None
            try:
                row = conn.execute(
                    """
                    SELECT meta_turno, turno_inicio, turno_fim, rampa_percentual,
                           horas_turno_json, meta_por_hora_json, unidade_1,
                           unidade_2, conv_m_por_pcs
                    FROM machine_config_tenant
                    WHERE cliente_id=? AND machine_id=?
                    LIMIT 1
                    """,
                    (cid, mid),
                ).fetchone()
            except Exception:
                row = None

            if not row:
                try:
                    row = conn.execute(
                        """
                        SELECT meta_turno, turno_inicio, turno_fim, rampa_percentual,
                               horas_turno_json, meta_por_hora_json, unidade_1,
                               unidade_2, conv_m_por_pcs
                        FROM machine_config
                        WHERE machine_id=? AND cliente_id=?
                        LIMIT 1
                        """,
                        (mid, cid),
                    ).fetchone()
                except Exception:
                    row = None
        finally:
            conn.close()

        if not row:
            return None

        try:
            horas_turno = json.loads(row[4] or "[]")
            if not isinstance(horas_turno, list):
                horas_turno = []
        except Exception:
            horas_turno = []
        try:
            meta_por_hora = json.loads(row[5] or "[]")
            if not isinstance(meta_por_hora, list):
                meta_por_hora = []
        except Exception:
            meta_por_hora = []
        try:
            conv = float(row[8]) if row[8] is not None else 1.0
            if conv <= 0:
                conv = 1.0
        except Exception:
            conv = 1.0

        return {
            "meta_turno": int(row[0] or 0),
            "turno_inicio": row[1],
            "turno_fim": row[2],
            "rampa_percentual": int(row[3] or 0),
            "horas_turno": horas_turno,
            "meta_por_hora": meta_por_hora,
            "unidade_1": row[6] if row[6] not in ("", None) else None,
            "unidade_2": row[7] if row[7] not in ("", None) else None,
            "conv_m_por_pcs": conv,
        }

    ms._load_machine_config = safe_load_machine_config
    ms._TENANT_RUNTIME_SAFETY_INSTALLED = True
    return True


def _install_producao_guards() -> bool:
    pr = sys.modules.get("modules.producao.routes")
    if pr is None or not hasattr(pr, "_get_conv_m_por_pcs"):
        return False

    if getattr(pr, "_TENANT_RUNTIME_SAFETY_INSTALLED", False):
        return True

    original_conv = pr._get_conv_m_por_pcs

    def safe_get_conv(machine_id: str, cliente_id: str | None = None) -> float:
        cid = _clean(cliente_id)
        mid = _mid(machine_id)
        if not cid:
            return original_conv(machine_id, cliente_id)
        if not mid:
            return 0.0

        conn = get_db()
        try:
            # Fonte oficial multi-tenant no banco central do IndFlow.
            try:
                row = conn.execute(
                    "SELECT conv_m_por_pcs FROM machine_config_tenant "
                    "WHERE cliente_id=? AND machine_id=? LIMIT 1",
                    (cid, mid),
                ).fetchone()
                if row and row[0] is not None:
                    value = float(row[0])
                    if value > 0:
                        return value
            except Exception:
                pass

            # Compatibilidade apenas se o registro legado tiver o MESMO dono.
            try:
                cols = {
                    str(r[1])
                    for r in conn.execute("PRAGMA table_info(machine_config)").fetchall()
                }
                if "cliente_id" in cols and "conv_m_por_pcs" in cols:
                    row = conn.execute(
                        "SELECT conv_m_por_pcs FROM machine_config "
                        "WHERE machine_id=? AND cliente_id=? LIMIT 1",
                        (mid, cid),
                    ).fetchone()
                    if row and row[0] is not None:
                        value = float(row[0])
                        if value > 0:
                            return value
            except Exception:
                pass
            return 0.0
        finally:
            conn.close()

    pr._get_conv_m_por_pcs = safe_get_conv
    pr._TENANT_RUNTIME_SAFETY_INSTALLED = True
    return True


def install_runtime_guards() -> dict:
    """Instala guards idempotentes nos modulos legados ja carregados."""
    global _INSTALLED
    machine_state_ok = _install_machine_state_guards()
    machine_ok = _install_machine_routes_guards()
    producao_ok = _install_producao_guards()
    _INSTALLED = bool(machine_state_ok and machine_ok and producao_ok)
    return {
        "installed": _INSTALLED,
        "machine_state": bool(machine_state_ok),
        "machine_routes": bool(machine_ok),
        "producao_routes": bool(producao_ok),
    }
