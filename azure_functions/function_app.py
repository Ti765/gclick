# IMPORTANTE — azure.functions deve ser o 1.º import
import azure.functions as func

import json
import logging
import os
import sys
from datetime import datetime
from pathlib import Path

# ─────────────────────────────────────────────────────────────
# PATHS & LOG
# ─────────────────────────────────────────────────────────────
SHARED_DIR = Path(__file__).parent / "shared_code"
if SHARED_DIR.exists():
    # Insere no início para garantir prioridade sobre outras entradas
    shared_str = str(SHARED_DIR.resolve())
    if shared_str not in sys.path:
        sys.path.insert(0, shared_str)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("gclick_function_app")

APP_VERSION = "2.1.4"

# Flags de ambiente
DEBUG_MOCK = os.getenv("DEBUG_MOCK", "false").lower() == "true"
IS_AZURE = bool(os.getenv("WEBSITE_INSTANCE_ID") or os.getenv("HOME"))

# ─────────────────────────────────────────────────────────────
# IMPORTS DO PROJETO (robustos: tenta direto e com prefixo shared_code)
# ─────────────────────────────────────────────────────────────
try:
    try:
        # Estilo quando shared_code está no sys.path
        from teams.user_mapping import mapear_apelido_para_teams_id  # type: ignore
        from teams.bot_sender import BotSender, ConversationReferenceStorage  # type: ignore
        from engine.notification_engine import run_notification_cycle  # type: ignore
        import_style = "plain"
    except ImportError:
        # Estilo alternativo se o ambiente exige prefixo explícito
        from shared_code.teams.user_mapping import mapear_apelido_para_teams_id  # type: ignore
        from shared_code.teams.bot_sender import BotSender, ConversationReferenceStorage  # type: ignore
        from shared_code.engine.notification_engine import run_notification_cycle  # type: ignore
        import_style = "shared_code"

    logger.info("✅  Módulos do projeto importados (%s)", import_style)
except Exception as imp_err:
    logger.critical("❌  Falha nos imports do projeto: %s", imp_err, exc_info=True)

    # Erros de importação podem impedir a indexação; stubs mantêm o app carregável.
    def mapear_apelido_para_teams_id(*_args, **_kwargs):
        logger.error("mapear_apelido_para_teams_id indisponível")
        return None

    class ConversationReferenceStorage:  # type: ignore
        def __init__(self, file_path: str = ""):
            self.file_path = file_path
            self._data = {}

        def list_users(self):
            return list(self._data.keys())

    class BotSender:  # type: ignore
        def __init__(self, *_args, **_kwargs):
            self.conversation_storage = ConversationReferenceStorage()

    def run_notification_cycle(*_args, **_kwargs):
        logger.error("run_notification_cycle indisponível")
        return {}

# ─────────────────────────────────────────────────────────────
# CONFIG AZURE FUNCTIONS APP
# ─────────────────────────────────────────────────────────────
# Define ANONYMOUS por padrão (cada rota também define explicitamente)
app = func.FunctionApp(http_auth_level=func.AuthLevel.ANONYMOUS)

# ─────────────────────────────────────────────────────────────
# BOT FRAMEWORK (opcional – só configura com credenciais)
# ─────────────────────────────────────────────────────────────
APP_ID = os.getenv("MicrosoftAppId", "")
APP_PASSWORD = os.getenv("MicrosoftAppPassword", "")

bot_sender = None
if APP_ID and APP_PASSWORD:
    try:
        from botbuilder.core import BotFrameworkAdapter, BotFrameworkAdapterSettings  # type: ignore

        adapter = BotFrameworkAdapter(BotFrameworkAdapterSettings(APP_ID, APP_PASSWORD))

        # storage path persistente (fora de wwwroot em produção)
        if IS_AZURE and os.getenv("HOME"):
            base = Path(os.getenv("HOME"))
            storage_path = base / "data" / "conversation_references.json"
        else:
            base = Path(__file__).parent / "storage"
            base.mkdir(parents=True, exist_ok=True)
            storage_path = base / "conversation_references.json"
        storage_path.parent.mkdir(parents=True, exist_ok=True)

        conversation_storage = ConversationReferenceStorage(str(storage_path))
        bot_sender = BotSender(adapter, APP_ID, conversation_storage)

        # expõe para o engine (se presente)
        try:
            import engine.notification_engine as ne  # type: ignore
            ne.bot_sender = bot_sender
            ne.adapter = adapter
            ne.conversation_storage = conversation_storage
        except Exception:
            pass

        logger.info("🤖  BotSender configurado – storage em %s", storage_path)
    except Exception as bot_err:
        logger.warning("⚠️  Bot Framework não configurado: %s", bot_err, exc_info=True)

