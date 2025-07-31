import os
import yaml
from functools import lru_cache

DEFAULT_CONFIG_PATH = os.environ.get("GCLICK_CONFIG_FILE", "config/config.yaml")

@lru_cache(maxsize=1)
def load_config(path: str = None) -> dict:
    path = path or DEFAULT_CONFIG_PATH
    if not os.path.exists(path):
        raise FileNotFoundError(f"Config não encontrada em {path}")
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    # Overrides simples via env (exemplo)
    categoria_env = os.getenv("GCLICK_CATEGORIA")
    if categoria_env:
        data.setdefault("notificacoes", {}).setdefault("filtros_busca", {})["categoria"] = categoria_env
    return data
