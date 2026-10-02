# Caminho: C:\Users\vlula\OneDrive\Área de Trabalho\Projetos Backup\GESTFLOW\apps\indflow\modules\operacao\services.py
# Último recode: 2026-10-02 17:26:16 (America/Bahia)
# Motivo: Suspender parada atual e cobrança de classificação fora do turno, nas pausas e sem comunicação, mantendo o acumulado diário e os registros anteriores.

from __future__ import annotations

from datetime import date, datetime, timedelta
import re
import sqlite3
import uuid

from modules.db_indflow import get_db
from modules.producao.historico_routes import (
    _load_machine_config, _planned_intervals_for_day, _communication_status,
)
from modules.paradas.services import (
    classify_occurrence,
    _sum_production,
    ensure_catalog_seed,
    list_occurrences,
    list_reasons,
    list_tenant_machines,
    normalize_machine_id,
    now_local,
    sync_detected_stops,
)

DEFAULT_TEMPO_OBRIGATORIO_MIN = 3
DEFAULT_BOTOES_POR_PAGINA = 8
DEFAULT_ORDENACAO = "mais_clicados"
VALID_ORDENACOES = {"codigo_crescente", "codigo_decrescente", "mais_clicados"}
OTHER_REASON_DESCRIPTION = "OUTROS"


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=? LIMIT 1",
        (str(table),),
    ).fetchone()
    return bool(row)


def _safe_int(value, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return int(default)


def _code_key(value: str) -> tuple:
    parts = re.split(r"(\d+)", str(value or ""))
    return tuple(int(p) if p.isdigit() else p.casefold() for p in parts)


def _ensure_other_reason(cliente_id: str) -> int | None:
    cid = str(cliente_id or "").strip()
    if not cid:
        return None

    ensure_catalog_seed(cid)
    stamp = now_local().isoformat()
    conn = get_db()
    try:
        existing = conn.execute(
            """
            SELECT id
            FROM parada_motivos
            WHERE cliente_id=? AND lower(descricao)=lower(?)
            LIMIT 1
            """,
            (cid, OTHER_REASON_DESCRIPTION),
        ).fetchone()
        if existing:
            reason_id = int(existing["id"])
            conn.execute(
                """
                UPDATE parada_motivos
                SET aplica_todas=1, ativo=1, updated_at=?
                WHERE id=? AND cliente_id=?
                """,
                (stamp, reason_id, cid),
            )
            conn.commit()
            return reason_id

        category = conn.execute(
            """
            SELECT id
            FROM parada_categorias
            WHERE cliente_id=? AND lower(nome)=lower('Outros')
            LIMIT 1
            """,
            (cid,),
        ).fetchone()
        if not category:
            cursor = conn.execute(
                """
                INSERT INTO parada_categorias
                (cliente_id, nome, slug, ordem, ativo, created_at, updated_at)
                VALUES (?, 'Outros', 'outros', 80, 1, ?, ?)
                """,
                (cid, stamp, stamp),
            )
            category_id = int(cursor.lastrowid)
        else:
            category_id = int(category["id"])

        code = "999"
        if conn.execute(
            "SELECT 1 FROM parada_motivos WHERE cliente_id=? AND codigo=? LIMIT 1",
            (cid, code),
        ).fetchone():
            code = "OUT"

        cursor = conn.execute(
            """
            INSERT INTO parada_motivos
            (cliente_id, categoria_id, codigo, descricao, tipo, aplica_todas, ativo, created_at, updated_at)
            VALUES (?, ?, ?, ?, 'nao_planejada', 1, 1, ?, ?)
            """,
            (cid, category_id, code, OTHER_REASON_DESCRIPTION, stamp, stamp),
        )
        conn.commit()
        return int(cursor.lastrowid)
    finally:
        conn.close()


def get_operational_config(cliente_id: str, machine_id: str) -> dict:
    cid = str(cliente_id or "").strip()
    mid = normalize_machine_id(machine_id, cid)
    default = {
        "tempo_obrigatorio_min": DEFAULT_TEMPO_OBRIGATORIO_MIN,
        "botoes_por_pagina": DEFAULT_BOTOES_POR_PAGINA,
        "ordenacao": DEFAULT_ORDENACAO,
        "tipos_ocorrencia": list_occurrence_types(cid, mid) if cid and mid else [],
    }
    if not cid or not mid:
        return default

    conn = get_db()
    try:
        if not _table_exists(conn, "operacao_parada_config"):
            return default
        row = conn.execute(
            """
            SELECT tempo_obrigatorio_min, botoes_por_pagina, ordenacao
            FROM operacao_parada_config
            WHERE cliente_id=? AND lower(machine_id)=lower(?)
            LIMIT 1
            """,
            (cid, mid),
        ).fetchone()
        if not row:
            return default
        order = str(row["ordenacao"] or DEFAULT_ORDENACAO).strip()
        if order not in VALID_ORDENACOES:
            order = DEFAULT_ORDENACAO
        return {
            "tempo_obrigatorio_min": max(1, min(120, _safe_int(row["tempo_obrigatorio_min"], DEFAULT_TEMPO_OBRIGATORIO_MIN))),
            "botoes_por_pagina": max(4, min(20, _safe_int(row["botoes_por_pagina"], DEFAULT_BOTOES_POR_PAGINA))),
            "ordenacao": order,
            "tipos_ocorrencia": default["tipos_ocorrencia"],
        }
    finally:
        conn.close()


def save_operational_config(cliente_id: str, machine_id: str, payload: dict) -> dict:
    cid = str(cliente_id or "").strip()
    mid = normalize_machine_id(machine_id, cid)
    if not cid or not mid:
        raise ValueError("Máquina inválida para a empresa atual.")

    tempo = _safe_int(payload.get("tempo_obrigatorio_min"), DEFAULT_TEMPO_OBRIGATORIO_MIN)
    page_size = _safe_int(payload.get("botoes_por_pagina"), DEFAULT_BOTOES_POR_PAGINA)
    order = str(payload.get("ordenacao") or DEFAULT_ORDENACAO).strip()

    if tempo < 1 or tempo > 120:
        raise ValueError("O tempo obrigatório deve ficar entre 1 e 120 minutos.")
    if page_size < 4 or page_size > 20:
        raise ValueError("A quantidade de botões por página deve ficar entre 4 e 20.")
    if order not in VALID_ORDENACOES:
        raise ValueError("Ordenação inválida.")

    types = validate_occurrence_types(payload["tipos_ocorrencia"]) if "tipos_ocorrencia" in payload else None
    stamp = now_local().isoformat()
    conn = get_db()
    try:
        _ensure_occurrence_tables(conn)
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            """
            INSERT INTO operacao_parada_config
            (cliente_id, machine_id, tempo_obrigatorio_min, botoes_por_pagina, ordenacao, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(cliente_id, machine_id) DO UPDATE SET
                tempo_obrigatorio_min=excluded.tempo_obrigatorio_min,
                botoes_por_pagina=excluded.botoes_por_pagina,
                ordenacao=excluded.ordenacao,
                updated_at=excluded.updated_at
            """,
            (cid, mid, tempo, page_size, order, stamp),
        )
        if types is not None:
            _store_occurrence_types(conn, cid, mid, types, stamp)
        conn.commit()
    except sqlite3.OperationalError as exc:
        raise ValueError("Estrutura da Tela Operacional ainda não foi inicializada no banco.") from exc
    finally:
        conn.close()

    return get_operational_config(cid, mid)


