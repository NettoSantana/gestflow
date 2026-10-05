# Caminho: C:\Users\vlula\OneDrive\Área de Trabalho\Projetos Backup\GESTFLOW\apps\indflow\modules\indicadores\routes.py
# Último recode: 2026-10-05 16:49 (America/Bahia)
# Motivo: Disponibilizar dados do card por turno e hora, com OEE existente, ocorrências configuradas e gramatura da OP ativa.

from __future__ import annotations

from datetime import date, datetime, timedelta
from flask import Blueprint, jsonify, render_template, request, session

from modules.db_indflow import get_db
from modules.admin.routes import login_required
from modules.paradas.services import _daily_indicator_row, _ideal_sec, machine_candidates
from modules.producao.historico_routes import (
    _get_columns, _load_machine_config, _parse_hhmm, _planned_intervals_for_day,
    _state_segments_for_day, _operational_segments_for_range, _state_metrics,
    _fetch_horaria, TZ_BAHIA,
)
from modules.paradas.services import general_indicator_summary, list_tenant_machines, machine_indicator_summary, normalize_machine_id, now_local

indicadores_bp = Blueprint("indicadores", __name__, template_folder="templates")


def _cliente_id() -> str:
    return str(session.get("cliente_id") or "").strip()


def _period() -> tuple[date, date]:
    today = now_local().date()
    try:
        end = datetime.strptime(request.args.get("fim") or today.isoformat(), "%Y-%m-%d").date()
    except Exception:
        end = today
    try:
        start = datetime.strptime(request.args.get("inicio") or (end - timedelta(days=6)).isoformat(), "%Y-%m-%d").date()
    except Exception:
        start = end - timedelta(days=6)
    if end < start:
        start, end = end, start
    if (end - start).days > 62:
        start = end - timedelta(days=62)
    return start, end


@indicadores_bp.get("/")
@login_required
def home():
    return render_template("indicadores_home.html")


@indicadores_bp.get("/maquina/<machine_id>")
@login_required
def machine_page(machine_id: str):
    return render_template("indicadores_maquina.html", machine_id=normalize_machine_id(machine_id, _cliente_id()))


@indicadores_bp.get("/api/resumo")
@login_required
def api_general():
    cid = _cliente_id()
    if not cid:
        return jsonify({"ok": False, "error": "Cliente da sessão não identificado."}), 403
    start, end = _period()
    include_test = request.args.get("teste") == "1"
    machines = list_tenant_machines(cid, include_test=include_test)
    data = general_indicator_summary(cid, start, end, machines=machines)
    data["inclui_teste"] = include_test
    return jsonify({"ok": True, "data": data})


@indicadores_bp.get("/api/maquina/<machine_id>")
@login_required
def api_machine(machine_id: str):
    cid = _cliente_id()
    if not cid:
        return jsonify({"ok": False, "error": "Cliente da sessão não identificado."}), 403
    start, end = _period()
    data = machine_indicator_summary(cid, normalize_machine_id(machine_id, cid), start, end)
    return jsonify({"ok": True, "data": data})



def _card_shift_windows(config, reference):
    cv2 = config.get("config_v2", config)
    shifts = cv2.get("shifts") or []
    active_days = {int(v) or 7 for v in cv2.get("active_days") or range(1, 8)}
    windows = []
    for day in (reference.date() - timedelta(days=1), reference.date()):
        if day.isoweekday() not in active_days:
            continue
        anchor = datetime.combine(day, datetime.min.time())
        for shift in shifts:
            start_min, end_min = _parse_hhmm(shift.get("start")), _parse_hhmm(shift.get("end"))
            if start_min is None or end_min is None:
                continue
            if end_min <= start_min:
                end_min += 1440
            start, end = anchor + timedelta(minutes=start_min), anchor + timedelta(minutes=end_min)
            single = {**cv2, "shifts": [shift]}
            planned = []
            for part_day in (day, day + timedelta(days=1)):
                for ps, pe in _planned_intervals_for_day(single, part_day) or []:
                    ps, pe = max(start, ps), min(end, pe)
                    if pe > ps:
                        planned.append((ps, pe))
            windows.append((start, end, shift, planned))
    return windows


