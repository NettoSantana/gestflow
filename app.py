# Caminho: C:\Users\vlula\OneDrive\Área de Trabalho\Projetos Backup\GESTFLOW\app.py
# Último recode: 2026-06-13 18:48 (America/Bahia)
# Motivo: Adicionar base de rotas, funções SQLite e tabela de produtos,
#         mantendo Dashboard (/), Clientes (/clientes), Fornecedores (/fornecedores),
#         Funcionários (/funcionarios), SQLite, visualização, edição, exclusão,
#         healthcheck (/health) e webhook Twilio (/bot) ativos.

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
