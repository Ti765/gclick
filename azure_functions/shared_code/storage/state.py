import json
from pathlib import Path
from threading import RLock
from datetime import date

_STATE_FILE = Path("storage/notification_state.json")
_LOCK = RLock()

def _ensure_file():
    if not _STATE_FILE.parent.exists():
        _STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    if not _STATE_FILE.exists():
        _STATE_FILE.write_text(json.dumps({"entries": []}, ensure_ascii=False))

def load_state():
    with _LOCK:
        _ensure_file()
        try:
            data = json.loads(_STATE_FILE.read_text(encoding="utf-8"))
            if "entries" not in data:
                data["entries"] = []
            return data
        except Exception:
            return {"entries": []}

def save_state(data):
    with _LOCK:
        _STATE_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False))

def already_sent(key: str) -> bool:
    data = load_state()
    return key in data["entries"]

def register_sent(key: str):
    data = load_state()
    if key not in data["entries"]:
        data["entries"].append(key)
        save_state(data)

def purge_older_than(days: int = 7):
    """
    Remove entradas com data anterior a hoje - days (segurança).
    Formato chave: YYYY-MM-DD|apelido|...
    """
    today = date.today()
    data = load_state()
    kept = []
    for k in data["entries"]:
        try:
            d_str = k.split("|", 1)[0]
            y, m, d = map(int, d_str.split("-"))
            kd = date(y, m, d)
            delta = (today - kd).days
            if delta <= days:
                kept.append(k)
        except Exception:
            # se formato inesperado, mantemos por segurança
            kept.append(k)
    if len(kept) != len(data["entries"]):
        data["entries"] = kept
        save_state(data)
