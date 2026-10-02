# Caminho: C:\Users\vlula\OneDrive\Área de Trabalho\Projetos Backup\GESTFLOW\apps\indflow\modules\operacao\services.py
# Último recode: 2026-10-02 11:37:23 (America/Bahia)
# Motivo: Persistir tipos e lançamentos de ocorrências por empresa e máquina, calcular saldo de hoje e informar paradas acumuladas sem alterar a contagem original.

from __future__ import annotations

from datetime import date, datetime, timedelta
import re
import sqlite3
import uuid

from modules.db_indflow import get_db
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


def get_operational_state(cliente_id: str, machine_id: str) -> dict:
    cid = str(cliente_id or "").strip()
    mid = normalize_machine_id(machine_id, cid)
    if not cid or not mid:
        raise ValueError("Máquina inválida para a empresa atual.")

    config = get_operational_config(cid, mid)
    today = now_local().date()
    start_day = today - timedelta(days=1)
    sync_detected_stops(cid, mid, start_day, today)
    _sync_operational_stop_from_state_events(cid, mid)
    rows = list_occurrences(cid, mid, start_day, today, sync=False)

    threshold_sec = int(config["tempo_obrigatorio_min"]) * 60
    pending = [
        row for row in rows
        if not row.get("classificada") and int(row.get("duration_sec") or 0) >= threshold_sec
    ]
    pending.sort(key=lambda row: int(row.get("started_at_ms") or 0))

    open_rows = [row for row in rows if row.get("ended_at_ms") in (None, "")]
    open_rows.sort(key=lambda row: int(row.get("started_at_ms") or 0), reverse=True)
    current_stop = open_rows[0] if open_rows else None
    reference_ms = int(now_local().timestamp() * 1000)
    day_start_ms = int(now_local().replace(hour=0, minute=0, second=0, microsecond=0).timestamp() * 1000)
    today_rows = [row for row in rows if int(row.get("ended_at_ms") or reference_ms) > day_start_ms]

    return {
        "machine_id": mid,
        "config": config,
        "pending": pending[0] if pending else None,
        "pending_count": len(pending),
        "current_stop": current_stop,
        "active_order": get_active_order(cid, mid),
        "ocorrencias_producao": get_occurrence_summary(cid, mid),
        "paradas_hoje": {
            "duration_sec": sum(int(row.get("duration_sec") or 0) for row in today_rows),
            "open_count": sum(row.get("ended_at_ms") in (None, "") for row in today_rows),
            "reference_ms": reference_ms,
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


def _occurrence_summary(conn, cid, mid, now):
    day = now.date().isoformat()
    start_ms = int(now.replace(hour=0, minute=0, second=0, microsecond=0).timestamp() * 1000)
    gross = _sum_production(conn, cid, mid, start_ms, int(now.timestamp() * 1000) + 1)
    totals = conn.execute("""
        SELECT tipo_id, SUM(quantidade) AS quantidade,
               SUM(CASE WHEN desconta_producao=1 THEN quantidade ELSE 0 END) AS desconto
        FROM operacao_ocorrencia_registros
        WHERE cliente_id=? AND machine_id=? AND data_ref=? GROUP BY tipo_id
    """, (cid, mid, day)).fetchall()
    discount = sum(int(row["desconto"] or 0) for row in totals)
    last = conn.execute("""
        SELECT created_at, operador_nome FROM operacao_ocorrencia_registros
        WHERE cliente_id=? AND machine_id=? AND data_ref=?
        ORDER BY created_at DESC, rowid DESC LIMIT 1
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
