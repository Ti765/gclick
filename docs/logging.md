# 📝 Sistema de Logging - G-Click Teams

O sistema de logging do G-Click Teams foi projetado para prover rastreabilidade consistente e configurável em todos os módulos da aplicação.

## 🎯 Objetivos

- **Consistência**: Formato padronizado em todo código
- **Rastreabilidade**: Área/módulo identificado em cada log
- **Performance**: Configurável por ambiente
- **Compatibilidade**: Integrado com Azure Functions Monitor

## 🛠 Configuração

### Setup Básico

```python
from config.logging_config import setup_logger

# Criar logger para o módulo
logger = setup_logger(__name__)
```

### Níveis de Log

```python
# Debug - Informação detalhada para desenvolvimento
logger.debug("Detalhes de processamento: %s", details)

# Info - Operações normais e sucesso
logger.info("Operação completada com sucesso")

# Warning - Alertas que não impedem execução
logger.warning("Recurso não encontrado, usando fallback")

# Error - Erros que podem afetar funcionalidades
logger.error("Falha na operação: %s", error)
```

### Configuração por Ambiente

```python
# Via variável de ambiente
GCLICK_LOG_LEVEL = {
    'production': 'INFO',    # Apenas informações essenciais
    'staging': 'DEBUG',      # Detalhes para testes
    'development': 'DEBUG'   # Máximo de informação
}

# Override manual se necessário
logger = setup_logger(__name__, level='DEBUG')
```

## 📋 Padrões de Logging

### Engine de Notificação

```python
# Ciclo de notificação
logger.info("[ENGINE] Iniciando ciclo de notificações")
logger.info("[ENGINE] Coletadas %d tarefas na janela %s -> %s", total, inicio, fim)
logger.debug("[ENGINE] Separação - Normais: %d, Overdue: %d", normais, overdue)
logger.warning("[ENGINE] Falha ao processar tarefa %s: %s", task_id, error)
```

### Teams Integration e Cards

```python
# Envio e processamento de cards
logger.info("[BOT-CARD] Enviado para %s (tarefa: %s)", apelido, tarefa_id)
logger.info("[ACTION] Ação '%s' processada para task %s", action, task_id)
logger.debug("[CARD] Gerado card com detalhes: %s", card_details)
logger.warning("[BOT] Falha na referência de conversa: %s", error)
```

### Integração G-Click

```python
# API G-Click
logger.info("[GCLICK] Obtidos %d responsáveis para tarefa %s", num_resp, task_id)
logger.debug("[GCLICK] Request URL=%s, params=%s", url, params)
logger.warning("[GCLICK] Timeout na requisição (tentativa %d/%d)", attempt, retries)
logger.error("[GCLICK] Falha na autenticação: %s", error)
```

### Storage e Cache

```python
# Operações de storage
logger.info("[STORAGE] Salvando estado em %s", file_path)
logger.debug("[CACHE] Cache hit para key=%s", key)
logger.warning("[STORAGE] Lock timeout após %ds", timeout)
```

## 🔍 Visualização de Logs

### Local Development

```powershell
# Via terminal
func logs tail

# Arquivo de log
tail -f /logs/gclick-teams.log
```

### Azure Functions

```python
# Application Insights
logger.info("[METRIC] performance_metric=%s value=%d", metric_name, value)

# Kusto Query
traces
| where customDimensions.LogLevel == "Error"
| where timestamp > ago(1h)
| project timestamp, message, operation_Id
```

## 📊 Métricas e Alertas

### Métricas Chave

- **Taxa de Erro**: Logs ERROR vs total
- **Performance**: Tempo de execução operações
- **Volume**: Número de tarefas processadas
- **Latência**: Tempo resposta G-Click

### Alertas Configurados

- ERROR logs acima do threshold
- Falhas de autenticação consecutivas
- Timeout em operações críticas
- Zero tarefas processadas

## 🎯 Boas Práticas

1. **Estrutura Clara**
   - Use prefixos de área: [ENGINE], [BOT], [GCLICK]
   - Mantenha mensagens concisas e descritivas
   - Inclua dados relevantes para debugging

2. **Nível Apropriado**
   - DEBUG: Detalhes técnicos para desenvolvimento
   - INFO: Fluxo normal de operações
   - WARNING: Situações inesperadas com fallback
   - ERROR: Falhas que precisam atenção

3. **Performance**
   - Evite logging excessivo em produção
   - Use DEBUG apenas quando necessário
   - Considere custo de string formatting

4. **Segurança**
   - Nunca log credenciais ou tokens
   - Mascare dados sensíveis
   - Valide entrada antes de logar

## 🔄 Rotação e Retenção

### Configuração Padrão

```python
# Política de retenção
log_config = {
    'maxBytes': 10485760,    # 10MB
    'backupCount': 5,        # Manter 5 arquivos
    'encoding': 'utf8'
}
```

### Limpeza Automática

- Rotação diária de arquivos
- Compressão após rotação
- Limpeza após 30 dias
- Backup antes da limpeza

## 🐛 Troubleshooting

### Problemas Comuns

1. **Logs Ausentes**
   - Verifique GCLICK_LOG_LEVEL
   - Confirme logger configurado
   - Valide permissões arquivo

2. **Performance Impact**
   - Reduza nível em produção
   - Otimize mensagens
   - Use string formatting lazy

3. **Azure Integration**
   - Verifique Application Insights
   - Confirme sampling rate
   - Valide connection string

### Debug Mode

```python
# Ativar debug temporário
import logging
logging.getLogger('gclick_teams').setLevel(logging.DEBUG)

# Validar configuração
print(logger.getEffectiveLevel())
print(logger.handlers)
```

## 📚 Referências

- [Python Logging](https://docs.python.org/3/library/logging.html)
- [Azure Functions Logging](https://docs.microsoft.com/azure/azure-functions/functions-monitoring)
- [Application Insights](https://docs.microsoft.com/azure/azure-monitor/app/app-insights-overview)