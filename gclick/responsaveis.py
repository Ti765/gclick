import os
import time
import requests
from typing import List, Dict, Any, Optional
from .auth import get_access_token

def _headers():
    return {"Authorization": f"Bearer {get_access_token()}"}

def listar_responsaveis_tarefa(
    tarefa_id: str,
    timeout: int = 8,
    retries: int = 3,
    backoff_base: float = 1.0,
    verbose: bool = False
) -> List[Dict[str, Any]]:
    """
    Consulta /tarefas/{id}/responsaveis com tratamento robusto de erros.
    Retorna lista (possivelmente vazia).
    """
    url = f"https://api.gclick.com.br/tarefas/{tarefa_id}/responsaveis"

    attempt = 0
    last_status_code = None
    
    while attempt < retries:
        attempt += 1
        try:
            resp = requests.get(url, headers=_headers(), timeout=timeout)
            last_status_code = resp.status_code
            
            if resp.status_code == 200:
                data = resp.json()
                if isinstance(data, list):
                    if verbose:
                        print(f"[RESP] tarefa={tarefa_id} -> {len(data)} responsável(is).")
                    return data
                if verbose:
                    print(f"[RESP][WARN] tarefa={tarefa_id} resposta não é lista. body={data}")
                return []
            elif resp.status_code == 500:
                # Erro específico do servidor - não retry agressivo
                if verbose:
                    print(f"[RESP][500] tarefa={tarefa_id} - endpoint pode não existir ou tarefa inválida")
                return []
            elif resp.status_code == 404:
                # Tarefa não encontrada ou sem responsáveis
                if verbose:
                    print(f"[RESP][404] tarefa={tarefa_id} - não encontrada ou sem responsáveis")
                return []
            else:
                if verbose:
                    print(f"[RESP][HTTP {resp.status_code}] tarefa={tarefa_id} body={resp.text[:180]}")
        except (requests.Timeout, requests.ConnectionError) as e:
            if verbose:
                print(f"[RESP][TIMEOUT/CONN] tarefa={tarefa_id} tent={attempt}/{retries} erro={e}")
        except requests.RequestException as e:
            if verbose:
                print(f"[RESP][EXC] tarefa={tarefa_id} tent={attempt}/{retries} erro={e}")

        # Não retry em erros definitivos (500, 404)
        if last_status_code in [500, 404]:
            break
            
        if attempt < retries:
            sleep_for = backoff_base * (2 ** (attempt - 1))
            time.sleep(sleep_for)

    if verbose:
        print(f"[RESP][FAIL] tarefa={tarefa_id} após {attempt} tentativas (último status: {last_status_code}).")
    return []

def normalizar_responsavel(raw: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": raw.get("id"),
        "apelido": raw.get("apelido"),
        "nome": raw.get("nome"),
        "email": raw.get("email"),
        "ativo": raw.get("ativo")
    }
