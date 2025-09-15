# azure_functions/shared_code/gclick/tarefas_detalhes.py
import os
import logging
from typing import Dict, Any, List, Tuple, Optional

import requests
import time
from datetime import datetime
import re

logger = logging.getLogger(__name__)

GCLICK_API_BASE = os.getenv("GCLICK_API_BASE", "https://appp.gclick.com.br/api/v1")
GCLICK_API_TOKEN = os.getenv("GCLICK_API_TOKEN", "")
# Template configurável caso seu endpoint real seja diferente
# Use placeholders {eveId} e {coId}. Ex.: "{base}/tarefas/{eveId}"
GCLICK_TASK_DETAILS_TMPL = os.getenv("GCLICK_TASK_DETAILS_TMPL", "{base}/tarefas/{eveId}")

# sessão HTTP com auth
_session = requests.Session()
if GCLICK_API_TOKEN:
    _session.headers.update({"Authorization": f"Bearer {GCLICK_API_TOKEN}"})
_session.headers.update({"Accept": "application/json"})


def _split_task_id(task_id: str) -> Tuple[str, str]:
    """
    Recebe "4.66030" ou "466030" e retorna (coId, eveId) como strings.
    - Caso tenha ponto: coId = parte antes do ponto; eveId = parte após.
    - Caso seja compacto: coId = primeiro dígito; eveId = resto.
    """
    s = str(task_id).strip()
    if "." in s:
        a, b = s.split(".", 1)
        return a, b
    # forma compacta "466030" -> "4" e "66030"
    return s[0], s[1:]


def _try_get(url: str, timeout: int = 12) -> Optional[Dict[str, Any]]:
    attempts = 2
    for i in range(attempts):
        try:
            r = _session.get(url, timeout=timeout)
            if r.status_code == 200:
                return r.json() or {}
            logger.warning("[GCLICK] %s -> HTTP %s", url, r.status_code)
            if 400 <= r.status_code < 500:
                # client error - não tenta novamente
                break
        except Exception as e:
            logger.warning("[GCLICK] Falha GET %s (attempt %s): %s", url, i + 1, e)
        if i + 1 < attempts:
            time.sleep(0.4 * (i + 1))
    return None


def _pick_last_comment(d: Dict[str, Any], *keys: str) -> Optional[str]:
    """Procura listas de histórico/comentários e retorna o texto do último item."""
    for k in keys:
        v = d.get(k)
        if isinstance(v, list) and v:
            last = v[-1]
            if isinstance(last, dict):
                text = last.get("texto") or last.get("comentario") or last.get("descricao") or last.get("observacao")
                if isinstance(text, str) and text.strip():
                    return text.strip()
            elif isinstance(last, str) and last.strip():
                return last.strip()
    return None


def _format_date_for_ui(v: Any) -> Optional[str]:
    """Tenta transformar várias datas em dd/mm/AAAA; retorna str ou None."""
    if not v:
        return None
    if isinstance(v, str):
        s = v.strip()
        # tentativa ISO
        try:
            dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
            return dt.strftime("%d/%m/%Y")
        except Exception:
            pass
        # tentar formatos comuns
        for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y", "%d/%m/%y"):
            try:
                return datetime.strptime(s, fmt).strftime("%d/%m/%Y")
            except Exception:
                continue
        # tentativa por regex dd/mm/yyyy ou dd-mm-yyyy sem parse
        m = re.search(r"(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})", s)
        if m:
            return m.group(1)
    if isinstance(v, (int, float)):
        try:
            return datetime.fromtimestamp(int(v)).strftime("%d/%m/%Y")
        except Exception:
            pass
    return None


