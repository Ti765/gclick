import os
import time
import requests

WEBHOOK_URL_ENV = "TEAMS_WEBHOOK_URL"

def is_teams_webhook_configured() -> bool:
    """Retorna True se a variável de ambiente TEAMS_WEBHOOK_URL estiver configurada."""
    return bool(os.environ.get(WEBHOOK_URL_ENV))


def enviar_teams_mensagem(texto: str, max_retries: int = 3, backoff: float = 1.5):
    """Envia uma mensagem simples via Incoming Webhook do Teams.

    Se a variável de ambiente `TEAMS_WEBHOOK_URL` não estiver configurada, a função
    levanta um RuntimeError com instruções claras sobre como configurar o fallback
    (definir a variável de ambiente ou usar o Bot Framework proativo).
    """
    url = os.environ.get(WEBHOOK_URL_ENV)
    if not url:
        raise RuntimeError(
            "TEAMS_WEBHOOK_URL não definido no ambiente. Para habilitar o fallback via Webhook, defina a variável de ambiente 'TEAMS_WEBHOOK_URL' com a URL do Incoming Webhook do Teams; "
            "ou habilite e inicialize o Bot Framework para envios proativos (cada usuário deve ter iniciado conversa com o bot)."
        )

    payload = {"text": texto}
    tentativa = 0
    while True:
        tentativa += 1
        try:
            resp = requests.post(url, json=payload, timeout=15)
            if resp.status_code >= 400:
                raise RuntimeError(f"HTTP {resp.status_code} -> {resp.text[:300]}")
            return resp.text
        except Exception:
            if tentativa >= max_retries:
                raise
            time.sleep(backoff * tentativa)
