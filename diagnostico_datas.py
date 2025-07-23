# diagnostico_datas.py (Sprint 3 atualizado)
import os
import sys
import csv
import json
import argparse
from collections import Counter
from datetime import date, datetime, timedelta

from dotenv import load_dotenv
load_dotenv()  # garante carregamento do .env local

try:
    from analytics.metrics import new_run_id
except ImportError:
    def new_run_id(prefix: str = 'run'):  # type: ignore
        return f"{prefix}_dummy"

RUN_ID = new_run_id('diag')
print(f"[diag] run_id={RUN_ID}")

# ===== Verificação inicial de variáveis de ambiente =====
ENV_REQUIRED = [
    "GCLICK_CLIENT_ID",
    "GCLICK_CLIENT_SECRET",
    "GCLICK_SISTEMA",
    "GCLICK_CONTA",
    "GCLICK_USUARIO",
    "GCLICK_EMPRESA",
]

missing = [k for k in ENV_REQUIRED if not os.getenv(k)]
if missing:
    print("[ERRO] Variáveis ausentes no ambiente:", ", ".join(missing))
    print("Verifique seu .env e se está executando no diretório correto.")
    sys.exit(1)

try:
    from gclick.tarefas import (
        listar_tarefas_page,
        normalizar_tarefa,
    )
except ImportError as e:
    print("[ERRO] Falha ao importar gclick.tarefas:", e)
    sys.exit(1)

# Caso _parse_date não esteja exposto, definimos fallback
def _parse_date_safe(s: str):
    if not s:
        return None
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%d/%m/%Y"):
        try:
            return datetime.strptime(s[:10], fmt).date()
        except ValueError:
            continue
    return None

STATUS_LABEL = {
    "A": "Aberto/Autorizada",
    "S": "Aguardando",
    "C": "Concluído",
    "D": "Dispensado",
    "F": "Finalizado",
    "E": "Retificando",
    "O": "Retificado",
    "P": "Solicitado (email)",
    "Q": "Solicitado (Visão Cliente)"
}

DEFAULT_STATUS_ABERTOS = ["A", "S", "Q", "P"]

def parse_args():
    ap = argparse.ArgumentParser(
        description="Diagnóstico de datas e classificação de tarefas G-Click"
    )
    ap.add_argument("--dias-proximos", type=int, default=3,
                    help="Dias futuros (>=0) a considerar (default=3)")
    ap.add_argument("--retro-dias", type=int, default=0,
                    help="Dias passados para incluir (vencidas) (default=0)")
    ap.add_argument("--categoria", default="Obrigacao",
                    help="Categoria (default=Obrigacao)")
    ap.add_argument("--page-size", type=int, default=200,
                    help="Tamanho da página (default=200)")
    ap.add_argument("--max-pages", type=int, default=None,
                    help="Máx de páginas (default=todo intervalo)")
    ap.add_argument("--status-abertos", default=",".join(DEFAULT_STATUS_ABERTOS),
                    help="CSV de status considerados abertos (default=A,S,Q,P)")
    ap.add_argument("--usar-fallback", action="store_true",
                    help="Usar dataMeta -> dataAcao como fallback para dataVencimento ausente.")
    ap.add_argument("--csv-out", default=None,
                    help="Exportar CSV com diagnóstico detalhado.")
    ap.add_argument("--top-datas", type=int, default=10,
                    help="Número de datas distintas a exibir por campo (default=10)")
    ap.add_argument("--max-exemplos", type=int, default=5,
                    help="Exemplos por motivo de exclusão (default=5)")
    ap.add_argument("--verbose", action="store_true",
                    help="Logs detalhados.")
    return ap.parse_args()

