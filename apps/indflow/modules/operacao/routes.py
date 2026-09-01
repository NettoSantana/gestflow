# Caminho: C:\Users\vlula\OneDrive\Área de Trabalho\Projetos Backup\GESTFLOW\apps\indflow\modules\operacao\routes.py
# Último recode: 2026-09-01 18:38 (America/Bahia)
# Motivo: Exigir sessão SSO do GestFlow também na Tela Operacional e impedir PIN/QR de criar acesso independente ao IndFlow.

from __future__ import annotations

from datetime import datetime
import hashlib
import io
import re
import time
import uuid

from flask import Blueprint, Response, current_app, jsonify, redirect, render_template, request, session, url_for
from itsdangerous import BadSignature, URLSafeSerializer
import qrcode
import qrcode.image.svg
from werkzeug.security import check_password_hash, generate_password_hash

from modules.admin.routes import _gestflow_base_url, _is_gestflow_session, admin_required, login_required
from modules.db_indflow import get_db
from modules.paradas.services import normalize_machine_id
from modules.operacao.services import (
    classify_pending_occurrence,
    get_operational_config,
    get_operational_state,
    list_operational_machines,
    list_operational_reasons,
    save_operational_config,
)

operacao_bp = Blueprint("operacao", __name__, template_folder="templates")

MAX_OPERATORS_PER_MACHINE = 3
OPERATOR_ACCESS_SALT = "indflow-operator-access-v1"


def _cliente_id() -> str:
    return str(session.get("cliente_id") or "").strip()


def _role() -> str:
    return str(session.get("role") or "").strip().lower()


def _is_operator_session() -> bool:
    return _role() == "operator" and bool(session.get("operator_id"))


def _is_superadmin_session() -> bool:
    return _role() == "superadmin"


def _now_iso() -> str:
    return datetime.utcnow().isoformat()


def _ensure_operator_tables() -> None:
    conn = get_db()
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS operadores (
                id TEXT PRIMARY KEY,
                cliente_id TEXT NOT NULL,
                nome TEXT NOT NULL,
                pin_lookup TEXT NOT NULL,
                pin_hash TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'active',
                active_machine_id TEXT,
                last_login_at TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS operador_maquinas (
                operador_id TEXT NOT NULL,
                cliente_id TEXT NOT NULL,
                machine_id TEXT NOT NULL,
                created_at TEXT NOT NULL,
                PRIMARY KEY (operador_id, machine_id)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS operador_pin_tentativas (
                cliente_id TEXT NOT NULL,
                client_key TEXT NOT NULL,
                fail_count INTEGER NOT NULL DEFAULT 0,
                blocked_until INTEGER NOT NULL DEFAULT 0,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (cliente_id, client_key)
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS ix_operadores_cliente_status "
            "ON operadores(cliente_id, status)"
        )
        conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS ux_operadores_cliente_pin_lookup "
            "ON operadores(cliente_id, pin_lookup)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS ix_operador_maquinas_cliente_machine "
            "ON operador_maquinas(cliente_id, machine_id)"
        )
        conn.commit()
    finally:
        conn.close()


def _operator_serializer() -> URLSafeSerializer:
    secret = str(current_app.config.get("SECRET_KEY") or "").strip()
    if not secret:
        raise RuntimeError("SECRET_KEY não configurada.")
    return URLSafeSerializer(secret_key=secret, salt=OPERATOR_ACCESS_SALT)


def _canonical_operator_machine(cliente_id: str, machine_id: str) -> str:
    cid = str(cliente_id or "").strip()
    mid = normalize_machine_id(machine_id or "", cid)
    if not cid or not mid:
        raise ValueError("Máquina não identificada.")
    known = {m.casefold(): m for m in list_operational_machines(cid)}
    if mid.casefold() not in known:
        raise ValueError("Máquina não pertence à empresa atual.")
    return known[mid.casefold()]


def _operator_access_token(cliente_id: str, machine_id: str = "") -> str:
    cid = str(cliente_id or "").strip()
    if not cid:
        raise ValueError("Cliente não identificado.")
    payload: dict[str, object] = {"cliente_id": cid, "v": 1}
    if str(machine_id or "").strip():
        payload["machine_id"] = _canonical_operator_machine(cid, machine_id)
        payload["v"] = 2
    return _operator_serializer().dumps(payload)


def _operator_access_context(token: str) -> tuple[str, str]:
    try:
        data = _operator_serializer().loads(str(token or "").strip())
    except BadSignature as exc:
        raise ValueError("Link de acesso do operador inválido.") from exc
    if not isinstance(data, dict) or data.get("v") not in (1, 2):
        raise ValueError("Link de acesso do operador inválido.")
    cid = str(data.get("cliente_id") or "").strip()
    if not cid:
        raise ValueError("Cliente não identificado.")
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT id FROM clientes WHERE id=? AND status='active' LIMIT 1",
            (cid,),
        ).fetchone()
    finally:
        conn.close()
    if not row:
        raise ValueError("Empresa não está ativa no IndFlow.")

    machine_id = ""
    if data.get("v") == 2:
        machine_id = _canonical_operator_machine(cid, str(data.get("machine_id") or ""))
    return cid, machine_id