def list_operational_reasons(cliente_id: str, machine_id: str, order: str) -> list[dict]:
    cid = str(cliente_id or "").strip()
    mid = normalize_machine_id(machine_id, cid)
    _ensure_other_reason(cid)
    reasons = list_reasons(cid, machine_id=mid)
    usage: dict[int, int] = {}

    conn = get_db()
    try:
        if _table_exists(conn, "parada_ocorrencias"):
            rows = conn.execute(
                """
                SELECT motivo_id, COUNT(1) AS total
                FROM parada_ocorrencias
                WHERE cliente_id=? AND lower(machine_id)=lower(?) AND motivo_id IS NOT NULL
                GROUP BY motivo_id
                """,
                (cid, mid),
            ).fetchall()
            usage = {int(r["motivo_id"]): int(r["total"] or 0) for r in rows}
    finally:
        conn.close()

    for reason in reasons:
        reason["uso_count"] = usage.get(int(reason.get("id") or 0), 0)

    if order == "codigo_decrescente":
        reasons.sort(key=lambda r: _code_key(r.get("codigo") or ""), reverse=True)
    elif order == "mais_clicados":
        reasons.sort(key=lambda r: (-int(r.get("uso_count") or 0), _code_key(r.get("codigo") or "")))
    else:
        reasons.sort(key=lambda r: _code_key(r.get("codigo") or ""))

    reasons.sort(
        key=lambda r: str(r.get("descricao") or "").strip().casefold() == OTHER_REASON_DESCRIPTION.casefold()
    )
    return reasons