def collect_tasks(categoria, inicio: date, fim: date, page_size=200, max_pages=None, verbose=False):
    tarefas = []
    page = 0
    while True:
        tasks_page, meta = listar_tarefas_page(
            categoria=categoria,
            page=page,
            size=page_size,
            dataVencimentoInicio=inicio.isoformat(),
            dataVencimentoFim=fim.isoformat()
        )
        tarefas.extend(tasks_page)
        if verbose:
            print(f"[PAG] page={page} obtidas={len(tasks_page)} totalPages={meta.get('totalPages')}")
        page += 1
        if meta.get("last"):
            break
        if max_pages is not None and page >= max_pages:
            if verbose:
                print("[INFO] max_pages atingido.")
            break
    return tarefas

def normalize_all(raw_tasks):
    out = []
    for t in raw_tasks:
        try:
            nt = normalizar_tarefa(t)
        except Exception:
            nt = dict(t)  # fallback raso
        # Garantir campos *_dt se não existirem
        for campo in ("dataVencimento", "dataMeta", "dataAcao", "dataConclusao"):
            dt_key = f"{campo}_dt"
            if dt_key not in nt:
                nt[dt_key] = _parse_date_safe(nt.get(campo))
        out.append(nt)
    return out

def classify(tasks, hoje: date, abertos_set, usar_fallback=False):
    buckets = {"vencidas": [], "vence_hoje": [], "vence_em_3_dias": []}
    excl = {"sem_data": [], "fora_janela": [], "status_fechado": []}

    for t in tasks:
        status = t.get("status")
        dt_venc = t.get("dataVencimento_dt")
        if usar_fallback and dt_venc is None:
            dt_venc = t.get("dataMeta_dt") or t.get("dataAcao_dt")

        if dt_venc is None:
            excl["sem_data"].append(t)
            continue

        if status not in abertos_set:
            excl["status_fechado"].append(t)
            continue

        delta = (dt_venc - hoje).days
        if delta < 0:
            buckets["vencidas"].append(t)
        elif delta == 0:
            buckets["vence_hoje"].append(t)
        elif 0 < delta <= 3:
            buckets["vence_em_3_dias"].append(t)
        else:
            excl["fora_janela"].append(t)

    return buckets, excl

def collect_date_stats(tasks):
    fields = ["dataVencimento", "dataMeta", "dataAcao", "dataConclusao"]
    presence = {f: 0 for f in fields}
    distinct = {f: Counter() for f in fields}
    for t in tasks:
        for f in fields:
            val = t.get(f)
            if val:
                presence[f] += 1
                distinct[f][val] += 1
    return presence, distinct

def print_top_distinct(distinct, top_n=10):
    for f, counter in distinct.items():
        print(f"\n[DATAS] {f} distintos={len(counter)} top {top_n}:")
        for v, c in counter.most_common(top_n):
            print(f"  {v} -> {c}")

def show_examples(excl, max_ex=5):
    for reason, itens in excl.items():
        print(f"\n[EXCLUSÃO] {reason} total={len(itens)}")
        for t in itens[:max_ex]:
            print(f"  - id={t.get('id')} status={t.get('status')} nome={t.get('nome')}")

def export_csv(path, tasks, buckets, excl, usar_fallback):
    bucket_map = {}
    for b, lista in buckets.items():
        for t in lista:
            bucket_map[t.get("id")] = b
    excl_map = {}
    for r, lista in excl.items():
        for t in lista:
            excl_map[t.get("id")] = r

    fields = [
        "id","status","status_label","dataVencimento","dataMeta","dataAcao","dataConclusao",
        "bucket","exclusao","usar_fallback"
    ]
    with open(path, "w", newline="", encoding="utf-8") as f:
        wr = csv.writer(f, delimiter=";")
        wr.writerow(fields)
        for t in tasks:
            sid = t.get("id")
            st = t.get("status")
            wr.writerow([
                sid,
                st,
                STATUS_LABEL.get(st, ""),
                t.get("dataVencimento"),
                t.get("dataMeta"),
                t.get("dataAcao"),
                t.get("dataConclusao"),
                bucket_map.get(sid, ""),
                excl_map.get(sid, ""),
                "1" if usar_fallback else "0"
            ])
    print(f"[CSV] Exportado: {path}")

