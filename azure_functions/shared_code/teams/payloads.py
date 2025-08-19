from typing import List, Dict, Any
from config.loader import load_config

def construir_url_tarefa(tid: str) -> str:
    cfg = load_config()
    base = cfg["notificacoes"]["links"]["base_tarefa"]
    return base.format(id=tid)

def formatar_tarefa_curta(t: Dict[str, Any]) -> str:
    return f"[{t.get('id')}] {t.get('nome')} (venc: {t.get('dataVencimento')})"

def bloco_detalhado(tarefas: List[Dict[str, Any]]) -> str:
    linhas = []
    for t in tarefas:
        linhas.append(f"- {formatar_tarefa_curta(t)} → {construir_url_tarefa(t.get('id'))}")
    return "\n".join(linhas)

def bloco_agregado(tarefas: List[Dict[str, Any]], label: str) -> str:
    cfg = load_config()
    link_lista = cfg["notificacoes"]["links"]["lista_pendentes"]
    return f"{label}: {len(tarefas)} pendências. Ver todas: {link_lista}"

def payload_individual(responsavel_meta: Dict[str, Any], grupos: Dict[str, List[Dict[str, Any]]]) -> str:
    """
    Retorna texto simples (Markdown) simulando card.
    """
    cfg = load_config()
    limite = cfg["notificacoes"]["formato"]["limite_detalhe"]
    sim = cfg["notificacoes"]["simulacao"]
    mencao_prefix = ""
    if sim.get("mencao_simulada"):
        mencao_prefix = f"[@{responsavel_meta.get('apelido')}] (SIMULAÇÃO)\n"

    partes = [f"{mencao_prefix}*Resumo de obrigações*"]
    map_label = {
        "vence_hoje": "Vencem HOJE",
        "vence_em_3_dias": "Vencem próximos dias",
        "vencidas": "VENCIDAS"
    }

    # Ordem de prioridade
    for chave in ("vence_hoje", "vence_em_3_dias", "vencidas"):
        lista = grupos.get(chave, [])
        if not lista:
            continue
        if len(lista) <= limite:
            partes.append(f"**{map_label[chave]} ({len(lista)})**\n{bloco_detalhado(lista)}")
        else:
            partes.append(f"**{map_label[chave]}**\n{bloco_agregado(lista, map_label[chave])}")

    return "\n\n".join(partes)

def payload_vencida_canal(tarefa: Dict[str, Any]) -> str:
    return (
        f"⚠️ *Tarefa vencida*: {formatar_tarefa_curta(tarefa)}\n"
        f"Abrir: {construir_url_tarefa(tarefa.get('id'))}\n"
        f"[Ação 1: Preencher] | [Ação 2: Dispensada]"
    )
