from datetime import date, timedelta
from typing import List, Dict, Any

FINALIZADOS = {"C", "D", "F", "O"}  # Concluído, Dispensado, Finalizado, Retificado

def classificar_vencimento(tarefas: List[Dict[str, Any]], hoje: date) -> Dict[str, List[Dict[str, Any]]]:
    """
    Retorna dicionário com listas: vencidas, vence_hoje, vence_em_3_dias.
    Ignora tarefas finalizadas para alertas.
    """
    out = {"vencidas": [], "vence_hoje": [], "vence_em_3_dias": []}
    limite_3 = hoje + timedelta(days=3)

    for t in tarefas:
        dv = t.get("_dt_dataVencimento")
        if not dv:
            continue
        status = t.get("status")
        if status in FINALIZADOS:
            continue

        if dv < hoje:
            out["vencidas"].append(t)
        elif dv == hoje:
            out["vence_hoje"].append(t)
        elif hoje < dv <= limite_3:
            out["vence_em_3_dias"].append(t)

    return out
