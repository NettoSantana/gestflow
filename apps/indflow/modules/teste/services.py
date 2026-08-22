# Caminho: C:\Users\vlula\OneDrive\Área de Trabalho\Projetos Backup\GESTFLOW\apps\indflow\modules\teste\services.py
# Último recode: 2026-08-21 06:43 (America/Bahia)
# Motivo: Migrar para a estrutura consolidada GESTFLOW + INDFLOW na branch DEV, preservando o conteúdo funcional validado.

from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo
import sqlite3

from modules.db_indflow import get_db

TZ_BAHIA = ZoneInfo("America/Bahia")
TEST_MACHINE_ID = "teste01"
TEST_DAYS = 7

# Cenário diário de 06:00-14:00, com intervalo programado 12:00-13:00.
# A lista é a única fonte sintética usada por Histórico, Paradas e Indicadores.
_TEST_SEGMENTS = {
    6: [("06:00:00", "06:50:00", "RUN"), ("06:50:00", "07:00:00", "STOP")],
    7: [("07:00:00", "07:15:00", "STOP"), ("07:15:00", "08:00:00", "RUN")],
    8: [("08:00:00", "09:00:00", "RUN")],
    9: [("09:00:00", "09:12:00", "STOP"), ("09:12:00", "10:00:00", "RUN")],
    10: [("10:00:00", "10:38:00", "RUN"), ("10:38:00", "10:55:00", "STOP"), ("10:55:00", "11:00:00", "RUN")],
    11: [("11:00:00", "12:00:00", "RUN")],
    12: [("12:00:00", "13:00:00", "NP")],
    13: [("13:00:00", "13:25:00", "RUN"), ("13:25:00", "13:45:00", "STOP"), ("13:45:00", "14:00:00", "RUN")],
}

_TEST_PRODUCTION = {6: 850, 7: 760, 8: 980, 9: 830, 10: 780, 11: 1000, 12: 0, 13: 900}
_TEST_META = {6: 1000, 7: 1000, 8: 1000, 9: 1000, 10: 1000, 11: 1000, 12: 0, 13: 1000}
_TEST_REFUGO = {6: 5, 7: 7, 8: 8, 9: 10, 10: 9, 11: 8, 12: 0, 13: 13}
_TEST_CLASSIFICATIONS = ["103", "112", "116", None]


def _now() -> datetime:
    return datetime.now(TZ_BAHIA)


def _now_iso() -> str:
    return _now().isoformat(timespec="seconds")


def _normalize(machine_id: str | None) -> str:
    value = str(machine_id or "").strip()
    if "::" in value:
        value = value.split("::", 1)[-1]
    return value.casefold()


def _ensure_registry_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS indflow_test_machines (
            cliente_id TEXT NOT NULL,
            machine_id TEXT NOT NULL,
            ativo INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (cliente_id, machine_id)
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS ix_indflow_test_machines_cliente ON indflow_test_machines(cliente_id, ativo)"
    )


def is_test_machine(cliente_id: str, machine_id: str | None) -> bool:
    cid = str(cliente_id or "").strip()
    if not cid or _normalize(machine_id) != TEST_MACHINE_ID:
        return False
    conn = get_db()
    try:
        _ensure_registry_table(conn)
        row = conn.execute(
            "SELECT 1 FROM indflow_test_machines WHERE cliente_id=? AND lower(machine_id)=lower(?) AND ativo=1 LIMIT 1",
            (cid, TEST_MACHINE_ID),
        ).fetchone()
        return bool(row)
    finally:
        conn.close()


def list_active_test_machines(cliente_id: str) -> list[str]:
    cid = str(cliente_id or "").strip()
    if not cid:
        return []
    conn = get_db()
    try:
        _ensure_registry_table(conn)
        rows = conn.execute(
            "SELECT machine_id FROM indflow_test_machines WHERE cliente_id=? AND ativo=1 ORDER BY machine_id",
            (cid,),
        ).fetchall()
        return [str(r[0]).strip() for r in rows if str(r[0] or "").strip()]
    finally:
        conn.close()


def test_default_day() -> date:
    return _now().date() - timedelta(days=1)


def test_period() -> tuple[date, date]:
    end = test_default_day()
    return end - timedelta(days=TEST_DAYS - 1), end


def _time_to_dt(day: date, hhmmss: str) -> datetime:
    hh, mm, ss = [int(x) for x in hhmmss.split(":")]
    return datetime(day.year, day.month, day.day, hh, mm, ss)


