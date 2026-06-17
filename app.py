# Caminho: C:\Users\vlula\OneDrive\Área de Trabalho\Projetos Backup\GESTFLOW\app.py
# Último recode: 2026-06-16 21:35 (America/Bahia)
# Motivo: Ligar campos completos da tela de OS no banco, formulário, listagem e geração por venda.

from __future__ import annotations

import html
import sqlite3
from pathlib import Path
from typing import Any

from flask import Flask, Response, redirect, render_template, request, url_for

import config

app = Flask(__name__)

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "gestflow.db"


def _twiml_message(text: str) -> str:
    safe = html.escape(text or "")
    return f'<?xml version="1.0" encoding="UTF-8"?><Response><Message>{safe}</Message></Response>'


def conectar_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


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
    with conectar_db() as conn:
        conn.execute(
            """
            INSERT INTO clientes (
                nome,
                documento,
                telefone,
                cidade,
                status,
                email
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
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
    with conectar_db() as conn:
        rows = conn.execute(
            """
            SELECT
                id,
                nome,
                documento,
                telefone,
                cidade,
                status,
                email,
                criado_em
            FROM clientes
            ORDER BY id DESC
            """
        ).fetchall()

    return [dict(row) for row in rows]


def buscar_cliente_por_id(cliente_id: int) -> dict[str, Any] | None:
    with conectar_db() as conn:
        row = conn.execute(
            """
            SELECT
                id,
                nome,
                documento,
                telefone,
                cidade,
                status,
                email,
                criado_em
            FROM clientes
            WHERE id = ?
            """,
            (cliente_id,),
        ).fetchone()

    if row is None:
        return None

    return dict(row)


def atualizar_cliente_db(cliente_id: int, cliente: dict[str, str]) -> None:
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
            """,
            (
                cliente["nome"],
                cliente["documento"],
                cliente["telefone"],
                cliente["cidade"],
                cliente["status"],
                cliente["email"],
                cliente_id,
            ),
        )
        conn.commit()


def excluir_cliente_db(cliente_id: int) -> None:
    with conectar_db() as conn:
        conn.execute(
            """
            DELETE FROM clientes
            WHERE id = ?
            """,
            (cliente_id,),
        )
        conn.commit()


def salvar_fornecedor_db(fornecedor: dict[str, str]) -> None:
    with conectar_db() as conn:
        conn.execute(
            """
            INSERT INTO fornecedores (
                nome,
                documento,
                telefone,
                cidade,
                status,
                email,
                categoria,
                observacoes
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
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
            ),
        )
        conn.commit()


def listar_fornecedores() -> list[dict[str, Any]]:
    with conectar_db() as conn:
        rows = conn.execute(
            """
            SELECT
                id,
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
            ORDER BY id DESC
            """
        ).fetchall()

    return [dict(row) for row in rows]


def buscar_fornecedor_por_id(fornecedor_id: int) -> dict[str, Any] | None:
    with conectar_db() as conn:
        row = conn.execute(
            """
            SELECT
                id,
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
            """,
            (fornecedor_id,),
        ).fetchone()

    if row is None:
        return None

    return dict(row)


def atualizar_fornecedor_db(fornecedor_id: int, fornecedor: dict[str, str]) -> None:
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
            ),
        )
        conn.commit()


def excluir_fornecedor_db(fornecedor_id: int) -> None:
    with conectar_db() as conn:
        conn.execute(
            """
            DELETE FROM fornecedores
            WHERE id = ?
            """,
            (fornecedor_id,),
        )
        conn.commit()


def salvar_funcionario_db(funcionario: dict[str, str]) -> None:
    with conectar_db() as conn:
        conn.execute(
            """
            INSERT INTO funcionarios (
                nome,
                cpf,
                telefone,
                cidade,
                cargo,
                status,
                email,
                observacoes
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
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
            ),
        )
        conn.commit()


def listar_funcionarios() -> list[dict[str, Any]]:
    with conectar_db() as conn:
        rows = conn.execute(
            """
            SELECT
                id,
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
            ORDER BY id DESC
            """
        ).fetchall()

    return [dict(row) for row in rows]


def buscar_funcionario_por_id(funcionario_id: int) -> dict[str, Any] | None:
    with conectar_db() as conn:
        row = conn.execute(
            """
            SELECT
                id,
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
            """,
            (funcionario_id,),
        ).fetchone()

    if row is None:
        return None

    return dict(row)


