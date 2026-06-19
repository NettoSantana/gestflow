# Caminho: C:\Users\vlula\OneDrive\Área de Trabalho\Projetos Backup\GESTFLOW\app.py
# Último recode: 2026-06-19 08:45 (America/Bahia)
# Motivo: Impressões de orçamento e venda buscando dados cadastrados da empresa e do cliente.

from __future__ import annotations

import html
import sqlite3
from datetime import date, datetime
from pathlib import Path
from typing import Any

from flask import Flask, Response, redirect, render_template, request, session, url_for

from werkzeug.security import check_password_hash, generate_password_hash

import config

app = Flask(__name__)
app.secret_key = getattr(config, "SECRET_KEY", "gestflow-dev-secret-key-trocar-em-producao")

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = DATA_DIR / "gestflow.db"


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

    if str(usuario.get("empresa_status") or "").strip().lower() != "ativo":
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
            (datetime.now().isoformat(timespec="seconds"), usuario_id),
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


@app.context_processor
def injetar_usuario_logado() -> dict[str, Any]:
    return {"usuario_logado": usuario_logado()}


@app.before_request
def exigir_login_rotas_internas() -> Response | None:
    rotas_publicas = {
        "portal",
        "login",
        "health",
        "twilio_webhook",
        "static",
    }

    if request.endpoint in rotas_publicas:
        return None

    if request.path.startswith("/static/"):
        return None

    if session.get("usuario_id"):
        return None

    return redirect(url_for("login"))


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
            "estoque_movimentacoes",
            "financeiro_titulos",
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

def salvar_funcionario_db(funcionario: dict[str, str]) -> None:
    empresa_id = empresa_logada_id()

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
                observacoes
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                observacoes = ?
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

    if vencimento is not None and vencimento < date.today():
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
    atualizar_status_financeiro_titulo_db(titulo_id, "pago", date.today().isoformat())


def montar_financeiro_titulo_formulario(tipo_padrao: str = "receber") -> dict[str, str]:
    tipo = (request.form.get("financeiro_tipo") or tipo_padrao).strip() or tipo_padrao

    if tipo not in {"receber", "pagar"}:
        tipo = tipo_padrao

    status = (request.form.get("financeiro_status") or "aberto").strip() or "aberto"

    if status not in {"aberto", "pago", "vencido", "cancelado"}:
        status = "aberto"

    data_pagamento = (request.form.get("financeiro_data_pagamento") or "").strip()

    if status == "pago" and not data_pagamento:
        data_pagamento = date.today().isoformat()

    return {
        "tipo": tipo,
        "descricao": (request.form.get("financeiro_descricao") or "").strip(),
        "pessoa": (request.form.get("financeiro_pessoa") or "").strip(),
        "categoria": (request.form.get("financeiro_categoria") or "Outros").strip() or "Outros",
        "origem": "manual",
        "origem_id": "",
        "documento": (request.form.get("financeiro_documento") or "").strip(),
        "data_emissao": (request.form.get("financeiro_data_emissao") or date.today().isoformat()).strip(),
        "data_vencimento": (request.form.get("financeiro_data_vencimento") or date.today().isoformat()).strip(),
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
    data_emissao = str(venda.get("data") or "").strip() or date.today().isoformat()
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
    inicio_mes_atual = date.today().replace(day=1)
    return [_adicionar_meses(inicio_mes_atual, indice - quantidade + 1) for indice in range(quantidade)]


def _montar_calendario_financeiro(titulos: list[dict[str, Any]]) -> list[dict[str, Any]]:
    hoje = date.today()
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
    hoje = date.today()
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
    hoje = date.today()

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

    hoje = date.today()
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
                criado_em
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
            "plano": "Start",
            "status": "ativo",
            "criado_em": "",
        }

    return dict(row)


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
    return {
        "empresa": buscar_empresa_configuracoes(),
        "usuarios": listar_usuarios_configuracoes(),
        "lojas": listar_lojas_configuracoes(),
    }