# ─────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────
def _json(payload: dict, status: int = 200) -> func.HttpResponse:
    return func.HttpResponse(
        json.dumps(payload, ensure_ascii=False),
        status_code=status,
        headers={"Content-Type": "application/json"},
    )

def _run_cycle(period: str, dias_proximos: int, full_scan: bool):
    exec_mode = "live" if os.getenv("SIMULACAO", "true").lower() == "false" else "dry_run"
    logger.info("⏳  run_notification_cycle(%s) → modo=%s, dias=%s", period, exec_mode, dias_proximos)
    result = run_notification_cycle(
        dias_proximos=dias_proximos,
        execution_mode=exec_mode,
        run_reason=f"scheduled_{period}",
        usar_full_scan=full_scan,
        apenas_status_abertos=True,
    )
    logger.info("✅  Ciclo %s concluído → %s", period, result)

# ─────────────────────────────────────────────────────────────
# HTTP — Webhook G‑Click
# ─────────────────────────────────────────────────────────────
@app.function_name(name="GClickWebhook")
@app.route(route="gclick", methods=["POST"], auth_level=func.AuthLevel.ANONYMOUS)
def gclick_webhook(req: func.HttpRequest) -> func.HttpResponse:
    logger.info("📨  /gclick webhook chamado")
    try:
        try:
            payload = req.get_json()
        except ValueError:
            return func.HttpResponse("Payload inválido", status_code=400)

        if not payload:
            return func.HttpResponse("Payload vazio", status_code=400)

        evento = payload.get("evento", "notificacao_generica")
        responsaveis = payload.get("responsaveis", [])

        enviados, falhou = 0, 0
        for resp in responsaveis:
            apelido = (resp.get("apelido") or "").strip()
            if not apelido:
                continue
            try:
                teams_id = mapear_apelido_para_teams_id(apelido)
                if not teams_id:
                    falhou += 1
                    logger.warning("Mapeamento não encontrado: %s", apelido)
                    continue
                # TODO: usar bot_sender.send_message / send_card quando disponível
                enviados += 1
            except Exception as map_err:
                falhou += 1
                logger.error("Erro no mapeamento %s: %s", apelido, map_err)

        return _json(
            {
                "evento": evento,
                "total_responsaveis": len(responsaveis),
                "notificacoes_enviadas": enviados,
                "notificacoes_falharam": falhou,
                "timestamp": datetime.utcnow().isoformat(),
            }
        )
    except Exception:
        logger.exception("Erro no webhook")
        return func.HttpResponse("Erro interno", status_code=500)

# ─────────────────────────────────────────────────────────────
# TIMERS
# ─────────────────────────────────────────────────────────────
@app.function_name(name="MorningNotifications")
@app.schedule(schedule="0 0 11 * * 1-5", arg_name="timer", run_on_startup=False, use_monitor=True)
def morning_notifications(timer: func.TimerRequest) -> None:
    try:
        _run_cycle("morning", int(os.getenv("DIAS_PROXIMOS", "3")), full_scan=True)
    except Exception:
        logger.exception("Erro no ciclo matutino")

@app.function_name(name="AfternoonNotifications")
@app.schedule(schedule="0 30 20 * * 1-5", arg_name="timer", run_on_startup=False, use_monitor=True)
def afternoon_notifications(timer: func.TimerRequest) -> None:
    try:
        _run_cycle("afternoon", int(os.getenv("DIAS_PROXIMOS", "1")), full_scan=False)
    except Exception:
        logger.exception("Erro no ciclo vespertino")

# ─────────────────────────────────────────────────────────────
# HTTP — Teams messages (stub)
# ─────────────────────────────────────────────────────────────
@app.function_name(name="Messages")
@app.route(route="messages", methods=["POST"], auth_level=func.AuthLevel.ANONYMOUS)
def messages(req: func.HttpRequest) -> func.HttpResponse:
    try:
        body = req.get_json()
        logger.info(
            "Teams activity recebida: %s de %s (%s)",
            body.get("type"),
            body.get("from", {}).get("name"),
            body.get("from", {}).get("id"),
        )
        return _json(
            {
                "status": "received_stub_mode",
                "adapter_status": "configured" if bot_sender else "not_configured",
                "timestamp": datetime.utcnow().isoformat(),
                "note": "Stub — implemente adapter.process_activity para processamento real",
            }
        )
    except Exception:
        logger.exception("Erro no stub /messages")
        return func.HttpResponse("Erro interno", status_code=500)

