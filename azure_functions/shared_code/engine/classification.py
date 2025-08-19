from datetime import date, timedelta
from typing import Dict, List, Any, Optional

def classificar_tarefa_individual(tarefa: Dict[str, Any], hoje: date, dias_proximos: int = 3) -> Optional[str]:
    """
    Classifica uma única tarefa com base na data de vencimento.
    
    Args:
        tarefa: Dicionário com dados da tarefa
        hoje: Data atual
        dias_proximos: Número de dias futuros a considerar
        
    Returns:
        str: "vencidas" (vencimento anterior a hoje, mas não mais que 1 dia)
             "vence_hoje" (vencimento hoje)
             "vence_em_3_dias" (vencimento em até X dias)
             None (fora do período de interesse ou mais de 1 dia vencida)
    """
    # Tenta obter a data já parseada
    dt = tarefa.get("_dt_dataVencimento")
    
    if not dt:
        # Tenta parsear da string
        dv = tarefa.get("dataVencimento")
        if dv:
            try:
                from datetime import datetime
                dt = datetime.strptime(dv, "%Y-%m-%d").date()
            except Exception:
                return None
    
    if not dt:
        return None
    
    # Regra de classificação refinada para Sprint 2:
    # - Tarefas com mais de 1 dia de atraso são ignoradas
    # - Tarefas vencidas até 1 dia atrás são incluídas em "vencidas"
    # - Tarefas que vencem hoje são "vence_hoje"
    # - Tarefas que vencem nos próximos X dias são "vence_em_3_dias"
    
    if dt < hoje - timedelta(days=1):
        # Mais de 1 dia de atraso - não incluir
        return None
    elif dt < hoje:
        # Até 1 dia de atraso
        return "vencidas"
    elif dt == hoje:
        return "vence_hoje"
    elif dt <= hoje + timedelta(days=dias_proximos):
        return "vence_em_3_dias"
        
    return None


def classificar_por_vencimento(tarefas, hoje: date, dias_proximos: int = 3):
    """
    Retorna dicionário com listas:
      - vencidas (até 1 dia de atraso)
      - vence_hoje
      - vence_em_3_dias (1 .. dias_proximos)
    Considera campo 'dataVencimento' (string YYYY-MM-DD) ou _dt_dataVencimento.
    Ignora tarefas sem data de vencimento ou com mais de 1 dia de atraso.
    """
    vencidas = []
    vence_hoje = []
    vence_em_3 = []

    for t in tarefas:
        classificacao = classificar_tarefa_individual(t, hoje, dias_proximos)
        
        if classificacao == "vencidas":
            vencidas.append(t)
        elif classificacao == "vence_hoje":
            vence_hoje.append(t)
        elif classificacao == "vence_em_3_dias":
            vence_em_3.append(t)
        # Se classificacao for None, a tarefa é ignorada

    return {
        "vencidas": vencidas,
        "vence_hoje": vence_hoje,
        "vence_em_3_dias": vence_em_3
    }


def resumir_contagens(classif: Dict[str, List[Any]]) -> Dict[str, int]:
    return {
        "vencidas": len(classif.get("vencidas", [])),
        "vence_hoje": len(classif.get("vence_hoje", [])),
        "vence_em_3_dias": len(classif.get("vence_em_3_dias", [])),
    }
