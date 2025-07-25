import sys
import os
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from dotenv import load_dotenv
from datetime import date, timedelta
from gclick.tarefas import (
    listar_tarefas_page,
    listar_tarefas_abertas_intervalo,  # Função que existe
    STATUS_LABELS  # Corrigido de STATUS_LABEL
)
from gclick.responsaveis import listar_responsaveis_tarefa
from gclick.departamentos import get_departamentos_cached  # Usar cache existente
from teams.webhook import enviar_teams_mensagem
import json

load_dotenv()

def coletar_tarefas_intervalo(categoria="Obrigacao", limite_itens=50, dias_vencimento_proximos=3):
    """Implementação baseada na função existente"""
    hoje = date.today()
    fim = hoje + timedelta(days=dias_vencimento_proximos)
    
    try:
        tarefas, meta = listar_tarefas_abertas_intervalo(
            inicio=hoje.isoformat(),
            fim=fim.isoformat(),
            categoria=categoria,
            page_size=min(limite_itens, 200)
        )
        return tarefas[:limite_itens]
    except Exception as e:
        print(f"Erro ao coletar tarefas por intervalo: {e}")
        return []


def sanitize_for_print(obj: dict) -> dict:
    """
    Retorna uma cópia do dicionário removendo chaves técnicas (_dt_*)
    para impressão 'bruta' e evitando erro de serialização.
    """
    clean = {}
    for k, v in obj.items():
        if k.startswith("_dt_"):
            continue
        clean[k] = v
    return clean


def json_dump(obj) -> str:
    """
    Dump JSON que sabe serializar date/datetime.
    """
    def _default(o):
        if isinstance(o, (date,)):
            return o.isoformat()
        return str(o)
    return json.dumps(obj, indent=2, ensure_ascii=False, default=_default)


def mostrar_tarefas_resumo(tarefas, max_itens=5):
    print(f"\n=== Tarefas (total={len(tarefas)}) ===")
    for i, t in enumerate(tarefas[:max_itens], start=1):
        print(
            f"{i}. id={t.get('id')} | nome={t.get('nome')} | "
            f"status={t.get('status')}({t.get('_statusLabel')}) | "
            f"venc={t.get('dataVencimento')}"
        )


def main():
    # 1. Cache de departamentos
    departamentos = get_departamentos_cached()
    print(f"Departamentos cacheados: {len(departamentos)} (exibe 3):")
    for d in departamentos[:3]:
        print(f" - {d.get('id')} | {d.get('nome')}")

    # 2. Página única de tarefas (demonstração)
    tarefas_page, meta = listar_tarefas_page(
        categoria="Obrigacao",
        page=0,
        size=5
    )
    print("\n== Página 0 de tarefas ==")
    print("Meta:", {k: meta.get(k) for k in ("page", "size", "totalElements", "totalPages")})
    if tarefas_page:
        primeira_sanitizada = sanitize_for_print(tarefas_page[0])
        print("Primeira tarefa (bruto normalizado sem campos _dt_):\n",
              json_dump(primeira_sanitizada))

    mostrar_tarefas_resumo(tarefas_page)

    # 3. Coletar tarefas próximas (ex: vencendo próximos 3 dias)
    tarefas_proximas = coletar_tarefas_intervalo(
        categoria="Obrigacao",
        limite_itens=50,
        dias_vencimento_proximos=3
    )
    print(f"\nTarefas com vencimento nos próximos 3 dias: {len(tarefas_proximas)}")
    mostrar_tarefas_resumo(tarefas_proximas)

    # 4. Responsáveis da primeira tarefa (se existir)
    if tarefas_page:
        tid = tarefas_page[0].get("id")
        if tid:
            try:
                responsaveis = listar_responsaveis_tarefa(tid)
                print(f"\nResponsáveis da tarefa {tid}: {len(responsaveis)}")
                for r in responsaveis:
                    print(" -", r.get("id"), r.get("apelido"), r.get("email"))
            except Exception as e:
                print("Falha ao buscar responsáveis:", e)

    # 5. Mensagem Teams
    enviar_teams_mensagem(
        f"✅ Refinos aplicados + correção de serialização. "
        f"Tarefas página0={len(tarefas_page)}, próximas_3_dias={len(tarefas_proximas)}."
    )
    print("\nMensagem enviada ao Teams (ou tentativa registrada).")


if __name__ == "__main__":
    main()
