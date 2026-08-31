# Caminho: C:\Users\vlula\OneDrive\Área de Trabalho\Projetos Backup\GESTFLOW\apps\indflow\modules\operacao\services.py
# Último recode: 2026-08-31 19:39 (America/Bahia)
# Motivo: Garantir motivo fixo OUTROS na Tela Operacional e manter sua posição ao final da lista de paradas.

from __future__ import annotations

from datetime import date, datetime, timedelta
import re
import sqlite3

from modules.db_indflow import get_db
from modules.paradas.services import (
    classify_occurrence,
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

    stamp = now_local().isoformat()
    conn = get_db()
    try:
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
        conn.commit()
    except sqlite3.OperationalError as exc:
        raise ValueError("Estrutura da Tela Operacional ainda não foi inicializada no banco.") from exc
    finally:
        conn.close()

    return {
        "tempo_obrigatorio_min": tempo,
        "botoes_por_pagina": page_size,
        "ordenacao": order,
    }


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


def get_operational_state(cliente_id: str, machine_id: str) -> dict:
    cid = str(cliente_id or "").strip()
    mid = normalize_machine_id(machine_id, cid)
    if not cid or not mid:
        raise ValueError("Máquina inválida para a empresa atual.")

    config = get_operational_config(cid, mid)
    today = now_local().date()
    start_day = today - timedelta(days=1)
    sync_detected_stops(cid, mid, start_day, today)
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

    return {
        "machine_id": mid,
        "config": config,
        "pending": pending[0] if pending else None,
        "pending_count": len(pending),
        "current_stop": current_stop,
        "active_order": get_active_order(cid, mid),
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