def main():
    args = parse_args()

    hoje = date.today()
    inicio = hoje - timedelta(days=args.retro_dias)
    fim = hoje + timedelta(days=args.dias_proximos)

    abertos_set = {s.strip() for s in args.status_abertos.split(",") if s.strip()}
    print(f"[INFO] Janela: {inicio} -> {fim} | categoria={args.categoria}")
    print(f"[INFO] Status abertos: {sorted(abertos_set)} | fallback={args.usar_fallback}")

    # 1. Coleta
    raw = collect_tasks(
        categoria=args.categoria,
        inicio=inicio,
        fim=fim,
        page_size=args.page_size,
        max_pages=args.max_pages,
        verbose=args.verbose
    )
    print(f"[INFO] Coletadas {len(raw)} tarefas (brutas)")

    # 2. Normalização
    tasks = normalize_all(raw)

    # 3. Estatísticas de datas
    presence, distinct = collect_date_stats(tasks)
    print("\n[PRESENÇA DE DATAS]")
    total = len(tasks) or 1
    for f, c in presence.items():
        print(f"  - {f}: {c} ({c/total*100:.1f}%)")

    print_top_distinct(distinct, top_n=args.top_datas)

    # 4. Status
    dist_status = Counter([t.get("status") for t in tasks])
    print("\n[STATUS] Distribuição:")
    for s, cnt in dist_status.most_common():
        print(f"  {s} {STATUS_LABEL.get(s,'?')}: {cnt} ({cnt/total*100:.1f}%)")

    # 5. Classificação – sem fallback
    buckets_nf, excl_nf = classify(tasks, hoje, abertos_set, usar_fallback=False)
    print("\n[CLASSIFICAÇÃO - SEM FALLBACK]")
    for b, lst in buckets_nf.items():
        print(f"  {b}: {len(lst)}")
    print("[EXCLUSÕES - SEM FALLBACK]")
    for r, lst in excl_nf.items():
        print(f"  {r}: {len(lst)}")

    show_examples(excl_nf, max_ex=args.max_exemplos)

    # 6. Classificação – com fallback (opcional)
    if args.usar_fallback:
        buckets_fb, excl_fb = classify(tasks, hoje, abertos_set, usar_fallback=True)
        print("\n[CLASSIFICAÇÃO - COM FALLBACK]")
        for b, lst in buckets_fb.items():
            print(f"  {b}: {len(lst)}")
        print("[EXCLUSÕES - COM FALLBACK]")
        for r, lst in excl_fb.items():
            print(f"  {r}: {len(lst)}")

        print("\n[COMPARATIVO]")
        for b in buckets_nf:
            sem = len(buckets_nf[b])
            com = len(buckets_fb[b])
            print(f"  {b}: sem={sem} com={com} (+{com-sem})")

        show_examples(excl_fb, max_ex=args.max_exemplos)

    # 7. CSV
    if args.csv_out:
        if args.usar_fallback:
            root, ext = (args.csv_out.rsplit(".", 1) + ["csv"])[:2]
            export_csv(f"{root}_nofallback.{ext}", tasks, buckets_nf, excl_nf, usar_fallback=False)
            export_csv(f"{root}_fallback.{ext}", tasks, buckets_fb, excl_fb, usar_fallback=True)
        else:
            export_csv(args.csv_out, tasks, buckets_nf, excl_nf, usar_fallback=False)

    # 8. Resumo JSON
    resumo = {
        "run_id": RUN_ID,
        "total": len(tasks),
        "janela": {"inicio": inicio.isoformat(), "fim": fim.isoformat(), "hoje": hoje.isoformat()},
        "status_abertos": sorted(abertos_set),
        "sem_fallback": {k: len(v) for k, v in buckets_nf.items()},
        "exclusoes_sem_fallback": {k: len(v) for k, v in excl_nf.items()}
    }
    if args.usar_fallback:
        resumo["com_fallback"] = {k: len(v) for k, v in buckets_fb.items()}
    print("\n[RESUMO JSON]")
    print(json.dumps(resumo, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()
    