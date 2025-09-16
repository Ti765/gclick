import os
import time
import requests

WEBHOOK_URL_ENV = "TEAMS_WEBHOOK_URL"

def enviar_teams_mensagem(texto: str, max_retries: int = 3, backoff: float = 1.5):
    url = os.environ.get(WEBHOOK_URL_ENV)
    if not url:
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
        except Exception as e:
            if tentativa >= max_retries:
                raise
            time.sleep(backoff * tentativa)
