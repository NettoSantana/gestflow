# Caminho: C:\Users\vlula\OneDrive\Área de Trabalho\Projetos Backup\GESTFLOW\apps\indflow\modules\db_indflow.py
# Último recode: 2026-08-21 06:43 (America/Bahia)
# Motivo: Migrar para a estrutura consolidada GESTFLOW + INDFLOW na branch DEV, preservando o conteúdo funcional validado.

import os
import sqlite3
from pathlib import Path


def _is_railway() -> bool:
    keys = ["RAILWAY_ENVIRONMENT", "RAILWAY_PROJECT_ID", "RAILWAY_SERVICE_ID", "RAILWAY_STATIC_URL"]
    return any((os.getenv(k) or "").strip() for k in keys)


def _default_db_path() -> str:
    env_path = os.getenv("INDFLOW_DB_PATH", "").strip()
    if env_path:
        return env_path
    if _is_railway():
        return "/data/indflow.db"
    if Path("/data").exists():
        return "/data/indflow.db"
    return "indflow.db"


def _ensure_db_dir(db_path: str) -> None:
    db_file = Path(db_path)
    if db_file.parent and str(db_file.parent) not in ("", "."):
        db_file.parent.mkdir(parents=True, exist_ok=True)


def get_db():
    db_path = _default_db_path()
    _ensure_db_dir(db_path)
    conn = sqlite3.connect(db_path, timeout=30, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def _has_column(conn: sqlite3.Connection, table: str, column: str) -> bool:
    cur = conn.execute(f"PRAGMA table_info({table})")
    cols = [r[1] for r in cur.fetchall()]
    return column in cols


def _add_column_if_missing(conn: sqlite3.Connection, table: str, column: str, col_ddl: str) -> None:
    if not _has_column(conn, table, column):
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_ddl}")


def _dedupe_keep_latest(conn: sqlite3.Connection, table: str, keys: list[str]) -> None:
    """
    Remove duplicados mantendo o maior id (mais recente) por grupo.
    Requer coluna 'id' INTEGER PRIMARY KEY AUTOINCREMENT no table.
    Agrupa por keys + COALESCE(cliente_id,'__NULL__') quando cliente_id existir.
    """
    cols = keys[:]
    if _has_column(conn, table, "cliente_id") and "cliente_id" not in cols:
        cols.append("COALESCE(cliente_id,'__NULL__')")

    group_expr = ", ".join(cols) if cols else "1"
    conn.execute(f"""
        DELETE FROM {table}
        WHERE id NOT IN (
            SELECT MAX(id) FROM {table}
            GROUP BY {group_expr}
        )
    """)


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    try:
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
            (table,),
        ).fetchone()
        return bool(row)
    except Exception:
        return False


