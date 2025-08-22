import os
import time
import json
import logging
from datetime import date, timedelta
from collections import defaultdict
from typing import Dict, List, Any, Tuple, Optional
import datetime as dt

import yaml

from gclick.tarefas import listar_tarefas_page, normalizar_tarefa
from gclick.responsaveis import listar_responsaveis_tarefa
from teams.webhook import enviar_teams_mensagem
from teams.cards import create_task_notification_card
from storage.state import already_sent, register_sent, purge_older_than
# NOVA API: Idempotência granular
from storage.state import (
    get_global_state_storage, 
    aplicar_filtro_idempotencia, 
    marcar_envios_bem_sucedidos,
    criar_chave_idempotencia
)

# Configurar logger
logger = logging.getLogger(__name__)

# Imports P2: Cache e Resilience
try:
    from engine.cache import IntelligentCache
    from engine.resilience import resilient, resilience_manager
    HAS_RESILIENCE = True
    # Instanciar cache global
    notification_cache = IntelligentCache(max_size=1000, default_ttl=300)
except ImportError as e:
    logger.warning("Sistema de resilience não disponível: %s", e)
    HAS_RESILIENCE = False
    notification_cache = None
    # Fallback decorator que não faz nada
    def resilient(service: str = "default", check_rate_limit: bool = True):
        def decorator(func):
            return func
        return decorator

# Imports para funcionalidades avançadas
try:
    from engine.classification import separar_tarefas_overdue, obter_data_atual_brt
    from reports.overdue_report import gerar_relatorio_excel_overdue
    HAS_ADVANCED_FEATURES = True
except ImportError as e:
    logger.warning("Funcionalidades avançadas não disponíveis: %s", e)
    HAS_ADVANCED_FEATURES = False

# ================= HELPERS PARA ROBUSTEZ =================

def _cached_listar_tarefas_page(categoria: str, page: int, size: int, 
                               dataVencimentoInicio: str = None, 
                               dataVencimentoFim: str = None):
    """Wrapper com cache para listar_tarefas_page."""
    if not HAS_RESILIENCE or not notification_cache:
        return listar_tarefas_page(categoria, page, size, dataVencimentoInicio, dataVencimentoFim)
    
    # Criar chave de cache baseada nos parâmetros
    cache_key = f"tarefas:{categoria}:{page}:{size}:{dataVencimentoInicio}:{dataVencimentoFim}"
    
    # Tentar buscar do cache primeiro
    cached_result = notification_cache.get(cache_key)
    if cached_result is not None:
        logger.debug("🎯 Cache HIT para tarefas (page=%d, size=%d)", page, size)
        return cached_result
    
    # Se não está no cache, fazer chamada da API
    try:
        result = listar_tarefas_page(categoria, page, size, dataVencimentoInicio, dataVencimentoFim)
        # Armazenar no cache com TTL menor para dados dinâmicos (5 minutos)
        notification_cache.set(cache_key, result, ttl=300)
        logger.debug("💾 Cache MISS para tarefas (page=%d, size=%d) - armazenado", page, size)
        return result
    except Exception as e:
        logger.warning("❌ Falha ao buscar tarefas (page=%d, size=%d): %s", page, size, e)
        raise

@resilient(service="teams_bot", check_rate_limit=False)  # Rate limit separado do main cycle
async def _resilient_send_card(bot_sender, teams_id: str, card_payload: dict, fallback_text: str):
    """Wrapper com resilience para envio de cards."""
    if not HAS_RESILIENCE:
        return await bot_sender.send_card(teams_id, card_payload, fallback_text)
    
    try:
        result = await bot_sender.send_card(teams_id, card_payload, fallback_text)
        logger.debug("📤 Card enviado com sucesso para %s", teams_id)
        return result
    except Exception as e:
        logger.warning("📤❌ Falha ao enviar card para %s: %s", teams_id, e)
        raise

def _ensure_card_payload(card) -> dict:
    """Garante que o payload do card seja dict (Teams/Bot esperam dict)."""
    if isinstance(card, str):
        try:
            return json.loads(card)
        except Exception:
            logging.warning("[CARD] Payload veio como string não-JSON; usando fallback.")
            return {"type": "AdaptiveCard", "version": "1.3"}  # fallback mínimo
    return card


