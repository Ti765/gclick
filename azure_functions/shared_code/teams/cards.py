"""
Módulo para criação de cartões adaptativos (Adaptive Cards) para o Teams.

- Remove botões "Finalizar" e "Dispensar".
- Usa deep-link correto para abrir a obrigação no G-Click via helper montar_link_gclick_obrigacao.
- Detalhes expansíveis (Action.ToggleVisibility) com atividades, meta interna e observações.
- Retorna payloads como dict (compatível com o sender atual).
"""

from typing import Dict, Any, Optional, List, Tuple
from datetime import datetime, date

# Import relativo ao shared_code
from utils.gclick_links import (
    montar_link_gclick_obrigacao,
    EMPRESA_ID_PADRAO,
)


# =========================
# API pública
# =========================
def create_task_notification_card(
    tarefa: Dict[str, Any],
    responsavel: Dict[str, Any],
    detalhes: Optional[Dict[str, Any]] = None,
    *,
    max_atividades: int = 5,
) -> Dict[str, Any]:
    """
    Cria um Adaptive Card para notificação de tarefa/obrigação (estilo minimalista/dark-friendly).

    Args:
        tarefa: Dict com dados da tarefa (id, nome, dataVencimento, status etc.)
        responsavel: Dict com dados do responsável (nome, apelido etc.)
        detalhes: Dict opcional com:
            - atividades: List[{"titulo": str, "concluida": bool}]
            - contagem: {"pendentes": int, "concluidas": int, "total": int}
            - meta_interna: str (data normalizada dd/mm/aaaa quando disponível)
            - observacoes: str (resumo curto)
        max_atividades: Limite de linhas de atividades a exibir no bloco "Detalhes"

    Returns:
        dict: payload de Adaptive Card pronto para envio
    """
    # Extrair dados essenciais da tarefa
    id_tarefa = str(tarefa.get("id", "")).strip()
    nome_tarefa = tarefa.get("nome") or tarefa.get("titulo") or "Tarefa sem nome"
    data_venc = tarefa.get("dataVencimento", "")
    status = tarefa.get("_statusLabel", tarefa.get("status", "")) or "—"

    # Responsável
    nome_responsavel = responsavel.get("nome") or responsavel.get("apelido") or "—"

    # URL deep-link correto
    url_tarefa = montar_link_gclick_obrigacao(id_tarefa, EMPRESA_ID_PADRAO)

    # Estilo de urgência
    cor_status, icone_status = _determine_urgency_style(data_venc)

    # ID único para toggle de detalhes (evita colisões)
    detalhes_container_id = f"detalhes_{id_tarefa or 'x'}"

    # Cabeçalho compacto
    header_container = {
        "type": "Container",
        "bleed": True,
        "items": [
            {
                "type": "ColumnSet",
                "columns": [
                    {
                        "type": "Column",
                        "width": "auto",
                        "items": [
                            {"type": "TextBlock", "text": icone_status, "size": "Large"}
                        ],
                        "verticalContentAlignment": "Center",
                    },
                    {
                        "type": "Column",
                        "width": "stretch",
                        "items": [
                            {
                                "type": "TextBlock",
                                "text": "Obrigação Fiscal",
                                "weight": "Bolder",
                                "size": "Medium",
                                "wrap": True,
                            },
                            {
                                "type": "TextBlock",
                                "text": _get_urgency_message(data_venc),
                                "wrap": True,
                                "isSubtle": True,
                                "spacing": "None",
                                "color": cor_status,
                            },
                        ],
                    },
                ],
            }
        ],
        # "style": "emphasis"  # opcional; o Teams segue o tema do usuário (dark/clear)
    }

    # Corpo principal (título e facts)
    body_items: List[Dict[str, Any]] = [
        header_container,
        {
            "type": "TextBlock",
            "text": nome_tarefa,
            "wrap": True,
            "size": "Large",
            "weight": "Bolder",
            "spacing": "Medium",
        },
        {
            "type": "FactSet",
            "facts": [
                {"title": "ID:", "value": id_tarefa or "—"},
                {"title": "Vencimento:", "value": _format_date_for_display(data_venc)},
                {"title": "Status:", "value": str(status)},
                {"title": "Responsável:", "value": nome_responsavel},
            ],
        },
    ]

    # “Dica” de contagem quando houver detalhes
    if detalhes and isinstance(detalhes, dict):
        cont = detalhes.get("contagem") or {}
        pend = _safe_int(cont.get("pendentes"))
        conc = _safe_int(cont.get("concluidas"))
        total = _safe_int(cont.get("total")) or (pend + conc)
        if total > 0:
            hint = f"Atividades: {conc}/{total} concluídas • {pend} pendentes"
            body_items.append(
                {
                    "type": "TextBlock",
                    "text": hint,
                    "wrap": True,
                    "isSubtle": True,
                    "spacing": "Small",
                }
            )

    # Ações (OpenUrl e Toggle detalhes)
    actions: List[Dict[str, Any]] = [
        {"type": "Action.OpenUrl", "title": "📋 Ver no G-Click", "url": url_tarefa},
        {
            "type": "Action.ToggleVisibility",
            "title": "📝 Detalhes",
            "targetElements": [detalhes_container_id],
        },
    ]

    # Container de detalhes (inicialmente oculto)
    detalhes_container = _render_detalhes_container(
        detalhes_container_id, nome_tarefa, detalhes, max_atividades=max_atividades
    )

    # Montar card completo
    card: Dict[str, Any] = {
        "type": "AdaptiveCard",
        "version": "1.3",
        "body": body_items + [detalhes_container],
        "actions": actions,
    }
    return card