def _operator_admin_cliente_id() -> str:
    if _is_superadmin_session():
        requested = str(
            request.values.get("cliente_id")
            or request.args.get("cliente_id")
            or session.get("cliente_id")
            or ""
        ).strip()
        if requested:
            return requested
    return _cliente_id()


def _list_clientes_admin() -> list[dict]:
    if not _is_superadmin_session():
        return []
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT id, nome, status FROM clientes ORDER BY nome COLLATE NOCASE"
        ).fetchall()
    finally:
        conn.close()
    return [
        {"id": str(r["id"]), "nome": str(r["nome"] or ""), "status": str(r["status"] or "")}
        for r in rows
    ]


def _list_operator_machines(cliente_id: str, operator_id: str) -> list[str]:
    _ensure_operator_tables()
    cid = str(cliente_id or "").strip()
    oid = str(operator_id or "").strip()
    if not cid or not oid:
        return []
    conn = get_db()
    try:
        rows = conn.execute(
            """
            SELECT machine_id
            FROM operador_maquinas
            WHERE cliente_id=? AND operador_id=?
            ORDER BY lower(machine_id)
            """,
            (cid, oid),
        ).fetchall()
    finally:
        conn.close()
    linked = [normalize_machine_id(r["machine_id"] or "", cid) for r in rows]
    known = {m.casefold(): m for m in list_operational_machines(cid)}
    out: list[str] = []
    for mid in linked:
        if mid and mid.casefold() in known and known[mid.casefold()] not in out:
            out.append(known[mid.casefold()])
    return out


def _operator_record(operator_id: str):
    _ensure_operator_tables()
    oid = str(operator_id or "").strip()
    if not oid:
        return None
    conn = get_db()
    try:
        row = conn.execute(
            """
            SELECT id, cliente_id, nome, pin_hash, status, active_machine_id,
                   last_login_at, created_at, updated_at
            FROM operadores
            WHERE id=?
            LIMIT 1
            """,
            (oid,),
        ).fetchone()
    finally:
        conn.close()
    return dict(row) if row else None


def _operator_session_record():
    if not _is_operator_session():
        return None
    row = _operator_record(str(session.get("operator_id") or ""))
    if not row:
        return None
    if str(row.get("status") or "").lower() != "active":
        return None
    if str(row.get("cliente_id") or "") != _cliente_id():
        return None
    return row


def _operator_actor() -> str:
    if _is_operator_session():
        return f"OPERADOR: {str(session.get('operator_name') or '').strip()}"
    return str(session.get("email") or session.get("user_id") or "")


def _operator_pin_ok(pin: str) -> bool:
    return bool(re.fullmatch(r"\d{4}", str(pin or "").strip()))


def _pin_lookup(cliente_id: str, pin: str) -> str:
    secret = str(current_app.config.get("SECRET_KEY") or "")
    cid = str(cliente_id or "").strip()
    value = str(pin or "").strip()
    return hashlib.sha256(f"{secret}|{cid}|{value}".encode("utf-8")).hexdigest()


def _pin_guard_key() -> str:
    secret = str(current_app.config.get("SECRET_KEY") or "")
    remote = str(request.remote_addr or "")
    agent = str(request.headers.get("User-Agent") or "")[:256]
    return hashlib.sha256(f"{secret}|{remote}|{agent}".encode("utf-8")).hexdigest()


def _pin_guard_remaining(cliente_id: str) -> int:
    _ensure_operator_tables()
    cid = str(cliente_id or "").strip()
    key = _pin_guard_key()
    conn = get_db()
    try:
        row = conn.execute(
            """
            SELECT blocked_until
            FROM operador_pin_tentativas
            WHERE cliente_id=? AND client_key=?
            LIMIT 1
            """,
            (cid, key),
        ).fetchone()
    finally:
        conn.close()
    blocked_until = int(row["blocked_until"] or 0) if row else 0
    return max(0, blocked_until - int(time.time()))