def _card_production(conn, cid, mid, start, end):
    if end <= start:
        return 0
    mids = machine_candidates(cid, mid)
    marks = ",".join("?" for _ in mids)
    total = 0
    day = start.date()
    while day <= (end - timedelta(microseconds=1)).date():
        ds = datetime.combine(day, datetime.min.time())
        de = ds + timedelta(days=1)
        left, right = max(start, ds), min(end, de)
        stamp = lambda dt: int(dt.replace(tzinfo=TZ_BAHIA).timestamp() * 1000)
        cols = _get_columns(conn, "producao_evento")
        has_events = False
        if {"cliente_id", "machine_id", "ts_ms", "delta"}.issubset(cols):
            row = conn.execute(
                f"SELECT COUNT(*) FROM producao_evento WHERE cliente_id=? AND lower(machine_id) IN ({marks}) AND ts_ms>=? AND ts_ms<?",
                [cid, *(v.lower() for v in mids), stamp(ds), stamp(de)],
            ).fetchone()
            has_events = bool(row[0])
        if has_events:
            row = conn.execute(
                f"SELECT COALESCE(SUM(delta),0) FROM producao_evento WHERE cliente_id=? AND lower(machine_id) IN ({marks}) AND ts_ms>=? AND ts_ms<?",
                [cid, *(v.lower() for v in mids), stamp(left), stamp(right)],
            ).fetchone()
            total += max(0, int(row[0]))
        else:
            # O legado só tem totais por hora: não inventa um recorte de minutos.
            if left.minute or left.second or left.microsecond:
                return None
            hourly = _fetch_horaria(conn, mid, day, cid)
            for hour, values in hourly.items():
                hs = ds + timedelta(hours=int(hour))
                if left <= hs < right:
                    total += max(0, int(values.get("produzido") or 0))
        day += timedelta(days=1)
    return total


def _card_quality(conn, cid, mid, start, end, types):
    totals = {item["id"]: 0 for item in types if item["ativo"]}
    discount = 0
    cols = _get_columns(conn, "operacao_ocorrencia_registros")
    if {"cliente_id", "machine_id", "created_at", "tipo_id", "quantidade", "desconta_producao"}.issubset(cols):
        adjusted = bool(_get_columns(conn, "operacao_ocorrencia_ajustes"))
        quantity = "COALESCE(a.quantidade,r.quantidade)" if adjusted else "r.quantidade"
        join = "LEFT JOIN operacao_ocorrencia_ajustes a USING (cliente_id,machine_id,request_id,tipo_id)" if adjusted else ""
        active = "AND COALESCE(a.excluido,0)=0" if adjusted else ""
        rows = conn.execute(
            f"SELECT r.tipo_id, r.created_at, r.desconta_producao, {quantity} AS quantidade FROM operacao_ocorrencia_registros r {join} "
            f"WHERE r.cliente_id=? AND lower(r.machine_id)=lower(?) AND r.data_ref>=? AND r.data_ref<=? {active}",
            (cid, mid, start.date().isoformat(), end.date().isoformat()),
        ).fetchall()
        for row in rows:
            try:
                received = datetime.fromisoformat(str(row["created_at"]).replace("Z", "+00:00"))
                if received.tzinfo:
                    received = received.astimezone(TZ_BAHIA).replace(tzinfo=None)
            except (ValueError, TypeError):
                continue
            if start <= received < end:
                amount = max(0, int(row["quantidade"] or 0))
                if row["tipo_id"] in totals:
                    totals[row["tipo_id"]] += amount
                if row["desconta_producao"]:
                    discount += amount
    legacy = 0
    if {"cliente_id", "machine_id", "dia_ref", "hora_dia", "refugo"}.issubset(_get_columns(conn, "refugo_horaria")):
        mids = machine_candidates(cid, mid)
        marks = ",".join("?" for _ in mids)
        rows = conn.execute(
            f"SELECT dia_ref,hora_dia,refugo FROM refugo_horaria WHERE cliente_id=? AND lower(machine_id) IN ({marks}) AND dia_ref>=? AND dia_ref<=?",
            [cid, *(v.lower() for v in mids), start.date().isoformat(), end.date().isoformat()],
        ).fetchall()
        for row in rows:
            hs = datetime.fromisoformat(row["dia_ref"]) + timedelta(hours=int(row["hora_dia"]))
            if max(start, hs) < min(end, hs + timedelta(hours=1)):
                legacy += max(0, int(row["refugo"] or 0))
    items = [{"nome": item["nome"], "quantidade": totals[item["id"]]} for item in types if item["ativo"]]
    if legacy:
        scrap = next((item for item in items if item["nome"].strip().casefold() in {"refugo", "refugos"}), None)
        if scrap is None:
            items.append({"nome": "Refugo (horário)", "quantidade": legacy})
        else:
            scrap["quantidade"] += legacy
    return items, discount + legacy


