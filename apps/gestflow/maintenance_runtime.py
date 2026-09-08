# Caminho: C:\Users\vlula\OneDrive\Área de Trabalho\Projetos Backup\GESTFLOW\apps\gestflow\maintenance_runtime.py
# Último recode: 2026-09-08 06:00 (America/Bahia)
# Motivo: Integrar Manutenção aos Módulos do Sistema, respeitando ativação, menu lateral, acesso direto, permissões e perfil Serviços / Manutenção.

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any
import urllib.parse


STATUS_ORDEM = {
    "aberta": "Aberta",
    "em_atendimento": "Em atendimento",
    "aguardando_peca": "Aguardando peça",
    "concluida": "Concluída",
    "cancelada": "Cancelada",
}

PRIORIDADES = {
    "baixa": "Baixa",
    "media": "Média",
    "alta": "Alta",
    "critica": "Crítica",
}

TIPOS_PLANO = {
    "preventiva": "Preventiva",
    "preditiva": "Preditiva",
}

PERIODICIDADES = {
    "dias": "Dias",
    "horas": "Horas de máquina",
    "pecas": "Peças produzidas",
}


MODULO_MANUTENCAO = {
    "codigo": "manutencao",
    "nome": "Manutenção",
    "grupo": "Industrial",
    "descricao": "Preventivas, preditivas, corretivas, OS e histórico de manutenção por equipamento.",
}


def _registrar_modulo_sistema(runtime: Any) -> None:
    codigo = MODULO_MANUTENCAO["codigo"]

    modulos = getattr(runtime, "GESTFLOW_MODULOS", None)
    if isinstance(modulos, list) and not any(
        _texto(item.get("codigo")) == codigo
        for item in modulos
        if isinstance(item, dict)
    ):
        indice = next(
            (
                posicao + 1
                for posicao, item in enumerate(modulos)
                if isinstance(item, dict) and _texto(item.get("codigo")) == "equipamentos"
            ),
            len(modulos),
        )
        modulos.insert(indice, dict(MODULO_MANUTENCAO))

    padrao = getattr(runtime, "GESTFLOW_MODULOS_PADRAO", None)
    if isinstance(padrao, dict):
        padrao[codigo] = True

    codigos = getattr(runtime, "GESTFLOW_MODULOS_CODIGOS", None)
    if isinstance(codigos, set):
        codigos.add(codigo)

    especializados = getattr(runtime, "GESTFLOW_MODULOS_ESPECIALIZADOS", None)
    if isinstance(especializados, set):
        especializados.add(codigo)

    operacionais = getattr(runtime, "GESTFLOW_MODULOS_OPERACIONAIS", None)
    if isinstance(operacionais, set):
        operacionais.discard(codigo)

    permissoes_modulos = getattr(runtime, "GESTFLOW_MODULOS_PERMISSOES", None)
    if isinstance(permissoes_modulos, list) and not any(
        _texto(item.get("codigo")) == codigo
        for item in permissoes_modulos
        if isinstance(item, dict)
    ):
        indice_config = next(
            (
                posicao
                for posicao, item in enumerate(permissoes_modulos)
                if isinstance(item, dict) and _texto(item.get("codigo")) == "configuracoes"
            ),
            len(permissoes_modulos),
        )
        permissoes_modulos.insert(indice_config, dict(MODULO_MANUTENCAO))

    perfis_modulos = getattr(runtime, "GESTFLOW_PERFIS_MODULOS", None)
    if isinstance(perfis_modulos, dict):
        for perfil in ("assistencia", "industrial", "completo"):
            modulos_perfil = perfis_modulos.get(perfil)
            if isinstance(modulos_perfil, set):
                modulos_perfil.add(codigo)

    permissoes_perfil = getattr(runtime, "GESTFLOW_PERMISSOES_PADRAO_PERFIL", None)
    if isinstance(permissoes_perfil, dict):
        tecnico = permissoes_perfil.get("tecnico")
        if isinstance(tecnico, dict):
            tecnico[codigo] = set(getattr(runtime, "_ACOES_OPERACAO", {"visualizar", "criar", "editar"}))
        consulta = permissoes_perfil.get("consulta")
        if isinstance(consulta, dict):
            consulta[codigo] = set(getattr(runtime, "_ACOES_LEITURA", {"visualizar"}))

    modulo_por_rota_original = getattr(runtime, "modulo_por_rota", None)
    if callable(modulo_por_rota_original) and not hasattr(runtime, "_manutencao_modulo_por_rota_original"):
        runtime._manutencao_modulo_por_rota_original = modulo_por_rota_original

        def modulo_por_rota_com_manutencao(path: str) -> str:
            caminho = _texto(path)
            if caminho == "/manutencao" or caminho.startswith("/manutencao/"):
                return codigo
            return runtime._manutencao_modulo_por_rota_original(path)

        runtime.modulo_por_rota = modulo_por_rota_com_manutencao

    modulo_por_rota_admin_original = getattr(runtime, "modulo_por_rota_admin", None)
    if callable(modulo_por_rota_admin_original) and not hasattr(runtime, "_manutencao_modulo_por_rota_admin_original"):
        runtime._manutencao_modulo_por_rota_admin_original = modulo_por_rota_admin_original

        def modulo_por_rota_admin_com_manutencao(path: str) -> str | None:
            caminho = _texto(path)
            if caminho == "/manutencao" or caminho.startswith("/manutencao/"):
                return codigo
            return runtime._manutencao_modulo_por_rota_admin_original(path)

        runtime.modulo_por_rota_admin = modulo_por_rota_admin_com_manutencao


