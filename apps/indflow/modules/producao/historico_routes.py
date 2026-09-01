# Caminho: C:\Users\vlula\OneDrive\Área de Trabalho\Projetos Backup\GESTFLOW\apps\indflow\modules\producao\historico_routes.py
# Último recode: 2026-09-01 10:49 (America/Bahia)
# Motivo: Restaurar compatibilidade das funções legadas usadas por Paradas/Indicadores sem desfazer o novo Histórico Operacional consolidado.

from __future__ import annotations

import json
import os
import sqlite3
import traceback
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from flask import Blueprint, jsonify, render_template, request, session

try:
    from modules.db_indflow import init_db, get_db
except Exception:
    init_db = None
    get_db = None

try:
    from modules.machine_state import get_machine
except Exception:
    get_machine = None


TZ_BAHIA = ZoneInfo("America/Bahia")

historico_bp = Blueprint(
    "historico_bp",
    __name__,
    template_folder="templates",
)


def _sqlite_connect(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def _get_conn() -> sqlite3.Connection:
    if callable(get_db):
        return get_db()

    db_path = (
        os.environ.get("INDFLOW_DB_PATH")
        or os.environ.get("DB_PATH")
        or "/data/indflow.db"
    )
    return _sqlite_connect(db_path)


def _cliente_id_sessao() -> str:
    return str(session.get("cliente_id") or "").strip()


def _safe_int(value, default: int = 0) -> int:
    try:
        if value is None:
            return default
        return int(float(value))
    except Exception:
        return default


def _table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    try:
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
            (table_name,),
        ).fetchone()
        return bool(row)
    except Exception:
        return False


def _get_columns(conn: sqlite3.Connection, table_name: str) -> set[str]:
    if not _table_exists(conn, table_name):
        return set()

    try:
        rows = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
        return {str(row[1]) for row in rows}
    except Exception:
        return set()


def _resolve_data_col(conn: sqlite3.Connection, table_name: str) -> str | None:
    cols = _get_columns(conn, table_name)
    for name in ("data_ref", "dia_ref", "data", "date"):
        if name in cols:
            return name
    return None