def create_summary_notification_card(resumo: Dict[str, Any], responsavel: str) -> Dict[str, Any]:
    """
    Cria um Adaptive Card para resumo de múltiplas obrigações (retorna dict).

    Args:
        resumo: Dicionário com contadores (vencidas, vence_hoje, vence_em_3_dias)
        responsavel: Nome/apelido do responsável

    Returns:
        dict: payload de Adaptive Card
    """
    counts = resumo.get("counts", {}) if isinstance(resumo, dict) else {}
    vencidas = _safe_int(counts.get("vencidas"))
    vence_hoje = _safe_int(counts.get("vence_hoje"))
    vence_proximos = _safe_int(counts.get("vence_em_3_dias"))
    total_pendentes = vencidas + vence_hoje + vence_proximos

    if vencidas > 0:
        cor_principal, icone = "attention", "🔴"
    elif vence_hoje > 0:
        cor_principal, icone = "warning", "🟡"
    else:
        cor_principal, icone = "good", "📅"

    body: List[Dict[str, Any]] = [
        {
            "type": "Container",
            "items": [
                {
                    "type": "ColumnSet",
                    "columns": [
                        {
                            "type": "Column",
                            "width": "auto",
                            "items": [{"type": "TextBlock", "text": icone, "size": "Large"}],
                            "verticalContentAlignment": "Center",
                        },
                        {
                            "type": "Column",
                            "width": "stretch",
                            "items": [
                                {
                                    "type": "TextBlock",
                                    "text": f"Resumo de Obrigações • {responsavel}",
                                    "weight": "Bolder",
                                    "size": "Medium",
                                    "wrap": True,
                                },
                                {
                                    "type": "TextBlock",
                                    "text": f"**{total_pendentes}** pendente(s)",
                                    "wrap": True,
                                    "spacing": "None",
                                    "color": cor_principal,
                                },
                            ],
                        },
                    ],
                }
            ],
        }
    ]

    if total_pendentes > 0:
        if vencidas > 0:
            body.append(
                {"type": "TextBlock", "text": f"🔴 **{vencidas}** vencida(s)", "wrap": True}
            )
        if vence_hoje > 0:
            body.append(
                {"type": "TextBlock", "text": f"🟡 **{vence_hoje}** vence(m) hoje", "wrap": True}
            )
        if vence_proximos > 0:
            body.append(
                {
                    "type": "TextBlock",
                    "text": f"🟢 **{vence_proximos}** vence(m) nos próximos dias",
                    "wrap": True,
                }
            )

    card: Dict[str, Any] = {
        "type": "AdaptiveCard",
        "version": "1.3",
        "body": body,
        "actions": [
            {
                "type": "Action.OpenUrl",
                "title": "🔍 Abrir G-Click",
                # Link genérico; pode ser ajustado para um filtro próprio, se houver
                "url": "https://app.gclick.com.br/",
            }
        ],
    }
    return card


