# IMPORTANTE: import azure.functions DEVE vir PRIMEIRO
import azure.functions as func
import logging
import os
import json
from datetime import datetime
import asyncio
from urllib.parse import urlparse

# Bot Framework (SDK Python)
from botbuilder.core import (
    BotFrameworkAdapterSettings,
    BotFrameworkAdapter,
    TurnContext,
    ActivityHandler,
)
from botbuilder.schema import Activity, ConversationReference, ChannelAccount
from botframework.connector.auth import MicrosoftAppCredentials

# Imports do projeto G-Click
try:
    from engine.notification_engine import run_cycle
    from teams.bot_sender import BotSender, ConversationReferenceStorage
except ImportError as e:
    logging.warning(f"Erro ao importar módulos do G-Click: {e}")
    # Definir fallback functions se imports falharem
    def run_cycle(simulacao=False):
        logging.warning("run_cycle não disponível - fallback")
        return {"status": "fallback", "simulacao": simulacao}
    
    class BotSender:
        def __init__(self, *args, **kwargs):
            pass
        async def send_message(self, user_id, message):
            logging.warning(f"BotSender fallback - não enviando para {user_id}")
            return False
    
    class ConversationReferenceStorage:
        def __init__(self, *args, **kwargs):
            self.references = {}
        def add(self, *args, **kwargs):
            pass

# Configuração do Bot
APP_ID = os.environ.get("MicrosoftAppId", "")
APP_PASSWORD = os.environ.get("MicrosoftAppPassword", "")

# Inicialização do adapter
adapter_settings = BotFrameworkAdapterSettings(APP_ID, APP_PASSWORD)
adapter = BotFrameworkAdapter(adapter_settings)

# Storage persistente para conversation references
conversation_storage = ConversationReferenceStorage("storage/conversation_references.json")

# Inicialização do bot_sender global com storage persistente
bot_sender = BotSender(adapter, APP_ID, conversation_storage)

# ============================================================
#  Configuração do Function App
# ============================================================
app = func.FunctionApp(http_auth_level=func.AuthLevel.ANONYMOUS)

# ============================================================
#  Configuração adicional do bot
# ============================================================
APP_TYPE = os.environ.get("MicrosoftAppType", "MultiTenant").strip()

# Não use MicrosoftAppTenantId quando MultiTenant.
# Se existir no portal, remova-o para evitar confusão.
if APP_TYPE.lower() == "multitenant" and os.environ.get("MicrosoftAppTenantId"):
    logging.warning("MicrosoftAppTenantId está definido, mas o bot está como MultiTenant.")

# ============================================================
#  Tratamento de erro global para o adapter
# ============================================================
async def on_error_handler(context: TurnContext, error: Exception):
    # Loga o stack trace
    logging.error("on_turn_error: %s", error, exc_info=True)

    # Tenta avisar o usuário do erro (pode falhar se o 401 vier nesse momento também)
    try:
        await context.send_activity("Ops! Ocorreu um erro interno.")
    except Exception as send_ex:
        logging.error("Falha ao enviar mensagem de erro ao usuário: %s", send_ex, exc_info=True)

# Registra error handler
adapter.on_turn_error = on_error_handler

# ============================================================
#  Utilitário: confiar no serviceUrl do Teams
# ============================================================
def trust_service_url_base(service_url: str):
    """Confia na URL base e na URL completa do serviço do Teams.
       Não usar expiration_time aqui (não existe no SDK)."""
    if not service_url:
        return
    parsed = urlparse(service_url)
    # Ex: https://smba.trafficmanager.net/amer/tenantid/...
    parts = parsed.path.strip("/").split("/")
    base_path = "/" + parts[0] if parts and parts[0] else ""
    base_url = f"{parsed.scheme}://{parsed.netloc}{base_path}"

    # Confia na base (ex: https://smba.trafficmanager.net/amer)
    MicrosoftAppCredentials.trust_service_url(base_url)
    # Confia na URL completa também
    MicrosoftAppCredentials.trust_service_url(service_url.rstrip("/"))

