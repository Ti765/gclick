import time
import argparse
from engine.notification_engine import ciclo_notificacao, load_notifications_config

def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--dry-run", action="store_true", help="Simulação contínua.")
    p.add_argument("--intervalo", type=int, help="Override segundos intervalo loop.")
    p.add_argument("--once", action="store_true", help="Executa apenas uma vez (atalho).")
    p.add_argument("--verbose", action="store_true")
    return p.parse_args()

def main():
    args = parse_args()
    cfg = load_notifications_config()
    ncfg = cfg["notificacao"]

    intervalo = args.intervalo or ncfg["intervalo_loop_segundos"]

    if args.once:
        ciclo_notificacao(
            dias_proximos=ncfg["dias_proximos"],
            page_size=ncfg["page_size"],
            categoria=ncfg.get("categoria_padrao","Obrigacao"),
            max_responsaveis_lookup=ncfg["max_responsaveis_lookup"],
            limite_responsaveis_notificar=ncfg["limite_responsaveis_notificar"],
            repetir_no_mesmo_dia=ncfg["repetir_no_mesmo_dia"],
            detalhar_limite=ncfg["detalhar_limite"],
            enviar_resumo_global=ncfg["enviar_resumo_global"],
            rate_limit_sleep_ms=ncfg["rate_limit_sleep_ms"],
            dry_run=args.dry_run,
            verbose=args.verbose
        )
        return

    print(f"[LOOP] Iniciando loop contínuo intervalo={intervalo}s dry_run={args.dry_run}")
    while True:
        inicio = time.time()
        try:
            ciclo_notificacao(
                dias_proximos=ncfg["dias_proximos"],
                page_size=ncfg["page_size"],
                categoria=ncfg.get("categoria_padrao","Obrigacao"),
                max_responsaveis_lookup=ncfg["max_responsaveis_lookup"],
                limite_responsaveis_notificar=ncfg["limite_responsaveis_notificar"],
                repetir_no_mesmo_dia=ncfg["repetir_no_mesmo_dia"],
                detalhar_limite=ncfg["detalhar_limite"],
                enviar_resumo_global=ncfg["enviar_resumo_global"],
                rate_limit_sleep_ms=ncfg["rate_limit_sleep_ms"],
                dry_run=args.dry_run,
                verbose=args.verbose
            )
        except Exception as e:
            print(f"[ERRO_LOOP] {e}")
        elapsed = time.time() - inicio
        restante = max(0, intervalo - elapsed)
        time.sleep(restante)

if __name__ == "__main__":
    main()