def _has_conversation(storage, user_id: str) -> bool:
    """Verifica, de forma tolerante, se há reference salva para o usuário."""
    if storage is None or not user_id:
        return False

    # Tenta diferentes métodos do storage
    for method in ("get", "has", "exists", "contains"):
        if hasattr(storage, method):
            fn = getattr(storage, method)
            try:
                res = fn(user_id)
                if isinstance(res, bool):
                    return res
                return bool(res)  # get(...) pode retornar dict/ref
            except TypeError:
                # get(user_id, default)
                try:
                    res = fn(user_id, None)  # type: ignore
                    return bool(res)
                except Exception:
                    pass
            except Exception:
                pass

    # Fallback para atributos internos
    for attr in ("_conversations", "references", "_data"):
        if hasattr(storage, attr):
            raw = getattr(storage, attr)
            if isinstance(raw, dict):
                return user_id in raw
    return False

try:
    from analytics.metrics import write_notification_cycle, new_run_id
except ImportError:  # Fallback se ainda não implementado
    def write_notification_cycle(**_k):  # type: ignore
        pass
    def new_run_id(prefix: str = 'run'):  # type: ignore
        return f"{prefix}_dummy"

# ================= INTEGRAÇÃO COM BOT ADAPTER =================
# Tente importar o adapter, conversation_references e BotSender.
bot_sender = None
adapter = None
conversation_references = None

try:
    # CORRIGIDO: Importar do módulo compartilhado correto
    from teams.bot_sender import BotSender
    from teams.user_mapping import mapear_apelido_para_teams_id
    # Note: adapter e conversation_references serão definidos pela function_app.py
    # quando o bot estiver ativo. Por enquanto, manteremos como None.
    import logging
    logging.info("[ENGINE] Bot sender imports disponíveis")
except ImportError as e:
    # Se falhar, segue só com webhook (até ajustar)
    import logging
    logging.warning(f"[BOT] Falha ao importar BotSender: {e}")
    
    def mapear_apelido_para_teams_id(apelido: str):
        return None

STATUS_ABERTOS = {"A", "P", "Q", "S"}
ALERT_ZERO_ABERTOS_TO_TEAMS = os.getenv("ALERT_ZERO_ABERTOS_TO_TEAMS", "false").lower() in ("1", "true", "yes")

STATUS_LABEL_LOCAL = {
    "A": "Aberto/Autorizada",
    "S": "Aguardando",
    "C": "Concluído",
    "D": "Dispensado",
    "F": "Finalizado",
    "E": "Retificando",
    "O": "Retificado",
    "P": "Solicitado (externo/email)",
    "Q": "Solicitado (visão cliente)"
}

# =============================================================
# Config
# =============================================================

def load_notifications_config(path="config/notifications.yaml") -> dict:
    """
    Carrega configurações de notificação com suporte a environment variables.
    Environment variables têm precedência sobre o YAML.
    """
    # Configurações padrão
    default_config = {
        "dias_proximos": 3,
        "dias_proximos_morning": 3,
        "dias_proximos_afternoon": 1,
        "page_size": 50,
        "max_responsaveis_lookup": 100,
        "usar_full_scan": True,
        "timezone": "America/Sao_Paulo",
        "max_tarefas_por_responsavel": 5
    }
    
    # Carregar YAML se existir
    yaml_config = {}
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                yaml_config = yaml.safe_load(f) or {}
            logger.info("✅ Configurações YAML carregadas de %s", path)
        except Exception as e:
            logger.warning("⚠️ Erro ao carregar YAML %s: %s", path, e)
    
    # Combinar configurações: padrão <- YAML <- env vars
    config = {**default_config, **yaml_config}
    
    # Environment variables têm precedência máxima
    env_mappings = {
        "DIAS_PROXIMOS": "dias_proximos",
        "DIAS_PROXIMOS_MORNING": "dias_proximos_morning", 
        "DIAS_PROXIMOS_AFTERNOON": "dias_proximos_afternoon",
        "PAGE_SIZE": "page_size",
        "MAX_RESPONSAVEIS_LOOKUP": "max_responsaveis_lookup",
        "USAR_FULL_SCAN": "usar_full_scan",
        "TIMEZONE": "timezone",
        "MAX_TAREFAS_POR_RESPONSAVEL": "max_tarefas_por_responsavel"
    }
    
    for env_var, config_key in env_mappings.items():
        env_value = os.getenv(env_var)
        if env_value is not None:
            # Converter tipos apropriados
            try:
                if config_key in ["usar_full_scan"]:
                    config[config_key] = env_value.lower() in ("true", "1", "yes")
                elif config_key in ["timezone"]:
                    config[config_key] = str(env_value)
                else:
                    config[config_key] = int(env_value)
                logger.info("🔧 Configuração %s sobrescrita por env var: %s", config_key, env_value)
            except ValueError as e:
                logger.warning("⚠️ Valor inválido para %s: %s (%s)", env_var, env_value, e)
    
    logger.info("⚙️ Configurações finais: %s", {k: v for k, v in config.items() if "password" not in k.lower()})
    return config