def _dt_to_ms(value: datetime) -> int:
    return int(value.replace(tzinfo=TZ_BAHIA).timestamp() * 1000)


def test_hour_segments(day: date, hour: int) -> list[dict]:
    rows = _TEST_SEGMENTS.get(int(hour))
    if rows:
        return [{"start": a, "end": b, "state": state} for a, b, state in rows]
    start = f"{int(hour):02d}:00:00"
    end = f"{(int(hour) + 1) % 24:02d}:00:00"
    return [{"start": start, "end": end, "state": "NP"}]


def test_stops_for_day(day: date) -> list[tuple[datetime, datetime]]:
    # Junta a parada 06:50-07:15, que cruza a virada da hora.
    return [
        (_time_to_dt(day, "06:50:00"), _time_to_dt(day, "07:15:00")),
        (_time_to_dt(day, "09:00:00"), _time_to_dt(day, "09:12:00")),
        (_time_to_dt(day, "10:38:00"), _time_to_dt(day, "10:55:00")),
        (_time_to_dt(day, "13:25:00"), _time_to_dt(day, "13:45:00")),
    ]


def test_day_state(day: date) -> dict:
    stops = test_stops_for_day(day)
    stop_sec = sum(int((end - start).total_seconds()) for start, end in stops)
    # Tempo programado líquido: 7 horas. A pausa 12:00-13:00 é NP e não entra.
    monitored_sec = 7 * 3600
    run_sec = max(0, monitored_sec - stop_sec)
    return {"run_sec": run_sec, "stop_sec": stop_sec, "stops": stops}


def test_day_totals(day: date) -> dict:
    state = test_day_state(day)
    return {
        "machine_id": TEST_MACHINE_ID,
        "data": day.isoformat(),
        "produzido": sum(_TEST_PRODUCTION.values()),
        "pecas_boas": sum(_TEST_PRODUCTION.values()) - sum(_TEST_REFUGO.values()),
        "refugo": sum(_TEST_REFUGO.values()),
        "refugo_total": sum(_TEST_REFUGO.values()),
        "meta": sum(_TEST_META.values()),
        "percentual": int(round((sum(_TEST_PRODUCTION.values()) / max(1, sum(_TEST_META.values()))) * 100)),
        "run_sec": state["run_sec"],
        "stop_sec": state["stop_sec"],
        "ops": [],
    }


def test_period_totals(start_day: date, end_day: date) -> dict:
    if end_day < start_day:
        start_day, end_day = end_day, start_day
    production = scrap = meta = run_sec = stop_sec = 0
    cursor = start_day
    while cursor <= end_day:
        day = test_day_totals(cursor)
        production += int(day["produzido"])
        scrap += int(day["refugo"])
        meta += int(day["meta"])
        run_sec += int(day["run_sec"])
        stop_sec += int(day["stop_sec"])
        cursor += timedelta(days=1)
    return {
        "producao": production,
        "refugo": scrap,
        "meta": meta,
        "run_sec": run_sec,
        "stop_sec": stop_sec,
        "ideal_sec_per_piece": 3.0,
    }


def test_history_rows(limit: int = 30) -> list[dict]:
    days = max(1, min(int(limit or 30), 365))
    end = test_default_day()
    rows = []
    for offset in range(days):
        day = end - timedelta(days=offset)
        rows.append(test_day_totals(day))
    rows.sort(key=lambda x: x["data"], reverse=True)
    return rows


def test_day_detail(day: date) -> dict:
    hours = []
    for hour in range(24):
        segs = test_hour_segments(day, hour)
        run_sec = 0
        stop_sec = 0
        stops = 0
        previous = None
        for seg in segs:
            start = _time_to_dt(day, seg["start"])
            end = _time_to_dt(day, seg["end"])
            if end <= start:
                end += timedelta(days=1)
            dur = max(0, int((end - start).total_seconds()))
            state = seg["state"]
            if state == "RUN":
                run_sec += dur
            elif state == "STOP":
                stop_sec += dur
                if dur > 0 and previous != "STOP":
                    stops += 1
            previous = state
        hours.append(
            {
                "hour": hour,
                "slot": f"{hour:02d}:00-{(hour + 1) % 24:02d}:00",
                "meta": int(_TEST_META.get(hour, 0)),
                "produzido": int(_TEST_PRODUCTION.get(hour, 0)),
                "refugo": int(_TEST_REFUGO.get(hour, 0)),
                "segments": segs,
                "tempo_produzindo_sec": run_sec,
                "tempo_parado_sec": stop_sec,
                "qtd_paradas": stops,
            }
        )
    return {
        "ok": True,
        "machine_id": TEST_MACHINE_ID,
        "effective_machine_id": TEST_MACHINE_ID,
        "date": day.isoformat(),
        "stop_sec": 60,
        "hours": hours,
        "dados_teste": True,
    }


