import os
import requests
from datetime import datetime, timedelta
from typing import Tuple, List, Dict, Any, Iterable

# Carrega .env defensivamente (não falha se não existir)
try:
    from dotenv import load_dotenv  # type: ignore
    load_dotenv()
except Exception:
    pass

REQUIRED_ENV = ["GCLICK_CLIENT_ID", "GCLICK_CLIENT_SECRET"]

def _ensure_env():
    faltando = [k for k in REQUIRED_ENV if not os.getenv(k)]
    if faltando:
        raise RuntimeError(
            f"[ENV] Variáveis ausentes: {', '.join(faltando)}. "
            "Carregue seu .env antes de importar gclick.tarefas ou defina-as no ambiente."
        )

# ============================================================
# Autenticação com cache simples
# ============================================================

_token_cache: Dict[str, Any] = {"value": None, "exp": None}

def _obter_token() -> Tuple[str, datetime]:
    _ensure_env()
    url = "https://api.gclick.com.br/oauth/token"
    payload = {
        "grant_type": "client_credentials",
        "client_id": os.environ["GCLICK_CLIENT_ID"],
        "client_secret": os.environ["GCLICK_CLIENT_SECRET"],
    }
    resp = requests.post(url, data=payload, timeout=25)
    resp.raise_for_status()
    data = resp.json()
    tok = data["access_token"]
    exp = datetime.utcnow() + timedelta(seconds=int(data.get("expires_in", 3600)) - 60)
    return tok, exp

def _get_access_token() -> str:
    now = datetime.utcnow()
    if _token_cache["value"] and _token_cache["exp"] and _token_cache["exp"] > now:
        return _token_cache["value"]
    tok, exp = _obter_token()
    _token_cache["value"] = tok
    _token_cache["exp"] = exp
    return tok

def _headers() -> Dict[str, str]:
    return {"Authorization": f"Bearer {_get_access_token()}"}

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
    return r

# ============================================================
# Página de tarefas
# ============================================================

def listar_tarefas_page(
    categoria: str = "Obrigacao",
    page: int = 0,
    size: int = 20,
    status: str | None = None,
    dataVencimentoInicio: str | None = None,
    dataVencimentoFim: str | None = None,
    extra_params: Dict[str, Any] | None = None,
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
