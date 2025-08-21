# IMPORTANTE — azure.functions deve ser o 1.º import
import azure.functions as func

import json
import logging
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Tuple, Optional

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
# HELPERS PARA PROCESSAMENTO DE AÇÕES
# ─────────────────────────────────────────────────────────────

def _extract_card_action(activity: dict) -> Tuple[Optional[str], Optional[str]]:
    """
    Extrai (action, task_id) cobrindo múltiplos formatos possíveis do Teams:
    - message + value.{action, taskId}
    - invoke (Universal Actions) + value.action.{data, verb}
    - value.data.{action, taskId}
    - channelData.postback.{action, taskId} (messageBack)
    """
    # Fonte principal do Teams
    v = activity.get("value") or {}
    # Alguns clientes colocam no channelData.postback
    if not v and isinstance(activity.get("channelData"), dict):
        v = activity["channelData"].get("postback") or {}

    # Universal Actions (Action.Execute): value.action = { type, data, verb, ... }
    if isinstance(v.get("action"), dict):
        inner = v["action"]
        inner_data = inner.get("data") or {}
        action = inner_data.get("action") or inner.get("verb")
        task_id = inner_data.get("taskId") or inner_data.get("id") or inner_data.get("task_id")
        if action or task_id:
            return action, task_id

    # Formatos simples: value.data.{...}
    if isinstance(v.get("data"), dict):
        d = v["data"]
        action = d.get("action") or d.get("verb")
        task_id = d.get("taskId") or d.get("id") or d.get("task_id")
        if action or task_id:
            return action, task_id

    # Formato clássico: value.{...}
    action = v.get("action") or v.get("verb")
    task_id = v.get("taskId") or v.get("id") or v.get("task_id")
    return action, task_id

# ─────────────────────────────────────────────────────────────
# ─────────────────────────────────────────────────────────────
# CONFIGURAÇÃO ROBUSTA DO BOT FRAMEWORK
# ─────────────────────────────────────────────────────────────
# Variáveis de ambiente (tentativa com nomes alternativos para compatibilidade)
APP_ID = os.getenv("MicrosoftAppId") or os.getenv("MICROSOFT_APP_ID", "")
APP_PASSWORD = os.getenv("MicrosoftAppPassword") or os.getenv("MICROSOFT_APP_PASSWORD", "")

bot_sender = None
conversation_storage = None