# =========================
# Helpers internos
# =========================
def _render_detalhes_container(
    container_id: str,
    nome_tarefa: str,
    detalhes: Optional[Dict[str, Any]],
    *,
    max_atividades: int = 5,
) -> Dict[str, Any]:
    """
    Constrói o Container de detalhes (colapsável).

    detalhes esperados:
      - atividades: List[{"titulo": str, "concluida": bool}]
      - contagem: {"pendentes": int, "concluidas": int, "total": int}
      - meta_interna: str
      - observacoes: str
    """
    items: List[Dict[str, Any]] = [
        {"type": "TextBlock", "text": f"**{nome_tarefa}**", "wrap": True, "weight": "Bolder"}
    ]

    if not detalhes or not isinstance(detalhes, dict):
        items.append(
            {
                "type": "TextBlock",
                "text": "Não foi possível carregar detalhes agora. Abra no G-Click para consultar.",
                "wrap": True,
                "isSubtle": True,
            }
        )
        return {"type": "Container", "id": container_id, "isVisible": False, "items": items}

    # Meta interna (data) e observações (resumo)
    meta_interna = detalhes.get("meta_interna")
    if meta_interna:
        items.append(
            {"type": "TextBlock", "text": f"🗓️ Meta interna: **{meta_interna}**", "wrap": True}
        )

    observacoes = detalhes.get("observacoes")
    if observacoes:
        items.append(
            {
                "type": "TextBlock",
                "text": f"📝 Observações: {_truncate(str(observacoes), 320)}",
                "wrap": True,
            }
        )

    # Lista de atividades (máx. N linhas)
    atividades = detalhes.get("atividades")
    if isinstance(atividades, list) and atividades:
        linhas: List[str] = []
        for i, atv in enumerate(atividades[: max_atividades]):
            titulo = str(atv.get("titulo") or atv.get("nome") or "Atividade").strip()
            concluida = bool(atv.get("concluida") or atv.get("feita") or atv.get("done"))
            check = "✔" if concluida else "☐"
            linhas.append(f"- {check} {titulo}")
        resto = max(0, len(atividades) - max_atividades)
        txt = "**Atividades**:\n" + "\n".join(linhas)
        if resto > 0:
            txt += f"\n… e mais {resto} atividade(s)."
        items.append({"type": "TextBlock", "text": txt, "wrap": True})

    # Contadores (se presentes)
    cont = detalhes.get("contagem") or {}
    pend = _safe_int(cont.get("pendentes"))
    conc = _safe_int(cont.get("concluidas"))
    total = _safe_int(cont.get("total")) or (pend + conc)
    if total > 0:
        items.append(
            {
                "type": "TextBlock",
                "text": f"Progresso: **{conc}/{total}** concluídas • {pend} pendentes",
                "wrap": True,
                "isSubtle": True,
                "spacing": "Small",
            }
        )

    return {"type": "Container", "id": container_id, "isVisible": False, "items": items}


def _determine_urgency_style(data_vencimento: str) -> Tuple[str, str]:
    """
    Determina (cor, ícone) conforme proximidade do vencimento.
    Cores: default | attention | warning | good | accent
    """
    if not data_vencimento:
        return "default", "📋"
    try:
        dt_venc = datetime.strptime(data_vencimento, "%Y-%m-%d").date()
        hoje = date.today()
        if dt_venc < hoje:
            return "attention", "🔴"  # vencida
        if dt_venc == hoje:
            return "warning", "🟡"    # vence hoje
        delta = (dt_venc - hoje).days
        if delta <= 3:
            return "good", "🟢"       # em breve
        return "default", "📅"
    except Exception:
        return "default", "📋"


def _format_date_for_display(data_vencimento: str) -> str:
    """YYYY-MM-DD -> dd/mm/aaaa (fallback para original se parsing falhar)."""
    if not data_vencimento:
        return "—"
    try:
        dt = datetime.strptime(data_vencimento, "%Y-%m-%d")
        return dt.strftime("%d/%m/%Y")
    except Exception:
        return str(data_vencimento)


def _get_urgency_message(data_vencimento: str) -> str:
    """Mensagem curta de urgência conforme data."""
    if not data_vencimento:
        return "Verifique o prazo desta obrigação."
    try:
        dt_venc = datetime.strptime(data_vencimento, "%Y-%m-%d").date()
        hoje = date.today()
        if dt_venc < hoje:
            dias = (hoje - dt_venc).days
            return f"Vencida há {dias} dia(s). Ação urgente necessária."
        if dt_venc == hoje:
            return "Vence HOJE. Ação imediata recomendada."
        delta = (dt_venc - hoje).days
        if delta == 1:
            return "Vence AMANHÃ. Prepare-se."
        if delta <= 3:
            return f"Vence em {delta} dia(s). Planeje a execução."
        return f"Vence em {delta} dia(s)."
    except Exception:
        return "Verifique o prazo no G-Click."


def _truncate(texto: str, max_len: int) -> str:
    """Corta texto em max_len com reticências."""
    s = (texto or "").strip()
    if len(s) <= max_len:
        return s
    return s[: max(0, max_len - 1)].rstrip() + "…"


def _safe_int(v: Any) -> int:
    try:
        return int(v)
    except Exception:
        return 0
