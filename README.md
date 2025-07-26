# 🚀 Sistema de Notificações G-Click → Teams

**Sistema de automação de notificações** que integra a **API G-Click** (gestão de obrigações fiscais) com o **Microsoft Teams**, enviando alertas automáticos sobre tarefas próximas ao vencimento.

## 📋 Funcionalidades

- ⚠️ **Notificações de tarefas vencidas**
- 📅 **Alertas de vencimento hoje**
- 🔔 **Lembretes de vencimento próximo** (3 dias)
- 👥 **Notificações individualizadas** por responsável
- 📊 **Dashboard de status** com métricas
- 🔄 **Execução programada** ou manual
- 💾 **Cache inteligente** para performance
- 📈 **Sistema de métricas** e analytics

## 🏗️ Arquitetura

```
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│   API G-Click   │────│  Sistema Core   │────│ Microsoft Teams │
│  (OAuth2 + REST)│    │ (Python Engine) │    │   (Webhooks/Bot)│
└─────────────────┘    └─────────────────┘    └─────────────────┘
                              │
                    ┌─────────┴─────────┐
                    │                   │
              ┌─────────────┐    ┌─────────────┐
              │  Analytics  │    │   Storage   │
              │ & Metrics   │    │ & State Mgmt│
              └─────────────┘    └─────────────┘
```

## 🚀 Como usar

### 1. Instalação

```bash
# Clone o repositório
git clone https://github.com/Ti765/gclick.git
cd gclick_teams

# Instale dependências
pip install -r requirements.txt
```

### 2. Configuração

```bash
# Copie o template de ambiente
cp .env.example .env

# Configure suas credenciais no .env
# G_CLICK_CLIENT_ID=seu_client_id
# G_CLICK_CLIENT_SECRET=seu_client_secret
# TEAMS_WEBHOOK_URL=sua_webhook_url
```

### 3. Execução

#### **Validação básica (Sprint 1)**
```bash
python main.py
```

#### **Notificação única (recomendado)**
```bash
# Dry-run (teste)
python notify_once.py --dias-proximos 3 --verbose

# Produção (envia ao Teams)
python notify_once.py --dias-proximos 3 --enviar
```

#### **Loop contínuo**
```bash
python notify_loop.py --intervalo 600
```

#### **Execução programada**
```bash
python scheduling.py
```

#### **Dashboard de status**
```bash
python status_dashboard.py
```

## 📁 Estrutura do Projeto

```
├── 📱 Scripts principais
│   ├── main.py              # Validação básica (Sprint 1)
│   ├── notify_once.py       # Execução única ⭐
│   ├── notify_loop.py       # Loop contínuo
│   ├── scheduling.py        # Execução programada
│   └── status_dashboard.py  # Dashboard de métricas
│
├── 🔗 gclick/              # Integração API G-Click
│   ├── auth.py             # OAuth2 + cache de token
│   ├── tarefas.py          # Consulta e normalização
│   ├── responsaveis.py     # Busca responsáveis
│   ├── departamentos.py    # Cache de departamentos
│   └── ...
│
├── ⚙️ engine/              # Motor de notificações
│   ├── notification_engine.py # Core principal ⭐
│   ├── message_builder.py     # Templates de mensagem
│   ├── classification.py      # Classificação temporal
│   └── models.py              # Data classes
│
├── 💬 teams/               # Microsoft Teams
│   ├── webhook.py          # Cliente webhook
│   ├── payloads.py         # Mensagens formatadas
│   └── bot_sender.py       # Bot framework (novo)
│
├── 💾 storage/             # Persistência
│   ├── state.py            # Estado de notificações
│   ├── lock.py             # File locks
│   └── notification_state.json
│
├── 📊 analytics/           # Métricas
│   ├── metrics.py          # Sistema de métricas
│   ├── status_metrics.py   # Analytics de status
│   └── metrics_aggregate.py
│
└── ⚙️ config/              # Configurações
    ├── config.yaml         # Config principal
    ├── notifications.yaml  # Parâmetros de notificação
    ├── scheduling.yaml     # Horários de execução
    └── loader.py           # Carregador de configs
```

