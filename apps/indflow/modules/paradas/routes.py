# Caminho: C:\Users\vlula\OneDrive\Área de Trabalho\Projetos Backup\GESTFLOW\apps\indflow\modules\paradas\routes.py
# Último recode: 2026-09-01 11:48 (America/Bahia)
# Motivo: Agrupar pequenas paradas abaixo do limite configurado e impedir classificação antes do tempo mínimo.

from __future__ import annotations

from datetime import date, datetime, timedelta
from flask import Blueprint, jsonify, render_template, request, session

from modules.admin.routes import admin_required, login_required
from modules.db_indflow import get_db
from modules.paradas.services import (
    classify_occurrence,
    ensure_catalog_seed,
    list_categories,
    list_occurrences,
    list_reasons,
    list_tenant_machines,
    normalize_machine_id,
    now_local,
    save_category,
    save_reason,
    sync_detected_stops,
    resolve_detected_occurrence,
)

paradas_bp = Blueprint("paradas", __name__, template_folder="templates")

DEFAULT_CLASSIFICATION_THRESHOLD_SEC = 180


def _classification_threshold_sec(cliente_id: str, machine_id: str) -> int:
    cid = str(cliente_id or "").strip()
    mid = normalize_machine_id(machine_id, cid)
    if not cid or not mid:
        return DEFAULT_CLASSIFICATION_THRESHOLD_SEC

    conn = get_db()
    try:
        exists = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='operacao_parada_config' LIMIT 1"
        ).fetchone()
        if not exists:
            return DEFAULT_CLASSIFICATION_THRESHOLD_SEC

        row = conn.execute(
            """
            SELECT tempo_obrigatorio_min
            FROM operacao_parada_config
            WHERE cliente_id=? AND lower(machine_id)=lower(?)
            LIMIT 1
            """,
            (cid, mid),
        ).fetchone()
        if not row:
            return DEFAULT_CLASSIFICATION_THRESHOLD_SEC

        try:
            minutes = int(row[0] or 0)
        except Exception:
            minutes = 0
        if minutes <= 0:
            return DEFAULT_CLASSIFICATION_THRESHOLD_SEC
        return max(60, min(7200, minutes * 60))
    finally:
        conn.close()


def _prepare_occurrences(cliente_id: str, rows: list[dict], only_unclassified: bool = False) -> dict:
    cid = str(cliente_id or "").strip()
    threshold_cache: dict[str, int] = {}
    regular_rows: list[dict] = []
    small_by_machine: dict[str, dict] = {}

    total_duration_sec = 0
    visible_duration_sec = 0
    classifiable_total = 0
    classifiable_unclassified = 0
    classifiable_classified = 0

    for source in rows:
        row = dict(source)
        mid = normalize_machine_id(row.get("machine_id") or "", cid)
        row["machine_id"] = mid or str(row.get("machine_id") or "")
        key = (mid or "").casefold()

        if key not in threshold_cache:
            threshold_cache[key] = _classification_threshold_sec(cid, mid)
        threshold_sec = int(threshold_cache[key])

        duration_sec = max(0, int(row.get("duration_sec") or 0))
        total_duration_sec += duration_sec
        is_closed = row.get("ended_at_ms") not in (None, "")
        is_small = bool(is_closed and duration_sec < threshold_sec)
        classified = bool(row.get("classificada"))
        can_classify = bool(duration_sec >= threshold_sec)

        row["classification_threshold_sec"] = threshold_sec
        row["small_stop"] = is_small
        row["can_classify"] = can_classify

        if is_small:
            if not only_unclassified:
                group = small_by_machine.setdefault(
                    key,
                    {
                        "machine_id": mid,
                        "count": 0,
                        "duration_sec": 0,
                        "first_started_at_ms": None,
                        "last_started_at_ms": None,
                        "classification_threshold_sec": threshold_sec,
                    },
                )
                started_at_ms = int(row.get("started_at_ms") or 0)
                group["count"] += 1
                group["duration_sec"] += duration_sec
                if group["first_started_at_ms"] is None or started_at_ms < group["first_started_at_ms"]:
                    group["first_started_at_ms"] = started_at_ms
                if group["last_started_at_ms"] is None or started_at_ms > group["last_started_at_ms"]:
                    group["last_started_at_ms"] = started_at_ms
            continue

        if can_classify:
            classifiable_total += 1
            if classified:
                classifiable_classified += 1
            else:
                classifiable_unclassified += 1

        if only_unclassified and (classified or not can_classify):
            continue

        regular_rows.append(row)
        visible_duration_sec += duration_sec

    small_stops = sorted(
        small_by_machine.values(),
        key=lambda item: int(item.get("last_started_at_ms") or 0),
        reverse=True,
    )
    small_stop_count = sum(int(item.get("count") or 0) for item in small_stops)
    small_stop_duration_sec = sum(int(item.get("duration_sec") or 0) for item in small_stops)

    classified_pct = (
        round((classifiable_classified / classifiable_total) * 100)
        if classifiable_total > 0
        else 100
    )

    return {
        "rows": regular_rows,
        "small_stops": small_stops,
        "stats": {
            "detected_count": len(regular_rows) if only_unclassified else len(rows),
            "unclassified_count": classifiable_unclassified,
            "duration_sec": visible_duration_sec if only_unclassified else total_duration_sec,
            "classified_pct": classified_pct,
            "classifiable_count": classifiable_total,
            "small_stop_count": small_stop_count,
            "small_stop_duration_sec": small_stop_duration_sec,
        },
    }


