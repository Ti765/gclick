import time
import requests
from typing import List, Dict, Any
from .auth import get_access_token
from azure_functions.shared_code.config.logging_config import setup_logger

logger = setup_logger(__name__)

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
                        logger.info(f"Tarefa {tarefa_id}: encontrado(s) {len(data)} responsável(is)")
                    return data
                if verbose:
                    logger.warning(f"Tarefa {tarefa_id}: resposta não é lista. body={data}")
                return []
            elif resp.status_code == 500:
                # Erro específico do servidor - não retry agressivo
                if verbose:
                    logger.warning(f"Tarefa {tarefa_id}: endpoint pode não existir ou tarefa inválida (HTTP 500)")
                return []
            elif resp.status_code == 404:
                # Tarefa não encontrada ou sem responsáveis
                if verbose:
                    logger.info(f"Tarefa {tarefa_id}: não encontrada ou sem responsáveis (HTTP 404)")
                return []
            else:
                if verbose:
                    logger.warning(f"Tarefa {tarefa_id}: erro HTTP {resp.status_code} - {resp.text[:180]}")
        except (requests.Timeout, requests.ConnectionError) as e:
            if verbose:
                logger.warning(f"Tarefa {tarefa_id}: timeout/erro conexão (tentativa {attempt}/{retries}) - {e}")
        except requests.RequestException as e:
            if verbose:
                logger.warning(f"Tarefa {tarefa_id}: erro na requisição (tentativa {attempt}/{retries}) - {e}")

        # Não retry em erros definitivos (500, 404)
        if last_status_code in [500, 404]:
            break
            
        if attempt < retries:
            sleep_for = backoff_base * (2 ** (attempt - 1))
            time.sleep(sleep_for)

    if verbose:
        logger.error(f"Tarefa {tarefa_id}: falha após {attempt} tentativas (último status: {last_status_code})")
    return []

def normalizar_responsavel(raw: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": raw.get("id"),
        "apelido": raw.get("apelido"),
        "nome": raw.get("nome"),
        "email": raw.get("email"),
        "ativo": raw.get("ativo")
    }
