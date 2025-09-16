import requests
from typing import Dict, Any
from .auth import get_access_token
from azure_functions.shared_code.config.logging_config import setup_logger

logger = setup_logger(__name__)

def _headers() -> Dict[str, str]:
    return {"Authorization": f"Bearer {get_access_token()}"}

def obter_tarefa_detalhes(task_id: str) -> Dict[str, Any]:
    """Obtém os detalhes de uma tarefa específica"""
    url = f"https://api.gclick.com.br/tarefas/{task_id}"
    resp = requests.get(url, headers=_headers(), timeout=40)
    if not resp.ok:
        raise RuntimeError(
            f"Erro {resp.status_code} GET {url} body={resp.text[:500]}"
        )
    return resp.json()

def resumir_detalhes_para_card(task_data: Dict[str, Any]) -> str:
    """Formata os detalhes da tarefa para exibição no card do Teams"""
    # Campos chave para mostrar
    campos = [
        ("Descrição", task_data.get("descricao")),
        ("Categoria", task_data.get("categoriaObrigacao", {}).get("nome")),
        ("Assunto", task_data.get("assunto")),
        ("Status", task_data.get("statusDescricao", task_data.get("status"))),
        ("Data Vencimento", task_data.get("dataVencimento")),
        ("Empresa", task_data.get("razaoSocial")),
    ]
    
    # Filtrar campos que existem e tem valor
    campos_validos = [(k, v) for k, v in campos if v]
    
    # Formatar em Markdown
    if not campos_validos:
        return "Sem detalhes disponíveis"
        
    return "\n".join([f"**{k}:** {v}" for k, v in campos_validos])