def _texto(valor: Any) -> str:
    return str(valor or "").strip()


def _inteiro(valor: Any, padrao: int = 0) -> int:
    try:
        return int(str(valor or "").strip())
    except (TypeError, ValueError):
        return padrao


def _decimal_texto(valor: Any) -> float:
    texto = (_texto(valor).replace(".", "").replace(",", ".") if "," in _texto(valor) else _texto(valor))
    try:
        return max(0.0, float(texto))
    except (TypeError, ValueError):
        return 0.0


def _data_iso(valor: Any) -> str:
    texto = _texto(valor)
    if not texto:
        return ""
    try:
        return date.fromisoformat(texto[:10]).isoformat()
    except (TypeError, ValueError):
        return ""


def _agora(runtime: Any) -> datetime:
    if hasattr(runtime, "agora_empresa"):
        try:
            return runtime.agora_empresa()
        except Exception:
            pass
    return datetime.now()


def _hoje(runtime: Any) -> date:
    if hasattr(runtime, "hoje_empresa"):
        try:
            return runtime.hoje_empresa()
        except Exception:
            pass
    return _agora(runtime).date()


def _empresa_id(runtime: Any) -> int:
    return int(runtime.empresa_logada_id())


def _equipamentos(runtime: Any) -> list[dict[str, Any]]:
    try:
        itens = runtime.listar_equipamentos_cadastrados()
    except Exception:
        itens = []
    return [dict(item) for item in itens]


def _funcionarios(runtime: Any) -> list[dict[str, Any]]:
    try:
        itens = runtime.listar_funcionarios()
    except Exception:
        return []
    retorno = []
    for item in itens:
        registro = dict(item)
        status = _texto(registro.get("status")).lower()
        if status in {"", "ativo"}:
            retorno.append(registro)
    return retorno


def _equipamento_empresa(runtime: Any, equipamento_id: int) -> dict[str, Any] | None:
    if equipamento_id <= 0:
        return None
    empresa_id = _empresa_id(runtime)
    with runtime.conectar_db() as conn:
        row = conn.execute(
            """
            SELECT id, empresa_id, cliente_nome, nome, marca, modelo, serie, tag,
                   local_instalacao, status
            FROM equipamentos
            WHERE id = ? AND empresa_id = ?
            """,
            (equipamento_id, empresa_id),
        ).fetchone()
    return dict(row) if row is not None else None


def _registrar_atividade(runtime: Any, acao: str, descricao: str, registro_id: int | None = None) -> None:
    if not hasattr(runtime, "registrar_atividade_usuario"):
        return
    try:
        runtime.registrar_atividade_usuario(
            acao,
            "manutencao",
            descricao,
            runtime.request.path,
            registro_id=registro_id,
        )
    except Exception:
        return


