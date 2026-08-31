# Caminho: C:\Users\vlula\OneDrive\Área de Trabalho\Projetos Backup\GESTFLOW\apps\indflow\modules\db_indflow.py
# Último recode: 2026-08-31 13:45 (America/Bahia)
# Motivo: Isolar configuracao e estado de parada por cliente + maquina, com backfill apenas quando o proprietario estiver comprovado por device ativo.

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


def _active_device_owner_for_machine(conn: sqlite3.Connection, machine_id: str) -> str | None:
    """Retorna o unico cliente ativo comprovado por device para a maquina.

    Se nao houver device, houver mais de um dono, ou o cliente nao estiver ativo,
    nao assume propriedade. Isso impede adotar registros historicos ambiguos.
    """
    mid = (machine_id or "").strip().lower()
    if not mid or not _table_exists(conn, "devices") or not _table_exists(conn, "clientes"):
        return None

    try:
        rows = conn.execute(
            """
            SELECT DISTINCT TRIM(d.cliente_id) AS cliente_id
            FROM devices d
            JOIN clientes c ON c.id = d.cliente_id
            WHERE lower(trim(COALESCE(d.machine_id,''))) = ?
              AND TRIM(COALESCE(d.cliente_id,'')) <> ''
              AND lower(trim(COALESCE(c.status,''))) = 'active'
            """,
            (mid,),
        ).fetchall()
    except Exception:
        return None

    owners = [str(r[0]).strip() for r in rows if r and r[0] and str(r[0]).strip()]
    return owners[0] if len(owners) == 1 else None