if APP_ID and APP_PASSWORD:
    try:
        from botbuilder.core import BotFrameworkAdapter, BotFrameworkAdapterSettings  # type: ignore

        # Configurar adapter do Bot Framework
        adapter_settings = BotFrameworkAdapterSettings(APP_ID, APP_PASSWORD)
        adapter = BotFrameworkAdapter(adapter_settings)

        # Configuração de storage path persistente baseado no ambiente
        if IS_AZURE:
            # Azure Functions: usar diretório persistente $HOME/data
            storage_base = Path(os.getenv("HOME", "/tmp")) / "data" / "gclick_teams"
        else:
            # Desenvolvimento local: usar diretório do projeto
            storage_base = Path(__file__).parent / "storage"
        
        # Criar diretórios necessários
        storage_base.mkdir(parents=True, exist_ok=True)
        storage_path = storage_base / "conversation_references.json"

        # Inicializar armazenamento robusto de conversation references
        conversation_storage = ConversationReferenceStorage(str(storage_path))
        
        # Inicializar BotSender com configuração completa
        bot_sender = BotSender(adapter, APP_ID, conversation_storage)

        logger.info("🤖  Bot Framework configurado com sucesso")
        logger.info("📁  Storage path: %s", storage_path)
        logger.info("🆔  App ID: %s...", APP_ID[:8] if APP_ID else "N/A")

        # Integrar storage na engine de notificação (se disponível)
        try:
            import engine.notification_engine as ne  # type: ignore
            ne.bot_sender = bot_sender
            ne.adapter = adapter
            ne.conversation_storage = conversation_storage
            logger.info("🔗  ConversationStorage integrado à NotificationEngine")
        except Exception as integration_err:
            logger.warning("⚠️  Falha na integração com NotificationEngine: %s", integration_err)
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
    """
    Endpoint robusto para receber mensagens do Teams.
    Processa Adaptive Cards, armazena ConversationReferences e trata interações do usuário.
    """
    try:
        body = req.get_json()
        msg_type = body.get("type")
        name = body.get("name")
        from_user = body.get("from", {})
        conversation = body.get("conversation", {})
        
        logger.info("📱 Teams activity: type=%s, name=%s, user=%s", 
                   msg_type, name, from_user.get("name"))

        # Armazenar/atualizar ConversationReference se disponível
        if conversation_storage and conversation.get("id"):
            try:
                # Extrair informações necessárias para ConversationReference
                user_id = from_user.get("id")
                conversation_id = conversation.get("id")
                service_url = body.get("serviceUrl", "")
                
                if user_id and conversation_id:
                    # Criar/atualizar entrada no storage
                    conversation_storage.store_conversation_reference(
                        user_id=user_id,
                        conversation_id=conversation_id,
                        service_url=service_url,
                        activity_data=body
                    )
                    logger.debug("💾 ConversationReference armazenado para user=%s", user_id)
            except Exception as storage_err:
                logger.warning("⚠️ Falha ao armazenar ConversationReference: %s", storage_err)

        # 1) Universal Actions (invoke/adaptiveCard/action)
        if msg_type == "invoke" and name in ("adaptiveCard/action", "task/submit"):
            logger.info("🎯 Processando payload 'invoke' de Adaptive Card")
            return _process_card_action(body)

        # 2) Mensagem normal com 'value' (alguns clientes do Teams)
        if msg_type == "message" and ("value" in body or "channelData" in body):
            logger.info("💬 Processando payload 'message' com 'value'")
            return _process_card_action(body)

        # 3) Mensagem de texto simples ou instalação de bot
        if msg_type == "message":
            text = body.get("text", "").strip().lower()
            
            # Comandos básicos do bot
            if text in ["/start", "/help", "ajuda", "help"]:
                response_text = ("👋 Olá! Sou o bot de notificações do G-Click.\n\n"
                               "Recebo notificações automáticas sobre tarefas vencidas e próximas do vencimento.\n"
                               "Digite `/status` para verificar seu status de notificações.")
                
                if bot_sender:
                    try:
                        # Enviar resposta direta
                        bot_sender.send_direct_message(body, response_text)
                        logger.info("✅ Mensagem de ajuda enviada para %s", from_user.get("name"))
                    except Exception as send_err:
                        logger.error("❌ Falha ao enviar mensagem de ajuda: %s", send_err)
                
                return _json({"status": "help_sent", "timestamp": datetime.utcnow().isoformat()})
            
            elif text == "/status":
                # Verificar status das notificações do usuário
                user_teams_id = from_user.get("id")
                status_info = {
                    "user_id": user_teams_id,
                    "conversation_stored": bool(conversation_storage and 
                                              conversation_storage.get_conversation_reference(user_teams_id)),
                    "bot_configured": bool(bot_sender),
                    "timestamp": datetime.utcnow().isoformat()
                }
                
                status_text = (f"📊 Status de Notificações:\n\n"
                             f"• ID do usuário: `{user_teams_id}`\n"
                             f"• Conversa armazenada: {'✅' if status_info['conversation_stored'] else '❌'}\n"
                             f"• Bot configurado: {'✅' if status_info['bot_configured'] else '❌'}\n"
                             f"• Timestamp: {status_info['timestamp']}")
                
                if bot_sender:
                    try:
                        bot_sender.send_direct_message(body, status_text)
                        logger.info("✅ Status enviado para %s", from_user.get("name"))
                    except Exception as send_err:
                        logger.error("❌ Falha ao enviar status: %s", send_err)
                
                return _json(status_info)

        # 4) Demais tipos de mensagem (log e confirmação)
        logger.info("📨 Teams activity recebida: %s de %s (%s)", 
                   msg_type, from_user.get("name"), from_user.get("id"))

        return _json(
            {
                "status": "received",
                "type": msg_type,
                "adapter_status": "configured" if bot_sender else "not_configured",
                "conversation_storage_status": "configured" if conversation_storage else "not_configured",
                "timestamp": datetime.utcnow().isoformat(),
                "note": "Mensagem recebida e processada com sucesso.",
            }
        )
    except Exception:
        logger.exception("Erro no processamento /messages")
        return func.HttpResponse("Erro interno", status_code=500)


