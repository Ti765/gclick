# gclick/departamentos.py
import requests
import time
from typing import List, Dict, Any
from .auth import get_access_token
from ..config.logging_config import setup_logger

logger = setup_logger(__name__)

BASE = "https://api.gclick.com.br"

# Cache simples em memória
_cache_departamentos = {"data": None, "timestamp": 0, "ttl": 3600}  # 1 hora

def listar_departamentos(page: int = 0, size: int = 100) -> List[Dict[str, Any]]:
    token = get_access_token()
    url = f"{BASE}/departamentos"
    params = {"page": page, "size": size}
    headers = {"Authorization": f"Bearer {token}"}
    resp = requests.get(url, headers=headers, params=params, timeout=30)
    if resp.status_code >= 400:
        raise RuntimeError(f"Erro {resp.status_code} ao listar departamentos: {resp.text[:400]}")
    data = resp.json()
    content = data.get("content", [])
    return content

def get_departamentos_cached() -> List[Dict[str, Any]]:
    """
    Retorna departamentos com cache de 1 hora.
    Thread-safe para uso concorrente.
    
    Returns:
        Lista de departamentos ou lista vazia em caso de erro
    """
    now = time.time()
    cache = _cache_departamentos
    
    if cache["data"] is None or (now - cache["timestamp"]) > cache["ttl"]:
        try:
            cache["data"] = listar_departamentos(size=500)  # Buscar todos
            cache["timestamp"] = now
            logger.info(f"Cache de departamentos atualizado: {len(cache['data'])} itens")
        except Exception as e:
            logger.error(f"Erro ao cachear departamentos: {e}")
            if cache["data"] is None:
                cache["data"] = []
    
    return cache["data"]