# ============================================================
#  Bot básico (Echo) para validar fluxo
# ============================================================
class GClickBot(ActivityHandler):
    """
    Bot principal do G-Click que processa mensagens e salva referências de conversação.
    """
    
    async def on_message_activity(self, turn_context: TurnContext):
        """
        Processa mensagens recebidas dos usuários.
        """
        text = turn_context.activity.text or ""
        await turn_context.send_activity(f"Echo: {text}")
        
        # Salva referência para mensagens proativas futuras
        self._save_conversation_reference(turn_context)

    async def on_members_added_activity(self, members_added, turn_context: TurnContext):
        """
        Processa quando o bot é adicionado a uma conversa ou um novo membro entra.
        """
        for member in members_added:
            if member.id != turn_context.activity.recipient.id:  # Não é o próprio bot
                await turn_context.send_activity(
                    "Olá! Eu sou o bot do G-Click. Estou pronto para enviar notificações sobre suas obrigações fiscais."
                )
        
        # Salva referência para envios futuros
        self._save_conversation_reference(turn_context)
                
    def _save_conversation_reference(self, turn_context: TurnContext):
        """
        Salva referência da conversa para mensagens proativas usando storage persistente.
        """
        # Obtém a referência da conversa
        conversation_reference = TurnContext.get_conversation_reference(turn_context.activity)
        
        # Armazena usando o ID do usuário como chave
        user_id = turn_context.activity.from_property.id
        
        # Usa o storage global persistente
        conversation_storage.add(user_id, conversation_reference)
        logging.info(f"Referência de conversa salva persistentemente para user_id={user_id}")

bot = GClickBot()

# ============================================================
#  /api/messages  (Endpoint do Bot Framework)
# ============================================================
@app.function_name(name="Messages")
@app.route(route="messages", methods=["POST"])
async def messages(req: func.HttpRequest) -> func.HttpResponse:
    logging.info("Recebendo atividade do Bot Framework em /api/messages")
    try:
        body_bytes = req.get_body()
        activity = Activity().deserialize(json.loads(body_bytes))

        # Log de depuração do header para garantir que vem um Bearer token
        auth_header = req.headers.get("Authorization", "") or req.headers.get("authorization", "")
        logging.info("Authorization header (primeiros 30 chars): %s", auth_header[:30])

        # Confia no serviceUrl antes de responder
        if activity.service_url:
            logging.info("serviceUrl recebido: %s", activity.service_url)
            trust_service_url_base(activity.service_url)
        else:
            logging.warning("Nenhum serviceUrl encontrado no Activity.")

        # process_activity é async
        response = await adapter.process_activity(activity, auth_header, bot.on_turn)

        # Se o adapter retornar algo (ex: InvokeResponse), devolvemos o status
        if response:
            return func.HttpResponse(status_code=response.status)

        return func.HttpResponse(status_code=200)

    except Exception as e:
        logging.exception("Erro ao processar atividade do bot")
        # Retorna 500 para o channel; o on_turn_error já tentou responder ao usuário
        return func.HttpResponse(f"Erro interno: {e}", status_code=500)

# ============================================================
#  /api/gclick  (Webhook do seu sistema)
#  Nesta sprint deixamos como stub. Na sprint 2: ler payload e enviar proativamente ao Teams.
# ============================================================
@app.function_name(name="GClickWebhook")
@app.route(route="gclick", methods=["POST"])
async def gclick_webhook(req: func.HttpRequest) -> func.HttpResponse:
    """
    Webhook para enviar notificações proativas via bot.
    """
    logging.info("Webhook do G-Click recebido em /api/gclick")
    
    try:
        data = req.get_json()
    except ValueError:
        return func.HttpResponse("Payload inválido", status_code=400)
    
    try:
        # Obtém dados do payload
        user_id = data.get("user_id")
        mensagem = data.get("mensagem", "Notificação do G-Click")
        
        if not user_id:
            logging.warning("[Webhook] Nenhum user_id fornecido no payload; nada foi enviado.")
            return func.HttpResponse("user_id obrigatório", status_code=400)
            
        # Envia mensagem proativa
        success = await bot_sender.send_message(user_id, mensagem)
        
        if success:
            return func.HttpResponse("Notificação enviada com sucesso", status_code=200)
        else:
            return func.HttpResponse("Usuário não encontrado ou erro ao enviar", status_code=404)
            
    except Exception as e:
        logging.error(f"Falha no processamento do webhook: {e}", exc_info=True)
        return func.HttpResponse("Erro interno ao enviar notificação", status_code=500)