def obter_tarefa_detalhes(task_id: str) -> Dict[str, Any]:
    """
    Busca o JSON bruto de detalhes da tarefa (tolerante a variações de endpoint).
    1) Usa template configurável (GCLICK_TASK_DETAILS_TMPL)
    2) Tenta algumas rotas de fallback comuns.
    """
    coId, eveId = _split_task_id(task_id)
    # 1) template
    urls = [
        GCLICK_TASK_DETAILS_TMPL.format(base=GCLICK_API_BASE, eveId=eveId, coId=coId),
        # 2) fallbacks (ajuste se necessário conforme sua API real)
        f"{GCLICK_API_BASE}/tarefas/{eveId}",
        f"{GCLICK_API_BASE}/obrigacoes/{coId}/tarefas/{eveId}",
    ]
    for url in urls:
        data = _try_get(url)
        if isinstance(data, dict):
            return data
    return {}  # falha: devolve vazio para UI fazer fallback


def _bool_status(valor: Any) -> Optional[bool]:
    """Converte status flexíveis em bool concluído/pendente."""
    if isinstance(valor, bool):
        return valor
    if isinstance(valor, str):
        v = valor.lower()
        if v in ("c", "f", "concluido", "finalizado", "concluída", "concluida"):
            return True
        if v in ("a", "aberto", "pendente", "p", "s"):
            return False
    if isinstance(valor, (int, float)):
        # 1 -> done; 0 -> pending
        return bool(valor)
    return None


def _pick_str(d: Dict[str, Any], *keys: str) -> Optional[str]:
    for k in keys:
        v = d.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return None


def _pick_date(d: Dict[str, Any], *keys: str) -> Optional[str]:
    for k in keys:
        v = d.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return None


def _atividades_from(d: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Tenta extrair lista de atividades/checklist em formato uniforme."""
    candidates = []
    for k in ("atividades", "checklist", "tarefasAtividades", "itens", "steps"):
        v = d.get(k)
        if isinstance(v, list) and v:
            candidates = v
            break

    result = []
    for idx, item in enumerate(candidates, 1):
        if not isinstance(item, dict):
            continue
        title = _pick_str(item, "descricao", "nome", "titulo", "texto") or f"Etapa {idx}"
        st = _bool_status(item.get("concluida"))  # bool se existir
        if st is None:
            st = _bool_status(item.get("status"))
        if st is None:
            st = _bool_status(item.get("feito"))
        result.append({"titulo": title, "done": bool(st)})
    return result


def resumir_detalhes_para_card(detalhes_raw: Dict[str, Any], *,
                               max_itens: int = 4,
                               max_obs: int = 280) -> Dict[str, Any]:
    """
    Normaliza o JSON bruto para a UI do card.
    Retorna dict com:
      - atividades_compactas (lista de strings com ✔/☐)
      - pendentes_total, concluidas_total
      - meta_interna (str)
      - observacoes (str reduzido)
    """
    atividades = _atividades_from(detalhes_raw)
    concluidas = sum(1 for a in atividades if a.get("done"))
    pendentes = max(0, len(atividades) - concluidas)

    linhas = []
    for i, a in enumerate(atividades[:max_itens], 1):
        mark = "✔" if a.get("done") else "☐"
        linhas.append(f"{i}. {a.get('titulo')} {mark}")
    resto = len(atividades) - len(linhas)
    if resto > 0:
        linhas.append(f"+ {resto} item(ns) restante(s)…")

    obs = _pick_str(detalhes_raw, "observacoes", "observacao", "obs", "nota", "notas")
    if not obs:
        # tentar extrair do histórico/comentários
        obs = _pick_last_comment(detalhes_raw, "historico", "comentarios", "history", "logs")
    if obs and len(obs) > max_obs:
        obs = obs[:max_obs - 1].rstrip() + "…"

    meta_raw = _pick_date(detalhes_raw, "dataMeta", "meta", "data_meta", "data_meta_interna")
    meta = _format_date_for_ui(meta_raw)

    return {
        "atividades_compactas": linhas,
        "pendentes_total": pendentes,
        "concluidas_total": concluidas,
        "meta_interna": meta,
        "observacoes": obs,
    }
