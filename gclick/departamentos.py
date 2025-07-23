# gclick/departamentos.py
import requests
from typing import List, Dict, Any
from .auth import get_access_token

BASE = "https://api.gclick.com.br"

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
