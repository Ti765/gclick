# analytics/status_metrics.py
from collections import Counter
from typing import List, Dict, Any

# Definições padrão (podem ser importadas em outros lugares)
OPEN_STATUSES = {"A", "P", "Q", "S"}
CLOSED_STATUSES = {"C", "D", "O"}

STATUS_LABEL = {
    "A": "Aberto/Autorizada",
    "P": "Solicitado (email)",
    "Q": "Solicitado (cliente)",
    "S": "Aguardando",
    "C": "Concluído",
    "D": "Dispensado",
    "O": "Retificado"
}

def classify_status(status: str) -> str:
    if status in OPEN_STATUSES:
        return "aberto"
    if status in CLOSED_STATUSES:
        return "fechado"
    return "outro"

def compute_status_distribution(tasks: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Recebe lista de tarefas (cada uma com chave 'status').
    Retorna:
      - contagem por status
      - percentuais
      - agregados aberto/fechado
    """
    total = len(tasks)
    counter = Counter(t.get("status") for t in tasks)
    # Map com labels
    detailed = []
    for st, count in counter.items():
        pct = (count / total * 100) if total else 0.0
        detailed.append({
            "status": st,
            "label": STATUS_LABEL.get(st, "Desconhecido"),
            "count": count,
            "pct": round(pct, 2),
            "grupo": classify_status(st)
        })
    detailed.sort(key=lambda x: (-x["count"], x["status"]))

    abertos = sum(c["count"] for c in detailed if c["grupo"] == "aberto")
    fechados = sum(c["count"] for c in detailed if c["grupo"] == "fechado")
    outros = total - (abertos + fechados)

    def pct(x): 
        return round((x / total * 100) if total else 0.0, 2)

    return {
        "total": total,
        "abertos": abertos,
        "fechados": fechados,
        "outros": outros,
        "pct_abertos": pct(abertos),
        "pct_fechados": pct(fechados),
        "pct_outros": pct(outros),
        "detalhe": detailed
    }

def ascii_bar(percent: float, width: int = 30, fill: str = "█") -> str:
    filled = int(round(percent / 100 * width))
    return fill * filled + " " * (width - filled)

def build_text_dashboard(dist: Dict[str, Any]) -> str:
    """
    Gera um mini dashboard textual (Markdown-friendly).
    """
    lines = []
    lines.append(f"**Total de tarefas na amostra:** {dist['total']}")
    lines.append("")
    lines.append("**Resumo aberto x fechado:**")
    lines.append(f"- Abertos: {dist['abertos']} ({dist['pct_abertos']}%)")
    lines.append(f"- Fechados: {dist['fechados']} ({dist['pct_fechados']}%)")
    if dist['outros']:
        lines.append(f"- Outros: {dist['outros']} ({dist['pct_outros']}%)")
    lines.append("")
    lines.append("```\nBARRAS (aberto vs fechado)\n")
    lines.append(f"Abertos : {ascii_bar(dist['pct_abertos'])} {dist['pct_abertos']}%")
    lines.append(f"Fechados: {ascii_bar(dist['pct_fechados'])} {dist['pct_fechados']}%")
    if dist['outros']:
        lines.append(f"Outros  : {ascii_bar(dist['pct_outros'])} {dist['pct_outros']}%")
    lines.append("```")
    lines.append("")
    lines.append("**Distribuição detalhada por status:**")
    for item in dist["detalhe"]:
        lines.append(f"- `{item['status']}` {item['label']}: {item['count']} ({item['pct']}%) → grupo={item['grupo']}")
    return "\n".join(lines)