def _registrar_historico(
    runtime: Any,
    *,
    entidade_tipo: str,
    entidade_id: int,
    acao: str,
    descricao: str,
    equipamento_id: int | None = None,
) -> None:
    empresa_id = _empresa_id(runtime)
    usuario_nome = _texto(runtime.session.get("usuario_nome") or runtime.session.get("nome"))
    ocorrido_em = _agora(runtime).isoformat(timespec="seconds")
    with runtime.conectar_db() as conn:
        conn.execute(
            """
            INSERT INTO manutencao_historico (
                empresa_id, equipamento_id, entidade_tipo, entidade_id,
                acao, descricao, usuario_nome, ocorrido_em
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                empresa_id,
                equipamento_id,
                entidade_tipo,
                entidade_id,
                acao,
                descricao,
                usuario_nome,
                ocorrido_em,
            ),
        )
        conn.commit()


def _garantir_tabelas(runtime: Any) -> None:
    with runtime.conectar_db() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS manutencao_planos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                empresa_id INTEGER NOT NULL,
                equipamento_id INTEGER NOT NULL,
                tipo TEXT NOT NULL DEFAULT 'preventiva',
                titulo TEXT NOT NULL,
                descricao TEXT,
                periodicidade_tipo TEXT NOT NULL DEFAULT 'dias',
                periodicidade_valor INTEGER NOT NULL DEFAULT 30,
                proxima_execucao TEXT,
                ultima_execucao TEXT,
                responsavel_id INTEGER,
                responsavel_nome TEXT,
                criticidade TEXT DEFAULT 'media',
                status TEXT NOT NULL DEFAULT 'ativo',
                criado_em TEXT,
                atualizado_em TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS manutencao_ordens (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                empresa_id INTEGER NOT NULL,
                numero TEXT,
                equipamento_id INTEGER NOT NULL,
                tipo TEXT NOT NULL,
                origem_plano_id INTEGER,
                titulo TEXT NOT NULL,
                descricao TEXT,
                prioridade TEXT NOT NULL DEFAULT 'media',
                status TEXT NOT NULL DEFAULT 'aberta',
                maquina_parada INTEGER NOT NULL DEFAULT 0,
                responsavel_id INTEGER,
                responsavel_nome TEXT,
                prevista_em TEXT,
                aberta_em TEXT,
                iniciada_em TEXT,
                concluida_em TEXT,
                causa TEXT,
                solucao TEXT,
                observacoes TEXT,
                custo_total REAL NOT NULL DEFAULT 0,
                criado_em TEXT,
                atualizado_em TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS manutencao_historico (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                empresa_id INTEGER NOT NULL,
                equipamento_id INTEGER,
                entidade_tipo TEXT NOT NULL,
                entidade_id INTEGER NOT NULL,
                acao TEXT NOT NULL,
                descricao TEXT,
                usuario_nome TEXT,
                ocorrido_em TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_manutencao_planos_empresa
            ON manutencao_planos (empresa_id, tipo, status, proxima_execucao)
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_manutencao_ordens_empresa
            ON manutencao_ordens (empresa_id, tipo, status, equipamento_id)
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_manutencao_historico_empresa
            ON manutencao_historico (empresa_id, ocorrido_em)
            """
        )
        conn.commit()


def _responsavel_form(runtime: Any) -> tuple[int | None, str]:
    responsavel_id = _inteiro(runtime.request.form.get("responsavel_id"), 0)
    if responsavel_id <= 0:
        return None, ""
    empresa_id = _empresa_id(runtime)
    with runtime.conectar_db() as conn:
        row = conn.execute(
            """
            SELECT id, nome
            FROM funcionarios
            WHERE id = ? AND empresa_id = ?
            """,
            (responsavel_id, empresa_id),
        ).fetchone()
    if row is None:
        return None, ""
    return int(row["id"]), _texto(row["nome"])


def _proxima_por_periodicidade(
    runtime: Any,
    periodicidade_tipo: str,
    periodicidade_valor: int,
    informada: str,
    base: date | None = None,
) -> str:
    if informada:
        return informada
    if periodicidade_tipo != "dias":
        return ""
    data_base = base or _hoje(runtime)
    return (data_base + timedelta(days=max(1, periodicidade_valor))).isoformat()


def _buscar_planos(runtime: Any, tipo: str) -> list[dict[str, Any]]:
    empresa_id = _empresa_id(runtime)
    with runtime.conectar_db() as conn:
        rows = conn.execute(
            """
            SELECT
                p.*,
                e.nome AS equipamento_nome,
                e.tag AS equipamento_tag,
                e.local_instalacao AS equipamento_local
            FROM manutencao_planos p
            JOIN equipamentos e
              ON e.id = p.equipamento_id
             AND e.empresa_id = p.empresa_id
            WHERE p.empresa_id = ?
              AND p.tipo = ?
            ORDER BY
                CASE WHEN p.status = 'ativo' THEN 0 ELSE 1 END,
                CASE WHEN COALESCE(p.proxima_execucao, '') = '' THEN 1 ELSE 0 END,
                p.proxima_execucao ASC,
                p.id DESC
            """,
            (empresa_id, tipo),
        ).fetchall()
    hoje = _hoje(runtime)
    retorno = []
    for row in rows:
        item = dict(row)
        proxima = _data_iso(item.get("proxima_execucao"))
        situacao = "sem_data"
        if _texto(item.get("status")).lower() != "ativo":
            situacao = "inativo"
        elif proxima:
            data_proxima = date.fromisoformat(proxima)
            if data_proxima < hoje:
                situacao = "vencida"
            elif data_proxima <= hoje + timedelta(days=7):
                situacao = "proxima"
            else:
                situacao = "programada"
        item["situacao"] = situacao
        retorno.append(item)
    return retorno


