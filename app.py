# Caminho: C:\Users\vlula\OneDrive\Área de Trabalho\Projetos Backup\GESTFLOW\app.py
# Último recode: 2026-06-13 15:08 (America/Bahia)
# Motivo: Adicionar rota POST de Clientes para receber o formulário inicial de cadastro,
#         mantendo Dashboard (/), listagem de Clientes (/clientes), healthcheck (/health)
#         e webhook Twilio (/bot) ativos.

from __future__ import annotations

import html
from flask import Flask, Response, redirect, render_template, request, url_for

import config

app = Flask(__name__)


def _twiml_message(text: str) -> str:
    safe = html.escape(text or "")
    return f'<?xml version="1.0" encoding="UTF-8"?><Response><Message>{safe}</Message></Response>'


@app.get("/")
def dashboard() -> str:
    return render_template("dashboard.html")


@app.get("/clientes")
def clientes() -> str:
    return render_template("clientes.html")


@app.post("/clientes")
def salvar_cliente() -> Response:
    cliente = {
        "nome": (request.form.get("cliente_nome") or "").strip(),
        "documento": (request.form.get("cliente_documento") or "").strip(),
        "telefone": (request.form.get("cliente_telefone") or "").strip(),
        "cidade": (request.form.get("cliente_cidade") or "").strip(),
        "status": (request.form.get("cliente_status") or "").strip(),
        "email": (request.form.get("cliente_email") or "").strip(),
    }

    # Banco SQLite ainda sera implantado no proximo passo.
    # Por enquanto a rota apenas recebe os dados do formulario e retorna para a tela Clientes.
    return redirect(url_for("clientes"))


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


if __name__ == "__main__":
    # Somente para uso local. No Railway usaremos o wsgi.py com waitress.
    app.run(host="0.0.0.0", port=5000, debug=config.DEBUG)
