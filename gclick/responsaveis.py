import os
import time
import requests
from typing import List, Dict, Any, Optional
from .auth import get_access_token

# Reuso simples de token em memória (válido ~1h)
_TOKEN_CACHE = {"token": None, "ts": 0, "ttl": 3200}

def _token():
    now = time.time()
    if not _TOKEN_CACHE["token"] or now - _TOKEN_CACHE["ts"] > _TOKEN_CACHE["ttl"]:
        _TOKEN_CACHE["token"] = get_access_token()
        _TOKEN_CACHE["ts"] = now
    return _TOKEN_CACHE["token"]

def _headers():
    return {"Authorization": f"Bearer {_token()}"}

def listar_responsaveis_tarefa(
    tarefa_id: str,
    timeout: int = 8,
    retries: int = 3,
    backoff_base: float = 1.0,
    verbose: bool = False
) -> List[Dict[str, Any]]:
    """
    Consulta /tarefas/{id}/responsaveis com retentativas.
    Retorna lista (possivelmente vazia).
    """
    url = f"https://api.gclick.com.br/tarefas/{tarefa_id}/responsaveis"

    attempt = 0
    while attempt < retries:
        attempt += 1
        try:
            resp = requests.get(url, headers=_headers(), timeout=timeout)
            if resp.status_code == 200:
                data = resp.json()
                if isinstance(data, list):
                    if verbose:
                        print(f"[RESP] tarefa={tarefa_id} -> {len(data)} responsável(is).")
                    return data
                if verbose:
                    print(f"[RESP][WARN] tarefa={tarefa_id} resposta não é lista. body={data}")
                return []
            else:
                if verbose:
                    print(f"[RESP][HTTP {resp.status_code}] tarefa={tarefa_id} body={resp.text[:180]}")
        except (requests.Timeout, requests.ConnectionError) as e:
            if verbose:
                print(f"[RESP][TIMEOUT/CONN] tarefa={tarefa_id} tent={attempt}/{retries} erro={e}")
        except Exception as e:
            if verbose:
                print(f"[RESP][EXC] tarefa={tarefa_id} tent={attempt}/{retries} erro={e}")

        if attempt < retries:
            sleep_for = backoff_base * (2 ** (attempt - 1))
            time.sleep(sleep_for)

    if verbose:
        print(f"[RESP][FAIL] tarefa={tarefa_id} após {retries} tentativas.")
    return []

def normalizar_responsavel(raw: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": raw.get("id"),
        "apelido": raw.get("apelido"),
        "nome": raw.get("nome"),
        "email": raw.get("email"),
        "ativo": raw.get("ativo")
    }
