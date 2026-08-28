# Caminho: C:\Users\vlula\OneDrive\Área de Trabalho\Projetos Backup\GESTFLOW\apps\indflow\modules\machine_state.py
# Último recode: 2026-08-21 06:43 (America/Bahia)
# Motivo: Migrar para a estrutura consolidada GESTFLOW + INDFLOW na branch DEV, preservando o conteúdo funcional validado.

from datetime import datetime
import json

from modules.db_indflow import get_db
from modules.machine_calc import now_bahia, dia_operacional_ref_str
from modules.repos.machine_config_repo import ensure_machine_config_tenant_table

machine_data = {}


def _normalize_machine_context(machine_id: str, cliente_id: str | None = None) -> tuple[str | None, str]:
    """Normaliza o contexto sem obrigar os chamadores atuais a mudar de uma vez.

    Aceita tanto:
      - machine_id="maquina01", cliente_id="cliente-x"
      - machine_id="cliente-x::maquina01"
    """
    raw = (machine_id or "").strip().lower()
    cid = (cliente_id or "").strip()

    if "::" in raw:
        scoped_cid, raw_mid = raw.split("::", 1)
        if not cid:
            cid = scoped_cid.strip()
        raw = raw_mid.strip()

    return (cid or None), raw


def _machine_cache_key(machine_id: str, cliente_id: str | None = None) -> str:
    cid, mid = _normalize_machine_context(machine_id, cliente_id)
    return f"{cid}::{mid}" if cid else mid


