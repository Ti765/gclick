from typing import List, Dict
from datetime import date

# Usar helper para gerar deep-link do G-Click
from utils.gclick_links import montar_link_gclick_obrigacao

def _linha_tarefa(t):
    return f"- [{t.get('id')}] {t.get('nome')} (venc: {t.get('dataVencimento')}) → {montar_link_gclick_obrigacao(t.get('id'))}"

def montar_payload_usuario(
    apelido: str,
    tarefas_hoje: List[Dict],
    tarefas_proximas: List[Dict],
    limite_detalhe: int = 3
) -> str:
    """
    Retorna texto markdown (para Webhook simples). Regra:
      - Se qtd <= limite_detalhe => lista detalhada
      - Se > limite_detalhe => resumo contagem + 1 link genérico (usando a primeira tarefa como referência)
    """
    partes = [f"*Resumo de obrigações para @{apelido}*"]

    # Hoje
    if tarefas_hoje:
        partes.append(f"\n**Vencem HOJE ({len(tarefas_hoje)})**")
        if len(tarefas_hoje) <= limite_detalhe:
            for t in tarefas_hoje:
                partes.append(_linha_tarefa(t))
        else:
            # Mostra apenas contagem + link
            link = montar_link_gclick_obrigacao(tarefas_hoje[0].get('id'))
            partes.append(f"- {len(tarefas_hoje)} obrigações vencem hoje. Ver lista: {link}")

    # Próximos dias
    if tarefas_proximas:
        partes.append(f"\n**Vencem nos próximos dias ({len(tarefas_proximas)})**")
        if len(tarefas_proximas) <= limite_detalhe:
            for t in tarefas_proximas:
                partes.append(_linha_tarefa(t))
        else:
            link = montar_link_gclick_obrigacao(tarefas_proximas[0].get('id'))
            partes.append(f"- {len(tarefas_proximas)} obrigações nos próximos dias. Ver lista: {link}")

    if not tarefas_hoje and not tarefas_proximas:
        partes.append("\n(Sem obrigações hoje ou nos próximos dias.)")

    return "\n".join(partes)


def montar_payload_resumo_global(classif_counts: Dict[str, int], hoje: date, dias_proximos: int) -> str:
    return (
        f"*Resumo Global ({hoje.isoformat()} + {dias_proximos}d)*\n"
        f"- Vencidas: {classif_counts['vencidas']}\n"
        f"- Vencem hoje: {classif_counts['vence_hoje']}\n"
        f"- Vencem próximos {dias_proximos} dias: {classif_counts['vence_em_3_dias']}"
    )
