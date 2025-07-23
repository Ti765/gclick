from datetime import date
from typing import Dict, List, Any

def classificar_por_vencimento(tarefas, hoje: date, dias_proximos: int = 3):
    """
    Retorna dicionário com listas:
      - vencidas
      - vence_hoje
      - vence_em_3_dias (1 .. dias_proximos)
    Considera campo 'dataVencimento' (string YYYY-MM-DD) ou _dt_dataVencimento.
    Ignora tarefas sem data de vencimento.
    """
    vencidas = []
    vence_hoje = []
    vence_em_3 = []

    for t in tarefas:
        dt = t.get("_dt_dataVencimento")
        if not dt:
            # tentar parse manual se só string
            dv = t.get("dataVencimento")
            if dv:
                try:
                    from datetime import datetime
                    dt = datetime.strptime(dv, "%Y-%m-%d").date()
                except Exception:
                    dt = None
        if not dt:
            continue

        if dt < hoje:
            vencidas.append(t)
        elif dt == hoje:
            vence_hoje.append(t)
        else:
            delta = (dt - hoje).days
            if 1 <= delta <= dias_proximos:
                vence_em_3.append(t)

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
