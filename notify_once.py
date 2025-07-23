#!/usr/bin/env python
"""
Script de execução única do ciclo de notificação.

Uso típico (dry-run padrão):
    python notify_once.py --dias-proximos 3 --verbose

Modo live (envia ao Teams):
    python notify_once.py --dias-proximos 3 --enviar

Desligar filtro de status abertos (examinar tudo):
    python notify_once.py --no-apenas-abertos --verbose
"""
from __future__ import annotations
import argparse
import sys
from engine.notification_engine import run_notification_cycle
from analytics.metrics import new_run_id
from storage.lock import FileLock


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Executa um ciclo único de notificação (G-Click -> Teams)."
    )

    grp_janela = p.add_argument_group("Janela / Coleta")
    grp_janela.add_argument("--dias-proximos", type=int, default=3,
                            help="Dias futuros a incluir na janela (default=3).")
    grp_janela.add_argument("--page-size", type=int, default=200,
                            help="Tamanho de página para paginação da API (default=200).")
    grp_janela.add_argument("--max-pages", type=int, default=None,
                            help="Limite de páginas no full-scan (None = até 'last').")
    grp_janela.add_argument("--no-full-scan", action="store_true",
                            help="Desativa full-scan (usa apenas page=0).")

    grp_filtro = p.add_argument_group("Filtros / Limites")
    grp_filtro.add_argument("--no-apenas-abertos", action="store_true",
                            help="(Desativa) Filtrar apenas status abertos (A,P,Q,S).")
    grp_filtro.add_argument("--max-resp", type=int, default=200,
                            help="Máx de tarefas para lookup de responsáveis (limita chamadas).")
    grp_filtro.add_argument("--limite-responsaveis", type=int, default=50,
                            help="Máx de responsáveis a notificar (ordenado por quantidade).")
    grp_filtro.add_argument("--limite-detalhe", type=int, default=5,
                            help="Máx de tarefas detalhadas antes de resumir com contador.")
    grp_filtro.add_argument("--rate-ms", type=int, default=0,
                            help="Sleep (ms) entre chamadas de responsáveis (throttle).")

    grp_saida = p.add_argument_group("Saída / Formato")
    grp_saida.add_argument("--sem-resumo-global", action="store_true",
                           help="Não envia/mostra mensagem de resumo global.")
    grp_saida.add_argument("--verbose", action="store_true", help="Logs detalhados (debug).")
    grp_saida.add_argument("--reason", default="manual",
                           help="Motivo (registrado em métricas).")

    grp_modo = p.add_argument_group("Modo de Execução")
    grp_modo.add_argument("--enviar", action="store_true",
                          help="Modo live (envia de verdade para Teams).")
    grp_modo.add_argument("--dry-run", action="store_true",
                          help="Força dry-run (mesmo efeito do default se --enviar não estiver).")

    return p


def validar_args(args: argparse.Namespace):
    if args.enviar and args.dry_run:
        print("[ERRO] Use apenas um dos modos: ou --enviar (live) ou --dry-run (dry-run forçado).")
        sys.exit(2)
    if args.dias_proximos < 0:
        print("[ERRO] --dias-proximos deve ser >= 0.")
        sys.exit(2)
    if args.page_size <= 0:
        print("[ERRO] --page-size deve ser > 0.")
        sys.exit(2)
    if args.max_pages is not None and args.max_pages <= 0:
        print("[ERRO] --max-pages deve ser None ou > 0.")
        sys.exit(2)


def main():
    parser = build_parser()
    args = parser.parse_args()
    validar_args(args)

    # Determina modo de execução
    if args.enviar:
        execution_mode = "live"
    else:
        execution_mode = "dry_run"  # default ou se --dry-run foi passado

    if args.verbose:
        print(f"[ARGS] {args}")
        print(f"[MODO] execution_mode={execution_mode}")

    run_id = new_run_id('notify')

    apenas_status_abertos = not args.no_apenas_abertos

    if args.verbose:
        print(f"[RUN] run_id={run_id} | janela_futura={args.dias_proximos}d "
              f"| full_scan={not args.no_full_scan} | apenas_abertos={apenas_status_abertos}")

    with FileLock('storage/notification.lock', timeout=60):
        resultado = run_notification_cycle(
            dias_proximos=args.dias_proximos,
            categoria="Obrigacao",
            usar_full_scan=not args.no_full_scan,
            page_size=args.page_size,
            max_pages=args.max_pages,
            apenas_status_abertos=apenas_status_abertos,
            max_responsaveis_lookup=args.max_resp,
            limite_responsaveis_notificar=args.limite_responsaveis,
            detalhar_limite=args.limite_detalhe,
            rate_limit_sleep_ms=args.rate_ms,
            enviar_resumo_global=not args.sem_resumo_global,
            execution_mode=execution_mode,
            run_id=run_id,
            run_reason=args.reason,
            verbose=args.verbose,
            registrar_metricas=True,
        )

    # Resumo humano
    counts = resultado.get("counts", {})
    meta = resultado.get("meta_cycle", {})
    print("\n===== RESUMO CICLO =====")
    print(f"run_id: {resultado.get('run_id')}")
    print(f"modo: {resultado.get('execution_mode')}")
    janela = meta.get("janela")
    if janela:
        print(f"janela: {janela[0]} -> {janela[1]}")
    print(f"tarefas (brutas): {meta.get('tarefas_coletadas')}")
    print(f"abertos_brutos: {meta.get('abertos_brutos')} | fechados_brutos: {meta.get('fechados_brutos')}")
    print(f"após_filtro (open_after_filter): {resultado.get('open_after_filter')}")
    print(f"vencidas={counts.get('vencidas')} | hoje={counts.get('vence_hoje')} | proximos={counts.get('vence_em_3_dias')}")
    print(f"responsáveis_notificados: {counts.get('responsaveis_selecionados')} "
          f"(lista={', '.join(resultado.get('responsaveis', []))})")
    print(f"resumo_global_incluido: {resultado.get('resumo_global_incluido')}")
    print(f"full_scan: {meta.get('full_scan')} | duração_s: {meta.get('duration_s')}")
    print("=========================\n")

    # Dump bruto (para logs / debug)
    print("[INFO] Resultado completo (dict):")
    print(resultado)


if __name__ == "__main__":
    main()
