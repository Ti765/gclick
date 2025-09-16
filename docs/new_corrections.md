O que está errado (pelos logs)

Storage de conversas NÃO está configurado (zero referências)

GET /api/debug/conversation-storage retorna:

storage_configured : False

references_count : 0

file_exists : False
➡️ Sem conversation references salvas, o bot não pode enviar mensagens proativas (cards) para ninguém. Isso só existe depois que um usuário manda uma mensagem para o bot, e o backend salva essa referência.

Ciclo está em “modo degradado” (engine não carregou)

Em todas as execuções do ciclo:
⏭️  Notification engine não ddisponível - modo degradado

➡️ O handler de /api/run-cycle e os timers detectaram que o módulo notification_engine não foi carregado (ImportError ou feature flag desligada). Em “degradado” ele não tenta mandar nada via bot/webhook — só devolve sucesso “de fachada”.

Mapeamento de usuário do Teams ausente (ou stub)

No webhook de teste:
Stub: mapear_apelido_para_teams_id chamado com mauricio
⚠️ Mapeamento não encontrado:: mauricio
📊 Webhook processado: 0 enviados, 1 falharam

➡️ A função de mapeamento está no modo stub (ou sem tabela). Mesmo que houvesse referência salva, esse caminho falha ao resolver o Teams ID.

O que fazer (passo a passo, direto ao ponto)
A. Ligar o notification engine (parar o “modo degradado”)

Confirme os imports no app
No arquivo da Function que processa /api/run-cycle (ou no function_app.py, conforme sua estrutura), garanta esse padrão de import com fallback:
try:
    from azure_functions.shared_code.engine.notification_engine import run_notification_cycle
    ENGINE_OK = True
except Exception as e:
    import logging, traceback
    ENGINE_OK = False
    logging.error("Falha ao importar notification_engine: %s", e, exc_info=True)

Se hoje você usa apenas from shared_code.engine.notification_engine import ..., troque para o caminho com prefixo azure_functions. (e mantenha o fallback, se quiser).

Feature flags / envs
No local.settings.json, garanta (exemplos):
{
  "IsEncrypted": false,
  "Values": {
    "AzureWebJobsStorage": "UseDevelopmentStorage=true",
    "FUNCTIONS_WORKER_RUNTIME": "python",

    "FEATURE_NOTIFICATION_ENGINE": "true",
    "FEATURE_TEAMS_BOT": "true",
    "FEATURE_STORE_CONVERSATIONS": "true",
    "FEATURE_DEBUG_ENDPOINTS": "true",

    "MICROSOFT_APP_ID": "<appId do seu bot>",
    "MICROSOFT_APP_PASSWORD": "<client secret do bot>",

    "CONVERSATION_STORAGE_PATH": ".data/conversations.json",

    "X_RUN_SECRET": "test123",      // se o endpoint exige
    "TEAMS_WEBHOOK_URL": "<opcional: webhook de canal para fallback>"
  }
}

Reinicie o host (func start) e verifique se a mensagem “modo degradado” sumiu ao chamar /api/run-cycle.

B. Inicializar o Teams Bot corretamente

Endpoint público / Bot Channel Registration

Com o ngrok http 7071 rodando, configure no Azure Bot (ou no arquivo de manifest do Teams app) a URL de mensagens:

Deixe MICROSOFT_APP_ID e MICROSOFT_APP_PASSWORD válidos no local.settings.json.

Capture a conversation reference (necessário 1x por usuário)

No Teams, abra um chat 1:1 com o bot e mande um “oi”.

O endpoint /api/messages receberá o activity e salvará a referência.

Confirme o armazenamento

Rode:
Invoke-RestMethod -Uri "http://localhost:7071/api/debug/conversation-storage" -Method GET

Esperado:

storage_configured : True

file_exists : True

references_count : >= 1

storage_path : ...conversations.json

Sem esse passo, não existe para onde enviar a notificação proativa.

C. Corrigir mapeamento de apelido → Teams ID

Você tem três alternativas (use a que preferir):

Mapeamento estático por ENV

Defina um JSON simples (apelido → AAD object id ou userId do Teams):
"TEAMS_USER_MAP_JSON": "{\"mauricio\":\"<teamsUserId>\"}"

O user_mapping.py deve ler isso (já há suporte no seu código; se não, é simples adicionar).

Arquivo de mapeamento

TEAMS_USER_MAP_FILE="config/teams_user_map.yaml"

Conteúdo:
mauricio: "<teamsUserId>"
joao:     "<teamsUserId>"

Default único para testes

TEAMS_DEFAULT_USER_ID="<teamsUserId>"

Assim, qualquer apelido cai nesse ID (bom para smoke test).

Depois, refaça o teste do /api/gclick e do /api/run-cycle. Aquele log “Stub: mapear_apelido…” deve desaparecer.