def usuario_logado_eh_admin_sistema() -> bool:
    email = str(session.get("usuario_email") or "").strip().lower()
    perfil = str(session.get("usuario_perfil") or "").strip().lower()

    emails_admin_sistema = {
        "admin@gestflow.local",
        "nettosantana@icloud.com",
    }

    return perfil in {"super_admin", "dono", "administrador_sistema"} or email in emails_admin_sistema


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

    return [dict(row) for row in rows]


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

    if status_normalizado not in {"ativo", "bloqueado", "cancelado"}:
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
    )


@app.get("/portal")
def portal() -> str:
    return render_template("portal.html")


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

        session.clear()
        session["usuario_id"] = int(usuario["id"])
        session["empresa_id"] = int(usuario["empresa_id"])
        session["usuario_nome"] = str(usuario.get("nome") or "")
        session["usuario_email"] = str(usuario.get("email") or "")
        session["usuario_perfil"] = str(usuario.get("perfil") or "")
        session["empresa_nome"] = str(usuario.get("empresa_nome") or "")
        session["empresa_plano"] = str(usuario.get("empresa_plano") or "")

        registrar_ultimo_login_usuario(int(usuario["id"]))

        return redirect(url_for("dashboard"))

    return render_template("login.html")


@app.get("/sair")
def sair() -> Response:
    session.clear()
    return redirect(url_for("login"))


@app.get("/")
def dashboard() -> str:
    dados_dashboard = montar_dashboard()
    return render_template("dashboard.html", dashboard=dados_dashboard)


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

    if cliente["nome"]:
        salvar_cliente_db(cliente)

    return redirect(url_for("clientes"))


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

    if cliente["nome"]:
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

    if fornecedor["nome"]:
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

    if fornecedor["nome"]:
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
    }

    if funcionario["nome"]:
        salvar_funcionario_db(funcionario)

    return redirect(url_for("funcionarios"))


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
    }

    if funcionario["nome"]:
        atualizar_funcionario_db(funcionario_id, funcionario)

    return redirect(url_for("ver_funcionario", funcionario_id=funcionario_id))


@app.post("/funcionarios/<int:funcionario_id>/excluir")
def excluir_funcionario(funcionario_id: int) -> Response:
    funcionario = buscar_funcionario_por_id(funcionario_id)

    if funcionario is not None:
        excluir_funcionario_db(funcionario_id)

    return redirect(url_for("funcionarios"))


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

    if produto["nome"]:
        salvar_produto_db(produto)

    return redirect(url_for("produtos"))


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

    if produto["nome"]:
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

    if servico["nome"]:
        salvar_servico_db(servico)

    return redirect(url_for("servicos"))


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

    if servico["nome"]:
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
        movimentacoes=movimentacoes,
        painel=painel,
        aba=aba,
        produto_selecionado=produto_selecionado,
        produto_selecionado_id=produto_selecionado_id,
    )


@app.post("/estoque/movimentar")
def movimentar_estoque() -> Response:
    movimentacao_form = montar_estoque_formulario()

    try:
        produto_id = int(movimentacao_form["produto_id"])
    except ValueError:
        return redirect(url_for("estoque"))

    produto = buscar_produto_por_id(produto_id)

    if produto is None:
        return redirect(url_for("estoque"))

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

    try:
        produto_id = int(produto_id_texto)
    except ValueError:
        return redirect(url_for("estoque") + "/compras")

    produto = buscar_produto_por_id(produto_id)

    if produto is None:
        return redirect(url_for("estoque") + "/compras")

    quantidade = _converter_valor_brl(request.form.get("compra_quantidade"))
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
    produtos_lista = listar_produtos()
    servicos_lista = listar_servicos()
    proximo_numero = proximo_numero_ordem_servico()

    return render_template(
        "ordens_servico.html",
        ordens_servico=ordens_servico_lista,
        clientes=clientes_lista,
        produtos=produtos_lista,
        servicos=servicos_lista,
        proximo_numero=proximo_numero,
    )