def _pin_guard_fail(cliente_id: str) -> None:
    _ensure_operator_tables()
    cid = str(cliente_id or "").strip()
    key = _pin_guard_key()
    now_epoch = int(time.time())
    now_iso = _now_iso()
    conn = get_db()
    try:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            """
            SELECT fail_count, blocked_until
            FROM operador_pin_tentativas
            WHERE cliente_id=? AND client_key=?
            LIMIT 1
            """,
            (cid, key),
        ).fetchone()
        fail_count = int(row["fail_count"] or 0) if row else 0
        blocked_until = int(row["blocked_until"] or 0) if row else 0
        if blocked_until > now_epoch:
            conn.commit()
            return
        fail_count += 1
        if fail_count >= 5:
            blocked_until = now_epoch + 300
            fail_count = 0
        conn.execute(
            """
            INSERT INTO operador_pin_tentativas
                (cliente_id, client_key, fail_count, blocked_until, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(cliente_id, client_key) DO UPDATE SET
                fail_count=excluded.fail_count,
                blocked_until=excluded.blocked_until,
                updated_at=excluded.updated_at
            """,
            (cid, key, fail_count, blocked_until, now_iso),
        )
        conn.commit()
    except Exception:
        conn.rollback()
    finally:
        conn.close()


def _pin_guard_clear(cliente_id: str) -> None:
    _ensure_operator_tables()
    cid = str(cliente_id or "").strip()
    key = _pin_guard_key()
    conn = get_db()
    try:
        conn.execute(
            "DELETE FROM operador_pin_tentativas WHERE cliente_id=? AND client_key=?",
            (cid, key),
        )
        conn.commit()
    finally:
        conn.close()


def _operator_by_pin(cliente_id: str, pin: str):
    _ensure_operator_tables()
    cid = str(cliente_id or "").strip()
    if not cid or not _operator_pin_ok(pin):
        return None
    lookup = _pin_lookup(cid, pin)
    conn = get_db()
    try:
        row = conn.execute(
            """
            SELECT id, cliente_id, nome, pin_lookup, pin_hash, status, active_machine_id
            FROM operadores
            WHERE cliente_id=? AND status='active' AND pin_lookup=?
            LIMIT 1
            """,
            (cid, lookup),
        ).fetchone()
    finally:
        conn.close()
    if not row:
        return None
    try:
        if check_password_hash(str(row["pin_hash"] or ""), str(pin)):
            return dict(row)
    except Exception:
        return None
    return None


def _pin_in_use(cliente_id: str, pin: str, exclude_operator_id: str = "") -> bool:
    _ensure_operator_tables()
    cid = str(cliente_id or "").strip()
    if not cid or not _operator_pin_ok(pin):
        return False
    lookup = _pin_lookup(cid, pin)
    conn = get_db()
    try:
        row = conn.execute(
            """
            SELECT id
            FROM operadores
            WHERE cliente_id=? AND pin_lookup=?
              AND (?='' OR id<>?)
            LIMIT 1
            """,
            (cid, lookup, exclude_operator_id, exclude_operator_id),
        ).fetchone()
    finally:
        conn.close()
    return bool(row)


def _operator_name_in_use(cliente_id: str, nome: str, exclude_operator_id: str = "") -> bool:
    _ensure_operator_tables()
    cid = str(cliente_id or "").strip()
    name = str(nome or "").strip().casefold()
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT id, nome FROM operadores WHERE cliente_id=?",
            (cid,),
        ).fetchall()
    finally:
        conn.close()
    return any(
        str(r["id"]) != str(exclude_operator_id)
        and str(r["nome"] or "").strip().casefold() == name
        for r in rows
    )


def _active_operator_count_for_machine(
    cliente_id: str,
    machine_id: str,
    exclude_operator_id: str = "",
) -> int:
    _ensure_operator_tables()
    cid = str(cliente_id or "").strip()
    mid = normalize_machine_id(machine_id, cid)
    conn = get_db()
    try:
        row = conn.execute(
            """
            SELECT COUNT(1)
            FROM operador_maquinas om
            JOIN operadores o ON o.id = om.operador_id
            WHERE om.cliente_id=?
              AND lower(om.machine_id)=lower(?)
              AND o.status='active'
              AND (?='' OR o.id<>?)
            """,
            (cid, mid, exclude_operator_id, exclude_operator_id),
        ).fetchone()
    finally:
        conn.close()
    return int(row[0] or 0) if row else 0