def _ensure_machine_config_table():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS machine_config (
            machine_id TEXT PRIMARY KEY,
            meta_turno INTEGER NOT NULL DEFAULT 0,
            turno_inicio TEXT,
            turno_fim TEXT,
            rampa_percentual INTEGER NOT NULL DEFAULT 0,
            horas_turno_json TEXT NOT NULL DEFAULT '[]',
            meta_por_hora_json TEXT NOT NULL DEFAULT '[]',

            -- ✅ manter compatível com machine_config_repo.py
            unidade_1 TEXT,
            unidade_2 TEXT,
            conv_m_por_pcs REAL,

            updated_at TEXT NOT NULL
        )
    """)
    conn.commit()

    # ✅ MIGRAÇÃO SEGURA (bancos antigos)
    try:
        cur.execute("PRAGMA table_info(machine_config)")
        cols = [r[1] for r in cur.fetchall()]

        if "unidade_1" not in cols:
            cur.execute("ALTER TABLE machine_config ADD COLUMN unidade_1 TEXT")
        if "unidade_2" not in cols:
            cur.execute("ALTER TABLE machine_config ADD COLUMN unidade_2 TEXT")
        if "conv_m_por_pcs" not in cols:
            cur.execute("ALTER TABLE machine_config ADD COLUMN conv_m_por_pcs REAL")

        conn.commit()
    except Exception:
        pass

    conn.close()


def _load_machine_config(machine_id: str, cliente_id: str | None = None):
    _ensure_machine_config_table()

    # A tabela tenant e paralela: se ainda nao existir em um banco antigo,
    # ela e criada sem substituir a machine_config legada.
    try:
        ensure_machine_config_tenant_table()
    except Exception:
        pass

    cid, machine_id = _normalize_machine_context(machine_id, cliente_id)
    if not machine_id:
        return None

    conn = get_db()
    cur = conn.cursor()
    row = None

    # Prioridade multiempresa: configuracao especifica do cliente + maquina.
    if cid:
        try:
            cur.execute("""
                SELECT
                    meta_turno,
                    turno_inicio,
                    turno_fim,
                    rampa_percentual,
                    horas_turno_json,
                    meta_por_hora_json,
                    unidade_1,
                    unidade_2,
                    conv_m_por_pcs
                FROM machine_config_tenant
                WHERE cliente_id=? AND machine_id=?
                LIMIT 1
            """, (cid, machine_id))
            row = cur.fetchone()
        except Exception:
            row = None

    # Fallback de transicao: mantem funcionando configuracoes antigas.
    if not row:
        cur.execute("""
            SELECT
                meta_turno,
                turno_inicio,
                turno_fim,
                rampa_percentual,
                horas_turno_json,
                meta_por_hora_json,
                unidade_1,
                unidade_2,
                conv_m_por_pcs
            FROM machine_config
            WHERE machine_id=?
            LIMIT 1
        """, (machine_id,))
        row = cur.fetchone()

    conn.close()

    if not row:
        return None

    try:
        meta_turno = int(row[0] or 0)
    except Exception:
        meta_turno = 0

    turno_inicio = row[1]
    turno_fim = row[2]

    try:
        rampa = int(row[3] or 0)
    except Exception:
        rampa = 0

    try:
        horas_turno = json.loads(row[4] or "[]")
        if not isinstance(horas_turno, list):
            horas_turno = []
    except Exception:
        horas_turno = []

    try:
        meta_por_hora = json.loads(row[5] or "[]")
        if not isinstance(meta_por_hora, list):
            meta_por_hora = []
    except Exception:
        meta_por_hora = []

    unidade_1 = row[6] if row[6] not in ("", None) else None
    unidade_2 = row[7] if row[7] not in ("", None) else None

    try:
        conv = float(row[8]) if row[8] is not None else 1.0
        if conv <= 0:
            conv = 1.0
    except Exception:
        conv = 1.0

    return {
        "meta_turno": meta_turno,
        "turno_inicio": turno_inicio,
        "turno_fim": turno_fim,
        "rampa_percentual": rampa,
        "horas_turno": horas_turno,
        "meta_por_hora": meta_por_hora,
        "unidade_1": unidade_1,
        "unidade_2": unidade_2,
        "conv_m_por_pcs": conv,
    }


def _load_baseline_diario_state(machine_id: str, cliente_id: str | None = None):
    """
    Carrega o ultimo baseline do dia operacional.

    Quando cliente_id estiver disponivel, prioriza o baseline daquele cliente.
    Para compatibilidade, aceita fallback apenas para registro legado sem dono;
    nunca usa baseline explicitamente pertencente a outro cliente.
    """
    cid, machine_id = _normalize_machine_context(machine_id, cliente_id)
    if not machine_id:
        return None

    try:
        conn = get_db()
        cur = conn.cursor()

        cur.execute("PRAGMA table_info(baseline_diario)")
        cols = [r[1] for r in cur.fetchall()]
        has_cliente_id = "cliente_id" in cols

        row = None
        if cid and has_cliente_id:
            cur.execute("""
                SELECT dia_ref, baseline_esp, esp_last
                FROM baseline_diario
                WHERE machine_id=? AND cliente_id=?
                ORDER BY updated_at DESC
                LIMIT 1
            """, (machine_id, cid))
            row = cur.fetchone()

            if not row:
                cur.execute("""
                    SELECT dia_ref, baseline_esp, esp_last
                    FROM baseline_diario
                    WHERE machine_id=?
                      AND (cliente_id IS NULL OR TRIM(cliente_id)='')
                    ORDER BY updated_at DESC
                    LIMIT 1
                """, (machine_id,))
                row = cur.fetchone()
        else:
            cur.execute("""
                SELECT dia_ref, baseline_esp, esp_last
                FROM baseline_diario
                WHERE machine_id=?
                ORDER BY updated_at DESC
                LIMIT 1
            """, (machine_id,))
            row = cur.fetchone()

        conn.close()

        if not row:
            return None

        dia_ref = str(row[0]) if row[0] else None
        try:
            baseline_esp = int(row[1])
        except Exception:
            baseline_esp = None
        try:
            esp_last = int(row[2])
        except Exception:
            esp_last = None

        if not dia_ref or baseline_esp is None or esp_last is None:
            return None

        return {"dia_ref": dia_ref, "baseline_esp": baseline_esp, "esp_last": esp_last}
    except Exception:
        return None


def get_machine(machine_id: str, cliente_id: str | None = None):
    # Normaliza e permite transicao gradual dos chamadores para contexto tenant.
    cliente_id, machine_id = _normalize_machine_context(machine_id, cliente_id)
    if not machine_id:
        machine_id = "maquina01"

    cache_key = _machine_cache_key(machine_id, cliente_id)

    if cache_key not in machine_data:
        agora = now_bahia()

        # Fonte da verdade pos-deploy: baseline_diario do tenant, quando houver.
        st = _load_baseline_diario_state(machine_id, cliente_id)

        if st:
            ultimo_dia = st["dia_ref"]
            baseline_diario = st["baseline_esp"]
            esp_absoluto = st["esp_last"]
            bd_dia_ref = st["dia_ref"]
            bd_esp_last = st["esp_last"]
            primeiro_update_pendente = False
        else:
            ultimo_dia = dia_operacional_ref_str(agora)
            baseline_diario = 0
            esp_absoluto = 0
            bd_dia_ref = None
            bd_esp_last = None
            primeiro_update_pendente = True

        machine_data[cache_key] = {
            "nome": machine_id.upper(),
            "status": "DESCONHECIDO",
            "cliente_id": cliente_id,

            "meta_turno": 0,
            "turno_inicio": None,
            "turno_fim": None,
            "rampa_percentual": 0,

            "unidade_1": None,
            "unidade_2": None,
            "conv_m_por_pcs": 1.0,

            "esp_absoluto": esp_absoluto,
            "baseline_diario": baseline_diario,
            "baseline_hora": 0,

            "producao_turno": 0,
            "producao_turno_anterior": 0,

            "horas_turno": [],
            "meta_por_hora": [],
            "producao_hora": 0,
            "percentual_hora": 0,
            "ultima_hora": None,

            "percentual_turno": 0,
            "tempo_medio_min_por_peca": None,

            "ultimo_dia": ultimo_dia,
            "reset_executado_hoje": False,

            "_bd_dia_ref": bd_dia_ref,
            "_bd_esp_last": bd_esp_last,

            "_primeiro_update_pendente": primeiro_update_pendente,
        }

        # Primeiro tenta a configuracao do tenant; se ainda nao existir,
        # usa a machine_config antiga durante a transicao.
        cfg = _load_machine_config(machine_id, cliente_id)
        if cfg:
            machine_data[cache_key]["meta_turno"] = cfg.get("meta_turno", 0) or 0
            machine_data[cache_key]["turno_inicio"] = cfg.get("turno_inicio")
            machine_data[cache_key]["turno_fim"] = cfg.get("turno_fim")
            machine_data[cache_key]["rampa_percentual"] = cfg.get("rampa_percentual", 0) or 0
            machine_data[cache_key]["horas_turno"] = cfg.get("horas_turno") or []
            machine_data[cache_key]["meta_por_hora"] = cfg.get("meta_por_hora") or []

            machine_data[cache_key]["unidade_1"] = cfg.get("unidade_1")
            machine_data[cache_key]["unidade_2"] = cfg.get("unidade_2")
            machine_data[cache_key]["conv_m_por_pcs"] = cfg.get("conv_m_por_pcs", 1.0) or 1.0

    return machine_data[cache_key]