def _card_period_summary(conn, cid, mid, config, windows, types, start, end, reference, label):
    elapsed_end = min(end, reference + timedelta(milliseconds=1))
    effective = []
    day = start.date()
    while day <= (end - timedelta(microseconds=1)).date():
        ds = datetime.combine(day, datetime.min.time())
        left, right = max(start, ds), min(elapsed_end, ds + timedelta(days=1))
        if right > left:
            effective.extend(_operational_segments_for_range(
                _state_segments_for_day(conn, cid, mid, day),
                _planned_intervals_for_day(config, day), left, right,
            ))
        day += timedelta(days=1)
    metrics = _state_metrics(effective)
    production = _card_production(conn, cid, mid, start, elapsed_end)
    quality, discount = _card_quality(conn, cid, mid, start, elapsed_end, types)
    goal = 0.0
    for _, _, shift, planned in windows:
        duration = sum((pe - ps).total_seconds() for ps, pe in planned)
        inside = sum(max(0, (min(end, pe) - max(start, ps)).total_seconds()) for ps, pe in planned)
        if duration > 0:
            goal += float(shift.get("meta_pcs") or 0) * inside / duration
    values = _daily_indicator_row(start.date(), metrics["tempo_produzindo_sec"], metrics["tempo_parado_sec"],
                                  production or 0, discount, round(goal), _ideal_sec(conn, cid, mid, start.date()))
    return {"label": label, "inicio": start.replace(tzinfo=TZ_BAHIA).isoformat(),
            "fim": end.replace(tzinfo=TZ_BAHIA).isoformat(), "meta": round(goal),
            "producao": production, "oee": values["oee"], "ocorrencias": quality,
            "paradas": metrics["paradas"]}


@indicadores_bp.get("/api/card/<machine_id>")
@login_required
def api_card(machine_id):
    cid = _cliente_id()
    if not cid:
        return jsonify({"ok": False, "error": "Cliente da sessão não identificado."}), 403
    mid = normalize_machine_id(machine_id, cid)
    if mid not in list_tenant_machines(cid):
        return jsonify({"ok": False, "error": "Máquina não vinculada à empresa atual."}), 404
    reference = now_local().replace(tzinfo=None)
    conn = get_db()
    try:
        config = _load_machine_config(conn, cid, mid)
        cv2 = config.get("config_v2", config)
        windows = _card_shift_windows(config, reference)
        eligible = [window for window in windows if window[0] <= reference]
        active = [window for window in eligible if reference < window[1]]
        chosen = max(active or eligible, key=lambda window: window[0]) if eligible else None
        day_start = reference.replace(hour=0, minute=0, second=0, microsecond=0)
        start, end, label = day_start, day_start + timedelta(days=1), "Dia"
        if chosen:
            start, end = chosen[:2]
            label = "Turno " + str(chosen[2].get("name") or "").strip()
        types = []
        if _get_columns(conn, "operacao_ocorrencia_tipos"):
            types = [dict(row) for row in conn.execute(
                "SELECT id,nome,ativo FROM operacao_ocorrencia_tipos WHERE cliente_id=? AND lower(machine_id)=lower(?) ORDER BY ordem,created_at,id",
                (cid, mid),
            ).fetchall()]
        gram = ""
        if {"cliente_id", "machine_id", "status", "gr_fio"}.issubset(_get_columns(conn, "ordens_producao")):
            mids = machine_candidates(cid, mid)
            marks = ",".join("?" for _ in mids)
            row = conn.execute(
                f"SELECT gr_fio FROM ordens_producao WHERE cliente_id=? AND lower(machine_id) IN ({marks}) AND status='ATIVA' ORDER BY id DESC LIMIT 1",
                [cid, *(v.lower() for v in mids)],
            ).fetchone()
            gram = str(row[0] or "").strip() if row else ""
        main = _card_period_summary(conn, cid, mid, config, windows, types, start, end, reference, label)
        hour = None
        if cv2.get("show_hour_tracking") is not False:
            hs = reference.replace(minute=0, second=0, microsecond=0)
            hour = _card_period_summary(conn, cid, mid, config, windows, types, hs, hs + timedelta(hours=1), reference, "Hora atual")
        response = jsonify({"ok": True, "data": {"gramatura": gram, "turno": main, "hora": hour}})
        response.headers["Cache-Control"] = "no-store"
        return response
    finally:
        conn.close()
