# Caminho: C:\Users\vlula\OneDrive\Área de Trabalho\Projetos Backup\GESTFLOW\apps\gestflow\mercado_pago_runtime.py
# Último recode: 2026-09-12 11:25 (America/Bahia)
# Motivo: Integrar cobranças PIX do GestFlow SaaS ao Mercado Pago no DEV, reaproveitando a comunicação e validação de webhook já validadas no LAVAGO.

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import uuid
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from mercadopago.webhook import InvalidWebhookSignatureError, WebhookSignatureValidator


MERCADO_PAGO_ORDERS_URL = "https://api.mercadopago.com/v1/orders"


class MercadoPagoErro(RuntimeError):
    pass


def criar_order_pix(
    valor,
    email,
    referencia_externa,
    nome_pagador="",
    modo_teste=False,
    expiracao="PT30M",
):
    token = _obter_access_token()
    referencia = _validar_referencia_externa(referencia_externa)
    valor_formatado = _formatar_valor(valor)

    pagador = {"email": str(email or "").strip()}
    if not pagador["email"]:
        raise MercadoPagoErro("E-mail do pagador é obrigatório para gerar o Pix.")

    if nome_pagador:
        partes_nome = str(nome_pagador).strip().split()
        if partes_nome:
            pagador["first_name"] = partes_nome[0]

    pagamento = {
        "amount": valor_formatado,
        "payment_method": {"id": "pix", "type": "bank_transfer"},
    }

    if _verdadeiro(modo_teste):
        valor_formatado = "50.00"
        pagamento["amount"] = valor_formatado
        pagador = {
            "email": "test_user_br@testuser.com",
            "first_name": "APRO",
        }
    elif expiracao:
        pagamento["expiration_time"] = expiracao

    dados = {
        "type": "online",
        "total_amount": valor_formatado,
        "external_reference": referencia,
        "processing_mode": "automatic",
        "transactions": {"payments": [pagamento]},
        "payer": pagador,
    }

    resposta = _requisitar(
        metodo="POST",
        url=MERCADO_PAGO_ORDERS_URL,
        token=token,
        dados=dados,
        idempotency_key=str(uuid.uuid4()),
    )
    return _resumir_order(resposta)


def consultar_order(order_id):
    token = _obter_access_token()
    identificador = str(order_id or "").strip()
    if not identificador:
        raise MercadoPagoErro("ID da cobrança Mercado Pago é obrigatório para consulta.")

    resposta = _requisitar(
        metodo="GET",
        url=f"{MERCADO_PAGO_ORDERS_URL}/{quote(identificador, safe='')}",
        token=token,
    )
    return _resumir_order(resposta)