def get_active_order(cliente_id: str, machine_id: str) -> dict | None:
    cid = str(cliente_id or "").strip()
    mid = normalize_machine_id(machine_id, cid)
    if not cid or not mid:
        return None
    conn = get_db()
    try:
        if not _table_exists(conn, "ordens_producao"):
            return None
        row = conn.execute(
            """
            SELECT id, os, lote, operador, started_at
            FROM ordens_producao
            WHERE cliente_id=? AND lower(machine_id)=lower(?) AND status='ATIVA'
            ORDER BY id DESC
            LIMIT 1
            """,
            (cid, mid),
        ).fetchone()
        if not row:
            return None
        return {
            "id": int(row["id"]),
            "os": str(row["os"] or ""),
            "lote": str(row["lote"] or ""),
            "operador": str(row["operador"] or ""),
            "started_at": row["started_at"],
        }
    finally:
        conn.close()


def _sync_operational_stop_from_state_events(cliente_id: str, machine_id: str) -> None:
    """
    Mantem o cronometro/classificacao da Tela Operacional independente de meta/turno.

    Fonte: ultima transicao real em machine_state_event, sempre isolada por
    cliente_id + machine_id. STOP abre/atualiza uma ocorrencia operacional;
    qualquer outro estado fecha apenas ocorrencias telemetricas ainda abertas.

    Isso nao altera a regra de indicadores/historico em paradas.services.
    """
    cid = str(cliente_id or "").strip()
    mid = normalize_machine_id(machine_id, cid)
    if not cid or not mid:
        return

    scoped_mid = f"{cid}::{mid}"
    conn = get_db()
    try:
        if not _table_exists(conn, "machine_state_event") or not _table_exists(conn, "parada_ocorrencias"):
            return

        row = conn.execute(
            """
            SELECT id, ts_ms, state
            FROM machine_state_event
            WHERE cliente_id=?
              AND (
                    lower(machine_id)=lower(?)
                 OR lower(effective_machine_id)=lower(?)
                 OR lower(effective_machine_id)=lower(?)
              )
            ORDER BY ts_ms DESC, id DESC
            LIMIT 1
            """,
            (cid, mid, mid, scoped_mid),
        ).fetchone()
        if not row:
            return

        state = str(row["state"] or "").strip().upper()
        transition_ms = _safe_int(row["ts_ms"], 0)
        if transition_ms <= 0:
            return

        now_ms = int(now_local().timestamp() * 1000)
        stamp = now_local().isoformat()

        if state == "STOP":
            duration_sec = max(0, int((now_ms - transition_ms) / 1000))
            conn.execute(
                """
                INSERT INTO parada_ocorrencias
                (cliente_id, machine_id, started_at_ms, ended_at_ms, duration_sec, source, status, created_at, updated_at)
                VALUES (?, ?, ?, NULL, ?, 'operacao_telemetria', 'ABERTA', ?, ?)
                ON CONFLICT(cliente_id, machine_id, started_at_ms) DO UPDATE SET
                    ended_at_ms=NULL,
                    duration_sec=excluded.duration_sec,
                    status='ABERTA',
                    updated_at=excluded.updated_at
                """,
                (cid, mid, transition_ms, duration_sec, stamp, stamp),
            )
            conn.commit()
            return

        conn.execute(
            """
            UPDATE parada_ocorrencias
            SET ended_at_ms=?,
                duration_sec=MAX(0, CAST((? - started_at_ms) / 1000 AS INTEGER)),
                status='FECHADA',
                updated_at=?
            WHERE cliente_id=?
              AND lower(machine_id)=lower(?)
              AND ended_at_ms IS NULL
              AND source IN ('operacao_telemetria', 'telemetria')
            """,
            (transition_ms, transition_ms, stamp, cid, mid),
        )
        conn.commit()
    finally:
        conn.close()


def _operational_window(cliente_id: str, machine_id: str) -> dict:
    reference = now_local()
    local = reference.replace(tzinfo=None)
    conn = get_db()
    try:
        config = _load_machine_config(conn, cliente_id, machine_id)
        planned = _planned_intervals_for_day(config, reference.date())
        comm = _communication_status(conn, cliente_id, machine_id, int(reference.timestamp()*1000))
    finally:
        conn.close()
    end_day = local.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
    active = planned is None or any(s <= local < e for s, e in planned)
    until = next((e for s, e in planned or [] if s <= local < e), end_day)
    status = "EM_TURNO" if active else "FORA_TURNO"
    if not active:
        cv2 = config.get("config_v2", config)
        if isinstance(cv2, dict):
            unbroken = {**cv2, "shifts": [{**s, "breaks": []} for s in cv2.get("shifts", []) if isinstance(s, dict)]}
            outer = _planned_intervals_for_day(unbroken, reference.date())
            if any(s <= local < e for s, e in outer or []): status = "PAUSA"
    return {"programado": active, "status": status, "reference_ms": int(reference.timestamp()*1000),
            "valid_until_ms": int(until.replace(tzinfo=reference.tzinfo).timestamp()*1000), "comunicacao": comm}