def _backfill_proven_machine_owners(conn: sqlite3.Connection) -> None:
    """Migra apenas registros cuja propriedade possa ser provada por devices.

    - Nao altera IDs historicos orfaos.
    - Nao atribui maquinas sem device.
    - Nao sobrescreve config tenant ja existente.
    - Mantem as tabelas legadas intactas para auditoria/rollback.
    """
    if _table_exists(conn, "machine_config") and _table_exists(conn, "machine_config_tenant"):
        try:
            rows = conn.execute(
                """
                SELECT machine_id, meta_turno, turno_inicio, turno_fim,
                       rampa_percentual, horas_turno_json, meta_por_hora_json,
                       unidade_1, unidade_2, conv_m_por_pcs,
                       alerta_sem_contagem_seg, config_json, updated_at,
                       cliente_id
                FROM machine_config
                """
            ).fetchall()
        except Exception:
            rows = []

        for row in rows:
            mid = str(row[0] or "").strip().lower()
            if not mid:
                continue
            owner = _active_device_owner_for_machine(conn, mid)
            if not owner:
                continue

            legacy_owner = str(row[13] or "").strip()
            if legacy_owner and legacy_owner != owner:
                continue

            conn.execute(
                """
                UPDATE machine_config
                SET cliente_id=?
                WHERE machine_id=?
                  AND (cliente_id IS NULL OR TRIM(cliente_id)='')
                """,
                (owner, row[0]),
            )
            conn.execute(
                """
                INSERT OR IGNORE INTO machine_config_tenant (
                    cliente_id, machine_id, meta_turno, turno_inicio, turno_fim,
                    rampa_percentual, horas_turno_json, meta_por_hora_json,
                    unidade_1, unidade_2, conv_m_por_pcs,
                    alerta_sem_contagem_seg, config_json, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    owner, mid, int(row[1] or 0), row[2], row[3], int(row[4] or 0),
                    row[5] or "[]", row[6] or "[]", row[7], row[8], row[9],
                    row[10], row[11], row[12] or "",
                ),
            )

    if _table_exists(conn, "machine_stop") and _table_exists(conn, "machine_stop_tenant"):
        try:
            rows = conn.execute(
                "SELECT machine_id, stopped_since_ms, updated_at FROM machine_stop"
            ).fetchall()
        except Exception:
            rows = []

        for row in rows:
            mid = str(row[0] or "").strip().lower()
            if not mid or "::" in mid:
                continue
            owner = _active_device_owner_for_machine(conn, mid)
            if not owner:
                continue
            conn.execute(
                """
                INSERT OR IGNORE INTO machine_stop_tenant
                    (cliente_id, machine_id, stopped_since_ms, updated_at)
                VALUES (?, ?, ?, ?)
                """,
                (owner, mid, int(row[1] or 0), row[2] or ""),
            )


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
    # A tabela antiga e preservada para compatibilidade/auditoria. Novas gravacoes
    # autenticadas usam machine_config_tenant, cuja chave e cliente + maquina.
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
    _add_column_if_missing(conn, "machine_config", "unidade_1", "TEXT")
    _add_column_if_missing(conn, "machine_config", "unidade_2", "TEXT")
    _add_column_if_missing(conn, "machine_config", "conv_m_por_pcs", "REAL")
    _add_column_if_missing(conn, "machine_config", "alerta_sem_contagem_seg", "INTEGER")
    cur.execute("CREATE INDEX IF NOT EXISTS ix_machine_config_cliente_id ON machine_config(cliente_id)")

    cur.execute("""
        CREATE TABLE IF NOT EXISTS machine_config_tenant (
            cliente_id TEXT NOT NULL,
            machine_id TEXT NOT NULL,
            meta_turno INTEGER NOT NULL DEFAULT 0,
            turno_inicio TEXT,
            turno_fim TEXT,
            rampa_percentual INTEGER NOT NULL DEFAULT 0,
            horas_turno_json TEXT NOT NULL DEFAULT '[]',
            meta_por_hora_json TEXT NOT NULL DEFAULT '[]',
            unidade_1 TEXT,
            unidade_2 TEXT,
            conv_m_por_pcs REAL,
            alerta_sem_contagem_seg INTEGER,
            config_json TEXT,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (cliente_id, machine_id)
        )
    """)
    cur.execute(
        "CREATE INDEX IF NOT EXISTS ix_machine_config_tenant_machine_id "
        "ON machine_config_tenant(machine_id)"
    )

    # -------------------- machine_stop --------------------
    # machine_stop e mantida somente como legado. Todo fluxo autenticado passa a
    # usar machine_stop_tenant para impedir colisao de nomes entre empresas.
    cur.execute("""
        CREATE TABLE IF NOT EXISTS machine_stop (
            machine_id TEXT PRIMARY KEY,
            stopped_since_ms INTEGER NOT NULL,
            updated_at TEXT NOT NULL
        )
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS ix_machine_stop_updated_at ON machine_stop(updated_at)")
    cur.execute("""
        CREATE TABLE IF NOT EXISTS machine_stop_tenant (
            cliente_id TEXT NOT NULL,
            machine_id TEXT NOT NULL,
            stopped_since_ms INTEGER NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (cliente_id, machine_id)
        )
    """)
    cur.execute(
        "CREATE INDEX IF NOT EXISTS ix_machine_stop_tenant_updated_at "
        "ON machine_stop_tenant(updated_at)"
    )

    # Adota apenas configuracao/STOP cujo dono pode ser provado pelo device.
    _backfill_proven_machine_owners(conn)

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

    try:
        _dedupe_keep_latest(conn, "producao_horaria", ["machine_id", "data_ref", "hora_idx"])
    except Exception:
        pass

    cur.execute("DROP INDEX IF EXISTS ux_producao_horaria")
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

    try:
        _dedupe_keep_latest(conn, "baseline_diario", ["machine_id", "dia_ref"])
    except Exception:
        pass

    cur.execute("DROP INDEX IF EXISTS ux_baseline_diario")
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

    if _table_exists(conn, "machine_state_event"):
        _add_column_if_missing(conn, "machine_state_event", "machine_id", "TEXT")
        _add_column_if_missing(conn, "machine_state_event", "cliente_id", "TEXT")
        _add_column_if_missing(conn, "machine_state_event", "ts_iso", "TEXT")
        _add_column_if_missing(conn, "machine_state_event", "hora_idx", "INTEGER")

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

    # Aplica guards de compatibilidade somente depois do schema estar pronto.
    # Em imports iniciais alguns modulos ainda podem nao existir; a chamada e
    # repetida pelo server.init_db() e e idempotente.
    try:
        from modules.tenant_runtime_safety import install_runtime_guards
        install_runtime_guards()
    except Exception:
        pass
##
