from typing import List, Dict, Any, Callable, Union
from config.loader import load_config

def _match_responsavel(responsavel: Dict[str, Any], wl_normalizada) -> bool:
    rid = responsavel.get("id")
    apelido = (responsavel.get("apelido") or "").lower()
    return (rid in wl_normalizada) or (apelido in wl_normalizada)

def resolver_responsaveis_para_tarefa(
    tarefa: Dict[str, Any],
    listar_responsaveis_tarefa_fn: Callable[[str], List[Dict[str, Any]]]
) -> List[Dict[str, Any]]:
    """
    Obtém e filtra responsáveis de uma tarefa conforme config.
    """
    cfg = load_config()
    notif = cfg.get("notificacoes", {})
    indiv = notif.get("individuais", {})
    modo = indiv.get("modo_selecao", "WHITELIST").upper()
    whitelist_cfg = indiv.get("whitelist", []) or []
    whitelist_norm = set()

    # Normaliza whitelist
    for x in whitelist_cfg:
        if isinstance(x, int):
            whitelist_norm.add(x)
        elif isinstance(x, str):
            whitelist_norm.add(x.lower())

    try:
        lista_raw = listar_responsaveis_tarefa_fn(tarefa.get("id"))
    except Exception:
        lista_raw = []

    # Futuro: se a API retornar campos como 'selecionado' / 'principal', aplicar aqui
    base = lista_raw

    if modo == "WHITELIST":
        base = [r for r in base if _match_responsavel(r, whitelist_norm)]
    # modo ALL => mantém todos

    if not base:
        # Força responsável teste se configurado
        sim = notif.get("simulacao", {})
        forced = sim.get("forcar_responsavel_teste")
        email_teste = sim.get("email_teste")
        if forced:
            base = [{
                "id": 0,
                "apelido": forced,
                "email": email_teste,
                "_forcado": True
            }]

    # Limite (segurança)
    limite = notif.get("limites", {}).get("max_tarefas_por_responsavel", 50)
    # Neste ponto não há relação 1-1 tarefa/responsável, limit não se aplica diretamente.
    return base
