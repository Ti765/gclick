# 🚀 G-Click Teams - Sistema de Notificações Fiscais

Sistema automatizado de notificações para obrigações fiscais integrado com Microsoft Teams e Azure Functions Bot Framework.

## 📋 Índice

- [Visão Geral](#-visão-geral)
- [Arquitetura](#-arquitetura)
- [Features Principais](#-features-principais)
- [Instalação e Configuração](#-instalação-e-configuração)
- [Como Usar](#-como-usar)
- [Estrutura do Projeto](#-estrutura-do-projeto)
- [Azure Functions Integration](#-azure-functions-integration)
- [API e Endpoints](#-api-e-endpoints)
- [Monitoramento e Analytics](#-monitoramento-e-analytics)
- [Configurações](#-configurações)
- [Troubleshooting](#-troubleshooting)

## 🎯 Visão Geral

O **G-Click Teams** é uma solução enterprise para automação de notificações de obrigações fiscais que:

- 🔄 **Coleta** tarefas da API G-Click automaticamente
- 🎯 **Classifica** por urgência e responsável
- 📨 **Envia** notificações via Teams (bot ou webhook)
- 📊 **Monitora** métricas e performance
- ☁️ **Executa** em Azure Functions com timer automático

## 🏗 Arquitetura

```
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│   API G-Click   │────│  Sistema Core   │────│ Microsoft Teams │
│  (OAuth2 + REST)│    │ (Python Engine) │    │(Webhook + Bot)  │
└─────────────────┘    └─────────────────┘    └─────────────────┘
                              │
                    ┌─────────┴─────────┐
                    │                   │
              ┌─────────────┐    ┌─────────────┐
              │Azure Function│    │  Analytics  │
              │  Bot Framework│    │ & Storage   │
              └─────────────┘    └─────────────┘
```

## ⭐ Features Principais

### 🤖 **Bot Framework Integration** (Sprint 1 & 2)
- Mensagens proativas diretas para usuários
- Storage persistente de referências de conversação
- Mapeamento automático G-Click → Teams ID
- **[NOVO] Cartões adaptativos interativos com botões**
- **[NOVO] Webhook robusto para notificações em tempo real**

### 🕒 **Agendamento Inteligente** (Sprint 2)
- **[NOVO] Timer duplo: 8:00 e 17:30 (BRT) em dias úteis**
- **[NOVO] Classificação avançada de urgência**
- **[NOVO] Filtro de tarefas vencidas (até 1 dia de atraso)**
- Horários configuráveis via variáveis de ambiente

### 🎨 **Experiência de Usuário Aprimorada** (Sprint 2)
- **[NOVO] Adaptive Cards com design responsivo**
- **[NOVO] Indicadores visuais de urgência (🔴🟡🟢)**
- **[NOVO] Botões para ações rápidas (Ver no G-Click, Detalhes)**
- **[NOVO] Mensagens formatadas com fallback para texto**

### 🛡️ **Resiliência e Confiabilidade** (Sprint 2)
- **[NOVO] Tratamento robusto de falhas em lote**
- **[NOVO] Retry automático com backoff exponencial**
- **[NOVO] Contador global de erros e monitoramento**
- **[NOVO] Logs detalhados para auditoria**
- **[NOVO] Validação rigorosa de payload do webhook**
- Endpoints para webhook e debug

### 🔄 **Motor de Notificações Inteligente**
- Coleta automática de tarefas por período
- Classificação por urgência temporal
- Agrupamento por responsável
- Filtros configuráveis via whitelist

### ☁️ **Azure Functions Ready**
- Timer triggers com cron configurável
- Endpoints HTTP para webhooks
- Tratamento robusto de erros
- Logs estruturados

### 📊 **Analytics e Monitoramento**
- Métricas em tempo real (JSONL)
- Dashboard de status ASCII
- Prevenção de duplicatas
- Exportação de dados

## 🛠 Instalação e Configuração

### **Pré-requisitos**
- Python 3.9+
- Conta Azure com Functions habilitadas
- Bot registrado no Azure Bot Service
- Acesso à API G-Click

### **1. Clone e Instale Dependências**

```bash
git clone https://github.com/Ti765/gclick.git
cd gclick
pip install -r requirements.txt
```

### **2. Configuração do Ambiente**

Crie `.env` na raiz do projeto:

```env
# G-Click API - Obrigatórias
GCLICK_CLIENT_ID=seu_client_id
GCLICK_CLIENT_SECRET=seu_client_secret
GCLICK_BASE_URL=https://api.gclick.com.br
GCLICK_SISTEMA=nome_do_sistema
GCLICK_CONTA=sua_conta
GCLICK_USUARIO=seu_usuario
GCLICK_SENHA=sua_senha
GCLICK_EMPRESA=codigo_empresa

# Microsoft Bot Framework - Obrigatórias
MicrosoftAppId=seu_app_id
MicrosoftAppPassword=sua_app_password
MicrosoftAppType=MultiTenant

# Teams Webhook (opcional - usado como fallback)
TEAMS_WEBHOOK_URL=https://outlook.office.com/webhook/...

# Configurações do Sistema (opcionais)
SIMULACAO=false
NOTIFY_CRON=0 0 20 * * *
GCLICK_DEBUG=0
ALERT_ZERO_ABERTOS_TO_TEAMS=false
GCLICK_CONFIG_FILE=config/config.yaml
GCLICK_CATEGORIA=todas
METRICS_DIR=storage/metrics
APP_TIMEZONE=America/Sao_Paulo
```

#### **📋 Tabela de Variáveis de Ambiente**

| Variável | Obrigatória | Propósito | Exemplo |
|----------|-------------|-----------|---------|
| `GCLICK_CLIENT_ID` | ✅ | ID do cliente OAuth2 G-Click | `abc123def456` |
| `GCLICK_CLIENT_SECRET` | ✅ | Secret do cliente OAuth2 | `secret_key_here` |
| `GCLICK_BASE_URL` | ✅ | URL base da API G-Click | `https://api.gclick.com.br` |
| `GCLICK_SISTEMA` | ✅ | Nome do sistema G-Click | `FISCAL_MANAGER` |
| `GCLICK_CONTA` | ✅ | Conta no sistema G-Click | `12345` |
| `GCLICK_USUARIO` | ✅ | Usuário de acesso | `usuario.api` |
| `GCLICK_SENHA` | ✅ | Senha do usuário | `senha_segura` |
| `GCLICK_EMPRESA` | ✅ | Código da empresa | `001` |
| `MicrosoftAppId` | ✅ | ID da aplicação Bot Framework | `12345678-1234-1234-1234-123456789012` |
| `MicrosoftAppPassword` | ✅ | Password da aplicação bot | `password_bot_framework` |
| `MicrosoftAppType` | ✅ | Tipo da aplicação bot | `MultiTenant` |
| `TEAMS_WEBHOOK_URL` | ❌ | URL webhook Teams (fallback) | `https://outlook.office.com/webhook/...` |
| `SIMULACAO` | ❌ | Modo simulação (dry-run) | `false` |
| `NOTIFY_CRON` | ❌ | Expressão cron para timer | `0 0 20 * * *` |
| `GCLICK_DEBUG` | ❌ | Debug HTTP requests | `0` |
| `ALERT_ZERO_ABERTOS_TO_TEAMS` | ❌ | Alertar quando zero tarefas | `false` |
| `GCLICK_CONFIG_FILE` | ❌ | Caminho config YAML | `config/config.yaml` |
| `GCLICK_CATEGORIA` | ❌ | Filtro de categoria | `todas` |
| `METRICS_DIR` | ❌ | Diretório de métricas | `storage/metrics` |
| `APP_TIMEZONE` | ❌ | Timezone da aplicação | `America/Sao_Paulo` |

### **3. Configuração Local Azure Functions**

Copie `local.settings.json.example` para `azure_functions/local.settings.json`:

```json
{
  "IsEncrypted": false,
  "Values": {
    "AzureWebJobsStorage": "UseDevelopmentStorage=true",
    "FUNCTIONS_WORKER_RUNTIME": "python",
    "MicrosoftAppId": "seu_app_id",
    "MicrosoftAppPassword": "sua_app_password",
    "GCLICK_CLIENT_ID": "seu_client_id",
    "GCLICK_CLIENT_SECRET": "seu_client_secret"
  }
}
```

## 🚀 Como Usar

### **Execução Local**

```bash
# Teste único com simulação
python notify_once.py --dias-proximos 3 --verbose --dry-run

# Execução real
python notify_once.py --dias-proximos 3 --verbose

# Dashboard de status
python status_dashboard.py

# Loop contínuo
python notify_loop.py
```

### **Testes e Simulação** (Sprint 2)

```bash
# Teste completo de ponta a ponta
python tests/test_notification_flow.py

# Simular webhook do G-Click (precisa do Functions rodando)
python tests/simulate_gclick_webhook.py --scenario single
python tests/simulate_gclick_webhook.py --scenario multiple
python tests/simulate_gclick_webhook.py --scenario overdue

# Listar cenários de teste disponíveis
python tests/simulate_gclick_webhook.py --list-scenarios

# Teste com URL personalizada
python tests/simulate_gclick_webhook.py --url https://sua-function-app.azurewebsites.net/api/gclick
```

### **Exemplos de Payload para Webhook** (Sprint 2)

**Payload básico:**
```json
{
  "evento": "tarefa_vencimento_proximo",
  "tarefa": {
    "id": "4.12345",
    "nome": "SPED - ECF (Escrituração Contábil Fiscal)",
    "dataVencimento": "2025-07-31",
    "status": "A"
  },
  "responsaveis": [
    {
      "id": "123",
      "apelido": "neusag.glip",
      "nome": "Neusa Gomes",
      "email": "neusa@exemplo.com"
    }
  ],
  "urgencia": "alta"
}
```

**Payload com múltiplos responsáveis:**
```json
{
  "evento": "tarefa_vencimento_hoje",
  "tarefa": {
    "id": "4.67890",
    "nome": "CSLL e IRPJ - LR",
    "dataVencimento": "2025-07-30",
    "status": "A"
  },
  "responsaveis": [
    {"apelido": "sueli.coelho", "nome": "Sueli Coelho"},
    {"apelido": "daniele.rocha", "nome": "Daniele Rocha"}
  ]
}
```

### **Azure Functions (Produção)**

```bash
# Instalar Azure Functions Core Tools
npm install -g azure-functions-core-tools@4

# Executar localmente
cd azure_functions
func start

# Deploy para Azure
func azure functionapp publish <nome-da-function-app>
```

### **Teste do Bot**

```bash
# Teste via webhook
curl -X POST http://localhost:7071/api/gclick \
  -H "Content-Type: application/json" \
  -d '{"user_id": "29:xxx", "mensagem": "Teste de notificação"}'

# Listar usuários com referências salvas
curl http://localhost:7071/api/debug/users
```

## 📁 Estrutura do Projeto

```
gclick_teams/
├── azure_functions/              # Azure Functions + Bot Framework
│   ├── function_app.py          # Main bot app com endpoints
│   ├── host.json                # Configuração runtime
│   ├── local.settings.json      # Configurações locais
│   └── requirements.txt         # Dependências Azure
├── gclick/                      # Integração API G-Click
│   ├── auth.py                  # OAuth2 authentication
│   ├── tarefas.py               # Consulta de tarefas
│   ├── responsaveis.py          # Busca responsáveis
│   └── departamentos.py         # Cache departamentos
├── teams/                       # Microsoft Teams Integration
│   ├── bot_sender.py           # Bot Framework sender
│   ├── webhook.py              # Webhook client
│   └── payloads.py             # Message templates
├── engine/                     # Motor de Notificações
│   ├── notification_engine.py  # Orquestrador principal
│   ├── message_builder.py      # Templates mensagens
│   ├── models.py               # Data classes
│   └── classification.py       # Lógica de classificação
├── storage/                    # Persistência de dados
│   ├── state.py               # Estado notificações
│   ├── lock.py                # File locking
│   └── conversation_references.json  # Bot references
├── analytics/                 # Métricas e análises
│   ├── metrics.py            # Sistema métricas JSONL
│   └── status_metrics.py     # Dashboard status
├── config/                   # Configurações
│   ├── config.yaml          # Config principal
│   ├── scheduling.yaml       # Horários execução
│   ├── notifications.yaml    # Templates notificações
│   └── feriados.yaml        # Calendário feriados
├── requirements.txt          # Dependências produção
├── requirements-dev.txt      # Dependências desenvolvimento
└── .funcignore              # Arquivos ignorados no deploy
```

## ☁️ Azure Functions Integration

### **Endpoints Disponíveis**

| Endpoint | Método | Função |
|----------|--------|--------|
| `/api/messages` | POST | Bot Framework webhook |
| `/api/gclick` | POST | Notificações proativas |
| `/api/debug/users` | GET | Lista usuários com referências |
| `/api/http_trigger` | GET/POST | Health check |

### **Timer Trigger**

Execução automática configurável via `NOTIFY_CRON`:

```python
# Padrão: 20:00 todos os dias
DEFAULT_CRON = "0 0 20 * * *"

# Personalizado via environment variable
CRON_EXPR = os.getenv("NOTIFY_CRON", DEFAULT_CRON)
```

### **Bot Framework Setup**

1. **Registre Bot no Azure Portal**
2. **Configure Bot Service** com endpoint: `https://sua-function.azurewebsites.net/api/messages`
3. **Adicione ao Teams** via App Studio
4. **Configure permissões** para envio proativo

## 🔌 API e Endpoints

### **Envio de Notificação Proativa**

```http
POST /api/gclick
Content-Type: application/json

{
  "user_id": "29:1234567890abcdef",
  "mensagem": "🚨 Você tem 3 obrigações vencendo hoje!"
}
```

### **Listar Usuários com Referências**

```http
GET /api/debug/users

Response:
{
  "users": ["29:abc123", "29:def456"],
  "count": 2
}
```

### **Health Check**

```http
GET /api/http_trigger?name=teste

Response: "Hello, teste. This HTTP triggered function executed successfully."
```

## 📊 Monitoramento e Analytics

### **Métricas Coletadas**

```json
{
  "timestamp": "2025-01-27T20:00:00Z",
  "type": "notification_cycle",
  "data": {
    "total_tasks": 156,
    "users_notified": 12,
    "notifications_sent": 45,
    "duration_seconds": 8.5
  }
}
```

### **Dashboard Status**

```bash
python status_dashboard.py

╔════════════════════════════════════════╗
║           STATUS DAS TAREFAS           ║
╠════════════════════════════════════════╣
║ 📊 Total de tarefas: 39,550            ║
║ ✅ Concluídas: 85.2% (33,697)         ║
║ 🔄 Em andamento: 12.1% (4,781)        ║
║ ⚠️  Atrasadas: 2.7% (1,072)           ║
╚════════════════════════════════════════╝
```

### **Logs e Debug**

```python
# Enable debug logs
import logging
logging.basicConfig(level=logging.DEBUG)

# Check conversation references
storage = ConversationReferenceStorage()
print(f"Usuários salvos: {storage.list_users()}")
```

## ⚙️ Configurações

### **config/config.yaml**

```yaml
sistema:
  simulacao: false
  max_tarefas_por_mensagem: 10
  
filtros:
  incluir_finalizadas: false
  status_permitidos: ["Pendente", "Em Andamento"]
  
notificacao:
  individuais: true
  canal_geral: false
  prefixo_urgencia: "🚨"
```

### **Mapeamento Usuários (teams/bot_sender.py)**

```python
def mapear_apelido_para_teams_id(apelido: str) -> Optional[str]:
    mapeamento = {
        "mauricio.bernej": "29:1xxxxx-yyyy-zzzz",
        "eliels.glip": "29:2xxxxx-yyyy-zzzz",
        # Adicione seus mapeamentos aqui
    }
    return mapeamento.get(apelido.lower())
```

## 🔧 Troubleshooting

### **Problemas Comuns**

#### **Bot não recebe mensagens**
```bash
# Verificar configuração
curl -X GET https://sua-function.azurewebsites.net/api/debug/users

# Logs Azure Functions
func logs tail --resource-group <rg> --name <function-app>
```

#### **Erro de autenticação G-Click**
```python
# Teste credentials
from gclick.auth import GClickAuth
auth = GClickAuth()
print(auth.get_token())  # Deve retornar token válido
```

#### **Storage não persiste**
```bash
# Verificar permissões pasta storage/
ls -la storage/
# Criar se não existir
mkdir -p storage
```

#### **Timer não executa**
```yaml
# Verificar cron expression
NOTIFY_CRON: "0 0 20 * * *"  # 20:00 todos os dias
NOTIFY_CRON: "0 */30 * * * *"  # A cada 30 minutos
```

### **Debug Mode**

```bash
# Execução com debug completo
export SIMULACAO=true
python notify_once.py --verbose --dry-run

# Logs detalhados Azure Functions
func logs --show-trace
```

### **Verificação de Saúde**

```bash
# Status sistema completo
python -c "
from engine.notification_engine import run_cycle
result = run_cycle(simulacao=True)
print(f'Status: {result}')
"
```

## 📈 Roadmap

### **Próximas Melhorias**
- [ ] Interface web para configuração
- [ ] Integração com Power BI para dashboards
- [ ] Suporte a múltiplos tenants G-Click
- [ ] Cache Redis para alta performance
- [ ] Notificações por email como fallback
- [ ] Webhooks bidirecionais para feedback

### **Contribuindo**

1. Fork o projeto
2. Crie branch para feature (`git checkout -b feature/nova-feature`)
3. Commit suas mudanças (`git commit -m 'feat: adiciona nova feature'`)
4. Push para branch (`git push origin feature/nova-feature`)
5. Abra Pull Request

---

## 📝 Licença

Este projeto está sob licença MIT. Veja o arquivo `LICENSE` para mais detalhes.

## 🙋‍♂️ Suporte

Para dúvidas ou problemas:
- 📧 Email: suporte@exemplo.com
- 🐛 Issues: [GitHub Issues](https://github.com/Ti765/gclick/issues)
- 📖 Wiki: [Documentação Completa](https://github.com/Ti765/gclick/wiki)

---

**Desenvolvido com ❤️ para automatizar e simplificar o compliance fiscal.**