def _validate_operator_machines(
    cliente_id: str,
    machine_ids: list[str],
    operator_id: str = "",
    operator_is_active: bool = True,
) -> tuple[list[str], str]:
    cid = str(cliente_id or "").strip()
    known = {m.casefold(): m for m in list_operational_machines(cid)}
    selected: list[str] = []
    for raw in machine_ids:
        mid = normalize_machine_id(raw or "", cid)
        if mid and mid.casefold() in known:
            canonical = known[mid.casefold()]
            if canonical not in selected:
                selected.append(canonical)
    if not selected:
        return [], "Selecione pelo menos uma máquina para o operador."
    if operator_is_active:
        for mid in selected:
            count = _active_operator_count_for_machine(cid, mid, operator_id)
            if count >= MAX_OPERATORS_PER_MACHINE:
                return [], f"{mid.upper()} já possui 3 operadores ativos."
    return selected, ""


def _list_operators_for_admin(cliente_id: str) -> list[dict]:
    _ensure_operator_tables()
    cid = str(cliente_id or "").strip()
    conn = get_db()
    try:
        rows = conn.execute(
            """
            SELECT id, cliente_id, nome, status, active_machine_id,
                   last_login_at, created_at, updated_at
            FROM operadores
            WHERE cliente_id=?
            ORDER BY CASE WHEN status='active' THEN 0 ELSE 1 END, nome COLLATE NOCASE
            """,
            (cid,),
        ).fetchall()
        links = conn.execute(
            """
            SELECT operador_id, machine_id
            FROM operador_maquinas
            WHERE cliente_id=?
            ORDER BY lower(machine_id)
            """,
            (cid,),
        ).fetchall()
    finally:
        conn.close()
    by_operator: dict[str, list[str]] = {}
    for link in links:
        by_operator.setdefault(str(link["operador_id"]), []).append(str(link["machine_id"]))
    out = []
    for row in rows:
        item = dict(row)
        item["machines"] = by_operator.get(str(row["id"]), [])
        out.append(item)
    return out


def _set_operator_active_machine(operator_id: str, machine_id: str | None) -> None:
    _ensure_operator_tables()
    conn = get_db()
    try:
        conn.execute(
            "UPDATE operadores SET active_machine_id=?, updated_at=? WHERE id=?",
            (machine_id, _now_iso(), str(operator_id)),
        )
        conn.commit()
    finally:
        conn.close()


def _operator_logout_redirect():
    response = redirect(_gestflow_base_url())
    response.headers["Cache-Control"] = "no-store"
    response.headers["Referrer-Policy"] = "no-referrer"
    return response


def _request_wants_json() -> bool:
    return (
        request.path.startswith("/operacao/api/")
        or request.path == "/machine/status"
        or "application/json" in str(request.headers.get("Accept") or "")
    )


@operacao_bp.before_app_request
def _global_access_policy():
    path = request.path or ""

    if path.startswith("/static/"):
        return None

    if _is_operator_session() and not _is_gestflow_session():
        session.clear()
        if _request_wants_json():
            return jsonify({"ok": False, "error": "Acesso ao IndFlow exige autenticação pelo GestFlow."}), 401
        return _operator_logout_redirect()

    if _is_operator_session():
        row = _operator_session_record()
        if not row:
            session.clear()
            return _operator_logout_redirect()

        allowed = (
            path == "/machine/status"
            or path == "/operacao"
            or path.startswith("/operacao/")
        )
        if not allowed:
            if _request_wants_json():
                return jsonify({"ok": False, "error": "Acesso exclusivo à Tela Operacional."}), 403
            return redirect(url_for("operacao.home"))

        if path == "/machine/status":
            selected = normalize_machine_id(session.get("operator_machine_id") or "", _cliente_id())
            requested = normalize_machine_id(request.args.get("machine_id") or "", _cliente_id())
            db_machine = normalize_machine_id(row.get("active_machine_id") or "", _cliente_id())
            if not selected or not requested or requested.casefold() != selected.casefold():
                return jsonify({"ok": False, "error": "Máquina não autorizada para esta sessão."}), 403
            if not db_machine or db_machine.casefold() != selected.casefold():
                session.pop("operator_machine_id", None)
                return jsonify({"ok": False, "error": "Sessão do operador mudou de máquina."}), 401

    return None


