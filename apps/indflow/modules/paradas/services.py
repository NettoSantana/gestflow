# Caminho: C:\Users\vlula\OneDrive\Área de Trabalho\Projetos Backup\GESTFLOW\apps\indflow\modules\paradas\services.py
# Último recode: 2026-08-31 15:47 (America/Bahia)
# Motivo: Centralizar a lista de máquinas reais em Devices, isolada por tenant e MAC válido.

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Iterable
from zoneinfo import ZoneInfo
import json
import re
import sqlite3

from modules.db_indflow import get_db
from modules.producao.historico_routes import (
    _build_meta_24_from_config_v2,
    _build_meta_24_from_machine_state,
    _build_segments_for_hour_from_day_segments,
    _fetch_horaria,
    _fetch_state_segments_from_state_events,
    _load_machine_config_json,
    _resolve_effective_machine_id,
)
from modules.teste.services import (
    is_test_machine,
    list_active_test_machines,
    test_day_state,
    test_period_totals,
)

try:
    from modules.machine_state import get_machine
except Exception:
    get_machine = None

TZ_BAHIA = ZoneInfo("America/Bahia")

DEFAULT_CATEGORIES = [
    ("Produção", 10),
    ("Manutenção", 20),
    ("Qualidade", 30),
    ("Segurança", 40),
    ("Utilidades", 50),
    ("Pessoal", 60),
    ("Logística", 70),
    ("Outros", 80),
]

# Carga inicial baseada na tabela enviada pelo usuario. As categorias e o tipo
# podem ser ajustados pela interface sem alterar os eventos de telemetria.
DEFAULT_REASONS = [
    ("1", "DDS", "Segurança", "planejada"),
    ("2", "PREPARAÇÃO DE MÁQUINA/AQUECIMENTO", "Produção", "planejada"),
    ("103", "TROCA DE ROLO / ABASTECIMENTO", "Produção", "planejada"),
    ("104", "ENROSCO NO CILINDRO", "Produção", "nao_planejada"),
    ("105", "REGULAGEM DO CORTE DA FACA DO AVENTAL", "Produção", "nao_planejada"),
    ("106", "REGULAGEM DO CORTE DA FACA DA GOLA", "Produção", "nao_planejada"),
    ("107", "ROMPIMENTO DE TNT", "Qualidade", "nao_planejada"),
    ("108", "AJUSTE DE CORTE DAS FITAS", "Produção", "nao_planejada"),
    ("109", "AJUSTE DE TEMPERATURA DA SELAGEM", "Produção", "nao_planejada"),
    ("110", "TROCA DE LÂMINA", "Manutenção", "planejada"),
    ("111", "TROCA DE PISTÃO", "Manutenção", "nao_planejada"),
    ("112", "FALHA NO SENSOR", "Manutenção", "nao_planejada"),
    ("113", "BAIXA VAZÃO DE AR-COMPRIMIDO", "Utilidades", "nao_planejada"),
    ("114", "TROCA DE PARAFUSO", "Manutenção", "nao_planejada"),
    ("115", "SOBRECARGA NO TRANSDUTOR", "Manutenção", "nao_planejada"),
    ("116", "PANE ELÉTRICA", "Manutenção", "nao_planejada"),
    ("117", "ROMPIMENTO DO ELÁSTICO", "Qualidade", "nao_planejada"),
    ("118", "TRAVAMENTO DA ESTEIRA", "Produção", "nao_planejada"),
    ("119", "LIMPEZA DA RECARTILHA", "Produção", "planejada"),
    ("120", "TROCA DE FITA DO CILINDRO", "Manutenção", "planejada"),
    ("121", "DESCANSO/IDA AO BANHEIRO", "Pessoal", "planejada"),
]


def now_local() -> datetime:
    return datetime.now(TZ_BAHIA)


def now_iso() -> str:
    return now_local().isoformat(timespec="seconds")


def slugify(value: str) -> str:
    import unicodedata

    s = unicodedata.normalize("NFKD", str(value or ""))
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    s = re.sub(r"[^a-zA-Z0-9]+", "-", s).strip("-").lower()
    return s or "categoria"


def normalize_machine_id(machine_id: str, cliente_id: str | None = None) -> str:
    raw = str(machine_id or "").strip()
    cid = str(cliente_id or "").strip()
    if not raw:
        return ""
    if cid and raw.startswith(f"{cid}::"):
        return raw.split("::", 1)[1].strip()
    if "::" in raw:
        return raw.split("::", 1)[-1].strip()
    return raw


