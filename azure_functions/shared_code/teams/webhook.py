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
    retorna sem exceções (apenas loga) para evitar spam de erros quando o Bot
    Framework for a fonte de envio preferencial (especialmente em TEST_MODE).
    """
    url = os.environ.get(WEBHOOK_URL_ENV)
    if not url:
        # Não lançar exceção para não poluir logs; os chamadores devem preferir o Bot
        # Framework quando disponível. Apenas retornamos None como sinal que nada foi enviado.
        print("[WEBHOOK] TEAMS_WEBHOOK_URL não configurado — salto do envio via webhook.")
        return None

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