def _buscar_ordens(runtime: Any, tipo: str = "", limite: int | None = None) -> list[dict[str, Any]]:
    empresa_id = _empresa_id(runtime)
    filtros = ["o.empresa_id = ?"]
    params: list[Any] = [empresa_id]
    if tipo:
        filtros.append("o.tipo = ?")
        params.append(tipo)
    limite_sql = ""
    if limite is not None and limite > 0:
        limite_sql = f" LIMIT {int(limite)}"
    with runtime.conectar_db() as conn:
        rows = conn.execute(
            f"""
            SELECT
                o.*,
                e.nome AS equipamento_nome,
                e.tag AS equipamento_tag,
                e.local_instalacao AS equipamento_local
            FROM manutencao_ordens o
            JOIN equipamentos e
              ON e.id = o.equipamento_id
             AND e.empresa_id = o.empresa_id
            WHERE {' AND '.join(filtros)}
            ORDER BY
                CASE o.status
                    WHEN 'em_atendimento' THEN 0
                    WHEN 'aguardando_peca' THEN 1
                    WHEN 'aberta' THEN 2
                    WHEN 'concluida' THEN 3
                    ELSE 4
                END,
                o.id DESC
            {limite_sql}
            """,
            params,
        ).fetchall()
    return [dict(row) for row in rows]


def _buscar_historico(runtime: Any, limite: int = 250) -> list[dict[str, Any]]:
    empresa_id = _empresa_id(runtime)
    with runtime.conectar_db() as conn:
        rows = conn.execute(
            """
            SELECT
                h.*,
                e.nome AS equipamento_nome,
                e.tag AS equipamento_tag
            FROM manutencao_historico h
            LEFT JOIN equipamentos e
              ON e.id = h.equipamento_id
             AND e.empresa_id = h.empresa_id
            WHERE h.empresa_id = ?
            ORDER BY h.id DESC
            LIMIT ?
            """,
            (empresa_id, max(1, limite)),
        ).fetchall()
    return [dict(row) for row in rows]


def _contexto_base(runtime: Any, secao: str) -> dict[str, Any]:
    return {
        "secao": secao,
        "equipamentos": _equipamentos(runtime),
        "funcionarios": _funcionarios(runtime),
        "status_ordem": STATUS_ORDEM,
        "prioridades": PRIORIDADES,
        "tipos_plano": TIPOS_PLANO,
        "periodicidades": PERIODICIDADES,
        "erro": _texto(runtime.request.args.get("erro")),
        "sucesso": _texto(runtime.request.args.get("sucesso")),
    }


def _redirecionar(runtime: Any, destino: str, *, sucesso: str = "", erro: str = ""):
    params = {}
    if sucesso:
        params["sucesso"] = sucesso
    if erro:
        params["erro"] = erro
    if params:
        destino += ("&" if "?" in destino else "?") + urllib.parse.urlencode(params)
    return runtime.redirect(destino)


def _dashboard(runtime: Any):
    empresa_id = _empresa_id(runtime)
    hoje = _hoje(runtime)
    semana = (hoje + timedelta(days=7)).isoformat()
    hoje_iso = hoje.isoformat()
    with runtime.conectar_db() as conn:
        indicadores = {
            "equipamentos": int(
                conn.execute(
                    """
                    SELECT COUNT(*) AS total
                    FROM equipamentos
                    WHERE empresa_id = ?
                      AND LOWER(COALESCE(status, 'ativo')) <> 'baixado'
                    """,
                    (empresa_id,),
                ).fetchone()["total"]
                or 0
            ),
            "ordens_abertas": int(
                conn.execute(
                    """
                    SELECT COUNT(*) AS total
                    FROM manutencao_ordens
                    WHERE empresa_id = ?
                      AND status NOT IN ('concluida', 'cancelada')
                    """,
                    (empresa_id,),
                ).fetchone()["total"]
                or 0
            ),
            "corretivas_abertas": int(
                conn.execute(
                    """
                    SELECT COUNT(*) AS total
                    FROM manutencao_ordens
                    WHERE empresa_id = ?
                      AND tipo = 'corretiva'
                      AND status NOT IN ('concluida', 'cancelada')
                    """,
                    (empresa_id,),
                ).fetchone()["total"]
                or 0
            ),
            "planos_vencidos": int(
                conn.execute(
                    """
                    SELECT COUNT(*) AS total
                    FROM manutencao_planos
                    WHERE empresa_id = ?
                      AND status = 'ativo'
                      AND COALESCE(proxima_execucao, '') <> ''
                      AND proxima_execucao < ?
                    """,
                    (empresa_id, hoje_iso),
                ).fetchone()["total"]
                or 0
            ),
            "planos_proximos": int(
                conn.execute(
                    """
                    SELECT COUNT(*) AS total
                    FROM manutencao_planos
                    WHERE empresa_id = ?
                      AND status = 'ativo'
                      AND COALESCE(proxima_execucao, '') <> ''
                      AND proxima_execucao BETWEEN ? AND ?
                    """,
                    (empresa_id, hoje_iso, semana),
                ).fetchone()["total"]
                or 0
            ),
        }

        proximos = [
            dict(row)
            for row in conn.execute(
                """
                SELECT
                    p.*,
                    e.nome AS equipamento_nome,
                    e.tag AS equipamento_tag
                FROM manutencao_planos p
                JOIN equipamentos e
                  ON e.id = p.equipamento_id
                 AND e.empresa_id = p.empresa_id
                WHERE p.empresa_id = ?
                  AND p.status = 'ativo'
                ORDER BY
                    CASE WHEN COALESCE(p.proxima_execucao, '') = '' THEN 1 ELSE 0 END,
                    p.proxima_execucao ASC,
                    p.id DESC
                LIMIT 8
                """,
                (empresa_id,),
            ).fetchall()
        ]

    contexto = _contexto_base(runtime, "dashboard")
    contexto.update(
        {
            "indicadores": indicadores,
            "proximos_planos": proximos,
            "ordens": _buscar_ordens(runtime, limite=8),
        }
    )
    return runtime.render_template("manutencao.html", **contexto)