def atualizar_funcionario_db(funcionario_id: int, funcionario: dict[str, str]) -> None:
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
            ),
        )
        conn.commit()


def excluir_funcionario_db(funcionario_id: int) -> None:
    with conectar_db() as conn:
        conn.execute(
            """
            DELETE FROM funcionarios
            WHERE id = ?
            """,
            (funcionario_id,),
        )
        conn.commit()


def salvar_produto_db(produto: dict[str, str]) -> None:
    with conectar_db() as conn:
        conn.execute(
            """
            INSERT INTO produtos (
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
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
            ),
        )
        conn.commit()


def listar_produtos() -> list[dict[str, Any]]:
    with conectar_db() as conn:
        rows = conn.execute(
            """
            SELECT
                id,
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
            ORDER BY id DESC
            """
        ).fetchall()

    return [dict(row) for row in rows]


def buscar_produto_por_id(produto_id: int) -> dict[str, Any] | None:
    with conectar_db() as conn:
        row = conn.execute(
            """
            SELECT
                id,
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
            """,
            (produto_id,),
        ).fetchone()

    if row is None:
        return None

    return dict(row)


def atualizar_produto_db(produto_id: int, produto: dict[str, str]) -> None:
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
            ),
        )
        conn.commit()


def excluir_produto_db(produto_id: int) -> None:
    with conectar_db() as conn:
        conn.execute(
            """
            DELETE FROM produtos
            WHERE id = ?
            """,
            (produto_id,),
        )
        conn.commit()


def salvar_servico_db(servico: dict[str, str]) -> None:
    with conectar_db() as conn:
        conn.execute(
            """
            INSERT INTO servicos (
                nome,
                codigo,
                categoria,
                unidade,
                custo,
                valor_venda,
                tempo_estimado,
                status,
                observacoes
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
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
            ),
        )
        conn.commit()


def listar_servicos() -> list[dict[str, Any]]:
    with conectar_db() as conn:
        rows = conn.execute(
            """
            SELECT
                id,
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
            ORDER BY id DESC
            """
        ).fetchall()

    return [dict(row) for row in rows]


def buscar_servico_por_id(servico_id: int) -> dict[str, Any] | None:
    with conectar_db() as conn:
        row = conn.execute(
            """
            SELECT
                id,
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
            """,
            (servico_id,),
        ).fetchone()

    if row is None:
        return None

    return dict(row)


def atualizar_servico_db(servico_id: int, servico: dict[str, str]) -> None:
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
            ),
        )
        conn.commit()


def excluir_servico_db(servico_id: int) -> None:
    with conectar_db() as conn:
        conn.execute(
            """
            DELETE FROM servicos
            WHERE id = ?
            """,
            (servico_id,),
        )
        conn.commit()


def proximo_numero_orcamento() -> str:
    with conectar_db() as conn:
        row = conn.execute(
            """
            SELECT
                COALESCE(MAX(id), 0) + 1 AS proximo
            FROM orcamentos
            """
        ).fetchone()

    proximo = 1 if row is None else int(row["proximo"])
    return str(proximo).zfill(4)


