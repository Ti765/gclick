"""
Módulo para criação de cartões adaptativos (Adaptive Cards) para o Teams.

Este módulo fornece funções para criar cartões interativos que são enviados
aos usuários via bot do Teams, oferecendo uma experiência mais rica que mensagens de texto simples.
"""

import json
from typing import Dict, Any, Optional
from datetime import datetime, date


def create_task_notification_card(tarefa: Dict[str, Any], responsavel: Dict[str, Any]) -> str:
    """
    Cria um Adaptive Card para notificação de tarefa/obrigação fiscal.
    
    Args:
        tarefa: Dicionário com dados da tarefa (id, nome, dataVencimento, etc)
        responsavel: Dicionário com dados do responsável (id, nome, apelido, etc)
        
    Returns:
        str: JSON do Adaptive Card formatado
    """
    # Extrair dados da tarefa
    id_tarefa = tarefa.get("id", "")
    nome_tarefa = tarefa.get("nome", "Tarefa sem nome")
    data_vencimento = tarefa.get("dataVencimento", "")
    status = tarefa.get("_statusLabel", tarefa.get("status", ""))
    
    # Extrair dados do responsável
    nome_responsavel = responsavel.get("nome", responsavel.get("apelido", ""))
    
    # URL para acessar a tarefa no G-Click
    url_tarefa = f"https://app.gclick.com.br/tarefas/{id_tarefa}"
    
    # Determinar cor e ícone baseado na proximidade do vencimento
    cor_status, icone_status = _determine_urgency_style(data_vencimento)
    
    card = {
        "type": "AdaptiveCard",
        "version": "1.3",
        "body": [
            {
                "type": "Container",
                "style": "emphasis",
                "items": [
                    {
                        "type": "ColumnSet",
                        "columns": [
                            {
                                "type": "Column",
                                "width": "auto",
                                "items": [
                                    {
                                        "type": "TextBlock",
                                        "text": icone_status,
                                        "size": "Large"
                                    }
                                ]
                            },
                            {
                                "type": "Column",
                                "width": "stretch",
                                "items": [
                                    {
                                        "type": "TextBlock",
                                        "text": "Obrigação Fiscal Pendente",
                                        "weight": "Bolder",
                                        "size": "Medium"
                                    }
                                ]
                            }
                        ]
                    }
                ]
            },
            {
                "type": "TextBlock",
                "text": nome_tarefa,
                "wrap": True,
                "size": "Large",
                "weight": "Bolder",
                "color": cor_status
            },
            {
                "type": "FactSet",
                "facts": [
                    {
                        "title": "ID da Tarefa:",
                        "value": id_tarefa
                    },
                    {
                        "title": "Vencimento:",
                        "value": _format_date_for_display(data_vencimento)
                    },
                    {
                        "title": "Status:",
                        "value": status
                    },
                    {
                        "title": "Responsável:",
                        "value": nome_responsavel
                    }
                ]
            },
            {
                "type": "TextBlock",
                "text": _get_urgency_message(data_vencimento),
                "wrap": True,
                "color": cor_status
            }
        ],
        "actions": [
            {
                "type": "Action.OpenUrl",
                "title": "📋 Ver no G-Click",
                "url": url_tarefa
            },
            {
                "type": "Action.ShowCard",
                "title": "📝 Detalhes",
                "card": {
                    "type": "AdaptiveCard",
                    "version": "1.3",
                    "body": [
                        {
                            "type": "TextBlock",
                            "text": f"**{nome_tarefa}**",
                            "wrap": True,
                            "weight": "Bolder"
                        },
                        {
                            "type": "TextBlock",
                            "text": f"Esta obrigação fiscal está sob sua responsabilidade e requer atenção.",
                            "wrap": True
                        },
                        {
                            "type": "TextBlock",
                            "text": f"**Próximos passos:**\n- Acesse o G-Click para verificar detalhes\n- Verifique documentos necessários\n- Execute as ações pendentes",
                            "wrap": True
                        }
                    ]
                }
            },
            {
                "type": "Action.Submit",
                "title": "✔ Finalizar",
                "data": {
                    "action": "finalizar",
                    "taskId": id_tarefa
                }
            },
            {
                "type": "Action.Submit",
                "title": "✖ Dispensar",
                "data": {
                    "action": "dispensar", 
                    "taskId": id_tarefa
                }
            }
        ]
    }
    
    return json.dumps(card, ensure_ascii=False, indent=2)


