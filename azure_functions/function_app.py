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

APP_VERSION = "2.2.0"

# Flags de ambiente e configuração dinâmica
DEBUG_MOCK = os.getenv("DEBUG_MOCK", "false").lower() == "true"
# Detecção robusta de ambiente Azure (múltiplas variáveis)
IS_AZURE = bool(
    os.getenv("WEBSITE_INSTANCE_ID") or 
    os.getenv("WEBSITE_SITE_NAME") or 
    os.getenv("FUNCTIONS_WORKER_RUNTIME") and os.getenv("AzureWebJobsStorage", "").startswith("DefaultEndpointsProtocol=https")
)

# (opcional) helper que pode ser útil em logs e ramificações
IS_LOCAL = not IS_AZURE


# Feature flags para habilitar/desabilitar funcionalidades
FEATURES = {
    "webhook_gclick": os.getenv("FEATURE_WEBHOOK_GCLICK", "true").lower() == "true",
    "teams_bot": os.getenv("FEATURE_TEAMS_BOT", "true").lower() == "true",
    "notification_engine": os.getenv("FEATURE_NOTIFICATION_ENGINE", "true").lower() == "true",
    "adaptive_cards": os.getenv("FEATURE_ADAPTIVE_CARDS", "true").lower() == "true",
    "conversation_storage": os.getenv("FEATURE_CONVERSATION_STORAGE", "true").lower() == "true",
    "debug_endpoints": os.getenv("FEATURE_DEBUG_ENDPOINTS", "false").lower() == "true",  # desabilitado por padrão em produção
    "scheduled_notifications": os.getenv("FEATURE_SCHEDULED_NOTIFICATIONS", "true").lower() == "true"
}

# Configurações dinâmicas
CONFIG = {
    "dias_proximos_morning": int(os.getenv("DIAS_PROXIMOS_MORNING", "3")),
    "dias_proximos_afternoon": int(os.getenv("DIAS_PROXIMOS_AFTERNOON", "1")),
    "timezone": os.getenv("TIMEZONE", "America/Sao_Paulo"),
    "locale": os.getenv("LOCALE", "pt-BR"),
    "notification_timeout": int(os.getenv("NOTIFICATION_TIMEOUT", "30")),
    "max_retries": int(os.getenv("MAX_RETRIES", "3"))
}

logger.info("🎛️  Features habilitadas: %s", [k for k, v in FEATURES.items() if v])
logger.info("⚙️  Configurações: timezone=%s, locale=%s", CONFIG["timezone"], CONFIG["locale"])

# Validação de timezone para evitar crash local sem tzdata (Windows/DEV)
try:
    from zoneinfo import ZoneInfo  # Python 3.9+
    _ = ZoneInfo(CONFIG.get("timezone", "UTC"))
except Exception:
    logger.warning(
        "⚠️ Timezone %s indisponível neste host; usando UTC. Instale 'tzdata' no DEV.",
        CONFIG.get("timezone"),
    )
    CONFIG["timezone"] = "UTC"

# ─────────────────────────────────────────────────────────────
# IMPORTS DO PROJETO - SEMPRE VIA shared_code (elimina ambiguidade)
# ─────────────────────────────────────────────────────────────
# Variáveis para armazenar imports e flags de estado
mapear_apelido_para_teams_id = None
BotSender = None
ConversationReferenceStorage = None
run_notification_cycle = None
import_style = "failed"

try:
    # ✅ SEMPRE usar shared_code.* para evitar colisão com pacote 'teams' do PyPI
    from shared_code.teams.user_mapping import mapear_apelido_para_teams_id
    from shared_code.teams.bot_sender import BotSender, ConversationReferenceStorage
    from shared_code.engine.notification_engine import run_notification_cycle
    
    # ✅ VERIFICAÇÃO DE SANIDADE: garantir que é a classe REAL
    if not hasattr(ConversationReferenceStorage, "store_conversation_reference"):
        raise ImportError("ConversationReferenceStorage importada é STUB - método ausente!")
    
    import_style = "shared_code"
    logger.info("✅ Imports shared_code OK - ConversationReferenceStorage REAL carregada")
    
except Exception as imp_err:
    logger.error("❌ Falha nos imports shared_code: %s", imp_err, exc_info=True)
    
    # Tentar fallback para imports diretos (compatibilidade)
    try:
        import sys
        from pathlib import Path
        
        # Adicionar diretório raiz ao path se ainda não estiver
        root_dir = Path(__file__).parent.parent
        if str(root_dir) not in sys.path:
            sys.path.insert(0, str(root_dir))
            
        from teams.user_mapping import mapear_apelido_para_teams_id
        from teams.bot_sender import BotSender, ConversationReferenceStorage
        from engine.notification_engine import run_notification_cycle
        
        import_style = "direct"
        logger.warning("⚠️ Usando imports diretos como fallback")
        
    except Exception as fallback_err:
        logger.error("❌ Fallback imports também falharam: %s", fallback_err, exc_info=True)
        
        # Modo degradado - criar stubs para evitar crash
        logger.warning("⚠️ Executando em modo degradado - funcionalidades limitadas")
        import_style = "degraded"
        
        # Stubs mínimos para evitar NameError
        def mapear_apelido_para_teams_id(apelido):
            logger.warning("Stub: mapear_apelido_para_teams_id chamado com %s", apelido)
            return None
            
        class ConversationReferenceStorage:
            def __init__(self, *args, **kwargs):
                pass
            def store_conversation_reference(self, *args, **kwargs):
                logger.warning("Stub: store_conversation_reference chamado")
                
        class BotSender:
            def __init__(self, *args, **kwargs):
                pass
                
        def run_notification_cycle(*args, **kwargs):
            logger.warning("Stub: run_notification_cycle chamado")
            return {"status": "degraded", "message": "Imports não disponíveis"}

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

