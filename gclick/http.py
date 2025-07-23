import os
import time
import json
import requests
from .auth import get_access_token

BASE_URL = "https://api.gclick.com.br"
DEBUG = os.getenv("GCLICK_DEBUG", "0") == "1"

class GClickHTTPError(RuntimeError):
    def __init__(self, message, status=None, url=None, body=None, trace_id=None):
        super().__init__(message)
        self.status = status
        self.url = url
        self.body = body
        self.trace_id = trace_id

def _full_url(path: str) -> str:
    if path.startswith("http"):
        return path
    return f"{BASE_URL}/{path.lstrip('/')}"

def gclick_get(path: str, params=None, retry=True, max_retries=2, backoff=1.5):
    """
    GET simples com:
      - renovação de token em 401/403
      - pequenas tentativas extras para 502/503/504
    """
    url = _full_url(path)
    attempt = 0
    while True:
        attempt += 1
        token = get_access_token(force=False)
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json"
        }
        resp = requests.get(url, headers=headers, params=params, timeout=40)

        if resp.status_code in (401, 403) and retry:
            # Força renovação token
            if DEBUG:
                print(f"[DEBUG] Renovando token após {resp.status_code} em {url}")
            get_access_token(force=True)
            if attempt <= max_retries:
                time.sleep(0.8)
                continue

        if resp.status_code >= 400:
            transient = resp.status_code in (500, 502, 503, 504)
            body_json = None
            trace_id = None
            try:
                body_json = resp.json()
                if isinstance(body_json, dict):
                    trace_id = body_json.get("traceId")
            except Exception:
                body_json = resp.text

            if DEBUG:
                print(f"[DEBUG] Falha GET {url} params={params} status={resp.status_code} body={body_json}")

            if transient and attempt <= max_retries:
                time.sleep(backoff * attempt)
                continue

            raise GClickHTTPError(
                f"Erro {resp.status_code} em {url}",
                status=resp.status_code,
                url=url,
                body=body_json,
                trace_id=trace_id
            )

        try:
            data = resp.json()
        except ValueError:
            raise GClickHTTPError("Resposta não JSON", status=resp.status_code, url=url, body=resp.text)

        if DEBUG:
            if isinstance(data, dict):
                print(f"[DEBUG] OK GET {url} params={params} -> chaves_top={list(data.keys())[:6]}")
            else:
                print(f"[DEBUG] OK GET {url} (lista) len={len(data) if isinstance(data, list) else 'n/a'}")
        return data