def _resolve_machine(cid: str, raw_machine: str | None) -> tuple[str, list[str]]:
    if _is_operator_session():
        row = _operator_session_record()
        if not row:
            return "", []
        authorized = _list_operator_machines(cid, str(row.get("id") or ""))
        selected = normalize_machine_id(session.get("operator_machine_id") or "", cid)
        db_selected = normalize_machine_id(row.get("active_machine_id") or "", cid)
        known = {m.casefold(): m for m in authorized}
        if (
            selected
            and db_selected
            and selected.casefold() == db_selected.casefold()
            and selected.casefold() in known
        ):
            return known[selected.casefold()], [known[selected.casefold()]]
        return "", []

    machines = list_operational_machines(cid)
    machine_id = normalize_machine_id(raw_machine or "", cid)
    known = {m.casefold(): m for m in machines}
    if machine_id and machine_id.casefold() in known:
        machine_id = known[machine_id.casefold()]
    elif machines:
        machine_id = machines[0]
    else:
        machine_id = ""
    return machine_id, machines


@operacao_bp.get("/")
@login_required
def home():
    if _is_operator_session() and not session.get("operator_machine_id"):
        return redirect(url_for("operacao.operador_escolher_maquina"))
    cid = _cliente_id()
    machine_id, machines = _resolve_machine(cid, request.args.get("machine_id"))
    if _is_operator_session() and not machine_id:
        return redirect(url_for("operacao.operador_escolher_maquina"))
    return render_template(
        "operacao_home.html",
        machine_id=machine_id,
        machines=machines,
        is_operator=_is_operator_session(),
        operator_name=str(session.get("operator_name") or ""),
    )


@operacao_bp.get("/operadores")
@admin_required
def operadores_admin():
    cid = _operator_admin_cliente_id()
    machines = list_operational_machines(cid) if cid else []
    return render_template(
        "operadores_admin.html",
        cliente_id=cid,
        clientes=_list_clientes_admin(),
        is_superadmin=_is_superadmin_session(),
        machines=machines,
        operadores=_list_operators_for_admin(cid) if cid else [],
        max_per_machine=MAX_OPERATORS_PER_MACHINE,
        message=(request.args.get("msg") or "").strip() or None,
        error=(request.args.get("err") or "").strip() or None,
    )


