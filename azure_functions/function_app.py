# IMPORTANTE ─ azure.functions deve ser o 1.º import
import azure.functions as func

import json
import logging
import os
import sys
from datetime import datetime

# ─────────────────────────────────────────────────────────────
# PATHS & LOG
# ─────────────────────────────────────────────────────────────
sys.path.append(os.path.join(os.path.dirname(__file__), "shared_code"))

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("gclick_function_app")

APP_VERSION = "2.1.3"

# flags de ambiente
DEBUG_MOCK = os.getenv("DEBUG_MOCK", "false").lower() == "true"
IS_AZURE = bool(os.getenv("WEBSITE_INSTANCE_ID") or os.getenv("HOME"))

# ─────────────────────────────────────────────────────────────
# IMPORTS DO PROJETO
# ─────────────────────────────────────────────────────────────
try:
    from teams.user_mapping import mapear_apelido_para_teams_id
    from teams.bot_sender import BotSender, ConversationReferenceStorage
    from engine.notification_engine import run_notification_cycle

    logger.info("✅  Módulos do projeto importados")
except ImportError as imp_err:
    logger.critical(f"❌  Falha nos imports do projeto: {imp_err}")
    raise  # aborta start para evitar host quebrado

# ─────────────────────────────────────────────────────────────
# CONFIG AZURE FUNCTIONS APP
# ─────────────────────────────────────────────────────────────
app = func.FunctionApp()

# ─────────────────────────────────────────────────────────────
# BOT FRAMEWORK (opcional – só configura com credenciais)
# ─────────────────────────────────────────────────────────────
APP_ID = os.getenv("MicrosoftAppId", "")
APP_PASSWORD = os.getenv("MicrosoftAppPassword", "")

bot_sender = None
if APP_ID and APP_PASSWORD:
    try:
        from botbuilder.core import BotFrameworkAdapter, BotFrameworkAdapterSettings

        adapter = BotFrameworkAdapter(BotFrameworkAdapterSettings(APP_ID, APP_PASSWORD))

        # storage path
        if IS_AZURE and os.getenv("HOME"):
            storage_path = os.path.join(os.getenv("HOME"), "data", "conversation_references.json")
        else:
            local_dir = os.path.join(os.path.dirname(__file__), "storage")
            os.makedirs(local_dir, exist_ok=True)
            storage_path = os.path.join(local_dir, "conversation_references.json")
        os.makedirs(os.path.dirname(storage_path), exist_ok=True)

        conversation_storage = ConversationReferenceStorage(storage_path)
        bot_sender = BotSender(adapter, APP_ID, conversation_storage)

        # expõe para o engine
        import engine.notification_engine as ne

        ne.bot_sender = bot_sender
        ne.adapter = adapter
        ne.conversation_storage = conversation_storage

        logger.info(f"🤖  BotSender configurado – storage em {storage_path}")
    except Exception as bot_err:
        logger.warning(f"⚠️  Bot Framework não configurado: {bot_err}")

# ─────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────
def _run_cycle(period: str, dias_proximos: int, full_scan: bool):
    exec_mode = "live" if os.getenv("SIMULACAO", "true").lower() == "false" else "dry_run"
    logger.info(f"⏳  run_notification_cycle({period}) → modo={exec_mode}, dias={dias_proximos}")
    result = run_notification_cycle(
        dias_proximos=dias_proximos,
        execution_mode=exec_mode,
        run_reason=f"scheduled_{period}",
        usar_full_scan=full_scan,
        apenas_status_abertos=True,
    )
    logger.info(f"✅  Ciclo {period} concluído → {result}")


# ─────────────────────────────────────────────────────────────
# HTTP ─ Webhook G‑Click
# ─────────────────────────────────────────────────────────────
@app.function_name(name="GClickWebhook")
@app.route(route="gclick", methods=["POST"], auth_level=func.AuthLevel.ANONYMOUS)
def gclick_webhook(req: func.HttpRequest) -> func.HttpResponse:
    logger.info("📨  /gclick webhook chamado")
    try:
        payload = req.get_json()
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
                    logger.warning(f"Mapeamento não encontrado: {apelido}")
                    continue
                # TODO: usar bot_sender.send_message / send_card
                enviados += 1
            except Exception as map_err:
                falhou += 1
                logger.error(f"Erro no mapeamento {apelido}: {map_err}")

        return func.HttpResponse(
            json.dumps(
                {
                    "evento": evento,
                    "total_responsaveis": len(responsaveis),
                    "notificacoes_enviadas": enviados,
                    "notificacoes_falharam": falhou,
                    "timestamp": datetime.utcnow().isoformat(),
                }
            ),
            headers={"Content-Type": "application/json"},
        )
    except Exception as exc:
        logger.exception("Erro no webhook")
        return func.HttpResponse("Erro interno", status_code=500)


