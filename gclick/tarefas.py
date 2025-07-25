import os
import requests
from datetime import datetime, timedelta
from typing import Tuple, List, Dict, Any, Iterable, Optional
from .auth import get_access_token  # Usar auth centralizado

# Carrega .env defensivamente (não falha se não existir)
try:
    from dotenv import load_dotenv  # type: ignore
    load_dotenv()
except Exception:
    pass

def _headers() -> Dict[str, str]:
    return {"Authorization": f"Bearer {get_access_token()}"}

# ============================================================
# Status labels
# ============================================================

STATUS_LABELS = {
    "A": "Aberto/Autorizada",
    "S": "Aguardando",
    "C": "Concluído",
    "D": "Dispensado",
    "F": "Finalizado",
    "E": "Retificando",
    "O": "Retificado",
    "P": "Solicitado (email/externo)",
    "Q": "Solicitado (Visão Cliente)"
}

# ============================================================
# Normalização
# ============================================================

def normalizar_tarefa(t: Dict[str, Any]) -> Dict[str, Any]:
    r = dict(t)
    st = r.get("status")
    r["_statusLabel"] = STATUS_LABELS.get(st, st)
    
    # Normalizar data de vencimento
    dv = r.get("dataVencimento")
    if dv and isinstance(dv, str):
        try:
            # Assumindo formato ISO (YYYY-MM-DD ou YYYY-MM-DDTHH:mm:ss)
            from datetime import datetime
            if 'T' in dv:
                # Formato com tempo
                r["_dt_dataVencimento"] = datetime.fromisoformat(dv.replace('Z', '')).date()
            else:
                # Apenas data
                r["_dt_dataVencimento"] = datetime.fromisoformat(dv).date()
        except ValueError:
            try:
                # Tentar outros formatos comuns
                from datetime import datetime
                r["_dt_dataVencimento"] = datetime.strptime(dv[:10], "%Y-%m-%d").date()
            except ValueError:
                print(f"[WARN] Formato de data não reconhecido: {dv}")
                r["_dt_dataVencimento"] = None
    else:
        r["_dt_dataVencimento"] = None
    
    # Normalizar outros campos importantes que podem vir como None
    if not r.get("nome") and r.get("assunto"):
        r["nome"] = r.get("assunto")
    elif not r.get("assunto") and r.get("nome"):
        r["assunto"] = r.get("nome")
    
    return r

# ============================================================
# Página de tarefas
# ============================================================

def listar_tarefas_page(
    categoria: str = "Obrigacao",
    page: int = 0,
    size: int = 20,
    status: Optional[str] = None,
    dataVencimentoInicio: Optional[str] = None,
    dataVencimentoFim: Optional[str] = None,
    extra_params: Optional[Dict[str, Any]] = None,
    validar_filtro_status: bool = False,
    divergencia_limite: float = 0.8,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    url = "https://api.gclick.com.br/tarefas"
    params: Dict[str, Any] = {
        "categoria": categoria,
        "page": page,
        "size": size,
    }
    if status:
        params["status"] = status
    if dataVencimentoInicio:
        params["dataVencimentoInicio"] = dataVencimentoInicio
    if dataVencimentoFim:
        params["dataVencimentoFim"] = dataVencimentoFim
    if extra_params:
        params.update(extra_params)

    resp = requests.get(url, headers=_headers(), params=params, timeout=40)
    if not resp.ok:
        raise RuntimeError(
            f"Erro {resp.status_code} GET {url} params={params} body={resp.text[:500]}"
        )

    data = resp.json()
    content = data.get("content", []) or []
    norm = [normalizar_tarefa(t) for t in content]

    meta = {
        "page": data.get("page"),
        "size": data.get("size"),
        "totalElements": data.get("totalElements"),
        "totalPages": data.get("totalPages"),
        "last": data.get("last"),
        "raw_params": params
    }

    if validar_filtro_status and status and norm:
        diff_ratio = sum(1 for t in norm if t.get("status") != status) / len(norm)
        meta["status_filter_diff_ratio"] = diff_ratio
        if diff_ratio >= divergencia_limite:
            print(
                f"[WARN] Filtro status='{status}' possivelmente ignorado (divergência "
                f"{diff_ratio:.2%} >= {divergencia_limite:.0%})."
            )
            meta["status_filter_warning"] = True
        else:
            meta["status_filter_warning"] = False

    return norm, meta

# ============================================================
# Coleta multi-status de abertos
# ============================================================

def listar_tarefas_abertas_intervalo(
    inicio: str,
    fim: str,
    page_size: int = 200,
    max_pages: int | None = None,
    categoria: str = "Obrigacao",
    statuses: Iterable[str] = ("A", "P", "Q", "S"),
    verbose: bool = False
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    agregadas: List[Dict[str, Any]] = []
    por_status: Dict[str, int] = {}

    for st in statuses:
        page = 0
        coletadas_st: List[Dict[str, Any]] = []
        while True:
            lst, meta = listar_tarefas_page(
                categoria=categoria,
                page=page,
                size=page_size,
                status=st,
                dataVencimentoInicio=inicio,
                dataVencimentoFim=fim,
                validar_filtro_status=False
            )
            coletadas_st.extend(lst)

            if verbose:
                print(f"[INFO] Status {st}: página={page} obtidas={len(lst)} totalPages={meta.get('totalPages')}")

            if meta.get("last") is True:
                break
            page += 1
            if max_pages is not None and page >= max_pages:
                break

        por_status[st] = len(coletadas_st)
        agregadas.extend(coletadas_st)

    # Deduplicação defensiva
    dedup: Dict[str, Dict[str, Any]] = {}
    for t in agregadas:
        tid = str(t.get("id"))
        dedup[tid] = t
    final_list = list(dedup.values())

    meta_multi = {
        "intervalo": (inicio, fim),
        "statuses_consultados": list(statuses),
        "por_status": por_status,
        "total": sum(por_status.values())
    }
    return final_list, meta_multi