def _cliente_id() -> str:
    return str(session.get("cliente_id") or "").strip()


def _parse_day(value: str | None, fallback: date) -> date:
    try:
        return datetime.strptime(str(value or ""), "%Y-%m-%d").date()
    except Exception:
        return fallback


def _period_from_request(default_days: int = 1) -> tuple[date, date]:
    today = now_local().date()
    end = _parse_day(request.args.get("fim") or request.args.get("date"), today)
    start = _parse_day(request.args.get("inicio"), end - timedelta(days=max(0, default_days - 1)))
    if end < start:
        start, end = end, start
    if (end - start).days > 62:
        start = end - timedelta(days=62)
    return start, end


@paradas_bp.get("/")
@login_required
def home():
    cid = _cliente_id()
    ensure_catalog_seed(cid)
    return render_template("paradas_home.html")


@paradas_bp.get("/catalogo")
@admin_required
def catalogo_page():
    cid = _cliente_id()
    ensure_catalog_seed(cid)
    return render_template("paradas_catalogo.html")


@paradas_bp.get("/api/contexto")
@login_required
def api_contexto():
    cid = _cliente_id()
    if not cid:
        return jsonify({"ok": False, "error": "Cliente da sessão não identificado."}), 403
    ensure_catalog_seed(cid)
    include_test = request.args.get("teste") == "1"
    return jsonify(
        {
            "ok": True,
            "machines": list_tenant_machines(cid, include_test=include_test),
            "categories": list_categories(cid),
            "reasons": list_reasons(cid),
        }
    )


@paradas_bp.get("/api/catalogo")
@login_required
def api_catalogo():
    cid = _cliente_id()
    if not cid:
        return jsonify({"ok": False, "error": "Cliente da sessão não identificado."}), 403
    machine_id = normalize_machine_id(request.args.get("machine_id") or "", cid)
    category_id = request.args.get("categoria_id")
    try:
        category_id_int = int(category_id) if category_id else None
    except Exception:
        category_id_int = None
    return jsonify(
        {
            "ok": True,
            "categories": list_categories(cid, include_inactive=request.args.get("todos") == "1"),
            "reasons": list_reasons(
                cid,
                machine_id=machine_id or None,
                category_id=category_id_int,
                include_inactive=request.args.get("todos") == "1",
            ),
            "machines": list_tenant_machines(cid, include_test=request.args.get("teste") == "1"),
        }
    )


@paradas_bp.post("/api/categorias")
@admin_required
def api_save_category():
    cid = _cliente_id()
    try:
        result = save_category(cid, request.get_json(silent=True) or {})
        return jsonify({"ok": True, "categoria": result})
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400


@paradas_bp.post("/api/motivos")
@admin_required
def api_save_reason():
    cid = _cliente_id()
    try:
        result = save_reason(cid, request.get_json(silent=True) or {})
        return jsonify({"ok": True, "motivo": result})
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400