# ─────────────────────────────────────────────────────────────
# TIMERS
# ─────────────────────────────────────────────────────────────
@app.function_name(name="MorningNotifications")
@app.schedule(
    schedule="0 0 11 * * 1-5", arg_name="timer", run_on_startup=False, use_monitor=True
)
def morning_notifications(timer: func.TimerRequest) -> None:
    try:
        _run_cycle("morning", int(os.getenv("DIAS_PROXIMOS", "3")), full_scan=True)
    except Exception:
        logger.exception("Erro no ciclo matutino")


@app.function_name(name="AfternoonNotifications")
@app.schedule(
    schedule="0 30 20 * * 1-5", arg_name="timer", run_on_startup=False, use_monitor=True
)
def afternoon_notifications(timer: func.TimerRequest) -> None:
    try:
        _run_cycle("afternoon", int(os.getenv("DIAS_PROXIMOS", "1")), full_scan=False)
    except Exception:
        logger.exception("Erro no ciclo vespertino")


# ─────────────────────────────────────────────────────────────
# HTTP ─ Teams messages (stub)
# ─────────────────────────────────────────────────────────────
@app.function_name(name="Messages")
@app.route(route="messages", methods=["POST"], auth_level=func.AuthLevel.ANONYMOUS)
def messages(req: func.HttpRequest) -> func.HttpResponse:
    try:
        body = req.get_json()
        logger.info(
            f"Teams activity recebida: {body.get('type')} de "
            f"{body.get('from', {}).get('name')} ({body.get('from', {}).get('id')})"
        )
        return func.HttpResponse(
            json.dumps(
                {
                    "status": "received_stub_mode",
                    "adapter_status": "configured" if bot_sender else "not_configured",
                    "timestamp": datetime.utcnow().isoformat(),
                    "note": "Stub – implementar adapter.process_activity p/ processamento real",
                }
            ),
            headers={"Content-Type": "application/json"},
        )
    except Exception:
        logger.exception("Erro no stub /messages")
        return func.HttpResponse("Erro interno", status_code=500)


# ─────────────────────────────────────────────────────────────
# HTTP ─ Listagem de usuários conhecidos
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
                logger.warning(f"list_users() falhou: {err}")
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
        return func.HttpResponse(
            json.dumps(
                {
                    "users": users,
                    "count": len(users),
                    "data_source": source,
                    "timestamp": datetime.utcnow().isoformat(),
                }
            ),
            headers={"Content-Type": "application/json"},
        )
    except Exception:
        logger.exception("Erro em /debug/users")
        return func.HttpResponse("Erro interno", status_code=500)


# ─────────────────────────────────────────────────────────────
# HTTP ─ Echo genérico
# ─────────────────────────────────────────────────────────────
@app.function_name(name="HttpTrigger")
@app.route(route="http_trigger", methods=["GET", "POST"], auth_level=func.AuthLevel.ANONYMOUS)
def http_trigger(req: func.HttpRequest) -> func.HttpResponse:
    try:
        if req.method == "GET":
            name = req.params.get("name", "Mundo")
            return func.HttpResponse(
                json.dumps(
                    {
                        "message": f"Olá, {name}!",
                        "method": "GET",
                        "environment": "Azure" if IS_AZURE else "Local",
                        "timestamp": datetime.utcnow().isoformat(),
                        "version": APP_VERSION,
                    }
                ),
                headers={"Content-Type": "application/json"},
            )
        if req.method == "POST":
            body = req.get_json()
            return func.HttpResponse(
                json.dumps(
                    {
                        "echo": body,
                        "method": "POST",
                        "environment": "Azure" if IS_AZURE else "Local",
                        "timestamp": datetime.utcnow().isoformat(),
                        "version": APP_VERSION,
                    }
                ),
                headers={"Content-Type": "application/json"},
            )
        return func.HttpResponse("Método não permitido", status_code=405)
    except Exception:
        logger.exception("Erro no HTTP trigger genérico")
        return func.HttpResponse("Erro interno", status_code=500)


# ─────────────────────────────────────────────────────────────
# HTTP ─ Health check
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

    return func.HttpResponse(
        json.dumps(
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
        ),
        headers={"Content-Type": "application/json"},
    )