# =============================================================
# Classificação Temporal
# =============================================================

def classificar(tarefa: Dict[str, Any], hoje: date, dias_proximos: int) -> Optional[str]:
    """
    Classifica uma tarefa usando a lógica padronizada do classification.py.
    Mantém compatibilidade com a API interna existente.
    """
    try:
        # Usar a lógica padronizada de classification.py
        from engine.classification import classificar_tarefa_individual
        resultado = classificar_tarefa_individual(tarefa, hoje)
        
        # Mapear resultado padronizado para formato interno
        if resultado is None:
            return None
        elif resultado == "vencidas":
            return "vencidas"
        elif resultado == "vence_hoje":
            return "vence_hoje"
        elif resultado == "vence_em_3_dias":
            # Verificar se está dentro da janela de dias_proximos
            dt_txt = tarefa.get("dataVencimento")
            if dt_txt:
                try:
                    dt_venc = date.fromisoformat(dt_txt)
                    if dt_venc <= hoje + timedelta(days=dias_proximos):
                        return "vence_em_3_dias"
                except Exception:
                    pass
            return None
        else:
            return resultado
    except ImportError:
        # Fallback para lógica interna se classification.py não disponível
        logger.warning("classification.py não disponível, usando lógica interna")
        dt_txt = tarefa.get("dataVencimento")
        if not dt_txt:
            return None
        try:
            dt_venc = date.fromisoformat(dt_txt)
        except Exception:
            return None
        
        # Aplicar regra de filtro: ignorar atrasos > 1 dia
        if dt_venc < hoje - timedelta(days=1):
            return None
            
        if dt_venc < hoje:
            return "vencidas"
        if dt_venc == hoje:
            return "vence_hoje"
        if dt_venc <= hoje + timedelta(days=dias_proximos):
            return "vence_em_3_dias"
        return None

# =============================================================
# Agrupamento por Responsável
# =============================================================

def agrupar_por_responsavel(
    tarefas_relevantes: List[Dict[str, Any]],
    max_responsaveis_lookup: int = 100,
    sleep_ms: int = 0,
    verbose: bool = False
) -> Dict[str, List[Dict[str, Any]]]:
    grupos: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    consultados = 0
    for t in tarefas_relevantes:
        if consultados >= max_responsaveis_lookup:
            break
        t_id = str(t["id"])
        try:
            resp_list = listar_responsaveis_tarefa(t_id)
            if verbose:
                print(f"[RESP] tarefa={t_id} -> {len(resp_list)} responsável(is).")
            consultados += 1
            if sleep_ms > 0:
                time.sleep(sleep_ms / 1000.0)
            if not isinstance(resp_list, list):
                continue
            for r in resp_list:
                apelido = r.get("apelido") or r.get("nome") or f"resp_{r.get('id')}"
                grupos[apelido].append(t)
        except Exception as e:
            if verbose:
                print(f"[WARN] Falha ao buscar responsáveis tarefa={t_id}: {e}")
    return grupos

# =============================================================
# Formatação de Mensagens
# =============================================================

def formatar_mensagem_individual(apelido: str, buckets: Dict[str, List[Dict[str, Any]]], limite_detalhe: int = 5) -> Optional[str]:
    partes = ["*Resumo de obrigações*"]
    ordem = ["vencidas", "vence_hoje", "vence_em_3_dias"]
    titulos = {
        "vencidas": "VENCIDAS",
        "vence_hoje": "Vencem HOJE",
        "vence_em_3_dias": "Vencem em 3 dias"
    }
    total_listadas = 0
    for chave in ordem:
        lista = buckets.get(chave, [])
        if not lista:
            continue
        partes.append(f"\n**{titulos[chave]} ({len(lista)})**")
        for i, t in enumerate(lista):
            if i < limite_detalhe:
                partes.append(
                    f"- [{t['id']}] {t.get('nome') or t.get('titulo') or 'Tarefa'} (venc: {t['dataVencimento']}) → "
                    f"https://app.gclick.com.br/tarefas/{t['id']}"
                )
            else:
                partes.append(f"- {len(lista)-limite_detalhe} tarefa(s) adicionais.")
                break
        total_listadas += len(lista)
    if total_listadas == 0:
        return None
    return "\n".join(partes)

