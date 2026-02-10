# Caminho: C:\Users\vlula\OneDrive\Área de Trabalho\Projetos Backup\GESTFLOW\modules\whatsapp.py
# Último recode: 2026-02-09 20:56 (America/Bahia)
# Motivo: Criar handler mínimo do WhatsApp para validar webhook Twilio
#         (entrada -> processamento -> resposta), sem estado e sem banco.

from __future__ import annotations


def handle_message(from_number: str, body: str) -> str:
    """
    Handler mínimo do WhatsApp.
    Recebe o número de origem e o texto da mensagem e retorna uma resposta fixa.
    """
    text = (body or "").strip().lower()

    if not text:
        return "Mensagem vazia recebida. Digite qualquer coisa para testar o GESTFLOW."

    return (
        "GESTFLOW está ativo ✅\n\n"
        f"Origem: {from_number}\n"
        f"Mensagem: {body}\n\n"
        "Webhook funcionando corretamente."
    )