def init_db():
    conn = get_db()
    cur = conn.cursor()

    # -------------------- auth --------------------
    cur.execute("""
        CREATE TABLE IF NOT EXISTS clientes (
            id TEXT PRIMARY KEY,
            nome TEXT NOT NULL,
            api_key_hash TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'active',
            created_at TEXT NOT NULL
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS usuarios (
            id TEXT PRIMARY KEY,
            email TEXT NOT NULL,
            senha_hash TEXT NOT NULL,
            cliente_id TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'admin',
            status TEXT NOT NULL DEFAULT 'active',
            created_at TEXT NOT NULL,
            FOREIGN KEY (cliente_id) REFERENCES clientes(id)
        )
    """)
    cur.execute("CREATE UNIQUE INDEX IF NOT EXISTS ux_usuarios_email ON usuarios(email)")
    cur.execute("CREATE INDEX IF NOT EXISTS ix_usuarios_cliente_id ON usuarios(cliente_id)")

    # -------------------- integracao GestFlow --------------------
    # Mantem as identidades dos dois sistemas independentes:
    # GestFlow usa empresa_id/usuario_id (INTEGER), enquanto o IndFlow usa
    # cliente_id/usuario_id proprios (TEXT/UUID). O vinculo fica somente aqui.
    cur.execute("""
        CREATE TABLE IF NOT EXISTS integracao_gestflow_empresas (
            gestflow_empresa_id INTEGER PRIMARY KEY,
            indflow_cliente_id TEXT NOT NULL UNIQUE,
            status TEXT NOT NULL DEFAULT 'active',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY (indflow_cliente_id) REFERENCES clientes(id)
        )
    """)
    cur.execute("""
        CREATE INDEX IF NOT EXISTS ix_integracao_gestflow_empresas_cliente
        ON integracao_gestflow_empresas(indflow_cliente_id)
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS integracao_gestflow_usuarios (
            gestflow_empresa_id INTEGER NOT NULL,
            gestflow_usuario_id INTEGER NOT NULL,
            indflow_usuario_id TEXT NOT NULL UNIQUE,
            indflow_cliente_id TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'active',
            last_sso_at TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (gestflow_empresa_id, gestflow_usuario_id),
            FOREIGN KEY (gestflow_empresa_id) REFERENCES integracao_gestflow_empresas(gestflow_empresa_id),
            FOREIGN KEY (indflow_usuario_id) REFERENCES usuarios(id),
            FOREIGN KEY (indflow_cliente_id) REFERENCES clientes(id)
        )
    """)
    cur.execute("""
        CREATE INDEX IF NOT EXISTS ix_integracao_gestflow_usuarios_cliente
        ON integracao_gestflow_usuarios(indflow_cliente_id)
    """)
    cur.execute("""
        CREATE INDEX IF NOT EXISTS ix_integracao_gestflow_usuarios_usuario
        ON integracao_gestflow_usuarios(indflow_usuario_id)
    """)

    # -------------------- devices --------------------
    cur.execute("""
        CREATE TABLE IF NOT EXISTS devices (
            device_id TEXT PRIMARY KEY,
            machine_id TEXT,
            alias TEXT,
            last_seen TEXT
        )
    """)
    _add_column_if_missing(conn, "devices", "cliente_id", "TEXT")
    _add_column_if_missing(conn, "devices", "created_at", "TEXT")
    cur.execute("CREATE INDEX IF NOT EXISTS ix_devices_machine_id ON devices(machine_id)")
    cur.execute("CREATE INDEX IF NOT EXISTS ix_devices_cliente_id ON devices(cliente_id)")

    # -------------------- producao_diaria --------------------
    cur.execute("""
        CREATE TABLE IF NOT EXISTS producao_diaria (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            machine_id TEXT,
            data TEXT,
            produzido INTEGER,
            meta INTEGER,
            percentual INTEGER
        )
    """)
    _add_column_if_missing(conn, "producao_diaria", "cliente_id", "TEXT")
    cur.execute("CREATE INDEX IF NOT EXISTS ix_producao_diaria_cliente_id ON producao_diaria(cliente_id)")

    # -------------------- machine_config --------------------
    cur.execute("""
        CREATE TABLE IF NOT EXISTS machine_config (
            machine_id TEXT PRIMARY KEY,
            meta_turno INTEGER NOT NULL DEFAULT 0,
            turno_inicio TEXT,
            turno_fim TEXT,
            rampa_percentual INTEGER NOT NULL DEFAULT 0,
            horas_turno_json TEXT NOT NULL DEFAULT '[]',
            meta_por_hora_json TEXT NOT NULL DEFAULT '[]',
            updated_at TEXT NOT NULL
        )
    """)
    _add_column_if_missing(conn, "machine_config", "cliente_id", "TEXT")
    _add_column_if_missing(conn, "machine_config", "config_json", "TEXT")
    cur.execute("CREATE INDEX IF NOT EXISTS ix_machine_config_cliente_id ON machine_config(cliente_id)")

    # -------------------- producao_horaria --------------------
    cur.execute("""
        CREATE TABLE IF NOT EXISTS producao_horaria (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            machine_id TEXT NOT NULL,
            data_ref TEXT NOT NULL,
            hora_idx INTEGER NOT NULL,
            baseline_esp INTEGER NOT NULL,
            esp_last INTEGER NOT NULL,
            produzido INTEGER NOT NULL,
            meta INTEGER NOT NULL,
            percentual INTEGER NOT NULL,
            updated_at TEXT NOT NULL
        )
    """)
    _add_column_if_missing(conn, "producao_horaria", "cliente_id", "TEXT")

    # limpa duplicados antes de índices unique (evita crash)
    try:
        _dedupe_keep_latest(conn, "producao_horaria", ["machine_id", "data_ref", "hora_idx"])
    except Exception:
        pass

    # remove índice legado antigo (pode colidir com multi-tenant)
    cur.execute("DROP INDEX IF EXISTS ux_producao_horaria")

    # unique multi-tenant + legado parcial
    cur.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS ux_producao_horaria_cliente
        ON producao_horaria(cliente_id, machine_id, data_ref, hora_idx)
    """)
    cur.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS ux_producao_horaria_legacy
        ON producao_horaria(machine_id, data_ref, hora_idx)
        WHERE cliente_id IS NULL
    """)

    # -------------------- baseline_diario --------------------
    cur.execute("""
        CREATE TABLE IF NOT EXISTS baseline_diario (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            machine_id TEXT NOT NULL,
            dia_ref TEXT NOT NULL,
            baseline_esp INTEGER NOT NULL,
            esp_last INTEGER NOT NULL,
            updated_at TEXT NOT NULL
        )
    """)
    _add_column_if_missing(conn, "baseline_diario", "cliente_id", "TEXT")

    # limpa duplicados antes de índices unique (RESOLVE seu erro do Railway)
    try:
        _dedupe_keep_latest(conn, "baseline_diario", ["machine_id", "dia_ref"])
    except Exception:
        pass

    # remove índice legado antigo que está derrubando o deploy
    cur.execute("DROP INDEX IF EXISTS ux_baseline_diario")

    # unique multi-tenant + legado parcial
    cur.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS ux_baseline_diario_cliente
        ON baseline_diario(cliente_id, machine_id, dia_ref)
    """)
    cur.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS ux_baseline_diario_legacy
        ON baseline_diario(machine_id, dia_ref)
        WHERE cliente_id IS NULL
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS ix_baseline_diario_cliente_id ON baseline_diario(cliente_id)")

    # -------------------- machine_state_event (RUN/STOP) --------------------
    # Fonte persistente de estado para montar o Historico (segments) sem "sumir" no refresh.
    #
    # IMPORTANTE:
    # O machine_routes.py já tenta inserir: machine_id, effective_machine_id, cliente_id, ts_ms, ts_iso, data_ref, hora_idx, state.
    # Se o schema não tiver essas colunas, o insert falha e o erro fica "silencioso" (try/except).
    #
    # Por isso, aqui garantimos o schema completo.
    cur.execute("""
        CREATE TABLE IF NOT EXISTS machine_state_event (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            machine_id TEXT,
            effective_machine_id TEXT NOT NULL,
            cliente_id TEXT,
            ts_ms INTEGER NOT NULL,
            ts_iso TEXT,
            data_ref TEXT NOT NULL,
            hora_idx INTEGER,
            state TEXT NOT NULL
        )
    """)

    # Migração defensiva (caso a tabela já exista em schema antigo)
    if _table_exists(conn, "machine_state_event"):
        _add_column_if_missing(conn, "machine_state_event", "machine_id", "TEXT")
        _add_column_if_missing(conn, "machine_state_event", "cliente_id", "TEXT")
        _add_column_if_missing(conn, "machine_state_event", "ts_iso", "TEXT")
        _add_column_if_missing(conn, "machine_state_event", "hora_idx", "INTEGER")

    # Índices para leitura por dia e reconstrução de segments
    cur.execute("""
        CREATE INDEX IF NOT EXISTS ix_machine_state_event_eff_day_ts
        ON machine_state_event(effective_machine_id, data_ref, ts_ms)
    """)
    cur.execute("""
        CREATE INDEX IF NOT EXISTS ix_machine_state_event_cliente_eff_day_ts
        ON machine_state_event(cliente_id, effective_machine_id, data_ref, ts_ms)
    """)
    cur.execute("""
        CREATE INDEX IF NOT EXISTS ix_machine_state_event_machine_day_ts
        ON machine_state_event(machine_id, data_ref, ts_ms)
    """)

    
    # -------------------- paradas / motivos / classificacao --------------------
    # A telemetria original permanece em machine_state_event. Estas tabelas apenas
    # guardam catalogo e classificacao das ocorrencias detectadas.
    cur.execute("""
        CREATE TABLE IF NOT EXISTS parada_categorias (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            cliente_id TEXT NOT NULL,
            nome TEXT NOT NULL,
            slug TEXT NOT NULL,
            ordem INTEGER NOT NULL DEFAULT 0,
            ativo INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """)
    cur.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS ux_parada_categorias_cliente_nome
        ON parada_categorias(cliente_id, nome COLLATE NOCASE)
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS ix_parada_categorias_cliente ON parada_categorias(cliente_id, ativo, ordem)")

    cur.execute("""
        CREATE TABLE IF NOT EXISTS parada_motivos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            cliente_id TEXT NOT NULL,
            categoria_id INTEGER NOT NULL,
            codigo TEXT NOT NULL,
            descricao TEXT NOT NULL,
            tipo TEXT NOT NULL DEFAULT 'nao_planejada',
            aplica_todas INTEGER NOT NULL DEFAULT 1,
            ativo INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """)
    cur.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS ux_parada_motivos_cliente_codigo
        ON parada_motivos(cliente_id, codigo COLLATE NOCASE)
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS ix_parada_motivos_cliente_categoria ON parada_motivos(cliente_id, categoria_id, ativo)")

    cur.execute("""
        CREATE TABLE IF NOT EXISTS parada_motivo_maquinas (
            cliente_id TEXT NOT NULL,
            motivo_id INTEGER NOT NULL,
            machine_id TEXT NOT NULL,
            PRIMARY KEY (cliente_id, motivo_id, machine_id)
        )
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS ix_parada_motivo_maquinas_mid ON parada_motivo_maquinas(cliente_id, machine_id)")

    cur.execute("""
        CREATE TABLE IF NOT EXISTS parada_ocorrencias (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            cliente_id TEXT NOT NULL,
            machine_id TEXT NOT NULL,
            started_at_ms INTEGER NOT NULL,
            ended_at_ms INTEGER,
            duration_sec INTEGER NOT NULL DEFAULT 0,
            source TEXT NOT NULL DEFAULT 'telemetria',
            status TEXT NOT NULL DEFAULT 'FECHADA',
            categoria_id INTEGER,
            motivo_id INTEGER,
            observacao TEXT,
            responsavel TEXT,
            classificado_por TEXT,
            classificado_at TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """)
    cur.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS ux_parada_ocorrencias_cliente_maquina_inicio
        ON parada_ocorrencias(cliente_id, machine_id, started_at_ms)
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS ix_parada_ocorrencias_periodo ON parada_ocorrencias(cliente_id, machine_id, started_at_ms, ended_at_ms)")
    cur.execute("CREATE INDEX IF NOT EXISTS ix_parada_ocorrencias_motivo ON parada_ocorrencias(cliente_id, motivo_id, started_at_ms)")

    # -------------------- tela operacional / classificacao obrigatoria --------------------
    cur.execute("""
        CREATE TABLE IF NOT EXISTS operacao_parada_config (
            cliente_id TEXT NOT NULL,
            machine_id TEXT NOT NULL,
            tempo_obrigatorio_min INTEGER NOT NULL DEFAULT 3,
            botoes_por_pagina INTEGER NOT NULL DEFAULT 8,
            ordenacao TEXT NOT NULL DEFAULT 'mais_clicados',
            updated_at TEXT NOT NULL,
            PRIMARY KEY (cliente_id, machine_id)
        )
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS ix_operacao_parada_config_cliente ON operacao_parada_config(cliente_id, machine_id)")

    # -----------------------------
    # Estrutura para bobinas por OP
    # -----------------------------

    # Eventos por bobina (N bobinas por OP)
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS ordens_producao_bobina_eventos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            op_id INTEGER NOT NULL,
            seq INTEGER NOT NULL DEFAULT 0,

            comprimento_m INTEGER NOT NULL DEFAULT 0,

            started_at TEXT NOT NULL,
            ended_at TEXT,

            start_abs_pcs INTEGER NOT NULL DEFAULT 0,
            end_abs_pcs INTEGER,

            created_at TEXT,
            updated_at TEXT,

            UNIQUE(op_id, seq)
        )
        """
    )

    # Garantir colunas (compatibilidade/migracao leve)
    _add_column_if_missing(conn, "ordens_producao_bobina_eventos", "op_id", "INTEGER NOT NULL DEFAULT 0")
    _add_column_if_missing(conn, "ordens_producao_bobina_eventos", "seq", "INTEGER NOT NULL DEFAULT 0")
    _add_column_if_missing(conn, "ordens_producao_bobina_eventos", "comprimento_m", "INTEGER NOT NULL DEFAULT 0")
    _add_column_if_missing(conn, "ordens_producao_bobina_eventos", "started_at", "TEXT NOT NULL DEFAULT ''")
    _add_column_if_missing(conn, "ordens_producao_bobina_eventos", "ended_at", "TEXT")
    _add_column_if_missing(conn, "ordens_producao_bobina_eventos", "start_abs_pcs", "INTEGER NOT NULL DEFAULT 0")
    _add_column_if_missing(conn, "ordens_producao_bobina_eventos", "end_abs_pcs", "INTEGER")
    _add_column_if_missing(conn, "ordens_producao_bobina_eventos", "created_at", "TEXT")
    _add_column_if_missing(conn, "ordens_producao_bobina_eventos", "updated_at", "TEXT")

    cur.execute("CREATE INDEX IF NOT EXISTS ix_op_bobina_eventos_opid ON ordens_producao_bobina_eventos(op_id)")
    cur.execute("CREATE INDEX IF NOT EXISTS ix_op_bobina_eventos_opid_seq ON ordens_producao_bobina_eventos(op_id, seq)")

    # Pendencia de troca: impede clique duplo e sincroniza inicio da proxima bobina no primeiro machine/update
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS ordens_producao_bobina_pendencia (
            op_id INTEGER PRIMARY KEY,
            machine_id TEXT NOT NULL,
            armed_at TEXT NOT NULL,

            closed_seq INTEGER NOT NULL DEFAULT 0,
            closed_abs_pcs INTEGER NOT NULL DEFAULT 0,
            next_seq INTEGER NOT NULL DEFAULT 0,

            created_at TEXT,
            updated_at TEXT
        )
        """
    )

    _add_column_if_missing(conn, "ordens_producao_bobina_pendencia", "machine_id", "TEXT NOT NULL DEFAULT ''")
    _add_column_if_missing(conn, "ordens_producao_bobina_pendencia", "armed_at", "TEXT NOT NULL DEFAULT ''")
    _add_column_if_missing(conn, "ordens_producao_bobina_pendencia", "closed_seq", "INTEGER NOT NULL DEFAULT 0")
    _add_column_if_missing(conn, "ordens_producao_bobina_pendencia", "closed_abs_pcs", "INTEGER NOT NULL DEFAULT 0")
    _add_column_if_missing(conn, "ordens_producao_bobina_pendencia", "next_seq", "INTEGER NOT NULL DEFAULT 0")
    _add_column_if_missing(conn, "ordens_producao_bobina_pendencia", "created_at", "TEXT")
    _add_column_if_missing(conn, "ordens_producao_bobina_pendencia", "updated_at", "TEXT")

    cur.execute("CREATE INDEX IF NOT EXISTS ix_op_bobina_pend_opid ON ordens_producao_bobina_pendencia(op_id)")


    conn.commit()
    conn.close()
##