# ─────────────────────────────────────────────────────────────
# HTTP — Listagem de usuários conhecidos
# ─────────────────────────────────────────────────────────────
@app.function_name(name="ListUsers")
@app.route(route="debug/users", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def list_users(req: func.HttpRequest) -> func.HttpResponse:
    users, source = [], "no_storage"
    try:
        if bot_sender:
            try:
                users = [{"id": uid} for uid in bot_sender.conversation_storage.list_users()]
                source = "list_users"
            except Exception as err:
                logger.warning("list_users() falhou: %s", err)
                # fallback interno
                for attr in ("_conversations", "references", "_data"):
                    if hasattr(bot_sender.conversation_storage, attr):
                        raw = getattr(bot_sender.conversation_storage, attr)
                        users = [{"id": k} for k in raw] if isinstance(raw, dict) else []
                        source = f"internal_{attr}"
                        break
        elif DEBUG_MOCK or not IS_AZURE:
            users = [{"id": "mock_user_1"}, {"id": "mock_user_2"}]
            source = "mock"

        return _json(
            {
                "users": users,
                "count": len(users),
                "data_source": source,
                "timestamp": datetime.utcnow().isoformat(),
            }
        )
    except Exception:
        logger.exception("Erro em /debug/users")
        return func.HttpResponse("Erro interno", status_code=500)

# ─────────────────────────────────────────────────────────────
# HTTP — Echo genérico
# ─────────────────────────────────────────────────────────────
@app.function_name(name="HttpTrigger")
@app.route(route="http_trigger", methods=["GET", "POST"], auth_level=func.AuthLevel.ANONYMOUS)
def http_trigger(req: func.HttpRequest) -> func.HttpResponse:
    try:
        if req.method == "GET":
            name = req.params.get("name", "Mundo")
            return _json(
                {
                    "message": f"Olá, {name}!",
                    "method": "GET",
                    "environment": "Azure" if IS_AZURE else "Local",
                    "timestamp": datetime.utcnow().isoformat(),
                    "version": APP_VERSION,
                }
            )
        if req.method == "POST":
            body = req.get_json()
            return _json(
                {
                    "echo": body,
                    "method": "POST",
                    "environment": "Azure" if IS_AZURE else "Local",
                    "timestamp": datetime.utcnow().isoformat(),
                    "version": APP_VERSION,
                }
            )
        return func.HttpResponse("Método não permitido", status_code=405)
    except Exception:
        logger.exception("Erro no HTTP trigger genérico")
        return func.HttpResponse("Erro interno", status_code=500)

# ─────────────────────────────────────────────────────────────
# HTTP — Health check
# ─────────────────────────────────────────────────────────────
@app.function_name(name="HealthCheck")
@app.route(route="health", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def health(req: func.HttpRequest) -> func.HttpResponse:
    storage_status, storage_info = "not_configured", {}
    if bot_sender:
        try:
            s_path = getattr(bot_sender.conversation_storage, "file_path", "unknown")
            storage_status = "healthy" if os.path.exists(s_path) else "missing_file"
            storage_info = {"path": s_path, "exists": os.path.exists(s_path)}
        except Exception as st_err:
            storage_status, storage_info = "error", {"error": str(st_err)}

    try:
        mapping_test = mapear_apelido_para_teams_id("teste_health_check")
        mapping_status = "ok" if mapping_test is not None else "no_match"
    except Exception as mp_err:
        mapping_status = f"error: {mp_err}"

    return _json(
        {
            "status": "healthy",
            "version": APP_VERSION,
            "python": sys.version.split()[0],
            "environment": "Azure" if IS_AZURE else "Local",
            "bot_configured": bool(bot_sender),
            "storage": {"status": storage_status, **storage_info},
            "user_mapping": mapping_status,
            "timestamp": datetime.utcnow().isoformat(),
            "functions_detected": {
                "total": 7,
                "http_endpoints": 5,
                "timer_triggers": 2,
            },
        }
    )