def _equipamentos_pagina(runtime: Any):
    contexto = _contexto_base(runtime, "equipamentos")
    return runtime.render_template("manutencao.html", **contexto)


def _planos_pagina(runtime: Any, tipo: str):
    if tipo not in TIPOS_PLANO:
        return runtime.redirect("/manutencao")

    if runtime.request.method == "POST":
        equipamento_id = _inteiro(runtime.request.form.get("equipamento_id"), 0)
        equipamento = _equipamento_empresa(runtime, equipamento_id)
        titulo = _texto(runtime.request.form.get("titulo"))
        descricao = _texto(runtime.request.form.get("descricao"))
        periodicidade_tipo = _texto(runtime.request.form.get("periodicidade_tipo")).lower()
        periodicidade_valor = max(1, _inteiro(runtime.request.form.get("periodicidade_valor"), 1))
        proxima_execucao = _data_iso(runtime.request.form.get("proxima_execucao"))
        criticidade = _texto(runtime.request.form.get("criticidade")).lower() or "media"
        responsavel_id, responsavel_nome = _responsavel_form(runtime)

        if equipamento is None:
            return _redirecionar(runtime, f"/manutencao/{tipo}s", erro="Selecione um equipamento válido.")
        if not titulo:
            return _redirecionar(runtime, f"/manutencao/{tipo}s", erro="Informe o serviço planejado.")
        if periodicidade_tipo not in PERIODICIDADES:
            periodicidade_tipo = "dias"
        if criticidade not in PRIORIDADES:
            criticidade = "media"

        proxima_execucao = _proxima_por_periodicidade(
            runtime,
            periodicidade_tipo,
            periodicidade_valor,
            proxima_execucao,
        )
        agora = _agora(runtime).isoformat(timespec="seconds")
        empresa_id = _empresa_id(runtime)

        with runtime.conectar_db() as conn:
            cursor = conn.execute(
                """
                INSERT INTO manutencao_planos (
                    empresa_id, equipamento_id, tipo, titulo, descricao,
                    periodicidade_tipo, periodicidade_valor, proxima_execucao,
                    responsavel_id, responsavel_nome, criticidade, status,
                    criado_em, atualizado_em
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'ativo', ?, ?)
                """,
                (
                    empresa_id,
                    equipamento_id,
                    tipo,
                    titulo,
                    descricao,
                    periodicidade_tipo,
                    periodicidade_valor,
                    proxima_execucao,
                    responsavel_id,
                    responsavel_nome,
                    criticidade,
                    agora,
                    agora,
                ),
            )
            plano_id = int(cursor.lastrowid)
            conn.commit()

        rotulo = TIPOS_PLANO[tipo]
        _registrar_historico(
            runtime,
            entidade_tipo="plano",
            entidade_id=plano_id,
            acao="criacao",
            descricao=f"{rotulo} criada: {titulo}",
            equipamento_id=equipamento_id,
        )
        _registrar_atividade(runtime, "criacao", f"Criou {rotulo.lower()} {titulo}", plano_id)
        return _redirecionar(runtime, f"/manutencao/{tipo}s", sucesso=f"{rotulo} programada com sucesso.")

    contexto = _contexto_base(runtime, f"{tipo}s")
    contexto.update({"tipo_plano": tipo, "planos": _buscar_planos(runtime, tipo)})
    return runtime.render_template("manutencao.html", **contexto)