def machine_candidates(cliente_id: str, machine_id: str) -> list[str]:
    cid = str(cliente_id or "").strip()
    mid = normalize_machine_id(machine_id, cid)
    out: list[str] = []
    for value in (machine_id, mid, f"{cid}::{mid}" if cid and mid else ""):
        v = str(value or "").strip()
        if v and v not in out:
            out.append(v)
    return out


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=? LIMIT 1", (table,)
    ).fetchone() is not None


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    if not _table_exists(conn, table):
        return set()
    return {str(r[1]) for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def ensure_catalog_seed(cliente_id: str) -> None:
    cid = str(cliente_id or "").strip()
    if not cid:
        return
    conn = get_db()
    try:
        stamp = now_iso()
        count = conn.execute(
            "SELECT COUNT(1) FROM parada_categorias WHERE cliente_id=?", (cid,)
        ).fetchone()[0]
        if int(count or 0) == 0:
            for name, order in DEFAULT_CATEGORIES:
                conn.execute(
                    """
                    INSERT INTO parada_categorias
                    (cliente_id, nome, slug, ordem, ativo, created_at, updated_at)
                    VALUES (?, ?, ?, ?, 1, ?, ?)
                    """,
                    (cid, name, slugify(name), int(order), stamp, stamp),
                )

        categories = {
            str(r["nome"]).casefold(): int(r["id"])
            for r in conn.execute(
                "SELECT id, nome FROM parada_categorias WHERE cliente_id=?", (cid,)
            ).fetchall()
        }

        reason_count = conn.execute(
            "SELECT COUNT(1) FROM parada_motivos WHERE cliente_id=?", (cid,)
        ).fetchone()[0]
        if int(reason_count or 0) == 0:
            for code, desc, cat_name, kind in DEFAULT_REASONS:
                cat_id = categories.get(cat_name.casefold())
                if not cat_id:
                    continue
                conn.execute(
                    """
                    INSERT INTO parada_motivos
                    (cliente_id, categoria_id, codigo, descricao, tipo, aplica_todas, ativo, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, 1, 1, ?, ?)
                    """,
                    (cid, cat_id, str(code), desc, kind, stamp, stamp),
                )
        conn.commit()
    finally:
        conn.close()


def list_categories(cliente_id: str, include_inactive: bool = False) -> list[dict]:
    cid = str(cliente_id or "").strip()
    ensure_catalog_seed(cid)
    conn = get_db()
    try:
        where = "cliente_id=?"
        params: list[object] = [cid]
        if not include_inactive:
            where += " AND ativo=1"
        rows = conn.execute(
            f"SELECT id, nome, slug, ordem, ativo FROM parada_categorias WHERE {where} ORDER BY ordem, nome COLLATE NOCASE",
            params,
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def list_reasons(
    cliente_id: str,
    machine_id: str | None = None,
    category_id: int | None = None,
    include_inactive: bool = False,
) -> list[dict]:
    cid = str(cliente_id or "").strip()
    ensure_catalog_seed(cid)
    mid = normalize_machine_id(machine_id or "", cid)
    conn = get_db()
    try:
        where = ["m.cliente_id=?"]
        params: list[object] = [cid]
        if not include_inactive:
            where.append("m.ativo=1")
        if category_id:
            where.append("m.categoria_id=?")
            params.append(int(category_id))
        if mid:
            where.append(
                "(m.aplica_todas=1 OR EXISTS (SELECT 1 FROM parada_motivo_maquinas mm WHERE mm.cliente_id=m.cliente_id AND mm.motivo_id=m.id AND lower(mm.machine_id)=lower(?)))"
            )
            params.append(mid)
        sql = f"""
            SELECT m.id, m.categoria_id, c.nome AS categoria_nome,
                   m.codigo, m.descricao, m.tipo, m.aplica_todas, m.ativo,
                   GROUP_CONCAT(mm.machine_id, '||') AS maquinas_csv
            FROM parada_motivos m
            JOIN parada_categorias c ON c.id=m.categoria_id AND c.cliente_id=m.cliente_id
            LEFT JOIN parada_motivo_maquinas mm ON mm.motivo_id=m.id AND mm.cliente_id=m.cliente_id
            WHERE {' AND '.join(where)}
            GROUP BY m.id
            ORDER BY c.ordem, CAST(m.codigo AS INTEGER), m.codigo, m.descricao COLLATE NOCASE
        """
        rows = conn.execute(sql, params).fetchall()
        out = []
        for row in rows:
            item = dict(row)
            item["maquinas"] = [x for x in str(item.pop("maquinas_csv") or "").split("||") if x]
            item["planejada"] = item.get("tipo") == "planejada"
            out.append(item)
        return out
    finally:
        conn.close()


def list_tenant_machines(cliente_id: str, include_test: bool = False) -> list[str]:
    """
    Fonte única das máquinas reais visíveis ao tenant.

    Uma máquina real só pertence à lista quando existe um device:
    - do cliente atual;
    - com MAC válido;
    - com machine_id vinculado.

    Dados históricos, configurações e eventos não recriam máquinas removidas ou
    ainda não vinculadas. Máquinas sintéticas entram somente com include_test=True.
    """
    cid = str(cliente_id or "").strip()
    if not cid:
        return []

    out: set[str] = set()
    conn = get_db()
    try:
        cols = _columns(conn, "devices")
        required = {"device_id", "cliente_id", "machine_id"}
        if required.issubset(cols):
            rows = conn.execute(
                """
                SELECT device_id, machine_id
                FROM devices
                WHERE cliente_id=?
                  AND machine_id IS NOT NULL
                  AND trim(machine_id)<>''
                """,
                (cid,),
            ).fetchall()

            for row in rows:
                if isinstance(row, sqlite3.Row):
                    device_id = str(row["device_id"] or "")
                    machine_id = row["machine_id"]
                else:
                    device_id = str(row[0] or "")
                    machine_id = row[1]

                normalized_mac = device_id.strip().upper().replace(":", "").replace("-", "")
                if not re.fullmatch(r"[0-9A-F]{12}", normalized_mac):
                    continue

                mid = normalize_machine_id(machine_id, cid)
                if mid:
                    out.add(mid)
    finally:
        conn.close()

    if include_test:
        out.update(list_active_test_machines(cid))

    return sorted(out, key=lambda x: x.casefold())


def _meta24_for_day(conn: sqlite3.Connection, cliente_id: str, machine_id: str, day: date) -> list[int] | None:
    eff = _resolve_effective_machine_id(conn, machine_id, day.isoformat(), cliente_id)
    cfg = _load_machine_config_json(conn, machine_id, cliente_id)
    if (not cfg) and eff and eff != machine_id:
        cfg = _load_machine_config_json(conn, eff, cliente_id)
    meta24 = _build_meta_24_from_config_v2(cfg, day)
    if meta24 is None:
        state = None
        if callable(get_machine):
            try:
                try:
                    state = get_machine(machine_id, cliente_id)
                except TypeError:
                    state = get_machine(f"{cliente_id}::{machine_id}")
            except Exception:
                state = None
        meta24 = _build_meta_24_from_machine_state(state)
    if meta24 is None:
        try:
            hor = _fetch_horaria(conn, eff or machine_id, day, cliente_id)
            meta24 = [int(hor.get(h, {}).get("meta", 0) or 0) for h in range(24)]
        except Exception:
            meta24 = None
    return meta24


def _merge_intervals(intervals: list[tuple[datetime, datetime]]) -> list[tuple[datetime, datetime]]:
    if not intervals:
        return []
    items = sorted(intervals, key=lambda x: x[0])
    out: list[tuple[datetime, datetime]] = [items[0]]
    for start, end in items[1:]:
        prev_start, prev_end = out[-1]
        if start <= prev_end + timedelta(seconds=1):
            out[-1] = (prev_start, max(prev_end, end))
        else:
            out.append((start, end))
    return out


def detected_day_state(cliente_id: str, machine_id: str, day: date) -> dict:
    cid = str(cliente_id or "").strip()
    mid = normalize_machine_id(machine_id, cid)
    if not cid or not mid:
        return {"run_sec": 0, "stop_sec": 0, "stops": []}
    if is_test_machine(cid, mid):
        return test_day_state(day)

    conn = get_db()
    try:
        eff = _resolve_effective_machine_id(conn, mid, day.isoformat(), cid)
        day_segments = _fetch_state_segments_from_state_events(
            conn, eff or mid, day, machine_id=mid, cliente_id=cid
        )
        meta24 = _meta24_for_day(conn, cid, mid, day)
        if meta24 is None:
            # Sem configuracao/meta confiavel, preserva a seguranca dos indicadores:
            # nao transforma IDLE/STOP de madrugada em parada produtiva.
            return {"run_sec": 0, "stop_sec": 0, "stops": []}

        now_naive = now_local().replace(tzinfo=None)
        run_sec = 0
        stop_sec = 0
        stops: list[tuple[datetime, datetime]] = []
        for h in range(24):
            hs = datetime(day.year, day.month, day.day, h, 0, 0)
            he = hs + timedelta(hours=1)
            if day == now_naive.date():
                if now_naive <= hs:
                    continue
                he_calc = min(he, now_naive)
            else:
                he_calc = he
            if he_calc <= hs:
                continue
            is_np = int(meta24[h] or 0) <= 0
            segs = _build_segments_for_hour_from_day_segments(hs, he_calc, is_np, day_segments)
            for seg in segs:
                state = str(seg.get("state") or "").upper()
                try:
                    s_parts = [int(x) for x in str(seg.get("start") or "00:00:00").split(":")]
                    e_parts = [int(x) for x in str(seg.get("end") or "00:00:00").split(":")]
                    s = datetime(day.year, day.month, day.day, s_parts[0], s_parts[1], s_parts[2])
                    e = datetime(day.year, day.month, day.day, e_parts[0], e_parts[1], e_parts[2])
                    if e < s:
                        e += timedelta(days=1)
                except Exception:
                    continue
                dur = max(0, int((e - s).total_seconds()))
                if state == "RUN":
                    run_sec += dur
                elif state == "STOP" and dur > 0:
                    stop_sec += dur
                    stops.append((s, e))
        return {"run_sec": run_sec, "stop_sec": stop_sec, "stops": _merge_intervals(stops)}
    finally:
        conn.close()


def _dt_to_ms(dt_naive: datetime) -> int:
    return int(dt_naive.replace(tzinfo=TZ_BAHIA).timestamp() * 1000)


def sync_detected_stops(cliente_id: str, machine_id: str, start_day: date, end_day: date) -> list[dict]:
    cid = str(cliente_id or "").strip()
    mid = normalize_machine_id(machine_id, cid)
    if not cid or not mid:
        return []
    if end_day < start_day:
        start_day, end_day = end_day, start_day
    if (end_day - start_day).days > 62:
        start_day = end_day - timedelta(days=62)

    intervals: list[tuple[datetime, datetime]] = []
    cursor = start_day
    while cursor <= end_day:
        state = detected_day_state(cid, mid, cursor)
        intervals.extend(state.get("stops") or [])
        cursor += timedelta(days=1)
    intervals = _merge_intervals(intervals)

    stamp = now_iso()
    now_ms = int(now_local().timestamp() * 1000)
    occurrence_source = "teste" if is_test_machine(cid, mid) else "telemetria"
    conn = get_db()
    try:
        for start, end in intervals:
            start_ms = _dt_to_ms(start)
            end_ms = _dt_to_ms(end)
            is_open = abs(end_ms - now_ms) <= 5000 and end_day >= now_local().date()
            stored_end = None if is_open else end_ms
            duration = max(0, int(((now_ms if is_open else end_ms) - start_ms) / 1000))
            conn.execute(
                """
                INSERT INTO parada_ocorrencias
                (cliente_id, machine_id, started_at_ms, ended_at_ms, duration_sec, source, status, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(cliente_id, machine_id, started_at_ms) DO UPDATE SET
                    ended_at_ms=excluded.ended_at_ms,
                    duration_sec=excluded.duration_sec,
                    status=excluded.status,
                    updated_at=excluded.updated_at
                """,
                (cid, mid, start_ms, stored_end, duration, occurrence_source, "ABERTA" if is_open else "FECHADA", stamp, stamp),
            )
        conn.commit()
        return list_occurrences(cid, mid, start_day, end_day, sync=False)
    finally:
        conn.close()


def resolve_detected_occurrence(
    cliente_id: str,
    machine_id: str,
    started_at_ms: int,
    ended_at_ms: int | None,
) -> int:
    """Resolve um clique do historico para uma parada realmente detectada.

    O intervalo recebido do navegador pode ser apenas um recorte horario da barra STOP.
    Por seguranca, ele nunca cria uma parada arbitraria: primeiro ressincroniza a telemetria
    e depois procura uma ocorrencia detectada que sobreponha o trecho clicado.
    """
    cid = str(cliente_id or "").strip()
    mid = normalize_machine_id(machine_id, cid)
    try:
        start_ms = int(started_at_ms)
        end_ms = int(ended_at_ms) if ended_at_ms not in (None, "") else start_ms + 1000
    except Exception as exc:
        raise ValueError("Intervalo de parada invalido.") from exc
    if not cid or not mid or start_ms <= 0 or end_ms <= start_ms:
        raise ValueError("Intervalo de parada invalido.")

    start_day = datetime.fromtimestamp(start_ms / 1000, TZ_BAHIA).date()
    end_day = datetime.fromtimestamp((end_ms - 1) / 1000, TZ_BAHIA).date()
    if (end_day - start_day).days > 2:
        raise ValueError("Intervalo de parada muito amplo.")

    sync_detected_stops(cid, mid, start_day, end_day)
    now_ms = int(now_local().timestamp() * 1000)
    occurrence_source = "teste" if is_test_machine(cid, mid) else "telemetria"
    conn = get_db()
    try:
        row = conn.execute(
            """
            SELECT id, started_at_ms, COALESCE(ended_at_ms, ?) AS effective_end
            FROM parada_ocorrencias
            WHERE cliente_id=? AND lower(machine_id)=lower(?)
              AND started_at_ms < ?
              AND COALESCE(ended_at_ms, ?) > ?
              AND source=?
            ORDER BY
              CASE
                WHEN started_at_ms <= ? AND COALESCE(ended_at_ms, ?) >= ? THEN 0
                ELSE 1
              END,
              ABS(started_at_ms - ?)
            LIMIT 1
            """,
            (now_ms, cid, mid, end_ms, now_ms, start_ms, occurrence_source, start_ms, now_ms, end_ms, start_ms),
        ).fetchone()
        if not row:
            raise ValueError("Este trecho nao corresponde a uma parada detectada pela telemetria.")
        return int(row["id"] if isinstance(row, sqlite3.Row) else row[0])
    finally:
        conn.close()

def list_occurrences(
    cliente_id: str,
    machine_id: str | None,
    start_day: date,
    end_day: date,
    sync: bool = True,
    only_unclassified: bool = False,
) -> list[dict]:
    cid = str(cliente_id or "").strip()
    mid = normalize_machine_id(machine_id or "", cid)
    if sync and mid:
        sync_detected_stops(cid, mid, start_day, end_day)
    start_ms = int(datetime(start_day.year, start_day.month, start_day.day, tzinfo=TZ_BAHIA).timestamp() * 1000)
    next_day = end_day + timedelta(days=1)
    end_ms = int(datetime(next_day.year, next_day.month, next_day.day, tzinfo=TZ_BAHIA).timestamp() * 1000)
    conn = get_db()
    try:
        where = ["o.cliente_id=?", "o.started_at_ms < ?", "COALESCE(o.ended_at_ms, ?) > ?"]
        params: list[object] = [cid, end_ms, end_ms, start_ms]
        if mid:
            where.append("lower(o.machine_id)=lower(?)")
            params.append(mid)
        if only_unclassified:
            where.append("o.motivo_id IS NULL")
        rows = conn.execute(
            f"""
            SELECT o.*, c.nome AS categoria_nome,
                   m.codigo AS motivo_codigo, m.descricao AS motivo_descricao, m.tipo AS motivo_tipo
            FROM parada_ocorrencias o
            LEFT JOIN parada_categorias c ON c.id=o.categoria_id AND c.cliente_id=o.cliente_id
            LEFT JOIN parada_motivos m ON m.id=o.motivo_id AND m.cliente_id=o.cliente_id
            WHERE {' AND '.join(where)}
            ORDER BY o.started_at_ms DESC
            """,
            params,
        ).fetchall()
        now_ms = int(now_local().timestamp() * 1000)
        out = []
        for r in rows:
            item = dict(r)
            finish = int(item.get("ended_at_ms") or now_ms)
            start = int(item.get("started_at_ms") or 0)
            item["duration_sec"] = max(0, int((finish - start) / 1000))
            item["classificada"] = bool(item.get("motivo_id"))
            item["planejada"] = item.get("motivo_tipo") == "planejada" if item.get("motivo_id") else None
            out.append(item)
        return out
    finally:
        conn.close()


def classify_occurrence(
    cliente_id: str,
    occurrence_id: int,
    motivo_id: int,
    observacao: str,
    responsavel: str,
    classificado_por: str,
) -> dict:
    cid = str(cliente_id or "").strip()
    conn = get_db()
    try:
        motive = conn.execute(
            """
            SELECT m.id, m.categoria_id, m.codigo, m.descricao, m.tipo
            FROM parada_motivos m
            JOIN parada_categorias c ON c.id=m.categoria_id AND c.cliente_id=m.cliente_id
            WHERE m.id=? AND m.cliente_id=? AND m.ativo=1 AND c.ativo=1
            """,
            (int(motivo_id), cid),
        ).fetchone()
        if not motive:
            raise ValueError("Motivo de parada inválido ou inativo.")
        occ = conn.execute(
            "SELECT id, machine_id FROM parada_ocorrencias WHERE id=? AND cliente_id=?",
            (int(occurrence_id), cid),
        ).fetchone()
        if not occ:
            raise ValueError("Parada não encontrada.")

        # Respeita restricao por maquina, quando o motivo nao se aplica a todas.
        allowed = conn.execute(
            "SELECT aplica_todas FROM parada_motivos WHERE id=? AND cliente_id=?",
            (int(motivo_id), cid),
        ).fetchone()
        if allowed and int(allowed[0] or 0) == 0:
            ok = conn.execute(
                "SELECT 1 FROM parada_motivo_maquinas WHERE cliente_id=? AND motivo_id=? AND lower(machine_id)=lower(?) LIMIT 1",
                (cid, int(motivo_id), normalize_machine_id(occ["machine_id"], cid)),
            ).fetchone()
            if not ok:
                raise ValueError("Este motivo não está habilitado para a máquina selecionada.")

        stamp = now_iso()
        conn.execute(
            """
            UPDATE parada_ocorrencias
            SET categoria_id=?, motivo_id=?, observacao=?, responsavel=?,
                classificado_por=?, classificado_at=?, updated_at=?
            WHERE id=? AND cliente_id=?
            """,
            (
                int(motive["categoria_id"]),
                int(motivo_id),
                str(observacao or "").strip()[:1000],
                str(responsavel or "").strip()[:120],
                str(classificado_por or "").strip()[:180],
                stamp,
                stamp,
                int(occurrence_id),
                cid,
            ),
        )
        conn.commit()
        return {
            "id": int(occurrence_id),
            "categoria_id": int(motive["categoria_id"]),
            "motivo_id": int(motivo_id),
            "codigo": motive["codigo"],
            "descricao": motive["descricao"],
            "tipo": motive["tipo"],
        }
    finally:
        conn.close()


def save_category(cliente_id: str, payload: dict) -> dict:
    cid = str(cliente_id or "").strip()
    name = str(payload.get("nome") or "").strip()[:80]
    if not name:
        raise ValueError("Informe o nome da categoria.")
    cat_id = int(payload.get("id") or 0)
    order = int(payload.get("ordem") or 0)
    active = 1 if bool(payload.get("ativo", True)) else 0
    stamp = now_iso()
    conn = get_db()
    try:
        if cat_id:
            found = conn.execute(
                "SELECT id FROM parada_categorias WHERE id=? AND cliente_id=?", (cat_id, cid)
            ).fetchone()
            if not found:
                raise ValueError("Categoria não encontrada.")
            conn.execute(
                "UPDATE parada_categorias SET nome=?, slug=?, ordem=?, ativo=?, updated_at=? WHERE id=? AND cliente_id=?",
                (name, slugify(name), order, active, stamp, cat_id, cid),
            )
        else:
            conn.execute(
                "INSERT INTO parada_categorias (cliente_id,nome,slug,ordem,ativo,created_at,updated_at) VALUES (?,?,?,?,?,?,?)",
                (cid, name, slugify(name), order, active, stamp, stamp),
            )
            cat_id = int(conn.execute("SELECT last_insert_rowid()").fetchone()[0])
        conn.commit()
        return {"id": cat_id, "nome": name, "ordem": order, "ativo": bool(active)}
    except sqlite3.IntegrityError as exc:
        raise ValueError("Já existe uma categoria com esse nome.") from exc
    finally:
        conn.close()


def save_reason(cliente_id: str, payload: dict) -> dict:
    cid = str(cliente_id or "").strip()
    reason_id = int(payload.get("id") or 0)
    category_id = int(payload.get("categoria_id") or 0)
    code = str(payload.get("codigo") or "").strip()[:30]
    desc = str(payload.get("descricao") or "").strip()[:180]
    kind = str(payload.get("tipo") or "nao_planejada").strip().lower()
    if kind not in ("planejada", "nao_planejada"):
        kind = "nao_planejada"
    if not category_id or not code or not desc:
        raise ValueError("Categoria, código e motivo são obrigatórios.")
    applies_all = 1 if bool(payload.get("aplica_todas", True)) else 0
    active = 1 if bool(payload.get("ativo", True)) else 0
    machines = [normalize_machine_id(x, cid) for x in (payload.get("maquinas") or [])]
    machines = sorted({x for x in machines if x}, key=lambda x: x.casefold())
    if not applies_all and not machines:
        raise ValueError("Selecione ao menos uma máquina ou marque 'Todas as máquinas'.")
    if not applies_all:
        known = {x.casefold() for x in list_tenant_machines(cid)}
        invalid = [x for x in machines if x.casefold() not in known]
        if invalid:
            raise ValueError("Há máquina selecionada que não pertence à empresa atual.")
    stamp = now_iso()
    conn = get_db()
    try:
        cat = conn.execute(
            "SELECT id FROM parada_categorias WHERE id=? AND cliente_id=?", (category_id, cid)
        ).fetchone()
        if not cat:
            raise ValueError("Categoria inválida.")
        if reason_id:
            found = conn.execute(
                "SELECT id FROM parada_motivos WHERE id=? AND cliente_id=?", (reason_id, cid)
            ).fetchone()
            if not found:
                raise ValueError("Motivo não encontrado.")
            conn.execute(
                """
                UPDATE parada_motivos
                SET categoria_id=?, codigo=?, descricao=?, tipo=?, aplica_todas=?, ativo=?, updated_at=?
                WHERE id=? AND cliente_id=?
                """,
                (category_id, code, desc, kind, applies_all, active, stamp, reason_id, cid),
            )
        else:
            conn.execute(
                """
                INSERT INTO parada_motivos
                (cliente_id,categoria_id,codigo,descricao,tipo,aplica_todas,ativo,created_at,updated_at)
                VALUES (?,?,?,?,?,?,?,?,?)
                """,
                (cid, category_id, code, desc, kind, applies_all, active, stamp, stamp),
            )
            reason_id = int(conn.execute("SELECT last_insert_rowid()").fetchone()[0])
        conn.execute(
            "DELETE FROM parada_motivo_maquinas WHERE cliente_id=? AND motivo_id=?", (cid, reason_id)
        )
        if not applies_all:
            for mid in machines:
                conn.execute(
                    "INSERT OR IGNORE INTO parada_motivo_maquinas (cliente_id,motivo_id,machine_id) VALUES (?,?,?)",
                    (cid, reason_id, mid),
                )
        conn.commit()
        return {
            "id": reason_id,
            "categoria_id": category_id,
            "codigo": code,
            "descricao": desc,
            "tipo": kind,
            "aplica_todas": bool(applies_all),
            "ativo": bool(active),
            "maquinas": machines,
        }
    except sqlite3.IntegrityError as exc:
        raise ValueError("Já existe um motivo com esse código para esta empresa.") from exc
    finally:
        conn.close()


def _sum_production(conn: sqlite3.Connection, cliente_id: str, machine_id: str, start_ms: int, end_ms: int) -> int:
    """Soma producao por dia: eventos quando existem; horario como fallback legado.

    Isso evita zerar indicadores historicos de dias anteriores a criacao de
    producao_evento, sem somar as duas fontes no mesmo dia.
    """
    mids = machine_candidates(cliente_id, machine_id)
    if not mids or end_ms <= start_ms:
        return 0

    event_ok = False
    event_cols: set[str] = set()
    if _table_exists(conn, "producao_evento"):
        event_cols = _columns(conn, "producao_evento")
        event_ok = {"cliente_id", "machine_id", "ts_ms", "delta"}.issubset(event_cols)

    hourly_ok = False
    hourly_cols: set[str] = set()
    if _table_exists(conn, "producao_horaria"):
        hourly_cols = _columns(conn, "producao_horaria")
        hourly_ok = {"cliente_id", "machine_id", "data_ref", "produzido"}.issubset(hourly_cols)

    placeholders = ",".join("?" for _ in mids)
    first_day = datetime.fromtimestamp(start_ms / 1000, TZ_BAHIA).date()
    last_day = datetime.fromtimestamp((end_ms - 1) / 1000, TZ_BAHIA).date()
    total = 0
    day = first_day
    while day <= last_day:
        ds = datetime(day.year, day.month, day.day, tzinfo=TZ_BAHIA)
        de = ds + timedelta(days=1)
        day_start = max(start_ms, int(ds.timestamp() * 1000))
        day_end = min(end_ms, int(de.timestamp() * 1000))
        used_events = False

        if event_ok and day_end > day_start:
            row = conn.execute(
                f"SELECT COUNT(1), COALESCE(SUM(delta),0) FROM producao_evento "
                f"WHERE cliente_id=? AND machine_id IN ({placeholders}) AND ts_ms>=? AND ts_ms<?",
                [cliente_id, *mids, day_start, day_end],
            ).fetchone()
            if row and int(row[0] or 0) > 0:
                total += max(0, int(row[1] or 0))
                used_events = True

        if not used_events and hourly_ok:
            row = conn.execute(
                f"SELECT COALESCE(SUM(produzido),0) FROM producao_horaria "
                f"WHERE cliente_id=? AND machine_id IN ({placeholders}) AND data_ref=?",
                [cliente_id, *mids, day.isoformat()],
            ).fetchone()
            total += max(0, int(row[0] or 0)) if row else 0

        day += timedelta(days=1)
    return total

def _sum_refugo(conn: sqlite3.Connection, cliente_id: str, machine_id: str, start_day: date, end_day: date) -> int:
    if not _table_exists(conn, "refugo_horaria"):
        return 0
    cols = _columns(conn, "refugo_horaria")
    if not {"cliente_id", "machine_id", "dia_ref"}.issubset(cols):
        return 0
    mids = machine_candidates(cliente_id, machine_id)
    placeholders = ",".join("?" for _ in mids)
    value_col = "refugo" if "refugo" in cols else ("qtd" if "qtd" in cols else None)
    if not value_col:
        return 0
    row = conn.execute(
        f"SELECT COALESCE(SUM({value_col}),0) FROM refugo_horaria WHERE cliente_id=? AND machine_id IN ({placeholders}) AND dia_ref>=? AND dia_ref<=?",
        [cliente_id, *mids, start_day.isoformat(), end_day.isoformat()],
    ).fetchone()
    return int(row[0] or 0) if row else 0


def _sum_meta(conn: sqlite3.Connection, cliente_id: str, machine_id: str, start_day: date, end_day: date) -> int:
    if not _table_exists(conn, "producao_horaria"):
        return 0
    cols = _columns(conn, "producao_horaria")
    if not {"cliente_id", "machine_id", "data_ref", "meta"}.issubset(cols):
        return 0
    mids = machine_candidates(cliente_id, machine_id)
    placeholders = ",".join("?" for _ in mids)
    row = conn.execute(
        f"SELECT COALESCE(SUM(meta),0) FROM producao_horaria WHERE cliente_id=? AND machine_id IN ({placeholders}) AND data_ref>=? AND data_ref<=?",
        [cliente_id, *mids, start_day.isoformat(), end_day.isoformat()],
    ).fetchone()
    return int(row[0] or 0) if row else 0


def _ideal_sec(conn: sqlite3.Connection, cliente_id: str, machine_id: str, day: date) -> float | None:
    cfg = _load_machine_config_json(conn, machine_id, cliente_id)
    oee = cfg.get("oee") if isinstance(cfg, dict) else None
    if isinstance(oee, dict):
        try:
            value = float(oee.get("ideal_sec_per_piece") or 0)
            if value > 0:
                return value
        except Exception:
            pass
    cv2 = cfg.get("config_v2") if isinstance(cfg, dict) and isinstance(cfg.get("config_v2"), dict) else {}
    oee2 = cv2.get("oee") if isinstance(cv2.get("oee"), dict) else {}
    try:
        value = float(oee2.get("ideal_sec_per_piece") or 0)
        return value if value > 0 else None
    except Exception:
        return None


def machine_indicator_summary(cliente_id: str, machine_id: str, start_day: date, end_day: date) -> dict:
    cid = str(cliente_id or "").strip()
    mid = normalize_machine_id(machine_id, cid)
    run_sec = 0
    stop_sec = 0
    cursor = start_day
    while cursor <= end_day:
        state = detected_day_state(cid, mid, cursor)
        run_sec += int(state.get("run_sec") or 0)
        stop_sec += int(state.get("stop_sec") or 0)
        cursor += timedelta(days=1)

    # Persiste apenas os intervalos derivados do rastro original para classificacao.
    sync_detected_stops(cid, mid, start_day, end_day)
    occurrences = list_occurrences(cid, mid, start_day, end_day, sync=False)
    classified = [o for o in occurrences if o.get("classificada")]
    unclassified = [o for o in occurrences if not o.get("classificada")]

    planned_sec = sum(int(o.get("duration_sec") or 0) for o in classified if o.get("planejada") is True)
    unplanned_sec = sum(int(o.get("duration_sec") or 0) for o in classified if o.get("planejada") is False)
    unclassified_sec = sum(int(o.get("duration_sec") or 0) for o in unclassified)

    start_ms = int(datetime(start_day.year, start_day.month, start_day.day, tzinfo=TZ_BAHIA).timestamp() * 1000)
    next_day = end_day + timedelta(days=1)
    end_ms = int(datetime(next_day.year, next_day.month, next_day.day, tzinfo=TZ_BAHIA).timestamp() * 1000)
    if is_test_machine(cid, mid):
        test_totals = test_period_totals(start_day, end_day)
        production = int(test_totals.get("producao") or 0)
        scrap = int(test_totals.get("refugo") or 0)
        meta = int(test_totals.get("meta") or 0)
        ideal = float(test_totals.get("ideal_sec_per_piece") or 3.0)
    else:
        conn = get_db()
        try:
            production = _sum_production(conn, cid, mid, start_ms, end_ms)
            scrap = _sum_refugo(conn, cid, mid, start_day, end_day)
            meta = _sum_meta(conn, cid, mid, start_day, end_day)
            ideal = _ideal_sec(conn, cid, mid, end_day)
        finally:
            conn.close()

    monitored = run_sec + stop_sec
    availability = (run_sec / monitored) if monitored > 0 else None
    performance = None
    if run_sec > 0 and ideal and ideal > 0:
        performance = min(1.0, max(0.0, (production * ideal) / run_sec))
    quality = None
    if production > 0:
        quality = min(1.0, max(0.0, (production - scrap) / production))
    oee = None
    if availability is not None and performance is not None and quality is not None:
        oee = availability * performance * quality

    category_map: dict[str, dict] = {}
    reason_map: dict[str, dict] = {}
    for occ in classified:
        cat = str(occ.get("categoria_nome") or "Outros")
        cat_item = category_map.setdefault(cat, {"nome": cat, "tempo_sec": 0, "ocorrencias": 0})
        cat_item["tempo_sec"] += int(occ.get("duration_sec") or 0)
        cat_item["ocorrencias"] += 1
        label = f"{occ.get('motivo_codigo') or ''} - {occ.get('motivo_descricao') or ''}".strip(" -")
        r_item = reason_map.setdefault(label, {"nome": label, "tempo_sec": 0, "ocorrencias": 0})
        r_item["tempo_sec"] += int(occ.get("duration_sec") or 0)
        r_item["ocorrencias"] += 1

    stop_count = len(occurrences)
    unplanned_occurrences = [o for o in classified if o.get("planejada") is False]
    unplanned_count = len(unplanned_occurrences)
    # MTTR/MTBF consideram somente ocorrencias classificadas como nao planejadas.
    # Paradas planejadas (DDS, setup etc.) nao devem distorcer confiabilidade.
    mttr = (unplanned_sec / unplanned_count) if unplanned_count > 0 else None
    mtbf = (run_sec / unplanned_count) if unplanned_count > 0 else None
    classified_pct = (len(classified) / stop_count) if stop_count > 0 else 1.0
    achievement = (production / meta) if meta > 0 else None

    return {
        "machine_id": mid,
        "periodo": {"inicio": start_day.isoformat(), "fim": end_day.isoformat()},
        "run_sec": run_sec,
        "stop_sec": stop_sec,
        "monitored_sec": monitored,
        "paradas": stop_count,
        "paradas_classificadas": len(classified),
        "paradas_nao_classificadas": len(unclassified),
        "classificacao_pct": classified_pct,
        "planned_stop_sec": planned_sec,
        "unplanned_stop_sec": unplanned_sec,
        "unclassified_stop_sec": unclassified_sec,
        "availability": availability,
        "performance": performance,
        "quality": quality,
        "oee": oee,
        "mttr_sec": mttr,
        "mtbf_sec": mtbf,
        "producao": production,
        "refugo": scrap,
        "meta": meta,
        "atingimento": achievement,
        "ideal_sec_per_piece": ideal,
        "categorias": sorted(category_map.values(), key=lambda x: x["tempo_sec"], reverse=True),
        "motivos": sorted(reason_map.values(), key=lambda x: x["tempo_sec"], reverse=True),
    }


def general_indicator_summary(cliente_id: str, start_day: date, end_day: date, machines: Iterable[str] | None = None) -> dict:
    cid = str(cliente_id or "").strip()
    machine_list = [normalize_machine_id(x, cid) for x in (machines or list_tenant_machines(cid))]
    machine_list = [x for x in machine_list if x]
    rows = [machine_indicator_summary(cid, mid, start_day, end_day) for mid in machine_list]

    run_sec = sum(int(r["run_sec"] or 0) for r in rows)
    stop_sec = sum(int(r["stop_sec"] or 0) for r in rows)
    production = sum(int(r["producao"] or 0) for r in rows)
    scrap = sum(int(r["refugo"] or 0) for r in rows)
    meta = sum(int(r["meta"] or 0) for r in rows)
    stops = sum(int(r["paradas"] or 0) for r in rows)
    classified = sum(int(r["paradas_classificadas"] or 0) for r in rows)
    monitored = run_sec + stop_sec
    availability = (run_sec / monitored) if monitored > 0 else None

    # Performance geral ponderada por tempo ideal de cada maquina.
    theoretical_sec = 0.0
    for r in rows:
        ideal = r.get("ideal_sec_per_piece")
        if ideal:
            theoretical_sec += float(r.get("producao") or 0) * float(ideal)
    performance = min(1.0, theoretical_sec / run_sec) if run_sec > 0 and theoretical_sec > 0 else None
    quality = min(1.0, max(0.0, (production - scrap) / production)) if production > 0 else None
    oee = availability * performance * quality if None not in (availability, performance, quality) else None

    category_map: dict[str, dict] = {}
    reason_map: dict[str, dict] = {}
    for row in rows:
        for item in row.get("categorias") or []:
            dst = category_map.setdefault(item["nome"], {"nome": item["nome"], "tempo_sec": 0, "ocorrencias": 0})
            dst["tempo_sec"] += int(item.get("tempo_sec") or 0)
            dst["ocorrencias"] += int(item.get("ocorrencias") or 0)
        for item in row.get("motivos") or []:
            dst = reason_map.setdefault(item["nome"], {"nome": item["nome"], "tempo_sec": 0, "ocorrencias": 0})
            dst["tempo_sec"] += int(item.get("tempo_sec") or 0)
            dst["ocorrencias"] += int(item.get("ocorrencias") or 0)

    return {
        "periodo": {"inicio": start_day.isoformat(), "fim": end_day.isoformat()},
        "maquinas": rows,
        "machine_count": len(rows),
        "run_sec": run_sec,
        "stop_sec": stop_sec,
        "paradas": stops,
        "paradas_classificadas": classified,
        "paradas_nao_classificadas": max(0, stops - classified),
        "classificacao_pct": (classified / stops) if stops > 0 else 1.0,
        "availability": availability,
        "performance": performance,
        "quality": quality,
        "oee": oee,
        "producao": production,
        "refugo": scrap,
        "meta": meta,
        "atingimento": (production / meta) if meta > 0 else None,
        "planned_stop_sec": sum(int(r["planned_stop_sec"] or 0) for r in rows),
        "unplanned_stop_sec": sum(int(r["unplanned_stop_sec"] or 0) for r in rows),
        "unclassified_stop_sec": sum(int(r["unclassified_stop_sec"] or 0) for r in rows),
        "categorias": sorted(category_map.values(), key=lambda x: x["tempo_sec"], reverse=True),
        "motivos": sorted(reason_map.values(), key=lambda x: x["tempo_sec"], reverse=True),
    }
