from __future__ import annotations
import argparse
import uuid
import datetime as dt
import logging
from pathlib import Path
import yaml

# Assumindo que notification_engine já tem função run_notification_cycle retornando metrics dict
from engine.notification_engine import run_notification_cycle  # ajustar import conforme projeto

RUN_ID_FORMAT = "%Y%m%dT%H%M%SZ"


def build_run_id(prefix: str = "notify") -> str:
    return f"{prefix}_{dt.datetime.utcnow().strftime(RUN_ID_FORMAT)}_{uuid.uuid4().hex[:6]}"


def load_yaml(path: str | Path):
    p = Path(path)
    if not p.exists():
        return {}
    with open(p, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f) or {}


def main():
    parser = argparse.ArgumentParser(description="Executa ciclo de notificação G-Click")
    parser.add_argument('--dias-proximos', type=int, default=3)
    parser.add_argument('--mode', choices=['dry_run', 'live'], default='dry_run')
    parser.add_argument('--config', default='config/scheduling.yaml')
    parser.add_argument('--reason', default='scheduled')
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')

    run_id = build_run_id()
    logging.info("Iniciando ciclo run_id=%s mode=%s dias_proximos=%s reason=%s", run_id, args.mode, args.dias_proximos, args.reason)

    metrics = run_notification_cycle(
        dias_proximos=args.dias_proximos,
        execution_mode=args.mode,
        run_id=run_id,
        run_reason=args.reason,
        max_pages=None,  # Ilimitado para execução em produção
    )
    logging.info("Fim ciclo run_id=%s open=%s vencidas=%s hoje=%s proximos=%s", run_id,
                 metrics.get('tasks_open_after_filter'), metrics.get('tasks_vencidas'),
                 metrics.get('tasks_vence_hoje'), metrics.get('tasks_vence_proximos'))

if __name__ == '__main__':
    main()