@operacao_bp.post("/operadores/criar")
@admin_required
def operadores_criar():
    cid = _operator_admin_cliente_id()
    nome = str(request.form.get("nome") or "").strip()
    pin = str(request.form.get("pin") or "").strip()
    machine_ids = request.form.getlist("machine_ids")
    if len(nome) < 2 or len(nome) > 80:
        return redirect(url_for("operacao.operadores_admin", cliente_id=cid, err="Informe o nome do operador."))
    if not _operator_pin_ok(pin):
        return redirect(url_for("operacao.operadores_admin", cliente_id=cid, err="O PIN deve ter exatamente 4 números."))
    if _operator_name_in_use(cid, nome):
        return redirect(url_for("operacao.operadores_admin", cliente_id=cid, err="Já existe um operador com esse nome."))
    if _pin_in_use(cid, pin):
        return redirect(url_for("operacao.operadores_admin", cliente_id=cid, err="Esse PIN já está sendo usado por outro operador."))
    selected, err = _validate_operator_machines(cid, machine_ids)
    if err:
        return redirect(url_for("operacao.operadores_admin", cliente_id=cid, err=err))

    oid = str(uuid.uuid4())
    now = _now_iso()
    conn = get_db()
    try:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            """
            INSERT INTO operadores
                (id, cliente_id, nome, pin_lookup, pin_hash, status, active_machine_id,
                 last_login_at, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, 'active', NULL, NULL, ?, ?)
            """,
            (oid, cid, nome, _pin_lookup(cid, pin), generate_password_hash(pin), now, now),
        )
        for mid in selected:
            conn.execute(
                """
                INSERT INTO operador_maquinas (operador_id, cliente_id, machine_id, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (oid, cid, mid, now),
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return redirect(url_for("operacao.operadores_admin", cliente_id=cid, msg="Operador criado."))


@operacao_bp.post("/operadores/maquinas")
@admin_required
def operadores_maquinas():
    cid = _operator_admin_cliente_id()
    oid = str(request.form.get("operator_id") or "").strip()
    row = _operator_record(oid)
    if not row or str(row.get("cliente_id") or "") != cid:
        return redirect(url_for("operacao.operadores_admin", cliente_id=cid, err="Operador não encontrado."))
    selected, err = _validate_operator_machines(
        cid,
        request.form.getlist("machine_ids"),
        operator_id=oid,
        operator_is_active=str(row.get("status") or "") == "active",
    )
    if err:
        return redirect(url_for("operacao.operadores_admin", cliente_id=cid, err=err))
    now = _now_iso()
    conn = get_db()
    try:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute("DELETE FROM operador_maquinas WHERE operador_id=? AND cliente_id=?", (oid, cid))
        for mid in selected:
            conn.execute(
                """
                INSERT INTO operador_maquinas (operador_id, cliente_id, machine_id, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (oid, cid, mid, now),
            )
        active_machine = normalize_machine_id(row.get("active_machine_id") or "", cid)
        if active_machine and active_machine.casefold() not in {m.casefold() for m in selected}:
            conn.execute("UPDATE operadores SET active_machine_id=NULL WHERE id=?", (oid,))
        conn.execute("UPDATE operadores SET updated_at=? WHERE id=?", (now, oid))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return redirect(url_for("operacao.operadores_admin", cliente_id=cid, msg="Máquinas atualizadas."))


@operacao_bp.post("/operadores/pin")
@admin_required
def operadores_pin():
    cid = _operator_admin_cliente_id()
    oid = str(request.form.get("operator_id") or "").strip()
    pin = str(request.form.get("pin") or "").strip()
    row = _operator_record(oid)
    if not row or str(row.get("cliente_id") or "") != cid:
        return redirect(url_for("operacao.operadores_admin", cliente_id=cid, err="Operador não encontrado."))
    if not _operator_pin_ok(pin):
        return redirect(url_for("operacao.operadores_admin", cliente_id=cid, err="O PIN deve ter exatamente 4 números."))
    if _pin_in_use(cid, pin, oid):
        return redirect(url_for("operacao.operadores_admin", cliente_id=cid, err="Esse PIN já está sendo usado por outro operador."))
    conn = get_db()
    try:
        conn.execute(
            "UPDATE operadores SET pin_lookup=?, pin_hash=?, updated_at=? WHERE id=?",
            (_pin_lookup(cid, pin), generate_password_hash(pin), _now_iso(), oid),
        )
        conn.commit()
    finally:
        conn.close()
    return redirect(url_for("operacao.operadores_admin", cliente_id=cid, msg="PIN atualizado."))


@operacao_bp.post("/operadores/status")
@admin_required
def operadores_status():
    cid = _operator_admin_cliente_id()
    oid = str(request.form.get("operator_id") or "").strip()
    row = _operator_record(oid)
    if not row or str(row.get("cliente_id") or "") != cid:
        return redirect(url_for("operacao.operadores_admin", cliente_id=cid, err="Operador não encontrado."))
    new_status = "inactive" if str(row.get("status") or "") == "active" else "active"
    if new_status == "active":
        selected, err = _validate_operator_machines(
            cid,
            _list_operator_machines(cid, oid),
            operator_id=oid,
            operator_is_active=True,
        )
        if err:
            return redirect(url_for("operacao.operadores_admin", cliente_id=cid, err=err))
        if not selected:
            return redirect(url_for("operacao.operadores_admin", cliente_id=cid, err="Vincule pelo menos uma máquina antes de ativar."))
    conn = get_db()
    try:
        conn.execute(
            """
            UPDATE operadores
            SET status=?, active_machine_id=NULL, updated_at=?
            WHERE id=?
            """,
            (new_status, _now_iso(), oid),
        )
        conn.commit()
    finally:
        conn.close()
    return redirect(url_for("operacao.operadores_admin", cliente_id=cid, msg="Status atualizado."))


@operacao_bp.get("/operadores/qr/<machine_id>")
@admin_required
def operador_qr_admin(machine_id: str):
    cid = _operator_admin_cliente_id()
    try:
        mid = _canonical_operator_machine(cid, machine_id)
        token = _operator_access_token(cid, mid)
    except ValueError as exc:
        return redirect(url_for("operacao.operadores_admin", cliente_id=cid, err=str(exc)))

    access_url = url_for("operacao.operador_pin", token=token, _external=True)
    if _is_superadmin_session():
        qr_svg_url = url_for("operacao.operador_qr_svg", machine_id=mid, cliente_id=cid)
    else:
        qr_svg_url = url_for("operacao.operador_qr_svg", machine_id=mid)
    return render_template(
        "operador_qr.html",
        machine_id=mid,
        access_url=access_url,
        qr_svg_url=qr_svg_url,
        cliente_id=cid,
        is_superadmin=_is_superadmin_session(),
    )


@operacao_bp.get("/operadores/qr/<machine_id>/qr.svg")
@admin_required
def operador_qr_svg(machine_id: str):
    cid = _operator_admin_cliente_id()
    try:
        mid = _canonical_operator_machine(cid, machine_id)
        token = _operator_access_token(cid, mid)
    except ValueError:
        return Response("QR inválido.", status=404, mimetype="text/plain")

    access_url = url_for("operacao.operador_pin", token=token, _external=True)
    qr = qrcode.QRCode(
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=10,
        border=4,
    )
    qr.add_data(access_url)
    qr.make(fit=True)
    image = qr.make_image(image_factory=qrcode.image.svg.SvgPathImage)
    output = io.BytesIO()
    image.save(output)
    response = Response(output.getvalue(), mimetype="image/svg+xml")
    response.headers["Cache-Control"] = "no-store"
    return response


@operacao_bp.get("/acesso-operador")
@admin_required
def acesso_operador():
    cid = _operator_admin_cliente_id()
    token = _operator_access_token(cid)
    return redirect(url_for("operacao.operador_pin", token=token))


@operacao_bp.route("/pin", methods=["GET", "POST"])
@login_required
def operador_pin():
    token = str(request.values.get("token") or request.args.get("token") or "").strip()
    try:
        cid, target_machine = _operator_access_context(token)
    except ValueError as exc:
        return render_template(
            "operador_pin.html",
            token="",
            empresa="",
            machine_id="",
            error=str(exc),
        ), 403

    if not _is_superadmin_session() and cid != _cliente_id():
        return render_template(
            "operador_pin.html",
            token="",
            empresa="",
            machine_id="",
            error="Este acesso de operador não pertence à empresa autenticada no GestFlow.",
        ), 403

    conn = get_db()
    try:
        row = conn.execute("SELECT nome FROM clientes WHERE id=? LIMIT 1", (cid,)).fetchone()
        empresa = str(row["nome"] or "Empresa") if row else "Empresa"
    finally:
        conn.close()

    if request.method == "GET":
        return render_template(
            "operador_pin.html",
            token=token,
            empresa=empresa,
            machine_id=target_machine,
            error=None,
        )

    remaining = _pin_guard_remaining(cid)
    if remaining > 0:
        wait_min = max(1, (remaining + 59) // 60)
        return render_template(
            "operador_pin.html",
            token=token,
            empresa=empresa,
            machine_id=target_machine,
            error=f"Muitas tentativas incorretas. Aguarde {wait_min} minuto(s) e tente novamente.",
        ), 429

    pin = str(request.form.get("pin") or "").strip()
    if not _operator_pin_ok(pin):
        _pin_guard_fail(cid)
        return render_template(
            "operador_pin.html",
            token=token,
            empresa=empresa,
            machine_id=target_machine,
            error="Digite um PIN de 4 números.",
        )

    operator = _operator_by_pin(cid, pin)
    if not operator:
        _pin_guard_fail(cid)
        return render_template(
            "operador_pin.html",
            token=token,
            empresa=empresa,
            machine_id=target_machine,
            error="PIN inválido ou operador inativo.",
        )

    _pin_guard_clear(cid)
    machines = _list_operator_machines(cid, str(operator["id"]))
    if not machines:
        return render_template(
            "operador_pin.html",
            token=token,
            empresa=empresa,
            machine_id=target_machine,
            error="Seu cadastro não possui máquina autorizada. Procure o administrador.",
        )

    known = {m.casefold(): m for m in machines}
    if target_machine:
        if target_machine.casefold() not in known:
            return render_template(
                "operador_pin.html",
                token=token,
                empresa=empresa,
                machine_id=target_machine,
                error=f"Você não possui autorização para operar a máquina {target_machine.upper()}.",
            ), 403
        target_machine = known[target_machine.casefold()]

    gestflow_session = {
        "gestflow_sso": session.get("gestflow_sso"),
        "gestflow_empresa_id": session.get("gestflow_empresa_id"),
        "gestflow_usuario_id": session.get("gestflow_usuario_id"),
    }

    session.clear()
    session.update({key: value for key, value in gestflow_session.items() if value is not None})
    session["user_id"] = f"operator:{operator['id']}"
    session["cliente_id"] = cid
    session["role"] = "operator"
    session["operator_id"] = str(operator["id"])
    session["operator_name"] = str(operator["nome"])
    session["email"] = f"Operador · {operator['nome']}"

    conn = get_db()
    try:
        conn.execute(
            "UPDATE operadores SET last_login_at=?, updated_at=? WHERE id=?",
            (_now_iso(), _now_iso(), str(operator["id"])),
        )
        conn.commit()
    finally:
        conn.close()

    if target_machine:
        session["operator_machine_id"] = target_machine
        session["operator_entry_machine_id"] = target_machine
        _set_operator_active_machine(str(operator["id"]), target_machine)
        return redirect(url_for("operacao.home"))

    if len(machines) == 1:
        session["operator_machine_id"] = machines[0]
        _set_operator_active_machine(str(operator["id"]), machines[0])
        return redirect(url_for("operacao.home"))

    return redirect(url_for("operacao.operador_escolher_maquina"))


@operacao_bp.route("/escolher-maquina", methods=["GET", "POST"])
@login_required
def operador_escolher_maquina():
    if not _is_operator_session():
        return redirect(url_for("operacao.home"))
    row = _operator_session_record()
    if not row:
        session.clear()
        return _operator_logout_redirect()
    machines = _list_operator_machines(_cliente_id(), str(row["id"]))
    if not machines:
        return render_template(
            "operador_maquinas.html",
            operador=str(row.get("nome") or ""),
            machines=[],
            error="Nenhuma máquina autorizada. Procure o administrador.",
        )

    if request.method == "POST":
        requested = normalize_machine_id(request.form.get("machine_id") or "", _cliente_id())
        known = {m.casefold(): m for m in machines}
        if requested.casefold() not in known:
            return render_template(
                "operador_maquinas.html",
                operador=str(row.get("nome") or ""),
                machines=machines,
                error="Máquina não autorizada para seu cadastro.",
            )
        selected = known[requested.casefold()]
        session["operator_machine_id"] = selected
        _set_operator_active_machine(str(row["id"]), selected)
        return redirect(url_for("operacao.home"))

    if len(machines) == 1:
        session["operator_machine_id"] = machines[0]
        _set_operator_active_machine(str(row["id"]), machines[0])
        return redirect(url_for("operacao.home"))

    return render_template(
        "operador_maquinas.html",
        operador=str(row.get("nome") or ""),
        machines=machines,
        error=None,
    )


@operacao_bp.get("/trocar-maquina")
@login_required
def operador_trocar_maquina():
    if not _is_operator_session():
        return redirect(url_for("operacao.home"))
    oid = str(session.get("operator_id") or "")
    session.pop("operator_machine_id", None)
    session.pop("operator_entry_machine_id", None)
    if oid:
        _set_operator_active_machine(oid, None)
    return redirect(url_for("operacao.operador_escolher_maquina"))


@operacao_bp.get("/sair-operador")
@login_required
def operador_sair():
    oid = str(session.get("operator_id") or "")
    if oid:
        try:
            _set_operator_active_machine(oid, None)
        except Exception:
            pass
    session.clear()
    return _operator_logout_redirect()


@operacao_bp.get("/api/contexto")
@login_required
def api_contexto():
    cid = _cliente_id()
    if not cid:
        return jsonify({"ok": False, "error": "Cliente da sessão não identificado."}), 403
    machine_id, machines = _resolve_machine(cid, request.args.get("machine_id"))
    if not machine_id:
        return jsonify({"ok": True, "machine_id": "", "machines": [], "config": None, "reasons": []})
    config = get_operational_config(cid, machine_id)
    return jsonify(
        {
            "ok": True,
            "machine_id": machine_id,
            "machines": machines,
            "config": config,
            "reasons": list_operational_reasons(cid, machine_id, config["ordenacao"]),
            "operator": (
                {
                    "id": str(session.get("operator_id") or ""),
                    "nome": str(session.get("operator_name") or ""),
                }
                if _is_operator_session()
                else None
            ),
        }
    )


@operacao_bp.get("/api/estado")
@login_required
def api_estado():
    cid = _cliente_id()
    if not cid:
        return jsonify({"ok": False, "error": "Cliente da sessão não identificado."}), 403
    machine_id, _ = _resolve_machine(cid, request.args.get("machine_id"))
    if not machine_id:
        return jsonify({"ok": False, "error": "Nenhuma máquina disponível para a empresa atual."}), 404
    try:
        return jsonify({"ok": True, "data": get_operational_state(cid, machine_id)})
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400


@operacao_bp.post("/api/classificar")
@login_required
def api_classificar():
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
    try:
        result = classify_pending_occurrence(
            cid,
            occurrence_id,
            motivo_id,
            _operator_actor(),
        )
        return jsonify({"ok": True, "classificacao": result})
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400


@operacao_bp.post("/api/config")
@admin_required
def api_config():
    cid = _cliente_id()
    payload = request.get_json(silent=True) or {}
    machine_id = normalize_machine_id(payload.get("machine_id") or "", cid)
    if not machine_id:
        return jsonify({"ok": False, "error": "Máquina é obrigatória."}), 400
    known = {m.casefold(): m for m in list_operational_machines(cid)}
    if machine_id.casefold() not in known:
        return jsonify({"ok": False, "error": "Máquina não pertence à empresa atual."}), 400
    machine_id = known[machine_id.casefold()]
    try:
        config = save_operational_config(cid, machine_id, payload)
        return jsonify({"ok": True, "config": config})
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
