from datetime import date, timedelta, datetime
from typing import Dict, List, Any, Optional
import logging

# Timezone imports com fallback
try:
    from zoneinfo import ZoneInfo
except ImportError:
    try:
        from backports.zoneinfo import ZoneInfo
    except ImportError:
        ZoneInfo = None

# Configuração para timezone BRT (Brasília)
BRT_TIMEZONE = ZoneInfo("America/Sao_Paulo") if ZoneInfo else None

def obter_data_atual_brt() -> date:
    """Obtém a data atual no timezone BRT (Brasília)."""
    if BRT_TIMEZONE:
        agora_brt = datetime.now(BRT_TIMEZONE)
        return agora_brt.date()
    else:
        # Fallback para UTC/local se zoneinfo não disponível
        logging.warning("ZoneInfo não disponível, usando data local")
        return date.today()


def separar_tarefas_overdue(tarefas: List[Dict[str, Any]], hoje: Optional[date] = None) -> Dict[str, List[Dict[str, Any]]]:
    """
    Separa tarefas entre normais (para notificação) e overdue (para relatório).
    
    Args:
        tarefas: Lista de tarefas
        hoje: Data atual (opcional, usar data BRT se None)
        
    Returns:
        Dict com "normais" (até 1 dia atraso) e "overdue" (mais de 1 dia atraso)
    """
    if hoje is None:
        hoje = obter_data_atual_brt()
    
    normais = []
    overdue = []
    
    for tarefa in tarefas:
        # Tenta obter a data já parseada
        dt = tarefa.get("_dt_dataVencimento")
        
        if not dt:
            # Tenta parsear da string
            dv = tarefa.get("dataVencimento")
            if dv:
                try:
                    dt = datetime.strptime(dv, "%Y-%m-%d").date()
                except Exception:
                    # Se não conseguir parsear, considera normal (será ignorada na classificação)
                    normais.append(tarefa)
                    continue
            else:
                # Sem data de vencimento, considera normal
                normais.append(tarefa)
                continue
        
        # Classifica baseado no atraso
        if dt < hoje - timedelta(days=1):
            # Mais de 1 dia de atraso - vai para relatório
            overdue.append(tarefa)
        else:
            # Até 1 dia de atraso ou futuro - vai para notificação normal
            normais.append(tarefa)
    
    return {
        "normais": normais,
        "overdue": overdue
    }


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


def classificar_por_vencimento(tarefas, hoje: Optional[date] = None, dias_proximos: int = 3):
    """
    Retorna dicionário com listas:
      - vencidas (até 1 dia de atraso)
      - vence_hoje
      - vence_em_3_dias (1 .. dias_proximos)
    Considera campo 'dataVencimento' (string YYYY-MM-DD) ou _dt_dataVencimento.
    Ignora tarefas sem data de vencimento ou com mais de 1 dia de atraso.
    
    Args:
        tarefas: Lista de tarefas a classificar
        hoje: Data atual (opcional, usar data BRT se None)
        dias_proximos: Número de dias futuros a considerar
    """
    if hoje is None:
        hoje = obter_data_atual_brt()
    
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
