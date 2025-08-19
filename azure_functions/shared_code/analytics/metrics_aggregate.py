from __future__ import annotations
import json, csv, glob, argparse, datetime as dt
from pathlib import Path
from typing import Iterable, Dict, Any

METRICS_GLOB = "storage/metrics/notification_cycle_*.jsonl"
AGG_JSON = Path("storage/metrics/metrics_aggregate.json")
CSV_OUT = Path("reports/exports/metrics_daily.csv")

def iter_metric_lines(debug=False) -> Iterable[dict]:
    files = sorted(glob.glob(METRICS_GLOB))
    if debug:
        print(f"[DEBUG] Encontrados {len(files)} arquivos de métricas.")
    for fname in files:
        if debug:
            print(f"[DEBUG] Lendo {fname}")
        with open(fname, 'r', encoding='utf-8') as f:
            for i, line in enumerate(f, 1):
                l = line.strip()
                if not l:
                    continue
                try:
                    data = json.loads(l)
                    if debug:
                        print(f"[DEBUG] {fname} linha {i} run_id={data.get('run_id')}")
                    yield data
                except json.JSONDecodeError:
                    if debug:
                        print(f"[WARN] Linha inválida ignorada em {fname}:{i}")
                    continue

def aggregate(lines: Iterable[dict], debug=False) -> Dict[str, dict]:
    daily: Dict[str, dict] = {}
    for ev in lines:
        if ev.get("schema_version") != 1:
            if debug:
                print(f"[DEBUG] Ignorando schema_version={ev.get('schema_version')}")
            continue
        date_key = ev.get("cycle_date")
        stats = ev.get("stats") or {}
        if not date_key or not stats:
            if debug:
                print("[DEBUG] Evento sem cycle_date ou stats – ignorado")
            continue
        rec = daily.setdefault(date_key, {
            "open_total": 0,
            "vencidas": 0,
            "vence_hoje": 0,
            "vence_proximos": 0,
            "runs": 0,
            "run_ids": [],
        })
        rec["open_total"] = max(rec["open_total"], stats.get("tasks_open_after_filter", 0))
        rec["vencidas"] = max(rec["vencidas"], stats.get("tasks_vencidas", 0))
        rec["vence_hoje"] = max(rec["vence_hoje"], stats.get("tasks_vence_hoje", 0))
        rec["vence_proximos"] = max(rec["vence_proximos"], stats.get("tasks_vence_proximos", 0))
        rec["runs"] += 1
        rid = ev.get("run_id")
        if rid:
            rec["run_ids"].append(rid)
        if debug:
            print(f"[DEBUG] Agregado {date_key}: runs={rec['runs']} open_total={rec['open_total']}")

    dates_sorted = sorted(daily.keys())
    for i, dk in enumerate(dates_sorted):
        rec = daily[dk]
        open_total = rec["open_total"] or 0
        rec["pct_vencidas"] = (rec["vencidas"] / open_total) if open_total else None
        window_keys = dates_sorted[max(0, i - 6): i + 1]
        opens = [daily[w]["open_total"] for w in window_keys if daily[w]["open_total"] is not None]
        rec["open_7d_avg"] = sum(opens) / len(opens) if opens else None
        rec["anomalia_flag"] = bool(open_total == 0 or (rec["pct_vencidas"] or 0) > 0.5)
    return daily

def write_outputs(daily: Dict[str, dict]):
    AGG_JSON.parent.mkdir(parents=True, exist_ok=True)
    CSV_OUT.parent.mkdir(parents=True, exist_ok=True)
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    with open(AGG_JSON, 'w', encoding='utf-8') as f:
        json.dump({"generated_at": now, "days": daily}, f, ensure_ascii=False, indent=2)
    with open(CSV_OUT, 'w', newline='', encoding='utf-8') as f:
        w = csv.writer(f)
        w.writerow(["date","open_total","vencidas","vence_hoje","vence_proximos","pct_vencidas","open_7d_avg","runs","anomalia_flag"])
        for dk in sorted(daily.keys()):
            rec = daily[dk]
            w.writerow([
                dk,
                rec["open_total"], rec["vencidas"], rec["vence_hoje"], rec["vence_proximos"],
                f"{rec['pct_vencidas']:.4f}" if rec['pct_vencidas'] is not None else "",
                f"{rec['open_7d_avg']:.2f}" if rec['open_7d_avg'] is not None else "",
                rec["runs"], rec["anomalia_flag"],
            ])

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--since', help='YYYY-MM-DD (filtra dias >=)')
    ap.add_argument('--debug', action='store_true')
    args = ap.parse_args()

    lines = list(iter_metric_lines(debug=args.debug))
    daily = aggregate(lines, debug=args.debug)
    if args.since:
        daily = {k: v for k, v in daily.items() if k >= args.since}
    write_outputs(daily)
    if args.debug:
        print(f"[DEBUG] Dias agregados: {list(daily.keys())}")

if __name__ == '__main__':
    main()