# Configurar Bot Framework apenas se feature habilitada e credenciais disponíveis
if FEATURES["teams_bot"] and APP_ID and APP_PASSWORD and import_style != "degraded":
    try:
        from botbuilder.core import BotFrameworkAdapter, BotFrameworkAdapterSettings  # type: ignore

        # Configurar adapter do Bot Framework
        adapter_settings = BotFrameworkAdapterSettings(APP_ID, APP_PASSWORD)
        adapter = BotFrameworkAdapter(adapter_settings)

        # Configuração de storage path persistente baseado no ambiente
        if IS_AZURE:
            # Azure Functions: usar diretório persistente $HOME/data
            # Múltiplas variáveis para garantir compatibilidade
            home_dir = os.getenv("HOME") or os.getenv("USERPROFILE") or "/tmp"
            storage_base = Path(home_dir) / "data" / "gclick_teams"
            logger.info("🔧 Ambiente Azure detectado - usando $HOME/data: %s", storage_base)
        else:
            # Desenvolvimento local: usar diretório do projeto
            storage_base = Path(__file__).parent / "storage"
            logger.info("🔧 Ambiente local detectado - usando storage local: %s", storage_base)
        
        # Criar diretórios necessários com tratamento de erro robusto
        try:
            storage_base.mkdir(parents=True, exist_ok=True)
            logger.info("✅ Diretório de storage criado/verificado: %s", storage_base)
        except Exception as mkdir_err:
            logger.error("💥 Erro ao criar diretório de storage: %s", mkdir_err)
            # Fallback para diretório temporário
            storage_base = Path("/tmp") / "gclick_teams_fallback"
            storage_base.mkdir(parents=True, exist_ok=True)
            logger.warning("⚠️ Usando fallback storage: %s", storage_base)
            
        storage_path = storage_base / "conversation_references.json"

        # Inicializar armazenamento robusto apenas se feature habilitada
        conversation_storage = None
        if FEATURES["conversation_storage"]:
            try:
                conversation_storage = ConversationReferenceStorage(str(storage_path))
                # Verificar se a classe real foi importada
                if hasattr(conversation_storage, 'store_conversation_reference'):
                    logger.info("✅ ConversationReferenceStorage REAL inicializada em: %s", storage_path)
                else:
                    logger.error("❌ ConversationReferenceStorage STUB sendo usada!")
            except Exception as storage_init_err:
                logger.error("💥 Erro ao inicializar ConversationReferenceStorage: %s", storage_init_err)
                conversation_storage = None
        
        # Inicializar BotSender com configuração completa
        bot_sender = BotSender(adapter, APP_ID, conversation_storage)

        logger.info("🤖  Bot Framework configurado com sucesso")
        logger.info("📁  Storage path: %s", storage_path if FEATURES["conversation_storage"] else "desabilitado")
        logger.info("🆔  App ID: %s...", APP_ID[:8] if APP_ID else "N/A")

        # Integrar storage na engine de notificação (se ambas features habilitadas)
        if FEATURES["notification_engine"]:
            try:
                # Tentar importação robusto baseado no style detectado
                if import_style == "shared_code":
                    import shared_code.engine.notification_engine as ne  # type: ignore
                else:
                    import engine.notification_engine as ne  # type: ignore
                
                ne.bot_sender = bot_sender
                logger.info("🔗  BotSender integrado à NotificationEngine (com ConversationStorage)")
            except Exception as integration_err:
                logger.warning("⚠️  Falha na integração com NotificationEngine: %s", integration_err)

        logger.info("🤖  BotSender configurado – storage em %s", storage_path if FEATURES["conversation_storage"] else "desabilitado")
    except Exception as bot_err:
        logger.warning("⚠️  Bot Framework não configurado: %s", bot_err, exc_info=True)
elif import_style == "degraded":
    logger.warning("🤖  Bot Teams não configurado - modo degradado (imports falharam)")
elif not FEATURES["teams_bot"]:
    logger.info("🤖  Bot Teams desabilitado via feature flag")
elif not (APP_ID and APP_PASSWORD):
    logger.warning("⚠️  Credenciais do Bot Framework não configuradas (APP_ID/APP_PASSWORD)")

# ─────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────
def _json(payload: dict, status: int = 200) -> func.HttpResponse:
    return func.HttpResponse(
        json.dumps(payload, ensure_ascii=False),
        status_code=status,
        headers={"Content-Type": "application/json"},
    )

def run_async(coro):
    """
    Executa uma coroutine de forma segura em qualquer thread do Azure Functions.
    - Se houver event loop rodando nesta thread: agenda a tarefa e retorna True.
    - Se não houver: cria um loop, executa a coroutine e retorna o resultado.
    """
    import asyncio
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    if loop.is_running():
        asyncio.create_task(coro)
        return True
    else:
        return loop.run_until_complete(coro)