@app.post("/ordens-servico")
def salvar_ordem_servico() -> Response:
    ordem_servico = montar_ordem_servico_formulario(numero_padrao=proximo_numero_ordem_servico())
    itens = montar_ordem_servico_itens_formulario()

    if ordem_servico["cliente"] or ordem_servico["numero"]:
        salvar_ordem_servico_db(ordem_servico, itens)

    return redirect(url_for("ordens_servico"))


@app.get("/ordens-servico/<int:ordem_servico_id>")
def ver_ordem_servico(ordem_servico_id: int) -> str | Response:
    ordem_servico = buscar_ordem_servico_por_id(ordem_servico_id)

    if ordem_servico is None:
        return redirect(url_for("ordens_servico"))

    itens = listar_ordem_servico_itens(ordem_servico_id)
    itens_produtos = [item for item in itens if item["tipo_item"] == "produto"]
    itens_servicos = [item for item in itens if item["tipo_item"] == "servico"]

    return render_template(
        "ordem_servico_detalhe.html",
        ordem_servico=ordem_servico,
        itens=itens,
        itens_produtos=itens_produtos,
        itens_servicos=itens_servicos,
    )


@app.get("/ordens-servico/<int:ordem_servico_id>/imprimir/a4")
def imprimir_ordem_servico_a4(ordem_servico_id: int) -> str | Response:
    ordem_servico = buscar_ordem_servico_por_id(ordem_servico_id)

    if ordem_servico is None:
        return redirect(url_for("ordens_servico"))

    itens = listar_ordem_servico_itens(ordem_servico_id)
    itens_produtos = [item for item in itens if item["tipo_item"] == "produto"]
    itens_servicos = [item for item in itens if item["tipo_item"] == "servico"]

    return render_template(
        "ordem_servico_imprimir_a4.html",
        ordem_servico=ordem_servico,
        itens=itens,
        itens_produtos=itens_produtos,
        itens_servicos=itens_servicos,
    )