def get_operational_state(cliente_id: str, machine_id: str) -> dict:
    cid = str(cliente_id or "").strip()
    mid = normalize_machine_id(machine_id, cid)
    if not cid or not mid:
        raise ValueError("Máquina inválida para a empresa atual.")

    config = get_operational_config(cid, mid)
    window = _operational_window(cid, mid)
    today = now_local().date()
    start_day = today - timedelta(days=1)
    rows = sync_detected_stops(cid, mid, start_day, today)
    _sync_operational_stop_from_state_events(cid, mid)

    threshold_sec = int(config["tempo_obrigatorio_min"]) * 60
    pending = [
        row for row in rows
        if not row.get("classificada") and int(row.get("duration_sec") or 0) >= threshold_sec
    ]
    pending.sort(key=lambda row: int(row.get("started_at_ms") or 0))

    open_rows = [row for row in rows if row.get("ended_at_ms") in (None, "")]
    open_rows.sort(key=lambda row: int(row.get("started_at_ms") or 0), reverse=True)
    current_stop = open_rows[0] if open_rows else None
    if not window["programado"] or window["comunicacao"].get("online") is False:
        current_stop = None
        pending = []
    reference_ms = int(now_local().timestamp() * 1000)
    today_rows = [row for row in rows if row.get("data_ref") == today.isoformat()]
    day_end = datetime.combine(today + timedelta(days=1), datetime.min.time(), tzinfo=now_local().tzinfo)
    daily_open = next((row for row in today_rows if row.get("ended_at_ms") is None), None)
    if daily_open:
        reference_ms = int(daily_open.get("reference_ms") or reference_ms)

    return {
        "machine_id": mid,
        "programacao": window,
        "config": config,
        "pending": pending[0] if pending else None,
        "pending_count": len(pending),
        "current_stop": current_stop,
        "active_order": get_active_order(cid, mid),
        "ocorrencias_producao": get_occurrence_summary(cid, mid),
        "paradas_hoje": {
            "duration_sec": sum(int(row.get("duration_sec") or 0) for row in today_rows),
            "open_count": 1 if daily_open else 0,
            "reference_ms": reference_ms,
            "data_ref": today.isoformat(),
            "day_end_ms": int(day_end.timestamp() * 1000),
            "open_until_ms": min(int(daily_open.get("open_until_ms") or day_end.timestamp() * 1000),
                                 int(window["comunicacao"].get("expires_at_ms") or day_end.timestamp()*1000)) if daily_open else None,
        },
    }


def classify_pending_occurrence(
    cliente_id: str,
    occurrence_id: int,
    motivo_id: int,
    classificado_por: str,
) -> dict:
    cid = str(cliente_id or "").strip()
    conn = get_db()
    try:
        row = conn.execute(
            """
            SELECT id, machine_id, started_at_ms, ended_at_ms, motivo_id
            FROM parada_ocorrencias
            WHERE id=? AND cliente_id=?
            LIMIT 1
            """,
            (int(occurrence_id), cid),
        ).fetchone()
        if not row:
            raise ValueError("Parada não encontrada.")
        if row["motivo_id"] is not None:
            raise ValueError("Esta parada já foi classificada.")
        mid = normalize_machine_id(row["machine_id"], cid)
        cfg = get_operational_config(cid, mid)
        now_ms = int(now_local().timestamp() * 1000)
        finish = _safe_int(row["ended_at_ms"], now_ms) if row["ended_at_ms"] not in (None, "") else now_ms
        duration_sec = max(0, int((finish - int(row["started_at_ms"] or 0)) / 1000))
        if duration_sec < int(cfg["tempo_obrigatorio_min"]) * 60:
            raise ValueError("Esta parada ainda não atingiu o tempo mínimo obrigatório.")
    finally:
        conn.close()

    return classify_occurrence(
        cid,
        int(occurrence_id),
        int(motivo_id),
        "",
        "",
        str(classificado_por or ""),
    )