def _reason_map(conn: sqlite3.Connection, cliente_id: str) -> dict[str, tuple[int, int]]:
    rows = conn.execute(
        "SELECT id, categoria_id, codigo FROM parada_motivos WHERE cliente_id=?",
        (cliente_id,),
    ).fetchall()
    return {str(r["codigo"]): (int(r["id"]), int(r["categoria_id"])) for r in rows}


def activate_test_scenario(cliente_id: str) -> dict:
    cid = str(cliente_id or "").strip()
    if not cid:
        raise ValueError("Cliente da sessão não identificado.")

    stamp = _now_iso()
    start_day, end_day = test_period()
    conn = get_db()
    try:
        _ensure_registry_table(conn)
        conn.execute(
            """
            INSERT INTO indflow_test_machines (cliente_id, machine_id, ativo, created_at, updated_at)
            VALUES (?, ?, 1, ?, ?)
            ON CONFLICT(cliente_id, machine_id) DO UPDATE SET ativo=1, updated_at=excluded.updated_at
            """,
            (cid, TEST_MACHINE_ID, stamp, stamp),
        )

        # Recriar significa resetar apenas registros de teste. Nenhuma tabela de
        # produção/telemetria real é tocada.
        conn.execute(
            "DELETE FROM parada_ocorrencias WHERE cliente_id=? AND lower(machine_id)=lower(?) AND source='teste'",
            (cid, TEST_MACHINE_ID),
        )
        reasons = _reason_map(conn, cid)

        cursor = start_day
        while cursor <= end_day:
            for index, (start, end) in enumerate(test_stops_for_day(cursor)):
                start_ms = _dt_to_ms(start)
                end_ms = _dt_to_ms(end)
                duration = int((end - start).total_seconds())
                code = _TEST_CLASSIFICATIONS[index]
                motivo_id = categoria_id = None
                if code and code in reasons:
                    motivo_id, categoria_id = reasons[code]
                conn.execute(
                    """
                    INSERT INTO parada_ocorrencias
                    (cliente_id, machine_id, started_at_ms, ended_at_ms, duration_sec, source, status,
                     categoria_id, motivo_id, observacao, responsavel, classificado_por, classificado_at,
                     created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, 'teste', 'FECHADA', ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        cid,
                        TEST_MACHINE_ID,
                        start_ms,
                        end_ms,
                        duration,
                        categoria_id,
                        motivo_id,
                        "Dado sintético para validação" if motivo_id else None,
                        "TESTE" if motivo_id else None,
                        "sistema_teste" if motivo_id else None,
                        stamp if motivo_id else None,
                        stamp,
                        stamp,
                    ),
                )
            cursor += timedelta(days=1)
        conn.commit()
    finally:
        conn.close()

    return {
        "machine_id": TEST_MACHINE_ID,
        "inicio": start_day.isoformat(),
        "fim": end_day.isoformat(),
        "dias": TEST_DAYS,
        "paradas_por_dia": len(test_stops_for_day(end_day)),
        "mensagem": "TESTE01 criado somente no modo de teste. Telemetria e produção reais não foram alteradas.",
    }


def remove_test_scenario(cliente_id: str) -> dict:
    cid = str(cliente_id or "").strip()
    if not cid:
        raise ValueError("Cliente da sessão não identificado.")
    conn = get_db()
    try:
        _ensure_registry_table(conn)
        deleted_occ = conn.execute(
            "DELETE FROM parada_ocorrencias WHERE cliente_id=? AND lower(machine_id)=lower(?) AND source='teste'",
            (cid, TEST_MACHINE_ID),
        ).rowcount
        deleted_reg = conn.execute(
            "DELETE FROM indflow_test_machines WHERE cliente_id=? AND lower(machine_id)=lower(?)",
            (cid, TEST_MACHINE_ID),
        ).rowcount
        conn.commit()
        return {
            "machine_id": TEST_MACHINE_ID,
            "ocorrencias_removidas": int(deleted_occ or 0),
            "registro_removido": int(deleted_reg or 0),
            "mensagem": "Dados TESTE01 removidos. Nenhum dado real foi alterado.",
        }
    finally:
        conn.close()