# ============================================================
#  Endpoint para debug - listar usuários com referências
# ============================================================
@app.function_name(name="ListUsers")
@app.route(route="debug/users", methods=["GET"])
def list_users(req: func.HttpRequest) -> func.HttpResponse:
    """
    Lista todos os usuários que têm referências de conversação salvas.
    """
    try:
        users = conversation_storage.list_users()
        return func.HttpResponse(
            json.dumps({"users": users, "count": len(users)}),
            status_code=200,
            headers={"Content-Type": "application/json"}
        )
    except Exception as e:
        logging.error(f"Erro ao listar usuários: {e}")
        return func.HttpResponse("Erro interno", status_code=500)

# ============================================================
#  /api/http_trigger (endpoint antigo, mantido para debug)
# ============================================================
@app.function_name(name="HttpTrigger")
@app.route(route="http_trigger", methods=["GET", "POST"])
def http_trigger(req: func.HttpRequest) -> func.HttpResponse:
    logging.info("Python HTTP trigger function processed a request.")
    try:
        name = req.params.get("name")
        if not name:
            try:
                req_body = req.get_json()
                if req_body:
                    name = req_body.get("name")
            except (ValueError, TypeError):
                pass

        if name:
            response_message = f"Hello, {name}. This HTTP triggered function executed successfully."
        else:
            response_message = (
                "This HTTP triggered function executed successfully. "
                "Pass a name in the query string or in the request body for a personalized response."
            )
        return func.HttpResponse(response_message, status_code=200)

    except Exception as e:
        logging.error("Error in HTTP trigger: %s", str(e))
        return func.HttpResponse("Internal server error occurred.", status_code=500)

# ============================================================
#  TIMER TRIGGER (Scheduler) - Agendamento automático
# ============================================================
# Expressão CRON padrão (UTC). Formato: sec min hora dia mês diaSemana
# Exemplo: 0 0 20 * * *  -> executa todo dia às 20:00 UTC
DEFAULT_CRON = "0 0 20 * * *"
CRON_EXPR = os.getenv("NOTIFY_CRON", DEFAULT_CRON)

@app.function_name(name="DailyGclickNotify")
@app.schedule(schedule=CRON_EXPR, arg_name="mytimer", run_on_startup=False, use_monitor=True)
def daily_gclick_notify(mytimer: func.TimerRequest) -> None:
    """
    Executa o ciclo de coleta + classificação + envio de notificações.
    Ajuste para importar seu orquestrador real (engine.notification_engine.run_cycle).
    """
    logging.info(f"[Scheduler] Disparado em {datetime.utcnow().isoformat()}Z (PastDue={mytimer.past_due})")
    try:
        # Import dentro da função para evitar falhas se módulo não existir no cold start
        try:
            from engine.notification_engine import run_cycle  # type: ignore
            simulacao = os.getenv("SIMULACAO", "false").lower() == "true"
            run_cycle(simulacao=simulacao)
        except ImportError:
            logging.warning("[Scheduler] engine.notification_engine.run_cycle não encontrado. Ajuste a importação.")
        logging.info("[Scheduler] Finalizado com sucesso.")
    except Exception as e:
        logging.exception("[Scheduler] Falhou: %s", e)