## 🔧 Configurações Avançadas

### **config/config.yaml**
```yaml
simulacao:
  dry_run_default: true
  
individuais:
  limite_responsaveis_notificar: 50
  detalhar_limite: 5
  
limites:
  max_responsaveis_lookup: 100
  page_size: 200
```

### **config/notifications.yaml**
```yaml
ciclo:
  rate_limit_sleep_ms: 100
  repetir_no_mesmo_dia: false
  
filtros:
  apenas_status_abertos: true
  dias_proximos_default: 3
```

### **config/scheduling.yaml**
```yaml
horarios:
  - "08:00"
  - "14:00"
  - "17:00"
  
skip_weekends: true
skip_holidays: true
```

## 📊 Sistema de Métricas

O sistema registra métricas detalhadas em:
- **JSONL**: `storage/metrics/notification_cycle_*.jsonl`
- **JSON**: `storage/metrics/metrics_aggregate.json`
- **CSV**: `reports/exports/metrics_daily.csv`

### Métricas Coletadas:
- Total de tarefas processadas
- Distribuição por status (vencidas/hoje/próximas)
- Performance (tempo de execução)
- Responsáveis notificados
- Taxa de erro

## 🛡️ Segurança

- ✅ **OAuth2** Client Credentials para G-Click
- ✅ **Environment variables** para credenciais
- ✅ **Thread-safe** operations
- ✅ **Rate limiting** configurável
- ✅ **Retry logic** com backoff

## 🔄 Fluxo de Execução

1. **🔐 Autenticação** → OAuth2 com G-Click
2. **📥 Coleta** → Busca tarefas por período
3. **🎯 Classificação** → Vencidas/hoje/próximas
4. **👥 Responsáveis** → Identifica responsáveis
5. **🔍 Filtragem** → Aplica whitelist
6. **📨 Notificação** → Envia via Teams
7. **📊 Métricas** → Registra estatísticas

## 🚦 Status do Projeto

- ✅ **Sprint 1**: Validação básica completa
- ✅ **Core Engine**: Totalmente implementado
- ✅ **Teams Integration**: Webhook + Bot Framework
- ✅ **Métricas**: Sistema completo
- ✅ **Configurabilidade**: 17+ parâmetros
- ✅ **Produção Ready**: Error handling + logging

### **Últimas melhorias:**
- 🔧 Cache unificado de departamentos
- 🐍 Type hints compatíveis (Python 3.9+)
- 🛡️ Exception handling robusto
- 🤖 Integração Bot Framework Teams

## 📖 Exemplos de Uso

### **Notificação de teste**
```bash
python notify_once.py --dias-proximos 7 --verbose --dry-run
```

### **Notificação em produção**
```bash
python notify_once.py --dias-proximos 3 --enviar --registrar-metricas
```

### **Dashboard de status**
```bash
python status_dashboard.py --enviar-teams
```

## 🤝 Contribuição

1. Fork o projeto
2. Crie uma branch (`git checkout -b feature/nova-funcionalidade`)
3. Commit suas mudanças (`git commit -am 'Adiciona nova funcionalidade'`)
4. Push para a branch (`git push origin feature/nova-funcionalidade`)
5. Crie um Pull Request

## 📄 Licença

Este projeto está sob licença [MIT](LICENSE).

## 🆘 Suporte

Para dúvidas ou problemas:
- 📧 Abra uma [issue](https://github.com/Ti765/gclick/issues)
- 📚 Consulte os logs em `storage/` e `analytics/`
- 🔧 Use `--verbose` para debug detalhado

---

**Sistema desenvolvido para automação de notificações de obrigações fiscais** 🇧🇷