def _run_cycle(period: str, dias_proximos: int, full_scan: bool):
    """
    Função central que executa um ciclo de notificações com retentativas.
    
    Args:
        period: Identificador do ciclo ("morning", "afternoon", "manual")
        dias_proximos: Quantos dias à frente verificar
        full_scan: Se True, verifica todas as tarefas. Se False, apenas próximas do vencimento.
        
    Returns:
        dict: Resultado da execução com status e detalhes
    """
    if not FEATURES["notification_engine"]:
        logger.info("⏭️  Notification engine desabilitado via feature flag")
        return {"status": "disabled", "period": period}

    max_attempts = CONFIG["max_retries"]
    timeout = CONFIG["notification_timeout"]  

    try:    
        # Lazy import para evitar deadlock de imports circulares
        from shared_code.engine.notification_engine import run_notification_cycle
        
        # Modo produção por padrão - apenas dry_run se explicitamente configurado
        exec_mode = "dry_run" if os.getenv("SIMULACAO", "false").lower() == "true" else "live"
        logger.info("⏳  run_notification_cycle(%s) → modo=%s, dias=%s, timezone=%s", 
                   period, exec_mode, dias_proximos, CONFIG["timezone"])

        # Loop de retentativas com backoff exponencial
        import time
        result = None
        last_error = None
        
        for attempt in range(max_attempts):
            try:
                result = run_notification_cycle(
                    dias_proximos=dias_proximos,
                    execution_mode=exec_mode,
                    run_reason=f"scheduled_{period}",
                    usar_full_scan=full_scan,
                    apenas_status_abertos=True,
                    timeout=timeout
                )
                logger.info("✅  Ciclo %s concluído → %s", period, result)
                return result
                
            except Exception as e:
                last_error = e
                if attempt < max_attempts - 1:  # não esperar na última tentativa
                    delay = min(2 ** attempt, 60)  # backoff exponencial, max 60s
                    logger.warning("⚠️  Tentativa %d falhou, aguardando %ds: %s", 
                                 attempt + 1, delay, e)
                    time.sleep(delay)
                else:
                    logger.error("❌  Todas as %d tentativas falharam", max_attempts)
                    break
                    
        # Se chegou aqui, todas as tentativas falharam
        return {
            "status": "error",
            "period": period,
            "error": str(last_error),
            "attempts": max_attempts
        }
                
    except ImportError as import_err:
        logger.error("❌ Import run_notification_cycle falhou: %s", import_err)
        return {
            "status": "import_failed",
            "period": period,
            "error": str(import_err)
        }

# ─────────────────────────────────────────────────────────────
# HTTP — Webhook G‑Click
# ─────────────────────────────────────────────────────────────
@app.function_name(name="GClickWebhook")
@app.route(route="gclick", methods=["POST"], auth_level=func.AuthLevel.ANONYMOUS)
def gclick_webhook(req: func.HttpRequest) -> func.HttpResponse:
    if not FEATURES["webhook_gclick"]:
        return func.HttpResponse("Webhook G-Click desabilitado", status_code=503)
        
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
        tarefas = payload.get("tarefas", [])
        
        logger.info("📋 Webhook recebido: evento=%s, %d responsáveis, %d tarefas", 
                   evento, len(responsaveis), len(tarefas))

        enviados, falhou = 0, 0
        mensagens_enviadas = []
        
        for resp in responsaveis:
            apelido = (resp.get("apelido") or "").strip()
            if not apelido:
                continue
                
            try:
                teams_id = mapear_apelido_para_teams_id(apelido)
                if not teams_id:
                    falhou += 1
                    logger.warning("⚠️ Mapeamento não encontrado: %s", apelido)
                    continue
                
                # Envio real de notificação se bot configurado
                if bot_sender and FEATURES["teams_bot"]:
                    try:
                        # Construir mensagem personalizada
                        if tarefas:
                            # Notificação com tarefas específicas
                            tarefa_lista = []
                            for t in tarefas[:5]:  # Limitar a 5 tarefas
                                task_id = t.get("id", "N/A")
                                titulo = t.get("titulo", t.get("assunto", "Sem título"))
                                vencimento = t.get("dataVencimento", "")
                                tarefa_lista.append(f"• **{titulo}** (ID: {task_id}) - Vence: {vencimento}")
                            
                            if len(tarefas) > 5:
                                tarefa_lista.append(f"• ... e mais {len(tarefas) - 5} tarefa(s)")
                            
                            # Corrigir f-string com backslash - separar a operação
                            tarefas_formatadas = '\n'.join(tarefa_lista)
                            mensagem = (f"🔔 **{evento}**\n\n"
                                      f"📋 **Tarefas para sua atenção:**\n"
                                      f"{tarefas_formatadas}\n\n"
                                      f"👤 **Responsável:** {apelido}\n"
                                      f"🕐 **Timestamp:** {datetime.utcnow().strftime('%d/%m/%Y %H:%M')}")
                        else:
                            # Notificação genérica
                            mensagem = (f"🔔 **{evento}**\n\n"
                                      f"📝 Você tem notificações pendentes no G-Click.\n\n"
                                      f"👤 **Responsável:** {apelido}\n"
                                      f"🕐 **Timestamp:** {datetime.utcnow().strftime('%d/%m/%Y %H:%M')}")
                        
                        # Enviar mensagem usando bot_sender de forma segura em qualquer thread
                        sent_success = run_async(bot_sender.send_message(teams_id, mensagem))
                        
                        if sent_success:
                            enviados += 1
                            mensagens_enviadas.append({
                                "apelido": apelido,
                                "teams_id": teams_id,
                                "status": "enviado"
                            })
                            logger.info("✅ Notificação enviada para %s (%s)", apelido, teams_id)
                        else:
                            falhou += 1
                            logger.error("❌ Falha no envio para %s (%s)", apelido, teams_id)
                            
                    except Exception as send_err:
                        falhou += 1
                        logger.error("❌ Erro ao enviar via bot para %s: %s", apelido, send_err)
                else:
                    # Fallback: marcar como enviado mas sem envio real
                    enviados += 1
                    mensagens_enviadas.append({
                        "apelido": apelido,
                        "teams_id": teams_id,
                        "status": "mock" if not bot_sender else "bot_desabilitado"
                    })
                    logger.info("📤 Notificação mockada para %s (bot não configurado)", apelido)
                    
            except Exception as map_err:
                falhou += 1
                logger.error("❌ Erro no processamento %s: %s", apelido, map_err)

        # Resposta detalhada
        resultado = {
            "evento": evento,
            "total_responsaveis": len(responsaveis),
            "total_tarefas": len(tarefas),
            "notificacoes_enviadas": enviados,
            "notificacoes_falharam": falhou,
            "timestamp": datetime.utcnow().isoformat(),
            "bot_configurado": bool(bot_sender),
            "features": {
                "webhook_gclick": FEATURES["webhook_gclick"],
                "teams_bot": FEATURES["teams_bot"]
            },
            "detalhes_envio": mensagens_enviadas
        }
        
        logger.info("📊 Webhook processado: %d enviados, %d falharam", enviados, falhou)
        return _json(resultado)
    except Exception:
        logger.exception("Erro no webhook")
        return func.HttpResponse("Erro interno", status_code=500)

