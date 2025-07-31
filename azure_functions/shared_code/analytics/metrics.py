"""Escrita de métricas em JSON Lines.
Inclui enriquecimento Sprint 3: schema_version, run_id, execution_mode, collected_at.
"""
from __future__ import annotations
import json
import os
import uuid
import datetime as dt
from pathlib import Path
from typing import Any, Optional

SCHEMA_VERSION = 1
METRICS_DIR = Path(os.getenv('METRICS_DIR', 'storage/metrics'))
METRICS_DIR.mkdir(parents=True, exist_ok=True)

def _month_file(prefix: str, cycle_date: str) -> Path:
    # cycle_date: YYYY-MM-DD
    ym = cycle_date[:7]
    return METRICS_DIR / f"{prefix}_{ym}.jsonl"

def new_run_id(prefix: str = 'run') -> str:
    return f"{prefix}_{dt.datetime.utcnow().strftime('%Y%m%dT%H%M%SZ')}_{uuid.uuid4().hex[:6]}"

def write_notification_cycle(
    *,
    run_id: str,
    execution_mode: str,
    cycle_date: str,
    window_days: int,
    stats: dict,
    responsaveis: dict | None = None,
    api: dict | None = None,
    limits: dict | None = None,
    extra: dict | None = None,
):
    line = {
        "schema_version": SCHEMA_VERSION,
        "run_id": run_id,
        "collected_at": dt.datetime.utcnow().isoformat() + 'Z',
        "execution_mode": execution_mode,
        "window_days": window_days,
        "cycle_date": cycle_date,
        "timezone": os.getenv('APP_TIMEZONE', 'America/Sao_Paulo'),
        "stats": stats,
    }
    if responsaveis:
        line["responsaveis"] = responsaveis
    if api:
        line["api"] = api
    if limits:
        line["limits"] = limits
    if extra:
        line.update(extra)

    fpath = _month_file('notification_cycle', cycle_date)
    fpath.parent.mkdir(parents=True, exist_ok=True)
    with open(fpath, 'a', encoding='utf-8') as f:
        f.write(json.dumps(line, ensure_ascii=False) + '\n')
        