def salvar_orcamento_db(orcamento: dict[str, str], itens: list[dict[str, str]]) -> int:
    with conectar_db() as conn:
        cursor = conn.execute(
            """
            INSERT INTO orcamentos (
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
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
            ),
        )
        orcamento_id = int(cursor.lastrowid)

        for item in itens:
            if not item["descricao"]:
                continue

            conn.execute(
                """
                INSERT INTO orcamento_itens (
                    orcamento_id,
                    tipo_item,
                    descricao,
                    detalhes,
                    quantidade,
                    valor_unitario,
                    desconto,
                    subtotal
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
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
    with conectar_db() as conn:
        rows = conn.execute(
            """
            SELECT
                id,
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
            ORDER BY id DESC
            """
        ).fetchall()

    return [dict(row) for row in rows]


def buscar_orcamento_por_id(orcamento_id: int) -> dict[str, Any] | None:
    with conectar_db() as conn:
        row = conn.execute(
            """
            SELECT
                id,
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
            """,
            (orcamento_id,),
        ).fetchone()

    if row is None:
        return None

    return dict(row)


def listar_orcamento_itens(orcamento_id: int) -> list[dict[str, Any]]:
    with conectar_db() as conn:
        rows = conn.execute(
            """
            SELECT
                id,
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
            ORDER BY id ASC
            """,
            (orcamento_id,),
        ).fetchall()

    return [dict(row) for row in rows]


def atualizar_orcamento_db(orcamento_id: int, orcamento: dict[str, str], itens: list[dict[str, str]]) -> None:
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
            ),
        )

        conn.execute(
            """
            DELETE FROM orcamento_itens
            WHERE orcamento_id = ?
            """,
            (orcamento_id,),
        )

        for item in itens:
            if not item["descricao"]:
                continue

            conn.execute(
                """
                INSERT INTO orcamento_itens (
                    orcamento_id,
                    tipo_item,
                    descricao,
                    detalhes,
                    quantidade,
                    valor_unitario,
                    desconto,
                    subtotal
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
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
    with conectar_db() as conn:
        conn.execute(
            """
            DELETE FROM orcamento_itens
            WHERE orcamento_id = ?
            """,
            (orcamento_id,),
        )
        conn.execute(
            """
            DELETE FROM orcamentos
            WHERE id = ?
            """,
            (orcamento_id,),
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
    with conectar_db() as conn:
        row = conn.execute(
            """
            SELECT
                COALESCE(MAX(id), 0) + 1 AS proximo
            FROM vendas
            """
        ).fetchone()

    proximo = 1 if row is None else int(row["proximo"])
    return str(proximo).zfill(4)


def salvar_venda_db(venda: dict[str, str], itens: list[dict[str, str]]) -> int:
    with conectar_db() as conn:
        cursor = conn.execute(
            """
            INSERT INTO vendas (
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
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
            ),
        )
        venda_id = int(cursor.lastrowid)

        for item in itens:
            if not item["descricao"]:
                continue

            conn.execute(
                """
                INSERT INTO venda_itens (
                    venda_id,
                    tipo_item,
                    descricao,
                    detalhes,
                    quantidade,
                    valor_unitario,
                    desconto,
                    subtotal
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
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
    with conectar_db() as conn:
        rows = conn.execute(
            """
            SELECT
                id,
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
            ORDER BY id DESC
            """
        ).fetchall()

    return [dict(row) for row in rows]


def buscar_venda_por_id(venda_id: int) -> dict[str, Any] | None:
    with conectar_db() as conn:
        row = conn.execute(
            """
            SELECT
                id,
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
            """,
            (venda_id,),
        ).fetchone()

    if row is None:
        return None

    return dict(row)


def listar_venda_itens(venda_id: int) -> list[dict[str, Any]]:
    with conectar_db() as conn:
        rows = conn.execute(
            """
            SELECT
                id,
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
            ORDER BY id ASC
            """,
            (venda_id,),
        ).fetchall()

    return [dict(row) for row in rows]



def atualizar_venda_db(venda_id: int, venda: dict[str, str], itens: list[dict[str, str]]) -> None:
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
            ),
        )

        conn.execute(
            """
            DELETE FROM venda_itens
            WHERE venda_id = ?
            """,
            (venda_id,),
        )

        for item in itens:
            if not item["descricao"]:
                continue

            conn.execute(
                """
                INSERT INTO venda_itens (
                    venda_id,
                    tipo_item,
                    descricao,
                    detalhes,
                    quantidade,
                    valor_unitario,
                    desconto,
                    subtotal
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
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
    with conectar_db() as conn:
        conn.execute(
            """
            DELETE FROM venda_itens
            WHERE venda_id = ?
            """,
            (venda_id,),
        )
        conn.execute(
            """
            DELETE FROM vendas
            WHERE id = ?
            """,
            (venda_id,),
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
    with conectar_db() as conn:
        row = conn.execute(
            """
            SELECT
                COALESCE(MAX(id), 0) + 1 AS proximo
            FROM ordens_servico
            """
        ).fetchone()

    proximo = 1 if row is None else int(row["proximo"])
    return str(proximo).zfill(4)


def salvar_ordem_servico_db(ordem_servico: dict[str, str], itens: list[dict[str, str]]) -> int:
    with conectar_db() as conn:
        cursor = conn.execute(
            """
            INSERT INTO ordens_servico (
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
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
            ),
        )
        ordem_servico_id = int(cursor.lastrowid)

        for item in itens:
            if not item["descricao"]:
                continue

            conn.execute(
                """
                INSERT INTO ordem_servico_itens (
                    ordem_servico_id,
                    tipo_item,
                    descricao,
                    detalhes,
                    quantidade,
                    valor_unitario,
                    desconto,
                    subtotal
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
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


def listar_ordens_servico() -> list[dict[str, Any]]:
    with conectar_db() as conn:
        rows = conn.execute(
            """
            SELECT
                id,
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
            ORDER BY id DESC
            """
        ).fetchall()

    return [dict(row) for row in rows]


def buscar_ordem_servico_por_id(ordem_servico_id: int) -> dict[str, Any] | None:
    with conectar_db() as conn:
        row = conn.execute(
            """
            SELECT
                id,
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
            """,
            (ordem_servico_id,),
        ).fetchone()

    if row is None:
        return None

    return dict(row)


def listar_ordem_servico_itens(ordem_servico_id: int) -> list[dict[str, Any]]:
    with conectar_db() as conn:
        rows = conn.execute(
            """
            SELECT
                id,
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
            ORDER BY id ASC
            """,
            (ordem_servico_id,),
        ).fetchall()

    return [dict(row) for row in rows]


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
        "equipamento": (request.form.get("os_equipamento") or "").strip(),
        "marca": (request.form.get("os_marca") or "").strip(),
        "modelo": (request.form.get("os_modelo") or "").strip(),
        "serie": (request.form.get("os_serie") or "").strip(),
        "local_servico": (request.form.get("os_local_servico") or "").strip(),
        "condicoes": (request.form.get("os_condicoes") or "").strip(),
        "acessorios": (request.form.get("os_acessorios") or "").strip(),
        "laudo": (request.form.get("os_laudo") or "").strip(),
        "termos": (request.form.get("os_termos") or "").strip(),
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
        "relato_cliente": (request.form.get("os_relato_cliente") or "").strip(),
        "diagnostico": (request.form.get("os_diagnostico") or "").strip(),
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


@app.get("/")
def dashboard() -> str:
    return render_template("dashboard.html")


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


@app.post("/vendas")
def salvar_venda() -> Response:
    venda = montar_venda_formulario(numero_padrao=proximo_numero_venda())
    itens = montar_venda_itens_formulario()

    if venda["cliente"] or venda["numero"]:
        salvar_venda_db(venda, itens)

    return redirect(url_for("vendas"))


@app.get("/vendas/<int:venda_id>")
def ver_venda(venda_id: int) -> str | Response:
    venda = buscar_venda_por_id(venda_id)

    if venda is None:
        return redirect(url_for("vendas"))

    itens = listar_venda_itens(venda_id)

    return render_template("venda_detalhe.html", venda=venda, itens=itens)



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

    return render_template(
        "venda_imprimir_a4.html",
        venda=venda,
        itens=itens,
        itens_produtos=itens_produtos,
        itens_servicos=itens_servicos,
    )


@app.get("/vendas/<int:venda_id>/imprimir/cupom")
def imprimir_venda_cupom(venda_id: int) -> str | Response:
    venda = buscar_venda_por_id(venda_id)

    if venda is None:
        return redirect(url_for("vendas"))

    itens = listar_venda_itens(venda_id)
    itens_produtos = [item for item in itens if item["tipo_item"] == "produto"]
    itens_servicos = [item for item in itens if item["tipo_item"] == "servico"]

    return render_template(
        "venda_imprimir_cupom.html",
        venda=venda,
        itens=itens,
        itens_produtos=itens_produtos,
        itens_servicos=itens_servicos,
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

    return render_template(
        "orcamento_imprimir_a4.html",
        orcamento=orcamento,
        itens=itens,
        itens_produtos=itens_produtos,
        itens_servicos=itens_servicos,
    )


@app.get("/orcamentos/<int:orcamento_id>/imprimir/cupom")
def imprimir_orcamento_cupom(orcamento_id: int) -> str | Response:
    orcamento = buscar_orcamento_por_id(orcamento_id)

    if orcamento is None:
        return redirect(url_for("orcamentos"))

    itens = listar_orcamento_itens(orcamento_id)
    itens_produtos = [item for item in itens if item["tipo_item"] == "produto"]
    itens_servicos = [item for item in itens if item["tipo_item"] == "servico"]

    return render_template(
        "orcamento_imprimir_cupom.html",
        orcamento=orcamento,
        itens=itens,
        itens_produtos=itens_produtos,
        itens_servicos=itens_servicos,
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