# ─────────────────────────────────────────────────────────────
# TIMERS - Executam em UTC por padrão
# Para horário de São Paulo, configure no Function App:
# Linux: WEBSITE_TIME_ZONE=America/Sao_Paulo  
# Windows: WEBSITE_TIME_ZONE=E. South America Standard Time
# ─────────────────────────────────────────────────────────────
@app.function_name(name="MorningNotifications")
@app.schedule(schedule="0 0 11 * * 1-5", arg_name="timer", run_on_startup=False, use_monitor=True)
def morning_notifications(timer: func.TimerRequest) -> None:
    """
    Timer matutino: 11:00 (UTC) ou 08:00 (BRT) se timezone configurado.
    Executa scan completo para detectar tarefas vencidas e próximas do vencimento.
    """
    if not FEATURES["scheduled_notifications"]:
        logger.info("⏭️  Notificações agendadas desabilitadas via feature flag")
        return
        
    try:
        _run_cycle("morning", CONFIG["dias_proximos_morning"], full_scan=True)
    except Exception:
        logger.exception("Erro no ciclo matutino")

@app.function_name(name="AfternoonNotifications")
@app.schedule(schedule="0 30 20 * * 1-5", arg_name="timer", run_on_startup=False, use_monitor=True)
def afternoon_notifications(timer: func.TimerRequest) -> None:
    """
    Timer vespertino: 20:30 (UTC) ou 17:30 (BRT) se timezone configurado.
    Executa scan rápido para tarefas com vencimento próximo apenas.
    """
    if not FEATURES["scheduled_notifications"]:
        logger.info("⏭️  Notificações agendadas desabilitadas via feature flag")
        return
        
    try:
        _run_cycle("afternoon", CONFIG["dias_proximos_afternoon"], full_scan=False)
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
    if not FEATURES["teams_bot"]:
        return func.HttpResponse("Bot Teams desabilitado", status_code=503)
        
    try:
        body = req.get_json()
        msg_type = body.get("type")
        name = body.get("name")
        from_user = body.get("from", {})
        conversation = body.get("conversation", {})
        recipient = body.get("recipient", {})  # dados do bot (id/nome)
        
        logger.info("📱 Teams activity: type=%s, name=%s, user=%s", 
                   msg_type, name, from_user.get("name"))

        # Armazenar/atualizar ConversationReference se disponível e feature habilitada
        stored = False  # NOVO: flag para rastrear se foi armazenado
        if FEATURES["conversation_storage"] and conversation_storage:
            try:
                # Extrair informações necessárias para ConversationReference
                user_id = from_user.get("id")
                user_name = from_user.get("name", "")
                conversation_id = conversation.get("id")
                service_url = body.get("serviceUrl", "")
                channel_id = body.get("channelId", "msteams")
                
                # 🔍 LOG DETALHADO para debug da captura de Teams ID
                logger.info("🔍 DETALHES DA CAPTURA - user_id: %s, user_name: %s, conversation_id: %s, service_url: %s", 
                           user_id, user_name, conversation_id, service_url)
                
                if user_id and conversation_id:
                    # Caminho normal: payload real vindo do Teams
                    conversation_data = {
                        "user": {
                            "id": user_id,
                            "name": user_name,
                            "aad_object_id": from_user.get("aadObjectId"),
                            "role": from_user.get("role", "user")
                        },
                        "bot": {
                            "id": recipient.get("id"),
                            "name": recipient.get("name"),
                        },
                        "conversation": {
                            "id": conversation_id,
                            "name": conversation.get("name"),
                            "conversation_type": conversation.get("conversationType", "personal"),
                            "tenant_id": conversation.get("tenantId")
                        },
                        "channel_id": channel_id,
                        "service_url": service_url,
                        "locale": body.get("locale", CONFIG["locale"]),
                        "timezone": body.get("timezone", CONFIG["timezone"]),
                        "last_activity": {
                            "type": body.get("type"),
                            "timestamp": datetime.utcnow().isoformat(),
                            "id": body.get("id")
                        }
                    }
                    
                    # Armazenar usando nova API robusta
                    # ✅ VERIFICAÇÃO DEFENSIVA antes de chamar
                    store_method = getattr(conversation_storage, "store_conversation_reference", None)
                    if callable(store_method):
                        store_method(user_id=user_id, conversation_data=conversation_data)
                        stored = True
                        logger.info("✅ ConversationReference armazenada para %s (%s)", user_name, user_id)
                    else:
                        logger.error("❌ conversation_storage é STUB - método store_conversation_reference ausente!")
                        logger.error("❌ Tipo: %s, Métodos: %s", type(conversation_storage), dir(conversation_storage))
                    
                # Fallback DEV: sem conversation.id, mas com from.id (não funciona para envio real)
                elif user_id and not IS_AZURE:
                    logger.warning("⚠️  MODO DEV: conversation_id ausente, usando fallback dev-conversation")
                    conversation_data = {
                        "user": {
                            "id": user_id,
                            "name": user_name,
                            "aad_object_id": from_user.get("aadObjectId"),
                            "role": from_user.get("role", "user")
                        },
                        "bot": {
                            "id": recipient.get("id"),
                            "name": recipient.get("name"),
                        },
                        "conversation": {
                            "id": f"dev-{user_id}",
                            "name": "DEV Conversation",
                            "conversation_type": "personal",
                            "tenant_id": "dev-tenant"
                        },
                        "channel_id": channel_id,
                        "service_url": service_url or "https://smba.trafficmanager.net/amer/",
                        "locale": body.get("locale", CONFIG["locale"]),
                        "timezone": body.get("timezone", CONFIG["timezone"]),
                        "last_activity": {
                            "type": body.get("type"),
                            "timestamp": datetime.utcnow().isoformat(),
                            "id": body.get("id")
                        }
                    }
                    
                    # ✅ VERIFICAÇÃO DEFENSIVA antes de chamar (modo DEV)
                    store_method = getattr(conversation_storage, "store_conversation_reference", None)
                    if callable(store_method):
                        store_method(user_id=user_id, conversation_data=conversation_data)
                        stored = True
                        logger.info("✅ ConversationReference DEV armazenada para %s (%s)", user_name, user_id)
                    else:
                        logger.error("❌ conversation_storage é STUB no modo DEV!")
                else:
                    logger.warning("❌ CAPTURA FALHOU: user_id=%s, conversation_id=%s, IS_AZURE=%s", 
                                   user_id, conversation_id, IS_AZURE)
                    
            except Exception as storage_err:
                logger.error("💥 ERRO ao armazenar ConversationReference: %s", storage_err, exc_info=True)
        else:
            logger.info("ℹ️  ConversationStorage desabilitado ou indisponível")

        # 📊 LOG FINAL do resultado da captura
        if stored:
            logger.info("✅ Teams ID capturado com sucesso!")
        else:
            logger.warning("⚠️  Teams ID NÃO foi capturado nesta mensagem")

        # 1) Universal Actions (invoke/adaptiveCard/action)
        if msg_type == "invoke" and name in ("adaptiveCard/action", "task/submit"):
            logger.info("🎯 Processando payload 'invoke' de Adaptive Card")
            return _process_card_action(body)

        # 2) Mensagem normal com 'value' apenas se for realmente um card action
        if msg_type == "message" and "value" in body:
            # Verificar se realmente é um card action antes de processar
            value_data = body.get("value", {})
            if isinstance(value_data, dict) and ("action" in value_data or "taskId" in value_data):
                logger.info("💬 Processando payload 'message' com card action")
                return _process_card_action(body)
            else:
                logger.debug("💬 Mensagem com 'value' mas não é card action, tratando como mensagem normal")

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
                "status": "reference_stored" if stored else "received",
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

        if action_type == "finalizar":
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
                run_async(bot_sender.send_message(user_id, confirmation_text))
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
    # A funcionalidade de 'dispensar' foi removida por não existir API pública
    logger.warning("Funcionalidade 'dispensar' desabilitada - chamada ignorada para task_id=%s", task_id)
    return False