def _process_card_action(body: dict) -> func.HttpResponse:
    """
    Processa ações dos botões dos Adaptive Cards.
    
    Args:
        body: Payload do Teams com dados da ação
        
    Returns:
        func.HttpResponse: Resposta da ação processada
    """
    try:
        action_type, task_id = _extract_card_action(body)
        user_info = body.get("from", {}) or {}
        user_id = user_info.get("id")
        user_name = user_info.get("name", "Usuário")

        if not action_type or not task_id:
            logger.warning("Ação inválida: dados incompletos (action/taskId ausentes)")
            return _json({"result": "error", "message": "Dados da ação incompletos"}, status=200)

        logger.info("Ação '%s' para task %s do usuário %s", action_type, task_id, user_name)

        confirmation_text = ""
        result_status = ""

        if action_type == "dispensar":
            try:
                success = _dispensar_tarefa_gclick(task_id)
                if success:
                    confirmation_text = f"✅ Tarefa **{task_id}** dispensada no G-Click com sucesso!"
                    result_status = "dispensada"
                else:
                    confirmation_text = f"⚠️ Não foi possível dispensar a tarefa **{task_id}** no G-Click."
                    result_status = "erro_dispensar"
            except Exception as e:
                logger.error("Erro ao dispensar tarefa %s: %s", task_id, e)
                confirmation_text = f"⚠️ Erro ao conectar com G-Click para dispensar a tarefa **{task_id}**."
                result_status = "erro_conexao"

        elif action_type == "finalizar":
            confirmation_text = (
                f"✅ Tarefa **{task_id}** marcada como **finalizada** no seu chat.\n"
                f"*(Status não alterado no G-Click)*"
            )
            result_status = "finalizada"

        else:
            logger.warning("Ação desconhecida: %s", action_type)
            confirmation_text = f"⚠️ Ação '{action_type}' não reconhecida."
            result_status = "acao_invalida"

        # Enviar confirmação para o usuário (se tivermos referência de conversa)
        if bot_sender and user_id and confirmation_text:
            try:
                import asyncio
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    asyncio.ensure_future(bot_sender.send_message(user_id, confirmation_text))
                else:
                    loop.run_until_complete(bot_sender.send_message(user_id, confirmation_text))
                logger.info("Confirmação enviada para %s (%s)", user_name, user_id)
            except Exception as e:
                logger.error("Falha ao enviar confirmação para %s: %s", user_id, e)

        # Importante: para 'invoke' o Bot Framework espera 200
        return _json(
            {
                "result": result_status,
                "taskId": task_id,
                "action": action_type,
                "timestamp": datetime.utcnow().isoformat(),
            },
            status=200,
        )

    except Exception as e:
        logger.exception("Erro ao processar ação do card: %s", e)
        return _json({"result": "error", "message": "Erro interno ao processar ação"}, status=200)


def _dispensar_tarefa_gclick(task_id: str) -> bool:
    """
    Dispensa uma tarefa no G-Click alterando seu status para 'D' (Dispensado).
    
    Args:
        task_id: ID da tarefa no G-Click
        
    Returns:
        bool: True se dispensada com sucesso, False caso contrário
    """
    try:
        import requests
        import os
        
        # URL base do G-Click
        base_url = os.getenv("GCLICK_BASE_URL", "https://api.gclick.com.br")
        
        # Headers com autenticação (assume que já existe função para isso)
        try:
            # Tentar importar função de autenticação existente
            if SHARED_DIR.exists():
                sys.path.insert(0, str(SHARED_DIR))
            from gclick.auth import get_auth_headers
            headers = get_auth_headers()
        except ImportError:
            # Fallback: construir headers manualmente
            token = os.getenv("GCLICK_TOKEN")
            if not token:
                logger.error("Token G-Click não configurado")
                return False
            headers = {
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json"
            }
        
        # Endpoint para dispensar tarefa (adaptar conforme API real do G-Click)
        # Nota: Este endpoint é uma suposição - deve ser confirmado com a documentação
        endpoint = f"{base_url}/tarefas/{task_id}/status"
        payload = {"status": "D"}  # D = Dispensado
        
        response = requests.put(endpoint, json=payload, headers=headers, timeout=10)
        
        if response.status_code == 200:
            logger.info(f"Tarefa {task_id} dispensada com sucesso no G-Click")
            return True
        else:
            logger.error(f"Falha ao dispensar tarefa {task_id}: HTTP {response.status_code} - {response.text}")
            return False
            
    except Exception as e:
        logger.error(f"Exceção ao dispensar tarefa {task_id}: {e}")
        return False

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
