# Caminho: C:\Users\vlula\OneDrive\Área de Trabalho\Projetos Backup\GESTFLOW\apps\indflow\modules\devices\routes.py
# Último recode: 2026-08-31 16:03 (America/Bahia)
# Motivo: Permitir geração segura e rotacionável da API Key do ESP por tenant, restrita a ADMIN.

from flask import Blueprint, render_template, request, redirect, url_for, session, jsonify
from datetime import datetime
import hashlib
import re
import secrets

from modules.db_indflow import get_db
from modules.admin.routes import admin_required, login_required

devices_bp = Blueprint("devices", __name__, template_folder="templates")


# ============================================================
# HELPERS
# ============================================================

def _ensure_devices_table(conn):
    # Tabela mínima para cadastro/vínculo de devices (MAC = device_id)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS devices (
            device_id TEXT PRIMARY KEY,
            machine_id TEXT,
            alias TEXT,
            last_seen TEXT
        )
    """)
    try:
        conn.execute("ALTER TABLE devices ADD COLUMN cliente_id TEXT")
    except Exception:
        pass
    try:
        conn.execute("ALTER TABLE devices ADD COLUMN created_at TEXT")
    except Exception:
        pass
    try:
        conn.execute("CREATE INDEX IF NOT EXISTS ix_devices_cliente_id ON devices(cliente_id)")
    except Exception:
        pass
    conn.commit()


def _cliente_id_atual() -> str:
    return (session.get("cliente_id") or "").strip()


def _norm_device_id(v: str) -> str:
    """
    Normaliza MAC:
    - remove ':' e '-'
    - uppercase
    """
    s = (v or "").strip().upper()
    s = s.replace(":", "").replace("-", "")
    return s


def _is_valid_mac(v: str) -> bool:
    """
    MAC válido = exatamente 12 caracteres hexadecimais
    """
    return bool(re.fullmatch(r"[0-9A-F]{12}", (v or "")))


def _norm_machine_id(v: str) -> str:
    return (v or "").strip().lower()


def _norm_alias(v: str) -> str:
    s = (v or "").strip()
    if len(s) > 32:
        s = s[:32]
    return s


def _now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


# ============================================================
# ROUTES
# ============================================================

@devices_bp.route("/", methods=["GET"])
@login_required
def home():
    cliente_id = _cliente_id_atual()
    if not cliente_id:
        return "Cliente da sessao nao identificado", 403

    db = get_db()
    _ensure_devices_table(db)

    cur = db.execute("""
        SELECT device_id, machine_id, alias, last_seen
        FROM devices
        WHERE cliente_id = ?
        ORDER BY (machine_id IS NULL) DESC, last_seen DESC
    """, (cliente_id,))
    rows = cur.fetchall()

    devices = []
    for r in rows:
        try:
            device_id = r["device_id"]
            machine_id = r["machine_id"]
            alias = r["alias"]
            last_seen = r["last_seen"]
        except Exception:
            device_id, machine_id, alias, last_seen = r

        devices.append({
            "device_id": device_id,
            "machine_id": machine_id,
            "alias": alias,
            "last_seen": last_seen,
            "is_valid_mac": _is_valid_mac(device_id),
        })

    return render_template("devices_home.html", devices=devices)


@devices_bp.route("/machines", methods=["GET"])
@login_required
def machines():
    """
    Lista somente máquinas vinculadas a MACs válidos do tenant autenticado.
    O dashboard usa este endpoint como fonte da verdade e não usa localStorage.
    """
    cliente_id = _cliente_id_atual()
    if not cliente_id:
        return jsonify({"ok": False, "error": "Cliente da sessao nao identificado"}), 403

    db = get_db()
    _ensure_devices_table(db)

    rows = db.execute(
        """
        SELECT device_id, machine_id
        FROM devices
        WHERE cliente_id = ?
          AND machine_id IS NOT NULL
          AND TRIM(machine_id) <> ''
        ORDER BY machine_id ASC
        """,
        (cliente_id,),
    ).fetchall()

    machines_seen = set()
    machines_out = []

    for row in rows:
        try:
            device_id = row["device_id"]
            machine_id = row["machine_id"]
        except Exception:
            device_id, machine_id = row

        if not _is_valid_mac(_norm_device_id(device_id)):
            continue

        mid = _norm_machine_id(machine_id)
        if not mid or mid in machines_seen:
            continue

        machines_seen.add(mid)
        machines_out.append(mid)

    return jsonify({
        "ok": True,
        "cliente_id": cliente_id,
        "machines": machines_out,
    })


@devices_bp.route("/api-key", methods=["POST"])
@admin_required
def generate_api_key():
    """
    Gera/rotaciona a API Key usada pelo ESP deste tenant.

    Segurança:
    - somente ADMIN/SUPERADMIN;
    - a chave em texto puro existe apenas nesta resposta;
    - o banco persiste somente SHA-256;
    - gerar uma nova chave invalida imediatamente a anterior.
    """
    cliente_id = _cliente_id_atual()
    if not cliente_id:
        return jsonify({"ok": False, "error": "Cliente da sessao nao identificado"}), 403

    api_key_plain = secrets.token_urlsafe(48)
    api_key_hash = hashlib.sha256(api_key_plain.encode("utf-8")).hexdigest()

    db = get_db()
    try:
        cur = db.execute(
            """
            UPDATE clientes
            SET api_key_hash = ?
            WHERE id = ? AND status = 'active'
            """,
            (api_key_hash, cliente_id),
        )

        if int(cur.rowcount or 0) != 1:
            db.rollback()
            return jsonify({"ok": False, "error": "Cliente ativo nao encontrado"}), 404

        db.commit()
    finally:
        db.close()

    response = jsonify({
        "ok": True,
        "api_key": api_key_plain,
        "warning": "Esta chave sera exibida somente agora. A chave anterior foi invalidada.",
    })
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Referrer-Policy"] = "no-referrer"
    return response


@devices_bp.route("/link", methods=["POST"])
@login_required
def link_device():
    cliente_id = _cliente_id_atual()
    if not cliente_id:
        return "Cliente da sessao nao identificado", 403

    device_id = _norm_device_id(request.form.get("device_id"))
    machine_id = _norm_machine_id(request.form.get("machine_id"))

    # REGRA ESTRUTURAL: DEVICE PRECISA SER MAC VÁLIDO
    if not device_id or not _is_valid_mac(device_id):
        return redirect(url_for("devices.home"))

    if not machine_id:
        return redirect(url_for("devices.home"))

    db = get_db()
    _ensure_devices_table(db)

    now = _now_str()
    row = db.execute(
        "SELECT cliente_id FROM devices WHERE device_id = ? LIMIT 1",
        (device_id,),
    ).fetchone()

    if row is None:
        db.execute("""
            INSERT INTO devices (device_id, cliente_id, machine_id, alias, created_at, last_seen)
            VALUES (?, ?, ?, NULL, ?, ?)
        """, (device_id, cliente_id, machine_id, now, now))
        db.commit()
        return redirect(url_for("devices.home"))

    try:
        owner = (row["cliente_id"] or "").strip()
    except Exception:
        owner = (row[0] or "").strip()

    if owner and owner != cliente_id:
        return redirect(url_for("devices.home"))

    if not owner:
        db.execute("""
            UPDATE devices
            SET cliente_id = ?,
                machine_id = ?,
                created_at = COALESCE(created_at, ?),
                last_seen = ?
            WHERE device_id = ?
              AND (cliente_id IS NULL OR TRIM(cliente_id) = '')
        """, (cliente_id, machine_id, now, now, device_id))
    else:
        db.execute("""
            UPDATE devices
            SET machine_id = ?, last_seen = ?
            WHERE device_id = ? AND cliente_id = ?
        """, (machine_id, now, device_id, cliente_id))

    db.commit()
    return redirect(url_for("devices.home"))


@devices_bp.route("/unlink", methods=["POST"])
@login_required
def unlink_device():
    cliente_id = _cliente_id_atual()
    if not cliente_id:
        return "Cliente da sessao nao identificado", 403

    device_id = _norm_device_id(request.form.get("device_id"))

    # Desvincular só faz sentido pro MAC real
    if not device_id or not _is_valid_mac(device_id):
        return redirect(url_for("devices.home"))

    db = get_db()
    _ensure_devices_table(db)

    db.execute(
        "UPDATE devices SET machine_id = NULL, last_seen = ? WHERE device_id = ? AND cliente_id = ?",
        (_now_str(), device_id, cliente_id),
    )
    db.commit()
    return redirect(url_for("devices.home"))


@devices_bp.route("/delete", methods=["POST"])
@login_required
def delete_device():
    """
    Excluir deve permitir remover “fantasmas” também (MAQUINA01, etc),
    então NÃO exigimos MAC válido aqui.
    """
    cliente_id = _cliente_id_atual()
    if not cliente_id:
        return "Cliente da sessao nao identificado", 403

    raw = (request.form.get("device_id") or "").strip()
    if not raw:
        return redirect(url_for("devices.home"))

    # Se vier com separador, normaliza. Se for string livre, mantém "como está" (upper).
    if ":" in raw or "-" in raw:
        device_id = _norm_device_id(raw)
    else:
        device_id = raw.upper()

    db = get_db()
    _ensure_devices_table(db)

    db.execute("DELETE FROM devices WHERE device_id = ? AND cliente_id = ?", (device_id, cliente_id))
    db.commit()
    return redirect(url_for("devices.home"))


@devices_bp.route("/alias", methods=["POST"])
@login_required
def set_alias():
    cliente_id = _cliente_id_atual()
    if not cliente_id:
        return "Cliente da sessao nao identificado", 403

    device_id = _norm_device_id(request.form.get("device_id"))
    alias = _norm_alias(request.form.get("alias"))

    # Alias só pro MAC real
    if not device_id or not _is_valid_mac(device_id):
        return redirect(url_for("devices.home"))

    db = get_db()
    _ensure_devices_table(db)

    cur = db.execute("SELECT device_id FROM devices WHERE device_id = ? AND cliente_id = ?", (device_id, cliente_id))
    exists = cur.fetchone() is not None
    if not exists:
        return redirect(url_for("devices.home"))

    db.execute(
        "UPDATE devices SET alias = ?, last_seen = ? WHERE device_id = ? AND cliente_id = ?",
        (alias if alias else None, _now_str(), device_id, cliente_id),
    )
    db.commit()
    return redirect(url_for("devices.home"))


@devices_bp.route("/cleanup-invalid", methods=["POST"])
@login_required
def cleanup_invalid():
    """
    Remove com segurança qualquer registro cujo device_id NÃO seja MAC válido.
    Ex.: MAQUINA01, MAQUINA01_DEV, etc.
    """
    cliente_id = _cliente_id_atual()
    if not cliente_id:
        return "Cliente da sessao nao identificado", 403

    db = get_db()
    _ensure_devices_table(db)

    cur = db.execute("SELECT device_id FROM devices WHERE cliente_id = ?", (cliente_id,))
    rows = cur.fetchall()

    to_delete = []
    for r in rows:
        try:
            device_id = r["device_id"]
        except Exception:
            device_id = r[0]
        if not _is_valid_mac(device_id):
            to_delete.append(device_id)

    for device_id in to_delete:
        db.execute("DELETE FROM devices WHERE device_id = ? AND cliente_id = ?", (device_id, cliente_id))

    db.commit()
    return redirect(url_for("devices.home"))