def create_summary_notification_card(resumo: Dict[str, Any], responsavel: str) -> str:
    """
    Cria um Adaptive Card para resumo de múltiplas obrigações.
    
    Args:
        resumo: Dicionário com resumo das obrigações (contadores, listas, etc)
        responsavel: Nome/apelido do responsável
        
    Returns:
        str: JSON do Adaptive Card formatado
    """
    counts = resumo.get("counts", {})
    vencidas = counts.get("vencidas", 0)
    vence_hoje = counts.get("vence_hoje", 0)
    vence_proximos = counts.get("vence_em_3_dias", 0)
    
    total_pendentes = vencidas + vence_hoje + vence_proximos
    
    # CORRIGIDO: Determinar cor baseada na urgência (minúsculo)
    if vencidas > 0:
        cor_principal = "attention"
        icone = "⚠️"
    elif vence_hoje > 0:
        cor_principal = "warning"
        icone = "🕐"
    else:
        cor_principal = "good"
        icone = "📅"
    
    card = {
        "type": "AdaptiveCard",
        "version": "1.3",
        "body": [
            {
                "type": "Container",
                "style": "emphasis",
                "items": [
                    {
                        "type": "ColumnSet",
                        "columns": [
                            {
                                "type": "Column",
                                "width": "auto",
                                "items": [
                                    {
                                        "type": "TextBlock",
                                        "text": icone,
                                        "size": "Large"
                                    }
                                ]
                            },
                            {
                                "type": "Column",
                                "width": "stretch",
                                "items": [
                                    {
                                        "type": "TextBlock",
                                        "text": f"Resumo de Obrigações - {responsavel}",
                                        "weight": "Bolder",
                                        "size": "Medium"
                                    }
                                ]
                            }
                        ]
                    }
                ]
            },
            {
                "type": "TextBlock",
                "text": f"**{total_pendentes} obrigação(ões) pendente(s)**",
                "size": "Large",
                "weight": "Bolder",
                "color": cor_principal
            }
        ],
        "actions": [
            {
                "type": "Action.OpenUrl",
                "title": "🔍 Ver Todas no G-Click",
                "url": "https://app.gclick.com.br/tarefas"
            }
        ]
    }
    
    # Adicionar detalhes se houver tarefas pendentes
    if total_pendentes > 0:
        detalhes = []
        
        if vencidas > 0:
            detalhes.append({
                "type": "TextBlock",
                "text": f"🔴 **{vencidas}** vencida(s)",
                "color": "attention"
            })
            
        if vence_hoje > 0:
            detalhes.append({
                "type": "TextBlock", 
                "text": f"🟡 **{vence_hoje}** vence(m) hoje",
                "color": "warning"
            })
            
        if vence_proximos > 0:
            detalhes.append({
                "type": "TextBlock",
                "text": f"🟢 **{vence_proximos}** vence(m) nos próximos dias",
                "color": "good"
            })
            
        card["body"].extend(detalhes)
    
    return json.dumps(card, ensure_ascii=False, indent=2)


def _determine_urgency_style(data_vencimento: str) -> tuple[str, str]:
    """
    Determina a cor e ícone baseado na proximidade do vencimento.
    
    Args:
        data_vencimento: Data de vencimento no formato YYYY-MM-DD
        
    Returns:
        tuple: (cor, icone) para usar no card
    """
    if not data_vencimento:
        return "default", "📋"
    
    try:
        dt_venc = datetime.strptime(data_vencimento, "%Y-%m-%d").date()
        hoje = date.today()
        
        if dt_venc < hoje:
            return "attention", "🔴"  # Vencida
        elif dt_venc == hoje:
            return "warning", "🟡"   # Vence hoje
        else:
            delta = (dt_venc - hoje).days
            if delta <= 3:
                return "good", "🟢"  # Vence em breve
            else:
                return "default", "📅"  # Futuro
                
    except Exception:
        return "default", "📋"


def _format_date_for_display(data_vencimento: str) -> str:
    """
    Formata a data para exibição mais amigável.
    
    Args:
        data_vencimento: Data no formato YYYY-MM-DD
        
    Returns:
        str: Data formatada para exibição
    """
    if not data_vencimento:
        return "Data não informada"
    
    try:
        dt = datetime.strptime(data_vencimento, "%Y-%m-%d")
        return dt.strftime("%d/%m/%Y")
    except Exception:
        return data_vencimento


def _get_urgency_message(data_vencimento: str) -> str:
    """
    Gera mensagem de urgência baseada na data de vencimento.
    
    Args:
        data_vencimento: Data de vencimento no formato YYYY-MM-DD
        
    Returns:
        str: Mensagem de urgência apropriada
    """
    if not data_vencimento:
        return "Verifique o prazo desta obrigação."
    
    try:
        dt_venc = datetime.strptime(data_vencimento, "%Y-%m-%d").date()
        hoje = date.today()
        
        if dt_venc < hoje:
            dias_atraso = (hoje - dt_venc).days
            return f"⚠️ Esta obrigação está vencida há {dias_atraso} dia(s). Ação urgente necessária!"
        elif dt_venc == hoje:
            return "🕐 Esta obrigação vence HOJE. Ação imediata necessária!"
        else:
            delta = (dt_venc - hoje).days
            if delta == 1:
                return "📅 Esta obrigação vence AMANHÃ. Prepare-se!"
            elif delta <= 3:
                return f"📅 Esta obrigação vence em {delta} dias. Planeje sua execução."
            else:
                return f"📅 Esta obrigação vence em {delta} dias."
                
    except Exception:
        return "Verifique o prazo desta obrigação no G-Click."
