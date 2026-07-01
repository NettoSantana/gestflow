# Caminho: C:\Users\vlula\OneDrive\Área de Trabalho\Projetos Backup\GESTFLOW\app.py
# Último recode: 2026-07-01 18:55 (America/Bahia)
# Motivo: Criar Assistente IA flutuante interno do GestFlow.

from __future__ import annotations

import html
import json
import os
import re
import secrets
import sqlite3
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from flask import Flask, Response, jsonify, redirect, render_template, request, send_from_directory, session, url_for

from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename

import config

app = Flask(__name__)
app.secret_key = getattr(config, "SECRET_KEY", "gestflow-dev-secret-key-trocar-em-producao")

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = DATA_DIR / "gestflow.db"

UPLOAD_DIR = DATA_DIR / "uploads" / "logos"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
OS_FOTOS_DIR = DATA_DIR / "uploads" / "os_fotos"
OS_FOTOS_DIR.mkdir(parents=True, exist_ok=True)
EXTENSOES_LOGO_PERMITIDAS = {"png", "jpg", "jpeg", "webp", "gif"}
EXTENSOES_FOTO_OS_PERMITIDAS = {"png", "jpg", "jpeg", "webp"}

TIMEZONE_PADRAO_GESTFLOW = "America/Bahia"
FUSOS_HORARIOS_GESTFLOW = [
    {"valor": "America/Bahia", "nome": "Bahia / Brasil"},
    {"valor": "America/Sao_Paulo", "nome": "Brasília / São Paulo"},
    {"valor": "America/Recife", "nome": "Recife"},
    {"valor": "America/Fortaleza", "nome": "Fortaleza"},
    {"valor": "America/Manaus", "nome": "Manaus"},
    {"valor": "America/Cuiaba", "nome": "Cuiabá"},
    {"valor": "America/Rio_Branco", "nome": "Rio Branco"},
]
FUSOS_HORARIOS_VALIDOS = {item["valor"] for item in FUSOS_HORARIOS_GESTFLOW}



def _twiml_message(text: str) -> str:
    safe = html.escape(text or "")
    return f'<?xml version="1.0" encoding="UTF-8"?><Response><Message>{safe}</Message></Response>'


def conectar_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def buscar_usuario_por_email(email: str) -> dict[str, Any] | None:
    email_normalizado = str(email or "").strip().lower()

    if not email_normalizado:
        return None

    with conectar_db() as conn:
        row = conn.execute(
            """
            SELECT
                usuarios.id,
                usuarios.empresa_id,
                usuarios.nome,
                usuarios.email,
                usuarios.senha_hash,
                usuarios.perfil,
                usuarios.status,
                usuarios.ultimo_login,
                usuarios.criado_em,
                empresas.nome_fantasia AS empresa_nome,
                empresas.plano AS empresa_plano,
                empresas.status AS empresa_status
            FROM usuarios
            JOIN empresas ON empresas.id = usuarios.empresa_id
            WHERE LOWER(usuarios.email) = ?
            LIMIT 1
            """,
            (email_normalizado,),
        ).fetchone()

    if row is None:
        return None

    return dict(row)


def autenticar_usuario(email: str, senha: str) -> dict[str, Any] | None:
    email_normalizado = str(email or "").strip().lower()
    senha_normalizada = str(senha or "").strip()

    usuario = buscar_usuario_por_email(email_normalizado)

    if usuario is None:
        return None

    if str(usuario.get("status") or "").strip().lower() != "ativo":
        return None

    if str(usuario.get("empresa_status") or "").strip().lower() not in {"ativo", "trial"}:
        return None

    senha_hash = str(usuario.get("senha_hash") or "")

    if not senha_hash or not check_password_hash(senha_hash, senha_normalizada):
        return None

    return usuario


def registrar_ultimo_login_usuario(usuario_id: int) -> None:
    with conectar_db() as conn:
        conn.execute(
            """
            UPDATE usuarios
            SET ultimo_login = ?
            WHERE id = ?
            """,
            (agora_empresa().isoformat(timespec="seconds"), usuario_id),
        )
        conn.commit()


def usuario_logado() -> dict[str, Any] | None:
    usuario_id = session.get("usuario_id")

    if not usuario_id:
        return None

    return {
        "id": session.get("usuario_id"),
        "empresa_id": session.get("empresa_id"),
        "nome": session.get("usuario_nome"),
        "email": session.get("usuario_email"),
        "perfil": session.get("usuario_perfil"),
        "empresa_nome": session.get("empresa_nome"),
        "empresa_plano": session.get("empresa_plano"),
    }


def empresa_padrao_id() -> int:
    with conectar_db() as conn:
        row = conn.execute(
            """
            SELECT id
            FROM empresas
            ORDER BY id ASC
            LIMIT 1
            """
        ).fetchone()

    if row is None:
        return 1

    return int(row["id"])


def empresa_logada_id() -> int:
    try:
        return int(session.get("empresa_id") or empresa_padrao_id())
    except (TypeError, ValueError):
        return empresa_padrao_id()


def usuario_logado_id() -> int | None:
    try:
        usuario_id = session.get("usuario_id")
        return int(usuario_id) if usuario_id else None
    except (TypeError, ValueError):
        return None


def normalizar_timezone_empresa(valor: Any) -> str:
    timezone = str(valor or "").strip()

    if timezone in FUSOS_HORARIOS_VALIDOS:
        return timezone

    return TIMEZONE_PADRAO_GESTFLOW


def timezone_empresa() -> str:
    empresa_id = empresa_logada_id()

    try:
        with conectar_db() as conn:
            row = conn.execute(
                """
                SELECT timezone
                FROM empresas
                WHERE id = ?
                LIMIT 1
                """,
                (empresa_id,),
            ).fetchone()
    except sqlite3.Error:
        return TIMEZONE_PADRAO_GESTFLOW

    if row is None:
        return TIMEZONE_PADRAO_GESTFLOW

    return normalizar_timezone_empresa(row["timezone"])


def agora_empresa() -> datetime:
    try:
        return datetime.now(ZoneInfo(timezone_empresa())).replace(tzinfo=None)
    except Exception:
        return datetime.now(ZoneInfo(TIMEZONE_PADRAO_GESTFLOW)).replace(tzinfo=None)


def hoje_empresa() -> date:
    return agora_empresa().date()


def formatar_data_br(valor: Any) -> str:
    texto = str(valor or "").strip()

    if not texto:
        return ""

    try:
        if isinstance(valor, datetime):
            return valor.strftime("%d/%m/%Y")
        if isinstance(valor, date):
            return valor.strftime("%d/%m/%Y")
        return datetime.strptime(texto[:10], "%Y-%m-%d").strftime("%d/%m/%Y")
    except (TypeError, ValueError):
        return texto


def formatar_data_hora_br(valor: Any) -> str:
    texto = str(valor or "").strip()

    if not texto:
        return ""

    try:
        return datetime.fromisoformat(texto).strftime("%d/%m/%Y %H:%M")
    except (TypeError, ValueError):
        return texto


def _converter_data_simples(valor: Any) -> date | None:
    texto = str(valor or "").strip()

    if not texto:
        return None

    try:
        return datetime.strptime(texto[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def calcular_dias_trial_restantes(trial_fim: Any) -> int | None:
    data_fim = _converter_data_simples(trial_fim)

    if data_fim is None:
        return None

    return (data_fim - hoje_empresa()).days


def montar_aviso_trial_empresa() -> dict[str, Any]:
    if not session.get("usuario_id"):
        return {}

    with conectar_db() as conn:
        row = conn.execute(
            """
            SELECT
                id,
                plano,
                status,
                trial_inicio,
                trial_fim,
                codigo_indicacao,
                indicado_por_empresa_id,
                indicador_codigo,
                pix_indicador
            FROM empresas
            WHERE id = ?
            LIMIT 1
            """,
            (empresa_logada_id(),),
        ).fetchone()

    if row is None:
        return {}

    empresa = dict(row)
    status = str(empresa.get("status") or "").strip().lower()
    dias_restantes = calcular_dias_trial_restantes(empresa.get("trial_fim"))

    if status != "trial":
        return {
            "status": status,
            "plano": empresa.get("plano") or "Start",
            "trial_inicio": empresa.get("trial_inicio") or "",
            "trial_fim": empresa.get("trial_fim") or "",
            "dias_restantes": dias_restantes,
            "exibir_aviso": False,
        }

    if dias_restantes is None:
        texto = "Teste grátis ativo."
    elif dias_restantes < 0:
        texto = "Seu teste grátis terminou. Escolha um plano para continuar usando o GestFlow."
    elif dias_restantes == 0:
        texto = "Seu teste grátis termina hoje."
    elif dias_restantes == 1:
        texto = "Seu teste grátis termina em 1 dia."
    else:
        texto = f"Seu teste grátis termina em {dias_restantes} dias."

    return {
        "status": status,
        "plano": empresa.get("plano") or "Start",
        "trial_inicio": empresa.get("trial_inicio") or "",
        "trial_fim": empresa.get("trial_fim") or "",
        "dias_restantes": dias_restantes,
        "exibir_aviso": True,
        "texto": texto,
    }


@app.context_processor
def injetar_usuario_logado() -> dict[str, Any]:
    return {
        "usuario_logado": usuario_logado(),
        "empresa_trial": montar_aviso_trial_empresa(),
        "data_hoje": formatar_data_br(hoje_empresa()),
        "data_hora_atual": formatar_data_hora_br(agora_empresa().isoformat(timespec="seconds")),
        "timezone_empresa": timezone_empresa(),
    }


@app.before_request
def exigir_login_rotas_internas() -> Response | None:
    rotas_publicas = {
        "portal",
        "planos",
        "novo_cadastro",
        "login",
        "esqueci_senha",
        "health",
        "twilio_webhook",
        "acompanhamento_os_publico",
        "servir_foto_os",
        "static",
    }

    if request.endpoint in rotas_publicas:
        return None

    if request.path.startswith("/static/"):
        return None

    if session.get("usuario_id"):
        return None

    return redirect(url_for("login"))



def normalizar_codigo_indicacao(codigo: Any) -> str:
    texto = str(codigo or "").strip().upper()
    return "".join(caractere for caractere in texto if caractere.isalnum())[:32]


def gerar_codigo_indicacao_base(empresa_id: int) -> str:
    return f"GF{int(empresa_id):04d}"


def garantir_codigo_indicacao_empresa(empresa_id: int, conn: sqlite3.Connection | None = None) -> str:
    codigo_base = gerar_codigo_indicacao_base(empresa_id)

    def _executar(conexao: sqlite3.Connection) -> str:
        row = conexao.execute(
            """
            SELECT codigo_indicacao
            FROM empresas
            WHERE id = ?
            LIMIT 1
            """,
            (empresa_id,),
        ).fetchone()

        if row is not None:
            codigo_atual = normalizar_codigo_indicacao(row["codigo_indicacao"])
            if codigo_atual:
                return codigo_atual

        codigo_final = codigo_base
        tentativa = 1

        while True:
            conflito = conexao.execute(
                """
                SELECT id
                FROM empresas
                WHERE codigo_indicacao = ?
                  AND id <> ?
                LIMIT 1
                """,
                (codigo_final, empresa_id),
            ).fetchone()

            if conflito is None:
                break

            tentativa += 1
            codigo_final = f"{codigo_base}{tentativa}"

        conexao.execute(
            """
            UPDATE empresas
            SET codigo_indicacao = ?
            WHERE id = ?
            """,
            (codigo_final, empresa_id),
        )
        return codigo_final

    if conn is not None:
        return _executar(conn)

    with conectar_db() as conexao:
        codigo = _executar(conexao)
        conexao.commit()
        return codigo


def buscar_empresa_por_codigo_indicacao(codigo: Any) -> dict[str, Any] | None:
    codigo_normalizado = normalizar_codigo_indicacao(codigo)

    if not codigo_normalizado:
        return None

    with conectar_db() as conn:
        row = conn.execute(
            """
            SELECT
                id,
                nome_fantasia,
                email,
                plano,
                status,
                codigo_indicacao
            FROM empresas
            WHERE codigo_indicacao = ?
            LIMIT 1
            """,
            (codigo_normalizado,),
        ).fetchone()

    if row is None:
        return None

    return dict(row)


def valor_comissao_por_plano(plano: Any) -> float:
    plano_normalizado = str(plano or "Start").strip()
    valores = {
        "Start": 3.0,
        "Pro": 5.0,
        "Business": 10.0,
    }
    return valores.get(plano_normalizado, 3.0)


def formatar_valor_comissao(valor: Any) -> str:
    return _formatar_moeda_brl(float(valor or 0))


def montar_link_indicacao(codigo: Any) -> str:
    codigo_normalizado = normalizar_codigo_indicacao(codigo)
    base_url = request.url_root.rstrip("/") if request else ""
    return f"{base_url}{url_for('novo_cadastro')}?ref={codigo_normalizado}"


def iniciar_banco() -> None:
    with conectar_db() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS clientes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nome TEXT NOT NULL,
                documento TEXT,
                telefone TEXT,
                cidade TEXT,
                status TEXT NOT NULL DEFAULT 'ativo',
                email TEXT,
                criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS fornecedores (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nome TEXT NOT NULL,
                documento TEXT,
                telefone TEXT,
                cidade TEXT,
                status TEXT NOT NULL DEFAULT 'ativo',
                email TEXT,
                categoria TEXT,
                observacoes TEXT,
                criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS funcionarios (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nome TEXT NOT NULL,
                cpf TEXT,
                telefone TEXT,
                cidade TEXT,
                cargo TEXT,
                status TEXT NOT NULL DEFAULT 'ativo',
                email TEXT,
                observacoes TEXT,
                criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS produtos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nome TEXT NOT NULL,
                codigo TEXT,
                categoria TEXT,
                unidade TEXT,
                estoque_atual TEXT,
                estoque_minimo TEXT,
                preco_custo TEXT,
                preco_venda TEXT,
                status TEXT NOT NULL DEFAULT 'ativo',
                observacoes TEXT,
                criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS servicos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nome TEXT NOT NULL,
                codigo TEXT,
                categoria TEXT,
                unidade TEXT,
                custo TEXT,
                valor_venda TEXT,
                tempo_estimado TEXT,
                status TEXT NOT NULL DEFAULT 'ativo',
                observacoes TEXT,
                criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS orcamentos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                numero TEXT,
                cliente TEXT,
                responsavel TEXT,
                data TEXT,
                prazo_entrega TEXT,
                validade TEXT,
                canal_venda TEXT,
                centro_custo TEXT,
                introducao TEXT,
                tipo TEXT NOT NULL DEFAULT 'misto',
                status TEXT NOT NULL DEFAULT 'aberto',
                total_produtos TEXT,
                total_servicos TEXT,
                desconto_valor TEXT,
                desconto_percentual TEXT,
                valor_total TEXT,
                forma_pagamento TEXT,
                observacoes TEXT,
                observacoes_internas TEXT,
                criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS orcamento_itens (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                orcamento_id INTEGER NOT NULL,
                tipo_item TEXT NOT NULL DEFAULT 'produto',
                descricao TEXT,
                detalhes TEXT,
                quantidade TEXT,
                valor_unitario TEXT,
                desconto TEXT,
                subtotal TEXT,
                criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (orcamento_id) REFERENCES orcamentos (id)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS vendas (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                numero TEXT,
                cliente TEXT,
                responsavel TEXT,
                data TEXT,
                prazo_entrega TEXT,
                canal_venda TEXT,
                centro_custo TEXT,
                tipo TEXT NOT NULL DEFAULT 'misto',
                status TEXT NOT NULL DEFAULT 'aberta',
                total_produtos TEXT,
                total_servicos TEXT,
                desconto_valor TEXT,
                desconto_percentual TEXT,
                valor_total TEXT,
                forma_pagamento TEXT,
                observacoes TEXT,
                observacoes_internas TEXT,
                criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS venda_itens (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                venda_id INTEGER NOT NULL,
                tipo_item TEXT NOT NULL DEFAULT 'produto',
                descricao TEXT,
                detalhes TEXT,
                quantidade TEXT,
                valor_unitario TEXT,
                desconto TEXT,
                subtotal TEXT,
                criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (venda_id) REFERENCES vendas (id)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS ordens_servico (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                numero TEXT,
                cliente TEXT,
                responsavel TEXT,
                tecnico TEXT,
                data_abertura TEXT,
                data_previsao TEXT,
                data_saida TEXT,
                hora_entrada TEXT,
                hora_saida TEXT,
                canal_venda TEXT,
                centro_custo TEXT,
                equipamento TEXT,
                marca TEXT,
                modelo TEXT,
                serie TEXT,
                local_servico TEXT,
                condicoes TEXT,
                acessorios TEXT,
                laudo TEXT,
                termos TEXT,
                informar_endereco_entrega TEXT,
                endereco_entrega TEXT,
                bairro_entrega TEXT,
                cidade_entrega TEXT,
                origem_venda_id INTEGER,
                tipo TEXT NOT NULL DEFAULT 'misto',
                status TEXT NOT NULL DEFAULT 'aberta',
                prioridade TEXT NOT NULL DEFAULT 'normal',
                total_produtos TEXT,
                total_servicos TEXT,
                frete TEXT,
                outros TEXT,
                desconto_valor TEXT,
                valor_total TEXT,
                forma_pagamento TEXT,
                exibir_valor_impressao TEXT,
                relato_cliente TEXT,
                diagnostico TEXT,
                servico_executado TEXT,
                observacoes TEXT,
                observacoes_internas TEXT,
                criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS ordem_servico_itens (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ordem_servico_id INTEGER NOT NULL,
                tipo_item TEXT NOT NULL DEFAULT 'produto',
                descricao TEXT,
                detalhes TEXT,
                quantidade TEXT,
                valor_unitario TEXT,
                desconto TEXT,
                subtotal TEXT,
                criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (ordem_servico_id) REFERENCES ordens_servico (id)
            )
            """
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS os_fotos_equipamento (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                empresa_id INTEGER,
                ordem_servico_id INTEGER NOT NULL,
                titulo TEXT,
                equipamento_indice TEXT DEFAULT '0',
                foto_antes_path TEXT,
                foto_depois_path TEXT,
                observacoes TEXT,
                criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                atualizado_em TEXT,
                FOREIGN KEY (ordem_servico_id) REFERENCES ordens_servico (id)
            )
            """
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS os_acompanhamentos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                empresa_id INTEGER,
                ordem_servico_id INTEGER NOT NULL,
                token TEXT NOT NULL UNIQUE,
                data_acompanhamento TEXT,
                responsavel TEXT,
                status_link TEXT NOT NULL DEFAULT 'ativo',
                status_dia TEXT NOT NULL DEFAULT 'aberto',
                atividades_previstas TEXT,
                equipe_prevista TEXT,
                materiais_previstos TEXT,
                atividades_executadas TEXT,
                equipe_real TEXT,
                materiais_utilizados TEXT,
                observacoes TEXT,
                aberto_em TEXT,
                finalizado_em TEXT,
                expira_em TEXT,
                criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                atualizado_em TEXT,
                FOREIGN KEY (ordem_servico_id) REFERENCES ordens_servico (id)
            )
            """
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS os_acompanhamento_equipe (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                empresa_id INTEGER,
                acompanhamento_id INTEGER NOT NULL,
                funcionario_id INTEGER,
                nome TEXT,
                cargo TEXT,
                horas TEXT,
                observacoes TEXT,
                criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (acompanhamento_id) REFERENCES os_acompanhamentos (id),
                FOREIGN KEY (funcionario_id) REFERENCES funcionarios (id)
            )
            """
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS os_acompanhamento_materiais (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                empresa_id INTEGER,
                acompanhamento_id INTEGER NOT NULL,
                produto_id INTEGER,
                nome TEXT,
                unidade TEXT,
                quantidade TEXT,
                observacoes TEXT,
                criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (acompanhamento_id) REFERENCES os_acompanhamentos (id),
                FOREIGN KEY (produto_id) REFERENCES produtos (id)
            )
            """
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS os_acompanhamento_servicos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                empresa_id INTEGER,
                acompanhamento_id INTEGER NOT NULL,
                servico_id INTEGER,
                nome TEXT,
                quantidade TEXT,
                observacoes TEXT,
                criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (acompanhamento_id) REFERENCES os_acompanhamentos (id),
                FOREIGN KEY (servico_id) REFERENCES servicos (id)
            )
            """
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS estoque_movimentacoes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                produto_id INTEGER,
                produto_nome TEXT,
                tipo TEXT NOT NULL DEFAULT 'entrada',
                quantidade TEXT,
                saldo_anterior TEXT,
                saldo_atual TEXT,
                motivo TEXT,
                documento TEXT,
                responsavel TEXT,
                observacoes TEXT,
                criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (produto_id) REFERENCES produtos (id)
            )
            """
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS financeiro_titulos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tipo TEXT NOT NULL DEFAULT 'receber',
                descricao TEXT,
                pessoa TEXT,
                categoria TEXT,
                origem TEXT NOT NULL DEFAULT 'manual',
                origem_id INTEGER,
                documento TEXT,
                data_emissao TEXT,
                data_vencimento TEXT,
                data_pagamento TEXT,
                valor TEXT,
                forma_pagamento TEXT,
                status TEXT NOT NULL DEFAULT 'aberto',
                observacoes TEXT,
                criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS caixa_aberturas (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                empresa_id INTEGER,
                usuario_id INTEGER,
                responsavel TEXT,
                valor_abertura TEXT,
                valor_fechamento TEXT,
                status TEXT NOT NULL DEFAULT 'aberto',
                aberto_em TEXT,
                fechado_em TEXT,
                observacoes TEXT,
                criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS caixa_movimentacoes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                empresa_id INTEGER,
                caixa_id INTEGER,
                venda_id INTEGER,
                tipo TEXT NOT NULL DEFAULT 'entrada',
                descricao TEXT,
                forma_pagamento TEXT,
                valor TEXT,
                criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (caixa_id) REFERENCES caixa_aberturas (id),
                FOREIGN KEY (venda_id) REFERENCES vendas (id)
            )
            """
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS indicacao_comissoes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                indicador_empresa_id INTEGER NOT NULL,
                indicado_empresa_id INTEGER NOT NULL,
                plano TEXT,
                competencia TEXT,
                valor TEXT,
                status TEXT NOT NULL DEFAULT 'liberada',
                data_pagamento_cliente TEXT,
                data_liberacao TEXT,
                data_repasse TEXT,
                observacoes TEXT,
                criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (indicador_empresa_id) REFERENCES empresas (id),
                FOREIGN KEY (indicado_empresa_id) REFERENCES empresas (id)
            )
            """
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS empresas (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nome_fantasia TEXT NOT NULL,
                razao_social TEXT,
                documento TEXT,
                email TEXT,
                telefone TEXT,
                plano TEXT NOT NULL DEFAULT 'Start',
                status TEXT NOT NULL DEFAULT 'ativo',
                criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS usuarios (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                empresa_id INTEGER NOT NULL,
                nome TEXT NOT NULL,
                email TEXT NOT NULL UNIQUE,
                senha_hash TEXT NOT NULL,
                perfil TEXT NOT NULL DEFAULT 'administrador',
                status TEXT NOT NULL DEFAULT 'ativo',
                ultimo_login TEXT,
                criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (empresa_id) REFERENCES empresas (id)
            )
            """
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS usuario_atividades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                empresa_id INTEGER,
                usuario_id INTEGER,
                usuario_nome TEXT,
                tipo TEXT NOT NULL DEFAULT 'acesso',
                modulo TEXT,
                descricao TEXT,
                rota TEXT,
                criado_em TEXT DEFAULT CURRENT_TIMESTAMP
            )
            """
        )


        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS assistente_conversas (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                empresa_id INTEGER,
                usuario_id INTEGER,
                usuario_nome TEXT,
                pergunta TEXT,
                resposta TEXT,
                origem TEXT NOT NULL DEFAULT 'local',
                criado_em TEXT DEFAULT CURRENT_TIMESTAMP
            )
            """
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS lojas (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                empresa_id INTEGER NOT NULL,
                nome TEXT NOT NULL,
                tipo TEXT NOT NULL DEFAULT 'Principal',
                cidade TEXT,
                status TEXT NOT NULL DEFAULT 'ativo',
                criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (empresa_id) REFERENCES empresas (id)
            )
            """
        )

        empresa_row = conn.execute(
            """
            SELECT id
            FROM empresas
            ORDER BY id ASC
            LIMIT 1
            """
        ).fetchone()

        if empresa_row is None:
            cursor_empresa = conn.execute(
                """
                INSERT INTO empresas (
                    nome_fantasia,
                    razao_social,
                    documento,
                    email,
                    telefone,
                    plano,
                    status
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "GestFlow Demo",
                    "GestFlow Demo",
                    "",
                    "",
                    "",
                    "Start",
                    "ativo",
                ),
            )
            empresa_id_inicial = int(cursor_empresa.lastrowid)
        else:
            empresa_id_inicial = int(empresa_row["id"])

        usuario_row = conn.execute(
            """
            SELECT id
            FROM usuarios
            WHERE email = ?
            LIMIT 1
            """,
            ("admin@gestflow.local",),
        ).fetchone()

        if usuario_row is None:
            conn.execute(
                """
                INSERT INTO usuarios (
                    empresa_id,
                    nome,
                    email,
                    senha_hash,
                    perfil,
                    status,
                    ultimo_login
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    empresa_id_inicial,
                    "Netto Santana",
                    "admin@gestflow.local",
                    generate_password_hash("admin123"),
                    "administrador",
                    "ativo",
                    "",
                ),
            )

        loja_row = conn.execute(
            """
            SELECT id
            FROM lojas
            WHERE empresa_id = ?
            LIMIT 1
            """,
            (empresa_id_inicial,),
        ).fetchone()

        if loja_row is None:
            conn.execute(
                """
                INSERT INTO lojas (
                    empresa_id,
                    nome,
                    tipo,
                    cidade,
                    status
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    empresa_id_inicial,
                    "Matriz",
                    "Principal",
                    "",
                    "ativo",
                ),
            )

        colunas_empresas = {
            str(row["name"])
            for row in conn.execute("PRAGMA table_info(empresas)").fetchall()
        }

        if "logo_path" not in colunas_empresas:
            conn.execute("ALTER TABLE empresas ADD COLUMN logo_path TEXT")

        if "trial_inicio" not in colunas_empresas:
            conn.execute("ALTER TABLE empresas ADD COLUMN trial_inicio TEXT")

        if "trial_fim" not in colunas_empresas:
            conn.execute("ALTER TABLE empresas ADD COLUMN trial_fim TEXT")

        if "codigo_indicacao" not in colunas_empresas:
            conn.execute("ALTER TABLE empresas ADD COLUMN codigo_indicacao TEXT")

        if "indicado_por_empresa_id" not in colunas_empresas:
            conn.execute("ALTER TABLE empresas ADD COLUMN indicado_por_empresa_id INTEGER")

        if "indicador_codigo" not in colunas_empresas:
            conn.execute("ALTER TABLE empresas ADD COLUMN indicador_codigo TEXT")

        if "pix_indicador" not in colunas_empresas:
            conn.execute("ALTER TABLE empresas ADD COLUMN pix_indicador TEXT")

        if "timezone" not in colunas_empresas:
            conn.execute("ALTER TABLE empresas ADD COLUMN timezone TEXT DEFAULT 'America/Bahia'")

        if "onboarding_concluido" not in colunas_empresas:
            conn.execute("ALTER TABLE empresas ADD COLUMN onboarding_concluido TEXT DEFAULT 'nao'")

        if "onboarding_ramo" not in colunas_empresas:
            conn.execute("ALTER TABLE empresas ADD COLUMN onboarding_ramo TEXT")

        if "onboarding_objetivos" not in colunas_empresas:
            conn.execute("ALTER TABLE empresas ADD COLUMN onboarding_objetivos TEXT")

        if "onboarding_ferramenta_atual" not in colunas_empresas:
            conn.execute("ALTER TABLE empresas ADD COLUMN onboarding_ferramenta_atual TEXT")

        if "onboarding_canal_contato" not in colunas_empresas:
            conn.execute("ALTER TABLE empresas ADD COLUMN onboarding_canal_contato TEXT")

        if "tour_concluido" not in colunas_empresas:
            conn.execute("ALTER TABLE empresas ADD COLUMN tour_concluido TEXT DEFAULT 'nao'")

        colunas_config_gerador = {
            "gerador_margem_material": "TEXT DEFAULT '30'",
            "gerador_margem_mao_obra": "TEXT DEFAULT '40'",
            "gerador_margem_custos": "TEXT DEFAULT '20'",
            "gerador_imposto_percentual": "TEXT DEFAULT '8'",
            "gerador_administrativo_percentual": "TEXT DEFAULT '10'",
            "gerador_reserva_percentual": "TEXT DEFAULT '5'",
            "gerador_config_atualizado_em": "TEXT",
        }

        for coluna, tipo_coluna in colunas_config_gerador.items():
            if coluna not in colunas_empresas:
                conn.execute(f"ALTER TABLE empresas ADD COLUMN {coluna} {tipo_coluna}")

        colunas_funcionarios_existentes = {
            str(row["name"])
            for row in conn.execute("PRAGMA table_info(funcionarios)").fetchall()
        }

        colunas_custos_funcionarios = {
            "salario_base": "TEXT",
            "inss_percentual": "TEXT",
            "fgts_percentual": "TEXT",
            "ferias_percentual": "TEXT",
            "decimo_percentual": "TEXT",
            "beneficios": "TEXT",
            "transporte": "TEXT",
            "alimentacao": "TEXT",
            "outros_custos": "TEXT",
            "custo_mensal": "TEXT",
            "custo_dia": "TEXT",
            "custo_hora": "TEXT",
        }

        for coluna, tipo_coluna in colunas_custos_funcionarios.items():
            if coluna not in colunas_funcionarios_existentes:
                conn.execute(f"ALTER TABLE funcionarios ADD COLUMN {coluna} {tipo_coluna}")

        empresas_sem_codigo = conn.execute(
            """
            SELECT id
            FROM empresas
            WHERE codigo_indicacao IS NULL
               OR TRIM(codigo_indicacao) = ''
            ORDER BY id ASC
            """
        ).fetchall()

        for empresa_sem_codigo in empresas_sem_codigo:
            garantir_codigo_indicacao_empresa(int(empresa_sem_codigo["id"]), conn)


        tabelas_com_empresa_id = [
            "clientes",
            "fornecedores",
            "funcionarios",
            "produtos",
            "servicos",
            "orcamentos",
            "orcamento_itens",
            "vendas",
            "venda_itens",
            "ordens_servico",
            "ordem_servico_itens",
            "os_fotos_equipamento",
            "os_acompanhamentos",
            "os_acompanhamento_equipe",
            "os_acompanhamento_materiais",
            "os_acompanhamento_servicos",
            "estoque_movimentacoes",
            "financeiro_titulos",
            "caixa_aberturas",
            "caixa_movimentacoes",
            "usuario_atividades",
            "assistente_conversas",
        ]

        for tabela in tabelas_com_empresa_id:
            colunas_tabela = {
                str(row["name"])
                for row in conn.execute(f"PRAGMA table_info({tabela})").fetchall()
            }

            if "empresa_id" not in colunas_tabela:
                conn.execute(f"ALTER TABLE {tabela} ADD COLUMN empresa_id INTEGER")

            conn.execute(
                f"UPDATE {tabela} SET empresa_id = ? WHERE empresa_id IS NULL",
                (empresa_id_inicial,),
            )

        colunas_ordens_servico = {
            "tecnico": "TEXT",
            "data_saida": "TEXT",
            "hora_entrada": "TEXT",
            "hora_saida": "TEXT",
            "canal_venda": "TEXT",
            "centro_custo": "TEXT",
            "marca": "TEXT",
            "modelo": "TEXT",
            "serie": "TEXT",
            "condicoes": "TEXT",
            "acessorios": "TEXT",
            "laudo": "TEXT",
            "termos": "TEXT",
            "informar_endereco_entrega": "TEXT",
            "endereco_entrega": "TEXT",
            "bairro_entrega": "TEXT",
            "cidade_entrega": "TEXT",
            "frete": "TEXT",
            "outros": "TEXT",
            "desconto_valor": "TEXT",
            "exibir_valor_impressao": "TEXT",
        }
        colunas_existentes = {
            str(row["name"])
            for row in conn.execute("PRAGMA table_info(ordens_servico)").fetchall()
        }

        for coluna, tipo_coluna in colunas_ordens_servico.items():
            if coluna not in colunas_existentes:
                conn.execute(f"ALTER TABLE ordens_servico ADD COLUMN {coluna} {tipo_coluna}")

        colunas_fotos_equipamento = {
            str(row["name"])
            for row in conn.execute("PRAGMA table_info(os_fotos_equipamento)").fetchall()
        }

        if "equipamento_indice" not in colunas_fotos_equipamento:
            conn.execute("ALTER TABLE os_fotos_equipamento ADD COLUMN equipamento_indice TEXT DEFAULT '0'")

        conn.commit()


def salvar_cliente_db(cliente: dict[str, str]) -> None:
    empresa_id = empresa_logada_id()

    with conectar_db() as conn:
        conn.execute(
            """
            INSERT INTO clientes (
                empresa_id,
                nome,
                documento,
                telefone,
                cidade,
                status,
                email
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                empresa_id,
                cliente["nome"],
                cliente["documento"],
                cliente["telefone"],
                cliente["cidade"],
                cliente["status"],
                cliente["email"],
            ),
        )
        conn.commit()


def listar_clientes() -> list[dict[str, Any]]:
    empresa_id = empresa_logada_id()

    with conectar_db() as conn:
        rows = conn.execute(
            """
            SELECT
                id,
                empresa_id,
                nome,
                documento,
                telefone,
                cidade,
                status,
                email,
                criado_em
            FROM clientes
            WHERE empresa_id = ?
            ORDER BY id DESC
            """,
            (empresa_id,),
        ).fetchall()

    return [dict(row) for row in rows]


def buscar_cliente_por_id(cliente_id: int) -> dict[str, Any] | None:
    empresa_id = empresa_logada_id()

    with conectar_db() as conn:
        row = conn.execute(
            """
            SELECT
                id,
                empresa_id,
                nome,
                documento,
                telefone,
                cidade,
                status,
                email,
                criado_em
            FROM clientes
            WHERE id = ?
              AND empresa_id = ?
            """,
            (cliente_id, empresa_id),
        ).fetchone()

    if row is None:
        return None

    return dict(row)



def buscar_cliente_por_nome(nome_cliente: str) -> dict[str, Any] | None:
    empresa_id = empresa_logada_id()
    nome_normalizado = str(nome_cliente or "").strip()

    if not nome_normalizado:
        return None

    with conectar_db() as conn:
        row = conn.execute(
            """
            SELECT
                id,
                empresa_id,
                nome,
                documento,
                telefone,
                cidade,
                status,
                email,
                criado_em
            FROM clientes
            WHERE empresa_id = ?
              AND LOWER(nome) = LOWER(?)
            ORDER BY id DESC
            LIMIT 1
            """,
            (empresa_id, nome_normalizado),
        ).fetchone()

        if row is None:
            row = conn.execute(
                """
                SELECT
                    id,
                    empresa_id,
                    nome,
                    documento,
                    telefone,
                    cidade,
                    status,
                    email,
                    criado_em
                FROM clientes
                WHERE empresa_id = ?
                  AND LOWER(nome) LIKE LOWER(?)
                ORDER BY id DESC
                LIMIT 1
                """,
                (empresa_id, f"%{nome_normalizado}%"),
            ).fetchone()

    if row is None:
        return None

    return dict(row)


def buscar_loja_principal_configuracoes() -> dict[str, Any]:
    with conectar_db() as conn:
        row = conn.execute(
            """
            SELECT
                id,
                empresa_id,
                nome,
                tipo,
                cidade,
                status,
                criado_em
            FROM lojas
            WHERE empresa_id = ?
            ORDER BY
                CASE WHEN LOWER(tipo) = 'principal' THEN 0 ELSE 1 END,
                id ASC
            LIMIT 1
            """,
            (empresa_logada_id(),),
        ).fetchone()

    if row is None:
        return {
            "id": "",
            "empresa_id": empresa_logada_id(),
            "nome": "Matriz",
            "tipo": "Principal",
            "cidade": "",
            "status": "ativo",
            "criado_em": "",
        }

    return dict(row)


def montar_contexto_impressao(nome_cliente: Any) -> dict[str, Any]:
    return {
        "empresa": buscar_empresa_configuracoes(),
        "loja": buscar_loja_principal_configuracoes(),
        "cliente": buscar_cliente_por_nome(str(nome_cliente or "")),
    }

def atualizar_cliente_db(cliente_id: int, cliente: dict[str, str]) -> None:
    empresa_id = empresa_logada_id()

    with conectar_db() as conn:
        conn.execute(
            """
            UPDATE clientes
            SET
                nome = ?,
                documento = ?,
                telefone = ?,
                cidade = ?,
                status = ?,
                email = ?
            WHERE id = ?
              AND empresa_id = ?
            """,
            (
                cliente["nome"],
                cliente["documento"],
                cliente["telefone"],
                cliente["cidade"],
                cliente["status"],
                cliente["email"],
                cliente_id,
                empresa_id,
            ),
        )
        conn.commit()


def excluir_cliente_db(cliente_id: int) -> None:
    empresa_id = empresa_logada_id()

    with conectar_db() as conn:
        conn.execute(
            """
            DELETE FROM clientes
            WHERE id = ?
              AND empresa_id = ?
            """,
            (cliente_id, empresa_id),
        )
        conn.commit()


def salvar_fornecedor_db(fornecedor: dict[str, str]) -> None:
    empresa_id = empresa_logada_id()

    with conectar_db() as conn:
        conn.execute(
            """
            INSERT INTO fornecedores (
                empresa_id,
                nome,
                documento,
                telefone,
                cidade,
                status,
                email,
                categoria,
                observacoes
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                empresa_id,
                fornecedor["nome"],
                fornecedor["documento"],
                fornecedor["telefone"],
                fornecedor["cidade"],
                fornecedor["status"],
                fornecedor["email"],
                fornecedor["categoria"],
                fornecedor["observacoes"],
            ),
        )
        conn.commit()

def listar_fornecedores() -> list[dict[str, Any]]:
    empresa_id = empresa_logada_id()

    with conectar_db() as conn:
        rows = conn.execute(
            """
            SELECT
                id,
                empresa_id,
                nome,
                documento,
                telefone,
                cidade,
                status,
                email,
                categoria,
                observacoes,
                criado_em
            FROM fornecedores
            WHERE empresa_id = ?
            ORDER BY id DESC
            """,
            (empresa_id,),
        ).fetchall()

    return [dict(row) for row in rows]

def buscar_fornecedor_por_id(fornecedor_id: int) -> dict[str, Any] | None:
    empresa_id = empresa_logada_id()

    with conectar_db() as conn:
        row = conn.execute(
            """
            SELECT
                id,
                empresa_id,
                nome,
                documento,
                telefone,
                cidade,
                status,
                email,
                categoria,
                observacoes,
                criado_em
            FROM fornecedores
            WHERE id = ?
              AND empresa_id = ?
            """,
            (fornecedor_id, empresa_id),
        ).fetchone()

    if row is None:
        return None

    return dict(row)

def atualizar_fornecedor_db(fornecedor_id: int, fornecedor: dict[str, str]) -> None:
    empresa_id = empresa_logada_id()

    with conectar_db() as conn:
        conn.execute(
            """
            UPDATE fornecedores
            SET
                nome = ?,
                documento = ?,
                telefone = ?,
                cidade = ?,
                status = ?,
                email = ?,
                categoria = ?,
                observacoes = ?
            WHERE id = ?
              AND empresa_id = ?
            """,
            (
                fornecedor["nome"],
                fornecedor["documento"],
                fornecedor["telefone"],
                fornecedor["cidade"],
                fornecedor["status"],
                fornecedor["email"],
                fornecedor["categoria"],
                fornecedor["observacoes"],
                fornecedor_id,
                empresa_id,
            ),
        )
        conn.commit()

def excluir_fornecedor_db(fornecedor_id: int) -> None:
    empresa_id = empresa_logada_id()

    with conectar_db() as conn:
        conn.execute(
            """
            DELETE FROM fornecedores
            WHERE id = ?
              AND empresa_id = ?
            """,
            (fornecedor_id, empresa_id),
        )
        conn.commit()

def _normalizar_custos_funcionario(funcionario: dict[str, str]) -> dict[str, str]:
    funcionario_normalizado = dict(funcionario)

    salario = _converter_valor_brl(funcionario_normalizado.get("salario_base"))
    inss = _converter_valor_brl(funcionario_normalizado.get("inss_percentual"))
    fgts = _converter_valor_brl(funcionario_normalizado.get("fgts_percentual"))
    ferias = _converter_valor_brl(funcionario_normalizado.get("ferias_percentual"))
    decimo = _converter_valor_brl(funcionario_normalizado.get("decimo_percentual"))
    beneficios = _converter_valor_brl(funcionario_normalizado.get("beneficios"))
    transporte = _converter_valor_brl(funcionario_normalizado.get("transporte"))
    alimentacao = _converter_valor_brl(funcionario_normalizado.get("alimentacao"))
    outros_custos = _converter_valor_brl(funcionario_normalizado.get("outros_custos"))

    encargos_percentual = inss + fgts + ferias + decimo
    custo_mensal_calculado = salario + (salario * encargos_percentual / 100) + beneficios + transporte + alimentacao + outros_custos

    custo_mensal = _converter_valor_brl(funcionario_normalizado.get("custo_mensal")) or custo_mensal_calculado
    custo_dia = _converter_valor_brl(funcionario_normalizado.get("custo_dia")) or (custo_mensal / 22 if custo_mensal else 0)
    custo_hora = _converter_valor_brl(funcionario_normalizado.get("custo_hora")) or (custo_mensal / 220 if custo_mensal else 0)

    funcionario_normalizado["salario_base"] = funcionario_normalizado.get("salario_base", "")
    funcionario_normalizado["inss_percentual"] = funcionario_normalizado.get("inss_percentual", "")
    funcionario_normalizado["fgts_percentual"] = funcionario_normalizado.get("fgts_percentual", "")
    funcionario_normalizado["ferias_percentual"] = funcionario_normalizado.get("ferias_percentual", "")
    funcionario_normalizado["decimo_percentual"] = funcionario_normalizado.get("decimo_percentual", "")
    funcionario_normalizado["beneficios"] = funcionario_normalizado.get("beneficios", "")
    funcionario_normalizado["transporte"] = funcionario_normalizado.get("transporte", "")
    funcionario_normalizado["alimentacao"] = funcionario_normalizado.get("alimentacao", "")
    funcionario_normalizado["outros_custos"] = funcionario_normalizado.get("outros_custos", "")
    funcionario_normalizado["custo_mensal"] = _formatar_moeda_brl(custo_mensal) if custo_mensal else ""
    funcionario_normalizado["custo_dia"] = _formatar_moeda_brl(custo_dia) if custo_dia else ""
    funcionario_normalizado["custo_hora"] = _formatar_moeda_brl(custo_hora) if custo_hora else ""

    return funcionario_normalizado


def salvar_funcionario_db(funcionario: dict[str, str]) -> None:
    empresa_id = empresa_logada_id()
    funcionario = _normalizar_custos_funcionario(funcionario)

    with conectar_db() as conn:
        conn.execute(
            """
            INSERT INTO funcionarios (
                empresa_id,
                nome,
                cpf,
                telefone,
                cidade,
                cargo,
                status,
                email,
                observacoes,
                salario_base,
                inss_percentual,
                fgts_percentual,
                ferias_percentual,
                decimo_percentual,
                beneficios,
                transporte,
                alimentacao,
                outros_custos,
                custo_mensal,
                custo_dia,
                custo_hora
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                empresa_id,
                funcionario["nome"],
                funcionario["cpf"],
                funcionario["telefone"],
                funcionario["cidade"],
                funcionario["cargo"],
                funcionario["status"],
                funcionario["email"],
                funcionario["observacoes"],
                funcionario["salario_base"],
                funcionario["inss_percentual"],
                funcionario["fgts_percentual"],
                funcionario["ferias_percentual"],
                funcionario["decimo_percentual"],
                funcionario["beneficios"],
                funcionario["transporte"],
                funcionario["alimentacao"],
                funcionario["outros_custos"],
                funcionario["custo_mensal"],
                funcionario["custo_dia"],
                funcionario["custo_hora"],
            ),
        )
        conn.commit()

def listar_funcionarios() -> list[dict[str, Any]]:
    empresa_id = empresa_logada_id()

    with conectar_db() as conn:
        rows = conn.execute(
            """
            SELECT
                id,
                empresa_id,
                nome,
                cpf,
                telefone,
                cidade,
                cargo,
                status,
                email,
                observacoes,
                salario_base,
                inss_percentual,
                fgts_percentual,
                ferias_percentual,
                decimo_percentual,
                beneficios,
                transporte,
                alimentacao,
                outros_custos,
                custo_mensal,
                custo_dia,
                custo_hora,
                criado_em
            FROM funcionarios
            WHERE empresa_id = ?
            ORDER BY id DESC
            """,
            (empresa_id,),
        ).fetchall()

    return [dict(row) for row in rows]

def buscar_funcionario_por_id(funcionario_id: int) -> dict[str, Any] | None:
    empresa_id = empresa_logada_id()

    with conectar_db() as conn:
        row = conn.execute(
            """
            SELECT
                id,
                empresa_id,
                nome,
                cpf,
                telefone,
                cidade,
                cargo,
                status,
                email,
                observacoes,
                salario_base,
                inss_percentual,
                fgts_percentual,
                ferias_percentual,
                decimo_percentual,
                beneficios,
                transporte,
                alimentacao,
                outros_custos,
                custo_mensal,
                custo_dia,
                custo_hora,
                criado_em
            FROM funcionarios
            WHERE id = ?
              AND empresa_id = ?
            """,
            (funcionario_id, empresa_id),
        ).fetchone()

    if row is None:
        return None

    return dict(row)

def atualizar_funcionario_db(funcionario_id: int, funcionario: dict[str, str]) -> None:
    empresa_id = empresa_logada_id()
    funcionario = _normalizar_custos_funcionario(funcionario)

    with conectar_db() as conn:
        conn.execute(
            """
            UPDATE funcionarios
            SET
                nome = ?,
                cpf = ?,
                telefone = ?,
                cidade = ?,
                cargo = ?,
                status = ?,
                email = ?,
                observacoes = ?,
                salario_base = ?,
                inss_percentual = ?,
                fgts_percentual = ?,
                ferias_percentual = ?,
                decimo_percentual = ?,
                beneficios = ?,
                transporte = ?,
                alimentacao = ?,
                outros_custos = ?,
                custo_mensal = ?,
                custo_dia = ?,
                custo_hora = ?
            WHERE id = ?
              AND empresa_id = ?
            """,
            (
                funcionario["nome"],
                funcionario["cpf"],
                funcionario["telefone"],
                funcionario["cidade"],
                funcionario["cargo"],
                funcionario["status"],
                funcionario["email"],
                funcionario["observacoes"],
                funcionario["salario_base"],
                funcionario["inss_percentual"],
                funcionario["fgts_percentual"],
                funcionario["ferias_percentual"],
                funcionario["decimo_percentual"],
                funcionario["beneficios"],
                funcionario["transporte"],
                funcionario["alimentacao"],
                funcionario["outros_custos"],
                funcionario["custo_mensal"],
                funcionario["custo_dia"],
                funcionario["custo_hora"],
                funcionario_id,
                empresa_id,
            ),
        )
        conn.commit()

def excluir_funcionario_db(funcionario_id: int) -> None:
    empresa_id = empresa_logada_id()

    with conectar_db() as conn:
        conn.execute(
            """
            DELETE FROM funcionarios
            WHERE id = ?
              AND empresa_id = ?
            """,
            (funcionario_id, empresa_id),
        )
        conn.commit()

def salvar_produto_db(produto: dict[str, str]) -> None:
    empresa_id = empresa_logada_id()

    with conectar_db() as conn:
        conn.execute(
            """
            INSERT INTO produtos (
                empresa_id,
                nome,
                codigo,
                categoria,
                unidade,
                estoque_atual,
                estoque_minimo,
                preco_custo,
                preco_venda,
                status,
                observacoes
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                empresa_id,
                produto["nome"],
                produto["codigo"],
                produto["categoria"],
                produto["unidade"],
                produto["estoque_atual"],
                produto["estoque_minimo"],
                produto["preco_custo"],
                produto["preco_venda"],
                produto["status"],
                produto["observacoes"],
            ),
        )
        conn.commit()

def listar_produtos() -> list[dict[str, Any]]:
    empresa_id = empresa_logada_id()

    with conectar_db() as conn:
        rows = conn.execute(
            """
            SELECT
                id,
                empresa_id,
                nome,
                codigo,
                categoria,
                unidade,
                estoque_atual,
                estoque_minimo,
                preco_custo,
                preco_venda,
                status,
                observacoes,
                criado_em
            FROM produtos
            WHERE empresa_id = ?
            ORDER BY id DESC
            """,
            (empresa_id,),
        ).fetchall()

    return [dict(row) for row in rows]

def buscar_produto_por_id(produto_id: int) -> dict[str, Any] | None:
    empresa_id = empresa_logada_id()

    with conectar_db() as conn:
        row = conn.execute(
            """
            SELECT
                id,
                empresa_id,
                nome,
                codigo,
                categoria,
                unidade,
                estoque_atual,
                estoque_minimo,
                preco_custo,
                preco_venda,
                status,
                observacoes,
                criado_em
            FROM produtos
            WHERE id = ?
              AND empresa_id = ?
            """,
            (produto_id, empresa_id),
        ).fetchone()

    if row is None:
        return None

    return dict(row)

def atualizar_produto_db(produto_id: int, produto: dict[str, str]) -> None:
    empresa_id = empresa_logada_id()

    with conectar_db() as conn:
        conn.execute(
            """
            UPDATE produtos
            SET
                nome = ?,
                codigo = ?,
                categoria = ?,
                unidade = ?,
                estoque_atual = ?,
                estoque_minimo = ?,
                preco_custo = ?,
                preco_venda = ?,
                status = ?,
                observacoes = ?
            WHERE id = ?
              AND empresa_id = ?
            """,
            (
                produto["nome"],
                produto["codigo"],
                produto["categoria"],
                produto["unidade"],
                produto["estoque_atual"],
                produto["estoque_minimo"],
                produto["preco_custo"],
                produto["preco_venda"],
                produto["status"],
                produto["observacoes"],
                produto_id,
                empresa_id,
            ),
        )
        conn.commit()

def excluir_produto_db(produto_id: int) -> None:
    empresa_id = empresa_logada_id()

    with conectar_db() as conn:
        conn.execute(
            """
            DELETE FROM produtos
            WHERE id = ?
              AND empresa_id = ?
            """,
            (produto_id, empresa_id),
        )
        conn.commit()

def listar_estoque_movimentacoes(limite: int = 100, produto_id: int | None = None) -> list[dict[str, Any]]:
    empresa_id = empresa_logada_id()
    consulta = """
        SELECT
            id,
            empresa_id,
            produto_id,
            produto_nome,
            tipo,
            quantidade,
            saldo_anterior,
            saldo_atual,
            motivo,
            documento,
            responsavel,
            observacoes,
            criado_em
        FROM estoque_movimentacoes
        WHERE empresa_id = ?
    """

    parametros: list[Any] = [empresa_id]

    if produto_id is not None:
        consulta += " AND produto_id = ?"
        parametros.append(produto_id)

    consulta += " ORDER BY id DESC LIMIT ?"
    parametros.append(limite)

    with conectar_db() as conn:
        rows = conn.execute(consulta, parametros).fetchall()

    return [dict(row) for row in rows]

def salvar_estoque_movimentacao_db(movimentacao: dict[str, str]) -> None:
    empresa_id = empresa_logada_id()

    with conectar_db() as conn:
        conn.execute(
            """
            INSERT INTO estoque_movimentacoes (
                empresa_id,
                produto_id,
                produto_nome,
                tipo,
                quantidade,
                saldo_anterior,
                saldo_atual,
                motivo,
                documento,
                responsavel,
                observacoes
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                empresa_id,
                movimentacao["produto_id"],
                movimentacao["produto_nome"],
                movimentacao["tipo"],
                movimentacao["quantidade"],
                movimentacao["saldo_anterior"],
                movimentacao["saldo_atual"],
                movimentacao["motivo"],
                movimentacao["documento"],
                movimentacao["responsavel"],
                movimentacao["observacoes"],
            ),
        )

        conn.execute(
            """
            UPDATE produtos
            SET estoque_atual = ?
            WHERE id = ?
              AND empresa_id = ?
            """,
            (
                movimentacao["saldo_atual"],
                movimentacao["produto_id"],
                empresa_id,
            ),
        )

        conn.commit()

def _formatar_numero_estoque(valor: float) -> str:
    texto = f"{valor:.2f}".replace(".", ",")

    if texto.endswith(",00"):
        return texto[:-3]

    return texto


def montar_estoque_formulario() -> dict[str, str]:
    return {
        "produto_id": (request.form.get("estoque_produto_id") or "").strip(),
        "tipo": (request.form.get("estoque_tipo") or "entrada").strip() or "entrada",
        "quantidade": (request.form.get("estoque_quantidade") or "0").strip(),
        "motivo": (request.form.get("estoque_motivo") or "").strip(),
        "documento": (request.form.get("estoque_documento") or "").strip(),
        "responsavel": (request.form.get("estoque_responsavel") or "").strip(),
        "observacoes": (request.form.get("estoque_observacoes") or "").strip(),
    }


def montar_painel_estoque() -> dict[str, Any]:
    produtos_lista = listar_produtos()
    movimentacoes = listar_estoque_movimentacoes(10)

    total_produtos = len(produtos_lista)
    produtos_com_estoque = 0
    produtos_baixo = 0
    produtos_zerados = 0
    saldo_total = 0.0

    for produto in produtos_lista:
        estoque_atual = _converter_valor_brl(produto.get("estoque_atual"))
        estoque_minimo = _converter_valor_brl(produto.get("estoque_minimo"))

        saldo_total += estoque_atual

        if estoque_atual > 0:
            produtos_com_estoque += 1

        if estoque_atual <= 0:
            produtos_zerados += 1

        if estoque_minimo > 0 and estoque_atual <= estoque_minimo:
            produtos_baixo += 1

    return {
        "total_produtos": total_produtos,
        "produtos_com_estoque": produtos_com_estoque,
        "produtos_baixo": produtos_baixo,
        "produtos_zerados": produtos_zerados,
        "saldo_total": saldo_total,
        "ultimas_movimentacoes": movimentacoes,
    }

def _normalizar_texto_busca(valor: Any) -> str:
    return str(valor or "").strip().casefold()


def buscar_produto_por_descricao_item(descricao: Any) -> dict[str, Any] | None:
    texto_original = str(descricao or "").strip()
    texto_normalizado = _normalizar_texto_busca(texto_original)

    if not texto_normalizado:
        return None

    produtos_lista = listar_produtos()

    for produto in produtos_lista:
        nome = _normalizar_texto_busca(produto.get("nome"))
        codigo = _normalizar_texto_busca(produto.get("codigo"))

        if texto_normalizado == nome or (codigo and texto_normalizado == codigo):
            return produto

    for produto in produtos_lista:
        nome = _normalizar_texto_busca(produto.get("nome"))
        codigo = _normalizar_texto_busca(produto.get("codigo"))

        if nome and nome in texto_normalizado:
            return produto

        if codigo and codigo in texto_normalizado:
            return produto

    return None


def baixar_estoque_por_venda_db(venda_id: int, venda: dict[str, str], itens: list[dict[str, str]]) -> None:
    status_venda = str(venda.get("status") or "").strip()

    if status_venda == "cancelada":
        return

    numero_venda = str(venda.get("numero") or venda_id).strip() or str(venda_id)
    responsavel = str(venda.get("responsavel") or "").strip()

    for item in itens:
        tipo_item = str(item.get("tipo_item") or "").strip()

        if tipo_item != "produto":
            continue

        descricao = str(item.get("descricao") or "").strip()

        if not descricao:
            continue

        produto = buscar_produto_por_descricao_item(descricao)

        if produto is None:
            continue

        quantidade = _converter_valor_brl(item.get("quantidade"))

        if quantidade <= 0:
            quantidade = 1.0

        saldo_anterior_numero = _converter_valor_brl(produto.get("estoque_atual"))
        saldo_atual_numero = saldo_anterior_numero - quantidade

        movimentacao = {
            "produto_id": str(produto.get("id") or ""),
            "produto_nome": str(produto.get("nome") or descricao),
            "tipo": "saida",
            "quantidade": _formatar_numero_estoque(quantidade),
            "saldo_anterior": _formatar_numero_estoque(saldo_anterior_numero),
            "saldo_atual": _formatar_numero_estoque(saldo_atual_numero),
            "motivo": "Venda de produto",
            "documento": f"Venda Nº {numero_venda}",
            "responsavel": responsavel,
            "observacoes": "Baixa automática gerada ao salvar a venda.",
        }

        salvar_estoque_movimentacao_db(movimentacao)


def montar_devolucao_itens_formulario() -> list[dict[str, str]]:
    descricoes = request.form.getlist("devolucao_descricao")
    quantidades = request.form.getlist("devolucao_quantidade")
    detalhes = request.form.getlist("devolucao_detalhes")

    total_itens = max(len(descricoes), len(quantidades), len(detalhes), 0)
    itens: list[dict[str, str]] = []

    for index in range(total_itens):
        descricao = (descricoes[index] if index < len(descricoes) else "").strip()
        quantidade = (quantidades[index] if index < len(quantidades) else "").strip()
        detalhe = (detalhes[index] if index < len(detalhes) else "").strip()

        if not descricao:
            continue

        itens.append(
            {
                "descricao": descricao,
                "quantidade": quantidade,
                "detalhes": detalhe,
            }
        )

    return itens


def devolver_estoque_por_venda_db(
    venda_id: int,
    venda: dict[str, Any],
    itens_devolucao: list[dict[str, str]],
    responsavel: str = "",
    observacoes: str = "",
) -> None:
    numero_venda = str(venda.get("numero") or venda_id).strip() or str(venda_id)
    responsavel = str(responsavel or venda.get("responsavel") or "").strip()
    observacoes = str(observacoes or "").strip()

    for item in itens_devolucao:
        descricao = str(item.get("descricao") or "").strip()

        if not descricao:
            continue

        produto = buscar_produto_por_descricao_item(descricao)

        if produto is None:
            continue

        quantidade = _converter_valor_brl(item.get("quantidade"))

        if quantidade <= 0:
            continue

        saldo_anterior_numero = _converter_valor_brl(produto.get("estoque_atual"))
        saldo_atual_numero = saldo_anterior_numero + quantidade

        texto_observacoes = "Entrada automática gerada por devolução de venda."

        detalhe = str(item.get("detalhes") or "").strip()
        if detalhe:
            texto_observacoes += f"\nItem: {detalhe}"

        if observacoes:
            texto_observacoes += f"\n{observacoes}"

        movimentacao = {
            "produto_id": str(produto.get("id") or ""),
            "produto_nome": str(produto.get("nome") or descricao),
            "tipo": "entrada",
            "quantidade": _formatar_numero_estoque(quantidade),
            "saldo_anterior": _formatar_numero_estoque(saldo_anterior_numero),
            "saldo_atual": _formatar_numero_estoque(saldo_atual_numero),
            "motivo": "Devolução de venda",
            "documento": f"Devolução Venda Nº {numero_venda}",
            "responsavel": responsavel,
            "observacoes": texto_observacoes,
        }

        salvar_estoque_movimentacao_db(movimentacao)


def salvar_servico_db(servico: dict[str, str]) -> None:
    empresa_id = empresa_logada_id()

    with conectar_db() as conn:
        conn.execute(
            """
            INSERT INTO servicos (
                empresa_id,
                nome,
                codigo,
                categoria,
                unidade,
                custo,
                valor_venda,
                tempo_estimado,
                status,
                observacoes
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                empresa_id,
                servico["nome"],
                servico["codigo"],
                servico["categoria"],
                servico["unidade"],
                servico["custo"],
                servico["valor_venda"],
                servico["tempo_estimado"],
                servico["status"],
                servico["observacoes"],
            ),
        )
        conn.commit()

def listar_servicos() -> list[dict[str, Any]]:
    empresa_id = empresa_logada_id()

    with conectar_db() as conn:
        rows = conn.execute(
            """
            SELECT
                id,
                empresa_id,
                nome,
                codigo,
                categoria,
                unidade,
                custo,
                valor_venda,
                tempo_estimado,
                status,
                observacoes,
                criado_em
            FROM servicos
            WHERE empresa_id = ?
            ORDER BY id DESC
            """,
            (empresa_id,),
        ).fetchall()

    return [dict(row) for row in rows]

def buscar_servico_por_id(servico_id: int) -> dict[str, Any] | None:
    empresa_id = empresa_logada_id()

    with conectar_db() as conn:
        row = conn.execute(
            """
            SELECT
                id,
                empresa_id,
                nome,
                codigo,
                categoria,
                unidade,
                custo,
                valor_venda,
                tempo_estimado,
                status,
                observacoes,
                criado_em
            FROM servicos
            WHERE id = ?
              AND empresa_id = ?
            """,
            (servico_id, empresa_id),
        ).fetchone()

    if row is None:
        return None

    return dict(row)

def atualizar_servico_db(servico_id: int, servico: dict[str, str]) -> None:
    empresa_id = empresa_logada_id()

    with conectar_db() as conn:
        conn.execute(
            """
            UPDATE servicos
            SET
                nome = ?,
                codigo = ?,
                categoria = ?,
                unidade = ?,
                custo = ?,
                valor_venda = ?,
                tempo_estimado = ?,
                status = ?,
                observacoes = ?
            WHERE id = ?
              AND empresa_id = ?
            """,
            (
                servico["nome"],
                servico["codigo"],
                servico["categoria"],
                servico["unidade"],
                servico["custo"],
                servico["valor_venda"],
                servico["tempo_estimado"],
                servico["status"],
                servico["observacoes"],
                servico_id,
                empresa_id,
            ),
        )
        conn.commit()

def excluir_servico_db(servico_id: int) -> None:
    empresa_id = empresa_logada_id()

    with conectar_db() as conn:
        conn.execute(
            """
            DELETE FROM servicos
            WHERE id = ?
              AND empresa_id = ?
            """,
            (servico_id, empresa_id),
        )
        conn.commit()

def proximo_numero_orcamento() -> str:
    empresa_id = empresa_logada_id()

    with conectar_db() as conn:
        row = conn.execute(
            """
            SELECT
                COALESCE(MAX(id), 0) + 1 AS proximo
            FROM orcamentos
            WHERE empresa_id = ?
            """,
            (empresa_id,),
        ).fetchone()

    proximo = 1 if row is None else int(row["proximo"])
    return str(proximo).zfill(4)

def salvar_orcamento_db(orcamento: dict[str, str], itens: list[dict[str, str]]) -> int:
    empresa_id = empresa_logada_id()

    with conectar_db() as conn:
        cursor = conn.execute(
            """
            INSERT INTO orcamentos (
                empresa_id,
                numero,
                cliente,
                responsavel,
                data,
                prazo_entrega,
                validade,
                canal_venda,
                centro_custo,
                introducao,
                tipo,
                status,
                total_produtos,
                total_servicos,
                desconto_valor,
                desconto_percentual,
                valor_total,
                forma_pagamento,
                observacoes,
                observacoes_internas
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                empresa_id,
                orcamento["numero"],
                orcamento["cliente"],
                orcamento["responsavel"],
                orcamento["data"],
                orcamento["prazo_entrega"],
                orcamento["validade"],
                orcamento["canal_venda"],
                orcamento["centro_custo"],
                orcamento["introducao"],
                orcamento["tipo"],
                orcamento["status"],
                orcamento["total_produtos"],
                orcamento["total_servicos"],
                orcamento["desconto_valor"],
                orcamento["desconto_percentual"],
                orcamento["valor_total"],
                orcamento["forma_pagamento"],
                orcamento["observacoes"],
                orcamento["observacoes_internas"],
            ),
        )
        orcamento_id = int(cursor.lastrowid)

        for item in itens:
            if not item["descricao"]:
                continue

            conn.execute(
                """
                INSERT INTO orcamento_itens (
                    empresa_id,
                    orcamento_id,
                    tipo_item,
                    descricao,
                    detalhes,
                    quantidade,
                    valor_unitario,
                    desconto,
                    subtotal
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    empresa_id,
                    orcamento_id,
                    item["tipo_item"],
                    item["descricao"],
                    item["detalhes"],
                    item["quantidade"],
                    item["valor_unitario"],
                    item["desconto"],
                    item["subtotal"],
                ),
            )

        conn.commit()

    return orcamento_id

def listar_orcamentos() -> list[dict[str, Any]]:
    empresa_id = empresa_logada_id()

    with conectar_db() as conn:
        rows = conn.execute(
            """
            SELECT
                id,
                empresa_id,
                numero,
                cliente,
                responsavel,
                data,
                prazo_entrega,
                validade,
                canal_venda,
                centro_custo,
                introducao,
                tipo,
                status,
                total_produtos,
                total_servicos,
                desconto_valor,
                desconto_percentual,
                valor_total,
                forma_pagamento,
                observacoes,
                observacoes_internas,
                criado_em
            FROM orcamentos
            WHERE empresa_id = ?
            ORDER BY id DESC
            """,
            (empresa_id,),
        ).fetchall()

    return [dict(row) for row in rows]

def buscar_orcamento_por_id(orcamento_id: int) -> dict[str, Any] | None:
    empresa_id = empresa_logada_id()

    with conectar_db() as conn:
        row = conn.execute(
            """
            SELECT
                id,
                empresa_id,
                numero,
                cliente,
                responsavel,
                data,
                prazo_entrega,
                validade,
                canal_venda,
                centro_custo,
                introducao,
                tipo,
                status,
                total_produtos,
                total_servicos,
                desconto_valor,
                desconto_percentual,
                valor_total,
                forma_pagamento,
                observacoes,
                observacoes_internas,
                criado_em
            FROM orcamentos
            WHERE id = ?
              AND empresa_id = ?
            """,
            (orcamento_id, empresa_id),
        ).fetchone()

    if row is None:
        return None

    return dict(row)

def listar_orcamento_itens(orcamento_id: int) -> list[dict[str, Any]]:
    empresa_id = empresa_logada_id()

    with conectar_db() as conn:
        rows = conn.execute(
            """
            SELECT
                id,
                empresa_id,
                orcamento_id,
                tipo_item,
                descricao,
                detalhes,
                quantidade,
                valor_unitario,
                desconto,
                subtotal,
                criado_em
            FROM orcamento_itens
            WHERE orcamento_id = ?
              AND empresa_id = ?
            ORDER BY id ASC
            """,
            (orcamento_id, empresa_id),
        ).fetchall()

    return [dict(row) for row in rows]

def atualizar_orcamento_db(orcamento_id: int, orcamento: dict[str, str], itens: list[dict[str, str]]) -> None:
    empresa_id = empresa_logada_id()

    with conectar_db() as conn:
        conn.execute(
            """
            UPDATE orcamentos
            SET
                numero = ?,
                cliente = ?,
                responsavel = ?,
                data = ?,
                prazo_entrega = ?,
                validade = ?,
                canal_venda = ?,
                centro_custo = ?,
                introducao = ?,
                tipo = ?,
                status = ?,
                total_produtos = ?,
                total_servicos = ?,
                desconto_valor = ?,
                desconto_percentual = ?,
                valor_total = ?,
                forma_pagamento = ?,
                observacoes = ?,
                observacoes_internas = ?
            WHERE id = ?
              AND empresa_id = ?
            """,
            (
                orcamento["numero"],
                orcamento["cliente"],
                orcamento["responsavel"],
                orcamento["data"],
                orcamento["prazo_entrega"],
                orcamento["validade"],
                orcamento["canal_venda"],
                orcamento["centro_custo"],
                orcamento["introducao"],
                orcamento["tipo"],
                orcamento["status"],
                orcamento["total_produtos"],
                orcamento["total_servicos"],
                orcamento["desconto_valor"],
                orcamento["desconto_percentual"],
                orcamento["valor_total"],
                orcamento["forma_pagamento"],
                orcamento["observacoes"],
                orcamento["observacoes_internas"],
                orcamento_id,
                empresa_id,
            ),
        )

        conn.execute(
            """
            DELETE FROM orcamento_itens
            WHERE orcamento_id = ?
              AND empresa_id = ?
            """,
            (orcamento_id, empresa_id),
        )

        for item in itens:
            if not item["descricao"]:
                continue

            conn.execute(
                """
                INSERT INTO orcamento_itens (
                    empresa_id,
                    orcamento_id,
                    tipo_item,
                    descricao,
                    detalhes,
                    quantidade,
                    valor_unitario,
                    desconto,
                    subtotal
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    empresa_id,
                    orcamento_id,
                    item["tipo_item"],
                    item["descricao"],
                    item["detalhes"],
                    item["quantidade"],
                    item["valor_unitario"],
                    item["desconto"],
                    item["subtotal"],
                ),
            )

        conn.commit()

def excluir_orcamento_db(orcamento_id: int) -> None:
    empresa_id = empresa_logada_id()

    with conectar_db() as conn:
        conn.execute(
            """
            DELETE FROM orcamento_itens
            WHERE orcamento_id = ?
              AND empresa_id = ?
            """,
            (orcamento_id, empresa_id),
        )
        conn.execute(
            """
            DELETE FROM orcamentos
            WHERE id = ?
              AND empresa_id = ?
            """,
            (orcamento_id, empresa_id),
        )
        conn.commit()

def montar_orcamento_formulario(numero_padrao: str = "") -> dict[str, str]:
    return {
        "numero": (request.form.get("orcamento_numero") or numero_padrao).strip(),
        "cliente": (request.form.get("orcamento_cliente") or "").strip(),
        "responsavel": (request.form.get("orcamento_responsavel") or "").strip(),
        "data": (request.form.get("orcamento_data") or "").strip(),
        "prazo_entrega": (request.form.get("orcamento_prazo_entrega") or "").strip(),
        "validade": (request.form.get("orcamento_validade") or "").strip(),
        "canal_venda": (request.form.get("orcamento_canal_venda") or "").strip(),
        "centro_custo": (request.form.get("orcamento_centro_custo") or "").strip(),
        "introducao": (request.form.get("orcamento_introducao") or "").strip(),
        "tipo": (request.form.get("orcamento_tipo") or "misto").strip() or "misto",
        "status": (request.form.get("orcamento_status") or "aberto").strip() or "aberto",
        "total_produtos": (request.form.get("orcamento_total_produtos") or "0,00").strip(),
        "total_servicos": (request.form.get("orcamento_total_servicos") or "0,00").strip(),
        "desconto_valor": (request.form.get("orcamento_desconto_valor") or "0,00").strip(),
        "desconto_percentual": (request.form.get("orcamento_desconto_percentual") or "0,00").strip(),
        "valor_total": (request.form.get("orcamento_valor_total") or "0,00").strip(),
        "forma_pagamento": (request.form.get("orcamento_forma_pagamento") or "").strip(),
        "observacoes": (request.form.get("orcamento_observacoes") or "").strip(),
        "observacoes_internas": (request.form.get("orcamento_observacoes_internas") or "").strip(),
    }


def montar_orcamento_itens_formulario() -> list[dict[str, str]]:
    tipos = request.form.getlist("item_tipo")
    descricoes = request.form.getlist("item_descricao")
    detalhes = request.form.getlist("item_detalhes")
    quantidades = request.form.getlist("item_quantidade")
    valores_unitarios = request.form.getlist("item_valor_unitario")
    descontos = request.form.getlist("item_desconto")
    subtotais = request.form.getlist("item_subtotal")

    total_itens = max(
        len(tipos),
        len(descricoes),
        len(detalhes),
        len(quantidades),
        len(valores_unitarios),
        len(descontos),
        len(subtotais),
        0,
    )

    itens: list[dict[str, str]] = []

    for index in range(total_itens):
        itens.append(
            {
                "tipo_item": (tipos[index] if index < len(tipos) else "produto").strip() or "produto",
                "descricao": (descricoes[index] if index < len(descricoes) else "").strip(),
                "detalhes": (detalhes[index] if index < len(detalhes) else "").strip(),
                "quantidade": (quantidades[index] if index < len(quantidades) else "").strip(),
                "valor_unitario": (valores_unitarios[index] if index < len(valores_unitarios) else "").strip(),
                "desconto": (descontos[index] if index < len(descontos) else "").strip(),
                "subtotal": (subtotais[index] if index < len(subtotais) else "").strip(),
            }
        )

    return itens


def _valor_formulario_positivo(valor: Any) -> bool:
    return _converter_valor_brl(valor) > 0


def _item_documento_valido(item: dict[str, str], exigir_valor: bool = True) -> bool:
    descricao = str(item.get("descricao") or "").strip()
    quantidade = _converter_valor_brl(item.get("quantidade"))
    valor_unitario = _converter_valor_brl(item.get("valor_unitario"))

    if not descricao:
        return False

    if descricao.startswith("__novo"):
        return False

    if quantidade <= 0:
        return False

    if exigir_valor and valor_unitario <= 0:
        return False

    return True


def _existe_item_documento_valido(itens: list[dict[str, str]], exigir_valor: bool = True) -> bool:
    return any(_item_documento_valido(item, exigir_valor=exigir_valor) for item in itens)


def validar_orcamento_para_salvar(orcamento: dict[str, str], itens: list[dict[str, str]]) -> str:
    if not orcamento["cliente"]:
        return "Selecione um cliente para salvar o orçamento."

    if orcamento["cliente"].startswith("__novo"):
        return "Finalize o cadastro do cliente antes de salvar o orçamento."

    if not orcamento["responsavel"]:
        return "Selecione um responsável para salvar o orçamento."

    if orcamento["responsavel"].startswith("__novo"):
        return "Finalize o cadastro do responsável antes de salvar o orçamento."

    if not orcamento["data"]:
        return "Informe a data do orçamento."

    if not orcamento["canal_venda"]:
        return "Informe o canal de venda do orçamento."

    if not _existe_item_documento_valido(itens, exigir_valor=True):
        return "Adicione pelo menos um produto ou serviço com quantidade e valor unitário maiores que zero."

    if not _valor_formulario_positivo(orcamento["valor_total"]):
        return "O valor total do orçamento precisa ser maior que zero."

    return ""


def validar_venda_para_salvar(venda: dict[str, str], itens: list[dict[str, str]]) -> str:
    if not venda["cliente"]:
        return "Selecione um cliente para salvar a venda."

    if venda["cliente"].startswith("__novo"):
        return "Finalize o cadastro do cliente antes de salvar a venda."

    if not venda["responsavel"]:
        return "Selecione um responsável para salvar a venda."

    if venda["responsavel"].startswith("__novo"):
        return "Finalize o cadastro do responsável antes de salvar a venda."

    if not venda["data"]:
        return "Informe a data da venda."

    if not venda["canal_venda"]:
        return "Informe o canal de venda."

    if not venda["forma_pagamento"]:
        return "Informe a forma de pagamento."

    if not _existe_item_documento_valido(itens, exigir_valor=True):
        return "Adicione pelo menos um produto ou serviço com quantidade e valor unitário maiores que zero."

    if not _valor_formulario_positivo(venda["valor_total"]):
        return "O valor total da venda precisa ser maior que zero."

    return ""


def validar_ordem_servico_para_salvar(ordem_servico: dict[str, str], itens: list[dict[str, str]]) -> str:
    if not ordem_servico["cliente"]:
        return "Selecione um cliente para salvar a OS."

    if ordem_servico["cliente"].startswith("__novo"):
        return "Finalize o cadastro do cliente antes de salvar a OS."

    if not ordem_servico["responsavel"]:
        return "Selecione um responsável para salvar a OS."

    if ordem_servico["responsavel"].startswith("__novo"):
        return "Finalize o cadastro do responsável antes de salvar a OS."

    if not ordem_servico["tecnico"]:
        return "Selecione um técnico para salvar a OS."

    if ordem_servico["tecnico"].startswith("__novo"):
        return "Finalize o cadastro do técnico antes de salvar a OS."

    if not ordem_servico["data_abertura"]:
        return "Informe a data de abertura da OS."

    if not ordem_servico["status"]:
        return "Informe o status da OS."

    if not ordem_servico["prioridade"]:
        return "Informe a prioridade da OS."

    tem_item = _existe_item_documento_valido(itens, exigir_valor=False)
    tem_relato = bool(
        ordem_servico["relato_cliente"]
        or ordem_servico["diagnostico"]
        or ordem_servico["servico_executado"]
    )

    if not tem_item and not tem_relato:
        return "Informe ao menos um item, relato do cliente, diagnóstico ou serviço executado."

    return ""


def copiar_orcamento_db(orcamento_id: int) -> int | None:
    orcamento_original = buscar_orcamento_por_id(orcamento_id)

    if orcamento_original is None:
        return None

    itens_originais = listar_orcamento_itens(orcamento_id)
    novo_numero = proximo_numero_orcamento()

    novo_orcamento = {
        "numero": novo_numero,
        "cliente": str(orcamento_original.get("cliente") or ""),
        "responsavel": str(orcamento_original.get("responsavel") or ""),
        "data": str(orcamento_original.get("data") or ""),
        "prazo_entrega": str(orcamento_original.get("prazo_entrega") or ""),
        "validade": str(orcamento_original.get("validade") or ""),
        "canal_venda": str(orcamento_original.get("canal_venda") or ""),
        "centro_custo": str(orcamento_original.get("centro_custo") or ""),
        "introducao": str(orcamento_original.get("introducao") or ""),
        "tipo": str(orcamento_original.get("tipo") or "misto"),
        "status": "aberto",
        "total_produtos": str(orcamento_original.get("total_produtos") or "0,00"),
        "total_servicos": str(orcamento_original.get("total_servicos") or "0,00"),
        "desconto_valor": str(orcamento_original.get("desconto_valor") or "0,00"),
        "desconto_percentual": str(orcamento_original.get("desconto_percentual") or "0,00"),
        "valor_total": str(orcamento_original.get("valor_total") or "0,00"),
        "forma_pagamento": str(orcamento_original.get("forma_pagamento") or ""),
        "observacoes": str(orcamento_original.get("observacoes") or ""),
        "observacoes_internas": str(orcamento_original.get("observacoes_internas") or ""),
    }

    novos_itens: list[dict[str, str]] = []

    for item in itens_originais:
        novos_itens.append(
            {
                "tipo_item": str(item.get("tipo_item") or "produto"),
                "descricao": str(item.get("descricao") or ""),
                "detalhes": str(item.get("detalhes") or ""),
                "quantidade": str(item.get("quantidade") or ""),
                "valor_unitario": str(item.get("valor_unitario") or ""),
                "desconto": str(item.get("desconto") or ""),
                "subtotal": str(item.get("subtotal") or ""),
            }
        )

    return salvar_orcamento_db(novo_orcamento, novos_itens)



def _limpar_lista_formulario(nome: str) -> list[str]:
    return [str(valor or "").strip() for valor in request.form.getlist(nome)]


def _valor_percentual_formulario(nome: str, padrao: float = 0.0) -> float:
    texto = str(request.form.get(nome) or "").strip()
    if not texto:
        return padrao
    return _converter_valor_brl(texto)


def _gerador_item_valor(descricoes: list[str], indice: int) -> str:
    if indice < len(descricoes):
        return str(descricoes[indice] or "").strip()
    return ""



def _formatar_percentual_simples(valor: float) -> str:
    texto = _formatar_moeda_brl(valor)
    if texto.endswith(",00"):
        return texto[:-3]
    if texto.endswith("0"):
        return texto.rstrip("0").rstrip(",")
    return texto


def buscar_configuracao_gerador_empresa() -> dict[str, str]:
    empresa_id = empresa_logada_id()

    padrao = {
        "margem_material": "30",
        "margem_mao_obra": "40",
        "margem_custos": "20",
        "imposto_percentual": "8",
        "administrativo_percentual": "10",
        "reserva_percentual": "5",
    }

    with conectar_db() as conn:
        row = conn.execute(
            """
            SELECT
                gerador_margem_material,
                gerador_margem_mao_obra,
                gerador_margem_custos,
                gerador_imposto_percentual,
                gerador_administrativo_percentual,
                gerador_reserva_percentual
            FROM empresas
            WHERE id = ?
            LIMIT 1
            """,
            (empresa_id,),
        ).fetchone()

    if row is None:
        return padrao

    return {
        "margem_material": str(row["gerador_margem_material"] or padrao["margem_material"]),
        "margem_mao_obra": str(row["gerador_margem_mao_obra"] or padrao["margem_mao_obra"]),
        "margem_custos": str(row["gerador_margem_custos"] or padrao["margem_custos"]),
        "imposto_percentual": str(row["gerador_imposto_percentual"] or padrao["imposto_percentual"]),
        "administrativo_percentual": str(row["gerador_administrativo_percentual"] or padrao["administrativo_percentual"]),
        "reserva_percentual": str(row["gerador_reserva_percentual"] or padrao["reserva_percentual"]),
    }


def salvar_configuracao_gerador_empresa(dados: dict[str, Any]) -> None:
    empresa_id = empresa_logada_id()

    with conectar_db() as conn:
        conn.execute(
            """
            UPDATE empresas
            SET
                gerador_margem_material = ?,
                gerador_margem_mao_obra = ?,
                gerador_margem_custos = ?,
                gerador_imposto_percentual = ?,
                gerador_administrativo_percentual = ?,
                gerador_reserva_percentual = ?,
                gerador_config_atualizado_em = ?
            WHERE id = ?
            """,
            (
                _formatar_percentual_simples(float(dados.get("margem_material") or 0)),
                _formatar_percentual_simples(float(dados.get("margem_mao_obra") or 0)),
                _formatar_percentual_simples(float(dados.get("margem_custos") or 0)),
                _formatar_percentual_simples(float(dados.get("imposto_percentual") or 0)),
                _formatar_percentual_simples(float(dados.get("administrativo_percentual") or 0)),
                _formatar_percentual_simples(float(dados.get("reserva_percentual") or 0)),
                agora_empresa().isoformat(timespec="seconds"),
                empresa_id,
            ),
        )
        conn.commit()


def montar_gerador_orcamento_formulario() -> dict[str, Any]:
    materiais_descricao = _limpar_lista_formulario("material_descricao")
    materiais_unidade = _limpar_lista_formulario("material_unidade")
    materiais_quantidade = _limpar_lista_formulario("material_quantidade")
    materiais_valor = _limpar_lista_formulario("material_valor_unitario")
    materiais_perda = _limpar_lista_formulario("material_perda_percentual")

    mao_funcao = _limpar_lista_formulario("mao_funcao")
    mao_pessoas = _limpar_lista_formulario("mao_pessoas")
    mao_tempo = _limpar_lista_formulario("mao_tempo")
    mao_unidade = _limpar_lista_formulario("mao_unidade")
    mao_custo = _limpar_lista_formulario("mao_custo_unitario")

    custos_descricao = _limpar_lista_formulario("custo_descricao")
    custos_valor = _limpar_lista_formulario("custo_valor")

    materiais: list[dict[str, Any]] = []
    for indice in range(max(len(materiais_descricao), len(materiais_quantidade), len(materiais_valor), 0)):
        descricao = _gerador_item_valor(materiais_descricao, indice)
        if not descricao:
            continue

        quantidade = _converter_valor_brl(_gerador_item_valor(materiais_quantidade, indice))
        valor_unitario = _converter_valor_brl(_gerador_item_valor(materiais_valor, indice))
        perda_percentual = _converter_valor_brl(_gerador_item_valor(materiais_perda, indice))
        custo = quantidade * valor_unitario
        custo_com_perda = custo * (1 + (perda_percentual / 100))

        materiais.append(
            {
                "descricao": descricao,
                "unidade": _gerador_item_valor(materiais_unidade, indice) or "un",
                "quantidade": quantidade,
                "valor_unitario": valor_unitario,
                "perda_percentual": perda_percentual,
                "custo": custo_com_perda,
            }
        )

    mao_obra: list[dict[str, Any]] = []
    for indice in range(max(len(mao_funcao), len(mao_pessoas), len(mao_tempo), len(mao_custo), 0)):
        funcao = _gerador_item_valor(mao_funcao, indice)
        if not funcao:
            continue

        pessoas = _converter_valor_brl(_gerador_item_valor(mao_pessoas, indice)) or 1
        tempo = _converter_valor_brl(_gerador_item_valor(mao_tempo, indice)) or 1
        custo_unitario = _converter_valor_brl(_gerador_item_valor(mao_custo, indice))
        custo = pessoas * tempo * custo_unitario

        mao_obra.append(
            {
                "funcao": funcao,
                "pessoas": pessoas,
                "tempo": tempo,
                "unidade": _gerador_item_valor(mao_unidade, indice) or "dia",
                "custo_unitario": custo_unitario,
                "custo": custo,
            }
        )

    custos_adicionais: list[dict[str, Any]] = []
    for indice in range(max(len(custos_descricao), len(custos_valor), 0)):
        descricao = _gerador_item_valor(custos_descricao, indice)
        if not descricao:
            continue

        valor = _converter_valor_brl(_gerador_item_valor(custos_valor, indice))
        custos_adicionais.append({"descricao": descricao, "valor": valor})

    margem_material = _valor_percentual_formulario("margem_material", 30.0)
    margem_mao_obra = _valor_percentual_formulario("margem_mao_obra", 40.0)
    margem_custos = _valor_percentual_formulario("margem_custos", 20.0)
    imposto_percentual = _valor_percentual_formulario("imposto_percentual", 8.0)
    administrativo_percentual = _valor_percentual_formulario("administrativo_percentual", 10.0)
    reserva_percentual = _valor_percentual_formulario("reserva_percentual", 5.0)

    custo_material = sum(item["custo"] for item in materiais)
    custo_mao_obra = sum(item["custo"] for item in mao_obra)
    custo_adicional = sum(item["valor"] for item in custos_adicionais)
    custo_total = custo_material + custo_mao_obra + custo_adicional

    venda_material = custo_material * (1 + (margem_material / 100))
    venda_mao_obra = custo_mao_obra * (1 + (margem_mao_obra / 100))
    venda_custos = custo_adicional * (1 + (margem_custos / 100))
    base_comercial = venda_material + venda_mao_obra + venda_custos
    administrativo_valor = base_comercial * (administrativo_percentual / 100)
    reserva_valor = base_comercial * (reserva_percentual / 100)
    base_antes_imposto = base_comercial + administrativo_valor + reserva_valor

    divisor_imposto = 1 - (imposto_percentual / 100)
    if divisor_imposto <= 0:
        divisor_imposto = 1

    valor_recomendado = base_antes_imposto / divisor_imposto
    valor_minimo = max(custo_total * 1.10 / divisor_imposto, custo_total)
    valor_ideal = valor_recomendado * 1.15

    tipo_valor = str(request.form.get("valor_escolhido_tipo") or "recomendado").strip()
    valor_customizado = _converter_valor_brl(request.form.get("valor_customizado"))

    if tipo_valor == "minimo":
        valor_escolhido = valor_minimo
    elif tipo_valor == "ideal":
        valor_escolhido = valor_ideal
    elif tipo_valor == "customizado" and valor_customizado > 0:
        valor_escolhido = valor_customizado
    else:
        tipo_valor = "recomendado"
        valor_escolhido = valor_recomendado

    lucro_estimado = valor_escolhido - custo_total
    margem_estimado = (lucro_estimado / valor_escolhido * 100) if valor_escolhido > 0 else 0

    return {
        "cliente": str(request.form.get("gerador_cliente") or "").strip(),
        "responsavel": str(request.form.get("gerador_responsavel") or "").strip(),
        "tipo_servico": str(request.form.get("gerador_tipo_servico") or "Serviço técnico").strip(),
        "data": str(request.form.get("gerador_data") or hoje_empresa().isoformat()).strip(),
        "prazo": str(request.form.get("gerador_prazo") or "").strip(),
        "validade": str(request.form.get("gerador_validade") or "15 dias").strip(),
        "forma_pagamento": str(request.form.get("gerador_forma_pagamento") or "").strip(),
        "escopo": str(request.form.get("gerador_escopo") or "").strip(),
        "observacoes_cliente": str(request.form.get("gerador_observacoes_cliente") or "").strip(),
        "materiais": materiais,
        "mao_obra": mao_obra,
        "custos_adicionais": custos_adicionais,
        "margem_material": margem_material,
        "margem_mao_obra": margem_mao_obra,
        "margem_custos": margem_custos,
        "imposto_percentual": imposto_percentual,
        "administrativo_percentual": administrativo_percentual,
        "reserva_percentual": reserva_percentual,
        "custo_material": custo_material,
        "custo_mao_obra": custo_mao_obra,
        "custo_adicional": custo_adicional,
        "custo_total": custo_total,
        "venda_material": venda_material,
        "venda_mao_obra": venda_mao_obra,
        "venda_custos": venda_custos,
        "administrativo_valor": administrativo_valor,
        "reserva_valor": reserva_valor,
        "valor_minimo": valor_minimo,
        "valor_recomendado": valor_recomendado,
        "valor_ideal": valor_ideal,
        "tipo_valor": tipo_valor,
        "valor_escolhido": valor_escolhido,
        "lucro_estimado": lucro_estimado,
        "margem_estimado": margem_estimado,
    }


def _gerador_alocar_total(valor_total: float, bases: list[float]) -> list[float]:
    soma_bases = sum(max(float(base or 0), 0.0) for base in bases)

    if valor_total <= 0 or soma_bases <= 0 or not bases:
        return [0.0 for _ in bases]

    valores: list[float] = []
    acumulado = 0.0

    for indice, base in enumerate(bases):
        if indice == len(bases) - 1:
            valor = max(valor_total - acumulado, 0.0)
        else:
            valor = round(valor_total * (max(float(base or 0), 0.0) / soma_bases), 2)
            acumulado += valor

        valores.append(valor)

    return valores


def gerar_orcamento_por_gerador_db(dados: dict[str, Any]) -> int:
    valor_total = float(dados.get("valor_escolhido") or 0)
    venda_material = float(dados.get("venda_material") or 0)
    venda_mao_obra = float(dados.get("venda_mao_obra") or 0)
    venda_custos = float(dados.get("venda_custos") or 0)
    materiais = list(dados.get("materiais") or [])

    # Padrão igual ao orçamento manual:
    # - materiais aparecem na seção PRODUTOS;
    # - mão de obra/custos aparecem na seção SERVIÇOS;
    # - impostos, administrativo, reserva técnica e lucro ficam embutidos nos valores.
    bases_grupos = []
    nomes_grupos = []

    if venda_material > 0:
        bases_grupos.append(venda_material)
        nomes_grupos.append("produtos")

    servicos_base = venda_mao_obra + venda_custos
    if servicos_base > 0:
        bases_grupos.append(servicos_base)
        nomes_grupos.append("servicos")

    if not bases_grupos:
        bases_grupos.append(valor_total)
        nomes_grupos.append("servicos")

    valores_grupos = _gerador_alocar_total(valor_total, bases_grupos)
    total_produtos_numero = 0.0
    total_servicos_numero = 0.0

    for nome_grupo, valor_grupo in zip(nomes_grupos, valores_grupos):
        if nome_grupo == "produtos":
            total_produtos_numero += valor_grupo
        else:
            total_servicos_numero += valor_grupo

    itens: list[dict[str, str]] = []

    if total_produtos_numero > 0:
        if materiais:
            bases_materiais = [float(item.get("custo") or 0) for item in materiais]
            valores_materiais = _gerador_alocar_total(total_produtos_numero, bases_materiais)

            for material, valor_material in zip(materiais, valores_materiais):
                descricao = str(material.get("descricao") or "Material aplicado").strip()
                quantidade_numero = float(material.get("quantidade") or 0) or 1.0
                valor_unitario = valor_material / quantidade_numero if quantidade_numero > 0 else valor_material

                itens.append(
                    {
                        "tipo_item": "produto",
                        "descricao": descricao,
                        "detalhes": "Material previsto no Gerador de Orçamentos.",
                        "quantidade": _formatar_numero_estoque(quantidade_numero),
                        "valor_unitario": _formatar_moeda_brl(valor_unitario),
                        "desconto": "0,00",
                        "subtotal": _formatar_moeda_brl(valor_material),
                    }
                )
        else:
            itens.append(
                {
                    "tipo_item": "produto",
                    "descricao": "Materiais aplicados no serviço",
                    "detalhes": "Materiais previstos no Gerador de Orçamentos.",
                    "quantidade": "1",
                    "valor_unitario": _formatar_moeda_brl(total_produtos_numero),
                    "desconto": "0,00",
                    "subtotal": _formatar_moeda_brl(total_produtos_numero),
                }
            )

    if total_servicos_numero > 0:
        bases_servicos = []
        descricoes_servicos: list[tuple[str, str]] = []

        if venda_mao_obra > 0:
            bases_servicos.append(venda_mao_obra)
            descricoes_servicos.append(
                (
                    "Mão de obra técnica",
                    "Equipe técnica, tempo de execução e mobilização conforme escopo do serviço.",
                )
            )

        if venda_custos > 0:
            bases_servicos.append(venda_custos)
            descricoes_servicos.append(
                (
                    "Custos operacionais",
                    "Deslocamento, ferramentas, consumíveis e demais custos operacionais necessários à execução.",
                )
            )

        if not bases_servicos:
            bases_servicos.append(total_servicos_numero)
            descricoes_servicos.append(
                (
                    "Serviço técnico conforme escopo",
                    str(dados.get("escopo") or "Serviço técnico gerado pelo Gerador de Orçamentos."),
                )
            )

        valores_servicos = _gerador_alocar_total(total_servicos_numero, bases_servicos)

        for (descricao, detalhes), valor_servico in zip(descricoes_servicos, valores_servicos):
            if valor_servico <= 0:
                continue

            itens.append(
                {
                    "tipo_item": "servico",
                    "descricao": descricao,
                    "detalhes": detalhes,
                    "quantidade": "1",
                    "valor_unitario": _formatar_moeda_brl(valor_servico),
                    "desconto": "0,00",
                    "subtotal": _formatar_moeda_brl(valor_servico),
                }
            )

    detalhes_internos = [
        "Orçamento gerado pelo Gerador de Orçamentos.",
        "Materiais separados como PRODUTOS e mão de obra/custos separados como SERVIÇOS, mantendo o padrão do orçamento manual.",
        "A composição de impostos, administrativo, reserva técnica e lucro foi embutida nos itens comerciais.",
        f"Tipo de serviço: {dados.get('tipo_servico') or '-'}",
        f"Valor escolhido: {dados.get('tipo_valor') or 'recomendado'}",
        f"Custo material: R$ {_formatar_moeda_brl(float(dados.get('custo_material') or 0))}",
        f"Custo mão de obra: R$ {_formatar_moeda_brl(float(dados.get('custo_mao_obra') or 0))}",
        f"Custos adicionais: R$ {_formatar_moeda_brl(float(dados.get('custo_adicional') or 0))}",
        f"Custo total: R$ {_formatar_moeda_brl(float(dados.get('custo_total') or 0))}",
        f"Lucro estimado: R$ {_formatar_moeda_brl(float(dados.get('lucro_estimado') or 0))}",
        f"Margem estimada: {_formatar_moeda_brl(float(dados.get('margem_estimado') or 0))}%",
    ]

    escopo = str(dados.get("escopo") or "").replace("\\n", "\n").strip()
    observacoes_cliente = str(dados.get("observacoes_cliente") or "").replace("\\n", "\n").strip()
    observacoes = observacoes_cliente
    if escopo:
        observacoes = f"Escopo: {escopo}"
        if observacoes_cliente:
            observacoes += f"\n\n{observacoes_cliente}"

    if total_produtos_numero > 0 and total_servicos_numero > 0:
        tipo_orcamento = "misto"
    elif total_produtos_numero > 0:
        tipo_orcamento = "produto"
    else:
        tipo_orcamento = "servico"

    orcamento = {
        "numero": proximo_numero_orcamento(),
        "cliente": str(dados.get("cliente") or ""),
        "responsavel": str(dados.get("responsavel") or ""),
        "data": str(dados.get("data") or hoje_empresa().isoformat()),
        "prazo_entrega": str(dados.get("prazo") or ""),
        "validade": str(dados.get("validade") or "15 dias"),
        "canal_venda": "Gerador de Orçamentos",
        "centro_custo": str(dados.get("tipo_servico") or "Serviço técnico"),
        "introducao": "GESTFLOW apresenta abaixo sua proposta comercial para fornecimento de produtos e/ou execução de serviços conforme solicitado:",
        "tipo": tipo_orcamento,
        "status": "aberto",
        "total_produtos": _formatar_moeda_brl(total_produtos_numero),
        "total_servicos": _formatar_moeda_brl(total_servicos_numero),
        "desconto_valor": "0,00",
        "desconto_percentual": "0,00",
        "valor_total": _formatar_moeda_brl(valor_total),
        "forma_pagamento": str(dados.get("forma_pagamento") or ""),
        "observacoes": observacoes,
        "observacoes_internas": "\n".join(detalhes_internos),
    }

    return salvar_orcamento_db(orcamento, itens)

def proximo_numero_venda() -> str:
    empresa_id = empresa_logada_id()

    with conectar_db() as conn:
        row = conn.execute(
            """
            SELECT
                COALESCE(MAX(id), 0) + 1 AS proximo
            FROM vendas
            WHERE empresa_id = ?
            """,
            (empresa_id,),
        ).fetchone()

    proximo = 1 if row is None else int(row["proximo"])
    return str(proximo).zfill(4)

def salvar_venda_db(venda: dict[str, str], itens: list[dict[str, str]]) -> int:
    empresa_id = empresa_logada_id()

    with conectar_db() as conn:
        cursor = conn.execute(
            """
            INSERT INTO vendas (
                empresa_id,
                numero,
                cliente,
                responsavel,
                data,
                prazo_entrega,
                canal_venda,
                centro_custo,
                tipo,
                status,
                total_produtos,
                total_servicos,
                desconto_valor,
                desconto_percentual,
                valor_total,
                forma_pagamento,
                observacoes,
                observacoes_internas
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                empresa_id,
                venda["numero"],
                venda["cliente"],
                venda["responsavel"],
                venda["data"],
                venda["prazo_entrega"],
                venda["canal_venda"],
                venda["centro_custo"],
                venda["tipo"],
                venda["status"],
                venda["total_produtos"],
                venda["total_servicos"],
                venda["desconto_valor"],
                venda["desconto_percentual"],
                venda["valor_total"],
                venda["forma_pagamento"],
                venda["observacoes"],
                venda["observacoes_internas"],
            ),
        )
        venda_id = int(cursor.lastrowid)

        for item in itens:
            if not item["descricao"]:
                continue

            conn.execute(
                """
                INSERT INTO venda_itens (
                    empresa_id,
                    venda_id,
                    tipo_item,
                    descricao,
                    detalhes,
                    quantidade,
                    valor_unitario,
                    desconto,
                    subtotal
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    empresa_id,
                    venda_id,
                    item["tipo_item"],
                    item["descricao"],
                    item["detalhes"],
                    item["quantidade"],
                    item["valor_unitario"],
                    item["desconto"],
                    item["subtotal"],
                ),
            )

        conn.commit()

    return venda_id

def copiar_venda_db(venda_id: int) -> int | None:
    venda_original = buscar_venda_por_id(venda_id)

    if venda_original is None:
        return None

    itens_originais = listar_venda_itens(venda_id)
    novo_numero = proximo_numero_venda()

    nova_venda = {
        "numero": novo_numero,
        "cliente": str(venda_original.get("cliente") or ""),
        "responsavel": str(venda_original.get("responsavel") or ""),
        "data": str(venda_original.get("data") or ""),
        "prazo_entrega": str(venda_original.get("prazo_entrega") or ""),
        "canal_venda": str(venda_original.get("canal_venda") or ""),
        "centro_custo": str(venda_original.get("centro_custo") or ""),
        "tipo": str(venda_original.get("tipo") or "misto"),
        "status": "aberta",
        "total_produtos": str(venda_original.get("total_produtos") or "0,00"),
        "total_servicos": str(venda_original.get("total_servicos") or "0,00"),
        "desconto_valor": str(venda_original.get("desconto_valor") or "0,00"),
        "desconto_percentual": str(venda_original.get("desconto_percentual") or "0,00"),
        "valor_total": str(venda_original.get("valor_total") or "0,00"),
        "forma_pagamento": str(venda_original.get("forma_pagamento") or ""),
        "observacoes": str(venda_original.get("observacoes") or ""),
        "observacoes_internas": str(venda_original.get("observacoes_internas") or ""),
    }

    novos_itens: list[dict[str, str]] = []

    for item in itens_originais:
        novos_itens.append(
            {
                "tipo_item": str(item.get("tipo_item") or "produto"),
                "descricao": str(item.get("descricao") or ""),
                "detalhes": str(item.get("detalhes") or ""),
                "quantidade": str(item.get("quantidade") or ""),
                "valor_unitario": str(item.get("valor_unitario") or ""),
                "desconto": str(item.get("desconto") or ""),
                "subtotal": str(item.get("subtotal") or ""),
            }
        )

    return salvar_venda_db(nova_venda, novos_itens)

def listar_vendas() -> list[dict[str, Any]]:
    empresa_id = empresa_logada_id()

    with conectar_db() as conn:
        rows = conn.execute(
            """
            SELECT
                id,
                empresa_id,
                numero,
                cliente,
                responsavel,
                data,
                prazo_entrega,
                canal_venda,
                centro_custo,
                tipo,
                status,
                total_produtos,
                total_servicos,
                desconto_valor,
                desconto_percentual,
                valor_total,
                forma_pagamento,
                observacoes,
                observacoes_internas,
                criado_em
            FROM vendas
            WHERE empresa_id = ?
            ORDER BY id DESC
            """,
            (empresa_id,),
        ).fetchall()

    return [dict(row) for row in rows]

def buscar_venda_por_id(venda_id: int) -> dict[str, Any] | None:
    empresa_id = empresa_logada_id()

    with conectar_db() as conn:
        row = conn.execute(
            """
            SELECT
                id,
                empresa_id,
                numero,
                cliente,
                responsavel,
                data,
                prazo_entrega,
                canal_venda,
                centro_custo,
                tipo,
                status,
                total_produtos,
                total_servicos,
                desconto_valor,
                desconto_percentual,
                valor_total,
                forma_pagamento,
                observacoes,
                observacoes_internas,
                criado_em
            FROM vendas
            WHERE id = ?
              AND empresa_id = ?
            """,
            (venda_id, empresa_id),
        ).fetchone()

    if row is None:
        return None

    return dict(row)

def listar_venda_itens(venda_id: int) -> list[dict[str, Any]]:
    empresa_id = empresa_logada_id()

    with conectar_db() as conn:
        rows = conn.execute(
            """
            SELECT
                id,
                empresa_id,
                venda_id,
                tipo_item,
                descricao,
                detalhes,
                quantidade,
                valor_unitario,
                desconto,
                subtotal,
                criado_em
            FROM venda_itens
            WHERE venda_id = ?
              AND empresa_id = ?
            ORDER BY id ASC
            """,
            (venda_id, empresa_id),
        ).fetchall()

    return [dict(row) for row in rows]

def atualizar_venda_db(venda_id: int, venda: dict[str, str], itens: list[dict[str, str]]) -> None:
    empresa_id = empresa_logada_id()

    with conectar_db() as conn:
        conn.execute(
            """
            UPDATE vendas
            SET
                numero = ?,
                cliente = ?,
                responsavel = ?,
                data = ?,
                prazo_entrega = ?,
                canal_venda = ?,
                centro_custo = ?,
                tipo = ?,
                status = ?,
                total_produtos = ?,
                total_servicos = ?,
                desconto_valor = ?,
                desconto_percentual = ?,
                valor_total = ?,
                forma_pagamento = ?,
                observacoes = ?,
                observacoes_internas = ?
            WHERE id = ?
              AND empresa_id = ?
            """,
            (
                venda["numero"],
                venda["cliente"],
                venda["responsavel"],
                venda["data"],
                venda["prazo_entrega"],
                venda["canal_venda"],
                venda["centro_custo"],
                venda["tipo"],
                venda["status"],
                venda["total_produtos"],
                venda["total_servicos"],
                venda["desconto_valor"],
                venda["desconto_percentual"],
                venda["valor_total"],
                venda["forma_pagamento"],
                venda["observacoes"],
                venda["observacoes_internas"],
                venda_id,
                empresa_id,
            ),
        )

        conn.execute(
            """
            DELETE FROM venda_itens
            WHERE venda_id = ?
              AND empresa_id = ?
            """,
            (venda_id, empresa_id),
        )

        for item in itens:
            if not item["descricao"]:
                continue

            conn.execute(
                """
                INSERT INTO venda_itens (
                    empresa_id,
                    venda_id,
                    tipo_item,
                    descricao,
                    detalhes,
                    quantidade,
                    valor_unitario,
                    desconto,
                    subtotal
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    empresa_id,
                    venda_id,
                    item["tipo_item"],
                    item["descricao"],
                    item["detalhes"],
                    item["quantidade"],
                    item["valor_unitario"],
                    item["desconto"],
                    item["subtotal"],
                ),
            )

        conn.commit()

def excluir_venda_db(venda_id: int) -> None:
    empresa_id = empresa_logada_id()

    with conectar_db() as conn:
        conn.execute(
            """
            DELETE FROM venda_itens
            WHERE venda_id = ?
              AND empresa_id = ?
            """,
            (venda_id, empresa_id),
        )
        conn.execute(
            """
            DELETE FROM vendas
            WHERE id = ?
              AND empresa_id = ?
            """,
            (venda_id, empresa_id),
        )
        conn.commit()

def montar_venda_formulario(numero_padrao: str = "") -> dict[str, str]:
    return {
        "numero": (request.form.get("venda_numero") or numero_padrao).strip(),
        "cliente": (request.form.get("venda_cliente") or "").strip(),
        "responsavel": (request.form.get("venda_responsavel") or "").strip(),
        "data": (request.form.get("venda_data") or "").strip(),
        "prazo_entrega": (request.form.get("venda_prazo_entrega") or "").strip(),
        "canal_venda": (request.form.get("venda_canal_venda") or "").strip(),
        "centro_custo": (request.form.get("venda_centro_custo") or "").strip(),
        "tipo": (request.form.get("venda_tipo") or "misto").strip() or "misto",
        "status": (request.form.get("venda_status") or "aberta").strip() or "aberta",
        "total_produtos": (request.form.get("venda_total_produtos") or "0,00").strip(),
        "total_servicos": (request.form.get("venda_total_servicos") or "0,00").strip(),
        "desconto_valor": (request.form.get("venda_desconto_valor") or "0,00").strip(),
        "desconto_percentual": (request.form.get("venda_desconto_percentual") or "0,00").strip(),
        "valor_total": (request.form.get("venda_valor_total") or "0,00").strip(),
        "forma_pagamento": (request.form.get("venda_forma_pagamento") or "").strip(),
        "observacoes": (request.form.get("venda_observacoes") or "").strip(),
        "observacoes_internas": (request.form.get("venda_observacoes_internas") or "").strip(),
    }


def montar_venda_itens_formulario() -> list[dict[str, str]]:
    tipos = request.form.getlist("item_tipo")
    descricoes = request.form.getlist("item_descricao")
    detalhes = request.form.getlist("item_detalhes")
    quantidades = request.form.getlist("item_quantidade")
    valores_unitarios = request.form.getlist("item_valor_unitario")
    descontos = request.form.getlist("item_desconto")
    subtotais = request.form.getlist("item_subtotal")

    total_itens = max(
        len(tipos),
        len(descricoes),
        len(detalhes),
        len(quantidades),
        len(valores_unitarios),
        len(descontos),
        len(subtotais),
        0,
    )

    itens: list[dict[str, str]] = []

    for index in range(total_itens):
        itens.append(
            {
                "tipo_item": (tipos[index] if index < len(tipos) else "produto").strip() or "produto",
                "descricao": (descricoes[index] if index < len(descricoes) else "").strip(),
                "detalhes": (detalhes[index] if index < len(detalhes) else "").strip(),
                "quantidade": (quantidades[index] if index < len(quantidades) else "").strip(),
                "valor_unitario": (valores_unitarios[index] if index < len(valores_unitarios) else "").strip(),
                "desconto": (descontos[index] if index < len(descontos) else "").strip(),
                "subtotal": (subtotais[index] if index < len(subtotais) else "").strip(),
            }
        )

    return itens


def proximo_numero_ordem_servico() -> str:
    empresa_id = empresa_logada_id()

    with conectar_db() as conn:
        row = conn.execute(
            """
            SELECT
                COALESCE(MAX(id), 0) + 1 AS proximo
            FROM ordens_servico
            WHERE empresa_id = ?
            """,
            (empresa_id,),
        ).fetchone()

    proximo = 1 if row is None else int(row["proximo"])
    return str(proximo).zfill(4)

def salvar_ordem_servico_db(ordem_servico: dict[str, str], itens: list[dict[str, str]]) -> int:
    empresa_id = empresa_logada_id()

    with conectar_db() as conn:
        cursor = conn.execute(
            """
            INSERT INTO ordens_servico (
                empresa_id,
                numero,
                cliente,
                responsavel,
                tecnico,
                data_abertura,
                data_previsao,
                data_saida,
                hora_entrada,
                hora_saida,
                canal_venda,
                centro_custo,
                equipamento,
                marca,
                modelo,
                serie,
                local_servico,
                condicoes,
                acessorios,
                laudo,
                termos,
                informar_endereco_entrega,
                endereco_entrega,
                bairro_entrega,
                cidade_entrega,
                origem_venda_id,
                tipo,
                status,
                prioridade,
                total_produtos,
                total_servicos,
                frete,
                outros,
                desconto_valor,
                valor_total,
                forma_pagamento,
                exibir_valor_impressao,
                relato_cliente,
                diagnostico,
                servico_executado,
                observacoes,
                observacoes_internas
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                empresa_id,
                ordem_servico["numero"],
                ordem_servico["cliente"],
                ordem_servico["responsavel"],
                ordem_servico["tecnico"],
                ordem_servico["data_abertura"],
                ordem_servico["data_previsao"],
                ordem_servico["data_saida"],
                ordem_servico["hora_entrada"],
                ordem_servico["hora_saida"],
                ordem_servico["canal_venda"],
                ordem_servico["centro_custo"],
                ordem_servico["equipamento"],
                ordem_servico["marca"],
                ordem_servico["modelo"],
                ordem_servico["serie"],
                ordem_servico["local_servico"],
                ordem_servico["condicoes"],
                ordem_servico["acessorios"],
                ordem_servico["laudo"],
                ordem_servico["termos"],
                ordem_servico["informar_endereco_entrega"],
                ordem_servico["endereco_entrega"],
                ordem_servico["bairro_entrega"],
                ordem_servico["cidade_entrega"],
                ordem_servico["origem_venda_id"],
                ordem_servico["tipo"],
                ordem_servico["status"],
                ordem_servico["prioridade"],
                ordem_servico["total_produtos"],
                ordem_servico["total_servicos"],
                ordem_servico["frete"],
                ordem_servico["outros"],
                ordem_servico["desconto_valor"],
                ordem_servico["valor_total"],
                ordem_servico["forma_pagamento"],
                ordem_servico["exibir_valor_impressao"],
                ordem_servico["relato_cliente"],
                ordem_servico["diagnostico"],
                ordem_servico["servico_executado"],
                ordem_servico["observacoes"],
                ordem_servico["observacoes_internas"],
            ),
        )
        ordem_servico_id = int(cursor.lastrowid)

        for item in itens:
            if not item["descricao"]:
                continue

            conn.execute(
                """
                INSERT INTO ordem_servico_itens (
                    empresa_id,
                    ordem_servico_id,
                    tipo_item,
                    descricao,
                    detalhes,
                    quantidade,
                    valor_unitario,
                    desconto,
                    subtotal
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    empresa_id,
                    ordem_servico_id,
                    item["tipo_item"],
                    item["descricao"],
                    item["detalhes"],
                    item["quantidade"],
                    item["valor_unitario"],
                    item["desconto"],
                    item["subtotal"],
                ),
            )

        conn.commit()

    return ordem_servico_id

def atualizar_ordem_servico_db(ordem_servico_id: int, ordem_servico: dict[str, str], itens: list[dict[str, str]]) -> None:
    empresa_id = empresa_logada_id()

    with conectar_db() as conn:
        conn.execute(
            """
            UPDATE ordens_servico
            SET
                numero = ?,
                cliente = ?,
                responsavel = ?,
                tecnico = ?,
                data_abertura = ?,
                data_previsao = ?,
                data_saida = ?,
                hora_entrada = ?,
                hora_saida = ?,
                canal_venda = ?,
                centro_custo = ?,
                equipamento = ?,
                marca = ?,
                modelo = ?,
                serie = ?,
                local_servico = ?,
                condicoes = ?,
                acessorios = ?,
                laudo = ?,
                termos = ?,
                informar_endereco_entrega = ?,
                endereco_entrega = ?,
                bairro_entrega = ?,
                cidade_entrega = ?,
                origem_venda_id = ?,
                tipo = ?,
                status = ?,
                prioridade = ?,
                total_produtos = ?,
                total_servicos = ?,
                frete = ?,
                outros = ?,
                desconto_valor = ?,
                valor_total = ?,
                forma_pagamento = ?,
                exibir_valor_impressao = ?,
                relato_cliente = ?,
                diagnostico = ?,
                servico_executado = ?,
                observacoes = ?,
                observacoes_internas = ?
            WHERE id = ?
              AND empresa_id = ?
            """,
            (
                ordem_servico["numero"],
                ordem_servico["cliente"],
                ordem_servico["responsavel"],
                ordem_servico["tecnico"],
                ordem_servico["data_abertura"],
                ordem_servico["data_previsao"],
                ordem_servico["data_saida"],
                ordem_servico["hora_entrada"],
                ordem_servico["hora_saida"],
                ordem_servico["canal_venda"],
                ordem_servico["centro_custo"],
                ordem_servico["equipamento"],
                ordem_servico["marca"],
                ordem_servico["modelo"],
                ordem_servico["serie"],
                ordem_servico["local_servico"],
                ordem_servico["condicoes"],
                ordem_servico["acessorios"],
                ordem_servico["laudo"],
                ordem_servico["termos"],
                ordem_servico["informar_endereco_entrega"],
                ordem_servico["endereco_entrega"],
                ordem_servico["bairro_entrega"],
                ordem_servico["cidade_entrega"],
                ordem_servico["origem_venda_id"],
                ordem_servico["tipo"],
                ordem_servico["status"],
                ordem_servico["prioridade"],
                ordem_servico["total_produtos"],
                ordem_servico["total_servicos"],
                ordem_servico["frete"],
                ordem_servico["outros"],
                ordem_servico["desconto_valor"],
                ordem_servico["valor_total"],
                ordem_servico["forma_pagamento"],
                ordem_servico["exibir_valor_impressao"],
                ordem_servico["relato_cliente"],
                ordem_servico["diagnostico"],
                ordem_servico["servico_executado"],
                ordem_servico["observacoes"],
                ordem_servico["observacoes_internas"],
                ordem_servico_id,
                empresa_id,
            ),
        )

        conn.execute(
            """
            DELETE FROM ordem_servico_itens
            WHERE ordem_servico_id = ?
              AND empresa_id = ?
            """,
            (ordem_servico_id, empresa_id),
        )

        for item in itens:
            if not item["descricao"]:
                continue

            conn.execute(
                """
                INSERT INTO ordem_servico_itens (
                    empresa_id,
                    ordem_servico_id,
                    tipo_item,
                    descricao,
                    detalhes,
                    quantidade,
                    valor_unitario,
                    desconto,
                    subtotal
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    empresa_id,
                    ordem_servico_id,
                    item["tipo_item"],
                    item["descricao"],
                    item["detalhes"],
                    item["quantidade"],
                    item["valor_unitario"],
                    item["desconto"],
                    item["subtotal"],
                ),
            )

        conn.commit()

def listar_ordens_servico() -> list[dict[str, Any]]:
    empresa_id = empresa_logada_id()

    with conectar_db() as conn:
        rows = conn.execute(
            """
            SELECT
                id,
                empresa_id,
                numero,
                cliente,
                responsavel,
                tecnico,
                data_abertura,
                data_previsao,
                data_saida,
                hora_entrada,
                hora_saida,
                canal_venda,
                centro_custo,
                equipamento,
                marca,
                modelo,
                serie,
                local_servico,
                condicoes,
                acessorios,
                laudo,
                termos,
                informar_endereco_entrega,
                endereco_entrega,
                bairro_entrega,
                cidade_entrega,
                origem_venda_id,
                tipo,
                status,
                prioridade,
                total_produtos,
                total_servicos,
                frete,
                outros,
                desconto_valor,
                valor_total,
                forma_pagamento,
                exibir_valor_impressao,
                relato_cliente,
                diagnostico,
                servico_executado,
                observacoes,
                observacoes_internas,
                criado_em
            FROM ordens_servico
            WHERE empresa_id = ?
            ORDER BY id DESC
            """,
            (empresa_id,),
        ).fetchall()

    return [dict(row) for row in rows]

def buscar_ordem_servico_por_id(ordem_servico_id: int) -> dict[str, Any] | None:
    empresa_id = empresa_logada_id()

    with conectar_db() as conn:
        row = conn.execute(
            """
            SELECT
                id,
                empresa_id,
                numero,
                cliente,
                responsavel,
                tecnico,
                data_abertura,
                data_previsao,
                data_saida,
                hora_entrada,
                hora_saida,
                canal_venda,
                centro_custo,
                equipamento,
                marca,
                modelo,
                serie,
                local_servico,
                condicoes,
                acessorios,
                laudo,
                termos,
                informar_endereco_entrega,
                endereco_entrega,
                bairro_entrega,
                cidade_entrega,
                origem_venda_id,
                tipo,
                status,
                prioridade,
                total_produtos,
                total_servicos,
                frete,
                outros,
                desconto_valor,
                valor_total,
                forma_pagamento,
                exibir_valor_impressao,
                relato_cliente,
                diagnostico,
                servico_executado,
                observacoes,
                observacoes_internas,
                criado_em
            FROM ordens_servico
            WHERE id = ?
              AND empresa_id = ?
            """,
            (ordem_servico_id, empresa_id),
        ).fetchone()

    if row is None:
        return None

    return dict(row)

def listar_ordem_servico_itens(ordem_servico_id: int) -> list[dict[str, Any]]:
    empresa_id = empresa_logada_id()

    with conectar_db() as conn:
        rows = conn.execute(
            """
            SELECT
                id,
                empresa_id,
                ordem_servico_id,
                tipo_item,
                descricao,
                detalhes,
                quantidade,
                valor_unitario,
                desconto,
                subtotal,
                criado_em
            FROM ordem_servico_itens
            WHERE ordem_servico_id = ?
              AND empresa_id = ?
            ORDER BY id ASC
            """,
            (ordem_servico_id, empresa_id),
        ).fetchall()

    return [dict(row) for row in rows]


def listar_acompanhamentos_ordem_servico(ordem_servico_id: int) -> list[dict[str, Any]]:
    empresa_id = empresa_logada_id()

    with conectar_db() as conn:
        rows = conn.execute(
            """
            SELECT
                id,
                empresa_id,
                ordem_servico_id,
                token,
                data_acompanhamento,
                responsavel,
                status_link,
                status_dia,
                atividades_previstas,
                equipe_prevista,
                materiais_previstos,
                atividades_executadas,
                equipe_real,
                materiais_utilizados,
                observacoes,
                aberto_em,
                finalizado_em,
                expira_em,
                criado_em,
                atualizado_em
            FROM os_acompanhamentos
            WHERE ordem_servico_id = ?
              AND empresa_id = ?
            ORDER BY id DESC
            """,
            (ordem_servico_id, empresa_id),
        ).fetchall()

    return [dict(row) for row in rows]


def listar_equipe_acompanhamento(acompanhamento_id: int, empresa_id: int | None = None) -> list[dict[str, Any]]:
    parametros: list[Any] = [acompanhamento_id]
    filtro_empresa = ""

    if empresa_id is not None:
        filtro_empresa = " AND empresa_id = ?"
        parametros.append(empresa_id)

    with conectar_db() as conn:
        rows = conn.execute(
            f"""
            SELECT
                id,
                empresa_id,
                acompanhamento_id,
                funcionario_id,
                nome,
                cargo,
                horas,
                observacoes,
                criado_em
            FROM os_acompanhamento_equipe
            WHERE acompanhamento_id = ?
            {filtro_empresa}
            ORDER BY id ASC
            """,
            parametros,
        ).fetchall()

    return [dict(row) for row in rows]


def listar_materiais_acompanhamento(acompanhamento_id: int, empresa_id: int | None = None) -> list[dict[str, Any]]:
    parametros: list[Any] = [acompanhamento_id]
    filtro_empresa = ""

    if empresa_id is not None:
        filtro_empresa = " AND empresa_id = ?"
        parametros.append(empresa_id)

    with conectar_db() as conn:
        rows = conn.execute(
            f"""
            SELECT
                id,
                empresa_id,
                acompanhamento_id,
                produto_id,
                nome,
                unidade,
                quantidade,
                observacoes,
                criado_em
            FROM os_acompanhamento_materiais
            WHERE acompanhamento_id = ?
            {filtro_empresa}
            ORDER BY id ASC
            """,
            parametros,
        ).fetchall()

    return [dict(row) for row in rows]


def listar_servicos_acompanhamento(acompanhamento_id: int, empresa_id: int | None = None) -> list[dict[str, Any]]:
    parametros: list[Any] = [acompanhamento_id]
    filtro_empresa = ""

    if empresa_id is not None:
        filtro_empresa = " AND empresa_id = ?"
        parametros.append(empresa_id)

    with conectar_db() as conn:
        rows = conn.execute(
            f"""
            SELECT
                id,
                empresa_id,
                acompanhamento_id,
                servico_id,
                nome,
                quantidade,
                observacoes,
                criado_em
            FROM os_acompanhamento_servicos
            WHERE acompanhamento_id = ?
            {filtro_empresa}
            ORDER BY id ASC
            """,
            parametros,
        ).fetchall()

    return [dict(row) for row in rows]


def listar_itens_acompanhamento(acompanhamento_id: int, empresa_id: int | None = None) -> dict[str, list[dict[str, Any]]]:
    return {
        "equipe": listar_equipe_acompanhamento(acompanhamento_id, empresa_id),
        "materiais": listar_materiais_acompanhamento(acompanhamento_id, empresa_id),
        "servicos": listar_servicos_acompanhamento(acompanhamento_id, empresa_id),
    }


def anexar_itens_aos_acompanhamentos(acompanhamentos: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not acompanhamentos:
        return []

    acompanhamentos_normalizados = [dict(acompanhamento) for acompanhamento in acompanhamentos]

    for acompanhamento in acompanhamentos_normalizados:
        acompanhamento_id = int(acompanhamento.get("id") or 0)
        empresa_id = int(acompanhamento.get("empresa_id") or empresa_logada_id())
        itens = listar_itens_acompanhamento(acompanhamento_id, empresa_id)
        acompanhamento["equipe_lista"] = itens["equipe"]
        acompanhamento["materiais_lista"] = itens["materiais"]
        acompanhamento["servicos_lista"] = itens["servicos"]

    return acompanhamentos_normalizados


def listar_funcionarios_acompanhamento_publico(empresa_id: int) -> list[dict[str, Any]]:
    with conectar_db() as conn:
        rows = conn.execute(
            """
            SELECT
                id,
                empresa_id,
                nome,
                cargo,
                status
            FROM funcionarios
            WHERE empresa_id = ?
              AND LOWER(COALESCE(status, 'ativo')) = 'ativo'
            ORDER BY nome ASC
            """,
            (empresa_id,),
        ).fetchall()

    return [dict(row) for row in rows]


def listar_produtos_acompanhamento_publico(empresa_id: int) -> list[dict[str, Any]]:
    with conectar_db() as conn:
        rows = conn.execute(
            """
            SELECT
                id,
                empresa_id,
                nome,
                codigo,
                unidade,
                status
            FROM produtos
            WHERE empresa_id = ?
              AND LOWER(COALESCE(status, 'ativo')) = 'ativo'
            ORDER BY nome ASC
            """,
            (empresa_id,),
        ).fetchall()

    return [dict(row) for row in rows]


def listar_servicos_acompanhamento_publico(empresa_id: int) -> list[dict[str, Any]]:
    with conectar_db() as conn:
        rows = conn.execute(
            """
            SELECT
                id,
                empresa_id,
                nome,
                unidade,
                status
            FROM servicos
            WHERE empresa_id = ?
              AND LOWER(COALESCE(status, 'ativo')) = 'ativo'
            ORDER BY nome ASC
            """,
            (empresa_id,),
        ).fetchall()

    return [dict(row) for row in rows]


def _converter_inteiro_positivo(valor: Any) -> int | None:
    try:
        numero = int(str(valor or "").strip())
    except ValueError:
        return None

    if numero <= 0:
        return None

    return numero


def montar_itens_acompanhamento_formulario(formulario: Any) -> dict[str, list[dict[str, str]]]:
    equipe: list[dict[str, str]] = []
    materiais: list[dict[str, str]] = []
    servicos: list[dict[str, str]] = []

    equipe_ids = formulario.getlist("equipe_funcionario_id[]")
    equipe_horas = formulario.getlist("equipe_horas[]")
    equipe_observacoes = formulario.getlist("equipe_observacoes[]")

    for indice, funcionario_id in enumerate(equipe_ids):
        funcionario_id_texto = str(funcionario_id or "").strip()

        if not funcionario_id_texto:
            continue

        equipe.append(
            {
                "funcionario_id": funcionario_id_texto,
                "horas": str(equipe_horas[indice] if indice < len(equipe_horas) else "").strip(),
                "observacoes": str(equipe_observacoes[indice] if indice < len(equipe_observacoes) else "").strip(),
            }
        )

    material_ids = formulario.getlist("material_produto_id[]")
    material_quantidades = formulario.getlist("material_quantidade[]")
    material_observacoes = formulario.getlist("material_observacoes[]")

    for indice, produto_id in enumerate(material_ids):
        produto_id_texto = str(produto_id or "").strip()

        if not produto_id_texto:
            continue

        materiais.append(
            {
                "produto_id": produto_id_texto,
                "quantidade": str(material_quantidades[indice] if indice < len(material_quantidades) else "").strip(),
                "observacoes": str(material_observacoes[indice] if indice < len(material_observacoes) else "").strip(),
            }
        )

    servico_ids = formulario.getlist("servico_id[]")
    servico_quantidades = formulario.getlist("servico_quantidade[]")
    servico_observacoes = formulario.getlist("servico_observacoes[]")

    for indice, servico_id in enumerate(servico_ids):
        servico_id_texto = str(servico_id or "").strip()

        if not servico_id_texto:
            continue

        servicos.append(
            {
                "servico_id": servico_id_texto,
                "quantidade": str(servico_quantidades[indice] if indice < len(servico_quantidades) else "").strip(),
                "observacoes": str(servico_observacoes[indice] if indice < len(servico_observacoes) else "").strip(),
            }
        )

    return {
        "equipe": equipe,
        "materiais": materiais,
        "servicos": servicos,
    }


def salvar_itens_acompanhamento_os(
    conn: sqlite3.Connection,
    acompanhamento: dict[str, Any],
    itens: dict[str, list[dict[str, str]]],
) -> None:
    acompanhamento_id = int(acompanhamento.get("id") or 0)
    empresa_id = int(acompanhamento.get("empresa_id") or 0)

    if acompanhamento_id <= 0 or empresa_id <= 0:
        return

    conn.execute(
        "DELETE FROM os_acompanhamento_equipe WHERE acompanhamento_id = ? AND empresa_id = ?",
        (acompanhamento_id, empresa_id),
    )
    conn.execute(
        "DELETE FROM os_acompanhamento_materiais WHERE acompanhamento_id = ? AND empresa_id = ?",
        (acompanhamento_id, empresa_id),
    )
    conn.execute(
        "DELETE FROM os_acompanhamento_servicos WHERE acompanhamento_id = ? AND empresa_id = ?",
        (acompanhamento_id, empresa_id),
    )

    for item in itens.get("equipe", []):
        funcionario_id = _converter_inteiro_positivo(item.get("funcionario_id"))

        if funcionario_id is None:
            continue

        funcionario = conn.execute(
            """
            SELECT id, nome, cargo
            FROM funcionarios
            WHERE id = ?
              AND empresa_id = ?
            LIMIT 1
            """,
            (funcionario_id, empresa_id),
        ).fetchone()

        if funcionario is None:
            continue

        conn.execute(
            """
            INSERT INTO os_acompanhamento_equipe (
                empresa_id,
                acompanhamento_id,
                funcionario_id,
                nome,
                cargo,
                horas,
                observacoes
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                empresa_id,
                acompanhamento_id,
                funcionario_id,
                str(funcionario["nome"] or ""),
                str(funcionario["cargo"] or ""),
                str(item.get("horas") or ""),
                str(item.get("observacoes") or ""),
            ),
        )

    for item in itens.get("materiais", []):
        produto_id = _converter_inteiro_positivo(item.get("produto_id"))

        if produto_id is None:
            continue

        produto = conn.execute(
            """
            SELECT id, nome, unidade
            FROM produtos
            WHERE id = ?
              AND empresa_id = ?
            LIMIT 1
            """,
            (produto_id, empresa_id),
        ).fetchone()

        if produto is None:
            continue

        conn.execute(
            """
            INSERT INTO os_acompanhamento_materiais (
                empresa_id,
                acompanhamento_id,
                produto_id,
                nome,
                unidade,
                quantidade,
                observacoes
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                empresa_id,
                acompanhamento_id,
                produto_id,
                str(produto["nome"] or ""),
                str(produto["unidade"] or ""),
                str(item.get("quantidade") or ""),
                str(item.get("observacoes") or ""),
            ),
        )

    for item in itens.get("servicos", []):
        servico_id = _converter_inteiro_positivo(item.get("servico_id"))

        if servico_id is None:
            continue

        servico = conn.execute(
            """
            SELECT id, nome
            FROM servicos
            WHERE id = ?
              AND empresa_id = ?
            LIMIT 1
            """,
            (servico_id, empresa_id),
        ).fetchone()

        if servico is None:
            continue

        conn.execute(
            """
            INSERT INTO os_acompanhamento_servicos (
                empresa_id,
                acompanhamento_id,
                servico_id,
                nome,
                quantidade,
                observacoes
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                empresa_id,
                acompanhamento_id,
                servico_id,
                str(servico["nome"] or ""),
                str(item.get("quantidade") or ""),
                str(item.get("observacoes") or ""),
            ),
        )


def montar_url_acompanhamento_os(token: Any) -> str:
    token_normalizado = str(token or "").strip()

    if not token_normalizado:
        return ""

    base_url = request.url_root.rstrip("/") if request else ""

    return f"{base_url}/os/acompanhamento/{token_normalizado}"


def gerar_acompanhamento_diario_os(ordem_servico_id: int) -> tuple[bool, str, dict[str, Any] | None]:
    ordem_servico = buscar_ordem_servico_por_id(ordem_servico_id)

    if ordem_servico is None:
        return False, "OS não encontrada.", None

    status_os = str(ordem_servico.get("status") or "").strip().lower()

    if status_os != "andamento":
        return False, "O link de acompanhamento só pode ser gerado quando a OS estiver em andamento.", None

    empresa_id = empresa_logada_id()
    hoje = hoje_empresa().isoformat()
    agora = agora_empresa()
    expira_em = agora + timedelta(hours=24)

    with conectar_db() as conn:
        acompanhamento_existente = conn.execute(
            """
            SELECT
                id,
                empresa_id,
                ordem_servico_id,
                token,
                data_acompanhamento,
                responsavel,
                status_link,
                status_dia,
                atividades_previstas,
                equipe_prevista,
                materiais_previstos,
                atividades_executadas,
                equipe_real,
                materiais_utilizados,
                observacoes,
                aberto_em,
                finalizado_em,
                expira_em,
                criado_em,
                atualizado_em
            FROM os_acompanhamentos
            WHERE ordem_servico_id = ?
              AND empresa_id = ?
              AND data_acompanhamento = ?
              AND status_link = 'ativo'
              AND status_dia <> 'finalizado'
              AND datetime(expira_em) > datetime(?)
            ORDER BY id DESC
            LIMIT 1
            """,
            (ordem_servico_id, empresa_id, hoje, agora.isoformat(timespec="seconds")),
        ).fetchone()

        if acompanhamento_existente is not None:
            return True, "Já existe um link ativo para o acompanhamento de hoje.", dict(acompanhamento_existente)

        token = secrets.token_urlsafe(32)

        cursor = conn.execute(
            """
            INSERT INTO os_acompanhamentos (
                empresa_id,
                ordem_servico_id,
                token,
                data_acompanhamento,
                responsavel,
                status_link,
                status_dia,
                aberto_em,
                expira_em,
                atualizado_em
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                empresa_id,
                ordem_servico_id,
                token,
                hoje,
                str(ordem_servico.get("responsavel") or ordem_servico.get("tecnico") or ""),
                "ativo",
                "aberto",
                agora.isoformat(timespec="seconds"),
                expira_em.isoformat(timespec="seconds"),
                agora.isoformat(timespec="seconds"),
            ),
        )

        acompanhamento_id = int(cursor.lastrowid)
        conn.commit()

        row = conn.execute(
            """
            SELECT
                id,
                empresa_id,
                ordem_servico_id,
                token,
                data_acompanhamento,
                responsavel,
                status_link,
                status_dia,
                atividades_previstas,
                equipe_prevista,
                materiais_previstos,
                atividades_executadas,
                equipe_real,
                materiais_utilizados,
                observacoes,
                aberto_em,
                finalizado_em,
                expira_em,
                criado_em,
                atualizado_em
            FROM os_acompanhamentos
            WHERE id = ?
            LIMIT 1
            """,
            (acompanhamento_id,),
        ).fetchone()

    if row is None:
        return False, "Não foi possível recuperar o link gerado.", None

    return True, "Link de acompanhamento gerado com sucesso.", dict(row)


def buscar_acompanhamento_os_por_token(token: Any) -> dict[str, Any] | None:
    token_normalizado = str(token or "").strip()

    if not token_normalizado:
        return None

    with conectar_db() as conn:
        row = conn.execute(
            """
            SELECT
                os_acompanhamentos.id,
                os_acompanhamentos.empresa_id,
                os_acompanhamentos.ordem_servico_id,
                os_acompanhamentos.token,
                os_acompanhamentos.data_acompanhamento,
                os_acompanhamentos.responsavel,
                os_acompanhamentos.status_link,
                os_acompanhamentos.status_dia,
                os_acompanhamentos.atividades_previstas,
                os_acompanhamentos.equipe_prevista,
                os_acompanhamentos.materiais_previstos,
                os_acompanhamentos.atividades_executadas,
                os_acompanhamentos.equipe_real,
                os_acompanhamentos.materiais_utilizados,
                os_acompanhamentos.observacoes,
                os_acompanhamentos.aberto_em,
                os_acompanhamentos.finalizado_em,
                os_acompanhamentos.expira_em,
                os_acompanhamentos.criado_em,
                os_acompanhamentos.atualizado_em,
                ordens_servico.numero AS os_numero,
                ordens_servico.cliente AS os_cliente,
                ordens_servico.local_servico AS os_local_servico,
                ordens_servico.equipamento AS os_equipamento,
                ordens_servico.status AS os_status,
                ordens_servico.relato_cliente AS os_relato_cliente,
                ordens_servico.diagnostico AS os_diagnostico,
                ordens_servico.servico_executado AS os_servico_executado
            FROM os_acompanhamentos
            JOIN ordens_servico ON ordens_servico.id = os_acompanhamentos.ordem_servico_id
            WHERE os_acompanhamentos.token = ?
            LIMIT 1
            """,
            (token_normalizado,),
        ).fetchone()

    if row is None:
        return None

    return dict(row)


def acompanhamento_os_esta_expirado(acompanhamento: dict[str, Any]) -> bool:
    expira_em = str(acompanhamento.get("expira_em") or "").strip()

    if not expira_em:
        return True

    try:
        return datetime.fromisoformat(expira_em) < agora_empresa()
    except ValueError:
        return True


def atualizar_acompanhamento_os_publico(token: Any, dados: dict[str, str], finalizar: bool = False, itens: dict[str, list[dict[str, str]]] | None = None) -> bool:
    acompanhamento = buscar_acompanhamento_os_por_token(token)

    if acompanhamento is None:
        return False

    if acompanhamento_os_esta_expirado(acompanhamento):
        return False

    if str(acompanhamento.get("os_status") or "").strip().lower() != "andamento":
        return False

    if str(acompanhamento.get("status_dia") or "").strip().lower() == "finalizado":
        return False

    agora = agora_empresa().isoformat(timespec="seconds")
    status_dia = "finalizado" if finalizar else "aberto"
    finalizado_em = agora if finalizar else str(acompanhamento.get("finalizado_em") or "")

    with conectar_db() as conn:
        conn.execute(
            """
            UPDATE os_acompanhamentos
            SET
                responsavel = ?,
                status_dia = ?,
                atividades_previstas = ?,
                equipe_prevista = ?,
                materiais_previstos = ?,
                atividades_executadas = ?,
                equipe_real = ?,
                materiais_utilizados = ?,
                observacoes = ?,
                finalizado_em = ?,
                atualizado_em = ?
            WHERE token = ?
            """,
            (
                dados.get("responsavel", ""),
                status_dia,
                dados.get("atividades_previstas", ""),
                dados.get("equipe_prevista", ""),
                dados.get("materiais_previstos", ""),
                dados.get("atividades_executadas", ""),
                dados.get("equipe_real", ""),
                dados.get("materiais_utilizados", ""),
                dados.get("observacoes", ""),
                finalizado_em,
                agora,
                str(token or "").strip(),
            ),
        )

        if itens is not None:
            salvar_itens_acompanhamento_os(conn, acompanhamento, itens)

        conn.commit()

    return True


def _converter_data_iso(valor: Any) -> date | None:
    texto = str(valor or "").strip()

    if not texto:
        return None

    try:
        return datetime.strptime(texto, "%Y-%m-%d").date()
    except ValueError:
        return None


def _converter_valor_brl(valor: Any) -> float:
    texto = str(valor or "").strip()

    if not texto:
        return 0.0

    texto = texto.replace("R$", "").replace(" ", "")

    if "," in texto:
        texto = texto.replace(".", "").replace(",", ".")

    try:
        return float(texto)
    except ValueError:
        return 0.0


def _formatar_moeda_brl(valor: float) -> str:
    texto = f"{valor:,.2f}"
    return texto.replace(",", "X").replace(".", ",").replace("X", ".")


def _status_financeiro_calculado(titulo: dict[str, Any]) -> str:
    status = str(titulo.get("status") or "aberto").strip() or "aberto"

    if status != "aberto":
        return status

    vencimento = _converter_data_iso(titulo.get("data_vencimento"))

    if vencimento is not None and vencimento < hoje_empresa():
        return "vencido"

    return status


def _normalizar_status_financeiro(titulo: dict[str, Any]) -> dict[str, Any]:
    titulo_normalizado = dict(titulo)
    titulo_normalizado["status_exibicao"] = _status_financeiro_calculado(titulo_normalizado)
    titulo_normalizado["valor_numero"] = _converter_valor_brl(titulo_normalizado.get("valor"))
    return titulo_normalizado


def salvar_financeiro_titulo_db(titulo: dict[str, str]) -> int:
    empresa_id = empresa_logada_id()

    with conectar_db() as conn:
        cursor = conn.execute(
            """
            INSERT INTO financeiro_titulos (
                empresa_id,
                tipo,
                descricao,
                pessoa,
                categoria,
                origem,
                origem_id,
                documento,
                data_emissao,
                data_vencimento,
                data_pagamento,
                valor,
                forma_pagamento,
                status,
                observacoes
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                empresa_id,
                titulo["tipo"],
                titulo["descricao"],
                titulo["pessoa"],
                titulo["categoria"],
                titulo["origem"],
                titulo["origem_id"],
                titulo["documento"],
                titulo["data_emissao"],
                titulo["data_vencimento"],
                titulo["data_pagamento"],
                titulo["valor"],
                titulo["forma_pagamento"],
                titulo["status"],
                titulo["observacoes"],
            ),
        )
        titulo_id = int(cursor.lastrowid)
        conn.commit()

    return titulo_id

def listar_financeiro_titulos(tipo: str | None = None, limite: int | None = None) -> list[dict[str, Any]]:
    empresa_id = empresa_logada_id()
    consulta = """
        SELECT
            id,
            empresa_id,
            tipo,
            descricao,
            pessoa,
            categoria,
            origem,
            origem_id,
            documento,
            data_emissao,
            data_vencimento,
            data_pagamento,
            valor,
            forma_pagamento,
            status,
            observacoes,
            criado_em
        FROM financeiro_titulos
        WHERE empresa_id = ?
    """
    parametros: list[Any] = [empresa_id]

    if tipo:
        consulta += " AND tipo = ?"
        parametros.append(tipo)

    consulta += " ORDER BY data_vencimento ASC, id DESC"

    if limite is not None:
        consulta += " LIMIT ?"
        parametros.append(limite)

    with conectar_db() as conn:
        rows = conn.execute(consulta, parametros).fetchall()

    return [_normalizar_status_financeiro(dict(row)) for row in rows]

def buscar_financeiro_titulo_por_id(titulo_id: int) -> dict[str, Any] | None:
    empresa_id = empresa_logada_id()

    with conectar_db() as conn:
        row = conn.execute(
            """
            SELECT
                id,
                empresa_id,
                tipo,
                descricao,
                pessoa,
                categoria,
                origem,
                origem_id,
                documento,
                data_emissao,
                data_vencimento,
                data_pagamento,
                valor,
                forma_pagamento,
                status,
                observacoes,
                criado_em
            FROM financeiro_titulos
            WHERE id = ?
              AND empresa_id = ?
            """,
            (titulo_id, empresa_id),
        ).fetchone()

    if row is None:
        return None

    return _normalizar_status_financeiro(dict(row))

def atualizar_status_financeiro_titulo_db(titulo_id: int, status: str, data_pagamento: str = "") -> None:
    empresa_id = empresa_logada_id()

    with conectar_db() as conn:
        conn.execute(
            """
            UPDATE financeiro_titulos
            SET
                status = ?,
                data_pagamento = ?
            WHERE id = ?
              AND empresa_id = ?
            """,
            (status, data_pagamento, titulo_id, empresa_id),
        )
        conn.commit()

def cancelar_financeiro_titulo_db(titulo_id: int) -> None:
    atualizar_status_financeiro_titulo_db(titulo_id, "cancelado", "")


def baixar_financeiro_titulo_db(titulo_id: int) -> None:
    atualizar_status_financeiro_titulo_db(titulo_id, "pago", hoje_empresa().isoformat())


def montar_financeiro_titulo_formulario(tipo_padrao: str = "receber") -> dict[str, str]:
    tipo = (request.form.get("financeiro_tipo") or tipo_padrao).strip() or tipo_padrao

    if tipo not in {"receber", "pagar"}:
        tipo = tipo_padrao

    status = (request.form.get("financeiro_status") or "aberto").strip() or "aberto"

    if status not in {"aberto", "pago", "vencido", "cancelado"}:
        status = "aberto"

    data_pagamento = (request.form.get("financeiro_data_pagamento") or "").strip()

    if status == "pago" and not data_pagamento:
        data_pagamento = hoje_empresa().isoformat()

    return {
        "tipo": tipo,
        "descricao": (request.form.get("financeiro_descricao") or "").strip(),
        "pessoa": (request.form.get("financeiro_pessoa") or "").strip(),
        "categoria": (request.form.get("financeiro_categoria") or "Outros").strip() or "Outros",
        "origem": "manual",
        "origem_id": "",
        "documento": (request.form.get("financeiro_documento") or "").strip(),
        "data_emissao": (request.form.get("financeiro_data_emissao") or hoje_empresa().isoformat()).strip(),
        "data_vencimento": (request.form.get("financeiro_data_vencimento") or hoje_empresa().isoformat()).strip(),
        "data_pagamento": data_pagamento,
        "valor": (request.form.get("financeiro_valor") or "0,00").strip(),
        "forma_pagamento": (request.form.get("financeiro_forma_pagamento") or "").strip(),
        "status": status,
        "observacoes": (request.form.get("financeiro_observacoes") or "").strip(),
    }


def gerar_conta_receber_por_venda_db(venda_id: int, venda: dict[str, str]) -> None:
    status_venda = str(venda.get("status") or "").strip()

    if status_venda == "cancelada":
        return

    valor_total = _converter_valor_brl(venda.get("valor_total"))

    if valor_total <= 0:
        return

    numero_venda = str(venda.get("numero") or venda_id).strip() or str(venda_id)
    data_emissao = str(venda.get("data") or "").strip() or hoje_empresa().isoformat()
    prazo_entrega = str(venda.get("prazo_entrega") or "").strip()
    data_vencimento = prazo_entrega if _converter_data_iso(prazo_entrega) is not None else data_emissao

    titulo = {
        "tipo": "receber",
        "descricao": f"Recebimento de venda Nº {numero_venda}",
        "pessoa": str(venda.get("cliente") or "").strip(),
        "categoria": "Venda",
        "origem": "venda",
        "origem_id": str(venda_id),
        "documento": f"Venda Nº {numero_venda}",
        "data_emissao": data_emissao,
        "data_vencimento": data_vencimento,
        "data_pagamento": "",
        "valor": _formatar_moeda_brl(valor_total),
        "forma_pagamento": str(venda.get("forma_pagamento") or "").strip(),
        "status": "aberto",
        "observacoes": "Conta a receber gerada automaticamente ao salvar a venda.",
    }

    salvar_financeiro_titulo_db(titulo)


def _adicionar_meses(data_base: date, meses: int) -> date:
    mes_total = data_base.month - 1 + meses
    ano = data_base.year + mes_total // 12
    mes = mes_total % 12 + 1
    return date(ano, mes, 1)


def _nome_mes_curto(data_base: date) -> str:
    nomes = [
        "Jan",
        "Fev",
        "Mar",
        "Abr",
        "Mai",
        "Jun",
        "Jul",
        "Ago",
        "Set",
        "Out",
        "Nov",
        "Dez",
    ]
    return f"{nomes[data_base.month - 1]}/{str(data_base.year)[-2:]}"


def _periodo_ultimos_meses(quantidade: int = 6) -> list[date]:
    inicio_mes_atual = hoje_empresa().replace(day=1)
    return [_adicionar_meses(inicio_mes_atual, indice - quantidade + 1) for indice in range(quantidade)]


def _montar_calendario_financeiro(titulos: list[dict[str, Any]]) -> list[dict[str, Any]]:
    hoje = hoje_empresa()
    eventos: list[dict[str, Any]] = []

    for titulo in titulos:
        if titulo["status"] == "cancelado":
            continue

        vencimento = _converter_data_iso(titulo.get("data_vencimento"))

        if vencimento is None or vencimento.year != hoje.year or vencimento.month != hoje.month:
            continue

        eventos.append(
            {
                "dia": vencimento.day,
                "data": vencimento.isoformat(),
                "tipo": titulo["tipo"],
                "descricao": titulo["descricao"],
                "pessoa": titulo["pessoa"],
                "documento": titulo["documento"],
                "valor": titulo["valor_numero"],
                "valor_formatado": _formatar_moeda_brl(titulo["valor_numero"]),
                "status": titulo["status_exibicao"],
            }
        )

    eventos.sort(key=lambda item: (item["dia"], item["tipo"], item["descricao"] or ""))
    return eventos


def _montar_fluxo_caixa_mensal(titulos: list[dict[str, Any]]) -> list[dict[str, Any]]:
    meses = _periodo_ultimos_meses(6)
    fluxo = []

    for mes in meses:
        entradas = 0.0
        saidas = 0.0

        for titulo in titulos:
            pagamento = _converter_data_iso(titulo.get("data_pagamento"))

            if pagamento is None or pagamento.year != mes.year or pagamento.month != mes.month:
                continue

            if titulo["status"] != "pago":
                continue

            if titulo["tipo"] == "receber":
                entradas += titulo["valor_numero"]
            elif titulo["tipo"] == "pagar":
                saidas += titulo["valor_numero"]

        fluxo.append(
            {
                "mes": mes.isoformat(),
                "rotulo": _nome_mes_curto(mes),
                "entradas": entradas,
                "saidas": saidas,
                "saldo": entradas - saidas,
            }
        )

    return fluxo


def montar_painel_financeiro() -> dict[str, Any]:
    titulos = listar_financeiro_titulos()
    hoje = hoje_empresa()
    inicio_mes = hoje.replace(day=1)

    receber_aberto = [
        titulo
        for titulo in titulos
        if titulo["tipo"] == "receber" and titulo["status_exibicao"] in {"aberto", "vencido"}
    ]
    pagar_aberto = [
        titulo
        for titulo in titulos
        if titulo["tipo"] == "pagar" and titulo["status_exibicao"] in {"aberto", "vencido"}
    ]
    receber_hoje = [
        titulo
        for titulo in receber_aberto
        if _converter_data_iso(titulo.get("data_vencimento")) == hoje
    ]
    pagar_hoje = [
        titulo
        for titulo in pagar_aberto
        if _converter_data_iso(titulo.get("data_vencimento")) == hoje
    ]
    receber_vencido = [
        titulo
        for titulo in receber_aberto
        if titulo["status_exibicao"] == "vencido"
    ]
    pagar_vencido = [
        titulo
        for titulo in pagar_aberto
        if titulo["status_exibicao"] == "vencido"
    ]

    recebido_mes = []
    pago_mes = []

    for titulo in titulos:
        data_pagamento = _converter_data_iso(titulo.get("data_pagamento"))

        if data_pagamento is None or data_pagamento < inicio_mes or data_pagamento > hoje:
            continue

        if titulo["tipo"] == "receber" and titulo["status"] == "pago":
            recebido_mes.append(titulo)
        elif titulo["tipo"] == "pagar" and titulo["status"] == "pago":
            pago_mes.append(titulo)

    total_receber_aberto = sum(titulo["valor_numero"] for titulo in receber_aberto)
    total_pagar_aberto = sum(titulo["valor_numero"] for titulo in pagar_aberto)
    total_receber_hoje = sum(titulo["valor_numero"] for titulo in receber_hoje)
    total_pagar_hoje = sum(titulo["valor_numero"] for titulo in pagar_hoje)
    total_receber_vencido = sum(titulo["valor_numero"] for titulo in receber_vencido)
    total_pagar_vencido = sum(titulo["valor_numero"] for titulo in pagar_vencido)
    total_recebido_mes = sum(titulo["valor_numero"] for titulo in recebido_mes)
    total_pago_mes = sum(titulo["valor_numero"] for titulo in pago_mes)

    return {
        "a_receber_aberto": total_receber_aberto,
        "a_pagar_aberto": total_pagar_aberto,
        "receber_hoje": total_receber_hoje,
        "pagar_hoje": total_pagar_hoje,
        "receber_vencido": total_receber_vencido,
        "pagar_vencido": total_pagar_vencido,
        "recebido_mes": total_recebido_mes,
        "pago_mes": total_pago_mes,
        "saldo_previsto": total_receber_aberto - total_pagar_aberto,
        "saldo_mes": total_recebido_mes - total_pago_mes,
        "quantidade_receber_aberto": len(receber_aberto),
        "quantidade_pagar_aberto": len(pagar_aberto),
        "quantidade_receber_hoje": len(receber_hoje),
        "quantidade_pagar_hoje": len(pagar_hoje),
        "quantidade_receber_vencido": len(receber_vencido),
        "quantidade_pagar_vencido": len(pagar_vencido),
        "recebimentos": [titulo for titulo in titulos if titulo["tipo"] == "receber"],
        "pagamentos": [titulo for titulo in titulos if titulo["tipo"] == "pagar"],
        "recebimentos_abertos": receber_aberto,
        "pagamentos_abertos": pagar_aberto,
        "recebimentos_hoje": receber_hoje,
        "pagamentos_hoje": pagar_hoje,
        "recebimentos_vencidos": receber_vencido,
        "pagamentos_vencidos": pagar_vencido,
        "recebidos_mes": recebido_mes,
        "pagos_mes": pago_mes,
        "fluxo_mensal": _montar_fluxo_caixa_mensal(titulos),
        "calendario": _montar_calendario_financeiro(titulos),
        "ultimos_titulos": titulos[:10],
    }


def montar_painel_ordens_servico() -> dict[str, Any]:
    ordens = listar_ordens_servico()
    hoje = hoje_empresa()

    prazo = {
        "vencidas": 0,
        "hoje": 0,
        "amanha": 0,
        "futuras": 0,
        "sem_prazo": 0,
    }

    prioridade = {
        "baixa": 0,
        "media": 0,
        "alta": 0,
        "urgente": 0,
        "muito_urgente": 0,
        "normal": 0,
    }

    status = {
        "aberta": 0,
        "andamento": 0,
        "aguardando": 0,
        "finalizada": 0,
        "cancelada": 0,
    }

    faturamento = {
        "abertas": 0.0,
        "andamento": 0.0,
        "finalizadas": 0.0,
        "geral": 0.0,
    }

    por_tecnico: dict[str, dict[str, Any]] = {}
    proximas_ordens: list[dict[str, Any]] = []

    for ordem in ordens:
        data_previsao = _converter_data_iso(ordem.get("data_previsao"))
        status_os = str(ordem.get("status") or "aberta").strip() or "aberta"
        prioridade_os = str(ordem.get("prioridade") or "normal").strip() or "normal"
        tecnico = str(ordem.get("tecnico") or "Sem técnico").strip() or "Sem técnico"
        valor = _converter_valor_brl(ordem.get("valor_total"))

        if data_previsao is None:
            prazo["sem_prazo"] += 1
        elif data_previsao < hoje and status_os not in {"finalizada", "cancelada"}:
            prazo["vencidas"] += 1
        elif data_previsao == hoje:
            prazo["hoje"] += 1
        elif (data_previsao - hoje).days == 1:
            prazo["amanha"] += 1
        elif data_previsao > hoje:
            prazo["futuras"] += 1

        if prioridade_os in prioridade:
            prioridade[prioridade_os] += 1
        else:
            prioridade["normal"] += 1

        if status_os in status:
            status[status_os] += 1
        else:
            status["aberta"] += 1

        faturamento["geral"] += valor

        if status_os == "finalizada":
            faturamento["finalizadas"] += valor
        elif status_os == "andamento":
            faturamento["andamento"] += valor
        elif status_os != "cancelada":
            faturamento["abertas"] += valor

        if tecnico not in por_tecnico:
            por_tecnico[tecnico] = {
                "tecnico": tecnico,
                "quantidade": 0,
                "valor_total": 0.0,
                "abertas": 0,
                "finalizadas": 0,
            }

        por_tecnico[tecnico]["quantidade"] += 1
        por_tecnico[tecnico]["valor_total"] += valor

        if status_os == "finalizada":
            por_tecnico[tecnico]["finalizadas"] += 1
        elif status_os != "cancelada":
            por_tecnico[tecnico]["abertas"] += 1

        ordem_com_data = dict(ordem)
        ordem_com_data["_data_previsao_obj"] = data_previsao
        proximas_ordens.append(ordem_com_data)

    proximas_ordens.sort(
        key=lambda item: (
            item["_data_previsao_obj"] is None,
            item["_data_previsao_obj"] or date.max,
            item.get("id") or 0,
        )
    )

    painel_tecnicos = sorted(
        por_tecnico.values(),
        key=lambda item: item["valor_total"],
        reverse=True,
    )

    return {
        "ordens": ordens,
        "prazo": prazo,
        "prioridade": prioridade,
        "status": status,
        "faturamento": faturamento,
        "por_tecnico": painel_tecnicos,
        "proximas_ordens": proximas_ordens[:10],
    }


def excluir_ordem_servico_db(ordem_servico_id: int) -> None:
    empresa_id = empresa_logada_id()

    with conectar_db() as conn:
        conn.execute(
            """
            DELETE FROM ordem_servico_itens
            WHERE ordem_servico_id = ?
              AND empresa_id = ?
            """,
            (ordem_servico_id, empresa_id),
        )
        conn.execute(
            """
            DELETE FROM ordens_servico
            WHERE id = ?
              AND empresa_id = ?
            """,
            (ordem_servico_id, empresa_id),
        )
        conn.commit()

def _combinar_valores_formulario(campo: str) -> str:
    valores = [valor.strip() for valor in request.form.getlist(campo) if valor.strip()]

    if not valores:
        return ""

    if len(valores) == 1:
        return valores[0]

    return " | ".join(f"{indice + 1}) {valor}" for indice, valor in enumerate(valores))


def _separar_valores_formulario_combinado(valor: Any) -> list[str]:
    texto = str(valor or "").strip()

    if not texto:
        return []

    partes_numeradas = re.findall(r"(?:^|\s\|\s)\d+\)\s*(.*?)(?=\s\|\s\d+\)\s*|$)", texto)

    if partes_numeradas:
        return [parte.strip() for parte in partes_numeradas]

    if " | " in texto:
        return [parte.strip() for parte in texto.split(" | ")]

    return [texto]


def montar_equipamentos_ordem_servico(ordem_servico: dict[str, Any] | None) -> list[dict[str, str]]:
    if not ordem_servico:
        return [
            {
                "indice": "0",
                "titulo": "Equipamento principal",
                "equipamento": "",
                "marca": "",
                "modelo": "",
                "serie": "",
                "local_servico": "",
                "condicoes": "",
                "acessorios": "",
                "relato_cliente": "",
                "diagnostico": "",
                "laudo": "",
                "termos": "",
            }
        ]

    campos = {
        "equipamento": _separar_valores_formulario_combinado(ordem_servico.get("equipamento")),
        "marca": _separar_valores_formulario_combinado(ordem_servico.get("marca")),
        "modelo": _separar_valores_formulario_combinado(ordem_servico.get("modelo")),
        "serie": _separar_valores_formulario_combinado(ordem_servico.get("serie")),
        "local_servico": _separar_valores_formulario_combinado(ordem_servico.get("local_servico")),
        "condicoes": _separar_valores_formulario_combinado(ordem_servico.get("condicoes")),
        "acessorios": _separar_valores_formulario_combinado(ordem_servico.get("acessorios")),
        "relato_cliente": _separar_valores_formulario_combinado(ordem_servico.get("relato_cliente")),
        "diagnostico": _separar_valores_formulario_combinado(ordem_servico.get("diagnostico")),
        "laudo": _separar_valores_formulario_combinado(ordem_servico.get("laudo")),
        "termos": _separar_valores_formulario_combinado(ordem_servico.get("termos")),
    }

    total = max((len(valores) for valores in campos.values()), default=0)

    if total <= 0:
        total = 1

    equipamentos = []

    for indice in range(total):
        equipamento = {
            "indice": str(indice),
            "titulo": "Equipamento principal" if indice == 0 else f"Equipamento adicional {indice + 1}",
        }

        for campo, valores in campos.items():
            equipamento[campo] = valores[indice] if indice < len(valores) else ""

        equipamentos.append(equipamento)

    return equipamentos


def agrupar_fotos_por_equipamento(fotos_equipamento: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    fotos_por_equipamento: dict[str, list[dict[str, Any]]] = {}

    for foto in fotos_equipamento:
        indice = str(foto.get("equipamento_indice") or "0").strip() or "0"
        fotos_por_equipamento.setdefault(indice, []).append(foto)

    return fotos_por_equipamento


def montar_ordem_servico_formulario(numero_padrao: str = "") -> dict[str, str]:
    return {
        "numero": (request.form.get("os_numero") or numero_padrao).strip(),
        "cliente": (request.form.get("os_cliente") or "").strip(),
        "responsavel": (request.form.get("os_responsavel") or "").strip(),
        "tecnico": (request.form.get("os_tecnico") or "").strip(),
        "data_abertura": (request.form.get("os_data_abertura") or "").strip(),
        "data_previsao": (request.form.get("os_data_previsao") or "").strip(),
        "data_saida": (request.form.get("os_data_saida") or "").strip(),
        "hora_entrada": (request.form.get("os_hora_entrada") or "").strip(),
        "hora_saida": (request.form.get("os_hora_saida") or "").strip(),
        "canal_venda": (request.form.get("os_canal_venda") or "").strip(),
        "centro_custo": (request.form.get("os_centro_custo") or "").strip(),
        "equipamento": _combinar_valores_formulario("os_equipamento"),
        "marca": _combinar_valores_formulario("os_marca"),
        "modelo": _combinar_valores_formulario("os_modelo"),
        "serie": _combinar_valores_formulario("os_serie"),
        "local_servico": _combinar_valores_formulario("os_local_servico"),
        "condicoes": _combinar_valores_formulario("os_condicoes"),
        "acessorios": _combinar_valores_formulario("os_acessorios"),
        "laudo": _combinar_valores_formulario("os_laudo"),
        "termos": _combinar_valores_formulario("os_termos"),
        "informar_endereco_entrega": "sim" if request.form.get("os_informar_endereco_entrega") else "nao",
        "endereco_entrega": (request.form.get("os_endereco_entrega") or "").strip(),
        "bairro_entrega": (request.form.get("os_bairro_entrega") or "").strip(),
        "cidade_entrega": (request.form.get("os_cidade_entrega") or "").strip(),
        "origem_venda_id": (request.form.get("os_origem_venda_id") or "").strip(),
        "tipo": (request.form.get("os_tipo") or "misto").strip() or "misto",
        "status": (request.form.get("os_status") or "aberta").strip() or "aberta",
        "prioridade": (request.form.get("os_prioridade") or "normal").strip() or "normal",
        "total_produtos": (request.form.get("os_total_produtos") or "0,00").strip(),
        "total_servicos": (request.form.get("os_total_servicos") or "0,00").strip(),
        "frete": (request.form.get("os_frete") or "0,00").strip(),
        "outros": (request.form.get("os_outros") or "0,00").strip(),
        "desconto_valor": (request.form.get("os_desconto_valor") or "0,00").strip(),
        "valor_total": (request.form.get("os_valor_total") or "0,00").strip(),
        "forma_pagamento": (request.form.get("os_forma_pagamento") or "").strip(),
        "exibir_valor_impressao": "sim" if request.form.get("os_exibir_valor_impressao") else "nao",
        "relato_cliente": _combinar_valores_formulario("os_relato_cliente"),
        "diagnostico": _combinar_valores_formulario("os_diagnostico"),
        "servico_executado": (request.form.get("os_servico_executado") or "").strip(),
        "observacoes": (request.form.get("os_observacoes") or "").strip(),
        "observacoes_internas": (request.form.get("os_observacoes_internas") or "").strip(),
    }


def montar_ordem_servico_itens_formulario() -> list[dict[str, str]]:
    tipos = request.form.getlist("item_tipo")
    descricoes = request.form.getlist("item_descricao")
    detalhes = request.form.getlist("item_detalhes")
    quantidades = request.form.getlist("item_quantidade")
    valores_unitarios = request.form.getlist("item_valor_unitario")
    descontos = request.form.getlist("item_desconto")
    subtotais = request.form.getlist("item_subtotal")

    total_itens = max(
        len(tipos),
        len(descricoes),
        len(detalhes),
        len(quantidades),
        len(valores_unitarios),
        len(descontos),
        len(subtotais),
        0,
    )

    itens: list[dict[str, str]] = []

    for index in range(total_itens):
        itens.append(
            {
                "tipo_item": (tipos[index] if index < len(tipos) else "produto").strip() or "produto",
                "descricao": (descricoes[index] if index < len(descricoes) else "").strip(),
                "detalhes": (detalhes[index] if index < len(detalhes) else "").strip(),
                "quantidade": (quantidades[index] if index < len(quantidades) else "").strip(),
                "valor_unitario": (valores_unitarios[index] if index < len(valores_unitarios) else "").strip(),
                "desconto": (descontos[index] if index < len(descontos) else "").strip(),
                "subtotal": (subtotais[index] if index < len(subtotais) else "").strip(),
            }
        )

    return itens


def gerar_ordem_servico_por_venda_db(venda_id: int) -> int | None:
    venda = buscar_venda_por_id(venda_id)

    if venda is None:
        return None

    itens_venda = listar_venda_itens(venda_id)

    ordem_servico = {
        "numero": proximo_numero_ordem_servico(),
        "cliente": str(venda.get("cliente") or ""),
        "responsavel": str(venda.get("responsavel") or ""),
        "tecnico": "",
        "data_abertura": str(venda.get("data") or ""),
        "data_previsao": str(venda.get("prazo_entrega") or ""),
        "data_saida": "",
        "hora_entrada": "",
        "hora_saida": "",
        "canal_venda": str(venda.get("canal_venda") or ""),
        "centro_custo": str(venda.get("centro_custo") or ""),
        "equipamento": "",
        "marca": "",
        "modelo": "",
        "serie": "",
        "local_servico": "",
        "condicoes": "",
        "acessorios": "",
        "laudo": "",
        "termos": "",
        "informar_endereco_entrega": "nao",
        "endereco_entrega": "",
        "bairro_entrega": "",
        "cidade_entrega": "",
        "origem_venda_id": str(venda_id),
        "tipo": str(venda.get("tipo") or "misto"),
        "status": "aberta",
        "prioridade": "normal",
        "total_produtos": str(venda.get("total_produtos") or "0,00"),
        "total_servicos": str(venda.get("total_servicos") or "0,00"),
        "frete": "0,00",
        "outros": "0,00",
        "desconto_valor": str(venda.get("desconto_valor") or "0,00"),
        "valor_total": str(venda.get("valor_total") or "0,00"),
        "forma_pagamento": str(venda.get("forma_pagamento") or ""),
        "exibir_valor_impressao": "sim",
        "relato_cliente": str(venda.get("observacoes") or ""),
        "diagnostico": "",
        "servico_executado": "",
        "observacoes": "Gerada a partir da venda " + str(venda.get("numero") or venda_id),
        "observacoes_internas": str(venda.get("observacoes_internas") or ""),
    }

    itens_os: list[dict[str, str]] = []

    for item in itens_venda:
        itens_os.append(
            {
                "tipo_item": str(item.get("tipo_item") or "produto"),
                "descricao": str(item.get("descricao") or ""),
                "detalhes": str(item.get("detalhes") or ""),
                "quantidade": str(item.get("quantidade") or ""),
                "valor_unitario": str(item.get("valor_unitario") or ""),
                "desconto": str(item.get("desconto") or ""),
                "subtotal": str(item.get("subtotal") or ""),
            }
        )

    return salvar_ordem_servico_db(ordem_servico, itens_os)


def copiar_ordem_servico_db(ordem_servico_id: int) -> int | None:
    ordem_servico_original = buscar_ordem_servico_por_id(ordem_servico_id)

    if ordem_servico_original is None:
        return None

    itens_originais = listar_ordem_servico_itens(ordem_servico_id)
    nova_ordem_servico = {
        "numero": proximo_numero_ordem_servico(),
        "cliente": str(ordem_servico_original.get("cliente") or ""),
        "responsavel": str(ordem_servico_original.get("responsavel") or ""),
        "tecnico": str(ordem_servico_original.get("tecnico") or ""),
        "data_abertura": str(ordem_servico_original.get("data_abertura") or ""),
        "data_previsao": str(ordem_servico_original.get("data_previsao") or ""),
        "data_saida": str(ordem_servico_original.get("data_saida") or ""),
        "hora_entrada": str(ordem_servico_original.get("hora_entrada") or ""),
        "hora_saida": str(ordem_servico_original.get("hora_saida") or ""),
        "canal_venda": str(ordem_servico_original.get("canal_venda") or ""),
        "centro_custo": str(ordem_servico_original.get("centro_custo") or ""),
        "equipamento": str(ordem_servico_original.get("equipamento") or ""),
        "marca": str(ordem_servico_original.get("marca") or ""),
        "modelo": str(ordem_servico_original.get("modelo") or ""),
        "serie": str(ordem_servico_original.get("serie") or ""),
        "local_servico": str(ordem_servico_original.get("local_servico") or ""),
        "condicoes": str(ordem_servico_original.get("condicoes") or ""),
        "acessorios": str(ordem_servico_original.get("acessorios") or ""),
        "laudo": str(ordem_servico_original.get("laudo") or ""),
        "termos": str(ordem_servico_original.get("termos") or ""),
        "informar_endereco_entrega": str(ordem_servico_original.get("informar_endereco_entrega") or "nao"),
        "endereco_entrega": str(ordem_servico_original.get("endereco_entrega") or ""),
        "bairro_entrega": str(ordem_servico_original.get("bairro_entrega") or ""),
        "cidade_entrega": str(ordem_servico_original.get("cidade_entrega") or ""),
        "origem_venda_id": str(ordem_servico_original.get("origem_venda_id") or ""),
        "tipo": str(ordem_servico_original.get("tipo") or "misto"),
        "status": "aberta",
        "prioridade": str(ordem_servico_original.get("prioridade") or "normal"),
        "total_produtos": str(ordem_servico_original.get("total_produtos") or "0,00"),
        "total_servicos": str(ordem_servico_original.get("total_servicos") or "0,00"),
        "frete": str(ordem_servico_original.get("frete") or "0,00"),
        "outros": str(ordem_servico_original.get("outros") or "0,00"),
        "desconto_valor": str(ordem_servico_original.get("desconto_valor") or "0,00"),
        "valor_total": str(ordem_servico_original.get("valor_total") or "0,00"),
        "forma_pagamento": str(ordem_servico_original.get("forma_pagamento") or ""),
        "exibir_valor_impressao": str(ordem_servico_original.get("exibir_valor_impressao") or "sim"),
        "relato_cliente": str(ordem_servico_original.get("relato_cliente") or ""),
        "diagnostico": str(ordem_servico_original.get("diagnostico") or ""),
        "servico_executado": str(ordem_servico_original.get("servico_executado") or ""),
        "observacoes": str(ordem_servico_original.get("observacoes") or "") + "\nCópia gerada a partir da OS " + str(ordem_servico_original.get("numero") or ordem_servico_id),
        "observacoes_internas": str(ordem_servico_original.get("observacoes_internas") or ""),
    }

    novos_itens: list[dict[str, str]] = []

    for item in itens_originais:
        novos_itens.append(
            {
                "tipo_item": str(item.get("tipo_item") or "produto"),
                "descricao": str(item.get("descricao") or ""),
                "detalhes": str(item.get("detalhes") or ""),
                "quantidade": str(item.get("quantidade") or ""),
                "valor_unitario": str(item.get("valor_unitario") or ""),
                "desconto": str(item.get("desconto") or ""),
                "subtotal": str(item.get("subtotal") or ""),
            }
        )

    return salvar_ordem_servico_db(nova_ordem_servico, novos_itens)


def montar_dashboard() -> dict[str, Any]:
    vendas_lista = listar_vendas()
    ordens_lista = listar_ordens_servico()
    orcamentos_lista = listar_orcamentos()
    clientes_lista = listar_clientes()
    produtos_lista = listar_produtos()
    financeiro = montar_painel_financeiro()

    hoje = hoje_empresa()
    meses_grafico = _periodo_ultimos_meses(6)

    vendas_mes = []
    vendas_por_mes: list[dict[str, Any]] = []

    for mes in meses_grafico:
        vendas_por_mes.append(
            {
                "mes": mes.isoformat(),
                "rotulo": _nome_mes_curto(mes),
                "quantidade": 0,
                "valor_total": 0.0,
            }
        )

    for venda in vendas_lista:
        data_venda = _converter_data_iso(venda.get("data"))
        valor = _converter_valor_brl(venda.get("valor_total"))

        if data_venda is not None and data_venda.year == hoje.year and data_venda.month == hoje.month:
            vendas_mes.append({"venda": venda, "valor": valor})

        if data_venda is None:
            continue

        for item_mes in vendas_por_mes:
            mes_referencia = _converter_data_iso(item_mes["mes"])

            if mes_referencia is None:
                continue

            if data_venda.year == mes_referencia.year and data_venda.month == mes_referencia.month:
                item_mes["quantidade"] += 1
                item_mes["valor_total"] += valor
                break

    total_vendas_mes = sum(item["valor"] for item in vendas_mes)
    total_vendas_6_meses = sum(item["valor_total"] for item in vendas_por_mes)
    media_vendas_6_meses = total_vendas_6_meses / 6 if total_vendas_6_meses else 0.0

    orcamentos_abertos = [orcamento for orcamento in orcamentos_lista if str(orcamento.get("status") or "").strip() == "aberto"]
    total_orcamentos_abertos = sum(_converter_valor_brl(orcamento.get("valor_total")) for orcamento in orcamentos_abertos)

    os_abertas = [
        ordem
        for ordem in ordens_lista
        if str(ordem.get("status") or "").strip() in {"aberta", "andamento", "aguardando"}
    ]
    total_os_abertas = sum(_converter_valor_brl(ordem.get("valor_total")) for ordem in os_abertas)

    clientes_ativos = [cliente for cliente in clientes_lista if str(cliente.get("status") or "ativo").strip() == "ativo"]

    produtos_estoque = []
    produtos_estoque_baixo = []

    for produto in produtos_lista:
        estoque_atual = _converter_valor_brl(produto.get("estoque_atual"))
        estoque_minimo = _converter_valor_brl(produto.get("estoque_minimo"))

        if estoque_atual > 0:
            produtos_estoque.append(produto)

        if estoque_minimo > 0 and estoque_atual <= estoque_minimo:
            produtos_estoque_baixo.append(produto)

    ultimas_os = ordens_lista[:5]
    ultimas_vendas = vendas_lista[:5]

    return {
        "data_hoje": hoje.isoformat(),
        "vendas_mes": {
            "quantidade": len(vendas_mes),
            "valor_total": total_vendas_mes,
        },
        "vendas_6_meses": {
            "valor_total": total_vendas_6_meses,
            "media_mensal": media_vendas_6_meses,
            "meses": vendas_por_mes,
            "rotulos": [item["rotulo"] for item in vendas_por_mes],
            "valores": [item["valor_total"] for item in vendas_por_mes],
            "quantidades": [item["quantidade"] for item in vendas_por_mes],
        },
        "fluxo_6_meses": {
            "meses": financeiro["fluxo_mensal"],
            "rotulos": [item["rotulo"] for item in financeiro["fluxo_mensal"]],
            "entradas": [item["entradas"] for item in financeiro["fluxo_mensal"]],
            "saidas": [item["saidas"] for item in financeiro["fluxo_mensal"]],
            "saldos": [item["saldo"] for item in financeiro["fluxo_mensal"]],
        },
        "calendario": {
            "eventos": financeiro["calendario"],
        },
        "orcamentos_abertos": {
            "quantidade": len(orcamentos_abertos),
            "valor_total": total_orcamentos_abertos,
        },
        "ordens_abertas": {
            "quantidade": len(os_abertas),
            "valor_total": total_os_abertas,
        },
        "produtos": {
            "em_estoque": len(produtos_estoque),
            "estoque_baixo": len(produtos_estoque_baixo),
        },
        "clientes": {
            "ativos": len(clientes_ativos),
            "total": len(clientes_lista),
        },
        "ultimas_os": ultimas_os,
        "ultimas_vendas": ultimas_vendas,
        "financeiro": financeiro,
    }



def buscar_empresa_configuracoes() -> dict[str, Any]:
    with conectar_db() as conn:
        row = conn.execute(
            """
            SELECT
                id,
                nome_fantasia,
                razao_social,
                documento,
                email,
                telefone,
                plano,
                status,
                criado_em,
                logo_path,
                trial_inicio,
                trial_fim,
                codigo_indicacao,
                indicado_por_empresa_id,
                indicador_codigo,
                pix_indicador,
                timezone,
                onboarding_concluido,
                onboarding_ramo,
                onboarding_objetivos,
                onboarding_ferramenta_atual,
                onboarding_canal_contato,
                tour_concluido
            FROM empresas
            WHERE id = ?
            LIMIT 1
            """,
            (empresa_logada_id(),),
        ).fetchone()

    if row is None:
        return {
            "id": empresa_logada_id(),
            "nome_fantasia": "GestFlow Demo",
            "razao_social": "GestFlow Demo",
            "documento": "",
            "email": "",
            "telefone": "",
            "logo_path": "",
            "trial_inicio": "",
            "trial_fim": "",
            "codigo_indicacao": "",
            "indicado_por_empresa_id": "",
            "indicador_codigo": "",
            "pix_indicador": "",
            "timezone": TIMEZONE_PADRAO_GESTFLOW,
            "onboarding_concluido": "nao",
            "onboarding_ramo": "",
            "onboarding_objetivos": "",
            "onboarding_ferramenta_atual": "",
            "onboarding_canal_contato": "",
            "tour_concluido": "nao",
            "plano": "Start",
            "status": "ativo",
            "criado_em": "",
        }

    empresa = dict(row)
    empresa["timezone"] = normalizar_timezone_empresa(empresa.get("timezone"))
    return empresa


def listar_usuarios_configuracoes() -> list[dict[str, Any]]:
    with conectar_db() as conn:
        rows = conn.execute(
            """
            SELECT
                id,
                empresa_id,
                nome,
                email,
                perfil,
                status,
                ultimo_login,
                criado_em
            FROM usuarios
            WHERE empresa_id = ?
            ORDER BY id ASC
            """,
            (empresa_logada_id(),),
        ).fetchall()

    return [dict(row) for row in rows]


def listar_lojas_configuracoes() -> list[dict[str, Any]]:
    with conectar_db() as conn:
        rows = conn.execute(
            """
            SELECT
                id,
                empresa_id,
                nome,
                tipo,
                cidade,
                status,
                criado_em
            FROM lojas
            WHERE empresa_id = ?
            ORDER BY id ASC
            """,
            (empresa_logada_id(),),
        ).fetchall()

    return [dict(row) for row in rows]


def montar_configuracoes_contexto() -> dict[str, Any]:
    empresa = buscar_empresa_configuracoes()
    empresa_id = int(empresa.get("id") or empresa_logada_id())
    empresa["codigo_indicacao"] = garantir_codigo_indicacao_empresa(empresa_id)
    empresa["link_indicacao"] = montar_link_indicacao(empresa["codigo_indicacao"])

    return {
        "empresa": empresa,
        "usuarios": listar_usuarios_configuracoes(),
        "lojas": listar_lojas_configuracoes(),
        "fusos_horarios": FUSOS_HORARIOS_GESTFLOW,
    }



def buscar_usuario_configuracoes_por_id(usuario_id: int) -> dict[str, Any] | None:
    empresa_id = empresa_logada_id()

    with conectar_db() as conn:
        row = conn.execute(
            """
            SELECT
                id,
                empresa_id,
                nome,
                email,
                perfil,
                status
            FROM usuarios
            WHERE id = ?
              AND empresa_id = ?
            LIMIT 1
            """,
            (usuario_id, empresa_id),
        ).fetchone()

    if row is None:
        return None

    return dict(row)


def redefinir_senha_usuario_configuracoes_db(usuario_id: int, nova_senha: str) -> None:
    empresa_id = empresa_logada_id()
    senha_hash = generate_password_hash(str(nova_senha or ""))

    with conectar_db() as conn:
        conn.execute(
            """
            UPDATE usuarios
            SET senha_hash = ?
            WHERE id = ?
              AND empresa_id = ?
            """,
            (senha_hash, usuario_id, empresa_id),
        )
        conn.commit()


def atualizar_empresa_configuracoes_db(dados: dict[str, str]) -> None:
    empresa_id = empresa_logada_id()

    with conectar_db() as conn:
        conn.execute(
            """
            UPDATE empresas
            SET
                nome_fantasia = ?,
                razao_social = ?,
                documento = ?,
                email = ?,
                telefone = ?
            WHERE id = ?
            """,
            (
                dados["nome_fantasia"],
                dados["razao_social"],
                dados["documento"],
                dados["email"],
                dados["telefone"],
                empresa_id,
            ),
        )
        conn.commit()


def atualizar_timezone_empresa_configuracoes_db(timezone: str) -> None:
    empresa_id = empresa_logada_id()
    timezone_normalizado = normalizar_timezone_empresa(timezone)

    with conectar_db() as conn:
        conn.execute(
            """
            UPDATE empresas
            SET timezone = ?
            WHERE id = ?
            """,
            (timezone_normalizado, empresa_id),
        )
        conn.commit()


def salvar_logo_empresa_db(logo_path: str) -> None:
    empresa_id = empresa_logada_id()

    with conectar_db() as conn:
        conn.execute(
            """
            UPDATE empresas
            SET logo_path = ?
            WHERE id = ?
            """,
            (logo_path, empresa_id),
        )
        conn.commit()


def _extensao_logo_permitida(nome_arquivo: str) -> bool:
    if "." not in nome_arquivo:
        return False

    extensao = nome_arquivo.rsplit(".", 1)[1].lower()
    return extensao in EXTENSOES_LOGO_PERMITIDAS


def salvar_upload_logo_empresa(arquivo) -> str:
    nome_seguro = secure_filename(arquivo.filename or "")

    if not nome_seguro or not _extensao_logo_permitida(nome_seguro):
        raise ValueError("Formato de logo inválido. Use PNG, JPG, JPEG, WEBP ou GIF.")

    extensao = nome_seguro.rsplit(".", 1)[1].lower()
    empresa_id = empresa_logada_id()
    timestamp = agora_empresa().strftime("%Y%m%d%H%M%S")
    nome_final = f"empresa_{empresa_id}_{timestamp}.{extensao}"
    destino = UPLOAD_DIR / nome_final

    arquivo.save(destino)

    return f"/uploads/logos/{nome_final}"



def _extensao_foto_os_permitida(nome_arquivo: str) -> bool:
    if "." not in nome_arquivo:
        return False

    extensao = nome_arquivo.rsplit(".", 1)[1].lower()
    return extensao in EXTENSOES_FOTO_OS_PERMITIDAS


def salvar_upload_foto_os(arquivo, ordem_servico_id: int, tipo_foto: str) -> str:
    nome_seguro = secure_filename(arquivo.filename or "")

    if not nome_seguro:
        return ""

    if not _extensao_foto_os_permitida(nome_seguro):
        raise ValueError("Formato de foto inválido. Use PNG, JPG, JPEG ou WEBP.")

    extensao = nome_seguro.rsplit(".", 1)[1].lower()
    empresa_id = empresa_logada_id()
    timestamp = agora_empresa().strftime("%Y%m%d%H%M%S%f")
    tipo_limpo = "".join(caractere for caractere in str(tipo_foto or "foto") if caractere.isalnum())[:16] or "foto"
    nome_final = f"os_{empresa_id}_{int(ordem_servico_id)}_{tipo_limpo}_{timestamp}.{extensao}"
    destino = OS_FOTOS_DIR / nome_final

    arquivo.save(destino)

    return f"/uploads/os-fotos/{nome_final}"


def listar_fotos_equipamento_os(ordem_servico_id: int) -> list[dict[str, Any]]:
    empresa_id = empresa_logada_id()

    with conectar_db() as conn:
        rows = conn.execute(
            """
            SELECT
                id,
                empresa_id,
                ordem_servico_id,
                titulo,
                equipamento_indice,
                foto_antes_path,
                foto_depois_path,
                observacoes,
                criado_em,
                atualizado_em
            FROM os_fotos_equipamento
            WHERE ordem_servico_id = ?
              AND empresa_id = ?
            ORDER BY id ASC
            """,
            (ordem_servico_id, empresa_id),
        ).fetchall()

    return [dict(row) for row in rows]


def atualizar_fotos_equipamento_os_formulario(ordem_servico_id: int) -> None:
    empresa_id = empresa_logada_id()
    ids = request.form.getlist("foto_os_id")
    titulos = request.form.getlist("foto_os_titulo")
    indices_equipamento = request.form.getlist("foto_os_equipamento_indice")
    observacoes_lista = request.form.getlist("foto_os_observacoes")
    remover_ids = {
        int(valor)
        for valor in request.form.getlist("foto_os_remover")
        if str(valor or "").strip().isdigit()
    }
    arquivos_antes = request.files.getlist("foto_os_antes")
    arquivos_depois = request.files.getlist("foto_os_depois")
    agora = agora_empresa().isoformat(timespec="seconds")

    total_linhas = max(
        len(ids),
        len(titulos),
        len(indices_equipamento),
        len(observacoes_lista),
        len(arquivos_antes),
        len(arquivos_depois),
    )

    with conectar_db() as conn:
        for indice in range(total_linhas):
            foto_id_texto = str(ids[indice] if indice < len(ids) else "").strip()
            foto_id = int(foto_id_texto) if foto_id_texto.isdigit() else None
            titulo = str(titulos[indice] if indice < len(titulos) else "").strip()
            equipamento_indice = str(indices_equipamento[indice] if indice < len(indices_equipamento) else "0").strip() or "0"
            observacoes = str(observacoes_lista[indice] if indice < len(observacoes_lista) else "").strip()
            arquivo_antes = arquivos_antes[indice] if indice < len(arquivos_antes) else None
            arquivo_depois = arquivos_depois[indice] if indice < len(arquivos_depois) else None

            if foto_id is not None and foto_id in remover_ids:
                conn.execute(
                    """
                    DELETE FROM os_fotos_equipamento
                    WHERE id = ?
                      AND ordem_servico_id = ?
                      AND empresa_id = ?
                    """,
                    (foto_id, ordem_servico_id, empresa_id),
                )
                continue

            foto_antes_path = ""
            foto_depois_path = ""

            if arquivo_antes is not None and arquivo_antes.filename:
                foto_antes_path = salvar_upload_foto_os(arquivo_antes, ordem_servico_id, "antes")

            if arquivo_depois is not None and arquivo_depois.filename:
                foto_depois_path = salvar_upload_foto_os(arquivo_depois, ordem_servico_id, "depois")

            if foto_id is not None:
                row_atual = conn.execute(
                    """
                    SELECT foto_antes_path, foto_depois_path
                    FROM os_fotos_equipamento
                    WHERE id = ?
                      AND ordem_servico_id = ?
                      AND empresa_id = ?
                    LIMIT 1
                    """,
                    (foto_id, ordem_servico_id, empresa_id),
                ).fetchone()

                if row_atual is None:
                    continue

                conn.execute(
                    """
                    UPDATE os_fotos_equipamento
                    SET
                        titulo = ?,
                        equipamento_indice = ?,
                        foto_antes_path = ?,
                        foto_depois_path = ?,
                        observacoes = ?,
                        atualizado_em = ?
                    WHERE id = ?
                      AND ordem_servico_id = ?
                      AND empresa_id = ?
                    """,
                    (
                        titulo,
                        equipamento_indice,
                        foto_antes_path or row_atual["foto_antes_path"] or "",
                        foto_depois_path or row_atual["foto_depois_path"] or "",
                        observacoes,
                        agora,
                        foto_id,
                        ordem_servico_id,
                        empresa_id,
                    ),
                )
                continue

            if not titulo and not observacoes and not foto_antes_path and not foto_depois_path:
                continue

            conn.execute(
                """
                INSERT INTO os_fotos_equipamento (
                    empresa_id,
                    ordem_servico_id,
                    titulo,
                    equipamento_indice,
                    foto_antes_path,
                    foto_depois_path,
                    observacoes,
                    atualizado_em
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    empresa_id,
                    ordem_servico_id,
                    titulo,
                    equipamento_indice,
                    foto_antes_path,
                    foto_depois_path,
                    observacoes,
                    agora,
                ),
            )

        conn.commit()


def usuario_logado_eh_admin_sistema() -> bool:
    email = str(session.get("usuario_email") or "").strip().lower()
    perfil = str(session.get("usuario_perfil") or "").strip().lower()

    emails_admin_sistema = {
        "admin@gestflow.local",
        "nettosantana@icloud.com",
    }

    return perfil in {"super_admin", "dono", "administrador_sistema"} or email in emails_admin_sistema




def registrar_atividade_usuario(
    tipo: str,
    modulo: str,
    descricao: str,
    rota: str | None = None,
    empresa_id: int | None = None,
    usuario_id: int | None = None,
    usuario_nome: str | None = None,
) -> None:
    tipo_normalizado = str(tipo or "acesso").strip().lower() or "acesso"
    modulo_normalizado = str(modulo or "geral").strip().lower() or "geral"
    descricao_normalizada = str(descricao or "").strip()
    rota_normalizada = str(rota or (request.path if request else "")).strip()

    try:
        empresa_final = int(empresa_id if empresa_id is not None else (session.get("empresa_id") or 0))
    except (TypeError, ValueError):
        empresa_final = 0

    try:
        usuario_final = int(usuario_id if usuario_id is not None else (session.get("usuario_id") or 0))
    except (TypeError, ValueError):
        usuario_final = 0

    nome_final = str(usuario_nome or session.get("usuario_nome") or "").strip()

    if not usuario_final and not nome_final:
        return

    try:
        with conectar_db() as conn:
            conn.execute(
                """
                INSERT INTO usuario_atividades (
                    empresa_id,
                    usuario_id,
                    usuario_nome,
                    tipo,
                    modulo,
                    descricao,
                    rota,
                    criado_em
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    empresa_final or None,
                    usuario_final or None,
                    nome_final,
                    tipo_normalizado,
                    modulo_normalizado,
                    descricao_normalizada,
                    rota_normalizada,
                    agora_empresa().isoformat(timespec="seconds"),
                ),
            )
            conn.commit()
    except sqlite3.Error:
        return


def modulo_por_rota_admin(rota: str) -> str | None:
    rota = str(rota or "").strip()

    if rota == "/":
        return "dashboard"

    mapa_modulos = {
        "/clientes": "clientes",
        "/fornecedores": "fornecedores",
        "/funcionarios": "funcionarios",
        "/produtos": "produtos",
        "/servicos": "servicos",
        "/orcamentos": "orcamentos",
        "/vendas": "vendas",
        "/ordens-servico": "ordens_servico",
        "/estoque": "estoque",
        "/financeiro": "financeiro",
        "/configuracoes": "configuracoes",
        "/admin": "admin",
    }

    for prefixo, modulo in mapa_modulos.items():
        if rota == prefixo or rota.startswith(f"{prefixo}/"):
            return modulo

    return None


@app.before_request
def registrar_acesso_modulo_usuario() -> None:
    if request.method != "GET":
        return

    if not session.get("usuario_id"):
        return

    endpoint = str(request.endpoint or "")
    if endpoint in {"static", "servir_foto_os"}:
        return

    if request.path.startswith("/static/") or request.path.startswith("/uploads/"):
        return

    modulo = modulo_por_rota_admin(request.path)

    if not modulo:
        return

    registrar_atividade_usuario(
        "visualizacao",
        modulo,
        f"Acessou {modulo.replace('_', ' ')}",
        request.path,
    )


def montar_dashboard_admin() -> dict[str, Any]:
    agora = agora_empresa()
    limite_7_dias = (agora - timedelta(days=7)).isoformat(timespec="seconds")

    with conectar_db() as conn:
        resumo_row = conn.execute(
            """
            SELECT
                (SELECT COUNT(*) FROM empresas) AS total_empresas,
                (SELECT COUNT(*) FROM empresas WHERE LOWER(status) = 'trial') AS empresas_trial,
                (SELECT COUNT(*) FROM empresas WHERE LOWER(status) = 'ativo') AS empresas_ativas,
                (SELECT COUNT(*) FROM usuarios) AS total_usuarios,
                (SELECT COUNT(*) FROM usuarios WHERE ultimo_login IS NOT NULL AND TRIM(ultimo_login) <> '') AS usuarios_ja_acessaram,
                (SELECT COUNT(*) FROM usuarios WHERE ultimo_login IS NULL OR TRIM(ultimo_login) = '') AS usuarios_nunca_acessaram,
                (SELECT COUNT(*) FROM usuario_atividades WHERE criado_em >= ?) AS atividades_7_dias,
                (SELECT COUNT(DISTINCT usuario_id) FROM usuario_atividades WHERE criado_em >= ? AND usuario_id IS NOT NULL) AS usuarios_ativos_7_dias
            """,
            (limite_7_dias, limite_7_dias),
        ).fetchone()

        usuarios_rows = conn.execute(
            """
            SELECT
                usuarios.id,
                usuarios.nome,
                usuarios.email,
                usuarios.perfil,
                usuarios.status,
                usuarios.ultimo_login,
                usuarios.criado_em,
                empresas.nome_fantasia AS empresa_nome,
                empresas.status AS empresa_status,
                COALESCE(COUNT(usuario_atividades.id), 0) AS total_atividades,
                COALESCE(SUM(CASE WHEN usuario_atividades.tipo = 'login' THEN 1 ELSE 0 END), 0) AS total_logins,
                COALESCE(SUM(CASE WHEN usuario_atividades.tipo IN ('criacao', 'edicao', 'exclusao') THEN 1 ELSE 0 END), 0) AS total_acoes,
                MAX(usuario_atividades.criado_em) AS ultima_atividade
            FROM usuarios
            JOIN empresas ON empresas.id = usuarios.empresa_id
            LEFT JOIN usuario_atividades ON usuario_atividades.usuario_id = usuarios.id
            GROUP BY usuarios.id
            ORDER BY ultima_atividade DESC, usuarios.id DESC
            LIMIT 80
            """
        ).fetchall()

        atividades_rows = conn.execute(
            """
            SELECT
                usuario_atividades.id,
                usuario_atividades.empresa_id,
                usuario_atividades.usuario_id,
                usuario_atividades.usuario_nome,
                usuario_atividades.tipo,
                usuario_atividades.modulo,
                usuario_atividades.descricao,
                usuario_atividades.rota,
                usuario_atividades.criado_em,
                empresas.nome_fantasia AS empresa_nome
            FROM usuario_atividades
            LEFT JOIN empresas ON empresas.id = usuario_atividades.empresa_id
            ORDER BY usuario_atividades.id DESC
            LIMIT 60
            """
        ).fetchall()

        modulos_rows = conn.execute(
            """
            SELECT
                modulo,
                COUNT(*) AS total_acessos,
                SUM(CASE WHEN tipo IN ('criacao', 'edicao', 'exclusao') THEN 1 ELSE 0 END) AS total_acoes,
                MAX(criado_em) AS ultima_atividade
            FROM usuario_atividades
            WHERE modulo IS NOT NULL AND TRIM(modulo) <> ''
            GROUP BY modulo
            ORDER BY total_acessos DESC, modulo ASC
            LIMIT 20
            """
        ).fetchall()

    resumo = dict(resumo_row or {})
    usuarios = []

    for row in usuarios_rows:
        usuario = dict(row)
        total_logins = int(usuario.get("total_logins") or 0)
        total_acoes = int(usuario.get("total_acoes") or 0)
        ultimo_login = str(usuario.get("ultimo_login") or "").strip()

        if not ultimo_login and total_logins == 0:
            situacao = "Não testou"
            classe = "cancelada"
        elif total_acoes == 0:
            situacao = "Só entrou"
            classe = "aberta"
        elif total_acoes <= 2:
            situacao = "Testou pouco"
            classe = "aguardando"
        elif total_acoes < 10:
            situacao = "Testando"
            classe = "andamento"
        else:
            situacao = "Ativo"
            classe = "concretizada"

        usuario["situacao_uso"] = situacao
        usuario["situacao_classe"] = classe
        usuarios.append(usuario)

    return {
        "resumo": resumo,
        "usuarios": usuarios,
        "atividades": [dict(row) for row in atividades_rows],
        "modulos": [dict(row) for row in modulos_rows],
    }



def salvar_conversa_assistente(pergunta: str, resposta: str, origem: str) -> None:
    try:
        with conectar_db() as conn:
            conn.execute(
                """
                INSERT INTO assistente_conversas (
                    empresa_id,
                    usuario_id,
                    usuario_nome,
                    pergunta,
                    resposta,
                    origem,
                    criado_em
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    empresa_logada_id(),
                    usuario_logado_id(),
                    str(session.get("usuario_nome") or "").strip(),
                    str(pergunta or "").strip(),
                    str(resposta or "").strip(),
                    str(origem or "local").strip() or "local",
                    agora_empresa().isoformat(timespec="seconds"),
                ),
            )
            conn.commit()
    except sqlite3.Error:
        return


def resposta_assistente_local(pergunta: str) -> str:
    texto = str(pergunta or "").strip().lower()

    if not texto:
        return "Digite sua dúvida que eu te ajudo com o GestFlow."

    if any(palavra in texto for palavra in ["venda", "vender", "pdv", "balcão", "balcao"]):
        return (
            "Para fazer uma venda: acesse Vendas, preencha cliente, responsável, data e forma de pagamento, "
            "adicione produtos ou serviços, confira o total e clique em Salvar Venda. "
            "Para venda rápida, use Venda Balcão / PDV."
        )

    if any(palavra in texto for palavra in ["orçamento", "orcamento", "proposta"]):
        return (
            "Para criar um orçamento: acesse Orçamentos, informe cliente e responsável, adicione produtos ou serviços, "
            "confira os totais e salve. Depois você pode visualizar, editar, imprimir ou gerar cópia."
        )

    if any(palavra in texto for palavra in ["ordem de serviço", "os ", "o.s", "serviço", "servico"]):
        return (
            "Para abrir uma Ordem de Serviço: acesse Ordens de Serviço, informe cliente, técnico, equipamento, "
            "relato do cliente e itens usados. Depois você pode acompanhar, imprimir e adicionar fotos por equipamento."
        )

    if any(palavra in texto for palavra in ["cliente", "clientes"]):
        return (
            "Para cadastrar cliente: acesse Cadastros > Clientes e preencha nome, documento, telefone, cidade, status e e-mail. "
            "Em algumas telas também existe cadastro rápido sem sair do formulário."
        )

    if any(palavra in texto for palavra in ["produto", "estoque"]):
        return (
            "Para cadastrar produto: acesse Produtos > Gerenciar produtos. Informe nome, código, unidade, estoque atual, "
            "estoque mínimo e preço. Para controlar entrada e saída, use o módulo Estoque."
        )

    if any(palavra in texto for palavra in ["financeiro", "pagar", "receber", "caixa", "fluxo"]):
        return (
            "No Financeiro você controla contas a receber, contas a pagar e fluxo de caixa. "
            "Use os títulos para acompanhar vencimentos, pagamentos e saldo previsto."
        )

    if any(palavra in texto for palavra in ["escopo", "descrição", "descricao", "texto"]):
        return (
            "Posso te ajudar a montar um texto. Me diga o serviço executado, quantidade, local, problema encontrado "
            "e o que será feito. Exemplo: 'crie um escopo para manutenção de portão com troca de fim de curso'."
        )

    if any(palavra in texto for palavra in ["senha", "login", "acesso"]):
        return (
            "Para redefinir senha, um administrador deve acessar Configurações > Usuários e usar o formulário de redefinição. "
            "Por segurança, a nova senha precisa seguir as regras de senha forte."
        )

    return (
        "Sou o Assistente IA do GestFlow. Posso ajudar com vendas, orçamentos, OS, clientes, produtos, estoque, financeiro "
        "e textos de escopo. Me diga com mais detalhes o que você quer fazer."
    )


def chamar_assistente_ia(pergunta: str) -> tuple[str, str]:
    pergunta_limpa = str(pergunta or "").strip()

    api_key = str(getattr(config, "OPENAI_API_KEY", "") or os.environ.get("OPENAI_API_KEY", "")).strip()

    if not api_key:
        return resposta_assistente_local(pergunta_limpa), "local"

    prompt_sistema = (
        "Você é o Assistente IA interno do GestFlow, um ERP web simples para pequenos negócios. "
        "Responda em português do Brasil, de forma direta, prática e curta. "
        "Nesta primeira etapa você só orienta o usuário. Não diga que criou, alterou, apagou ou consultou dados reais. "
        "Não invente números do sistema. Quando o usuário pedir ação no banco, explique o caminho e diga que ações automáticas virão em etapa futura."
    )

    payload = {
        "model": str(getattr(config, "OPENAI_MODEL", "") or os.environ.get("OPENAI_MODEL", "") or "gpt-4.1-mini"),
        "input": [
            {"role": "system", "content": prompt_sistema},
            {"role": "user", "content": pergunta_limpa},
        ],
        "max_output_tokens": 450,
    }

    try:
        requisicao = urllib.request.Request(
            "https://api.openai.com/v1/responses",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )

        with urllib.request.urlopen(requisicao, timeout=18) as resposta_http:
            dados = json.loads(resposta_http.read().decode("utf-8"))

        texto_resposta = ""
        for item in dados.get("output", []):
            for conteudo in item.get("content", []):
                if conteudo.get("type") in {"output_text", "text"}:
                    texto_resposta += str(conteudo.get("text") or "")

        texto_resposta = texto_resposta.strip()

        if texto_resposta:
            return texto_resposta, "openai"

    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, ValueError, KeyError):
        pass

    return resposta_assistente_local(pergunta_limpa), "local"


def listar_empresas_admin() -> list[dict[str, Any]]:
    with conectar_db() as conn:
        rows = conn.execute(
            """
            SELECT
                empresas.id,
                empresas.nome_fantasia,
                empresas.razao_social,
                empresas.documento,
                empresas.email,
                empresas.telefone,
                empresas.plano,
                empresas.status,
                empresas.trial_inicio,
                empresas.trial_fim,
                empresas.codigo_indicacao,
                empresas.indicado_por_empresa_id,
                empresas.indicador_codigo,
                empresas.criado_em,
                COUNT(DISTINCT usuarios.id) AS total_usuarios,
                COUNT(DISTINCT lojas.id) AS total_lojas
            FROM empresas
            LEFT JOIN usuarios ON usuarios.empresa_id = empresas.id
            LEFT JOIN lojas ON lojas.empresa_id = empresas.id
            GROUP BY empresas.id
            ORDER BY empresas.id DESC
            """
        ).fetchall()

    empresas = []

    for row in rows:
        empresa = dict(row)
        dias_restantes = calcular_dias_trial_restantes(empresa.get("trial_fim"))
        empresa["trial_dias_restantes"] = dias_restantes

        if dias_restantes is None:
            empresa["trial_dias_texto"] = "-"
        elif dias_restantes < 0:
            empresa["trial_dias_texto"] = "Expirado"
        elif dias_restantes == 0:
            empresa["trial_dias_texto"] = "Hoje"
        elif dias_restantes == 1:
            empresa["trial_dias_texto"] = "1 dia"
        else:
            empresa["trial_dias_texto"] = f"{dias_restantes} dias"

        empresas.append(empresa)

    return empresas


def buscar_empresa_admin_por_id(empresa_id: int) -> dict[str, Any] | None:
    with conectar_db() as conn:
        row = conn.execute(
            """
            SELECT
                id,
                nome_fantasia,
                razao_social,
                documento,
                email,
                telefone,
                plano,
                status,
                trial_inicio,
                trial_fim,
                codigo_indicacao,
                indicado_por_empresa_id,
                indicador_codigo,
                criado_em
            FROM empresas
            WHERE id = ?
            LIMIT 1
            """,
            (empresa_id,),
        ).fetchone()

    if row is None:
        return None

    return dict(row)


def email_usuario_ja_existe(email: str) -> bool:
    email_normalizado = str(email or "").strip().lower()

    if not email_normalizado:
        return False

    with conectar_db() as conn:
        row = conn.execute(
            """
            SELECT id
            FROM usuarios
            WHERE LOWER(email) = ?
            LIMIT 1
            """,
            (email_normalizado,),
        ).fetchone()

    return row is not None


def buscar_usuario_admin_por_email(email: str) -> dict[str, Any] | None:
    email_normalizado = str(email or "").strip().lower()

    if not email_normalizado:
        return None

    with conectar_db() as conn:
        row = conn.execute(
            """
            SELECT
                id,
                empresa_id,
                nome,
                email,
                perfil,
                status
            FROM usuarios
            WHERE LOWER(email) = ?
            LIMIT 1
            """,
            (email_normalizado,),
        ).fetchone()

    if row is None:
        return None

    return dict(row)


def montar_empresa_admin_formulario() -> dict[str, str]:
    return {
        "admin_nome": (request.form.get("usuario_admin_nome") or "").strip(),
        "admin_email": (request.form.get("usuario_admin_email") or "").strip().lower(),
        "admin_senha": (request.form.get("usuario_admin_senha") or "").strip(),
        "plano": (request.form.get("empresa_plano") or "Start").strip() or "Start",
        "status": (request.form.get("empresa_status") or "ativo").strip() or "ativo",
    }


def criar_empresa_cliente_db(dados: dict[str, str]) -> int:
    admin_nome = dados["admin_nome"] or "Cliente GestFlow"
    admin_email = dados["admin_email"]
    admin_senha = dados["admin_senha"]
    nome_empresa_provisorio = f"Cadastro pendente - {admin_nome}".strip()
    loja_nome = "Matriz"

    with conectar_db() as conn:
        cursor_empresa = conn.execute(
            """
            INSERT INTO empresas (
                nome_fantasia,
                razao_social,
                documento,
                email,
                telefone,
                plano,
                status
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                nome_empresa_provisorio,
                "Cadastro pendente",
                "",
                admin_email,
                "",
                dados["plano"],
                dados["status"],
            ),
        )
        empresa_id = int(cursor_empresa.lastrowid)

        conn.execute(
            """
            INSERT INTO usuarios (
                empresa_id,
                nome,
                email,
                senha_hash,
                perfil,
                status,
                ultimo_login
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                empresa_id,
                admin_nome,
                admin_email,
                generate_password_hash(admin_senha),
                "administrador",
                "ativo",
                "",
            ),
        )

        conn.execute(
            """
            INSERT INTO lojas (
                empresa_id,
                nome,
                tipo,
                cidade,
                status
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (
                empresa_id,
                loja_nome,
                "Principal",
                "",
                "ativo",
            ),
        )

        conn.commit()

    return empresa_id


def atualizar_senha_acesso_admin_db(dados: dict[str, str]) -> int | None:
    admin_email = str(dados.get("admin_email") or "").strip().lower()
    admin_senha = str(dados.get("admin_senha") or "").strip()

    if not admin_email or not admin_senha:
        return None

    usuario_existente = buscar_usuario_admin_por_email(admin_email)

    if usuario_existente is None:
        return None

    usuario_id = int(usuario_existente["id"])
    empresa_id = int(usuario_existente["empresa_id"])
    admin_nome = str(dados.get("admin_nome") or usuario_existente.get("nome") or "Cliente GestFlow").strip()
    plano = str(dados.get("plano") or "Start").strip() or "Start"

    senha_hash_nova = generate_password_hash(admin_senha)

    with conectar_db() as conn:
        conn.execute(
            """
            UPDATE usuarios
            SET
                nome = ?,
                email = ?,
                senha_hash = ?,
                perfil = 'administrador',
                status = 'ativo'
            WHERE id = ?
            """,
            (
                admin_nome,
                admin_email,
                senha_hash_nova,
                usuario_id,
            ),
        )

        conn.execute(
            """
            UPDATE empresas
            SET
                email = ?,
                plano = ?,
                status = 'ativo'
            WHERE id = ?
            """,
            (
                admin_email,
                plano,
                empresa_id,
            ),
        )

        conn.execute(
            """
            UPDATE lojas
            SET status = 'ativo'
            WHERE empresa_id = ?
            """,
            (empresa_id,),
        )

        conn.commit()

    usuario_teste = buscar_usuario_por_email(admin_email)

    if usuario_teste is None:
        return None

    if not check_password_hash(str(usuario_teste.get("senha_hash") or ""), admin_senha):
        return None

    return empresa_id

def atualizar_status_empresa_admin_db(empresa_id: int, status: str) -> None:
    status_normalizado = str(status or "").strip()

    if status_normalizado not in {"trial", "ativo", "bloqueado", "cancelado"}:
        status_normalizado = "ativo"

    with conectar_db() as conn:
        conn.execute(
            """
            UPDATE empresas
            SET status = ?
            WHERE id = ?
            """,
            (status_normalizado, empresa_id),
        )
        conn.commit()


def excluir_empresa_cliente_admin_db(empresa_id: int) -> bool:
    try:
        empresa_id = int(empresa_id)
    except (TypeError, ValueError):
        return False

    empresa_principal_id = empresa_padrao_id()
    empresa_sessao_id = empresa_logada_id()

    if empresa_id <= 0:
        return False

    if empresa_id == empresa_principal_id:
        return False

    if empresa_id == empresa_sessao_id:
        return False

    empresa = buscar_empresa_admin_por_id(empresa_id)

    if empresa is None:
        return False

    with conectar_db() as conn:
        tabelas_por_empresa = [
            "orcamento_itens",
            "venda_itens",
            "ordem_servico_itens",
            "estoque_movimentacoes",
            "financeiro_titulos",
            "orcamentos",
            "vendas",
            "ordens_servico",
            "clientes",
            "fornecedores",
            "funcionarios",
            "produtos",
            "servicos",
        ]

        for tabela in tabelas_por_empresa:
            conn.execute(
                f"DELETE FROM {tabela} WHERE empresa_id = ?",
                (empresa_id,),
            )

        conn.execute(
            """
            DELETE FROM indicacao_comissoes
            WHERE indicador_empresa_id = ?
               OR indicado_empresa_id = ?
            """,
            (empresa_id, empresa_id),
        )

        conn.execute(
            """
            UPDATE empresas
            SET
                indicado_por_empresa_id = NULL,
                indicador_codigo = ''
            WHERE indicado_por_empresa_id = ?
            """,
            (empresa_id,),
        )

        conn.execute(
            """
            DELETE FROM lojas
            WHERE empresa_id = ?
            """,
            (empresa_id,),
        )

        conn.execute(
            """
            DELETE FROM usuarios
            WHERE empresa_id = ?
            """,
            (empresa_id,),
        )

        conn.execute(
            """
            DELETE FROM empresas
            WHERE id = ?
            """,
            (empresa_id,),
        )

        conn.commit()

    return True



@app.get("/admin/dashboard")
def admin_dashboard() -> str | Response:
    if not usuario_logado_eh_admin_sistema():
        return redirect(url_for("dashboard"))

    return render_template(
        "admin_dashboard.html",
        admin_dashboard=montar_dashboard_admin(),
    )


@app.route("/admin/empresas", methods=["GET", "POST"])
def admin_empresas() -> str | Response:
    if not usuario_logado_eh_admin_sistema():
        return redirect(url_for("dashboard"))

    erro = ""
    sucesso = ""
    formulario = {
        "plano": "Start",
        "status": "ativo",
        "admin_nome": "",
        "admin_email": "",
        "admin_senha": "",
    }

    if request.method == "POST":
        formulario = montar_empresa_admin_formulario()

        if not formulario["admin_nome"]:
            erro = "Informe o nome do cliente ou responsável."
        elif not formulario["admin_email"]:
            erro = "Informe o e-mail de login."
        elif not formulario["admin_senha"]:
            erro = "Informe a senha inicial."
        elif email_usuario_ja_existe(formulario["admin_email"]):
            empresa_id = atualizar_senha_acesso_admin_db(formulario)
            if empresa_id is None:
                erro = "Este e-mail já existe, mas não foi possível atualizar a senha."
            else:
                sucesso = f"Senha atualizada com sucesso. Login ativo e empresa ativa para o ID {empresa_id}."
                formulario = {
                    "plano": "Start",
                    "status": "ativo",
                    "admin_nome": "",
                    "admin_email": "",
                    "admin_senha": "",
                }
        else:
            empresa_id = criar_empresa_cliente_db(formulario)
            sucesso = f"Acesso criado com sucesso. ID provisório {empresa_id}."
            formulario = {
                "plano": "Start",
                "status": "ativo",
                "admin_nome": "",
                "admin_email": "",
                "admin_senha": "",
            }

    return render_template(
        "admin_empresas.html",
        empresas=listar_empresas_admin(),
        erro=erro,
        sucesso=sucesso,
        formulario=formulario,
    )


@app.post("/admin/empresas/<int:empresa_id>/status")
def admin_alterar_status_empresa(empresa_id: int) -> Response:
    if not usuario_logado_eh_admin_sistema():
        return redirect(url_for("dashboard"))

    empresa = buscar_empresa_admin_por_id(empresa_id)

    if empresa is not None:
        novo_status = (request.form.get("empresa_status") or "ativo").strip()
        atualizar_status_empresa_admin_db(empresa_id, novo_status)

    return redirect(url_for("admin_empresas"))


@app.post("/admin/empresas/<int:empresa_id>/excluir")
def admin_excluir_empresa(empresa_id: int) -> Response:
    if not usuario_logado_eh_admin_sistema():
        return redirect(url_for("dashboard"))

    excluir_empresa_cliente_admin_db(empresa_id)

    return redirect(url_for("admin_empresas"))



@app.get("/configuracoes")
@app.get("/configuracoes/gerais")
@app.get("/configuracoes/plano")
@app.get("/configuracoes/usuarios")
@app.get("/configuracoes/empresa")
@app.get("/configuracoes/marca")
@app.get("/configuracoes/lojas")
def configuracoes() -> str:
    aba = "gerais"

    if request.path.endswith("/plano"):
        aba = "plano"
    elif request.path.endswith("/usuarios"):
        aba = "usuarios"
    elif request.path.endswith("/empresa"):
        aba = "empresa"
    elif request.path.endswith("/marca"):
        aba = "marca"
    elif request.path.endswith("/lojas"):
        aba = "lojas"

    contexto = montar_configuracoes_contexto()

    return render_template(
        "configuracoes.html",
        aba=aba,
        empresa=contexto["empresa"],
        usuarios=contexto["usuarios"],
        lojas=contexto["lojas"],
        fusos_horarios=contexto["fusos_horarios"],
        erro=request.args.get("erro", ""),
        sucesso=request.args.get("sucesso", ""),
    )


@app.post("/configuracoes/gerais")
def salvar_configuracoes_gerais() -> Response:
    timezone = request.form.get("geral_timezone") or request.form.get("geral_fuso") or TIMEZONE_PADRAO_GESTFLOW
    atualizar_timezone_empresa_configuracoes_db(timezone)
    return redirect("/configuracoes/gerais?sucesso=Configurações gerais salvas com sucesso.")


@app.post("/configuracoes/empresa")
def salvar_configuracoes_empresa() -> Response:
    dados = {
        "nome_fantasia": (request.form.get("empresa_nome_fantasia") or "").strip(),
        "razao_social": (request.form.get("empresa_razao_social") or "").strip(),
        "documento": (request.form.get("empresa_documento") or "").strip(),
        "email": (request.form.get("empresa_email") or "").strip(),
        "telefone": (request.form.get("empresa_telefone") or "").strip(),
    }

    if dados["nome_fantasia"]:
        atualizar_empresa_configuracoes_db(dados)

    return redirect("/configuracoes/empresa")


@app.post("/configuracoes/marca")
def salvar_configuracoes_marca() -> Response:
    arquivo = request.files.get("marca_logo")

    if arquivo is not None and arquivo.filename:
        logo_path = salvar_upload_logo_empresa(arquivo)
        salvar_logo_empresa_db(logo_path)

    return redirect("/configuracoes/marca")


@app.get("/uploads/logos/<path:nome_arquivo>")
def servir_logo_empresa(nome_arquivo: str) -> Response:
    return send_from_directory(UPLOAD_DIR, nome_arquivo)


@app.get("/uploads/os-fotos/<path:nome_arquivo>")
def servir_foto_os(nome_arquivo: str) -> Response:
    return send_from_directory(OS_FOTOS_DIR, nome_arquivo)



def montar_novo_cadastro_formulario() -> dict[str, str]:
    plano = (request.form.get("plano") or request.args.get("plano") or "Start").strip() or "Start"

    if plano not in {"Start", "Pro", "Business"}:
        plano = "Start"

    return {
        "responsavel_nome": (request.form.get("responsavel_nome") or "").strip(),
        "empresa_nome": (request.form.get("empresa_nome") or "").strip(),
        "telefone": (request.form.get("telefone") or "").strip(),
        "email": (request.form.get("email") or "").strip().lower(),
        "senha": (request.form.get("senha") or "").strip(),
        "confirmar_senha": (request.form.get("confirmar_senha") or "").strip(),
        "termos_uso": (request.form.get("termos_uso") or "").strip(),
        "plano": plano,
        "ref": normalizar_codigo_indicacao(request.form.get("ref") or request.args.get("ref") or ""),
    }


def validar_senha_forte(senha: str) -> str:
    senha = str(senha or "")

    if len(senha) < 8:
        return "A senha precisa ter no mínimo 8 caracteres."

    if not re.search(r"[A-Z]", senha):
        return "A senha precisa ter pelo menos uma letra maiúscula."

    if not re.search(r"[a-z]", senha):
        return "A senha precisa ter pelo menos uma letra minúscula."

    if not re.search(r"\d", senha):
        return "A senha precisa ter pelo menos um número."

    if not re.search(r"[^A-Za-z0-9]", senha):
        return "A senha precisa ter pelo menos um caractere especial."

    return ""


def validar_novo_cadastro(formulario: dict[str, str]) -> str:
    if not formulario["responsavel_nome"]:
        return "Informe seu nome."

    if not formulario["empresa_nome"]:
        return "Informe o nome da empresa."

    if not formulario["telefone"]:
        return "Informe um telefone ou WhatsApp."

    if not formulario["email"]:
        return "Informe o e-mail de acesso."

    if email_usuario_ja_existe(formulario["email"]):
        return "Este e-mail já possui cadastro. Acesse pelo login ou use outro e-mail."

    erro_senha = validar_senha_forte(formulario["senha"])
    if erro_senha:
        return erro_senha

    if formulario["senha"] != formulario["confirmar_senha"]:
        return "A confirmação de senha não confere."

    if formulario.get("termos_uso") != "sim":
        return "Confirme que leu e concorda com os termos de uso."

    if formulario.get("ref") and buscar_empresa_por_codigo_indicacao(formulario["ref"]) is None:
        return "O código de indicação informado não foi encontrado. Confira o link recebido."

    return ""


def criar_empresa_trial_db(formulario: dict[str, str]) -> int:
    trial_inicio = hoje_empresa()
    trial_fim = trial_inicio + timedelta(days=7)
    indicador = buscar_empresa_por_codigo_indicacao(formulario.get("ref"))
    indicador_empresa_id = int(indicador["id"]) if indicador is not None else None
    indicador_codigo = normalizar_codigo_indicacao(formulario.get("ref")) if indicador is not None else ""

    with conectar_db() as conn:
        cursor_empresa = conn.execute(
            """
            INSERT INTO empresas (
                nome_fantasia,
                razao_social,
                documento,
                email,
                telefone,
                plano,
                status,
                trial_inicio,
                trial_fim,
                indicado_por_empresa_id,
                indicador_codigo
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                formulario["empresa_nome"],
                formulario["empresa_nome"],
                "",
                formulario["email"],
                formulario["telefone"],
                formulario["plano"],
                "trial",
                trial_inicio.isoformat(),
                trial_fim.isoformat(),
                indicador_empresa_id,
                indicador_codigo,
            ),
        )
        empresa_id = int(cursor_empresa.lastrowid)
        garantir_codigo_indicacao_empresa(empresa_id, conn)

        conn.execute(
            """
            INSERT INTO usuarios (
                empresa_id,
                nome,
                email,
                senha_hash,
                perfil,
                status,
                ultimo_login
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                empresa_id,
                formulario["responsavel_nome"],
                formulario["email"],
                generate_password_hash(formulario["senha"]),
                "administrador",
                "ativo",
                "",
            ),
        )

        conn.execute(
            """
            INSERT INTO lojas (
                empresa_id,
                nome,
                tipo,
                cidade,
                status
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (
                empresa_id,
                "Matriz",
                "Principal",
                "",
                "ativo",
            ),
        )

        conn.commit()

    return empresa_id

def entrar_usuario_na_sessao(usuario: dict[str, Any]) -> None:
    session.clear()
    session["usuario_id"] = int(usuario["id"])
    session["empresa_id"] = int(usuario["empresa_id"])
    session["usuario_nome"] = str(usuario.get("nome") or "")
    session["usuario_email"] = str(usuario.get("email") or "")
    session["usuario_perfil"] = str(usuario.get("perfil") or "")
    session["empresa_nome"] = str(usuario.get("empresa_nome") or "")
    session["empresa_plano"] = str(usuario.get("empresa_plano") or "")
    registrar_ultimo_login_usuario(int(usuario["id"]))



def buscar_onboarding_empresa() -> dict[str, Any]:
    with conectar_db() as conn:
        row = conn.execute(
            """
            SELECT
                id,
                nome_fantasia,
                onboarding_concluido,
                onboarding_ramo,
                onboarding_objetivos,
                onboarding_ferramenta_atual,
                onboarding_canal_contato,
                tour_concluido
            FROM empresas
            WHERE id = ?
            LIMIT 1
            """,
            (empresa_logada_id(),),
        ).fetchone()

    if row is None:
        return {
            "id": empresa_logada_id(),
            "nome_fantasia": "",
            "onboarding_concluido": "nao",
            "onboarding_ramo": "",
            "onboarding_objetivos": "",
            "onboarding_ferramenta_atual": "",
            "onboarding_canal_contato": "",
            "tour_concluido": "nao",
        }

    return dict(row)


def empresa_precisa_onboarding() -> bool:
    if not session.get("usuario_id"):
        return False

    empresa = buscar_onboarding_empresa()
    return str(empresa.get("onboarding_concluido") or "nao").strip().lower() != "sim"


def empresa_precisa_tour() -> bool:
    if not session.get("usuario_id"):
        return False

    empresa = buscar_onboarding_empresa()
    onboarding_ok = str(empresa.get("onboarding_concluido") or "nao").strip().lower() == "sim"
    tour_ok = str(empresa.get("tour_concluido") or "nao").strip().lower() == "sim"
    return onboarding_ok and not tour_ok


def montar_onboarding_formulario() -> dict[str, str]:
    objetivos = request.form.getlist("objetivos")

    return {
        "ramo": (request.form.get("ramo") or "").strip(),
        "objetivos": ", ".join(item.strip() for item in objetivos if item.strip()),
        "ferramenta_atual": (request.form.get("ferramenta_atual") or "").strip(),
        "canal_contato": (request.form.get("canal_contato") or "").strip(),
    }


def salvar_onboarding_empresa_db(dados: dict[str, str]) -> None:
    with conectar_db() as conn:
        conn.execute(
            """
            UPDATE empresas
            SET
                onboarding_concluido = 'sim',
                onboarding_ramo = ?,
                onboarding_objetivos = ?,
                onboarding_ferramenta_atual = ?,
                onboarding_canal_contato = ?
            WHERE id = ?
            """,
            (
                dados["ramo"],
                dados["objetivos"],
                dados["ferramenta_atual"],
                dados["canal_contato"],
                empresa_logada_id(),
            ),
        )
        conn.commit()


def marcar_tour_concluido_db() -> None:
    with conectar_db() as conn:
        conn.execute(
            """
            UPDATE empresas
            SET tour_concluido = 'sim'
            WHERE id = ?
            """,
            (empresa_logada_id(),),
        )
        conn.commit()



def listar_indicados_empresa(empresa_id: int) -> list[dict[str, Any]]:
    with conectar_db() as conn:
        rows = conn.execute(
            """
            SELECT
                id,
                nome_fantasia,
                email,
                telefone,
                plano,
                status,
                trial_inicio,
                trial_fim,
                criado_em
            FROM empresas
            WHERE indicado_por_empresa_id = ?
            ORDER BY id DESC
            """,
            (empresa_id,),
        ).fetchall()

    return [dict(row) for row in rows]


def listar_comissoes_indicador(empresa_id: int) -> list[dict[str, Any]]:
    with conectar_db() as conn:
        rows = conn.execute(
            """
            SELECT
                indicacao_comissoes.id,
                indicacao_comissoes.indicador_empresa_id,
                indicacao_comissoes.indicado_empresa_id,
                indicacao_comissoes.plano,
                indicacao_comissoes.competencia,
                indicacao_comissoes.valor,
                indicacao_comissoes.status,
                indicacao_comissoes.data_pagamento_cliente,
                indicacao_comissoes.data_liberacao,
                indicacao_comissoes.data_repasse,
                indicacao_comissoes.observacoes,
                indicacao_comissoes.criado_em,
                empresas.nome_fantasia AS indicado_nome,
                empresas.email AS indicado_email
            FROM indicacao_comissoes
            JOIN empresas ON empresas.id = indicacao_comissoes.indicado_empresa_id
            WHERE indicacao_comissoes.indicador_empresa_id = ?
            ORDER BY indicacao_comissoes.id DESC
            """,
            (empresa_id,),
        ).fetchall()

    comissoes = []
    for row in rows:
        item = dict(row)
        item["valor_formatado"] = formatar_valor_comissao(_converter_valor_brl(item.get("valor")))
        comissoes.append(item)

    return comissoes


def montar_indicacoes_contexto() -> dict[str, Any]:
    empresa = buscar_empresa_configuracoes()
    empresa_id = int(empresa.get("id") or empresa_logada_id())
    codigo = garantir_codigo_indicacao_empresa(empresa_id)
    empresa["codigo_indicacao"] = codigo
    empresa["link_indicacao"] = montar_link_indicacao(codigo)

    indicados = listar_indicados_empresa(empresa_id)
    comissoes = listar_comissoes_indicador(empresa_id)

    totais = {
        "indicados": len(indicados),
        "pendente": 0.0,
        "liberada": 0.0,
        "paga": 0.0,
        "cancelada": 0.0,
    }

    for comissao in comissoes:
        status = str(comissao.get("status") or "liberada").strip()
        valor = _converter_valor_brl(comissao.get("valor"))
        if status in totais:
            totais[status] += valor

    totais_formatados = {chave: formatar_valor_comissao(valor) if chave != "indicados" else valor for chave, valor in totais.items()}

    return {
        "empresa": empresa,
        "indicados": indicados,
        "comissoes": comissoes,
        "totais": totais_formatados,
    }


def atualizar_pix_indicador_db(chave_pix: str) -> None:
    with conectar_db() as conn:
        conn.execute(
            """
            UPDATE empresas
            SET pix_indicador = ?
            WHERE id = ?
            """,
            (chave_pix, empresa_logada_id()),
        )
        conn.commit()


def listar_indicacoes_admin() -> dict[str, Any]:
    with conectar_db() as conn:
        indicacoes_rows = conn.execute(
            """
            SELECT
                indicadas.id AS indicado_id,
                indicadas.nome_fantasia AS indicado_nome,
                indicadas.email AS indicado_email,
                indicadas.plano AS indicado_plano,
                indicadas.status AS indicado_status,
                indicadas.criado_em AS indicado_criado_em,
                indicadas.indicador_codigo,
                indicadoras.id AS indicador_id,
                indicadoras.nome_fantasia AS indicador_nome,
                indicadoras.email AS indicador_email,
                indicadoras.pix_indicador AS indicador_pix
            FROM empresas indicadas
            JOIN empresas indicadoras ON indicadoras.id = indicadas.indicado_por_empresa_id
            ORDER BY indicadas.id DESC
            """
        ).fetchall()

        comissoes_rows = conn.execute(
            """
            SELECT
                indicacao_comissoes.id,
                indicacao_comissoes.indicador_empresa_id,
                indicacao_comissoes.indicado_empresa_id,
                indicacao_comissoes.plano,
                indicacao_comissoes.competencia,
                indicacao_comissoes.valor,
                indicacao_comissoes.status,
                indicacao_comissoes.data_pagamento_cliente,
                indicacao_comissoes.data_liberacao,
                indicacao_comissoes.data_repasse,
                indicacao_comissoes.observacoes,
                indicacao_comissoes.criado_em,
                indicadoras.nome_fantasia AS indicador_nome,
                indicadoras.email AS indicador_email,
                indicadoras.pix_indicador AS indicador_pix,
                indicadas.nome_fantasia AS indicado_nome,
                indicadas.email AS indicado_email
            FROM indicacao_comissoes
            JOIN empresas indicadoras ON indicadoras.id = indicacao_comissoes.indicador_empresa_id
            JOIN empresas indicadas ON indicadas.id = indicacao_comissoes.indicado_empresa_id
            ORDER BY indicacao_comissoes.id DESC
            """
        ).fetchall()

    indicacoes = [dict(row) for row in indicacoes_rows]
    comissoes = []

    for row in comissoes_rows:
        item = dict(row)
        item["valor_formatado"] = formatar_valor_comissao(_converter_valor_brl(item.get("valor")))
        comissoes.append(item)

    total_liberado = sum(_converter_valor_brl(item.get("valor")) for item in comissoes if item.get("status") == "liberada")
    total_pago = sum(_converter_valor_brl(item.get("valor")) for item in comissoes if item.get("status") == "paga")
    total_pendente = sum(_converter_valor_brl(item.get("valor")) for item in comissoes if item.get("status") == "pendente")

    return {
        "indicacoes": indicacoes,
        "comissoes": comissoes,
        "totais": {
            "indicacoes": len(indicacoes),
            "liberado": formatar_valor_comissao(total_liberado),
            "pago": formatar_valor_comissao(total_pago),
            "pendente": formatar_valor_comissao(total_pendente),
        },
    }


def registrar_pagamento_indicacao_db(indicado_empresa_id: int, competencia: str = "") -> tuple[bool, str]:
    indicado = buscar_empresa_admin_por_id(indicado_empresa_id)

    if indicado is None:
        return False, "Empresa indicada não encontrada."

    indicador_empresa_id = indicado.get("indicado_por_empresa_id")

    if not indicador_empresa_id:
        return False, "Esta empresa não possui indicador vinculado."

    competencia = str(competencia or hoje_empresa().strftime("%Y-%m")).strip()[:7]

    if not competencia:
        competencia = hoje_empresa().strftime("%Y-%m")

    plano = str(indicado.get("plano") or "Start").strip() or "Start"
    valor = valor_comissao_por_plano(plano)

    with conectar_db() as conn:
        existente = conn.execute(
            """
            SELECT id
            FROM indicacao_comissoes
            WHERE indicado_empresa_id = ?
              AND competencia = ?
              AND status <> 'cancelada'
            LIMIT 1
            """,
            (indicado_empresa_id, competencia),
        ).fetchone()

        if existente is not None:
            return False, "Comissão desta competência já foi registrada para esta indicação."

        conn.execute(
            """
            INSERT INTO indicacao_comissoes (
                indicador_empresa_id,
                indicado_empresa_id,
                plano,
                competencia,
                valor,
                status,
                data_pagamento_cliente,
                data_liberacao,
                data_repasse,
                observacoes
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                int(indicador_empresa_id),
                int(indicado_empresa_id),
                plano,
                competencia,
                _formatar_moeda_brl(valor),
                "liberada",
                hoje_empresa().isoformat(),
                hoje_empresa().isoformat(),
                "",
                "Comissão recorrente gerada após pagamento confirmado do cliente indicado.",
            ),
        )
        conn.commit()

    return True, "Comissão registrada como liberada."


def atualizar_status_comissao_indicacao_db(comissao_id: int, status: str) -> None:
    status_normalizado = str(status or "").strip()

    if status_normalizado not in {"pendente", "liberada", "paga", "cancelada"}:
        status_normalizado = "liberada"

    data_repasse = hoje_empresa().isoformat() if status_normalizado == "paga" else ""

    with conectar_db() as conn:
        conn.execute(
            """
            UPDATE indicacao_comissoes
            SET
                status = ?,
                data_repasse = ?
            WHERE id = ?
            """,
            (status_normalizado, data_repasse, comissao_id),
        )
        conn.commit()


@app.get("/indicacoes")
def indicacoes() -> str:
    return render_template("indicacoes.html", contexto=montar_indicacoes_contexto())


@app.post("/indicacoes/pix")
def salvar_pix_indicador() -> Response:
    chave_pix = (request.form.get("pix_indicador") or "").strip()
    atualizar_pix_indicador_db(chave_pix)
    return redirect(url_for("indicacoes"))


@app.get("/admin/indicacoes")
def admin_indicacoes() -> str | Response:
    if not usuario_logado_eh_admin_sistema():
        return redirect(url_for("dashboard"))

    return render_template(
        "admin_indicacoes.html",
        contexto=listar_indicacoes_admin(),
        hoje_competencia=hoje_empresa().strftime("%Y-%m"),
        erro=request.args.get("erro", ""),
        sucesso=request.args.get("sucesso", ""),
    )


@app.post("/admin/indicacoes/<int:empresa_id>/registrar-pagamento")
def admin_registrar_pagamento_indicacao(empresa_id: int) -> Response:
    if not usuario_logado_eh_admin_sistema():
        return redirect(url_for("dashboard"))

    competencia = (request.form.get("competencia") or "").strip()
    ok, mensagem = registrar_pagamento_indicacao_db(empresa_id, competencia)

    if ok:
        return redirect(url_for("admin_indicacoes", sucesso=mensagem))

    return redirect(url_for("admin_indicacoes", erro=mensagem))


@app.post("/admin/indicacoes/comissoes/<int:comissao_id>/status")
def admin_atualizar_status_comissao_indicacao(comissao_id: int) -> Response:
    if not usuario_logado_eh_admin_sistema():
        return redirect(url_for("dashboard"))

    novo_status = (request.form.get("status") or "liberada").strip()
    atualizar_status_comissao_indicacao_db(comissao_id, novo_status)
    return redirect(url_for("admin_indicacoes", sucesso="Status da comissão atualizado."))

@app.get("/portal")
def portal() -> str:
    return render_template("portal.html")


@app.get("/planos")
def planos() -> str:
    return render_template("planos.html", ref=normalizar_codigo_indicacao(request.args.get("ref") or ""))


@app.route("/novo-cadastro", methods=["GET", "POST"])
def novo_cadastro() -> str | Response:
    formulario = montar_novo_cadastro_formulario()
    erro = ""

    if request.method == "POST":
        erro = validar_novo_cadastro(formulario)

        if not erro:
            criar_empresa_trial_db(formulario)
            usuario = buscar_usuario_por_email(formulario["email"])

            if usuario is None:
                return redirect(url_for("login"))

            entrar_usuario_na_sessao(usuario)
            return redirect(url_for("dashboard"))

    return render_template(
        "novo_cadastro.html",
        formulario=formulario,
        erro=erro,
    )


@app.route("/login", methods=["GET", "POST"])
def login() -> str | Response:
    if request.method == "GET" and session.get("usuario_id"):
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        email = (request.form.get("email") or "").strip().lower()
        senha = (request.form.get("senha") or "").strip()

        usuario = autenticar_usuario(email, senha)

        if usuario is None:
            return render_template(
                "login.html",
                erro_login="E-mail ou senha inválidos.",
                email_login=email,
            ), 401

        entrar_usuario_na_sessao(usuario)
        registrar_atividade_usuario("login", "acesso", "Login realizado", request.path)

        return redirect(url_for("dashboard"))

    return render_template("login.html")


@app.get("/esqueci-senha")
def esqueci_senha() -> str:
    return """
    <!DOCTYPE html>
    <html lang="pt-BR">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>GestFlow - Recuperar senha</title>
        <style>
            * { box-sizing: border-box; }
            body {
                margin: 0;
                min-height: 100vh;
                display: flex;
                align-items: center;
                justify-content: center;
                padding: 24px;
                background: linear-gradient(135deg, #06162b 0%, #0d2746 100%);
                color: #132238;
                font-family: Inter, Arial, Helvetica, sans-serif;
            }
            .card {
                width: min(520px, 100%);
                background: #ffffff;
                border-radius: 24px;
                padding: 34px;
                box-shadow: 0 22px 60px rgba(5, 20, 42, 0.22);
                text-align: center;
            }
            .badge {
                display: inline-flex;
                border-radius: 999px;
                padding: 8px 14px;
                margin-bottom: 18px;
                background: #eff6ff;
                color: #1e3a8a;
                font-weight: 900;
                font-size: 13px;
            }
            h1 {
                margin: 0 0 10px;
                color: #06162b;
                font-size: 28px;
            }
            p {
                margin: 0 0 18px;
                color: #60708a;
                line-height: 1.6;
            }
            .notice {
                border: 1px solid #dbe5f1;
                background: #f8fbff;
                border-radius: 16px;
                padding: 16px;
                margin: 18px 0;
                text-align: left;
                color: #334155;
                line-height: 1.55;
            }
            .actions {
                display: flex;
                justify-content: center;
                gap: 10px;
                flex-wrap: wrap;
                margin-top: 22px;
            }
            a {
                display: inline-flex;
                align-items: center;
                justify-content: center;
                min-height: 44px;
                padding: 0 18px;
                border-radius: 10px;
                font-weight: 900;
                text-decoration: none;
            }
            .primary {
                background: #06162b;
                color: #ffffff;
            }
            .light {
                border: 1px solid #dbe5f1;
                color: #06162b;
                background: #ffffff;
            }
        </style>
    </head>
    <body>
        <main class="card">
            <span class="badge">Recuperação de acesso</span>
            <h1>Esqueceu sua senha?</h1>
            <p>Por enquanto, a redefinição automática por e-mail ainda não está ativa.</p>
            <div class="notice">
                Solicite ao administrador da sua empresa para acessar <strong>Configurações &gt; Usuários</strong> e redefinir sua senha.
                A nova senha deverá seguir os critérios de segurança do GestFlow.
            </div>
            <div class="actions">
                <a href="/login" class="primary">Voltar para o login</a>
                <a href="/portal" class="light">Voltar ao portal</a>
            </div>
        </main>
    </body>
    </html>
    """


@app.post("/configuracoes/usuarios/redefinir-senha")
def redefinir_senha_usuario_configuracoes() -> Response:
    try:
        usuario_id = int(request.form.get("usuario_id") or 0)
    except (TypeError, ValueError):
        usuario_id = 0

    nova_senha = (request.form.get("nova_senha") or "").strip()
    confirmar_senha = (request.form.get("confirmar_senha") or "").strip()

    usuario = buscar_usuario_configuracoes_por_id(usuario_id)

    if usuario is None:
        return redirect("/configuracoes/usuarios?erro=Usuário não encontrado nesta empresa.")

    erro_senha = validar_senha_forte(nova_senha)
    if erro_senha:
        return redirect(f"/configuracoes/usuarios?erro={erro_senha}")

    if nova_senha != confirmar_senha:
        return redirect("/configuracoes/usuarios?erro=A confirmação da senha não confere.")

    redefinir_senha_usuario_configuracoes_db(usuario_id, nova_senha)

    return redirect("/configuracoes/usuarios?sucesso=Senha redefinida com sucesso.")


@app.get("/sair")
def sair() -> Response:
    session.clear()
    return redirect(url_for("login"))


@app.route("/onboarding", methods=["GET", "POST"])
def onboarding() -> str | Response:
    if not session.get("usuario_id"):
        return redirect(url_for("login"))

    empresa = buscar_onboarding_empresa()

    if request.method == "POST":
        dados = montar_onboarding_formulario()
        salvar_onboarding_empresa_db(dados)
        return redirect(url_for("dashboard", tour="1"))

    return render_template("onboarding.html", empresa=empresa)


@app.post("/tour/concluir")
def concluir_tour() -> Response:
    if not session.get("usuario_id"):
        return jsonify({"ok": False}), 401

    marcar_tour_concluido_db()
    return jsonify({"ok": True})


@app.get("/")
def dashboard() -> str | Response:
    if empresa_precisa_onboarding():
        return redirect(url_for("onboarding"))

    dados_dashboard = montar_dashboard()
    iniciar_tour = empresa_precisa_tour() or request.args.get("tour") == "1"

    return render_template(
        "dashboard.html",
        dashboard=dados_dashboard,
        iniciar_tour=iniciar_tour,
    )



def normalizar_cliente_para_salvar(cliente: dict[str, str]) -> dict[str, str]:
    cliente_normalizado = dict(cliente)

    if not cliente_normalizado["status"]:
        cliente_normalizado["status"] = "ativo"

    if cliente_normalizado["status"] not in {"ativo", "inativo", "pendente"}:
        cliente_normalizado["status"] = "ativo"

    return cliente_normalizado


def validar_cliente_para_salvar(cliente: dict[str, str]) -> str:
    if not cliente["nome"]:
        return "Informe o nome do cliente."

    if not cliente["status"]:
        return "Selecione o status do cliente."

    return ""


def normalizar_fornecedor_para_salvar(fornecedor: dict[str, str]) -> dict[str, str]:
    fornecedor_normalizado = dict(fornecedor)

    if not fornecedor_normalizado["status"]:
        fornecedor_normalizado["status"] = "ativo"

    if fornecedor_normalizado["status"] not in {"ativo", "inativo", "pendente"}:
        fornecedor_normalizado["status"] = "ativo"

    return fornecedor_normalizado


def validar_fornecedor_para_salvar(fornecedor: dict[str, str]) -> str:
    if not fornecedor["nome"]:
        return "Informe o nome do fornecedor."

    if not fornecedor["categoria"]:
        return "Selecione a categoria do fornecedor."

    if not fornecedor["status"]:
        return "Selecione o status do fornecedor."

    return ""


def normalizar_funcionario_para_salvar(funcionario: dict[str, str]) -> dict[str, str]:
    funcionario_normalizado = dict(funcionario)

    if not funcionario_normalizado["status"]:
        funcionario_normalizado["status"] = "ativo"

    if funcionario_normalizado["status"] not in {"ativo", "inativo", "pendente"}:
        funcionario_normalizado["status"] = "ativo"

    return funcionario_normalizado


def validar_funcionario_para_salvar(funcionario: dict[str, str]) -> str:
    if not funcionario["nome"]:
        return "Informe o nome do funcionário."

    if not funcionario["cargo"]:
        return "Informe o cargo ou função do funcionário."

    if not funcionario["status"]:
        return "Selecione o status do funcionário."

    return ""

@app.get("/clientes")
def clientes() -> str:
    clientes_lista = listar_clientes()
    return render_template("clientes.html", clientes=clientes_lista)


@app.post("/clientes")
def salvar_cliente() -> Response:
    cliente = {
        "nome": (request.form.get("cliente_nome") or "").strip(),
        "documento": (request.form.get("cliente_documento") or "").strip(),
        "telefone": (request.form.get("cliente_telefone") or "").strip(),
        "cidade": (request.form.get("cliente_cidade") or "").strip(),
        "status": (request.form.get("cliente_status") or "ativo").strip() or "ativo",
        "email": (request.form.get("cliente_email") or "").strip(),
    }

    cliente = normalizar_cliente_para_salvar(cliente)
    erro_validacao = validar_cliente_para_salvar(cliente)

    if erro_validacao:
        return redirect(url_for("clientes", erro=erro_validacao))

    salvar_cliente_db(cliente)
    registrar_atividade_usuario("criacao", "clientes", f"Criou cliente {cliente['nome']}", request.path)

    return redirect(url_for("clientes"))


@app.post("/clientes/rapido")
def salvar_cliente_rapido() -> Response:
    nome = (request.form.get("nome") or request.form.get("cliente_nome") or "").strip()
    documento = (request.form.get("documento") or request.form.get("cliente_documento") or "").strip()
    telefone = (request.form.get("telefone") or request.form.get("cliente_telefone") or "").strip()
    email = (request.form.get("email") or request.form.get("cliente_email") or "").strip()

    if not nome:
        return jsonify({"ok": False, "erro": "Informe o nome do cliente."}), 400

    cliente = {
        "nome": nome,
        "documento": documento,
        "telefone": telefone,
        "cidade": "",
        "status": "ativo",
        "email": email,
    }

    empresa_id = empresa_logada_id()

    with conectar_db() as conn:
        cursor = conn.execute(
            """
            INSERT INTO clientes (
                empresa_id,
                nome,
                documento,
                telefone,
                cidade,
                status,
                email
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                empresa_id,
                cliente["nome"],
                cliente["documento"],
                cliente["telefone"],
                cliente["cidade"],
                cliente["status"],
                cliente["email"],
            ),
        )
        cliente_id = int(cursor.lastrowid)
        conn.commit()

    registrar_atividade_usuario("criacao", "clientes", f"Criou cliente rápido {cliente['nome']}", request.path)

    cliente_resposta = {
        "id": cliente_id,
        "nome": cliente["nome"],
        "documento": cliente["documento"],
        "telefone": cliente["telefone"],
        "email": cliente["email"],
    }

    return jsonify(
        {
            "ok": True,
            "cliente": cliente_resposta,
            "item": cliente_resposta,
        }
    )


@app.get("/clientes/<int:cliente_id>")
def ver_cliente(cliente_id: int) -> str | Response:
    cliente = buscar_cliente_por_id(cliente_id)

    if cliente is None:
        return redirect(url_for("clientes"))

    return render_template("cliente_detalhe.html", cliente=cliente)


@app.get("/clientes/<int:cliente_id>/editar")
def editar_cliente(cliente_id: int) -> str | Response:
    cliente = buscar_cliente_por_id(cliente_id)

    if cliente is None:
        return redirect(url_for("clientes"))

    return render_template("cliente_editar.html", cliente=cliente)


@app.post("/clientes/<int:cliente_id>/editar")
def atualizar_cliente(cliente_id: int) -> Response:
    cliente_atual = buscar_cliente_por_id(cliente_id)

    if cliente_atual is None:
        return redirect(url_for("clientes"))

    cliente = {
        "nome": (request.form.get("cliente_nome") or "").strip(),
        "documento": (request.form.get("cliente_documento") or "").strip(),
        "telefone": (request.form.get("cliente_telefone") or "").strip(),
        "cidade": (request.form.get("cliente_cidade") or "").strip(),
        "status": (request.form.get("cliente_status") or "ativo").strip() or "ativo",
        "email": (request.form.get("cliente_email") or "").strip(),
    }

    cliente = normalizar_cliente_para_salvar(cliente)
    erro_validacao = validar_cliente_para_salvar(cliente)

    if erro_validacao:
        return redirect(url_for("editar_cliente", cliente_id=cliente_id, erro=erro_validacao))

    atualizar_cliente_db(cliente_id, cliente)

    return redirect(url_for("ver_cliente", cliente_id=cliente_id))


@app.post("/clientes/<int:cliente_id>/excluir")
def excluir_cliente(cliente_id: int) -> Response:
    cliente = buscar_cliente_por_id(cliente_id)

    if cliente is not None:
        excluir_cliente_db(cliente_id)

    return redirect(url_for("clientes"))


@app.get("/fornecedores")
def fornecedores() -> str:
    fornecedores_lista = listar_fornecedores()
    return render_template("fornecedores.html", fornecedores=fornecedores_lista)


@app.post("/fornecedores")
def salvar_fornecedor() -> Response:
    fornecedor = {
        "nome": (request.form.get("fornecedor_nome") or "").strip(),
        "documento": (request.form.get("fornecedor_documento") or "").strip(),
        "telefone": (request.form.get("fornecedor_telefone") or "").strip(),
        "cidade": (request.form.get("fornecedor_cidade") or "").strip(),
        "status": (request.form.get("fornecedor_status") or "ativo").strip() or "ativo",
        "email": (request.form.get("fornecedor_email") or "").strip(),
        "categoria": (request.form.get("fornecedor_categoria") or "").strip(),
        "observacoes": (request.form.get("fornecedor_observacoes") or "").strip(),
    }

    fornecedor = normalizar_fornecedor_para_salvar(fornecedor)
    erro_validacao = validar_fornecedor_para_salvar(fornecedor)

    if erro_validacao:
        return redirect(url_for("fornecedores", erro=erro_validacao))

    salvar_fornecedor_db(fornecedor)

    return redirect(url_for("fornecedores"))


@app.get("/fornecedores/<int:fornecedor_id>")
def ver_fornecedor(fornecedor_id: int) -> str | Response:
    fornecedor = buscar_fornecedor_por_id(fornecedor_id)

    if fornecedor is None:
        return redirect(url_for("fornecedores"))

    return render_template("fornecedor_detalhe.html", fornecedor=fornecedor)


@app.get("/fornecedores/<int:fornecedor_id>/editar")
def editar_fornecedor(fornecedor_id: int) -> str | Response:
    fornecedor = buscar_fornecedor_por_id(fornecedor_id)

    if fornecedor is None:
        return redirect(url_for("fornecedores"))

    return render_template("fornecedor_editar.html", fornecedor=fornecedor)


@app.post("/fornecedores/<int:fornecedor_id>/editar")
def atualizar_fornecedor(fornecedor_id: int) -> Response:
    fornecedor_atual = buscar_fornecedor_por_id(fornecedor_id)

    if fornecedor_atual is None:
        return redirect(url_for("fornecedores"))

    fornecedor = {
        "nome": (request.form.get("fornecedor_nome") or "").strip(),
        "documento": (request.form.get("fornecedor_documento") or "").strip(),
        "telefone": (request.form.get("fornecedor_telefone") or "").strip(),
        "cidade": (request.form.get("fornecedor_cidade") or "").strip(),
        "status": (request.form.get("fornecedor_status") or "ativo").strip() or "ativo",
        "email": (request.form.get("fornecedor_email") or "").strip(),
        "categoria": (request.form.get("fornecedor_categoria") or "").strip(),
        "observacoes": (request.form.get("fornecedor_observacoes") or "").strip(),
    }

    fornecedor = normalizar_fornecedor_para_salvar(fornecedor)
    erro_validacao = validar_fornecedor_para_salvar(fornecedor)

    if erro_validacao:
        return redirect(url_for("editar_fornecedor", fornecedor_id=fornecedor_id, erro=erro_validacao))

    atualizar_fornecedor_db(fornecedor_id, fornecedor)

    return redirect(url_for("ver_fornecedor", fornecedor_id=fornecedor_id))


@app.post("/fornecedores/<int:fornecedor_id>/excluir")
def excluir_fornecedor(fornecedor_id: int) -> Response:
    fornecedor = buscar_fornecedor_por_id(fornecedor_id)

    if fornecedor is not None:
        excluir_fornecedor_db(fornecedor_id)

    return redirect(url_for("fornecedores"))


@app.get("/funcionarios")
def funcionarios() -> str:
    funcionarios_lista = listar_funcionarios()
    return render_template("funcionarios.html", funcionarios=funcionarios_lista)


@app.post("/funcionarios")
def salvar_funcionario() -> Response:
    funcionario = {
        "nome": (request.form.get("funcionario_nome") or "").strip(),
        "cpf": (request.form.get("funcionario_cpf") or "").strip(),
        "telefone": (request.form.get("funcionario_telefone") or "").strip(),
        "cidade": (request.form.get("funcionario_cidade") or "").strip(),
        "cargo": (request.form.get("funcionario_cargo") or "").strip(),
        "status": (request.form.get("funcionario_status") or "ativo").strip() or "ativo",
        "email": (request.form.get("funcionario_email") or "").strip(),
        "observacoes": (request.form.get("funcionario_observacoes") or "").strip(),
        "salario_base": (request.form.get("funcionario_salario_base") or "").strip(),
        "inss_percentual": (request.form.get("funcionario_inss_percentual") or "").strip(),
        "fgts_percentual": (request.form.get("funcionario_fgts_percentual") or "").strip(),
        "ferias_percentual": (request.form.get("funcionario_ferias_percentual") or "").strip(),
        "decimo_percentual": (request.form.get("funcionario_decimo_percentual") or "").strip(),
        "beneficios": (request.form.get("funcionario_beneficios") or "").strip(),
        "transporte": (request.form.get("funcionario_transporte") or "").strip(),
        "alimentacao": (request.form.get("funcionario_alimentacao") or "").strip(),
        "outros_custos": (request.form.get("funcionario_outros_custos") or "").strip(),
        "custo_mensal": (request.form.get("funcionario_custo_mensal") or "").strip(),
        "custo_dia": (request.form.get("funcionario_custo_dia") or "").strip(),
        "custo_hora": (request.form.get("funcionario_custo_hora") or "").strip(),
    }

    funcionario = normalizar_funcionario_para_salvar(funcionario)
    erro_validacao = validar_funcionario_para_salvar(funcionario)

    if erro_validacao:
        return redirect(url_for("funcionarios", erro=erro_validacao))

    salvar_funcionario_db(funcionario)

    return redirect(url_for("funcionarios"))


@app.post("/funcionarios/rapido")
def salvar_funcionario_rapido() -> Response:
    nome = (request.form.get("nome") or request.form.get("funcionario_nome") or "").strip()
    cargo = (request.form.get("cargo") or request.form.get("funcionario_cargo") or "").strip()
    telefone = (request.form.get("telefone") or request.form.get("funcionario_telefone") or "").strip()
    email = (request.form.get("email") or request.form.get("funcionario_email") or "").strip()

    if not nome:
        return jsonify({"ok": False, "erro": "Informe o nome do funcionário."}), 400

    funcionario = {
        "nome": nome,
        "cpf": "",
        "telefone": telefone,
        "cidade": "",
        "cargo": cargo or "Mão de obra",
        "status": "ativo",
        "email": email,
        "observacoes": "Cadastro rápido gerado pelo orçamento.",
        "salario_base": (request.form.get("salario_base") or "").strip(),
        "inss_percentual": (request.form.get("inss_percentual") or "").strip(),
        "fgts_percentual": (request.form.get("fgts_percentual") or "").strip(),
        "ferias_percentual": (request.form.get("ferias_percentual") or "").strip(),
        "decimo_percentual": (request.form.get("decimo_percentual") or "").strip(),
        "beneficios": (request.form.get("beneficios") or "").strip(),
        "transporte": (request.form.get("transporte") or "").strip(),
        "alimentacao": (request.form.get("alimentacao") or "").strip(),
        "outros_custos": (request.form.get("outros_custos") or "").strip(),
        "custo_mensal": (request.form.get("custo_mensal") or "").strip(),
        "custo_dia": (request.form.get("custo_dia") or "").strip(),
        "custo_hora": (request.form.get("custo_hora") or "").strip(),
    }

    funcionario = _normalizar_custos_funcionario(funcionario)
    empresa_id = empresa_logada_id()

    with conectar_db() as conn:
        cursor = conn.execute(
            """
            INSERT INTO funcionarios (
                empresa_id,
                nome,
                cpf,
                telefone,
                cidade,
                cargo,
                status,
                email,
                observacoes,
                salario_base,
                inss_percentual,
                fgts_percentual,
                ferias_percentual,
                decimo_percentual,
                beneficios,
                transporte,
                alimentacao,
                outros_custos,
                custo_mensal,
                custo_dia,
                custo_hora
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                empresa_id,
                funcionario["nome"],
                funcionario["cpf"],
                funcionario["telefone"],
                funcionario["cidade"],
                funcionario["cargo"],
                funcionario["status"],
                funcionario["email"],
                funcionario["observacoes"],
                funcionario["salario_base"],
                funcionario["inss_percentual"],
                funcionario["fgts_percentual"],
                funcionario["ferias_percentual"],
                funcionario["decimo_percentual"],
                funcionario["beneficios"],
                funcionario["transporte"],
                funcionario["alimentacao"],
                funcionario["outros_custos"],
                funcionario["custo_mensal"],
                funcionario["custo_dia"],
                funcionario["custo_hora"],
            ),
        )
        funcionario_id = int(cursor.lastrowid)
        conn.commit()

    funcionario_resposta = {
        "id": funcionario_id,
        "nome": funcionario["nome"],
        "cargo": funcionario["cargo"],
        "telefone": funcionario["telefone"],
        "email": funcionario["email"],
        "salario_base": funcionario["salario_base"],
        "custo_mensal": funcionario["custo_mensal"],
        "custo_dia": funcionario["custo_dia"],
        "custo_hora": funcionario["custo_hora"],
    }

    return jsonify(
        {
            "ok": True,
            "funcionario": funcionario_resposta,
            "item": funcionario_resposta,
        }
    )


@app.get("/funcionarios/<int:funcionario_id>")
def ver_funcionario(funcionario_id: int) -> str | Response:
    funcionario = buscar_funcionario_por_id(funcionario_id)

    if funcionario is None:
        return redirect(url_for("funcionarios"))

    return render_template("funcionario_detalhe.html", funcionario=funcionario)


@app.get("/funcionarios/<int:funcionario_id>/editar")
def editar_funcionario(funcionario_id: int) -> str | Response:
    funcionario = buscar_funcionario_por_id(funcionario_id)

    if funcionario is None:
        return redirect(url_for("funcionarios"))

    return render_template("funcionario_editar.html", funcionario=funcionario)


@app.post("/funcionarios/<int:funcionario_id>/editar")
def atualizar_funcionario(funcionario_id: int) -> Response:
    funcionario_atual = buscar_funcionario_por_id(funcionario_id)

    if funcionario_atual is None:
        return redirect(url_for("funcionarios"))

    funcionario = {
        "nome": (request.form.get("funcionario_nome") or "").strip(),
        "cpf": (request.form.get("funcionario_cpf") or "").strip(),
        "telefone": (request.form.get("funcionario_telefone") or "").strip(),
        "cidade": (request.form.get("funcionario_cidade") or "").strip(),
        "cargo": (request.form.get("funcionario_cargo") or "").strip(),
        "status": (request.form.get("funcionario_status") or "ativo").strip() or "ativo",
        "email": (request.form.get("funcionario_email") or "").strip(),
        "observacoes": (request.form.get("funcionario_observacoes") or "").strip(),
        "salario_base": (request.form.get("funcionario_salario_base") or "").strip(),
        "inss_percentual": (request.form.get("funcionario_inss_percentual") or "").strip(),
        "fgts_percentual": (request.form.get("funcionario_fgts_percentual") or "").strip(),
        "ferias_percentual": (request.form.get("funcionario_ferias_percentual") or "").strip(),
        "decimo_percentual": (request.form.get("funcionario_decimo_percentual") or "").strip(),
        "beneficios": (request.form.get("funcionario_beneficios") or "").strip(),
        "transporte": (request.form.get("funcionario_transporte") or "").strip(),
        "alimentacao": (request.form.get("funcionario_alimentacao") or "").strip(),
        "outros_custos": (request.form.get("funcionario_outros_custos") or "").strip(),
        "custo_mensal": (request.form.get("funcionario_custo_mensal") or "").strip(),
        "custo_dia": (request.form.get("funcionario_custo_dia") or "").strip(),
        "custo_hora": (request.form.get("funcionario_custo_hora") or "").strip(),
    }

    funcionario = normalizar_funcionario_para_salvar(funcionario)
    erro_validacao = validar_funcionario_para_salvar(funcionario)

    if erro_validacao:
        return redirect(url_for("editar_funcionario", funcionario_id=funcionario_id, erro=erro_validacao))

    atualizar_funcionario_db(funcionario_id, funcionario)

    return redirect(url_for("ver_funcionario", funcionario_id=funcionario_id))


@app.post("/funcionarios/<int:funcionario_id>/excluir")
def excluir_funcionario(funcionario_id: int) -> Response:
    funcionario = buscar_funcionario_por_id(funcionario_id)

    if funcionario is not None:
        excluir_funcionario_db(funcionario_id)

    return redirect(url_for("funcionarios"))



def normalizar_produto_para_salvar(produto: dict[str, str]) -> dict[str, str]:
    produto_normalizado = dict(produto)

    if not produto_normalizado["estoque_atual"]:
        produto_normalizado["estoque_atual"] = "0"

    if not produto_normalizado["estoque_minimo"]:
        produto_normalizado["estoque_minimo"] = "0"

    if not produto_normalizado["status"]:
        produto_normalizado["status"] = "ativo"

    if produto_normalizado["status"] not in {"ativo", "inativo", "pendente"}:
        produto_normalizado["status"] = "ativo"

    return produto_normalizado


def validar_produto_para_salvar(produto: dict[str, str]) -> str:
    if not produto["nome"]:
        return "Informe o nome do produto."

    if not produto["unidade"]:
        return "Selecione a unidade do produto."

    if not produto["status"]:
        return "Selecione o status do produto."

    return ""


def normalizar_servico_para_salvar(servico: dict[str, str]) -> dict[str, str]:
    servico_normalizado = dict(servico)

    if not servico_normalizado["status"]:
        servico_normalizado["status"] = "ativo"

    if servico_normalizado["status"] not in {"ativo", "inativo", "pendente"}:
        servico_normalizado["status"] = "ativo"

    return servico_normalizado


def validar_servico_para_salvar(servico: dict[str, str]) -> str:
    if not servico["nome"]:
        return "Informe o nome do serviço."

    if not servico["unidade"]:
        return "Selecione a unidade do serviço."

    if not _valor_formulario_positivo(servico["valor_venda"]):
        return "Informe o valor de venda do serviço."

    if not servico["status"]:
        return "Selecione o status do serviço."

    return ""


@app.get("/produtos")
def produtos() -> str:
    produtos_lista = listar_produtos()
    return render_template("produtos.html", produtos=produtos_lista)


@app.post("/produtos")
def salvar_produto() -> Response:
    produto = {
        "nome": (request.form.get("produto_nome") or "").strip(),
        "codigo": (request.form.get("produto_codigo") or "").strip(),
        "categoria": (request.form.get("produto_categoria") or "").strip(),
        "unidade": (request.form.get("produto_unidade") or "").strip(),
        "estoque_atual": (request.form.get("produto_estoque_atual") or "").strip(),
        "estoque_minimo": (request.form.get("produto_estoque_minimo") or "").strip(),
        "preco_custo": (request.form.get("produto_preco_custo") or "").strip(),
        "preco_venda": (request.form.get("produto_preco_venda") or "").strip(),
        "status": (request.form.get("produto_status") or "ativo").strip() or "ativo",
        "observacoes": (request.form.get("produto_observacoes") or "").strip(),
    }

    produto = normalizar_produto_para_salvar(produto)
    erro_validacao = validar_produto_para_salvar(produto)

    if erro_validacao:
        return redirect(url_for("produtos", erro=erro_validacao))

    salvar_produto_db(produto)
    registrar_atividade_usuario("criacao", "produtos", f"Criou produto {produto['nome']}", request.path)

    return redirect(url_for("produtos"))



@app.post("/produtos/rapido")
def salvar_produto_rapido() -> Response:
    nome = (request.form.get("nome") or "").strip()
    preco_venda = (request.form.get("valor_venda") or request.form.get("preco_venda") or "").strip()
    preco_custo = (request.form.get("preco_custo") or request.form.get("custo") or "").strip()
    unidade = (request.form.get("unidade") or "un").strip() or "un"
    categoria = (request.form.get("categoria") or "").strip()
    observacoes = (request.form.get("observacoes") or "").strip()

    if not nome:
        return jsonify({"ok": False, "erro": "Informe o nome do produto."}), 400

    produto = {
        "nome": nome,
        "codigo": "",
        "categoria": categoria,
        "unidade": unidade,
        "estoque_atual": "0",
        "estoque_minimo": "0",
        "preco_custo": preco_custo,
        "preco_venda": preco_venda or preco_custo,
        "status": "ativo",
        "observacoes": observacoes,
    }

    produto = normalizar_produto_para_salvar(produto)
    erro_validacao = validar_produto_para_salvar(produto)

    if erro_validacao:
        return jsonify({"ok": False, "erro": erro_validacao}), 400

    empresa_id = empresa_logada_id()

    with conectar_db() as conn:
        cursor = conn.execute(
            """
            INSERT INTO produtos (
                empresa_id,
                nome,
                codigo,
                categoria,
                unidade,
                estoque_atual,
                estoque_minimo,
                preco_custo,
                preco_venda,
                status,
                observacoes
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                empresa_id,
                produto["nome"],
                produto["codigo"],
                produto["categoria"],
                produto["unidade"],
                produto["estoque_atual"],
                produto["estoque_minimo"],
                produto["preco_custo"],
                produto["preco_venda"],
                produto["status"],
                produto["observacoes"],
            ),
        )
        produto_id = int(cursor.lastrowid)
        conn.commit()

    registrar_atividade_usuario("criacao", "produtos", f"Criou produto rápido {produto['nome']}", request.path)

    return jsonify(
        {
            "ok": True,
            "item": {
                "id": produto_id,
                "nome": produto["nome"],
                "valor": produto["preco_venda"],
                "preco_custo": produto["preco_custo"],
                "preco_venda": produto["preco_venda"],
                "unidade": produto["unidade"],
                "categoria": produto["categoria"],
                "observacoes": produto["observacoes"],
            },
        }
    )


@app.get("/produtos/<int:produto_id>")
def ver_produto(produto_id: int) -> str | Response:
    produto = buscar_produto_por_id(produto_id)

    if produto is None:
        return redirect(url_for("produtos"))

    return render_template("produto_detalhe.html", produto=produto)


@app.get("/produtos/<int:produto_id>/editar")
def editar_produto(produto_id: int) -> str | Response:
    produto = buscar_produto_por_id(produto_id)

    if produto is None:
        return redirect(url_for("produtos"))

    return render_template("produto_editar.html", produto=produto)


@app.post("/produtos/<int:produto_id>/editar")
def atualizar_produto(produto_id: int) -> Response:
    produto_atual = buscar_produto_por_id(produto_id)

    if produto_atual is None:
        return redirect(url_for("produtos"))

    produto = {
        "nome": (request.form.get("produto_nome") or "").strip(),
        "codigo": (request.form.get("produto_codigo") or "").strip(),
        "categoria": (request.form.get("produto_categoria") or "").strip(),
        "unidade": (request.form.get("produto_unidade") or "").strip(),
        "estoque_atual": (request.form.get("produto_estoque_atual") or "").strip(),
        "estoque_minimo": (request.form.get("produto_estoque_minimo") or "").strip(),
        "preco_custo": (request.form.get("produto_preco_custo") or "").strip(),
        "preco_venda": (request.form.get("produto_preco_venda") or "").strip(),
        "status": (request.form.get("produto_status") or "ativo").strip() or "ativo",
        "observacoes": (request.form.get("produto_observacoes") or "").strip(),
    }

    produto = normalizar_produto_para_salvar(produto)
    erro_validacao = validar_produto_para_salvar(produto)

    if erro_validacao:
        return redirect(url_for("editar_produto", produto_id=produto_id, erro=erro_validacao))

    atualizar_produto_db(produto_id, produto)

    return redirect(url_for("ver_produto", produto_id=produto_id))


@app.post("/produtos/<int:produto_id>/excluir")
def excluir_produto(produto_id: int) -> Response:
    produto = buscar_produto_por_id(produto_id)

    if produto is not None:
        excluir_produto_db(produto_id)

    return redirect(url_for("produtos"))


@app.get("/servicos")
def servicos() -> str:
    servicos_lista = listar_servicos()
    return render_template("servicos.html", servicos=servicos_lista)


@app.post("/servicos")
def salvar_servico() -> Response:
    servico = {
        "nome": (request.form.get("servico_nome") or "").strip(),
        "codigo": (request.form.get("servico_codigo") or "").strip(),
        "categoria": (request.form.get("servico_categoria") or "").strip(),
        "unidade": (request.form.get("servico_unidade") or "").strip(),
        "custo": (request.form.get("servico_custo") or "").strip(),
        "valor_venda": (request.form.get("servico_valor_venda") or "").strip(),
        "tempo_estimado": (request.form.get("servico_tempo_estimado") or "").strip(),
        "status": (request.form.get("servico_status") or "ativo").strip() or "ativo",
        "observacoes": (request.form.get("servico_observacoes") or "").strip(),
    }

    servico = normalizar_servico_para_salvar(servico)
    erro_validacao = validar_servico_para_salvar(servico)

    if erro_validacao:
        return redirect(url_for("servicos", erro=erro_validacao))

    salvar_servico_db(servico)
    registrar_atividade_usuario("criacao", "servicos", f"Criou serviço {servico['nome']}", request.path)

    return redirect(url_for("servicos"))



@app.post("/servicos/rapido")
def salvar_servico_rapido() -> Response:
    nome = (request.form.get("nome") or "").strip()
    valor_venda = (request.form.get("valor_venda") or "").strip()
    categoria = (request.form.get("categoria") or "").strip()
    observacoes = (request.form.get("observacoes") or "").strip()

    if not nome:
        return jsonify({"ok": False, "erro": "Informe o nome do serviço."}), 400

    servico = {
        "nome": nome,
        "codigo": "",
        "categoria": categoria,
        "unidade": "un",
        "custo": "",
        "valor_venda": valor_venda,
        "tempo_estimado": "",
        "status": "ativo",
        "observacoes": observacoes,
    }

    servico = normalizar_servico_para_salvar(servico)
    erro_validacao = validar_servico_para_salvar(servico)

    if erro_validacao:
        return jsonify({"ok": False, "erro": erro_validacao}), 400

    empresa_id = empresa_logada_id()

    with conectar_db() as conn:
        cursor = conn.execute(
            """
            INSERT INTO servicos (
                empresa_id,
                nome,
                codigo,
                categoria,
                unidade,
                custo,
                valor_venda,
                tempo_estimado,
                status,
                observacoes
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                empresa_id,
                servico["nome"],
                servico["codigo"],
                servico["categoria"],
                servico["unidade"],
                servico["custo"],
                servico["valor_venda"],
                servico["tempo_estimado"],
                servico["status"],
                servico["observacoes"],
            ),
        )
        servico_id = int(cursor.lastrowid)
        conn.commit()

    registrar_atividade_usuario("criacao", "servicos", f"Criou serviço rápido {servico['nome']}", request.path)

    return jsonify(
        {
            "ok": True,
            "item": {
                "id": servico_id,
                "nome": servico["nome"],
                "valor": servico["valor_venda"],
                "categoria": servico["categoria"],
                "observacoes": servico["observacoes"],
            },
        }
    )


@app.get("/servicos/<int:servico_id>")
def ver_servico(servico_id: int) -> str | Response:
    servico = buscar_servico_por_id(servico_id)

    if servico is None:
        return redirect(url_for("servicos"))

    return render_template("servico_detalhe.html", servico=servico)


@app.get("/servicos/<int:servico_id>/editar")
def editar_servico(servico_id: int) -> str | Response:
    servico = buscar_servico_por_id(servico_id)

    if servico is None:
        return redirect(url_for("servicos"))

    return render_template("servico_editar.html", servico=servico)


@app.post("/servicos/<int:servico_id>/editar")
def atualizar_servico(servico_id: int) -> Response:
    servico_atual = buscar_servico_por_id(servico_id)

    if servico_atual is None:
        return redirect(url_for("servicos"))

    servico = {
        "nome": (request.form.get("servico_nome") or "").strip(),
        "codigo": (request.form.get("servico_codigo") or "").strip(),
        "categoria": (request.form.get("servico_categoria") or "").strip(),
        "unidade": (request.form.get("servico_unidade") or "").strip(),
        "custo": (request.form.get("servico_custo") or "").strip(),
        "valor_venda": (request.form.get("servico_valor_venda") or "").strip(),
        "tempo_estimado": (request.form.get("servico_tempo_estimado") or "").strip(),
        "status": (request.form.get("servico_status") or "ativo").strip() or "ativo",
        "observacoes": (request.form.get("servico_observacoes") or "").strip(),
    }

    servico = normalizar_servico_para_salvar(servico)
    erro_validacao = validar_servico_para_salvar(servico)

    if erro_validacao:
        return redirect(url_for("editar_servico", servico_id=servico_id, erro=erro_validacao))

    atualizar_servico_db(servico_id, servico)

    return redirect(url_for("ver_servico", servico_id=servico_id))


@app.post("/servicos/<int:servico_id>/excluir")
def excluir_servico(servico_id: int) -> Response:
    servico = buscar_servico_por_id(servico_id)

    if servico is not None:
        excluir_servico_db(servico_id)

    return redirect(url_for("servicos"))


@app.get("/financeiro")
@app.get("/financeiro/receber")
@app.get("/financeiro/pagar")
@app.get("/financeiro/fluxo-caixa")
def financeiro() -> str:
    aba = "fluxo-caixa"

    if request.path.endswith("/receber"):
        aba = "receber"
    elif request.path.endswith("/pagar"):
        aba = "pagar"

    painel = montar_painel_financeiro()

    return render_template(
        "financeiro.html",
        aba=aba,
        painel=painel,
        categorias_financeiro=[
            "Fornecedor",
            "Funcionário",
            "Aluguel",
            "Energia",
            "Internet",
            "Material",
            "Imposto",
            "Transporte",
            "Manutenção",
            "Outros",
        ],
    )


@app.post("/financeiro/titulos")
def salvar_financeiro_titulo() -> Response:
    tipo_padrao = (request.form.get("financeiro_tipo") or "receber").strip() or "receber"
    titulo = montar_financeiro_titulo_formulario(tipo_padrao=tipo_padrao)

    if titulo["descricao"] and _converter_valor_brl(titulo["valor"]) > 0:
        salvar_financeiro_titulo_db(titulo)

    if titulo["tipo"] == "pagar":
        return redirect("/financeiro/pagar")

    return redirect("/financeiro/receber")


@app.post("/financeiro/titulos/<int:titulo_id>/baixar")
def baixar_financeiro_titulo(titulo_id: int) -> Response:
    titulo = buscar_financeiro_titulo_por_id(titulo_id)

    if titulo is not None and titulo.get("status") != "cancelado":
        baixar_financeiro_titulo_db(titulo_id)

    return redirect(request.referrer or url_for("financeiro"))


@app.post("/financeiro/titulos/<int:titulo_id>/cancelar")
def cancelar_financeiro_titulo(titulo_id: int) -> Response:
    titulo = buscar_financeiro_titulo_por_id(titulo_id)

    if titulo is not None and titulo.get("status") != "pago":
        cancelar_financeiro_titulo_db(titulo_id)

    return redirect(request.referrer or url_for("financeiro"))


@app.get("/estoque")
@app.get("/estoque/movimentacoes")
@app.get("/estoque/ajustes")
@app.get("/estoque/compras")
def estoque() -> str:
    produtos_lista = listar_produtos()
    fornecedores_lista = listar_fornecedores()
    funcionarios_lista = listar_funcionarios()
    painel = montar_painel_estoque()
    aba = "movimentacoes"

    if request.path.endswith("/ajustes"):
        aba = "ajustes"
    elif request.path.endswith("/compras"):
        aba = "compras"

    produto_selecionado_id: int | None = None
    produto_selecionado = None

    try:
        produto_selecionado_id = int(request.args.get("produto_id") or "")
    except ValueError:
        produto_selecionado_id = None

    if produto_selecionado_id is not None:
        produto_selecionado = buscar_produto_por_id(produto_selecionado_id)

    movimentacoes = listar_estoque_movimentacoes(produto_id=produto_selecionado_id)

    return render_template(
        "estoque.html",
        produtos=produtos_lista,
        fornecedores=fornecedores_lista,
        funcionarios=funcionarios_lista,
        movimentacoes=movimentacoes,
        painel=painel,
        aba=aba,
        produto_selecionado=produto_selecionado,
        produto_selecionado_id=produto_selecionado_id,
    )


@app.post("/estoque/movimentar")
def movimentar_estoque() -> Response:
    movimentacao_form = montar_estoque_formulario()

    if not movimentacao_form["produto_id"]:
        return redirect(url_for("estoque", erro="Selecione um produto para movimentar o estoque."))

    if not _valor_formulario_positivo(movimentacao_form["quantidade"]):
        return redirect(url_for("estoque", erro="Informe uma quantidade maior que zero."))

    if not movimentacao_form["motivo"]:
        return redirect(url_for("estoque", erro="Informe o motivo da movimentação."))

    if not movimentacao_form["responsavel"]:
        return redirect(url_for("estoque", erro="Selecione o responsável pela movimentação."))

    try:
        produto_id = int(movimentacao_form["produto_id"])
    except ValueError:
        return redirect(url_for("estoque", erro="Produto inválido para movimentação."))

    produto = buscar_produto_por_id(produto_id)

    if produto is None:
        return redirect(url_for("estoque", erro="Produto não encontrado."))

    tipo = movimentacao_form["tipo"]

    if tipo not in {"entrada", "saida", "ajuste"}:
        tipo = "entrada"

    quantidade = _converter_valor_brl(movimentacao_form["quantidade"])
    saldo_anterior_numero = _converter_valor_brl(produto.get("estoque_atual"))

    if tipo == "entrada":
        saldo_atual_numero = saldo_anterior_numero + quantidade
    elif tipo == "saida":
        saldo_atual_numero = saldo_anterior_numero - quantidade
    else:
        saldo_atual_numero = quantidade

    movimentacao = {
        "produto_id": str(produto_id),
        "produto_nome": str(produto.get("nome") or ""),
        "tipo": tipo,
        "quantidade": _formatar_numero_estoque(quantidade),
        "saldo_anterior": _formatar_numero_estoque(saldo_anterior_numero),
        "saldo_atual": _formatar_numero_estoque(saldo_atual_numero),
        "motivo": movimentacao_form["motivo"],
        "documento": movimentacao_form["documento"],
        "responsavel": movimentacao_form["responsavel"],
        "observacoes": movimentacao_form["observacoes"],
    }

    salvar_estoque_movimentacao_db(movimentacao)

    if tipo == "ajuste":
        return redirect(url_for("estoque") + "/ajustes")

    return redirect(url_for("estoque") + f"?produto_id={produto_id}#historico")


@app.post("/estoque/comprar")
def comprar_produto_estoque() -> Response:
    produto_id_texto = (request.form.get("compra_produto_id") or "").strip()
    quantidade_texto = (request.form.get("compra_quantidade") or "").strip()
    responsavel = (request.form.get("compra_responsavel") or "").strip()

    if not produto_id_texto:
        return redirect(url_for("estoque") + "/compras")

    if not _valor_formulario_positivo(quantidade_texto):
        return redirect(url_for("estoque") + "/compras")

    if not responsavel:
        return redirect(url_for("estoque") + "/compras")

    try:
        produto_id = int(produto_id_texto)
    except ValueError:
        return redirect(url_for("estoque") + "/compras")

    produto = buscar_produto_por_id(produto_id)

    if produto is None:
        return redirect(url_for("estoque") + "/compras")

    quantidade = _converter_valor_brl(quantidade_texto)
    saldo_anterior_numero = _converter_valor_brl(produto.get("estoque_atual"))
    saldo_atual_numero = saldo_anterior_numero + quantidade

    fornecedor = (request.form.get("compra_fornecedor") or "").strip()
    documento = (request.form.get("compra_documento") or "").strip()
    responsavel = (request.form.get("compra_responsavel") or "").strip()
    valor_custo = (request.form.get("compra_valor_custo") or "").strip()
    observacoes = (request.form.get("compra_observacoes") or "").strip()

    motivo = "Compra de produto"

    if fornecedor:
        motivo += f" - {fornecedor}"

    movimentacao = {
        "produto_id": str(produto_id),
        "produto_nome": str(produto.get("nome") or ""),
        "tipo": "entrada",
        "quantidade": _formatar_numero_estoque(quantidade),
        "saldo_anterior": _formatar_numero_estoque(saldo_anterior_numero),
        "saldo_atual": _formatar_numero_estoque(saldo_atual_numero),
        "motivo": motivo,
        "documento": documento,
        "responsavel": responsavel,
        "observacoes": f"Valor de custo: {valor_custo}\n{observacoes}".strip(),
    }

    salvar_estoque_movimentacao_db(movimentacao)

    return redirect(url_for("estoque") + "/compras")


@app.get("/ordens-servico/painel")
def painel_ordens_servico() -> str:
    painel = montar_painel_ordens_servico()

    return render_template(
        "ordens_servico_painel.html",
        painel=painel,
    )


@app.get("/ordens-servico")
def ordens_servico() -> str:
    ordens_servico_lista = listar_ordens_servico()
    clientes_lista = listar_clientes()
    funcionarios_lista = listar_funcionarios()
    produtos_lista = listar_produtos()
    servicos_lista = listar_servicos()
    proximo_numero = proximo_numero_ordem_servico()

    return render_template(
        "ordens_servico.html",
        ordens_servico=ordens_servico_lista,
        clientes=clientes_lista,
        funcionarios=funcionarios_lista,
        produtos=produtos_lista,
        servicos=servicos_lista,
        proximo_numero=proximo_numero,
    )


@app.post("/ordens-servico")
def salvar_ordem_servico() -> Response:
    ordem_servico = montar_ordem_servico_formulario(numero_padrao=proximo_numero_ordem_servico())
    itens = montar_ordem_servico_itens_formulario()
    erro_validacao = validar_ordem_servico_para_salvar(ordem_servico, itens)

    if erro_validacao:
        return redirect(url_for("ordens_servico", erro=erro_validacao))

    nova_ordem_servico_id = salvar_ordem_servico_db(ordem_servico, itens)
    atualizar_fotos_equipamento_os_formulario(nova_ordem_servico_id)
    registrar_atividade_usuario("criacao", "ordens_servico", f"Criou OS {ordem_servico.get('numero') or nova_ordem_servico_id}", request.path)

    return redirect(url_for("ordens_servico"))


@app.get("/ordens-servico/<int:ordem_servico_id>")
def ver_ordem_servico(ordem_servico_id: int) -> str | Response:
    ordem_servico = buscar_ordem_servico_por_id(ordem_servico_id)

    if ordem_servico is None:
        return redirect(url_for("ordens_servico"))

    itens = listar_ordem_servico_itens(ordem_servico_id)
    itens_produtos = [item for item in itens if item["tipo_item"] == "produto"]
    itens_servicos = [item for item in itens if item["tipo_item"] == "servico"]
    acompanhamentos = anexar_itens_aos_acompanhamentos(listar_acompanhamentos_ordem_servico(ordem_servico_id))
    fotos_equipamento = listar_fotos_equipamento_os(ordem_servico_id)
    equipamentos_os = montar_equipamentos_ordem_servico(ordem_servico)
    fotos_por_equipamento = agrupar_fotos_por_equipamento(fotos_equipamento)
    token_gerado = (request.args.get("link") or "").strip()
    acompanhamento_url_gerada = montar_url_acompanhamento_os(token_gerado)
    acompanhamento_mensagem = (request.args.get("mensagem") or "").strip()
    acompanhamento_erro = (request.args.get("erro") or "").strip()

    return render_template(
        "ordem_servico_detalhe.html",
        ordem_servico=ordem_servico,
        itens=itens,
        itens_produtos=itens_produtos,
        itens_servicos=itens_servicos,
        acompanhamentos=acompanhamentos,
        equipamentos_os=equipamentos_os,
        fotos_equipamento=fotos_equipamento,
        fotos_por_equipamento=fotos_por_equipamento,
        acompanhamento_url_gerada=acompanhamento_url_gerada,
        acompanhamento_mensagem=acompanhamento_mensagem,
        acompanhamento_erro=acompanhamento_erro,
    )


@app.get("/ordens-servico/<int:ordem_servico_id>/imprimir/a4")
def imprimir_ordem_servico_a4(ordem_servico_id: int) -> str | Response:
    ordem_servico = buscar_ordem_servico_por_id(ordem_servico_id)

    if ordem_servico is None:
        return redirect(url_for("ordens_servico"))

    itens = listar_ordem_servico_itens(ordem_servico_id)
    itens_produtos = [item for item in itens if item["tipo_item"] == "produto"]
    itens_servicos = [item for item in itens if item["tipo_item"] == "servico"]
    acompanhamentos = anexar_itens_aos_acompanhamentos(listar_acompanhamentos_ordem_servico(ordem_servico_id))
    fotos_equipamento = listar_fotos_equipamento_os(ordem_servico_id)
    equipamentos_os = montar_equipamentos_ordem_servico(ordem_servico)
    fotos_por_equipamento = agrupar_fotos_por_equipamento(fotos_equipamento)
    contexto_impressao = montar_contexto_impressao(ordem_servico.get("cliente"))

    return render_template(
        "ordem_servico_imprimir_a4.html",
        ordem_servico=ordem_servico,
        itens=itens,
        itens_produtos=itens_produtos,
        itens_servicos=itens_servicos,
        acompanhamentos=acompanhamentos,
        equipamentos_os=equipamentos_os,
        fotos_equipamento=fotos_equipamento,
        fotos_por_equipamento=fotos_por_equipamento,
        empresa=contexto_impressao["empresa"],
        loja=contexto_impressao["loja"],
        cliente=contexto_impressao["cliente"],
    )


@app.get("/ordens-servico/<int:ordem_servico_id>/imprimir/cupom")
def imprimir_ordem_servico_cupom(ordem_servico_id: int) -> str | Response:
    ordem_servico = buscar_ordem_servico_por_id(ordem_servico_id)

    if ordem_servico is None:
        return redirect(url_for("ordens_servico"))

    itens = listar_ordem_servico_itens(ordem_servico_id)
    itens_produtos = [item for item in itens if item["tipo_item"] == "produto"]
    itens_servicos = [item for item in itens if item["tipo_item"] == "servico"]
    contexto_impressao = montar_contexto_impressao(ordem_servico.get("cliente"))

    return render_template(
        "ordem_servico_imprimir_cupom.html",
        ordem_servico=ordem_servico,
        itens=itens,
        itens_produtos=itens_produtos,
        itens_servicos=itens_servicos,
        empresa=contexto_impressao["empresa"],
        loja=contexto_impressao["loja"],
        cliente=contexto_impressao["cliente"],
    )



@app.get("/ordens-servico/<int:ordem_servico_id>/gerar/acompanhamento")
def gerar_link_acompanhamento_ordem_servico(ordem_servico_id: int) -> Response:
    sucesso, mensagem, acompanhamento = gerar_acompanhamento_diario_os(ordem_servico_id)

    if not sucesso or acompanhamento is None:
        return redirect(url_for("ver_ordem_servico", ordem_servico_id=ordem_servico_id, erro=mensagem))

    return redirect(
        url_for(
            "ver_ordem_servico",
            ordem_servico_id=ordem_servico_id,
            link=str(acompanhamento.get("token") or ""),
            mensagem=mensagem,
        )
    )


@app.route("/os/acompanhamento/<token>", methods=["GET", "POST"])
def acompanhamento_os_publico(token: str) -> str:
    acompanhamento = buscar_acompanhamento_os_por_token(token)
    mensagem = ""
    erro = ""
    funcionarios_acompanhamento: list[dict[str, Any]] = []
    produtos_acompanhamento: list[dict[str, Any]] = []
    servicos_cadastrados_acompanhamento: list[dict[str, Any]] = []
    equipe_acompanhamento: list[dict[str, Any]] = []
    materiais_acompanhamento: list[dict[str, Any]] = []
    servicos_acompanhamento: list[dict[str, Any]] = []

    if acompanhamento is None:
        return render_template(
            "os_acompanhamento_publico.html",
            acompanhamento=None,
            bloqueado=True,
            erro="Link de acompanhamento não encontrado.",
            mensagem="",
            funcionarios=[],
            produtos=[],
            servicos_cadastrados=[],
            equipe_acompanhamento=[],
            materiais_acompanhamento=[],
            servicos_acompanhamento=[],
        )

    empresa_acompanhamento_id = int(acompanhamento.get("empresa_id") or 0)
    acompanhamento_id = int(acompanhamento.get("id") or 0)

    if empresa_acompanhamento_id > 0:
        funcionarios_acompanhamento = listar_funcionarios_acompanhamento_publico(empresa_acompanhamento_id)
        produtos_acompanhamento = listar_produtos_acompanhamento_publico(empresa_acompanhamento_id)
        servicos_cadastrados_acompanhamento = listar_servicos_acompanhamento_publico(empresa_acompanhamento_id)

    if acompanhamento_id > 0:
        itens_salvos = listar_itens_acompanhamento(acompanhamento_id, empresa_acompanhamento_id)
        equipe_acompanhamento = itens_salvos["equipe"]
        materiais_acompanhamento = itens_salvos["materiais"]
        servicos_acompanhamento = itens_salvos["servicos"]

    bloqueado = False

    if acompanhamento_os_esta_expirado(acompanhamento):
        bloqueado = True
        erro = "Este link de acompanhamento expirou. Solicite um novo link."
    elif str(acompanhamento.get("os_status") or "").strip().lower() != "andamento":
        bloqueado = True
        erro = "Esta Ordem de Serviço não está disponível para acompanhamento diário."
    elif str(acompanhamento.get("status_dia") or "").strip().lower() == "finalizado":
        bloqueado = True
        mensagem = "A atividade do dia já foi finalizada."

    if request.method == "POST" and not bloqueado:
        acao = str(request.form.get("acao") or "salvar").strip().lower()
        finalizar = acao == "finalizar"
        dados = {
            "responsavel": str(request.form.get("responsavel") or "").strip(),
            "atividades_previstas": str(request.form.get("atividades_previstas") or "").strip(),
            "equipe_prevista": "",
            "materiais_previstos": "",
            "atividades_executadas": str(request.form.get("atividades_executadas") or "").strip(),
            "equipe_real": "",
            "materiais_utilizados": "",
            "observacoes": str(request.form.get("observacoes") or "").strip(),
        }
        itens_formulario = montar_itens_acompanhamento_formulario(request.form)

        atualizado = atualizar_acompanhamento_os_publico(token, dados, finalizar=finalizar, itens=itens_formulario)

        if atualizado:
            mensagem = "Acompanhamento finalizado com sucesso." if finalizar else "Acompanhamento salvo com sucesso."
            acompanhamento = buscar_acompanhamento_os_por_token(token) or acompanhamento
            bloqueado = finalizar
            acompanhamento_id = int(acompanhamento.get("id") or 0)
            empresa_acompanhamento_id = int(acompanhamento.get("empresa_id") or 0)
            itens_salvos = listar_itens_acompanhamento(acompanhamento_id, empresa_acompanhamento_id)
            equipe_acompanhamento = itens_salvos["equipe"]
            materiais_acompanhamento = itens_salvos["materiais"]
            servicos_acompanhamento = itens_salvos["servicos"]
        else:
            erro = "Não foi possível salvar o acompanhamento. Verifique se o link ainda está ativo."
            acompanhamento = buscar_acompanhamento_os_por_token(token) or acompanhamento

    return render_template(
        "os_acompanhamento_publico.html",
        acompanhamento=acompanhamento,
        bloqueado=bloqueado,
        erro=erro,
        mensagem=mensagem,
        funcionarios=funcionarios_acompanhamento,
        produtos=produtos_acompanhamento,
        servicos_cadastrados=servicos_cadastrados_acompanhamento,
        equipe_acompanhamento=equipe_acompanhamento,
        materiais_acompanhamento=materiais_acompanhamento,
        servicos_acompanhamento=servicos_acompanhamento,
    )


@app.get("/ordens-servico/<int:ordem_servico_id>/gerar/copia")
def gerar_copia_ordem_servico(ordem_servico_id: int) -> Response:
    nova_ordem_servico_id = copiar_ordem_servico_db(ordem_servico_id)

    if nova_ordem_servico_id is None:
        return redirect(url_for("ordens_servico"))

    return redirect(url_for("editar_ordem_servico", ordem_servico_id=nova_ordem_servico_id))


@app.get("/ordens-servico/<int:ordem_servico_id>/editar")
def editar_ordem_servico(ordem_servico_id: int) -> str | Response:
    ordem_servico = buscar_ordem_servico_por_id(ordem_servico_id)

    if ordem_servico is None:
        return redirect(url_for("ordens_servico"))

    itens = listar_ordem_servico_itens(ordem_servico_id)
    clientes_lista = listar_clientes()
    funcionarios_lista = listar_funcionarios()
    produtos_lista = listar_produtos()
    servicos_lista = listar_servicos()
    fotos_equipamento = listar_fotos_equipamento_os(ordem_servico_id)
    equipamentos_os = montar_equipamentos_ordem_servico(ordem_servico)
    fotos_por_equipamento = agrupar_fotos_por_equipamento(fotos_equipamento)

    return render_template(
        "ordem_servico_editar.html",
        ordem_servico=ordem_servico,
        itens=itens,
        clientes=clientes_lista,
        funcionarios=funcionarios_lista,
        produtos=produtos_lista,
        servicos=servicos_lista,
        equipamentos_os=equipamentos_os,
        fotos_equipamento=fotos_equipamento,
        fotos_por_equipamento=fotos_por_equipamento,
    )


@app.post("/ordens-servico/<int:ordem_servico_id>/editar")
def atualizar_ordem_servico(ordem_servico_id: int) -> Response:
    ordem_servico_atual = buscar_ordem_servico_por_id(ordem_servico_id)

    if ordem_servico_atual is None:
        return redirect(url_for("ordens_servico"))

    ordem_servico = montar_ordem_servico_formulario(numero_padrao=str(ordem_servico_atual["numero"] or ""))
    itens = montar_ordem_servico_itens_formulario()
    erro_validacao = validar_ordem_servico_para_salvar(ordem_servico, itens)

    if erro_validacao:
        return redirect(url_for("editar_ordem_servico", ordem_servico_id=ordem_servico_id, erro=erro_validacao))

    atualizar_ordem_servico_db(ordem_servico_id, ordem_servico, itens)
    atualizar_fotos_equipamento_os_formulario(ordem_servico_id)

    return redirect(url_for("ver_ordem_servico", ordem_servico_id=ordem_servico_id))


@app.post("/ordens-servico/<int:ordem_servico_id>/excluir")
def excluir_ordem_servico(ordem_servico_id: int) -> Response:
    ordem_servico = buscar_ordem_servico_por_id(ordem_servico_id)

    if ordem_servico is not None:
        excluir_ordem_servico_db(ordem_servico_id)

    return redirect(url_for("ordens_servico"))




def buscar_caixa_aberto_db() -> dict[str, Any] | None:
    empresa_id = empresa_logada_id()

    with conectar_db() as conn:
        row = conn.execute(
            """
            SELECT
                id,
                empresa_id,
                usuario_id,
                responsavel,
                valor_abertura,
                valor_fechamento,
                status,
                aberto_em,
                fechado_em,
                observacoes,
                criado_em
            FROM caixa_aberturas
            WHERE empresa_id = ?
              AND status = 'aberto'
            ORDER BY id DESC
            LIMIT 1
            """,
            (empresa_id,),
        ).fetchone()

    if row is None:
        return None

    return dict(row)


def abrir_caixa_db(valor_abertura: str, responsavel: str, gerar_recebimento: bool = False) -> int:
    empresa_id = empresa_logada_id()
    usuario_id = usuario_logado_id()
    valor_abertura_formatado = _formatar_moeda_brl(_converter_valor_brl(valor_abertura))
    aberto_em = agora_empresa().isoformat(timespec="seconds")

    with conectar_db() as conn:
        cursor = conn.execute(
            """
            INSERT INTO caixa_aberturas (
                empresa_id,
                usuario_id,
                responsavel,
                valor_abertura,
                valor_fechamento,
                status,
                aberto_em,
                fechado_em,
                observacoes
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                empresa_id,
                usuario_id,
                responsavel,
                valor_abertura_formatado,
                "",
                "aberto",
                aberto_em,
                "",
                "Abertura de caixa do PDV.",
            ),
        )
        caixa_id = int(cursor.lastrowid)

        conn.execute(
            """
            INSERT INTO caixa_movimentacoes (
                empresa_id,
                caixa_id,
                venda_id,
                tipo,
                descricao,
                forma_pagamento,
                valor
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                empresa_id,
                caixa_id,
                None,
                "abertura",
                "Abertura de caixa",
                "Dinheiro",
                valor_abertura_formatado,
            ),
        )

        conn.commit()

    if gerar_recebimento and _converter_valor_brl(valor_abertura_formatado) > 0:
        salvar_financeiro_titulo_db(
            {
                "tipo": "receber",
                "descricao": "Abertura de caixa PDV",
                "pessoa": responsavel or "Balcão",
                "categoria": "Caixa",
                "origem": "caixa",
                "origem_id": str(caixa_id),
                "documento": f"Caixa Nº {caixa_id}",
                "data_emissao": hoje_empresa().isoformat(),
                "data_vencimento": hoje_empresa().isoformat(),
                "data_pagamento": hoje_empresa().isoformat(),
                "valor": valor_abertura_formatado,
                "forma_pagamento": "Dinheiro",
                "status": "pago",
                "observacoes": "Recebimento opcional gerado pela abertura de caixa.",
            }
        )

    return caixa_id


def fechar_caixa_db(valor_fechamento: str, observacoes: str = "") -> bool:
    caixa = buscar_caixa_aberto_db()

    if caixa is None:
        return False

    empresa_id = empresa_logada_id()
    valor_formatado = _formatar_moeda_brl(_converter_valor_brl(valor_fechamento))

    with conectar_db() as conn:
        conn.execute(
            """
            UPDATE caixa_aberturas
            SET
                valor_fechamento = ?,
                status = 'fechado',
                fechado_em = ?,
                observacoes = ?
            WHERE id = ?
              AND empresa_id = ?
            """,
            (
                valor_formatado,
                agora_empresa().isoformat(timespec="seconds"),
                observacoes,
                int(caixa["id"]),
                empresa_id,
            ),
        )
        conn.commit()

    return True


def registrar_caixa_movimentacao_db(caixa_id: int, venda_id: int | None, tipo: str, descricao: str, forma_pagamento: str, valor: str) -> None:
    empresa_id = empresa_logada_id()

    with conectar_db() as conn:
        conn.execute(
            """
            INSERT INTO caixa_movimentacoes (
                empresa_id,
                caixa_id,
                venda_id,
                tipo,
                descricao,
                forma_pagamento,
                valor
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                empresa_id,
                caixa_id,
                venda_id,
                tipo,
                descricao,
                forma_pagamento,
                valor,
            ),
        )
        conn.commit()


def listar_caixa_movimentacoes(caixa_id: int) -> list[dict[str, Any]]:
    empresa_id = empresa_logada_id()

    with conectar_db() as conn:
        rows = conn.execute(
            """
            SELECT
                id,
                empresa_id,
                caixa_id,
                venda_id,
                tipo,
                descricao,
                forma_pagamento,
                valor,
                criado_em
            FROM caixa_movimentacoes
            WHERE empresa_id = ?
              AND caixa_id = ?
            ORDER BY id ASC
            """,
            (empresa_id, caixa_id),
        ).fetchall()

    return [dict(row) for row in rows]


def _normalizar_item_pdv(item: dict[str, Any]) -> dict[str, str] | None:
    tipo_item = str(item.get("tipo_item") or "produto").strip()
    if tipo_item not in {"produto", "servico"}:
        tipo_item = "produto"

    descricao = str(item.get("descricao") or "").strip()
    if not descricao:
        return None

    quantidade = _converter_valor_brl(item.get("quantidade"))
    valor_unitario = _converter_valor_brl(item.get("valor_unitario"))
    desconto = _converter_valor_brl(item.get("desconto"))

    if quantidade <= 0:
        quantidade = 1.0

    if valor_unitario <= 0:
        return None

    subtotal = max((quantidade * valor_unitario) - desconto, 0)

    return {
        "tipo_item": tipo_item,
        "descricao": descricao,
        "detalhes": str(item.get("detalhes") or "Balcão / PDV").strip(),
        "quantidade": _formatar_numero_estoque(quantidade),
        "valor_unitario": _formatar_moeda_brl(valor_unitario),
        "desconto": _formatar_moeda_brl(desconto),
        "subtotal": _formatar_moeda_brl(subtotal),
    }


def normalizar_carrinho_pdv_json(carrinho_json: str) -> list[dict[str, str]]:
    try:
        dados = json.loads(carrinho_json or "[]")
    except json.JSONDecodeError:
        return []

    if not isinstance(dados, list):
        return []

    itens: list[dict[str, str]] = []

    for item in dados:
        if not isinstance(item, dict):
            continue

        item_normalizado = _normalizar_item_pdv(item)
        if item_normalizado is not None:
            itens.append(item_normalizado)

    return itens


def montar_resumo_pdv(itens: list[dict[str, str]], desconto_valor: str = "0,00", desconto_percentual: str = "0,00", valor_pago: str = "0,00") -> dict[str, Any]:
    subtotal_produtos = sum(_converter_valor_brl(item["subtotal"]) for item in itens if item["tipo_item"] == "produto")
    subtotal_servicos = sum(_converter_valor_brl(item["subtotal"]) for item in itens if item["tipo_item"] == "servico")
    subtotal = subtotal_produtos + subtotal_servicos
    desconto_reais = _converter_valor_brl(desconto_valor)
    desconto_percentual_numero = _converter_valor_brl(desconto_percentual)
    desconto_percentual_valor = subtotal * (desconto_percentual_numero / 100)
    desconto_total = max(desconto_reais + desconto_percentual_valor, 0)
    total = max(subtotal - desconto_total, 0)
    valor_pago_numero = _converter_valor_brl(valor_pago)
    troco = max(valor_pago_numero - total, 0)

    return {
        "subtotal_produtos": subtotal_produtos,
        "subtotal_servicos": subtotal_servicos,
        "subtotal": subtotal,
        "desconto_total": desconto_total,
        "total": total,
        "valor_pago": valor_pago_numero,
        "troco": troco,
        "subtotal_produtos_formatado": _formatar_moeda_brl(subtotal_produtos),
        "subtotal_servicos_formatado": _formatar_moeda_brl(subtotal_servicos),
        "subtotal_formatado": _formatar_moeda_brl(subtotal),
        "desconto_total_formatado": _formatar_moeda_brl(desconto_total),
        "total_formatado": _formatar_moeda_brl(total),
        "valor_pago_formatado": _formatar_moeda_brl(valor_pago_numero),
        "troco_formatado": _formatar_moeda_brl(troco),
    }


def gerar_recebimento_pdv_pago_db(venda_id: int, venda: dict[str, str]) -> None:
    valor_total = _converter_valor_brl(venda.get("valor_total"))

    if valor_total <= 0:
        return

    numero_venda = str(venda.get("numero") or venda_id).strip() or str(venda_id)
    data_venda = str(venda.get("data") or hoje_empresa().isoformat()).strip()

    salvar_financeiro_titulo_db(
        {
            "tipo": "receber",
            "descricao": f"Recebimento PDV venda Nº {numero_venda}",
            "pessoa": str(venda.get("cliente") or "Consumidor").strip(),
            "categoria": "Venda balcão",
            "origem": "venda_pdv",
            "origem_id": str(venda_id),
            "documento": f"Venda PDV Nº {numero_venda}",
            "data_emissao": data_venda,
            "data_vencimento": data_venda,
            "data_pagamento": hoje_empresa().isoformat(),
            "valor": _formatar_moeda_brl(valor_total),
            "forma_pagamento": str(venda.get("forma_pagamento") or "").strip(),
            "status": "pago",
            "observacoes": "Recebimento gerado automaticamente pela venda de balcão.",
        }
    )




def listar_produtos_pdv() -> list[dict[str, Any]]:
    produtos = [
        produto
        for produto in listar_produtos()
        if str(produto.get("status") or "ativo").strip().lower() == "ativo"
    ]

    produtos.sort(key=lambda item: str(item.get("nome") or "").casefold())
    return produtos


@app.get("/vendas/balcao/abrir-caixa")
def venda_balcao_abrir_caixa() -> Response:
    return redirect(url_for("venda_balcao"))


@app.post("/vendas/balcao/abrir-caixa")
def venda_balcao_salvar_abertura_caixa() -> Response:
    valor_abertura = (request.form.get("valor_abertura") or "0,00").strip()
    responsavel = (request.form.get("responsavel") or session.get("usuario_nome") or "").strip()
    gerar_recebimento = bool(request.form.get("gerar_recebimento"))

    abrir_caixa_db(valor_abertura, responsavel, gerar_recebimento)

    return redirect(url_for("venda_balcao"))


@app.get("/vendas/balcao")
def venda_balcao() -> str:
    caixa_aberto = buscar_caixa_aberto_db()
    movimentacoes_caixa: list[dict[str, Any]] = []
    total_entradas_caixa = 0.0

    if caixa_aberto is not None:
        movimentacoes_caixa = listar_caixa_movimentacoes(int(caixa_aberto["id"]))
        total_entradas_caixa = sum(
            _converter_valor_brl(item.get("valor"))
            for item in movimentacoes_caixa
            if str(item.get("tipo") or "") in {"abertura", "venda", "entrada"}
        )

    return render_template(
        "venda_balcao.html",
        caixa=caixa_aberto,
        caixa_aberto=caixa_aberto,
        movimentacoes_caixa=movimentacoes_caixa,
        total_entradas_caixa=_formatar_moeda_brl(total_entradas_caixa),
        clientes=listar_clientes(),
        funcionarios=listar_funcionarios(),
        produtos=listar_produtos_pdv(),
    )


@app.post("/vendas/balcao/pagamento")
def venda_balcao_pagamento() -> str | Response:
    caixa_aberto = buscar_caixa_aberto_db()

    if caixa_aberto is None:
        return redirect(url_for("venda_balcao"))

    carrinho_json = request.form.get("carrinho_json") or "[]"
    itens = normalizar_carrinho_pdv_json(carrinho_json)

    itens = [
        item
        for item in itens
        if str(item.get("tipo_item") or "produto").strip() == "produto"
    ]

    if not itens:
        return redirect(url_for("venda_balcao", erro="Adicione pelo menos um produto para continuar."))

    session["pdv_carrinho"] = itens
    session["pdv_cliente"] = (request.form.get("cliente") or "AO CONSUMIDOR").strip() or "AO CONSUMIDOR"
    session["pdv_responsavel"] = (request.form.get("responsavel") or session.get("usuario_nome") or "").strip()

    resumo = montar_resumo_pdv(itens)

    return render_template(
        "venda_balcao_pagamento.html",
        caixa=caixa_aberto,
        itens=itens,
        resumo=resumo,
        cliente=session["pdv_cliente"],
        responsavel=session["pdv_responsavel"],
    )


@app.get("/vendas/balcao/pagamento")
def venda_balcao_pagamento_get() -> str | Response:
    caixa_aberto = buscar_caixa_aberto_db()

    if caixa_aberto is None:
        return redirect(url_for("venda_balcao"))

    itens = session.get("pdv_carrinho") or []

    if not itens:
        return redirect(url_for("venda_balcao"))

    resumo = montar_resumo_pdv(itens)

    return render_template(
        "venda_balcao_pagamento.html",
        caixa=caixa_aberto,
        itens=itens,
        resumo=resumo,
        cliente=session.get("pdv_cliente") or "AO CONSUMIDOR",
        responsavel=session.get("pdv_responsavel") or "",
    )


@app.post("/vendas/balcao/finalizar")
def venda_balcao_finalizar() -> Response:
    caixa_aberto = buscar_caixa_aberto_db()

    if caixa_aberto is None:
        return redirect(url_for("venda_balcao"))

    itens = session.get("pdv_carrinho") or []

    if not itens:
        return redirect(url_for("venda_balcao"))

    forma_pagamento = (request.form.get("forma_pagamento") or "").strip()
    desconto_valor = (request.form.get("desconto_valor") or "0,00").strip()
    desconto_percentual = (request.form.get("desconto_percentual") or "0,00").strip()
    valor_pago = (request.form.get("valor_pago") or "0,00").strip()

    if not forma_pagamento:
        return redirect(url_for("venda_balcao_pagamento_get"))

    resumo = montar_resumo_pdv(itens, desconto_valor, desconto_percentual, valor_pago)
    cliente = str(session.get("pdv_cliente") or "AO CONSUMIDOR").strip() or "AO CONSUMIDOR"
    responsavel = str(session.get("pdv_responsavel") or session.get("usuario_nome") or "").strip()

    venda = {
        "numero": proximo_numero_venda(),
        "cliente": cliente,
        "responsavel": responsavel,
        "data": hoje_empresa().isoformat(),
        "prazo_entrega": "imediato",
        "canal_venda": "Balcão / PDV",
        "centro_custo": "Balcão",
        "tipo": "produto",
        "status": "concretizada",
        "total_produtos": resumo["subtotal_produtos_formatado"],
        "total_servicos": "0,00",
        "desconto_valor": _formatar_moeda_brl(_converter_valor_brl(desconto_valor)),
        "desconto_percentual": _formatar_moeda_brl(_converter_valor_brl(desconto_percentual)),
        "valor_total": resumo["total_formatado"],
        "forma_pagamento": forma_pagamento,
        "observacoes": f"Venda balcão. Valor recebido: R$ {resumo['valor_pago_formatado']}. Troco: R$ {resumo['troco_formatado']}.",
        "observacoes_internas": f"Caixa Nº {caixa_aberto['id']}",
    }

    venda_id = salvar_venda_db(venda, itens)
    baixar_estoque_por_venda_db(venda_id, venda, itens)
    gerar_recebimento_pdv_pago_db(venda_id, venda)
    registrar_caixa_movimentacao_db(
        int(caixa_aberto["id"]),
        venda_id,
        "venda",
        f"Venda balcão Nº {venda['numero']}",
        forma_pagamento,
        resumo["total_formatado"],
    )

    session.pop("pdv_carrinho", None)
    session.pop("pdv_cliente", None)
    session.pop("pdv_responsavel", None)

    return redirect(url_for("venda_balcao_finalizada", venda_id=venda_id))


@app.get("/vendas/balcao/finalizada/<int:venda_id>")
def venda_balcao_finalizada(venda_id: int) -> str | Response:
    venda = buscar_venda_por_id(venda_id)

    if venda is None:
        return redirect(url_for("venda_balcao"))

    return render_template("venda_balcao_finalizada.html", venda=venda)


@app.get("/vendas/balcao/fechar-caixa")
def venda_balcao_fechar_caixa() -> Response:
    return redirect(url_for("venda_balcao"))


@app.post("/vendas/balcao/fechar-caixa")
def venda_balcao_salvar_fechamento_caixa() -> Response:
    valor_fechamento = (request.form.get("valor_fechamento") or "0,00").strip()
    observacoes = (request.form.get("observacoes") or "").strip()
    fechar_caixa_db(valor_fechamento, observacoes)

    return redirect(url_for("venda_balcao"))

@app.get("/vendas")
def vendas() -> str:
    vendas_lista = listar_vendas()
    clientes_lista = listar_clientes()
    funcionarios_lista = listar_funcionarios()
    produtos_lista = listar_produtos()
    servicos_lista = listar_servicos()
    proximo_numero = proximo_numero_venda()

    return render_template(
        "vendas.html",
        vendas=vendas_lista,
        clientes=clientes_lista,
        funcionarios=funcionarios_lista,
        produtos=produtos_lista,
        servicos=servicos_lista,
        proximo_numero=proximo_numero,
    )


@app.get("/vendas/devolucoes")
def vendas_devolucoes() -> str:
    vendas_lista = listar_vendas()
    clientes_lista = listar_clientes()
    funcionarios_lista = listar_funcionarios()
    produtos_lista = listar_produtos()
    servicos_lista = listar_servicos()
    proximo_numero = proximo_numero_venda()

    return render_template(
        "vendas.html",
        vendas=vendas_lista,
        clientes=clientes_lista,
        funcionarios=funcionarios_lista,
        produtos=produtos_lista,
        servicos=servicos_lista,
        proximo_numero=proximo_numero,
        modo_devolucoes=True,
    )


@app.post("/vendas")
def salvar_venda() -> Response:
    venda = montar_venda_formulario(numero_padrao=proximo_numero_venda())
    itens = montar_venda_itens_formulario()
    erro_validacao = validar_venda_para_salvar(venda, itens)

    if erro_validacao:
        return redirect(url_for("vendas", erro=erro_validacao))

    venda_id = salvar_venda_db(venda, itens)
    baixar_estoque_por_venda_db(venda_id, venda, itens)
    gerar_conta_receber_por_venda_db(venda_id, venda)
    registrar_atividade_usuario("criacao", "vendas", f"Criou venda {venda.get('numero') or venda_id}", request.path)

    return redirect(url_for("vendas"))


@app.get("/vendas/<int:venda_id>")
def ver_venda(venda_id: int) -> str | Response:
    venda = buscar_venda_por_id(venda_id)

    if venda is None:
        return redirect(url_for("vendas"))

    itens = listar_venda_itens(venda_id)

    return render_template("venda_detalhe.html", venda=venda, itens=itens)


@app.get("/vendas/<int:venda_id>/devolucao")
def devolucao_venda(venda_id: int) -> str | Response:
    venda = buscar_venda_por_id(venda_id)

    if venda is None:
        return redirect(url_for("vendas"))

    vendas_lista = listar_vendas()
    clientes_lista = listar_clientes()
    funcionarios_lista = listar_funcionarios()
    produtos_lista = listar_produtos()
    servicos_lista = listar_servicos()
    itens_venda = listar_venda_itens(venda_id)
    itens_produtos = [item for item in itens_venda if str(item.get("tipo_item") or "") == "produto"]

    return render_template(
        "vendas.html",
        vendas=vendas_lista,
        clientes=clientes_lista,
        funcionarios=funcionarios_lista,
        produtos=produtos_lista,
        servicos=servicos_lista,
        proximo_numero=proximo_numero_venda(),
        modo_devolucoes=True,
        devolucao_venda=venda,
        devolucao_itens=itens_produtos,
    )


@app.post("/vendas/<int:venda_id>/devolver")
def devolver_venda(venda_id: int) -> Response:
    venda = buscar_venda_por_id(venda_id)

    if venda is None:
        return redirect(url_for("vendas"))

    itens_devolucao = montar_devolucao_itens_formulario()
    responsavel = (request.form.get("devolucao_responsavel") or "").strip()
    observacoes = (request.form.get("devolucao_observacoes") or "").strip()

    if itens_devolucao:
        devolver_estoque_por_venda_db(venda_id, venda, itens_devolucao, responsavel, observacoes)

    return redirect(url_for("vendas_devolucoes"))



@app.get("/vendas/<int:venda_id>/gerar/copia")
def gerar_copia_venda(venda_id: int) -> Response:
    nova_venda_id = copiar_venda_db(venda_id)

    if nova_venda_id is None:
        return redirect(url_for("vendas"))

    return redirect(url_for("editar_venda", venda_id=nova_venda_id))



@app.get("/vendas/<int:venda_id>/gerar/os")
def gerar_ordem_servico_por_venda(venda_id: int) -> Response:
    ordem_servico_id = gerar_ordem_servico_por_venda_db(venda_id)

    if ordem_servico_id is None:
        return redirect(url_for("vendas"))

    return redirect(url_for("ordens_servico"))

@app.get("/vendas/<int:venda_id>/imprimir/a4")
def imprimir_venda_a4(venda_id: int) -> str | Response:
    venda = buscar_venda_por_id(venda_id)

    if venda is None:
        return redirect(url_for("vendas"))

    itens = listar_venda_itens(venda_id)
    itens_produtos = [item for item in itens if item["tipo_item"] == "produto"]
    itens_servicos = [item for item in itens if item["tipo_item"] == "servico"]

    contexto_impressao = montar_contexto_impressao(venda.get("cliente"))

    return render_template(
        "venda_imprimir_a4.html",
        venda=venda,
        itens=itens,
        itens_produtos=itens_produtos,
        itens_servicos=itens_servicos,
        empresa=contexto_impressao["empresa"],
        loja=contexto_impressao["loja"],
        cliente=contexto_impressao["cliente"],
    )


@app.get("/vendas/<int:venda_id>/imprimir/cupom")
def imprimir_venda_cupom(venda_id: int) -> str | Response:
    venda = buscar_venda_por_id(venda_id)

    if venda is None:
        return redirect(url_for("vendas"))

    itens = listar_venda_itens(venda_id)
    itens_produtos = [item for item in itens if item["tipo_item"] == "produto"]
    itens_servicos = [item for item in itens if item["tipo_item"] == "servico"]

    contexto_impressao = montar_contexto_impressao(venda.get("cliente"))

    return render_template(
        "venda_imprimir_cupom.html",
        venda=venda,
        itens=itens,
        itens_produtos=itens_produtos,
        itens_servicos=itens_servicos,
        empresa=contexto_impressao["empresa"],
        loja=contexto_impressao["loja"],
        cliente=contexto_impressao["cliente"],
    )


@app.get("/vendas/<int:venda_id>/editar")
def editar_venda(venda_id: int) -> str | Response:
    venda = buscar_venda_por_id(venda_id)

    if venda is None:
        return redirect(url_for("vendas"))

    itens = listar_venda_itens(venda_id)
    clientes_lista = listar_clientes()
    funcionarios_lista = listar_funcionarios()
    produtos_lista = listar_produtos()
    servicos_lista = listar_servicos()

    return render_template(
        "venda_editar.html",
        venda=venda,
        itens=itens,
        clientes=clientes_lista,
        funcionarios=funcionarios_lista,
        produtos=produtos_lista,
        servicos=servicos_lista,
    )


@app.post("/vendas/<int:venda_id>/editar")
def atualizar_venda(venda_id: int) -> Response:
    venda_atual = buscar_venda_por_id(venda_id)

    if venda_atual is None:
        return redirect(url_for("vendas"))

    venda = montar_venda_formulario(numero_padrao=str(venda_atual["numero"] or ""))
    itens = montar_venda_itens_formulario()
    erro_validacao = validar_venda_para_salvar(venda, itens)

    if erro_validacao:
        return redirect(url_for("editar_venda", venda_id=venda_id, erro=erro_validacao))

    atualizar_venda_db(venda_id, venda, itens)

    return redirect(url_for("vendas"))


@app.post("/vendas/<int:venda_id>/excluir")
def excluir_venda(venda_id: int) -> Response:
    venda = buscar_venda_por_id(venda_id)

    if venda is not None:
        excluir_venda_db(venda_id)

    return redirect(url_for("vendas"))



@app.route("/orcamentos/gerador", methods=["GET", "POST"])
def gerador_orcamentos() -> str | Response:
    if request.method == "POST":
        dados = montar_gerador_orcamento_formulario()
        salvar_configuracao_gerador_empresa(dados)

        if not dados["cliente"]:
            return redirect(url_for("gerador_orcamentos", erro="Selecione um cliente para gerar o orçamento."))

        if not dados["responsavel"]:
            return redirect(url_for("gerador_orcamentos", erro="Selecione um responsável para gerar o orçamento."))

        if float(dados.get("valor_escolhido") or 0) <= 0:
            return redirect(url_for("gerador_orcamentos", erro="Informe materiais, mão de obra ou custos para formar um valor de orçamento."))

        novo_orcamento_id = gerar_orcamento_por_gerador_db(dados)
        return redirect(url_for("ver_orcamento", orcamento_id=novo_orcamento_id))

    return render_template(
        "orcamento_gerador.html",
        clientes=listar_clientes(),
        funcionarios=listar_funcionarios(),
        produtos=listar_produtos(),
        gerador_config=buscar_configuracao_gerador_empresa(),
        proximo_numero=proximo_numero_orcamento(),
        data_hoje=hoje_empresa().isoformat(),
    )

@app.get("/orcamentos")
def orcamentos() -> str:
    orcamentos_lista = listar_orcamentos()
    clientes_lista = listar_clientes()
    funcionarios_lista = listar_funcionarios()
    produtos_lista = listar_produtos()
    servicos_lista = listar_servicos()
    proximo_numero = proximo_numero_orcamento()

    return render_template(
        "orcamentos.html",
        orcamentos=orcamentos_lista,
        clientes=clientes_lista,
        funcionarios=funcionarios_lista,
        produtos=produtos_lista,
        servicos=servicos_lista,
        proximo_numero=proximo_numero,
    )


@app.post("/orcamentos")
def salvar_orcamento() -> Response:
    orcamento = montar_orcamento_formulario(numero_padrao=proximo_numero_orcamento())
    itens = montar_orcamento_itens_formulario()
    erro_validacao = validar_orcamento_para_salvar(orcamento, itens)

    if erro_validacao:
        return redirect(url_for("orcamentos", erro=erro_validacao))

    orcamento_id = salvar_orcamento_db(orcamento, itens)
    registrar_atividade_usuario("criacao", "orcamentos", f"Criou orçamento {orcamento.get('numero') or orcamento_id}", request.path)

    return redirect(url_for("orcamentos"))


@app.get("/orcamentos/<int:orcamento_id>")
def ver_orcamento(orcamento_id: int) -> str | Response:
    orcamento = buscar_orcamento_por_id(orcamento_id)

    if orcamento is None:
        return redirect(url_for("orcamentos"))

    itens = listar_orcamento_itens(orcamento_id)

    return render_template("orcamento_detalhe.html", orcamento=orcamento, itens=itens)


@app.get("/orcamentos/<int:orcamento_id>/gerar/copia")
def gerar_copia_orcamento(orcamento_id: int) -> Response:
    novo_orcamento_id = copiar_orcamento_db(orcamento_id)

    if novo_orcamento_id is None:
        return redirect(url_for("orcamentos"))

    return redirect(url_for("editar_orcamento", orcamento_id=novo_orcamento_id))


@app.get("/orcamentos/<int:orcamento_id>/imprimir/a4")
def imprimir_orcamento_a4(orcamento_id: int) -> str | Response:
    orcamento = buscar_orcamento_por_id(orcamento_id)

    if orcamento is None:
        return redirect(url_for("orcamentos"))

    itens = listar_orcamento_itens(orcamento_id)
    itens_produtos = [item for item in itens if item["tipo_item"] == "produto"]
    itens_servicos = [item for item in itens if item["tipo_item"] == "servico"]

    contexto_impressao = montar_contexto_impressao(orcamento.get("cliente"))

    return render_template(
        "orcamento_imprimir_a4.html",
        orcamento=orcamento,
        itens=itens,
        itens_produtos=itens_produtos,
        itens_servicos=itens_servicos,
        empresa=contexto_impressao["empresa"],
        loja=contexto_impressao["loja"],
        cliente=contexto_impressao["cliente"],
    )


@app.get("/orcamentos/<int:orcamento_id>/imprimir/cupom")
def imprimir_orcamento_cupom(orcamento_id: int) -> str | Response:
    orcamento = buscar_orcamento_por_id(orcamento_id)

    if orcamento is None:
        return redirect(url_for("orcamentos"))

    itens = listar_orcamento_itens(orcamento_id)
    itens_produtos = [item for item in itens if item["tipo_item"] == "produto"]
    itens_servicos = [item for item in itens if item["tipo_item"] == "servico"]

    contexto_impressao = montar_contexto_impressao(orcamento.get("cliente"))

    return render_template(
        "orcamento_imprimir_cupom.html",
        orcamento=orcamento,
        itens=itens,
        itens_produtos=itens_produtos,
        itens_servicos=itens_servicos,
        empresa=contexto_impressao["empresa"],
        loja=contexto_impressao["loja"],
        cliente=contexto_impressao["cliente"],
    )


@app.get("/orcamentos/<int:orcamento_id>/editar")
def editar_orcamento(orcamento_id: int) -> str | Response:
    orcamento = buscar_orcamento_por_id(orcamento_id)

    if orcamento is None:
        return redirect(url_for("orcamentos"))

    itens = listar_orcamento_itens(orcamento_id)
    clientes_lista = listar_clientes()
    funcionarios_lista = listar_funcionarios()
    produtos_lista = listar_produtos()
    servicos_lista = listar_servicos()

    return render_template(
        "orcamento_editar.html",
        orcamento=orcamento,
        itens=itens,
        clientes=clientes_lista,
        funcionarios=funcionarios_lista,
        produtos=produtos_lista,
        servicos=servicos_lista,
    )


@app.post("/orcamentos/<int:orcamento_id>/editar")
def atualizar_orcamento(orcamento_id: int) -> Response:
    orcamento_atual = buscar_orcamento_por_id(orcamento_id)

    if orcamento_atual is None:
        return redirect(url_for("orcamentos"))

    orcamento = montar_orcamento_formulario(numero_padrao=str(orcamento_atual["numero"] or ""))
    itens = montar_orcamento_itens_formulario()
    erro_validacao = validar_orcamento_para_salvar(orcamento, itens)

    if erro_validacao:
        return redirect(url_for("editar_orcamento", orcamento_id=orcamento_id, erro=erro_validacao))

    atualizar_orcamento_db(orcamento_id, orcamento, itens)

    return redirect(url_for("ver_orcamento", orcamento_id=orcamento_id))


@app.post("/orcamentos/<int:orcamento_id>/excluir")
def excluir_orcamento(orcamento_id: int) -> Response:
    orcamento = buscar_orcamento_por_id(orcamento_id)

    if orcamento is not None:
        excluir_orcamento_db(orcamento_id)

    return redirect(url_for("orcamentos"))



@app.post("/assistente/perguntar")
def assistente_perguntar() -> Response:
    if not session.get("usuario_id"):
        return jsonify({"ok": False, "resposta": "Faça login para usar o Assistente IA."}), 401

    dados = request.get_json(silent=True) or {}
    pergunta = str(dados.get("pergunta") or "").strip()

    if not pergunta:
        return jsonify({"ok": False, "resposta": "Digite uma pergunta para o Assistente IA."}), 400

    if len(pergunta) > 1200:
        return jsonify({"ok": False, "resposta": "Sua pergunta ficou muito grande. Resuma um pouco e tente novamente."}), 400

    resposta, origem = chamar_assistente_ia(pergunta)
    salvar_conversa_assistente(pergunta, resposta, origem)
    registrar_atividade_usuario(
        "assistente",
        "assistente_ia",
        "Usou o Assistente IA",
        "/assistente/perguntar",
    )

    return jsonify({"ok": True, "resposta": resposta, "origem": origem})


@app.get("/health")
def health() -> Response:
    return Response("ok", status=200, mimetype="text/plain")


@app.post(config.WEBHOOK_PATH)
def twilio_webhook() -> Response:
    from_number = (request.form.get("From") or "").strip()
    body = (request.form.get("Body") or "").strip()

    # Import lazy para evitar falha de import enquanto os módulos ainda não foram criados.
    try:
        from modules.whatsapp import handle_message  # type: ignore
    except Exception:
        msg = "Modulo modules/whatsapp.py ainda nao foi criado. Proximo passo: criar modules/whatsapp.py."
        return Response(_twiml_message(msg), status=200, mimetype="application/xml")

    reply_text = handle_message(from_number=from_number, body=body)
    return Response(_twiml_message(reply_text), status=200, mimetype="application/xml")


iniciar_banco()


if __name__ == "__main__":
    # Somente para uso local. No Railway usaremos o wsgi.py com waitress.
    app.run(host="0.0.0.0", port=5000, debug=config.DEBUG)