@app.get("/ordens-servico/<int:ordem_servico_id>/imprimir/cupom")
def imprimir_ordem_servico_cupom(ordem_servico_id: int) -> str | Response:
    ordem_servico = buscar_ordem_servico_por_id(ordem_servico_id)

    if ordem_servico is None:
        return redirect(url_for("ordens_servico"))

    itens = listar_ordem_servico_itens(ordem_servico_id)
    itens_produtos = [item for item in itens if item["tipo_item"] == "produto"]
    itens_servicos = [item for item in itens if item["tipo_item"] == "servico"]

    return render_template(
        "ordem_servico_imprimir_cupom.html",
        ordem_servico=ordem_servico,
        itens=itens,
        itens_produtos=itens_produtos,
        itens_servicos=itens_servicos,
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
    produtos_lista = listar_produtos()
    servicos_lista = listar_servicos()

    return render_template(
        "ordem_servico_editar.html",
        ordem_servico=ordem_servico,
        itens=itens,
        clientes=clientes_lista,
        produtos=produtos_lista,
        servicos=servicos_lista,
    )


@app.post("/ordens-servico/<int:ordem_servico_id>/editar")
def atualizar_ordem_servico(ordem_servico_id: int) -> Response:
    ordem_servico_atual = buscar_ordem_servico_por_id(ordem_servico_id)

    if ordem_servico_atual is None:
        return redirect(url_for("ordens_servico"))

    ordem_servico = montar_ordem_servico_formulario(numero_padrao=str(ordem_servico_atual["numero"] or ""))
    itens = montar_ordem_servico_itens_formulario()

    atualizar_ordem_servico_db(ordem_servico_id, ordem_servico, itens)

    return redirect(url_for("ver_ordem_servico", ordem_servico_id=ordem_servico_id))


@app.post("/ordens-servico/<int:ordem_servico_id>/excluir")
def excluir_ordem_servico(ordem_servico_id: int) -> Response:
    ordem_servico = buscar_ordem_servico_por_id(ordem_servico_id)

    if ordem_servico is not None:
        excluir_ordem_servico_db(ordem_servico_id)

    return redirect(url_for("ordens_servico"))


@app.get("/vendas")
def vendas() -> str:
    vendas_lista = listar_vendas()
    clientes_lista = listar_clientes()
    produtos_lista = listar_produtos()
    servicos_lista = listar_servicos()
    proximo_numero = proximo_numero_venda()

    return render_template(
        "vendas.html",
        vendas=vendas_lista,
        clientes=clientes_lista,
        produtos=produtos_lista,
        servicos=servicos_lista,
        proximo_numero=proximo_numero,
    )


@app.get("/vendas/devolucoes")
def vendas_devolucoes() -> str:
    vendas_lista = listar_vendas()
    clientes_lista = listar_clientes()
    produtos_lista = listar_produtos()
    servicos_lista = listar_servicos()
    proximo_numero = proximo_numero_venda()

    return render_template(
        "vendas.html",
        vendas=vendas_lista,
        clientes=clientes_lista,
        produtos=produtos_lista,
        servicos=servicos_lista,
        proximo_numero=proximo_numero,
        modo_devolucoes=True,
    )


@app.post("/vendas")
def salvar_venda() -> Response:
    venda = montar_venda_formulario(numero_padrao=proximo_numero_venda())
    itens = montar_venda_itens_formulario()

    if venda["cliente"] or venda["numero"]:
        venda_id = salvar_venda_db(venda, itens)
        baixar_estoque_por_venda_db(venda_id, venda, itens)
        gerar_conta_receber_por_venda_db(venda_id, venda)

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
    produtos_lista = listar_produtos()
    servicos_lista = listar_servicos()
    itens_venda = listar_venda_itens(venda_id)
    itens_produtos = [item for item in itens_venda if str(item.get("tipo_item") or "") == "produto"]

    return render_template(
        "vendas.html",
        vendas=vendas_lista,
        clientes=clientes_lista,
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
    produtos_lista = listar_produtos()
    servicos_lista = listar_servicos()

    return render_template(
        "venda_editar.html",
        venda=venda,
        itens=itens,
        clientes=clientes_lista,
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

    atualizar_venda_db(venda_id, venda, itens)

    return redirect(url_for("vendas"))


@app.post("/vendas/<int:venda_id>/excluir")
def excluir_venda(venda_id: int) -> Response:
    venda = buscar_venda_por_id(venda_id)

    if venda is not None:
        excluir_venda_db(venda_id)

    return redirect(url_for("vendas"))


@app.get("/orcamentos")
def orcamentos() -> str:
    orcamentos_lista = listar_orcamentos()
    clientes_lista = listar_clientes()
    produtos_lista = listar_produtos()
    servicos_lista = listar_servicos()
    proximo_numero = proximo_numero_orcamento()

    return render_template(
        "orcamentos.html",
        orcamentos=orcamentos_lista,
        clientes=clientes_lista,
        produtos=produtos_lista,
        servicos=servicos_lista,
        proximo_numero=proximo_numero,
    )


@app.post("/orcamentos")
def salvar_orcamento() -> Response:
    orcamento = montar_orcamento_formulario(numero_padrao=proximo_numero_orcamento())
    itens = montar_orcamento_itens_formulario()

    if orcamento["cliente"] or orcamento["numero"]:
        salvar_orcamento_db(orcamento, itens)

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
    produtos_lista = listar_produtos()
    servicos_lista = listar_servicos()

    return render_template(
        "orcamento_editar.html",
        orcamento=orcamento,
        itens=itens,
        clientes=clientes_lista,
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

    atualizar_orcamento_db(orcamento_id, orcamento, itens)

    return redirect(url_for("ver_orcamento", orcamento_id=orcamento_id))


@app.post("/orcamentos/<int:orcamento_id>/excluir")
def excluir_orcamento(orcamento_id: int) -> Response:
    orcamento = buscar_orcamento_por_id(orcamento_id)

    if orcamento is not None:
        excluir_orcamento_db(orcamento_id)

    return redirect(url_for("orcamentos"))


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