@paradas_bp.get("/api/ocorrencias")
@login_required
def api_occurrences():
    cid = _cliente_id()
    if not cid:
        return jsonify({"ok": False, "error": "Cliente da sessão não identificado."}), 403
    start, end = _period_from_request(default_days=1)
    machine_id = normalize_machine_id(request.args.get("machine_id") or "", cid)
    only_unclassified = request.args.get("nao_classificadas") == "1"

    if machine_id:
        sync_detected_stops(cid, machine_id, start, end)
        rows = list_occurrences(cid, machine_id, start, end, sync=False, only_unclassified=only_unclassified)
    else:
        rows = []
        for mid in list_tenant_machines(cid, include_test=request.args.get("teste") == "1")[:50]:
            sync_detected_stops(cid, mid, start, end)
            rows.extend(list_occurrences(cid, mid, start, end, sync=False, only_unclassified=only_unclassified))
        rows.sort(key=lambda x: int(x.get("started_at_ms") or 0), reverse=True)

    prepared = _prepare_occurrences(cid, rows, only_unclassified=only_unclassified)
    return jsonify(
        {
            "ok": True,
            "inicio": start.isoformat(),
            "fim": end.isoformat(),
            "rows": prepared["rows"],
            "small_stops": prepared["small_stops"],
            "stats": prepared["stats"],
        }
    )


@paradas_bp.post("/api/ocorrencias/garantir")
@login_required
def api_ensure_occurrence():
    cid = _cliente_id()
    payload = request.get_json(silent=True) or {}
    machine_id = normalize_machine_id(payload.get("machine_id") or "", cid)
    try:
        start_ms = int(payload.get("started_at_ms"))
        end_raw = payload.get("ended_at_ms")
        end_ms = int(end_raw) if end_raw not in (None, "") else None
    except Exception:
        return jsonify({"ok": False, "error": "Intervalo de parada inválido."}), 400
    if not machine_id or start_ms <= 0:
        return jsonify({"ok": False, "error": "Máquina e início são obrigatórios."}), 400
    try:
        occurrence_id = resolve_detected_occurrence(cid, machine_id, start_ms, end_ms)
        return jsonify({"ok": True, "id": occurrence_id})
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400


@paradas_bp.post("/api/ocorrencias/classificar")
@login_required
def api_classify_occurrence():
    cid = _cliente_id()
    payload = request.get_json(silent=True) or {}
    try:
        occurrence_id = int(payload.get("id") or 0)
        motivo_id = int(payload.get("motivo_id") or 0)
    except Exception:
        occurrence_id = 0
        motivo_id = 0
    if occurrence_id <= 0 or motivo_id <= 0:
        return jsonify({"ok": False, "error": "Parada e motivo são obrigatórios."}), 400

    conn = get_db()
    try:
        occurrence = conn.execute(
            """
            SELECT machine_id, started_at_ms, ended_at_ms
            FROM parada_ocorrencias
            WHERE id=? AND cliente_id=?
            LIMIT 1
            """,
            (occurrence_id, cid),
        ).fetchone()
    finally:
        conn.close()

    if not occurrence:
        return jsonify({"ok": False, "error": "Parada não encontrada."}), 400

    machine_id = normalize_machine_id(occurrence["machine_id"], cid)
    threshold_sec = _classification_threshold_sec(cid, machine_id)
    finish_ms = (
        int(occurrence["ended_at_ms"])
        if occurrence["ended_at_ms"] not in (None, "")
        else int(now_local().timestamp() * 1000)
    )
    duration_sec = max(0, int((finish_ms - int(occurrence["started_at_ms"] or 0)) / 1000))
    if duration_sec < threshold_sec:
        threshold_min = max(1, int(threshold_sec / 60))
        return (
            jsonify(
                {
                    "ok": False,
                    "error": f"Pequenas paradas abaixo de {threshold_min} min não exigem classificação.",
                }
            ),
            400,
        )

    try:
        result = classify_occurrence(
            cid,
            occurrence_id,
            motivo_id,
            str(payload.get("observacao") or ""),
            str(payload.get("responsavel") or ""),
            str(session.get("email") or session.get("user_id") or ""),
        )
        return jsonify({"ok": True, "classificacao": result})
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
