import os
import re
from typing import Union

EMPRESA_ID_PADRAO = int(os.getenv("GCLICK_EMPRESA_ID", "2557"))

def montar_link_gclick_obrigacao(id_tarefa: Union[str, int], emp_id: int = EMPRESA_ID_PADRAO) -> str:
    s = str(id_tarefa or "").strip()
    # tenta capturar "NNN<sep>NNNNN" com qualquer separador não numérico
    m = re.match(r"^\s*(\d+)\D+(\d+)\s*$", s)
    if m:
        coid, eve = m.group(1), m.group(2)
    else:
        digits = re.findall(r"\d+", s)
        if not digits:
            return "https://app.gclick.com.br/coListar.do?obj=coevento"
        flat = "".join(digits)
        if len(flat) >= 2:
            coid, eve = flat[0], flat[1:]
        else:
            coid, eve = flat or "4", flat or "0"

    # normaliza zeros à esquerda
    try:
        coid = str(int(coid))
    except Exception:
        coid = str(coid)
    try:
        eve = str(int(eve))
    except Exception:
        eve = str(eve)

    return f"https://app.gclick.com.br/coListar.do?obj=coevento&coid={coid}&eveId={eve}&empId={emp_id}"
