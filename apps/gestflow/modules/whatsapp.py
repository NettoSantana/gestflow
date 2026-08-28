# Caminho: C:\Users\vlula\OneDrive\Área de Trabalho\Projetos Backup\GESTFLOW\apps\gestflow\modules\whatsapp.py
# Último recode: 2026-08-21 06:43 (America/Bahia)
# Motivo: Migrar para a estrutura consolidada GESTFLOW + INDFLOW na branch DEV, preservando o conteúdo funcional validado.

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