def _parse_date_any(value: str | None) -> date | None:
    value = str(value or "").strip()
    if not value:
        return None

    for fmt in ("%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(value, fmt).date()
        except Exception:
            continue
    return None


def _canonical_machine_id(raw: str | None, cliente_id: str | None = None) -> str:
    value = str(raw or "").strip()
    cid = str(cliente_id or "").strip()

    if not value:
        return ""

    if cid and value.startswith(f"{cid}::"):
        value = value.split("::", 1)[1].strip()

    if "::" in value:
        left, right = value.split("::", 1)
        if cid and left == cid:
            value = right.strip()
        else:
            value = left.strip()

    return value


def _machine_sort_key(value: str) -> tuple:
    text = str(value or "").strip()
    parts = re_split_numbers(text)
    return tuple(parts)


def re_split_numbers(value: str) -> list:
    import re

    parts = re.split(r"(\d+)", value.casefold())
    out = []
    for part in parts:
        if part.isdigit():
            out.append((0, int(part)))
        else:
            out.append((1, part))
    return out


def _matching_machine_ids(
    conn: sqlite3.Connection,
    table_name: str,
    cliente_id: str,
    machine_id: str,
    id_col: str = "machine_id",
) -> list[str]:
    cols = _get_columns(conn, table_name)
    if id_col not in cols:
        return []

    cid = str(cliente_id or "").strip()
    mid = _canonical_machine_id(machine_id, cid)
    if not mid:
        return []

    params: list = []
    where = []

    if cid:
        if "cliente_id" in cols:
            where.append("cliente_id=?")
            params.append(cid)
        else:
            # Em tabela sem tenant explícito, só aceita chave claramente scoped.
            where.append(f"{id_col} LIKE ?")
            params.append(f"{cid}::%")

    where.append(
        f"({id_col}=? OR {id_col}=? OR {id_col} LIKE ? OR {id_col} LIKE ?)"
    )
    params.extend(
        [
            mid,
            f"{cid}::{mid}" if cid else mid,
            f"{mid}::%",
            f"%::{mid}",
        ]
    )

    sql = (
        f"SELECT DISTINCT {id_col} AS mid FROM {table_name} "
        f"WHERE {' AND '.join(where)}"
    )

    found: list[str] = []
    try:
        for row in conn.execute(sql, tuple(params)).fetchall():
            value = str(row["mid"] if isinstance(row, sqlite3.Row) else row[0] or "").strip()
            if value and value not in found:
                found.append(value)
    except Exception:
        return []

    preferred = []
    scoped = f"{cid}::{mid}" if cid else ""
    for candidate in (scoped, mid):
        if candidate and candidate in found and candidate not in preferred:
            preferred.append(candidate)

    for value in found:
        if value not in preferred:
            preferred.append(value)

    return preferred


def _list_tenant_machines(conn: sqlite3.Connection, cliente_id: str) -> list[str]:
    cid = str(cliente_id or "").strip()
    machines: set[str] = set()

    sources = (
        ("machine_config_tenant", "machine_id"),
        ("producao_diaria", "machine_id"),
        ("producao_evento", "machine_id"),
        ("machine_state_event", "effective_machine_id"),
        ("machine_state_event", "machine_id"),
        ("ordens_producao", "machine_id"),
    )

    for table_name, id_col in sources:
        cols = _get_columns(conn, table_name)
        if id_col not in cols:
            continue

        try:
            if cid and "cliente_id" in cols:
                rows = conn.execute(
                    f"SELECT DISTINCT {id_col} AS mid FROM {table_name} WHERE cliente_id=?",
                    (cid,),
                ).fetchall()
            elif cid and table_name == "machine_config_tenant":
                continue
            elif cid:
                # Sem cliente_id, somente chaves explicitamente scoped.
                rows = conn.execute(
                    f"SELECT DISTINCT {id_col} AS mid FROM {table_name} WHERE {id_col} LIKE ?",
                    (f"{cid}::%",),
                ).fetchall()
            else:
                rows = conn.execute(
                    f"SELECT DISTINCT {id_col} AS mid FROM {table_name}"
                ).fetchall()

            for row in rows:
                raw = row["mid"] if isinstance(row, sqlite3.Row) else row[0]
                mid = _canonical_machine_id(raw, cid)
                if mid:
                    machines.add(mid)
        except Exception:
            continue

    return sorted(machines, key=_machine_sort_key)


def _machine_allowed(
    conn: sqlite3.Connection,
    cliente_id: str,
    machine_id: str,
) -> bool:
    mid = _canonical_machine_id(machine_id, cliente_id)
    if not mid:
        return False

    machines = _list_tenant_machines(conn, cliente_id)
    return mid in machines


def _day_bounds_ms(day: date) -> tuple[int, int]:
    start = datetime(day.year, day.month, day.day, tzinfo=TZ_BAHIA)
    end = start + timedelta(days=1)
    return int(start.timestamp() * 1000), int(end.timestamp() * 1000)


def _production_from_events(
    conn: sqlite3.Connection,
    cliente_id: str,
    machine_id: str,
    start_ms: int,
    end_ms: int,
) -> tuple[bool, int]:
    table = "producao_evento"
    cols = _get_columns(conn, table)
    if not {"machine_id", "ts_ms", "delta"}.issubset(cols):
        return False, 0

    if cliente_id and "cliente_id" not in cols:
        return False, 0

    candidates = _matching_machine_ids(
        conn,
        table,
        cliente_id,
        machine_id,
        "machine_id",
    )

    for candidate in candidates:
        try:
            if cliente_id:
                row = conn.execute(
                    "SELECT COUNT(1) AS c, COALESCE(SUM(delta),0) AS total "
                    "FROM producao_evento "
                    "WHERE cliente_id=? AND machine_id=? AND ts_ms>=? AND ts_ms<?",
                    (cliente_id, candidate, int(start_ms), int(end_ms)),
                ).fetchone()
            else:
                row = conn.execute(
                    "SELECT COUNT(1) AS c, COALESCE(SUM(delta),0) AS total "
                    "FROM producao_evento "
                    "WHERE machine_id=? AND ts_ms>=? AND ts_ms<?",
                    (candidate, int(start_ms), int(end_ms)),
                ).fetchone()

            count = _safe_int(row["c"] if row else 0, 0)
            if count > 0:
                return True, max(0, _safe_int(row["total"], 0))
        except Exception:
            continue

    return False, 0


def _daily_production_fallback(
    conn: sqlite3.Connection,
    cliente_id: str,
    machine_id: str,
    data_ref: str,
) -> dict:
    table = "producao_diaria"
    cols = _get_columns(conn, table)
    data_col = _resolve_data_col(conn, table)

    if not data_col or "machine_id" not in cols or "produzido" not in cols:
        return {"produzido": 0, "meta": 0, "percentual": 0}

    if cliente_id and "cliente_id" not in cols:
        return {"produzido": 0, "meta": 0, "percentual": 0}

    candidates = _matching_machine_ids(
        conn,
        table,
        cliente_id,
        machine_id,
        "machine_id",
    )
    if not candidates:
        return {"produzido": 0, "meta": 0, "percentual": 0}

    select_cols = ["machine_id", "produzido"]
    if "meta" in cols:
        select_cols.append("meta")
    if "percentual" in cols:
        select_cols.append("percentual")

    rows_all = []
    for candidate in candidates:
        try:
            if cliente_id:
                rows = conn.execute(
                    f"SELECT {', '.join(select_cols)} FROM {table} "
                    f"WHERE cliente_id=? AND machine_id=? AND {data_col}=?",
                    (cliente_id, candidate, data_ref),
                ).fetchall()
            else:
                rows = conn.execute(
                    f"SELECT {', '.join(select_cols)} FROM {table} "
                    f"WHERE machine_id=? AND {data_col}=?",
                    (candidate, data_ref),
                ).fetchall()
            rows_all.extend(rows)
        except Exception:
            continue

    if not rows_all:
        return {"produzido": 0, "meta": 0, "percentual": 0}

    # Evita somar registros duplicados/legados do mesmo dia.
    chosen = max(
        rows_all,
        key=lambda row: _safe_int(row["produzido"], 0),
    )

    produzido = max(0, _safe_int(chosen["produzido"], 0))
    meta = max(0, _safe_int(chosen["meta"], 0)) if "meta" in chosen.keys() else 0
    percentual = (
        _safe_int(chosen["percentual"], 0)
        if "percentual" in chosen.keys()
        else (int(round((produzido / meta) * 100)) if meta > 0 else 0)
    )

    return {
        "produzido": produzido,
        "meta": meta,
        "percentual": percentual,
    }


def _production_for_day(
    conn: sqlite3.Connection,
    cliente_id: str,
    machine_id: str,
    day: date,
) -> dict:
    start_ms, end_ms = _day_bounds_ms(day)
    found, total = _production_from_events(
        conn,
        cliente_id,
        machine_id,
        start_ms,
        end_ms,
    )

    fallback = _daily_production_fallback(
        conn,
        cliente_id,
        machine_id,
        day.isoformat(),
    )

    if found:
        meta = _safe_int(fallback.get("meta"), 0)
        percentual = int(round((total / meta) * 100)) if meta > 0 else 0
        return {
            "produzido": max(0, total),
            "meta": meta,
            "percentual": percentual,
        }

    return fallback


def _refugo_for_day(
    conn: sqlite3.Connection,
    cliente_id: str,
    machine_id: str,
    day: date,
) -> int:
    table = "refugo_horaria"
    cols = _get_columns(conn, table)
    data_col = _resolve_data_col(conn, table)

    if not data_col or "machine_id" not in cols:
        return 0
    if cliente_id and "cliente_id" not in cols:
        return 0

    ref_col = next(
        (name for name in ("refugo", "qtd", "quantidade", "valor") if name in cols),
        None,
    )
    if not ref_col:
        return 0

    candidates = _matching_machine_ids(
        conn,
        table,
        cliente_id,
        machine_id,
        "machine_id",
    )

    for candidate in candidates:
        try:
            if cliente_id:
                row = conn.execute(
                    f"SELECT COUNT(1) AS c, COALESCE(SUM({ref_col}),0) AS total "
                    f"FROM {table} WHERE cliente_id=? AND machine_id=? AND {data_col}=?",
                    (cliente_id, candidate, day.isoformat()),
                ).fetchone()
            else:
                row = conn.execute(
                    f"SELECT COUNT(1) AS c, COALESCE(SUM({ref_col}),0) AS total "
                    f"FROM {table} WHERE machine_id=? AND {data_col}=?",
                    (candidate, day.isoformat()),
                ).fetchone()

            if row and _safe_int(row["c"], 0) > 0:
                return max(0, _safe_int(row["total"], 0))
        except Exception:
            continue

    return 0


def _ops_for_day(
    conn: sqlite3.Connection,
    cliente_id: str,
    machine_id: str,
    day: date,
) -> list[dict]:
    table = "ordens_producao"
    cols = _get_columns(conn, table)

    if "machine_id" not in cols:
        return []

    if cliente_id and "cliente_id" not in cols:
        # Só permite tabela legada quando a própria machine_id estiver scoped.
        candidates = [
            value
            for value in _matching_machine_ids(
                conn,
                table,
                cliente_id,
                machine_id,
                "machine_id",
            )
            if value.startswith(f"{cliente_id}::")
        ]
    else:
        candidates = _matching_machine_ids(
            conn,
            table,
            cliente_id,
            machine_id,
            "machine_id",
        )

    if not candidates:
        return []

    date_fields = [
        name
        for name in (
            "ativada_at",
            "activated_at",
            "started_at",
            "inicio_iso",
            "created_at",
        )
        if name in cols
    ]
    if not date_fields:
        return []

    date_exprs = [f"datetime(replace({name}, 'T', ' '))" for name in date_fields]
    ref_expr = (
        date_exprs[0]
        if len(date_exprs) == 1
        else f"COALESCE({', '.join(date_exprs)})"
    )

    desired = [
        "id",
        "op_id",
        "op",
        "os",
        "lote",
        "operador",
        "inicio_iso",
        "fim_iso",
        "status",
        "ativada_at",
        "activated_at",
        "started_at",
        "created_at",
        "observacoes",
    ]
    select_cols = [name for name in desired if name in cols]
    if not select_cols:
        return []

    day_start = datetime(day.year, day.month, day.day)
    day_end = day_start + timedelta(days=1)
    start_sql = day_start.strftime("%Y-%m-%d %H:%M:%S")
    end_sql = day_end.strftime("%Y-%m-%d %H:%M:%S")

    out: list[dict] = []
    seen = set()

    for candidate in candidates:
        params: list = []
        where = []

        if cliente_id and "cliente_id" in cols:
            where.append("cliente_id=?")
            params.append(cliente_id)

        where.append("machine_id=?")
        params.append(candidate)
        where.append(f"{ref_expr}>=datetime(?)")
        params.append(start_sql)
        where.append(f"{ref_expr}<datetime(?)")
        params.append(end_sql)

        sql = (
            f"SELECT {', '.join(select_cols)}, {ref_expr} AS data_pertencimento "
            f"FROM {table} WHERE {' AND '.join(where)} ORDER BY {ref_expr} ASC"
        )

        try:
            rows = conn.execute(sql, tuple(params)).fetchall()
        except Exception:
            continue

        for row in rows:
            op_id = None
            for key in ("id", "op_id"):
                if key in row.keys() and row[key] is not None:
                    op_id = row[key]
                    break

            op_value = row["op"] if "op" in row.keys() else None
            os_value = row["os"] if "os" in row.keys() else None
            lote = row["lote"] if "lote" in row.keys() else None
            operador = row["operador"] if "operador" in row.keys() else None
            status = row["status"] if "status" in row.keys() else None
            data_pertencimento = row["data_pertencimento"]

            signature = (
                str(op_id or ""),
                str(op_value or ""),
                str(os_value or ""),
                str(lote or ""),
                str(operador or ""),
                str(data_pertencimento or ""),
            )
            if signature in seen:
                continue
            seen.add(signature)

            item = {
                "op_id": op_id,
                "op": op_value,
                "os": os_value,
                "lote": lote,
                "operador": operador,
                "status": status,
                "machine_id": _canonical_machine_id(candidate, cliente_id),
                "data_pertencimento": data_pertencimento,
            }

            for name in (
                "inicio_iso",
                "fim_iso",
                "ativada_at",
                "activated_at",
                "started_at",
                "created_at",
                "observacoes",
            ):
                if name in row.keys():
                    item[name] = row[name]

            out.append(item)

    return out


def _state_columns(conn: sqlite3.Connection) -> dict:
    table = "machine_state_event"
    cols = _get_columns(conn, table)
    if not cols:
        return {}

    id_col = (
        "effective_machine_id"
        if "effective_machine_id" in cols
        else ("machine_id" if "machine_id" in cols else None)
    )
    data_col = (
        "data_ref"
        if "data_ref" in cols
        else _resolve_data_col(conn, table)
    )
    ts_col = next(
        (name for name in ("ts_ms", "timestamp_ms", "ts") if name in cols),
        None,
    )
    state_col = next(
        (name for name in ("state", "status") if name in cols),
        None,
    )

    if not id_col or not data_col or not ts_col or not state_col:
        return {}

    return {
        "id_col": id_col,
        "data_col": data_col,
        "ts_col": ts_col,
        "state_col": state_col,
        "cols": cols,
    }


def _state_segments_for_day(
    conn: sqlite3.Connection,
    cliente_id: str,
    machine_id: str,
    day: date,
) -> list[tuple[datetime, datetime, str]]:
    info = _state_columns(conn)
    if not info:
        return []

    table = "machine_state_event"
    cols = info["cols"]
    id_col = info["id_col"]
    data_col = info["data_col"]
    ts_col = info["ts_col"]
    state_col = info["state_col"]

    if cliente_id and "cliente_id" not in cols:
        candidates = [
            value
            for value in _matching_machine_ids(
                conn,
                table,
                cliente_id,
                machine_id,
                id_col,
            )
            if value.startswith(f"{cliente_id}::")
        ]
    else:
        candidates = _matching_machine_ids(
            conn,
            table,
            cliente_id,
            machine_id,
            id_col,
        )

    if not candidates:
        return []

    day_start = datetime(day.year, day.month, day.day)
    day_end = day_start + timedelta(days=1)
    now_local = datetime.now(TZ_BAHIA).replace(tzinfo=None)
    hard_end = min(day_end, now_local) if day == now_local.date() else day_end

    if hard_end <= day_start:
        return []

    day_start_ms = int(day_start.replace(tzinfo=TZ_BAHIA).timestamp() * 1000)
    allowed = {"RUN", "STOP", "IDLE", "NP"}

    initial: tuple[str, int] | None = None

    for candidate in candidates:
        try:
            params = []
            where = []

            if cliente_id and "cliente_id" in cols:
                where.append("cliente_id=?")
                params.append(cliente_id)

            where.append(f"{id_col}=?")
            params.append(candidate)
            where.append(f"{ts_col}<?")
            params.append(day_start_ms)

            row = conn.execute(
                f"SELECT {state_col} AS st, {ts_col} AS ts "
                f"FROM {table} WHERE {' AND '.join(where)} "
                f"ORDER BY {ts_col} DESC LIMIT 1",
                tuple(params),
            ).fetchone()

            if not row:
                continue

            state = str(row["st"] or "").upper()
            ts_ms = _safe_int(row["ts"], -1)
            if state not in allowed or ts_ms < 0:
                continue

            if initial is None or ts_ms > initial[1]:
                initial = (state, ts_ms)
        except Exception:
            continue

    # Não herda estado muito antigo.
    state0 = "IDLE"
    if initial is not None:
        state, ts_ms = initial
        if day_start_ms - ts_ms <= 6 * 60 * 60 * 1000:
            state0 = state

    events: list[tuple[datetime, str]] = []
    seen = set()

    for candidate in candidates:
        try:
            params = []
            where = []

            if cliente_id and "cliente_id" in cols:
                where.append("cliente_id=?")
                params.append(cliente_id)

            where.append(f"{id_col}=?")
            params.append(candidate)
            where.append(f"{data_col}=?")
            params.append(day.isoformat())

            rows = conn.execute(
                f"SELECT {ts_col} AS ts, {state_col} AS st "
                f"FROM {table} WHERE {' AND '.join(where)} "
                f"ORDER BY {ts_col} ASC",
                tuple(params),
            ).fetchall()

            for row in rows:
                ts_ms = _safe_int(row["ts"], -1)
                state = str(row["st"] or "").upper()
                if ts_ms < 0 or state not in allowed:
                    continue

                signature = (ts_ms, state)
                if signature in seen:
                    continue
                seen.add(signature)

                try:
                    dt = datetime.fromtimestamp(
                        ts_ms / 1000.0,
                        tz=TZ_BAHIA,
                    ).replace(tzinfo=None)
                except Exception:
                    continue

                if day_start <= dt <= hard_end:
                    events.append((dt, state))
        except Exception:
            continue

    events.sort(key=lambda item: item[0])

    segments: list[tuple[datetime, datetime, str]] = []
    current_state = state0
    cursor = day_start

    for event_dt, state in events:
        if event_dt <= cursor:
            current_state = state
            cursor = event_dt
            continue

        segments.append((cursor, event_dt, current_state))
        cursor = event_dt
        current_state = state

    if cursor < hard_end:
        segments.append((cursor, hard_end, current_state))

    merged: list[tuple[datetime, datetime, str]] = []
    for start, end, state in segments:
        if end <= start:
            continue

        if merged and merged[-1][2] == state and merged[-1][1] == start:
            prev_start, _, prev_state = merged[-1]
            merged[-1] = (prev_start, end, prev_state)
        else:
            merged.append((start, end, state))

    return merged


def _state_metrics(
    segments: list[tuple[datetime, datetime, str]],
) -> dict:
    run_sec = 0
    stop_sec = 0
    stops = 0
    previous_state = None

    for start, end, state in segments:
        duration = max(0, int((end - start).total_seconds()))

        if state == "RUN":
            run_sec += duration
        elif state == "STOP":
            stop_sec += duration
            if duration > 0 and previous_state != "STOP":
                stops += 1

        previous_state = state

    return {
        "tempo_produzindo_sec": run_sec,
        "tempo_parado_sec": stop_sec,
        "paradas": stops,
    }


def _load_machine_config(
    conn: sqlite3.Connection,
    cliente_id: str,
    machine_id: str,
) -> dict:
    cid = str(cliente_id or "").strip()
    mid = _canonical_machine_id(machine_id, cid)

    table = "machine_config_tenant"
    cols = _get_columns(conn, table)

    if {"cliente_id", "machine_id", "config_json"}.issubset(cols):
        candidates = _matching_machine_ids(
            conn,
            table,
            cid,
            mid,
            "machine_id",
        )
        for candidate in candidates:
            try:
                row = conn.execute(
                    "SELECT config_json FROM machine_config_tenant "
                    "WHERE cliente_id=? AND machine_id=? LIMIT 1",
                    (cid, candidate),
                ).fetchone()
                if row and row["config_json"]:
                    return json.loads(row["config_json"])
            except Exception:
                continue

    # Fallback legado somente se não houver tenant explícito para a máquina.
    legacy = "machine_config"
    legacy_cols = _get_columns(conn, legacy)
    if "machine_id" in legacy_cols and "config_json" in legacy_cols:
        for candidate in (mid, f"{cid}::{mid}" if cid else mid):
            try:
                row = conn.execute(
                    "SELECT config_json FROM machine_config "
                    "WHERE machine_id=? LIMIT 1",
                    (candidate,),
                ).fetchone()
                if row and row["config_json"]:
                    return json.loads(row["config_json"])
            except Exception:
                continue

    return {}


def _parse_hhmm(value: str | None) -> int | None:
    value = str(value or "").strip()
    if ":" not in value:
        return None

    try:
        hour, minute = value.split(":", 1)
        hour_i = int(hour)
        minute_i = int(minute)
        if not (0 <= hour_i <= 23 and 0 <= minute_i <= 59):
            return None
        return hour_i * 60 + minute_i
    except Exception:
        return None


def _interval_intersects(
    a_start: int,
    a_end: int,
    b_start: int,
    b_end: int,
) -> bool:
    return a_start < b_end and b_start < a_end


def _meta_24_from_config(config: dict, day: date) -> list[int] | None:
    if not isinstance(config, dict):
        return None

    cv2 = config.get("config_v2")
    if not isinstance(cv2, dict):
        cv2 = config if isinstance(config.get("shifts"), list) else None
    if not isinstance(cv2, dict):
        return None

    active_days = cv2.get("active_days")
    if isinstance(active_days, list) and active_days:
        normalized = set()
        for value in active_days:
            try:
                day_value = int(value)
                if day_value == 0:
                    day_value = 7
                normalized.add(day_value)
            except Exception:
                continue

        if normalized and day.isoweekday() not in normalized:
            return [0] * 24

    shifts = cv2.get("shifts")
    if not isinstance(shifts, list) or not shifts:
        return None

    meta24 = [0] * 24

    for shift in shifts:
        if not isinstance(shift, dict):
            continue

        start_min = _parse_hhmm(shift.get("start"))
        end_min = _parse_hhmm(shift.get("end"))
        if start_min is None or end_min is None:
            continue

        if end_min <= start_min:
            end_min += 1440

        breaks = []
        for br in shift.get("breaks") or []:
            if not isinstance(br, dict):
                continue
            br_start = _parse_hhmm(br.get("start"))
            br_end = _parse_hhmm(br.get("end"))
            if br_start is None or br_end is None:
                continue
            if br_end <= br_start:
                br_end += 1440
            if br_start < start_min and end_min > 1440:
                br_start += 1440
                br_end += 1440
            breaks.append((br_start, br_end))

        meta_pcs = max(0, _safe_int(shift.get("meta_pcs"), 0))
        calc = shift.get("calc") if isinstance(shift.get("calc"), dict) else {}
        planned_min = max(0, _safe_int(calc.get("planned_min"), 0))

        if planned_min <= 0:
            planned_min = max(
                0,
                (end_min - start_min)
                - sum(max(0, end - start) for start, end in breaks),
            )

        planned_hours = planned_min / 60.0 if planned_min > 0 else 0.0
        meta_h = (
            int(round(meta_pcs / planned_hours))
            if meta_pcs > 0 and planned_hours > 0
            else 0
        )

        for hour in range(24):
            h0s = hour * 60
            h0e = (hour + 1) * 60
            h1s = h0s + 1440
            h1e = h0e + 1440

            inside = (
                _interval_intersects(h0s, h0e, start_min, end_min)
                or _interval_intersects(h1s, h1e, start_min, end_min)
            )
            if not inside:
                continue

            in_break = any(
                _interval_intersects(h0s, h0e, bs, be)
                or _interval_intersects(h1s, h1e, bs, be)
                for bs, be in breaks
            )

            if not in_break:
                meta24[hour] = max(meta24[hour], meta_h)

    return meta24


# ============================================================
# COMPATIBILIDADE COM PARADAS / INDICADORES
# ============================================================
# O módulo modules.paradas.services ainda importa estes nomes históricos.
# Mantemos a API interna antiga apontando para as rotinas consolidadas acima,
# evitando duplicar a lógica do Histórico Operacional.


def _build_meta_24_from_config_v2(cfg: dict | None, data_ref: date) -> list[int] | None:
    """Compatibilidade: mantém o nome antigo usando a regra consolidada atual."""
    return _meta_24_from_config(cfg or {}, data_ref)


def _build_meta_24_from_machine_state(machine_state: dict | None) -> list[int] | None:
    """Monta meta[24] a partir do fallback legado do estado da máquina."""
    if not isinstance(machine_state, dict):
        return None

    meta_por_hora = machine_state.get("meta_por_hora")
    if not isinstance(meta_por_hora, list) or not meta_por_hora:
        return None

    turno_inicio = str(machine_state.get("turno_inicio") or "").strip()
    if not turno_inicio:
        return None

    try:
        hora_inicio = int(turno_inicio.split(":", 1)[0])
    except Exception:
        return None

    if not 0 <= hora_inicio <= 23:
        return None

    meta24 = [0] * 24
    for index, value in enumerate(meta_por_hora):
        hora = (hora_inicio + index) % 24
        meta24[hora] = max(0, _safe_int(value, 0))

    return meta24


def _load_machine_config_json(
    conn: sqlite3.Connection,
    machine_id: str,
    cliente_id: str | None = None,
) -> dict:
    """Compatibilidade com o nome antigo do carregador de configuração."""
    return _load_machine_config(
        conn,
        str(cliente_id or "").strip(),
        machine_id,
    )


def _resolve_effective_machine_id(
    conn: sqlite3.Connection,
    machine_id: str,
    data_ref: str,
    cliente_id: str | None = None,
) -> str:
    """Retorna a representação canônica da máquina dentro do tenant atual."""
    cid = str(cliente_id or "").strip()
    mid = _canonical_machine_id(machine_id, cid)
    if not mid:
        return ""

    # Verifica primeiro se existe uma representação gravada no dia solicitado.
    table = "producao_diaria"
    cols = _get_columns(conn, table)
    data_col = _resolve_data_col(conn, table)
    if data_col and "machine_id" in cols:
        candidates = _matching_machine_ids(conn, table, cid, mid, "machine_id")
        for candidate in candidates:
            try:
                params = []
                where = []
                if cid and "cliente_id" in cols:
                    where.append("cliente_id=?")
                    params.append(cid)
                where.append("machine_id=?")
                params.append(candidate)
                where.append(f"{data_col}=?")
                params.append(str(data_ref or "").strip())
                row = conn.execute(
                    f"SELECT machine_id FROM {table} WHERE {' AND '.join(where)} LIMIT 1",
                    tuple(params),
                ).fetchone()
                if row:
                    raw = row["machine_id"] if isinstance(row, sqlite3.Row) else row[0]
                    return _canonical_machine_id(raw, cid) or mid
            except Exception:
                continue

    return mid


def _fetch_state_segments_from_state_events(
    conn: sqlite3.Connection,
    effective_machine_id: str,
    data_ref: date,
    machine_id: str | None = None,
    cliente_id: str | None = None,
) -> list[tuple[datetime, datetime, str]]:
    """Compatibilidade com a leitura consolidada de machine_state_event."""
    cid = str(cliente_id or "").strip()
    mid = _canonical_machine_id(machine_id or effective_machine_id, cid)
    if not mid:
        return []
    return _state_segments_for_day(conn, cid, mid, data_ref)


def _build_segments_for_hour_from_day_segments(
    hour_start: datetime,
    hour_end: datetime,
    is_np: bool,
    day_segments: list[tuple[datetime, datetime, str]],
) -> list[dict]:
    """Compatibilidade com o recorte horário usado pelos indicadores de paradas."""
    return _clip_state_segments(
        day_segments or [],
        hour_start,
        hour_end,
        bool(is_np),
    )


def _fetch_horaria(
    conn: sqlite3.Connection,
    machine_id: str,
    data_ref: date,
    cliente_id: str | None = None,
) -> dict[int, dict]:
    """Lê o consolidado horário no contrato antigo, preservando isolamento por tenant."""
    out: dict[int, dict] = {
        hour: {
            "meta": 0,
            "produzido": 0,
            "refugo": 0,
            "baseline_esp": 0,
            "esp_last": 0,
        }
        for hour in range(24)
    }

    cid = str(cliente_id or "").strip()
    mid = _canonical_machine_id(machine_id, cid)
    table = "producao_horaria"
    cols = _get_columns(conn, table)
    data_col = _resolve_data_col(conn, table)
    hour_col = next(
        (name for name in ("hora_dia", "hora_idx", "hora", "hora_int") if name in cols),
        None,
    )
    prod_col = next(
        (name for name in ("produzido", "producao", "count", "qtd") if name in cols),
        None,
    )
    meta_col = next(
        (name for name in ("meta_hora", "meta", "meta_pcs") if name in cols),
        None,
    )
    base_col = "baseline_esp" if "baseline_esp" in cols else None
    esp_col = next(
        (name for name in ("esp_last", "esp_abs", "esp", "contador", "counter") if name in cols),
        None,
    )

    if data_col and hour_col and "machine_id" in cols:
        select_cols = [hour_col]
        for column in (prod_col, meta_col, base_col, esp_col):
            if column and column not in select_cols:
                select_cols.append(column)

        candidates = _matching_machine_ids(conn, table, cid, mid, "machine_id")
        for candidate in candidates:
            try:
                params = []
                where = []
                if cid and "cliente_id" in cols:
                    where.append("cliente_id=?")
                    params.append(cid)
                elif cid and "cliente_id" not in cols:
                    continue

                where.append("machine_id=?")
                params.append(candidate)
                where.append(f"{data_col}=?")
                params.append(data_ref.isoformat())

                rows = conn.execute(
                    f"SELECT {', '.join(select_cols)} FROM {table} "
                    f"WHERE {' AND '.join(where)}",
                    tuple(params),
                ).fetchall()
            except Exception:
                continue

            for row in rows:
                try:
                    hour = _safe_int(
                        row[hour_col] if isinstance(row, sqlite3.Row) else row[0],
                        -1,
                    )
                except Exception:
                    continue
                if not 0 <= hour <= 23:
                    continue

                def _value(column: str | None) -> int:
                    if not column:
                        return 0
                    try:
                        if isinstance(row, sqlite3.Row):
                            return _safe_int(row[column], 0)
                        return _safe_int(row[select_cols.index(column)], 0)
                    except Exception:
                        return 0

                out[hour]["produzido"] = max(out[hour]["produzido"], _value(prod_col))
                out[hour]["meta"] = max(out[hour]["meta"], _value(meta_col))
                out[hour]["baseline_esp"] = max(out[hour]["baseline_esp"], _value(base_col))
                out[hour]["esp_last"] = max(out[hour]["esp_last"], _value(esp_col))

    # Refugo usa a rotina consolidada, que já resolve aliases de machine_id e tenant.
    for hour in range(24):
        out[hour]["refugo"] = _hourly_refugo(
            conn,
            cid,
            mid,
            data_ref,
            hour,
        )

    return out


def _hourly_fallback(
    conn: sqlite3.Connection,
    cliente_id: str,
    machine_id: str,
    day: date,
    hour: int,
) -> int:
    table = "producao_horaria"
    cols = _get_columns(conn, table)
    data_col = _resolve_data_col(conn, table)
    hour_col = next(
        (name for name in ("hora_dia", "hora_idx", "hora", "hora_int") if name in cols),
        None,
    )
    prod_col = next(
        (name for name in ("produzido", "producao", "count", "qtd") if name in cols),
        None,
    )

    if not data_col or not hour_col or not prod_col or "machine_id" not in cols:
        return 0
    if cliente_id and "cliente_id" not in cols:
        return 0

    candidates = _matching_machine_ids(
        conn,
        table,
        cliente_id,
        machine_id,
        "machine_id",
    )

    for candidate in candidates:
        try:
            if cliente_id:
                row = conn.execute(
                    f"SELECT COUNT(1) AS c, COALESCE(MAX({prod_col}),0) AS total "
                    f"FROM {table} WHERE cliente_id=? AND machine_id=? "
                    f"AND {data_col}=? AND {hour_col}=?",
                    (cliente_id, candidate, day.isoformat(), int(hour)),
                ).fetchone()
            else:
                row = conn.execute(
                    f"SELECT COUNT(1) AS c, COALESCE(MAX({prod_col}),0) AS total "
                    f"FROM {table} WHERE machine_id=? "
                    f"AND {data_col}=? AND {hour_col}=?",
                    (candidate, day.isoformat(), int(hour)),
                ).fetchone()

            if row and _safe_int(row["c"], 0) > 0:
                return max(0, _safe_int(row["total"], 0))
        except Exception:
            continue

    return 0


def _hourly_refugo(
    conn: sqlite3.Connection,
    cliente_id: str,
    machine_id: str,
    day: date,
    hour: int,
) -> int:
    table = "refugo_horaria"
    cols = _get_columns(conn, table)
    data_col = _resolve_data_col(conn, table)
    hour_col = next(
        (name for name in ("hora_dia", "hora_idx", "hora", "hora_int") if name in cols),
        None,
    )
    ref_col = next(
        (name for name in ("refugo", "qtd", "quantidade", "valor") if name in cols),
        None,
    )

    if not data_col or not hour_col or not ref_col or "machine_id" not in cols:
        return 0
    if cliente_id and "cliente_id" not in cols:
        return 0

    candidates = _matching_machine_ids(
        conn,
        table,
        cliente_id,
        machine_id,
        "machine_id",
    )

    for candidate in candidates:
        try:
            if cliente_id:
                row = conn.execute(
                    f"SELECT COUNT(1) AS c, COALESCE(SUM({ref_col}),0) AS total "
                    f"FROM {table} WHERE cliente_id=? AND machine_id=? "
                    f"AND {data_col}=? AND {hour_col}=?",
                    (cliente_id, candidate, day.isoformat(), int(hour)),
                ).fetchone()
            else:
                row = conn.execute(
                    f"SELECT COUNT(1) AS c, COALESCE(SUM({ref_col}),0) AS total "
                    f"FROM {table} WHERE machine_id=? "
                    f"AND {data_col}=? AND {hour_col}=?",
                    (candidate, day.isoformat(), int(hour)),
                ).fetchone()

            if row and _safe_int(row["c"], 0) > 0:
                return max(0, _safe_int(row["total"], 0))
        except Exception:
            continue

    return 0


def _clip_state_segments(
    segments: list[tuple[datetime, datetime, str]],
    start: datetime,
    end: datetime,
    force_np: bool,
) -> list[dict]:
    if end <= start:
        return [
            {
                "start": start.strftime("%H:%M:%S"),
                "end": start.strftime("%H:%M:%S"),
                "state": "NP" if force_np else "IDLE",
            }
        ]

    if force_np:
        return [
            {
                "start": start.strftime("%H:%M:%S"),
                "end": end.strftime("%H:%M:%S"),
                "state": "NP",
            }
        ]

    out = []
    cursor = start
    last_state = None

    for seg_start, seg_end, state in segments:
        clip_start = max(start, seg_start)
        clip_end = min(end, seg_end)

        if clip_end <= clip_start:
            continue

        if clip_start > cursor:
            fill_state = last_state if last_state else "IDLE"
            out.append(
                {
                    "start": cursor.strftime("%H:%M:%S"),
                    "end": clip_start.strftime("%H:%M:%S"),
                    "state": fill_state,
                }
            )

        out.append(
            {
                "start": clip_start.strftime("%H:%M:%S"),
                "end": clip_end.strftime("%H:%M:%S"),
                "state": state,
            }
        )
        cursor = clip_end
        last_state = state

    if cursor < end:
        out.append(
            {
                "start": cursor.strftime("%H:%M:%S"),
                "end": end.strftime("%H:%M:%S"),
                "state": last_state or "IDLE",
            }
        )

    if not out:
        out.append(
            {
                "start": start.strftime("%H:%M:%S"),
                "end": end.strftime("%H:%M:%S"),
                "state": "IDLE",
            }
        )

    merged = []
    for item in out:
        if (
            merged
            and merged[-1]["state"] == item["state"]
            and merged[-1]["end"] == item["start"]
        ):
            merged[-1]["end"] = item["end"]
        else:
            merged.append(item)

    return merged


def _segment_dict_metrics(segments: list[dict]) -> dict:
    run_sec = 0
    stop_sec = 0
    stops = 0
    previous = None

    for item in segments:
        try:
            start_h, start_m, start_s = map(int, item["start"].split(":"))
            end_h, end_m, end_s = map(int, item["end"].split(":"))
            start_sec = start_h * 3600 + start_m * 60 + start_s
            end_sec = end_h * 3600 + end_m * 60 + end_s
            duration = max(0, end_sec - start_sec)
        except Exception:
            duration = 0

        state = item.get("state")
        if state == "RUN":
            run_sec += duration
        elif state == "STOP":
            stop_sec += duration
            if duration > 0 and previous != "STOP":
                stops += 1

        previous = state

    return {
        "tempo_produzindo_sec": run_sec,
        "tempo_parado_sec": stop_sec,
        "qtd_paradas": stops,
    }


def _history_machine_day(
    conn: sqlite3.Connection,
    cliente_id: str,
    machine_id: str,
    day: date,
) -> dict:
    production = _production_for_day(
        conn,
        cliente_id,
        machine_id,
        day,
    )
    refugo = _refugo_for_day(
        conn,
        cliente_id,
        machine_id,
        day,
    )
    ops = _ops_for_day(
        conn,
        cliente_id,
        machine_id,
        day,
    )
    state_segments = _state_segments_for_day(
        conn,
        cliente_id,
        machine_id,
        day,
    )
    metrics = _state_metrics(state_segments)

    produzido = max(0, _safe_int(production.get("produzido"), 0))
    meta = max(0, _safe_int(production.get("meta"), 0))
    percentual = (
        int(round((produzido / meta) * 100))
        if meta > 0
        else _safe_int(production.get("percentual"), 0)
    )

    return {
        "machine_id": _canonical_machine_id(machine_id, cliente_id),
        "data": day.isoformat(),
        "produzido": produzido,
        "pecas_boas": max(0, produzido - refugo),
        "refugo": max(0, refugo),
        "meta": meta,
        "percentual": percentual,
        "tempo_produzindo_sec": metrics["tempo_produzindo_sec"],
        "tempo_parado_sec": metrics["tempo_parado_sec"],
        "paradas": metrics["paradas"],
        "ops_count": len(ops),
        "ops": ops,
    }


def _has_activity(item: dict) -> bool:
    return any(
        _safe_int(item.get(key), 0) > 0
        for key in (
            "produzido",
            "refugo",
            "tempo_produzindo_sec",
            "tempo_parado_sec",
            "paradas",
            "ops_count",
        )
    )


def _resolve_period() -> tuple[date, date]:
    today = datetime.now(TZ_BAHIA).date()

    date_from = _parse_date_any(request.args.get("date_from"))
    date_to = _parse_date_any(request.args.get("date_to"))

    if date_from or date_to:
        if date_from is None:
            date_from = date_to
        if date_to is None:
            date_to = date_from

        if date_from > date_to:
            date_from, date_to = date_to, date_from

        # Limite defensivo: 60 dias.
        if (date_to - date_from).days > 59:
            date_from = date_to - timedelta(days=59)

        return date_from, date_to

    days = _safe_int(request.args.get("days"), 7)
    days = max(1, min(days, 60))
    return today - timedelta(days=days - 1), today


if callable(init_db):
    try:
        init_db()
    except Exception:
        pass


@historico_bp.route("/api/producao/historico", methods=["GET"])
def api_producao_historico():
    cliente_id = _cliente_id_sessao()
    if not cliente_id:
        return jsonify(
            {
                "ok": False,
                "error": "Cliente da sessao nao identificado",
            }
        ), 403

    requested_machine = str(
        request.args.get("machine_id")
        or request.args.get("machine")
        or "all"
    ).strip()
    requested_machine_lower = requested_machine.casefold()

    date_from, date_to = _resolve_period()

    conn = _get_conn()
    try:
        machines = _list_tenant_machines(conn, cliente_id)

        if requested_machine_lower in ("", "all", "todos", "*"):
            selected_machines = machines[:]
            selected_machine = "all"
        else:
            selected_machine = _canonical_machine_id(
                requested_machine,
                cliente_id,
            )
            if selected_machine not in machines:
                return jsonify(
                    {
                        "ok": False,
                        "error": "Maquina nao encontrada para este cliente",
                    }
                ), 404
            selected_machines = [selected_machine]

        summary = {
            "produzido": 0,
            "tempo_produzindo_sec": 0,
            "tempo_parado_sec": 0,
            "ops": 0,
            "paradas": 0,
            "refugo": 0,
            "maquinas": len(selected_machines),
        }

        days_out = []
        cursor = date_to

        while cursor >= date_from:
            machine_rows = []

            for machine_id in selected_machines:
                row = _history_machine_day(
                    conn,
                    cliente_id,
                    machine_id,
                    cursor,
                )

                if selected_machine != "all" or _has_activity(row):
                    machine_rows.append(row)

            day_item = {
                "data": cursor.isoformat(),
                "produzido": sum(
                    _safe_int(row.get("produzido"), 0)
                    for row in machine_rows
                ),
                "pecas_boas": sum(
                    _safe_int(row.get("pecas_boas"), 0)
                    for row in machine_rows
                ),
                "refugo": sum(
                    _safe_int(row.get("refugo"), 0)
                    for row in machine_rows
                ),
                "tempo_produzindo_sec": sum(
                    _safe_int(row.get("tempo_produzindo_sec"), 0)
                    for row in machine_rows
                ),
                "tempo_parado_sec": sum(
                    _safe_int(row.get("tempo_parado_sec"), 0)
                    for row in machine_rows
                ),
                "ops_count": sum(
                    _safe_int(row.get("ops_count"), 0)
                    for row in machine_rows
                ),
                "paradas": sum(
                    _safe_int(row.get("paradas"), 0)
                    for row in machine_rows
                ),
                "maquinas_count": len(
                    [row for row in machine_rows if _has_activity(row)]
                ),
                "machines": machine_rows,
            }

            if selected_machine != "all":
                single = machine_rows[0] if machine_rows else None
                if single:
                    day_item["meta"] = single.get("meta", 0)
                    day_item["percentual"] = single.get("percentual", 0)
                    day_item["ops"] = single.get("ops", [])
                    day_item["maquinas_count"] = 1

            if _has_activity(day_item):
                days_out.append(day_item)

                summary["produzido"] += day_item["produzido"]
                summary["tempo_produzindo_sec"] += day_item["tempo_produzindo_sec"]
                summary["tempo_parado_sec"] += day_item["tempo_parado_sec"]
                summary["ops"] += day_item["ops_count"]
                summary["paradas"] += day_item["paradas"]
                summary["refugo"] += day_item["refugo"]

            cursor -= timedelta(days=1)

        payload = {
            "ok": True,
            "machine_id": selected_machine,
            "machines": machines,
            "selected_machines": selected_machines,
            "date_from": date_from.isoformat(),
            "date_to": date_to.isoformat(),
            "summary": summary,
            "days": days_out,
            "dados": days_out,
        }

        # Compatibilidade com o front antigo: sem wrap e máquina única,
        # mantém retorno como lista de dias.
        wrap = str(request.args.get("wrap") or "").strip() == "1"
        if not wrap and selected_machine != "all":
            legacy = []
            for day_item in reversed(days_out):
                legacy.append(
                    {
                        "data": day_item["data"],
                        "produzido": day_item["produzido"],
                        "pecas_boas": day_item["pecas_boas"],
                        "refugo": day_item["refugo"],
                        "meta": day_item.get("meta", 0),
                        "percentual": day_item.get("percentual", 0),
                        "ops": day_item.get("ops", []),
                        "tempo_produzindo_sec": day_item["tempo_produzindo_sec"],
                        "tempo_parado_sec": day_item["tempo_parado_sec"],
                        "paradas": day_item["paradas"],
                    }
                )
            return jsonify(legacy)

        return jsonify(payload)
    except Exception as exc:
        try:
            print(
                "ERROR historico operacional:\n" + traceback.format_exc(),
                flush=True,
            )
        except Exception:
            pass

        return jsonify(
            {
                "ok": False,
                "error": "Falha ao carregar historico operacional",
                "details": str(exc),
            }
        ), 500
    finally:
        if not callable(get_db):
            try:
                conn.close()
            except Exception:
                pass


@historico_bp.route("/api/producao/detalhe-dia", methods=["GET"])
def api_producao_detalhe_dia():
    cliente_id = _cliente_id_sessao()
    if not cliente_id:
        return jsonify(
            {
                "ok": False,
                "error": "Cliente da sessao nao identificado",
            }
        ), 403

    machine_id = _canonical_machine_id(
        request.args.get("machine_id"),
        cliente_id,
    )
    data_ref = _parse_date_any(
        request.args.get("date")
        or request.args.get("data")
    )

    if not machine_id:
        return jsonify(
            {
                "ok": False,
                "error": "machine_id obrigatorio",
            }
        ), 400

    if data_ref is None:
        data_ref = datetime.now(TZ_BAHIA).date()

    conn = _get_conn()
    try:
        if not _machine_allowed(conn, cliente_id, machine_id):
            return jsonify(
                {
                    "ok": False,
                    "error": "Maquina nao encontrada para este cliente",
                }
            ), 404

        config = _load_machine_config(
            conn,
            cliente_id,
            machine_id,
        )
        meta24 = _meta_24_from_config(config, data_ref)

        state_segments = _state_segments_for_day(
            conn,
            cliente_id,
            machine_id,
            data_ref,
        )

        now_local = datetime.now(TZ_BAHIA).replace(tzinfo=None)
        hours = []

        for hour in range(24):
            start = datetime(
                data_ref.year,
                data_ref.month,
                data_ref.day,
                hour,
                0,
                0,
            )
            end = start + timedelta(hours=1)

            end_calc = end
            if data_ref == now_local.date():
                if now_local <= start:
                    end_calc = start
                elif now_local < end:
                    end_calc = now_local

            start_ms = int(
                start.replace(tzinfo=TZ_BAHIA).timestamp() * 1000
            )
            end_ms = int(
                end_calc.replace(tzinfo=TZ_BAHIA).timestamp() * 1000
            )

            produced_found = False
            produced = 0

            if end_ms > start_ms:
                produced_found, produced = _production_from_events(
                    conn,
                    cliente_id,
                    machine_id,
                    start_ms,
                    end_ms,
                )

            if not produced_found:
                produced = _hourly_fallback(
                    conn,
                    cliente_id,
                    machine_id,
                    data_ref,
                    hour,
                )

            refugo = _hourly_refugo(
                conn,
                cliente_id,
                machine_id,
                data_ref,
                hour,
            )

            meta = (
                max(0, _safe_int(meta24[hour], 0))
                if isinstance(meta24, list) and len(meta24) == 24
                else 0
            )
            force_np = (
                isinstance(meta24, list)
                and len(meta24) == 24
                and meta <= 0
            )

            segments = _clip_state_segments(
                state_segments,
                start,
                end_calc,
                force_np,
            )
            metrics = _segment_dict_metrics(segments)

            hours.append(
                {
                    "hour": hour,
                    "slot": f"{hour:02d}:00-{(hour + 1) % 24:02d}:00",
                    "meta": meta,
                    "produzido": max(0, produced),
                    "refugo": max(0, refugo),
                    "segments": segments,
                    "tempo_produzindo_sec": metrics["tempo_produzindo_sec"],
                    "tempo_parado_sec": metrics["tempo_parado_sec"],
                    "qtd_paradas": metrics["qtd_paradas"],
                }
            )

        return jsonify(
            {
                "ok": True,
                "machine_id": machine_id,
                "effective_machine_id": machine_id,
                "date": data_ref.isoformat(),
                "hours": hours,
            }
        )
    except Exception as exc:
        try:
            print(
                "ERROR detalhe-dia:\n" + traceback.format_exc(),
                flush=True,
            )
        except Exception:
            pass

        return jsonify(
            {
                "ok": False,
                "error": "erro no detalhe-dia",
                "details": str(exc),
            }
        ), 500
    finally:
        if not callable(get_db):
            try:
                conn.close()
            except Exception:
                pass


def _distribute_total(total: int, slots: int = 24) -> list[int]:
    total = max(0, _safe_int(total, 0))
    if slots <= 0:
        return []

    base = total // slots
    remainder = total - base * slots
    values = [base] * slots

    for index in range(remainder):
        values[index] += 1

    return values


@historico_bp.route("/api/producao/backfill-horaria", methods=["POST"])
def api_producao_backfill_horaria():
    """
    Endpoint de compatibilidade para preencher producao_horaria
    quando existe apenas o consolidado diario.
    """
    cliente_id = _cliente_id_sessao()
    if not cliente_id:
        return jsonify(
            {
                "ok": False,
                "error": "Cliente da sessao nao identificado",
            }
        ), 403

    machine_id = _canonical_machine_id(
        request.args.get("machine_id"),
        cliente_id,
    )
    if not machine_id:
        return jsonify(
            {
                "ok": False,
                "error": "machine_id obrigatorio",
            }
        ), 400

    date_from = _parse_date_any(request.args.get("date_from"))
    date_to = _parse_date_any(request.args.get("date_to"))
    today = datetime.now(TZ_BAHIA).date()

    days = max(1, min(_safe_int(request.args.get("days"), 60), 366))
    if date_to is None:
        date_to = today
    if date_from is None:
        date_from = date_to - timedelta(days=days - 1)
    if date_from > date_to:
        date_from, date_to = date_to, date_from

    conn = _get_conn()
    try:
        if not _machine_allowed(conn, cliente_id, machine_id):
            return jsonify(
                {
                    "ok": False,
                    "error": "Maquina nao encontrada para este cliente",
                }
            ), 404

        table = "producao_horaria"
        cols = _get_columns(conn, table)
        data_col = _resolve_data_col(conn, table)
        hour_col = next(
            (
                name
                for name in ("hora_dia", "hora_idx", "hora", "hora_int")
                if name in cols
            ),
            None,
        )

        if (
            not data_col
            or not hour_col
            or "machine_id" not in cols
            or "produzido" not in cols
        ):
            return jsonify(
                {
                    "ok": False,
                    "error": "schema producao_horaria incompleto",
                }
            ), 400

        inserted_rows = 0
        backfilled_days = 0
        details = []
        cursor = date_from

        try:
            conn.execute("BEGIN")
        except Exception:
            pass

        while cursor <= date_to:
            daily = _production_for_day(
                conn,
                cliente_id,
                machine_id,
                cursor,
            )
            total = max(0, _safe_int(daily.get("produzido"), 0))
            meta_total = max(0, _safe_int(daily.get("meta"), 0))

            existing = 0
            try:
                params = []
                where = []

                if cliente_id and "cliente_id" in cols:
                    where.append("cliente_id=?")
                    params.append(cliente_id)

                where.append("machine_id=?")
                params.append(machine_id)
                where.append(f"{data_col}=?")
                params.append(cursor.isoformat())

                row = conn.execute(
                    f"SELECT COUNT(1) AS c FROM {table} "
                    f"WHERE {' AND '.join(where)}",
                    tuple(params),
                ).fetchone()
                existing = _safe_int(row["c"] if row else 0, 0)
            except Exception:
                existing = 0

            if total <= 0 or existing > 0:
                details.append(
                    {
                        "date": cursor.isoformat(),
                        "skipped": True,
                        "reason": (
                            "produzido_dia_zero"
                            if total <= 0
                            else "ja_existe_horaria"
                        ),
                    }
                )
                cursor += timedelta(days=1)
                continue

            production_hours = _distribute_total(total, 24)
            meta_hours = _distribute_total(meta_total, 24)

            insert_cols = ["machine_id", data_col, hour_col, "produzido"]
            if "cliente_id" in cols:
                insert_cols.append("cliente_id")
            if "meta" in cols:
                insert_cols.append("meta")
            if "percentual" in cols:
                insert_cols.append("percentual")
            if "updated_at" in cols:
                insert_cols.append("updated_at")

            sql = (
                f"INSERT INTO {table} ({', '.join(insert_cols)}) "
                f"VALUES ({','.join(['?'] * len(insert_cols))})"
            )

            for hour in range(24):
                values = []
                prod_h = production_hours[hour]
                meta_h = meta_hours[hour]
                pct = (
                    int(round((prod_h / meta_h) * 100))
                    if meta_h > 0
                    else 0
                )

                for column in insert_cols:
                    if column == "machine_id":
                        values.append(machine_id)
                    elif column == data_col:
                        values.append(cursor.isoformat())
                    elif column == hour_col:
                        values.append(hour)
                    elif column == "produzido":
                        values.append(prod_h)
                    elif column == "cliente_id":
                        values.append(cliente_id)
                    elif column == "meta":
                        values.append(meta_h)
                    elif column == "percentual":
                        values.append(pct)
                    elif column == "updated_at":
                        values.append(
                            datetime.now(TZ_BAHIA)
                            .replace(tzinfo=None)
                            .strftime("%Y-%m-%d %H:%M:%S")
                        )
                    else:
                        values.append(None)

                conn.execute(sql, tuple(values))
                inserted_rows += 1

            backfilled_days += 1
            details.append(
                {
                    "date": cursor.isoformat(),
                    "skipped": False,
                    "produzido": total,
                }
            )
            cursor += timedelta(days=1)

        try:
            conn.execute("COMMIT")
        except Exception:
            conn.commit()

        return jsonify(
            {
                "ok": True,
                "machine_id": machine_id,
                "date_from": date_from.isoformat(),
                "date_to": date_to.isoformat(),
                "days_backfilled": backfilled_days,
                "rows_inserted": inserted_rows,
                "details": details,
            }
        )
    except Exception as exc:
        try:
            conn.execute("ROLLBACK")
        except Exception:
            pass

        return jsonify(
            {
                "ok": False,
                "error": "falha no backfill",
                "details": str(exc),
            }
        ), 500
    finally:
        if not callable(get_db):
            try:
                conn.close()
            except Exception:
                pass


@historico_bp.route("/historico", methods=["GET"])
def historico_page():
    return render_template("historico.html")