def formatar_resumo_global(grupos_buckets: Dict[str, Dict[str, List[Dict[str, Any]]]]) -> str:
    colaboradores = []
    total_ocorrencias = 0
    ids_distintas = set()
    for apelido, bucket in grupos_buckets.items():
        subtotal = sum(len(lst) for lst in bucket.values())
        if subtotal > 0:
            colaboradores.append(apelido)
            total_ocorrencias += subtotal
            for lst in bucket.values():
                for t in lst:
                    ids_distintas.add(t["id"])
    return (
        "*Resumo Geral de Obrigações*\n"
        f"- Colaboradores com pendências/destaques: **{len(colaboradores)}**\n"
        f"- Tarefas distintas destacadas: **{len(ids_distintas)}**\n"
        f"- Total de ocorrências (somando por responsável): **{total_ocorrencias}**"
    )

# =============================================================
# Coleta de Tarefas (Single Page ou Full Scan)
# =============================================================

def _coletar_tarefas_intervalo(
    categoria: str,
    inicio: date,
    fim: date,
    page_size: int,
    usar_full_scan: bool,
    max_pages: Optional[int],
    verbose: bool
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    tarefas: List[Dict[str, Any]] = []
    meta_final: Dict[str, Any] = {}
    if not usar_full_scan:
        page_tasks, meta = _cached_listar_tarefas_page(
            categoria=categoria,
            page=0,
            size=page_size,
            dataVencimentoInicio=inicio.isoformat(),
            dataVencimentoFim=fim.isoformat()
        )
        tarefas.extend(page_tasks)
        meta_final = meta
        if verbose:
            print(f"[COLETA] Página única -> {len(page_tasks)} tarefas.")
    else:
        if verbose:
            print("[COLETA] FULL SCAN iniciado...")
        page = 0
        while True:
            page_tasks, meta = _cached_listar_tarefas_page(
                categoria=categoria,
                page=page,
                size=page_size,
                dataVencimentoInicio=inicio.isoformat(),
                dataVencimentoFim=fim.isoformat()
            )
            tarefas.extend(page_tasks)
            meta_final = meta
            if verbose:
                print(f"  - page={page} obtidas={len(page_tasks)} last={meta.get('last')}")
            page += 1
            if meta.get("last"):
                break
            if max_pages is not None and page >= max_pages:
                if verbose:
                    print("[COLETA] max_pages atingido, interrompendo full scan.")
                break
        if verbose:
            print(f"[COLETA] FULL SCAN total coletado={len(tarefas)} páginas={page}")
    return tarefas, meta_final

# =============================================================
# Núcleo do Ciclo de Notificação (Nova API)
# =============================================================

@resilient(service="notification_cycle", check_rate_limit=True)
def run_notification_cycle(
    *,
    dias_proximos: int = None,  # Será definido por configuração se None
    categoria: str = "Obrigacao",
    usar_full_scan: bool = None,  # Será definido por configuração se None
    page_size: int = None,  # Será definido por configuração se None
    max_pages: Optional[int] = None,
    apenas_status_abertos: bool = True,
    max_responsaveis_lookup: int = None,  # Será definido por configuração se None
    limite_responsaveis_notificar: int = 50,
    detalhar_limite: int = None,  # Será definido por configuração se None
    enviar_resumo_global: bool = True,
    rate_limit_sleep_ms: int = 0,
    repetir_no_mesmo_dia: bool = False,
    execution_mode: str = 'dry_run',  # 'dry_run' ou 'live'
    run_id: Optional[str] = None,
    run_reason: str = 'manual',
    verbose: bool = False,
    registrar_metricas: bool = True,
    alertar_se_zero_abertos: bool = True,
) -> Dict[str, Any]:
    """
    Executa um ciclo de notificação e registra métricas padronizadas.
    Retorna dicionário com estatísticas principais.
    
    MELHORIAS P1:
    - Carrega configurações dinâmicas do YAML + env vars
    - Suporte a configurações separadas morning/afternoon
    - Corrige duplicação usando configuração baseada em contexto
    """
    start_ts = time.time()
    if run_id is None:
        run_id = new_run_id('notify')

    # Carregar configurações dinâmicas
    config = load_notifications_config()
    
    # Detectar contexto baseado no run_reason para configurações específicas
    if run_reason.startswith("scheduled_morning"):
        dias_proximos_key = "dias_proximos_morning"
        context = "morning"
    elif run_reason.startswith("scheduled_afternoon"):
        dias_proximos_key = "dias_proximos_afternoon"  
        context = "afternoon"
    else:
        dias_proximos_key = "dias_proximos"
        context = "manual"
    
    # Aplicar configurações com fallbacks
    if dias_proximos is None:
        dias_proximos = config.get(dias_proximos_key, config.get("dias_proximos", 3))
    if usar_full_scan is None:
        usar_full_scan = config.get("usar_full_scan", True)
    if page_size is None:
        page_size = config.get("page_size", 200)
    if max_responsaveis_lookup is None:
        max_responsaveis_lookup = config.get("max_responsaveis_lookup", 100)
    if detalhar_limite is None:
        detalhar_limite = config.get("max_tarefas_por_responsavel", 5)

    logger.info("🎛️ Configurações aplicadas - contexto=%s, dias_proximos=%d, full_scan=%s",
                context, dias_proximos, usar_full_scan)

    # CORREÇÃO CRÍTICA: Usar timezone BRT e incluir 1 dia de atraso
    hoje = obter_data_atual_brt() if HAS_ADVANCED_FEATURES else date.today()
    t_inicio = hoje - timedelta(days=1)  # ← CORREÇÃO: incluir tarefas vencidas ontem
    t_fim = hoje + timedelta(days=dias_proximos)

    logger.info("🕒 Coletando tarefas de %s a %s (BRT) - inclui 1 dia atraso", t_inicio, t_fim)
    logger.info("🔍 Janela: ontem + hoje + próximos %d dias (contexto: %s)", dias_proximos, context)

    # 1. Coleta
    tarefas, meta = _coletar_tarefas_intervalo(
        categoria=categoria,
        inicio=t_inicio,
        fim=t_fim,
        page_size=page_size,
        usar_full_scan=usar_full_scan,
        max_pages=max_pages,
        verbose=verbose
    )

    if verbose:
        print(f"[DEBUG] Coletadas {len(tarefas)} tarefas (janela {t_inicio} -> {t_fim}) meta={meta}")

    # 2. Filtragem status abertos (client-side)
    if apenas_status_abertos:
        tarefas_filtradas = [t for t in tarefas if t.get("status") in STATUS_ABERTOS]
    else:
        tarefas_filtradas = list(tarefas)

    if verbose:
        print(f"[DEBUG] Após filtro status abertos={apenas_status_abertos}: {len(tarefas_filtradas)}")

    # 3. Separação de tarefas normais e overdue (se disponível)
    tarefas_normalizadas = [normalizar_tarefa(t) for t in tarefas_filtradas]
    
    if HAS_ADVANCED_FEATURES:
        separacao = separar_tarefas_overdue(tarefas_normalizadas, hoje)
        tarefas_para_notificacao = separacao["normais"]
        tarefas_overdue = separacao["overdue"]
        
        # Gerar relatório Excel para tarefas com muito atraso
        if tarefas_overdue and execution_mode == 'live':
            try:
                relatorio_path = gerar_relatorio_excel_overdue(
                    tarefas_overdue, 
                    output_dir="reports/exports",
                    hoje=hoje
                )
                logging.info("📊 Relatório Excel gerado: %s (%d tarefas)", 
                           relatorio_path, len(tarefas_overdue))
            except Exception as excel_err:
                logging.error("❌ Falha ao gerar relatório Excel: %s", excel_err)
        
        if verbose:
            print(f"[DEBUG] Separação - Normais: {len(tarefas_para_notificacao)}, "
                  f"Overdue: {len(tarefas_overdue)}")
    else:
        tarefas_para_notificacao = tarefas_normalizadas
        tarefas_overdue = []

    # 4. Classificação das tarefas normais
    buckets_globais = {"vencidas": [], "vence_hoje": [], "vence_em_3_dias": []}
    for nt in tarefas_para_notificacao:
        cls = classificar(nt, hoje, dias_proximos)
        if cls:
            buckets_globais[cls].append(nt)

    relevantes = buckets_globais["vencidas"] + buckets_globais["vence_hoje"] + buckets_globais["vence_em_3_dias"]
    if verbose:
        print("[INFO] Classificação:", {k: len(v) for k, v in buckets_globais.items()}, 
              "relevantes=", len(relevantes))
        if tarefas_overdue:
            print(f"[INFO] Tarefas overdue (relatório): {len(tarefas_overdue)}")

    # 5. Agrupamento de responsáveis
    grupos_resps = agrupar_por_responsavel(
        relevantes,
        max_responsaveis_lookup=max_responsaveis_lookup,
        sleep_ms=rate_limit_sleep_ms,
        verbose=verbose
    )

    # 5. Reclassificação por responsável (para contagens independentemente)
    grupos_buckets: Dict[str, Dict[str, List[Dict[str, Any]]]] = {}
    for apelido, tarefas_lista in grupos_resps.items():
        b = {"vencidas": [], "vence_hoje": [], "vence_em_3_dias": []}
        for t in tarefas_lista:
            cls = classificar(t, hoje, dias_proximos)
            if cls:
                b[cls].append(t)
        grupos_buckets[apelido] = b

    responsaveis_ordenados = sorted(
        grupos_buckets.items(),
        key=lambda kv: sum(len(lst) for lst in kv[1].values()),
        reverse=True
    )[:limite_responsaveis_notificar]

    purge_older_than(days=7)

    # 6. NOVA IDEMPOTÊNCIA: Filtro granular por tarefa/responsável/dia
    state_storage = get_global_state_storage()
    mensagens_enviadas: List[Tuple[str, str, str]] = []
    envios_para_marcar: List[Tuple[str, bool]] = []
    
    for apelido, bkt in responsaveis_ordenados:
        total_resp = sum(len(lst) for lst in bkt.values())
        if total_resp == 0:
            continue
        
        # APLICAR FILTRO GRANULAR: remove tarefas já enviadas hoje
        if not repetir_no_mesmo_dia:
            bkt_filtrado = aplicar_filtro_idempotencia(bkt, apelido, hoje, state_storage)
            if not bkt_filtrado:
                if verbose:
                    print(f"[SKIP] Todas as tarefas já foram notificadas hoje: {apelido}")
                continue
        else:
            # Se repetir_no_mesmo_dia=True, converte formato para compatibilidade
            bkt_filtrado = {
                nome: [(tarefa, criar_chave_idempotencia(str(tarefa.get("id", "")), apelido, hoje)) 
                       for tarefa in lista]
                for nome, lista in bkt.items()
            }
        
        # Construir mensagem com tarefas filtradas
        bkt_para_msg = {nome: [item[0] for item in lista] for nome, lista in bkt_filtrado.items()}
        msg = formatar_mensagem_individual(apelido, bkt_para_msg, limite_detalhe=detalhar_limite)
        if not msg:
            continue
            
        # Preparar para envio
        mensagens_enviadas.append((apelido, msg, bkt_filtrado))

    resumo_global_msg = formatar_resumo_global(grupos_buckets) if enviar_resumo_global else None

    # 7. Envio ou Dry-run
    if execution_mode == 'dry_run':
        print(f"[INFO] DRY-RUN run_id={run_id} – Mensagens preparadas:")
        if resumo_global_msg:
            print("----\n[RESUMO GLOBAL]\n" + resumo_global_msg)
        for apelido, key, msg in mensagens_enviadas:
            print("----")
            print(f"[{apelido}]\n{msg}")
        print(f"[INFO] DRY-RUN concluído. (responsáveis selecionados={len(mensagens_enviadas)})")
    else:
        # Primeiro, envia o resumo global (opcional)
        if resumo_global_msg:
            try:
                if bot_sender:
                    # Envie para um canal específico ou admin, se quiser, usando o bot.
                    logging.info("[BOT] Resumo global pronto para envio (adapte para enviar em canal, se desejar).")
                else:
                    enviar_teams_mensagem(resumo_global_msg)
            except Exception as e:
                print(f"[WARN] Falha envio resumo global: {e}")
        
        # Depois, envia individualmente com nova idempotência:
        for apelido, msg, bkt_filtrado in mensagens_enviadas:
            envios_realizados_responsavel = []
            
            try:
                mensagem_enviada = False
                
                # Tenta enviar via bot primeiro (se disponível)
                if bot_sender:
                    teams_id = mapear_apelido_para_teams_id(apelido)
                    if teams_id and _has_conversation(bot_sender.conversation_storage, teams_id):
                        try:
                            # Enviar um card por tarefa com nova estrutura
                            for categoria_urgencia, lista_tarefas_chaves in bkt_filtrado.items():
                                for tarefa, chave in lista_tarefas_chaves:
                                    try:
                                        # Dados do responsável para o card
                                        responsavel_dados = {"nome": apelido, "apelido": apelido}
                                        
                                        # Criar card da tarefa
                                        card_json_str = create_task_notification_card(tarefa, responsavel_dados)
                                        card_payload = _ensure_card_payload(card_json_str)
                                        
                                        # Texto de fallback
                                        fallback_text = (
                                            f"🔔 Obrigação: {tarefa.get('nome', 'Sem nome')} "
                                            f"(Venc: {tarefa.get('dataVencimento', 'N/A')})"
                                        )
                                        
                                        # Enviar card de forma assíncrona com resilience
                                        import asyncio
                                        loop = asyncio.get_event_loop()
                                        if loop.is_running():
                                            asyncio.ensure_future(_resilient_send_card(bot_sender, teams_id, card_payload, fallback_text))
                                        else:
                                            loop.run_until_complete(_resilient_send_card(bot_sender, teams_id, card_payload, fallback_text))
                                        
                                        # Marcar como enviado com sucesso
                                        envios_realizados_responsavel.append((chave, True))
                                        logging.info(f"[BOT-CARD] ✅ Enviado para {apelido} (tarefa: {tarefa.get('id')})")
                                        
                                    except Exception as card_error:
                                        envios_realizados_responsavel.append((chave, False))
                                        logging.warning(f"[BOT-CARD] ❌ Falha para {apelido} tarefa {tarefa.get('id')}: {card_error}")
                            
                            mensagem_enviada = True
                            logging.info(f"[BOT] ✅ Cards enviados para {apelido} (teams_id: {teams_id})")
                        except Exception as bot_error:
                            logging.warning(f"[BOT] ❌ Falha geral para {apelido}: {bot_error}")
                
                # Fallback para webhook se bot falhou ou não está disponível
                if not mensagem_enviada:
                    try:
                        enviar_teams_mensagem(f"{apelido}:\n{msg}")
                        # Se webhook teve sucesso, marcar todas as chaves como enviadas
                        for categoria_urgencia, lista_tarefas_chaves in bkt_filtrado.items():
                            for tarefa, chave in lista_tarefas_chaves:
                                envios_realizados_responsavel.append((chave, True))
                        logging.info(f"[WEBHOOK] ✅ Enviado para {apelido}")
                    except Exception as webhook_error:
                        logging.error(f"[WEBHOOK] ❌ Falha para {apelido}: {webhook_error}")
                        # Marcar como falha
                        for categoria_urgencia, lista_tarefas_chaves in bkt_filtrado.items():
                            for tarefa, chave in lista_tarefas_chaves:
                                envios_realizados_responsavel.append((chave, False))
                
                # NOVA LÓGICA: Marcar como enviado apenas os sucessos
                marcar_envios_bem_sucedidos(envios_realizados_responsavel, state_storage)
                
                if verbose:
                    sucessos = sum(1 for _, sucesso in envios_realizados_responsavel if sucesso)
                    total = len(envios_realizados_responsavel)
                    print(f"[ENVIADO] {apelido} - {sucessos}/{total} tarefas enviadas com sucesso")
                    
                if rate_limit_sleep_ms > 0:
                    time.sleep(rate_limit_sleep_ms / 1000.0)
                    
            except Exception as e:
                print(f"[ERRO_ENVIO] {apelido}: {e}")
                logging.error(f"[ERRO_ENVIO] {apelido}: {e}")
                # Em caso de erro geral, marcar todas como falha
                for categoria_urgencia, lista_tarefas_chaves in bkt_filtrado.items():
                    for tarefa, chave in lista_tarefas_chaves:
                        envios_realizados_responsavel.append((chave, False))
                if verbose:
                    print(f"[ENVIADO] {apelido} ({key})")
                if rate_limit_sleep_ms > 0:
                    time.sleep(rate_limit_sleep_ms / 1000.0)
            except Exception as e:
                print(f"[ERRO_ENVIO] {apelido}: {e}")
                logging.error(f"[ERRO_ENVIO] {apelido}: {e}")

    # 8. Estatísticas finais
    counts_final = {
        "vencidas": len(buckets_globais["vencidas"]),
        "vence_hoje": len(buckets_globais["vence_hoje"]),
        "vence_em_3_dias": len(buckets_globais["vence_em_3_dias"]),
        "responsaveis_selecionados": len(mensagens_enviadas)
    }

    total_abertos_brutos = sum(1 for t in tarefas if t.get("status") in STATUS_ABERTOS)
    total_fechados_brutos = len(tarefas) - total_abertos_brutos
    zero_abertos = apenas_status_abertos and total_abertos_brutos == 0

    duration = round(time.time() - start_ts, 2)

    # 9. Métricas padronizadas
    if registrar_metricas:
        stats = {
            'tasks_total_raw': len(tarefas),
            'tasks_open_after_filter': len(tarefas_filtradas),
            'tasks_vencidas': counts_final['vencidas'],
            'tasks_vence_hoje': counts_final['vence_hoje'],
            'tasks_vence_proximos': counts_final['vence_em_3_dias'],
            'duration_seconds': duration,
            'zero_abertos_flag': zero_abertos,
        }
        responsaveis_stats = {
            'total_distintos': len(grupos_buckets),
            'notificados_individuais': len(mensagens_enviadas),
            'supervisores_resumo': 1,  # Ajustar quando houver hierarquia real
        }
        limits_stats = {
            'responsaveis_limit_reached': len(grupos_buckets) > limite_responsaveis_notificar,
        }
        write_notification_cycle(
            run_id=run_id,
            execution_mode=execution_mode,
            cycle_date=hoje.isoformat(),
            window_days=dias_proximos,
            stats=stats,
            responsaveis=responsaveis_stats,
            limits=limits_stats,
            extra={'reason': run_reason, 'full_scan': usar_full_scan}
        )

    # 10. Alerta zero abertos
    if alertar_se_zero_abertos and zero_abertos:
        msg_warn = (f"[WARN] Nenhuma tarefa aberta detectada na janela {t_inicio}->{t_fim} "
                    f"(coletadas={len(tarefas)}). Pode ser período pós-fechamento.")
        print(msg_warn)
        if ALERT_ZERO_ABERTOS_TO_TEAMS and execution_mode == 'live':
            try:
                enviar_teams_mensagem(msg_warn)
            except Exception as e:
                print(f"[WARN] Falha ao enviar alerta ZERO_ABERTOS: {e}")

    meta_cycle = {
        "janela": (t_inicio.isoformat(), t_fim.isoformat()),
        "tarefas_coletadas": len(tarefas),
        "abertos_brutos": total_abertos_brutos,
        "fechados_brutos": total_fechados_brutos,
        "full_scan": usar_full_scan,
        "duration_s": duration,
        "run_id": run_id,
        "execution_mode": execution_mode,
    }

    return {
        "run_id": run_id,
        "execution_mode": execution_mode,
        "counts": counts_final,
        "responsaveis": [a for a, _, _ in mensagens_enviadas],
        "resumo_global_incluido": bool(resumo_global_msg),
        "meta_cycle": meta_cycle,
        "open_after_filter": len(tarefas_filtradas),
        "total_raw": len(tarefas),
    }

# =============================================================
# Wrapper de Compatibilidade (API antiga)
# =============================================================

def ciclo_notificacao(
    dias_proximos: int = 3,
    page_size: int = 200,
    categoria: str = "Obrigacao",
    max_responsaveis_lookup: int = 100,
    limite_responsaveis_notificar: int = 50,
    repetir_no_mesmo_dia: bool = False,
    detalhar_limite: int = 5,
    enviar_resumo_global: bool = True,
    rate_limit_sleep_ms: int = 0,
    dry_run: bool = True,
    verbose: bool = False,
    considerar_somente_abertos: bool = True,
    registrar_metricas: bool = True,
    alertar_se_zero_abertos: bool = True,
    usar_full_scan: bool = True,
    max_pages: Optional[int] = None,
    apenas_status_abertos: bool = True,  # alias para considerar_somente_abertos
    **_unused,
) -> Dict[str, Any]:
    return run_notification_cycle(
        dias_proximos=dias_proximos,
        categoria=categoria,
        usar_full_scan=usar_full_scan,
        page_size=page_size,
        max_pages=max_pages,
        apenas_status_abertos=apenas_status_abertos and considerar_somente_abertos,
        max_responsaveis_lookup=max_responsaveis_lookup,
        limite_responsaveis_notificar=limite_responsaveis_notificar,
        detalhar_limite=detalhar_limite,
        enviar_resumo_global=enviar_resumo_global,
        rate_limit_sleep_ms=rate_limit_sleep_ms,
        repetir_no_mesmo_dia=repetir_no_mesmo_dia,
        execution_mode='dry_run' if dry_run else 'live',
        verbose=verbose,
        registrar_metricas=registrar_metricas,
        alertar_se_zero_abertos=alertar_se_zero_abertos,
        run_reason='legacy_wrapper'
    )


def run_cycle(simulacao: bool = False):
    """
    Wrapper para compatibilidade com Azure Function.
    
    Args:
        simulacao: Se True, executa em modo dry_run sem enviar notificações reais
        
    Returns:
        Dict com resultados do ciclo de notificação
    """
    modo = "dry_run" if simulacao else "live"
    return run_notification_cycle(
        execution_mode=modo,
        run_reason="azure_function",
        registrar_metricas=True,
        alertar_se_zero_abertos=True,
        verbose=True
    )