# ─────────────────────────────────────────────────────────────
# HTTP — Configuração dinâmica
# ─────────────────────────────────────────────────────────────
@app.function_name(name="ConfigManager")
@app.route(route="config", methods=["GET", "POST"], auth_level=func.AuthLevel.ANONYMOUS)
def config_manager(req: func.HttpRequest) -> func.HttpResponse:
    """
    Endpoint para visualizar e ajustar configurações em tempo real.
    GET: visualiza configurações atuais
    POST: atualiza configurações (env vars temporárias)
    """
    if not FEATURES["debug_endpoints"]:
        return func.HttpResponse("Debug endpoints desabilitados", status_code=503)
    
    try:
        if req.method == "GET":
            # Mostrar configurações atuais
            if FEATURES["notification_engine"]:
                try:
                    # Tentar importação robusto baseado no style detectado
                    if import_style == "shared_code":
                        import shared_code.engine.notification_engine as ne  # type: ignore
                    else:
                        import engine.notification_engine as ne  # type: ignore
                    
                    current_config = ne.load_notifications_config()
                except Exception as e:
                    current_config = {"error": f"Falha ao carregar configurações: {e}"}
            else:
                current_config = {"status": "notification_engine_disabled"}
            
            response_data = {
                "config_atual": current_config,
                "features": FEATURES,
                "config_sistema": CONFIG,
                "env_vars_relevantes": {
                    "DIAS_PROXIMOS": os.getenv("DIAS_PROXIMOS"),
                    "DIAS_PROXIMOS_MORNING": os.getenv("DIAS_PROXIMOS_MORNING"),
                    "DIAS_PROXIMOS_AFTERNOON": os.getenv("DIAS_PROXIMOS_AFTERNOON"),
                    "SIMULACAO": os.getenv("SIMULACAO"),
                    "TIMEZONE": os.getenv("TIMEZONE"),
                },
                "timestamp": datetime.utcnow().isoformat()
            }
            
            return _json(response_data)
            
        elif req.method == "POST":
            # Atualizar configurações temporariamente
            try:
                updates = req.get_json()
            except ValueError:
                return func.HttpResponse("JSON inválido", status_code=400)
            
            if not updates:
                return func.HttpResponse("Payload vazio", status_code=400)
            
            updated_vars = {}
            valid_env_vars = [
                "DIAS_PROXIMOS", "DIAS_PROXIMOS_MORNING", "DIAS_PROXIMOS_AFTERNOON",
                "SIMULACAO", "TIMEZONE", "PAGE_SIZE", "MAX_RESPONSAVEIS_LOOKUP"
            ]
            
            for key, value in updates.items():
                if key in valid_env_vars:
                    # Atualizar environment variable temporariamente 
                    # (só dura enquanto a function estiver ativa)
                    os.environ[key] = str(value)
                    updated_vars[key] = value
                    logger.info("🔧 Configuração temporária atualizada: %s = %s", key, value)
                else:
                    logger.warning("⚠️ Configuração ignorada (não permitida): %s", key)
            
            return _json({
                "status": "updated",
                "updated_vars": updated_vars,
                "note": "Mudanças são temporárias e serão perdidas no restart da function",
                "timestamp": datetime.utcnow().isoformat()
            })
    
    except Exception:
        logger.exception("Erro em /config")
        return func.HttpResponse("Erro interno", status_code=500)