def _criar_ordem(
    runtime: Any,
    *,
    equipamento_id: int,
    tipo: str,
    titulo: str,
    descricao: str,
    prioridade: str,
    maquina_parada: bool,
    responsavel_id: int | None,
    responsavel_nome: str,
    prevista_em: str,
    origem_plano_id: int | None = None,
) -> int:
    empresa_id = _empresa_id(runtime)
    agora = _agora(runtime).isoformat(timespec="seconds")
    with runtime.conectar_db() as conn:
        cursor = conn.execute(
            """
            INSERT INTO manutencao_ordens (
                empresa_id, numero, equipamento_id, tipo, origem_plano_id,
                titulo, descricao, prioridade, status, maquina_parada,
                responsavel_id, responsavel_nome, prevista_em, aberta_em,
                criado_em, atualizado_em
            )
            VALUES (?, '', ?, ?, ?, ?, ?, ?, 'aberta', ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                empresa_id,
                equipamento_id,
                tipo,
                origem_plano_id,
                titulo,
                descricao,
                prioridade,
                1 if maquina_parada else 0,
                responsavel_id,
                responsavel_nome,
                prevista_em,
                agora,
                agora,
                agora,
            ),
        )
        ordem_id = int(cursor.lastrowid)
        numero = f"MAN-{ordem_id:06d}"
        conn.execute(
            "UPDATE manutencao_ordens SET numero = ? WHERE id = ? AND empresa_id = ?",
            (numero, ordem_id, empresa_id),
        )
        conn.commit()
    return ordem_id


def _corretivas_pagina(runtime: Any):
    if runtime.request.method == "POST":
        equipamento_id = _inteiro(runtime.request.form.get("equipamento_id"), 0)
        equipamento = _equipamento_empresa(runtime, equipamento_id)
        titulo = _texto(runtime.request.form.get("titulo"))
        descricao = _texto(runtime.request.form.get("descricao"))
        prioridade = _texto(runtime.request.form.get("prioridade")).lower() or "alta"
        maquina_parada = _texto(runtime.request.form.get("maquina_parada")) == "1"
        responsavel_id, responsavel_nome = _responsavel_form(runtime)

        if equipamento is None:
            return _redirecionar(runtime, "/manutencao/corretivas", erro="Selecione um equipamento válido.")
        if not titulo:
            return _redirecionar(runtime, "/manutencao/corretivas", erro="Informe o problema encontrado.")
        if prioridade not in PRIORIDADES:
            prioridade = "alta"

        ordem_id = _criar_ordem(
            runtime,
            equipamento_id=equipamento_id,
            tipo="corretiva",
            titulo=titulo,
            descricao=descricao,
            prioridade=prioridade,
            maquina_parada=maquina_parada,
            responsavel_id=responsavel_id,
            responsavel_nome=responsavel_nome,
            prevista_em="",
        )
        _registrar_historico(
            runtime,
            entidade_tipo="ordem",
            entidade_id=ordem_id,
            acao="abertura",
            descricao=f"Corretiva aberta: {titulo}",
            equipamento_id=equipamento_id,
        )
        _registrar_atividade(runtime, "criacao", f"Abriu corretiva {titulo}", ordem_id)
        return _redirecionar(runtime, "/manutencao/corretivas", sucesso="Corretiva aberta com sucesso.")

    contexto = _contexto_base(runtime, "corretivas")
    contexto["ordens"] = _buscar_ordens(runtime, tipo="corretiva")
    return runtime.render_template("manutencao.html", **contexto)


def _gerar_os_plano(runtime: Any, plano_id: int):
    empresa_id = _empresa_id(runtime)
    with runtime.conectar_db() as conn:
        row = conn.execute(
            """
            SELECT p.*, e.nome AS equipamento_nome
            FROM manutencao_planos p
            JOIN equipamentos e
              ON e.id = p.equipamento_id
             AND e.empresa_id = p.empresa_id
            WHERE p.id = ? AND p.empresa_id = ?
            """,
            (plano_id, empresa_id),
        ).fetchone()
    if row is None:
        return _redirecionar(runtime, "/manutencao", erro="Plano de manutenção não encontrado.")

    plano = dict(row)
    tipo = _texto(plano.get("tipo")).lower()
    destino = f"/manutencao/{tipo}s" if tipo in TIPOS_PLANO else "/manutencao"
    ordem_id = _criar_ordem(
        runtime,
        equipamento_id=int(plano["equipamento_id"]),
        tipo=tipo,
        titulo=_texto(plano["titulo"]),
        descricao=_texto(plano["descricao"]),
        prioridade=_texto(plano.get("criticidade")).lower() or "media",
        maquina_parada=False,
        responsavel_id=_inteiro(plano.get("responsavel_id"), 0) or None,
        responsavel_nome=_texto(plano.get("responsavel_nome")),
        prevista_em=_data_iso(plano.get("proxima_execucao")),
        origem_plano_id=plano_id,
    )
    _registrar_historico(
        runtime,
        entidade_tipo="ordem",
        entidade_id=ordem_id,
        acao="abertura",
        descricao=f"OS gerada pelo plano: {_texto(plano['titulo'])}",
        equipamento_id=int(plano["equipamento_id"]),
    )
    _registrar_atividade(runtime, "criacao", f"Gerou OS do plano {plano_id}", ordem_id)
    return _redirecionar(runtime, destino, sucesso="OS de manutenção gerada com sucesso.")


def _alternar_plano(runtime: Any, plano_id: int):
    empresa_id = _empresa_id(runtime)
    with runtime.conectar_db() as conn:
        row = conn.execute(
            """
            SELECT id, equipamento_id, tipo, titulo, status
            FROM manutencao_planos
            WHERE id = ? AND empresa_id = ?
            """,
            (plano_id, empresa_id),
        ).fetchone()
        if row is None:
            return _redirecionar(runtime, "/manutencao", erro="Plano não encontrado.")
        novo_status = "inativo" if _texto(row["status"]).lower() == "ativo" else "ativo"
        conn.execute(
            """
            UPDATE manutencao_planos
            SET status = ?, atualizado_em = ?
            WHERE id = ? AND empresa_id = ?
            """,
            (novo_status, _agora(runtime).isoformat(timespec="seconds"), plano_id, empresa_id),
        )
        conn.commit()

    tipo = _texto(row["tipo"]).lower()
    destino = f"/manutencao/{tipo}s" if tipo in TIPOS_PLANO else "/manutencao"
    _registrar_historico(
        runtime,
        entidade_tipo="plano",
        entidade_id=plano_id,
        acao="status",
        descricao=f"Plano {_texto(row['titulo'])}: {novo_status}",
        equipamento_id=int(row["equipamento_id"]),
    )
    return _redirecionar(runtime, destino, sucesso="Status do plano atualizado.")


def _ordens_pagina(runtime: Any):
    contexto = _contexto_base(runtime, "ordens")
    contexto["ordens"] = _buscar_ordens(runtime)
    return runtime.render_template("manutencao.html", **contexto)


def _atualizar_ordem(runtime: Any, ordem_id: int):
    empresa_id = _empresa_id(runtime)
    novo_status = _texto(runtime.request.form.get("status")).lower()
    if novo_status not in STATUS_ORDEM:
        return _redirecionar(runtime, "/manutencao/ordens", erro="Status inválido.")

    causa = _texto(runtime.request.form.get("causa"))
    solucao = _texto(runtime.request.form.get("solucao"))
    observacoes = _texto(runtime.request.form.get("observacoes"))
    custo_total = _decimal_texto(runtime.request.form.get("custo_total"))
    agora = _agora(runtime)
    agora_iso = agora.isoformat(timespec="seconds")

    with runtime.conectar_db() as conn:
        row = conn.execute(
            """
            SELECT *
            FROM manutencao_ordens
            WHERE id = ? AND empresa_id = ?
            """,
            (ordem_id, empresa_id),
        ).fetchone()
        if row is None:
            return _redirecionar(runtime, "/manutencao/ordens", erro="OS de manutenção não encontrada.")

        ordem = dict(row)
        iniciada_em = _texto(ordem.get("iniciada_em"))
        concluida_em = _texto(ordem.get("concluida_em"))
        if novo_status == "em_atendimento" and not iniciada_em:
            iniciada_em = agora_iso
        if novo_status == "concluida":
            concluida_em = agora_iso

        conn.execute(
            """
            UPDATE manutencao_ordens
            SET status = ?,
                iniciada_em = ?,
                concluida_em = ?,
                causa = ?,
                solucao = ?,
                observacoes = ?,
                custo_total = ?,
                atualizado_em = ?
            WHERE id = ? AND empresa_id = ?
            """,
            (
                novo_status,
                iniciada_em,
                concluida_em,
                causa,
                solucao,
                observacoes,
                custo_total,
                agora_iso,
                ordem_id,
                empresa_id,
            ),
        )

        plano_id = _inteiro(ordem.get("origem_plano_id"), 0)
        if novo_status == "concluida" and plano_id > 0:
            plano = conn.execute(
                """
                SELECT id, periodicidade_tipo, periodicidade_valor
                FROM manutencao_planos
                WHERE id = ? AND empresa_id = ?
                """,
                (plano_id, empresa_id),
            ).fetchone()
            if plano is not None:
                proxima = ""
                if _texto(plano["periodicidade_tipo"]).lower() == "dias":
                    proxima = (
                        agora.date() + timedelta(days=max(1, _inteiro(plano["periodicidade_valor"], 1)))
                    ).isoformat()
                conn.execute(
                    """
                    UPDATE manutencao_planos
                    SET ultima_execucao = ?,
                        proxima_execucao = ?,
                        atualizado_em = ?
                    WHERE id = ? AND empresa_id = ?
                    """,
                    (agora.date().isoformat(), proxima, agora_iso, plano_id, empresa_id),
                )
        conn.commit()

    descricao_status = STATUS_ORDEM[novo_status]
    _registrar_historico(
        runtime,
        entidade_tipo="ordem",
        entidade_id=ordem_id,
        acao="status",
        descricao=f"{_texto(ordem.get('numero'))} alterada para {descricao_status}",
        equipamento_id=int(ordem["equipamento_id"]),
    )
    _registrar_atividade(runtime, "edicao", f"Atualizou {_texto(ordem.get('numero'))} para {descricao_status}", ordem_id)
    return _redirecionar(runtime, "/manutencao/ordens", sucesso="OS de manutenção atualizada.")


def _historico_pagina(runtime: Any):
    contexto = _contexto_base(runtime, "historico")
    contexto["historico"] = _buscar_historico(runtime)
    return runtime.render_template("manutencao.html", **contexto)


def _injetar_menu_manutencao(runtime: Any, response: Any):
    try:
        content_type = _texto(response.headers.get("Content-Type")).lower()
        if "text/html" not in content_type:
            return response

        html = response.get_data(as_text=True)
        caminho = _texto(runtime.request.path)

        if caminho == "/configuracoes/modulos":
            inicio_perfis = html.find("const perfis = {")
            if inicio_perfis >= 0:
                inicio_service = html.find("service: [", inicio_perfis)
                fim_service = html.find("]", inicio_service)
                if inicio_service >= 0 and fim_service > inicio_service:
                    trecho = html[inicio_service:fim_service]
                    if "'manutencao'" not in trecho:
                        html = html[:fim_service] + ", 'manutencao'" + html[fim_service:]

        modulo_ativo = True
        if hasattr(runtime, "modulo_empresa_ativo"):
            modulo_ativo = bool(runtime.modulo_empresa_ativo("manutencao"))

        modulo_visivel = True
        if hasattr(runtime, "modulo_usuario_visivel"):
            modulo_visivel = bool(runtime.modulo_usuario_visivel("manutencao"))

        if modulo_ativo and modulo_visivel and 'href="/manutencao"' not in html:
            marcador = "</ul>\n    </nav>"
            if marcador in html:
                active = " active" if caminho.startswith("/manutencao") else ""
                bloco = (
                    f'\n            <li class="menu-item{active}">\n'
                    '                <a href="/manutencao">\n'
                    '                    <span class="menu-icon">M</span>\n'
                    '                    <span>Manutenção</span>\n'
                    '                </a>\n'
                    '            </li>\n'
                )
                html = html.replace(marcador, bloco + "        " + marcador, 1)

        response.set_data(html)
        response.headers["Content-Length"] = str(len(response.get_data()))
    except Exception:
        return response
    return response


def instalar_modulo_manutencao(runtime: Any) -> None:
    _registrar_modulo_sistema(runtime)
    _garantir_tabelas(runtime)
    app = runtime.app

    app.add_url_rule("/manutencao", "manutencao_dashboard", lambda: _dashboard(runtime), methods=["GET"])
    app.add_url_rule(
        "/manutencao/equipamentos",
        "manutencao_equipamentos",
        lambda: _equipamentos_pagina(runtime),
        methods=["GET"],
    )
    app.add_url_rule(
        "/manutencao/preventivas",
        "manutencao_preventivas",
        lambda: _planos_pagina(runtime, "preventiva"),
        methods=["GET", "POST"],
    )
    app.add_url_rule(
        "/manutencao/preditivas",
        "manutencao_preditivas",
        lambda: _planos_pagina(runtime, "preditiva"),
        methods=["GET", "POST"],
    )
    app.add_url_rule(
        "/manutencao/corretivas",
        "manutencao_corretivas",
        lambda: _corretivas_pagina(runtime),
        methods=["GET", "POST"],
    )
    app.add_url_rule(
        "/manutencao/planos/<int:plano_id>/gerar-os",
        "manutencao_gerar_os_plano",
        lambda plano_id: _gerar_os_plano(runtime, plano_id),
        methods=["POST"],
    )
    app.add_url_rule(
        "/manutencao/planos/<int:plano_id>/status",
        "manutencao_status_plano",
        lambda plano_id: _alternar_plano(runtime, plano_id),
        methods=["POST"],
    )
    app.add_url_rule(
        "/manutencao/ordens",
        "manutencao_ordens",
        lambda: _ordens_pagina(runtime),
        methods=["GET"],
    )
    app.add_url_rule(
        "/manutencao/ordens/<int:ordem_id>/status",
        "manutencao_atualizar_ordem",
        lambda ordem_id: _atualizar_ordem(runtime, ordem_id),
        methods=["POST"],
    )
    app.add_url_rule(
        "/manutencao/historico",
        "manutencao_historico",
        lambda: _historico_pagina(runtime),
        methods=["GET"],
    )
    app.after_request(lambda response: _injetar_menu_manutencao(runtime, response))
