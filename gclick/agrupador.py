from typing import Dict, List, Any, Callable

def agrupar_por_responsavel(
    classificacao: Dict[str, List[Dict[str, Any]]],
    resolver_resp_fn: Callable[[Dict[str, Any]], List[Dict[str, Any]]]
) -> Dict[str, Dict[str, Any]]:
    """
    Retorna:
    {
      responsavel_key: {
         'meta': {id, apelido, email, ...},
         'vence_em_3_dias': [...],
         'vence_hoje': [...],
         'vencidas': [...]
      }
    }
    """
    agrupado: Dict[str, Dict[str, Any]] = {}

    for categoria, tarefas in classificacao.items():
        for t in tarefas:
            responsaveis = resolver_resp_fn(t)
            for r in responsaveis:
                key = f"{r.get('id')}|{r.get('apelido')}"
                if key not in agrupado:
                    agrupado[key] = {
                        "meta": r,
                        "vence_em_3_dias": [],
                        "vence_hoje": [],
                        "vencidas": []
                    }
                agrupado[key][categoria].append(t)

    return agrupado
