import argparse
import os
from datetime import date, timedelta
from dotenv import load_dotenv

load_dotenv()

from gclick.tarefas import (
    listar_tarefas_abertas_intervalo,
    listar_tarefas_page
)
from analytics.status_metrics import (
    compute_status_distribution,
    build_text_dashboard
)
from teams.webhook import enviar_teams_mensagem

try:
    from analytics.metrics import write_notification_cycle, new_run_id  # opcional (não obrigatório aqui)
except ImportError:  # fallback
    def write_notification_cycle(**_k):
        pass
    def new_run_id(prefix: str = 'run'):  # type: ignore
        return f"{prefix}_dummy"


def _assert_env(keys: list[str]):
    faltando = [k for k in keys if not os.getenv(k)]
    if faltando:
        raise RuntimeError(
            f"[ENV] Variáveis ausentes: {', '.join(faltando)}. "
            "Verifique seu arquivo .env."
        )

def main():
    parser = argparse.ArgumentParser(description="Dashboard de status de tarefas G-Click.")
    parser.add_argument("--dias-proximos", type=int, default=3)
    parser.add_argument("--categoria", default="Obrigacao")
    parser.add_argument("--page-size", type=int, default=200)
    parser.add_argument("--max-pages", type=int, default=None)
    parser.add_argument("--modo", choices=["mix", "apenas_abertos", "bruto"], default="mix")
    parser.add_argument("--enviar-teams", action="store_true")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    _assert_env([
        "GCLICK_CLIENT_ID", "GCLICK_CLIENT_SECRET", "GCLICK_SISTEMA",
        "GCLICK_CONTA", "GCLICK_USUARIO", "GCLICK_SENHA", "GCLICK_EMPRESA"
    ])

    hoje = date.today()
    fim = hoje + timedelta(days=args.dias_proximos)
    inicio_str = hoje.isoformat()
    fim_str = fim.isoformat()

    if args.verbose:
        print(f"[INFO] Janela: {inicio_str} -> {fim_str} | modo={args.modo} | categoria={args.categoria}")

    dist_abertos = None
    meta_abertos = {}
    if args.modo in ("apenas_abertos", "mix"):
        if args.verbose:
            print("[COLETA] Multi-status (A,P,Q,S) apenas abertos...")
        abertos, meta_abertos = listar_tarefas_abertas_intervalo(
            inicio=inicio_str,
            fim=fim_str,
            page_size=args.page_size,
            max_pages=args.max_pages,
            categoria=args.categoria,
            verbose=args.verbose
        )
        dist_abertos = compute_status_distribution(abertos)

    bruto_dist = None
    meta_bruto = {}
    if args.modo in ("mix", "bruto"):
        if args.verbose:
            print("[COLETA] Página bruta (sem filtrar status na query)...")
        todas, meta_bruto = listar_tarefas_page(
            categoria=args.categoria,
            page=0,
            size=args.page_size,
            dataVencimentoInicio=inicio_str,
            dataVencimentoFim=fim_str
        )
        bruto_dist = compute_status_distribution(todas)

    print("\n=== DASHBOARD STATUS ===")
    print(f"Janela: {inicio_str} -> {fim_str} (categoria={args.categoria})")

    if dist_abertos:
        print("\n-- SOMENTE ABERTOS (multi-status) --")
        print(f"Meta multi-status: {meta_abertos}")
        print(build_text_dashboard(dist_abertos))

    if bruto_dist:
        print("\n-- AMOSTRA BRUTA (page única) --")
        print(f"Meta bruto: {meta_bruto}")
        print(build_text_dashboard(bruto_dist))

    # === Divergência Bruto vs Filtrado ===
    if dist_abertos and bruto_dist:
        total_bruto = bruto_dist['total']
        total_apos_status = dist_abertos['total']
        # Dedupe (número de abertos reais) - aqui usamos dist_abertos['abertos']
        total_abertas_dedup = dist_abertos['abertos']
        print("\n=== Divergência Bruto vs Filtrado ===")
        print(f"Total bruto coletado: {total_bruto}")
        print(f"Após filtro status (multi-coleta): {total_apos_status}")
        print(f"Abertas consideradas (deduplicadas): {total_abertas_dedup}")
        if total_bruto:
            perc_descartado = (total_bruto - total_apos_status) / total_bruto * 100
            print(f"Descartado pelo filtro status: {perc_descartado:.2f}%")

    if args.enviar_teams:
        partes = []
        if dist_abertos:
            partes.append(
                f"Abertos (multi): {dist_abertos['abertos']} de {dist_abertos['total']} "
                f"({dist_abertos['pct_abertos']}%)"
            )
        if bruto_dist:
            partes.append(
                f"Bruto(page0): {bruto_dist['abertos']} / {bruto_dist['total']} "
                f"({bruto_dist['pct_abertos']}%)"
            )
        msg = "*Dashboard rápido de obrigações*\n" + " | ".join(partes)
        enviar_teams_mensagem(msg)
        print("[INFO] Mensagem enviada ao Teams.")

if __name__ == "__main__":
    main()
    