def validar_assinatura_webhook(x_signature, x_request_id, data_id, secret=None):
    assinatura = str(x_signature or "").strip()
    request_id = str(x_request_id or "").strip()
    identificador = str(data_id or "").strip()
    segredo = str(secret or obter_webhook_secret()).strip()

    if not assinatura or not request_id or not identificador or not segredo:
        return False

    try:
        WebhookSignatureValidator.validate(
            assinatura,
            request_id,
            identificador,
            segredo,
        )
        return True
    except InvalidWebhookSignatureError:
        pass

    if not re.fullmatch(r"[A-Za-z0-9]+", identificador):
        return False

    timestamp = ""
    assinatura_v1 = ""
    for parte in assinatura.split(","):
        if "=" not in parte:
            continue
        chave, valor = parte.split("=", 1)
        chave = chave.strip().lower()
        valor = valor.strip()
        if chave == "ts":
            timestamp = valor
        elif chave == "v1":
            assinatura_v1 = valor

    if not timestamp or not assinatura_v1:
        return False

    manifesto = (
        f"id:{identificador.lower()};"
        f"request-id:{request_id};"
        f"ts:{timestamp};"
    )
    assinatura_calculada = hmac.new(
        segredo.encode("utf-8"),
        manifesto.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    return hmac.compare_digest(assinatura_calculada, assinatura_v1)


def obter_webhook_secret() -> str:
    return str(os.getenv("MERCADO_PAGO_WEBHOOK_SECRET", "") or "").strip()


def modo_teste_mercado_pago() -> bool:
    return _verdadeiro(os.getenv("MERCADO_PAGO_TEST_MODE", "0"))


def integracao_mercado_pago_configurada() -> bool:
    return bool(str(os.getenv("MERCADO_PAGO_ACCESS_TOKEN", "") or "").strip())


def _obter_access_token() -> str:
    token = str(os.getenv("MERCADO_PAGO_ACCESS_TOKEN", "") or "").strip()
    if not token:
        raise MercadoPagoErro("MERCADO_PAGO_ACCESS_TOKEN não está configurado no ambiente.")
    return token


def _formatar_valor(valor) -> str:
    try:
        decimal = Decimal(str(valor)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except (InvalidOperation, TypeError, ValueError) as erro:
        raise MercadoPagoErro("Valor inválido para pagamento Pix.") from erro

    if decimal <= 0:
        raise MercadoPagoErro("O valor do pagamento deve ser maior que zero.")
    return f"{decimal:.2f}"


def _validar_referencia_externa(referencia) -> str:
    valor = str(referencia or "").strip()
    if not valor:
        raise MercadoPagoErro("Referência externa do pagamento é obrigatória.")
    if len(valor) > 64 or not re.fullmatch(r"[A-Za-z0-9_-]+", valor):
        raise MercadoPagoErro(
            "Referência externa inválida. Use até 64 caracteres com letras, números, hífen ou sublinhado."
        )
    return valor


def _timeout_segundos() -> int:
    try:
        return max(int(os.getenv("MERCADO_PAGO_TIMEOUT_SECONDS", "15") or 15), 3)
    except (TypeError, ValueError):
        return 15


def _requisitar(metodo, url, token, dados=None, idempotency_key=None):
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}",
        "User-Agent": "GestFlow/1.0",
    }
    if idempotency_key:
        headers["X-Idempotency-Key"] = idempotency_key

    corpo = json.dumps(dados).encode("utf-8") if dados is not None else None
    requisicao = Request(url, data=corpo, method=metodo, headers=headers)

    try:
        with urlopen(requisicao, timeout=_timeout_segundos()) as resposta:
            conteudo = resposta.read().decode("utf-8")
            return json.loads(conteudo) if conteudo else {}
    except HTTPError as erro:
        detalhe = erro.read().decode("utf-8", errors="replace")[:1500]
        raise MercadoPagoErro(
            f"Mercado Pago recusou a requisição com status {erro.code}. {detalhe[:300]}"
        ) from erro
    except (URLError, TimeoutError) as erro:
        raise MercadoPagoErro("Não foi possível conectar ao Mercado Pago.") from erro
    except json.JSONDecodeError as erro:
        raise MercadoPagoErro("Resposta inválida recebida do Mercado Pago.") from erro


def _resumir_order(order):
    pagamentos = order.get("transactions", {}).get("payments", []) or []
    pagamento = pagamentos[0] if pagamentos else {}
    metodo = pagamento.get("payment_method", {}) or {}

    return {
        "order_id": order.get("id"),
        "external_reference": order.get("external_reference"),
        "total_amount": order.get("total_amount"),
        "order_status": order.get("status"),
        "order_status_detail": order.get("status_detail"),
        "payment_id": pagamento.get("id"),
        "payment_status": pagamento.get("status"),
        "payment_status_detail": pagamento.get("status_detail"),
        "payment_method_id": metodo.get("id"),
        "payment_method_type": metodo.get("type"),
        "ticket_url": metodo.get("ticket_url"),
        "qr_code": metodo.get("qr_code"),
        "qr_code_base64": metodo.get("qr_code_base64"),
    }


def _verdadeiro(valor) -> bool:
    return str(valor or "").strip().lower() in {"1", "true", "sim", "yes", "on"}