def list_operational_machines(cliente_id: str) -> list[str]:
    return list_tenant_machines(str(cliente_id or "").strip())


def _ensure_occurrence_tables(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS operacao_ocorrencia_tipos (
            cliente_id TEXT NOT NULL, machine_id TEXT NOT NULL, id TEXT NOT NULL,
            nome TEXT NOT NULL, desconta_producao INTEGER NOT NULL,
            ativo INTEGER NOT NULL DEFAULT 1, ordem INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
            PRIMARY KEY (cliente_id, machine_id, id)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS operacao_ocorrencia_registros (
            cliente_id TEXT NOT NULL, machine_id TEXT NOT NULL,
            request_id TEXT NOT NULL, tipo_id TEXT NOT NULL,
            nome TEXT NOT NULL, quantidade INTEGER NOT NULL CHECK (quantidade > 0),
            desconta_producao INTEGER NOT NULL, data_ref TEXT NOT NULL,
            operador_id TEXT NOT NULL, operador_nome TEXT NOT NULL,
            op_id INTEGER, created_at TEXT NOT NULL,
            PRIMARY KEY (cliente_id, machine_id, request_id, tipo_id)
        )
    """)
    # Correções separadas preservam o lançamento original e sua idempotência.
    conn.execute("""
        CREATE TABLE IF NOT EXISTS operacao_ocorrencia_ajustes (
            cliente_id TEXT NOT NULL, machine_id TEXT NOT NULL,
            request_id TEXT NOT NULL, tipo_id TEXT NOT NULL,
            quantidade INTEGER NOT NULL CHECK (quantidade > 0),
            excluido INTEGER NOT NULL DEFAULT 0, versao INTEGER NOT NULL,
            alterado_por_id TEXT NOT NULL, alterado_por_nome TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (cliente_id, machine_id, request_id, tipo_id)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS operacao_ocorrencia_historico (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            cliente_id TEXT NOT NULL, machine_id TEXT NOT NULL,
            request_id TEXT NOT NULL, tipo_id TEXT NOT NULL, acao TEXT NOT NULL,
            quantidade_anterior INTEGER NOT NULL, quantidade_nova INTEGER NOT NULL,
            excluido_anterior INTEGER NOT NULL, excluido_novo INTEGER NOT NULL,
            versao INTEGER NOT NULL, operador_id TEXT NOT NULL,
            operador_nome TEXT NOT NULL, created_at TEXT NOT NULL
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS ix_operacao_ocorrencias_dia "
                 "ON operacao_ocorrencia_registros(cliente_id, machine_id, data_ref)")
    conn.commit()


def list_occurrence_types(cliente_id: str, machine_id: str) -> list[dict]:
    conn = get_db()
    try:
        _ensure_occurrence_tables(conn)
        rows = conn.execute("""
            SELECT id, nome, desconta_producao, ativo
            FROM operacao_ocorrencia_tipos WHERE cliente_id=? AND machine_id=?
            ORDER BY ordem, created_at, id
        """, (cliente_id, machine_id)).fetchall()
        return [{"id": row["id"], "nome": row["nome"],
                 "desconta_producao": bool(row["desconta_producao"]),
                 "ativo": bool(row["ativo"])} for row in rows]
    finally:
        conn.close()


def validate_occurrence_types(raw) -> list[dict]:
    if not isinstance(raw, list) or len(raw) > 20:
        raise ValueError("Cadastre até 20 tipos de ocorrência por máquina.")
    out, ids, names = [], set(), set()
    for item in raw:
        if not isinstance(item, dict):
            raise ValueError("Tipo de ocorrência inválido.")
        try:
            type_id = str(uuid.UUID(str(item.get("id") or uuid.uuid4())))
        except ValueError as exc:
            raise ValueError("Identificador de ocorrência inválido.") from exc
        name = str(item.get("nome") or "").strip()
        active, deduct = item.get("ativo", True), item.get("desconta_producao")
        if not name or len(name) > 60:
            raise ValueError("Informe um nome de ocorrência com até 60 caracteres.")
        if not isinstance(active, bool) or not isinstance(deduct, bool):
            raise ValueError("Informe se a ocorrência está ativa e desconta da produção.")
        if type_id in ids or (active and name.casefold() in names):
            raise ValueError("Não repita o nome ou identificador de uma ocorrência ativa.")
        ids.add(type_id)
        if active:
            names.add(name.casefold())
        out.append({"id": type_id, "nome": name, "ativo": active, "desconta_producao": deduct})
    return out


def _store_occurrence_types(conn, cid, mid, types, stamp):
    # Desativa os tipos retirados do cadastro; preserva registros anteriores.
    conn.execute("UPDATE operacao_ocorrencia_tipos SET ativo=0, updated_at=? "
                 "WHERE cliente_id=? AND machine_id=?", (stamp, cid, mid))
    for order, item in enumerate(types):
        conn.execute("""
            INSERT INTO operacao_ocorrencia_tipos
            (cliente_id, machine_id, id, nome, desconta_producao, ativo, ordem, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(cliente_id, machine_id, id) DO UPDATE SET
                nome=excluded.nome, desconta_producao=excluded.desconta_producao,
                ativo=excluded.ativo, ordem=excluded.ordem, updated_at=excluded.updated_at
        """, (cid, mid, item["id"], item["nome"], int(item["desconta_producao"]),
              int(item["ativo"]), order, stamp, stamp))


def _quality_day_production(conn, cid, mid, day, now):
    start = datetime.combine(day, datetime.min.time(), tzinfo=now.tzinfo)
    end = min(start + timedelta(days=1), now + timedelta(milliseconds=1))
    return _sum_production(conn, cid, mid, int(start.timestamp() * 1000), int(end.timestamp() * 1000))


def _quality_discount(conn, cid, mid, day):
    row = conn.execute("""
        SELECT COALESCE(SUM(COALESCE(a.quantidade, r.quantidade)), 0) AS total
        FROM operacao_ocorrencia_registros r
        LEFT JOIN operacao_ocorrencia_ajustes a USING (cliente_id, machine_id, request_id, tipo_id)
        WHERE r.cliente_id=? AND r.machine_id=? AND r.data_ref=?
          AND r.desconta_producao=1 AND COALESCE(a.excluido, 0)=0
    """, (cid, mid, day.isoformat())).fetchone()
    return int(row["total"])


def _occurrence_summary(conn, cid, mid, now):
    day = now.date().isoformat()
    gross = _quality_day_production(conn, cid, mid, now.date(), now)
    totals = conn.execute("""
        SELECT r.tipo_id, SUM(COALESCE(a.quantidade, r.quantidade)) AS quantidade,
               SUM(CASE WHEN r.desconta_producao=1 THEN COALESCE(a.quantidade, r.quantidade) ELSE 0 END) AS desconto
        FROM operacao_ocorrencia_registros r
        LEFT JOIN operacao_ocorrencia_ajustes a USING (cliente_id, machine_id, request_id, tipo_id)
        WHERE r.cliente_id=? AND r.machine_id=? AND r.data_ref=?
          AND COALESCE(a.excluido, 0)=0 GROUP BY r.tipo_id
    """, (cid, mid, day)).fetchall()
    discount = sum(int(row["desconto"] or 0) for row in totals)
    last = conn.execute("""
        SELECT r.created_at, r.operador_nome FROM operacao_ocorrencia_registros r
        LEFT JOIN operacao_ocorrencia_ajustes a USING (cliente_id, machine_id, request_id, tipo_id)
        WHERE r.cliente_id=? AND r.machine_id=? AND r.data_ref=? AND COALESCE(a.excluido, 0)=0
        ORDER BY r.created_at DESC, r.rowid DESC LIMIT 1
    """, (cid, mid, day)).fetchone()
    return {"data_ref": day, "producao_bruta": gross, "descontos": discount,
            "saldo": max(0, gross - discount),
            "totais": {row["tipo_id"]: int(row["quantidade"]) for row in totals},
            "ultimo_registro": dict(last) if last else None}


def get_occurrence_summary(cliente_id: str, machine_id: str) -> dict:
    conn = get_db()
    try:
        _ensure_occurrence_tables(conn)
        return _occurrence_summary(conn, cliente_id, machine_id, now_local())
    finally:
        conn.close()


def save_production_occurrences(cliente_id: str, machine_id: str, payload: dict,
                                operador_id: str, operador_nome: str) -> dict:
    cid = str(cliente_id or "").strip()
    mid = normalize_machine_id(machine_id, cid)
    if not cid or not mid or not operador_id or not operador_nome:
        raise ValueError("Empresa, máquina e operador são obrigatórios.")
    try:
        request_id = str(uuid.UUID(str(payload.get("request_id") or "")))
    except ValueError as exc:
        raise ValueError("Identificador do lançamento inválido. Atualize a tela.") from exc
    raw = payload.get("itens")
    if not isinstance(raw, list) or not raw or len(raw) > 20:
        raise ValueError("Informe pelo menos uma quantidade para registrar.")
    items = {}
    for item in raw:
        if not isinstance(item, dict):
            raise ValueError("Lançamento inválido.")
        type_id, quantity = str(item.get("tipo_id") or ""), item.get("quantidade")
        if type_id in items or isinstance(quantity, bool) or not isinstance(quantity, int) or quantity < 1 or quantity > 1000000000:
            raise ValueError("Use quantidades inteiras positivas, sem repetir o tipo de ocorrência.")
        items[type_id] = quantity
    conn = get_db()
    try:
        _ensure_occurrence_tables(conn)
        conn.execute("BEGIN IMMEDIATE")
        existing = conn.execute("""
            SELECT tipo_id, quantidade FROM operacao_ocorrencia_registros
            WHERE cliente_id=? AND machine_id=? AND request_id=?
        """, (cid, mid, request_id)).fetchall()
        if existing:
            if {r["tipo_id"]: int(r["quantidade"]) for r in existing} != items:
                raise ValueError("Este lançamento já foi salvo com outros valores. Atualize a tela.")
            return {"duplicado": True, "resumo": _occurrence_summary(conn, cid, mid, now_local())}
        types = {r["id"]: dict(r) for r in conn.execute("""
            SELECT id, nome, desconta_producao FROM operacao_ocorrencia_tipos
            WHERE cliente_id=? AND machine_id=? AND ativo=1
        """, (cid, mid)).fetchall()}
        if any(type_id not in types for type_id in items):
            raise ValueError("A configuração de ocorrências mudou. Atualize a tela.")
        now = now_local()
        summary = _occurrence_summary(conn, cid, mid, now)
        new_discount = sum(quantity for type_id, quantity in items.items() if types[type_id]["desconta_producao"])
        if summary["descontos"] + new_discount > summary["producao_bruta"]:
            raise ValueError("Os descontos não podem ultrapassar a produção registrada hoje.")
        op_id = None
        if _table_exists(conn, "ordens_producao"):
            op = conn.execute("SELECT id FROM ordens_producao WHERE cliente_id=? "
                              "AND lower(machine_id)=lower(?) AND status='ATIVA' ORDER BY id DESC LIMIT 1",
                              (cid, mid)).fetchone()
            op_id = int(op["id"]) if op else None
        stamp = now.isoformat()
        for type_id, quantity in items.items():
            occurrence = types[type_id]
            conn.execute("""
                INSERT INTO operacao_ocorrencia_registros
                (cliente_id, machine_id, request_id, tipo_id, nome, quantidade,
                 desconta_producao, data_ref, operador_id, operador_nome, op_id, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (cid, mid, request_id, type_id, occurrence["nome"], quantity,
                  occurrence["desconta_producao"], summary["data_ref"], operador_id, operador_nome, op_id, stamp))
        result = _occurrence_summary(conn, cid, mid, now)
        conn.commit()
        return {"duplicado": False, "resumo": result}
    finally:
        conn.close()


def list_production_occurrences(cliente_id: str, machine_id: str, data_ref: str = "", pagina: int = 1) -> dict:
    cid = str(cliente_id or "").strip()
    mid = normalize_machine_id(machine_id, cid)
    now = now_local()
    try:
        day = date.fromisoformat(data_ref) if data_ref else now.date()
    except (ValueError, TypeError) as exc:
        raise ValueError("Data dos lançamentos inválida.") from exc
    if not cid or not mid or day > now.date():
        raise ValueError("Informe a máquina e uma data até hoje.")
    if isinstance(pagina, bool) or not isinstance(pagina, int) or pagina < 1:
        raise ValueError("Página de lançamentos inválida.")
    conn = get_db()
    try:
        _ensure_occurrence_tables(conn)
        conn.execute("BEGIN")
        total = conn.execute("SELECT COUNT(*) FROM operacao_ocorrencia_registros "
                             "WHERE cliente_id=? AND machine_id=? AND data_ref=?",
                             (cid, mid, day.isoformat())).fetchone()[0]
        pages = max(1, (total + 24) // 25)
        page = min(pagina, pages)
        rows = conn.execute("""
            SELECT r.request_id, r.tipo_id, r.nome, r.desconta_producao, r.created_at,
                   r.operador_nome, r.op_id, COALESCE(a.quantidade, r.quantidade) AS quantidade,
                   COALESCE(a.excluido, 0) AS excluido, COALESCE(a.versao, 0) AS versao,
                   a.updated_at, a.alterado_por_nome
            FROM operacao_ocorrencia_registros r
            LEFT JOIN operacao_ocorrencia_ajustes a USING (cliente_id, machine_id, request_id, tipo_id)
            WHERE r.cliente_id=? AND r.machine_id=? AND r.data_ref=?
            ORDER BY r.created_at DESC, r.rowid DESC LIMIT 25 OFFSET ?
        """, (cid, mid, day.isoformat(), (page - 1) * 25)).fetchall()
        return {"data_ref": day.isoformat(), "registros": [dict(row) for row in rows],
                "total": total, "pagina": page, "paginas": pages}
    finally:
        conn.close()


def change_production_occurrence(cliente_id: str, machine_id: str, payload: dict,
                                 operador_id: str, operador_nome: str) -> dict:
    cid = str(cliente_id or "").strip()
    mid = normalize_machine_id(machine_id, cid)
    if not cid or not mid or not operador_id or not operador_nome:
        raise ValueError("Empresa, máquina e operador são obrigatórios.")
    try:
        request_id = str(uuid.UUID(str(payload.get("request_id") or "")))
        type_id = str(uuid.UUID(str(payload.get("tipo_id") or "")))
    except ValueError as exc:
        raise ValueError("Identificador do lançamento inválido.") from exc
    action, version = payload.get("acao"), payload.get("versao")
    if action not in ("editar", "excluir") or isinstance(version, bool) or not isinstance(version, int) or version < 0:
        raise ValueError("Ação ou versão do lançamento inválida.")
    quantity = payload.get("quantidade")
    if action == "editar" and (isinstance(quantity, bool) or not isinstance(quantity, int)
                              or not 1 <= quantity <= 1000000000):
        raise ValueError("Informe uma quantidade inteira de 1 a 1.000.000.000.")
    conn = get_db()
    try:
        _ensure_occurrence_tables(conn)
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute("""
            SELECT r.data_ref, r.desconta_producao, COALESCE(a.quantidade, r.quantidade) AS quantidade,
                   COALESCE(a.excluido, 0) AS excluido, COALESCE(a.versao, 0) AS versao
            FROM operacao_ocorrencia_registros r
            LEFT JOIN operacao_ocorrencia_ajustes a USING (cliente_id, machine_id, request_id, tipo_id)
            WHERE r.cliente_id=? AND r.machine_id=? AND r.request_id=? AND r.tipo_id=?
        """, (cid, mid, request_id, type_id)).fetchone()
        if not row:
            raise ValueError("Lançamento não encontrado nesta máquina.")
        if row["versao"] != version:
            raise ValueError("Este lançamento foi alterado. Atualize a lista antes de tentar novamente.")
        if row["excluido"]:
            raise ValueError("Este lançamento já foi excluído.")
        previous_quantity = int(row["quantidade"])
        excluded = int(action == "excluir")
        quantity = previous_quantity if excluded else quantity
        now = now_local()
        if not excluded and row["desconta_producao"] and quantity > previous_quantity:
            day = date.fromisoformat(row["data_ref"])
            discount = _quality_discount(conn, cid, mid, day) + quantity - previous_quantity
            if discount > _quality_day_production(conn, cid, mid, day, now):
                raise ValueError("Os descontos não podem ultrapassar a produção registrada na data do lançamento.")
        if not excluded and quantity == previous_quantity:
            return {"resumo": _occurrence_summary(conn, cid, mid, now)}
        stamp, next_version = now.isoformat(), version + 1
        conn.execute("""
            INSERT INTO operacao_ocorrencia_ajustes
            (cliente_id, machine_id, request_id, tipo_id, quantidade, excluido, versao,
             alterado_por_id, alterado_por_nome, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(cliente_id, machine_id, request_id, tipo_id) DO UPDATE SET
                quantidade=excluded.quantidade, excluido=excluded.excluido, versao=excluded.versao,
                alterado_por_id=excluded.alterado_por_id, alterado_por_nome=excluded.alterado_por_nome,
                updated_at=excluded.updated_at
        """, (cid, mid, request_id, type_id, quantity, excluded, next_version, operador_id, operador_nome, stamp))
        conn.execute("""
            INSERT INTO operacao_ocorrencia_historico
            (cliente_id, machine_id, request_id, tipo_id, acao, quantidade_anterior, quantidade_nova,
             excluido_anterior, excluido_novo, versao, operador_id, operador_nome, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?, ?, ?)
        """, (cid, mid, request_id, type_id, action, previous_quantity, quantity,
              excluded, next_version, operador_id, operador_nome, stamp))
        result = _occurrence_summary(conn, cid, mid, now)
        conn.commit()
        return {"resumo": result}
    finally:
        conn.close()