# ─────────────────────────────────────────────────────────────
# HTTP — Status detalhado das features e configurações
# ─────────────────────────────────────────────────────────────
@app.function_name(name="HealthStatus")
@app.route(route="healthz", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def health_status(req: func.HttpRequest) -> func.HttpResponse:
    """
    Endpoint de saúde que exibe status das features e configurações.
    """
    try:
        health_data = {
            "status": "healthy",
            "timestamp": datetime.utcnow().isoformat(),
            "version": APP_VERSION,
            "environment": {
                "is_azure": IS_AZURE,
                "debug_mock": DEBUG_MOCK
            },
            "features": FEATURES,
            "config": {
                k: v for k, v in CONFIG.items() 
                if k not in ["password", "secret", "token"]  # Não expor secrets
            },
            "bot_framework": {
                "configured": bool(bot_sender),
                "app_id_present": bool(APP_ID),
                "password_present": bool(APP_PASSWORD),
                "conversation_storage": bool(conversation_storage)
            },
            "import_style": import_style if 'import_style' in globals() else "unknown"
        }
        
        return _json(health_data)
    except Exception:
        logger.exception("Erro em /health")
        return func.HttpResponse("Erro interno", status_code=500)

@app.function_name(name="ResilienceMetrics")
@app.route(route="metrics/resilience", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def resilience_metrics(req: func.HttpRequest) -> func.HttpResponse:
    """
    Endpoint que expõe métricas de resilience (rate limiting, circuit breaker, cache).
    """
    try:
        # Tentar importar o sistema de resilience
        try:
            try:
                from shared_code.engine.resilience import resilience_manager
            except ImportError:
                from engine.resilience import resilience_manager
            
            resilience_stats = resilience_manager.get_stats()
            
            # Estatísticas do cache (com import seguro do ne)
            cache_stats = {}
            try:
                # Tentar determinar qual pacote usar
                try:
                    import shared_code.engine.notification_engine as ne  # type: ignore
                except Exception:
                    import engine.notification_engine as ne  # type: ignore
                    
                if hasattr(ne, 'notification_cache') and ne.notification_cache:
                    cache_stats = ne.notification_cache.get_stats()
            except Exception as cache_err:
                logger.debug("Cache stats não disponível: %s", cache_err)
            
            metrics_data = {
                "timestamp": datetime.utcnow().isoformat(),
                "version": APP_VERSION,
                "resilience": resilience_stats,
                "cache": cache_stats,
                "status": "active" if resilience_stats else "unavailable"
            }
            
        except ImportError as e:
            metrics_data = {
                "timestamp": datetime.utcnow().isoformat(),
                "version": APP_VERSION,
                "status": "unavailable",
                "error": f"Sistema de resilience não disponível: {e}",
                "resilience": {},
                "cache": {}
            }
        
        return _json(metrics_data)
    except Exception:
        logger.exception("Erro em /metrics/resilience")
        return func.HttpResponse("Erro interno", status_code=500)

@app.function_name(name="ListUsers")
@app.route(route="debug/users", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def list_users(req: func.HttpRequest) -> func.HttpResponse:
    if not FEATURES["debug_endpoints"]:
        return func.HttpResponse("Debug endpoints desabilitados", status_code=503)
        
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
# HTTP — Capturar Teams ID do usuário
# ─────────────────────────────────────────────────────────────
@app.function_name(name="CaptureTeamsId")
@app.route(route="debug/capture-teams-id", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def capture_teams_id(req: func.HttpRequest) -> func.HttpResponse:
    """
    Endpoint para capturar e listar todos os Teams IDs que interagiram com o bot.
    Use este endpoint para descobrir seu Teams ID após enviar mensagens ao bot.
    """
    if not FEATURES["debug_endpoints"]:
        return func.HttpResponse("Debug endpoints desabilitados", status_code=503)
        
    try:
        conversation_list = []
        
        logger.info("🔍 /debug/capture-teams-id acessado - bot_sender=%s, conversation_storage=%s", 
                   bool(bot_sender), bool(conversation_storage))
        
        if bot_sender and conversation_storage:
            try:
                logger.info("🔍 Tentando listar conversas armazenadas...")
                # Tentar método principal
                if hasattr(conversation_storage, 'list_all_references'):
                    all_refs = conversation_storage.list_all_references()
                    logger.info("🔍 Encontradas %d referências", len(all_refs))
                    for user_id, ref_data in all_refs.items():
                        user_name = "N/A"
                        last_activity = "N/A"

                        if isinstance(ref_data, dict):
                            # v2 (novo): ref_data -> { user_id, conversation_data, stored_at, version }
                            if ref_data.get("version") == "2.0":
                                cdata = ref_data.get("conversation_data", {})
                                user_name = (cdata.get("user") or {}).get("name", "N/A")
                                last_activity = (cdata.get("last_activity") or {}).get("timestamp", "N/A")
                            else:
                                # legado: talvez já seja um dict no formato ConversationReference
                                user_name = (ref_data.get("user") or {}).get("name", "N/A")
                                last_activity = ref_data.get("stored_at", "N/A")

                        conversation_list.append({
                            "teams_id": user_id,
                            "user_name": user_name,
                            "last_activity": last_activity
                        })
                else:
                    # Fallback para estruturas internas
                    logger.info("🔍 Usando fallback para estruturas internas...")
                    for attr in ("_conversations", "references", "_data"):
                        if hasattr(conversation_storage, attr):
                            raw_data = getattr(conversation_storage, attr)
                            logger.info("🔍 Atributo %s encontrado com %d items", attr, len(raw_data) if isinstance(raw_data, dict) else 0)
                            if isinstance(raw_data, dict):
                                for user_id, data in raw_data.items():
                                    conversation_list.append({
                                        "teams_id": user_id,
                                        "user_name": "Dados internos",
                                        "last_activity": "N/A"
                                    })
                                break
            except Exception as e:
                logger.error("💥 Erro ao listar conversas: %s", e, exc_info=True)
        else:
            logger.warning("⚠️  bot_sender=%s, conversation_storage=%s - pelo menos um está indisponível", 
                          bool(bot_sender), bool(conversation_storage))
        
        return _json({
            "conversations_found": len(conversation_list),
            "conversations": conversation_list,
            "instructions": {
                "step_1": "Envie uma mensagem qualquer ao bot no Teams",
                "step_2": "Acesse este endpoint novamente para ver seu Teams ID",
                "step_3": "Use o Teams ID na configuração TEST_USER_TEAMS_ID",
                "note": "⚠️  Localmente, Teams ID nunca será capturado. Deploy no Azure é necessário!"
            },
            "storage_configured": bool(conversation_storage),
            "is_azure": IS_AZURE,
            "features_enabled": {
                "conversation_storage": FEATURES["conversation_storage"],
                "teams_bot": FEATURES["teams_bot"]
            },
            "timestamp": datetime.utcnow().isoformat()
        })
        
    except Exception:
        logger.exception("Erro em /debug/capture-teams-id")
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
                "total": 13,
                "http_endpoints": 11,
                "timer_triggers": 2,
            },
        }
    )

# ─────────────────────────────────────────────────────────────
# HTTP — Executar ciclo manualmente para testes
# ─────────────────────────────────────────────────────────────
@app.function_name(name="RunCycleNow")
@app.route(route="run-cycle", methods=["POST", "GET"], auth_level=func.AuthLevel.ANONYMOUS)
def run_cycle_now(req: func.HttpRequest) -> func.HttpResponse:
    """Executar ciclo de notificações manualmente para testes"""
    
    # ✅ Segurança básica
    secret = os.getenv("RUN_CYCLE_SECRET", "test123")
    provided_secret = req.headers.get("X-Run-Secret") or req.params.get("secret")
    
    if provided_secret != secret:
        return func.HttpResponse("❌ Forbidden - X-Run-Secret inválido", status_code=403)
    
    try:
        dias = int(req.params.get("dias", CONFIG.get("dias_proximos_morning", 3)))
        full = req.params.get("full", "true").lower() == "true"
        # Novo: se fornecido, força envio de mensagem de teste via bot
        force_test = req.params.get("force_test", "false").lower() in ("1", "true", "yes")
        
        logger.info("🚀 Executando ciclo manual: dias=%d, full_scan=%s, force_test=%s", dias, full, force_test)
        # Se solicitarem force_test e o bot estiver configurado, enviar mensagem de teste imediata
        if force_test and bot_sender:
            try:
                test_target = os.getenv("TEST_USER_TEAMS_ID") or os.getenv("TEAMS_USER_MAP_JSON")
                test_msg = os.getenv("TEST_MESSAGE_TEXT", "Mensagem de teste via Bot - por favor ignore")
                logger.info("🧪 Force test: enviando mensagem de teste para %s", test_target)
                sent = run_async(bot_sender.send_message(test_target, test_msg))
                return _json({"status": "force_test_sent", "target": test_target, "sent": bool(sent)})
            except Exception as e:
                logger.exception("💥 Falha ao enviar mensagem de teste via bot: %s", e)
                return _json({"status": "force_test_failed", "error": str(e)}, status=500)

        result = _run_cycle("manual", dias_proximos=dias, full_scan=full)
        
        return _json({
            "status": "success", 
            "message": "Ciclo executado com sucesso",
            "result": result,
            "timestamp": datetime.utcnow().isoformat()
        })
        
    except Exception as e:
        logger.error("💥 Erro no ciclo manual: %s", e, exc_info=True)
        return _json({"status": "error", "message": str(e)}, status=500)

# ─────────────────────────────────────────────────────────────
# HTTP — Debug ConversationReference Storage
# ─────────────────────────────────────────────────────────────
@app.function_name(name="DebugConversationStorage")
@app.route(route="debug/conversation-storage", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def debug_conversation_storage(req: func.HttpRequest) -> func.HttpResponse:
    """Debug endpoint para verificar estado do ConversationReference storage"""
    if not FEATURES["debug_endpoints"]:
        return _json({"error": "Debug endpoints desabilitados"}, status=403)
    
    try:
        debug_info = {
            "storage_configured": conversation_storage is not None,
            "storage_type": str(type(conversation_storage)) if conversation_storage else None,
            "storage_path": str(conversation_storage.file_path) if conversation_storage else None,
            "methods_available": {},
            "references_count": 0,
            "references_sample": {},
            "file_exists": False,
            "file_size": 0,
            "last_modified": None,
            "timestamp": datetime.utcnow().isoformat()
        }
        
        if conversation_storage:
            # Verificar métodos disponíveis
            methods_to_check = ['store_conversation_reference', 'get_conversation_reference', 'save', 'add', 'get', 'list_users']
            for method in methods_to_check:
                debug_info["methods_available"][method] = {
                    "exists": hasattr(conversation_storage, method),
                    "callable": callable(getattr(conversation_storage, method, None))
                }
            
            # Informações sobre as referências armazenadas
            debug_info["references_count"] = len(conversation_storage.references)
            
            # Sample de dados (primeiros 3 user_ids)
            sample_users = list(conversation_storage.references.keys())[:3]
            for user_id in sample_users:
                ref_data = conversation_storage.references.get(user_id)
                if isinstance(ref_data, dict) and ref_data.get("version") == "2.0":
                    cdata = ref_data.get("conversation_data", {})
                    debug_info["references_sample"][user_id] = {
                        "has_version": "2.0",
                        "user_name": (cdata.get("user") or {}).get("name"),
                        "bot_id": (cdata.get("bot") or {}).get("id"),
                        "conversation_id": (cdata.get("conversation") or {}).get("id"),
                        "service_url": cdata.get("service_url"),
                        "stored_at": ref_data.get("stored_at"),
                    }
                else:
                    debug_info["references_sample"][user_id] = {
                        "type": str(type(ref_data)),
                        "stored_at": (ref_data or {}).get("stored_at") if isinstance(ref_data, dict) else None
                    }
            
            # Informações sobre o arquivo
            if conversation_storage.file_path:
                file_path = Path(conversation_storage.file_path)
                debug_info["file_exists"] = file_path.exists()
                if file_path.exists():
                    stat = file_path.stat()
                    debug_info["file_size"] = stat.st_size
                    debug_info["last_modified"] = datetime.fromtimestamp(stat.st_mtime).isoformat()
        
        return _json(debug_info)
        
    except Exception as e:
        logger.error("💥 Erro no debug do conversation storage: %s", e, exc_info=True)
        return _json({"error": str(e), "timestamp": datetime.utcnow().isoformat()}, status=500)
