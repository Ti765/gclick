import os
import time
import requests
from typing import Optional
from .auth import get_access_token
from ..config.logging_config import setup_logger

logger = setup_logger(__name__)

BASE_URL = "https://api.gclick.com.br"
DEBUG = os.getenv("GCLICK_DEBUG", "0") == "1"
# Configuração de SSL verify via environment variable
SSL_VERIFY = os.getenv("GCLICK_SSL_VERIFY", "true").lower() in ("1", "true", "yes")

# Session reutilizável para melhor performance
_http_session: Optional[requests.Session] = None

def get_http_session() -> requests.Session:
    """
    Retorna uma session HTTP reutilizável para melhor performance.
    Thread-safe para Azure Functions.
    """
    global _http_session
    if _http_session is None:
        _http_session = requests.Session()
        # Configurações de connection pooling
        adapter = requests.adapters.HTTPAdapter(
            pool_connections=10,
            pool_maxsize=20,
            max_retries=0  # Controlamos retry manualmente
        )
        _http_session.mount('http://', adapter)
        _http_session.mount('https://', adapter)
        
        # Headers padrão
        _http_session.headers.update({
            'User-Agent': 'GClick-Teams-Bot/1.0',
            'Accept': 'application/json'
        })
        
        logger.debug("HTTP Session criada com connection pooling")
    
    return _http_session

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
      - reutilização de conexões HTTP via Session
    """
    url = _full_url(path)
    session = get_http_session()
    attempt = 0
    
    while True:
        attempt += 1
        token = get_access_token(force=False)
        headers = {
            "Authorization": f"Bearer {token}",
        }
        
        resp = session.get(url, headers=headers, params=params, timeout=40, verify=SSL_VERIFY)

        if resp.status_code in (401, 403) and retry:
            # Força renovação token
            if DEBUG:
                logger.debug(f"Renovando token após {resp.status_code} em {url}")
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
                logger.debug(f"Falha GET {url} params={params} status={resp.status_code} body={body_json}")

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
                logger.debug(f"OK GET {url} params={params} -> chaves_top={list(data.keys())[:6]}")
            else:
                logger.debug(f"OK GET {url} (lista) len={len(data) if isinstance(data, list) else 'n/a'}")
        return data
