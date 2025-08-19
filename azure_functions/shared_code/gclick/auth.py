# gclick/auth.py
import os
import time
import requests
from dotenv import load_dotenv

load_dotenv()

TOKEN_URL = "https://api.gclick.com.br/oauth/token"

# Cache em memória
_cached_token = None
_cached_expira_em = 0  # epoch seconds

def get_access_token(force: bool = False) -> str:
    """
    Obtém token OAuth diretamente (sem SDK).
    Faz cache até expirar (margem de 60s).
    Campos necessários no .env:
      GCLICK_CLIENT_ID
      GCLICK_CLIENT_SECRET
      GCLICK_SISTEMA
      GCLICK_CONTA
      GCLICK_USUARIO
      GCLICK_SENHA
      GCLICK_EMPRESA
    """
    global _cached_token, _cached_expira_em

    agora = time.time()
    if not force and _cached_token and agora < (_cached_expira_em - 60):
        return _cached_token

    payload = {
        "grant_type": "client_credentials",
        "client_id": os.environ["GCLICK_CLIENT_ID"],
        "client_secret": os.environ["GCLICK_CLIENT_SECRET"],
        "sistema": os.environ["GCLICK_SISTEMA"],
        "conta": os.environ["GCLICK_CONTA"],
        "usuario": os.environ["GCLICK_USUARIO"],
        "senha": os.environ["GCLICK_SENHA"],
        "empresa": os.environ["GCLICK_EMPRESA"],
    }

    resp = requests.post(TOKEN_URL, data=payload, timeout=30)
    if resp.status_code >= 400:
        raise RuntimeError(
            f"Falha ao obter token ({resp.status_code}): {resp.text[:500]}"
        )
    data = resp.json()
    access = data.get("access_token")
    expires_in = data.get("expires_in", 3600)
    if not access:
        raise RuntimeError(f"Resposta sem access_token: {data}")

    _cached_token = access
    _cached_expira_em = agora + int(expires_in)
    return _cached_token
