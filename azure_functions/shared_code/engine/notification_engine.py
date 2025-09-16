import os
import time
import json
import logging
from datetime import date, timedelta
from collections import defaultdict
from typing import Dict, List, Any, Tuple, Optional

import yaml

# Imports relativos para módulos locais
from ..gclick.tarefas import listar_tarefas_page, normalizar_tarefa
from ..gclick.tarefas_detalhes import obter_tarefa_detalhes, resumir_detalhes_para_card # type: ignore
from ..gclick.responsaveis import listar_responsaveis_tarefa
from ..teams.webhook import enviar_teams_mensagem
from ..storage.state import purge_older_than
# NOVA API: Idempotência granular
from ..storage.state import (
    get_global_state_storage,
    aplicar_filtro_idempotencia,
    marcar_envios_bem_sucedidos,
    criar_chave_idempotencia,
)

# ===================== LOGGER =====================
logger = logging.getLogger(__name__)

# ============ Resilience & Cache (opcional) ========
try:
    from .cache import IntelligentCache
    from .resilience import resilient, resilience_manager
    HAS_RESILIENCE = True
    notification_cache = IntelligentCache(max_size=1000, default_ttl=300)
except ImportError as e:
    logger.warning("Sistema de resilience não disponível: %s", e)
    HAS_RESILIENCE = False
    notification_cache = None

    def resilient(service: str = "default", check_rate_limit: bool = True):
        def decorator(func):
            return func
        return decorator

# ======= Funcionalidades avançadas (opcional) ======
try:
    from .classification import separar_tarefas_overdue, obter_data_atual_brt
    from ..reports.overdue_report import gerar_relatorio_excel_overdue
    HAS_ADVANCED_FEATURES = True
except ImportError as e:
    logger.warning("Funcionalidades avançadas não disponíveis: %s", e)
    HAS_ADVANCED_FEATURES = False

# ======= Deep-link G-Click (com fallback local) =====
try:
    # Preferência por helper compartilhado quando disponível neste ambiente
    from ..utils.gclick_links import montar_link_gclick_obrigacao, EMPRESA_ID_PADRAO  # type: ignore
except Exception:
    EMPRESA_ID_PADRAO = int(os.getenv("GCLICK_EMPRESA_ID", "2557"))

    def montar_link_gclick_obrigacao(task_id: str, empresa_id: int = EMPRESA_ID_PADRAO) -> str:
        """
        Fallback simples: tenta montar coListar.do quando id vem no formato 'X.YYYY'.
        Caso contrário, usa link genérico (melhor do que quebrar).
        """
        tid = str(task_id or "").strip()
        coid, eveid = None, None
        if "." in tid:
            left, right = tid.split(".", 1)
            if left.isdigit() and right.isdigit():
                coid, eveid = left, right
        if coid and eveid:
            return f"https://app.gclick.com.br/coListar.do?obj=coevento&coid={coid}&eveId={eveid}&empId={empresa_id}"
        # fallback genérico
        return f"https://app.gclick.com.br/tarefas/{tid}"

# ==================== Helpers ======================

def _cached_listar_tarefas_page(categoria: str, page: int, size: int,
                                dataVencimentoInicio: str = None,
                                dataVencimentoFim: str = None):
    """Wrapper com cache para listar_tarefas_page."""
    if not HAS_RESILIENCE or not notification_cache:
        return listar_tarefas_page(categoria, page, size, dataVencimentoInicio, dataVencimentoFim)

    cache_key = f"tarefas:{categoria}:{page}:{size}:{dataVencimentoInicio}:{dataVencimentoFim}"
    cached_result = notification_cache.get(cache_key)
    if cached_result is not None:
        logger.debug("🎯 Cache HIT tarefas (page=%d, size=%d)", page, size)
        return cached_result

    result = listar_tarefas_page(categoria, page, size, dataVencimentoInicio, dataVencimentoFim)
    notification_cache.set(cache_key, result, ttl=300)
    logger.debug("💾 Cache MISS tarefas (page=%d, size=%d) - armazenado", page, size)
    return result


def _cached_obter_detalhes(task_id: str, *, ttl: int = 600) -> Dict[str, Any]:
    """Busca detalhes da tarefa com cache (10 min por padrão) e retorna resumo para card."""
    if not HAS_RESILIENCE or not notification_cache:
        raw = obter_tarefa_detalhes(task_id)
        return resumir_detalhes_para_card(raw)

    cache_key = f"detalhes:{task_id}"
    cached = notification_cache.get(cache_key)
    if cached is not None:
        logger.debug("🎯 Cache HIT detalhes %s", task_id)
        return cached

    raw = obter_tarefa_detalhes(task_id)
    resumo = resumir_detalhes_para_card(raw)
    try:
        notification_cache.set(cache_key, resumo, ttl=ttl)
    except Exception:
        logger.debug("Falha ao setar cache detalhes %s", task_id, exc_info=True)
    return resumo


@resilient(service="teams_bot", check_rate_limit=False)
async def _resilient_send_card(bot_sender, teams_id: str, card_payload: dict, fallback_text: str):
    """Wrapper com resilience para envio de cards."""
    if not HAS_RESILIENCE:
        return await bot_sender.send_card(teams_id, card_payload, fallback_text)
    result = await bot_sender.send_card(teams_id, card_payload, fallback_text)
    logger.debug("📤 Card enviado com sucesso para %s", teams_id)
    return result


def _ensure_card_payload(card) -> dict:
    """Garante que o payload do card seja dict (Teams/Bot esperam dict)."""
    if isinstance(card, str):
        try:
            return json.loads(card)
        except Exception:
            logging.warning("[CARD] Payload string não-JSON; usando fallback.")
            return {"type": "AdaptiveCard", "version": "1.3"}
    return card


def _run_coro_safely(coro):
    """Executa uma coroutine em qualquer thread (cria loop se necessário)."""
    import asyncio
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(coro)
        return True
    except RuntimeError:
        return asyncio.run(coro)


def _has_conversation(storage, user_id: str) -> bool:
    """Verifica, de forma tolerante, se há reference salva para o usuário."""
    if storage is None or not user_id:
        return False

    for method in ("get", "has", "exists", "contains"):
        if hasattr(storage, method):
            fn = getattr(storage, method)
            try:
                res = fn(user_id)
                if isinstance(res, bool):
                    return res
                return bool(res)
            except TypeError:
                try:
                    res = fn(user_id, None)  # type: ignore
                    return bool(res)
                except Exception:
                    pass
            except Exception:
                pass

    for attr in ("_conversations", "references", "_data"):
        if hasattr(storage, attr):
            raw = getattr(storage, attr)
            if isinstance(raw, dict):
                return user_id in raw
    return False


# Métricas (fallbacks)
try:
    from ..analytics.metrics import write_notification_cycle, new_run_id
except ImportError:
    def write_notification_cycle(**_k):  # type: ignore
        pass
    def new_run_id(prefix: str = 'run'):  # type: ignore
        return f"{prefix}_dummy"


# =================== Integração Bot ==================
bot_sender = None
try:
    # Não precisamos importar BotSender aqui; o function_app injeta bot_sender neste módulo.
    from ..teams.user_mapping import mapear_apelido_para_teams_id
    logging.info("[ENGINE] Mapeador de usuário do Teams disponível")
except ImportError as e:
    logging.warning(f"[BOT] Falha ao importar user_mapping: {e}")
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

# ====================== Config ======================

def load_notifications_config(path="config/notifications.yaml") -> dict:
    default_config = {
        "dias_proximos": 3,
        "dias_proximos_morning": 3,
        "dias_proximos_afternoon": 1,
        "page_size": 50,
        "max_responsaveis_lookup": 100,
        "usar_full_scan": True,
        "timezone": "America/Sao_Paulo",
        "max_tarefas_por_responsavel": 5,
    }

    yaml_config = {}
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                yaml_config = yaml.safe_load(f) or {}
            logger.info("✅ Config YAML carregada de %s", path)
        except Exception as e:
            logger.warning("⚠️ Erro ao carregar YAML %s: %s", path, e)

    config = {**default_config, **yaml_config}

    # Detect common typos / unknown keys and warn developers early.
    expected_top_keys = {"notifications", "defaults"}
    unknown = set(yaml_config.keys()) - expected_top_keys
    if unknown:
        logging.warning(
            "Config de notificações contém chaves desconhecidas: %s. "
            "Verifique por erros de digitação como 'dias_proxximos' (deveria ser 'dias_proximos').",
            ", ".join(sorted(unknown)),
        )

    env_mappings = {
        "DIAS_PROXIMOS": "dias_proximos",
        "DIAS_PROXIMOS_MORNING": "dias_proximos_morning",
        "DIAS_PROXIMOS_AFTERNOON": "dias_proximos_afternoon",
        "PAGE_SIZE": "page_size",
        "MAX_RESPONSAVEIS_LOOKUP": "max_responsaveis_lookup",
        "USAR_FULL_SCAN": "usar_full_scan",
        "TIMEZONE": "timezone",
        "MAX_TAREFAS_POR_RESPONSAVEL": "max_tarefas_por_responsavel",
    }

    for env_var, config_key in env_mappings.items():
        env_value = os.getenv(env_var)
        if env_value is not None:
            try:
                if config_key in ["usar_full_scan"]:
                    config[config_key] = env_value.lower() in ("true", "1", "yes")
                elif config_key in ["timezone"]:
                    config[config_key] = str(env_value)
                else:
                    config[config_key] = int(env_value)
                logger.info("🔧 %s sobrescrito por env: %s", config_key, env_value)
            except ValueError as e:
                logger.warning("⚠️ Valor inválido %s=%s (%s)", env_var, env_value, e)

    logger.info("⚙️ Config finais: %s", {k: v for k, v in config.items() if "password" not in k.lower()})
    return config


# ================= Classificação Temporal ================

def classificar(tarefa: Dict[str, Any], hoje: date, dias_proximos: int) -> Optional[str]:
    try:
        from .classification import classificar_tarefa_individual
        resultado = classificar_tarefa_individual(tarefa, hoje)
        if resultado is None:
            return None
        if resultado == "vencidas":
            return "vencidas"
        if resultado == "vence_hoje":
            return "vence_hoje"
        if resultado == "vence_em_3_dias":
            dt_txt = tarefa.get("dataVencimento")
            if dt_txt:
                try:
                    dt_venc = date.fromisoformat(dt_txt)
                    if dt_venc <= hoje + timedelta(days=dias_proximos):
                        return "vence_em_3_dias"
                except Exception:
                    pass
            return None
        return resultado
    except ImportError:
        logger.warning("classification.py não disponível, usando lógica interna")
        dt_txt = tarefa.get("dataVencimento")
        if not dt_txt:
            return None
        try:
            dt_venc = date.fromisoformat(dt_txt)
        except Exception:
            return None
        if dt_venc < hoje - timedelta(days=1):
            return None
        if dt_venc < hoje:
            return "vencidas"
        if dt_venc == hoje:
            return "vence_hoje"
        if dt_venc <= hoje + timedelta(days=dias_proximos):
            return "vence_em_3_dias"
        return None


# ================= Agrupamento por Responsável ================

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


# ===================== Formatação de Mensagens =====================

def formatar_mensagem_individual(apelido: str, buckets: Dict[str, List[Dict[str, Any]]], limite_detalhe: int = 5) -> Optional[str]:
    partes = ["*Resumo de obrigações*"]
    ordem = ["vencidas", "vence_hoje", "vence_em_3_dias"]
    titulos = {
        "vencidas": "VENCIDAS",
        "vence_hoje": "Vencem HOJE",
        "vence_em_3_dias": "Vencem em 3 dias",
    }
    total_listadas = 0
    for chave in ordem:
        lista = buckets.get(chave, [])
        if not lista:
            continue
        partes.append(f"\n**{titulos[chave]} ({len(lista)})**")
        for i, t in enumerate(lista):
            if i < limite_detalhe:
                tid = str(t.get("id"))
                link = montar_link_gclick_obrigacao(tid, EMPRESA_ID_PADRAO)
                partes.append(
                    f"- [{tid}] {t.get('nome') or t.get('titulo') or 'Tarefa'} "
                    f"(venc: {t.get('dataVencimento')}) → {link}"
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


# ===================== Coleta de Tarefas =====================

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


# ===================== Núcleo do Ciclo =====================

@resilient(service="notification_cycle", check_rate_limit=True)
def run_notification_cycle(
    *,
    dias_proximos: int = None,
    categoria: str = "Obrigacao",
    usar_full_scan: bool = None,
    page_size: int = None,
    max_pages: Optional[int] = None,
    apenas_status_abertos: bool = True,
    max_responsaveis_lookup: int = None,
    limite_responsaveis_notificar: int = 50,
    detalhar_limite: int = None,
    enviar_resumo_global: bool = True,
    rate_limit_sleep_ms: int = 0,
    repetir_no_mesmo_dia: bool = False,
    execution_mode: str = 'dry_run',
    run_id: Optional[str] = None,
    run_reason: str = 'manual',
    verbose: bool = False,
    registrar_metricas: bool = True,
    alertar_se_zero_abertos: bool = True,
    timeout: Optional[int] = None,
) -> Dict[str, Any]:
    start_ts = time.time()
    if run_id is None:
        run_id = new_run_id('notify')

    config = load_notifications_config()

    if run_reason.startswith("scheduled_morning"):
        dias_proximos_key = "dias_proximos_morning"
        context = "morning"
    elif run_reason.startswith("scheduled_afternoon"):
        dias_proximos_key = "dias_proximos_afternoon"
        context = "afternoon"
    else:
        dias_proximos_key = "dias_proximos"
        context = "manual"

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

    logger.info("🎛️ Config aplicadas - contexto=%s, dias_proximos=%d, full_scan=%s",
                context, dias_proximos, usar_full_scan)
    if timeout is not None:
        logger.warning("⚠️ Deprecation warning: 'timeout' kwarg is accepted for backwards compatibility.")

    hoje = obter_data_atual_brt() if HAS_ADVANCED_FEATURES else date.today()
    t_inicio = hoje - timedelta(days=1)
    t_fim = hoje + timedelta(days=dias_proximos)

    logger.info("🕒 Coletando tarefas de %s a %s (BRT – inclui 1 dia de atraso)", t_inicio, t_fim)

    # 1) Coleta
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

    # 2) Filtro de status
    tarefas_filtradas = [t for t in tarefas if t.get("status") in STATUS_ABERTOS] if apenas_status_abertos else list(tarefas)
    if verbose:
        print(f"[DEBUG] Após filtro status abertos={apenas_status_abertos}: {len(tarefas_filtradas)}")

    # 3) Overdue split (opcional)
    tarefas_normalizadas = [normalizar_tarefa(t) for t in tarefas_filtradas]
    if HAS_ADVANCED_FEATURES:
        separacao = separar_tarefas_overdue(tarefas_normalizadas, hoje)
        tarefas_para_notificacao = separacao["normais"]
        tarefas_overdue = separacao["overdue"]
        if tarefas_overdue and execution_mode == 'live':
            try:
                relatorio_path = gerar_relatorio_excel_overdue(
                    tarefas_overdue,
                    output_dir="reports/exports",
                    hoje=hoje
                )
                logging.info("📊 Relatório Excel gerado: %s (%d tarefas)", relatorio_path, len(tarefas_overdue))
            except Exception as excel_err:
                logging.error("❌ Falha ao gerar relatório Excel: %s", excel_err)
        if verbose:
            print(f"[DEBUG] Separação - Normais: {len(tarefas_para_notificacao)}, Overdue: {len(tarefas_overdue)}")
    else:
        tarefas_para_notificacao = tarefas_normalizadas

    # 4) Classificação
    buckets_globais = {"vencidas": [], "vence_hoje": [], "vence_em_3_dias": []}
    for nt in tarefas_para_notificacao:
        cls = classificar(nt, hoje, dias_proximos)
        if cls:
            buckets_globais[cls].append(nt)

    relevantes = buckets_globais["vencidas"] + buckets_globais["vence_hoje"] + buckets_globais["vence_em_3_dias"]
    if verbose:
        print("[INFO] Classificação:", {k: len(v) for k, v in buckets_globais.items()}, "relevantes=", len(relevantes))

    # 5) Agrupamento por responsável
    grupos_resps = agrupar_por_responsavel(
        relevantes,
        max_responsaveis_lookup=max_responsaveis_lookup,
        sleep_ms=rate_limit_sleep_ms,
        verbose=verbose
    )

    # 5b) Reclassificar por responsável
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

    # 6) Idempotência granular
    state_storage = get_global_state_storage()
    mensagens_enviadas: List[Tuple[str, str, Dict[str, List[Tuple[Dict[str, Any], str]]]]] = []

    for apelido, bkt in responsaveis_ordenados:
        total_resp = sum(len(lst) for lst in bkt.values())
        if total_resp == 0:
            continue

        if not repetir_no_mesmo_dia:
            bkt_filtrado = aplicar_filtro_idempotencia(bkt, apelido, hoje, state_storage)
            if not bkt_filtrado:
                if verbose:
                    logger.debug("[SKIP] Todas as tarefas já foram notificadas hoje: %s", apelido)
                continue
        else:
            bkt_filtrado = {
                nome: [(tarefa, criar_chave_idempotencia(str(tarefa.get("id", "")), apelido, hoje))
                       for tarefa in lista]
                for nome, lista in bkt.items()
            }

        bkt_para_msg = {nome: [item[0] for item in lista] for nome, lista in bkt_filtrado.items()}
        msg = formatar_mensagem_individual(apelido, bkt_para_msg, limite_detalhe=detalhar_limite)
        if not msg:
            continue

        mensagens_enviadas.append((apelido, msg, bkt_filtrado))

    resumo_global_msg = formatar_resumo_global(grupos_buckets) if enviar_resumo_global else None

    # 7) Envio
    if execution_mode == 'dry_run':
        logger.info("DRY-RUN run_id=%s – Mensagens preparadas", run_id)
        if resumo_global_msg:
            logger.info("[RESUMO GLOBAL]\n%s", resumo_global_msg)
        for apelido, msg, _bkt in mensagens_enviadas:
            logger.info("----")
            logger.info("[%s]\n%s", apelido, msg)
        logger.info("DRY-RUN concluído. (responsáveis selecionados=%d)", len(mensagens_enviadas))
    else:
        if resumo_global_msg:
            try:
                if bot_sender:
                    logger.info("[BOT] Resumo global pronto para envio (adapte canal/alvo).")
                else:
                    enviar_teams_mensagem(resumo_global_msg)
            except Exception as e:
                logger.warning("Falha envio resumo global: %s", e)

        # Import tardio do card para evitar ciclos/ImportError prematuro
        try:
            from ..teams.cards import create_task_notification_card  # type: ignore
        except Exception as imp_err:
            logging.error("❌ Falha ao importar create_task_notification_card: %s", imp_err, exc_info=True)
            create_task_notification_card = None  # type: ignore

        for apelido, msg, bkt_filtrado in mensagens_enviadas:
            envios_realizados_responsavel: List[Tuple[str, bool]] = []
            try:
                mensagem_enviada = False

                if bot_sender:
                    teams_id = mapear_apelido_para_teams_id(apelido)
                    if teams_id and _has_conversation(getattr(bot_sender, "conversation_storage", None), teams_id):
                        try:
                            for _categoria, lista_tarefas_chaves in bkt_filtrado.items():
                                for tarefa, chave in lista_tarefas_chaves:
                                    try:
                                        responsavel_dados = {"nome": apelido, "apelido": apelido}

                                        # Detalhes compactos
                                        task_id_txt = str(tarefa.get("id") or tarefa.get("taskId") or "")
                                        detalhes_compactos: Dict[str, Any] = {}
                                        max_detalhes_per_run = int(os.getenv('MAX_DETALHES_FETCH_PER_RUN', '50'))
                                        if not hasattr(run_notification_cycle, '_detalhes_fetches_done'):
                                            setattr(run_notification_cycle, '_detalhes_fetches_done', 0)
                                        done = getattr(run_notification_cycle, '_detalhes_fetches_done')
                                        if done < max_detalhes_per_run:
                                            try:
                                                detalhes_compactos = _cached_obter_detalhes(task_id_txt)
                                                setattr(run_notification_cycle, '_detalhes_fetches_done', done + 1)
                                            except Exception as e_det:
                                                logging.warning("[DETALHES] Falha ao obter detalhes %s: %s", task_id_txt, e_det)

                                        # Monta card (se disponível)
                                        if create_task_notification_card:
                                            card_payload = _ensure_card_payload(
                                                create_task_notification_card(tarefa, responsavel_dados, detalhes=detalhes_compactos)  # type: ignore
                                            )
                                        else:
                                            # Fallback: mensagem simples
                                            card_payload = {
                                                "type": "AdaptiveCard", "version": "1.3",
                                                "body": [{"type": "TextBlock", "text": msg, "wrap": True}]
                                            }

                                        fallback_text = (
                                            f"🔔 Obrigação: {tarefa.get('nome', 'Sem nome')} "
                                            f"(Venc: {tarefa.get('dataVencimento', 'N/A')})"
                                        )

                                        _run_coro_safely(_resilient_send_card(bot_sender, teams_id, card_payload, fallback_text))

                                        envios_realizados_responsavel.append((chave, True))
                                        logging.info(f"[BOT-CARD] ✅ Enviado para {apelido} (tarefa: {tarefa.get('id')})")
                                    except Exception as card_error:
                                        envios_realizados_responsavel.append((chave, False))
                                        logging.warning(f"[BOT-CARD] ❌ Falha para {apelido} tarefa {tarefa.get('id')}: {card_error}")

                            mensagem_enviada = any(sucesso for _, sucesso in envios_realizados_responsavel)
                            sucessos = sum(1 for _, sucesso in envios_realizados_responsavel if sucesso)
                            total = len(envios_realizados_responsavel)
                            if sucessos > 0:
                                logging.info(f"[BOT] ✅ {sucessos}/{total} cards enviados para {apelido} (teams_id: {teams_id})")
                            else:
                                logging.warning(f"[BOT] ❌ Nenhum card enviado via bot para {apelido}")
                        except Exception as bot_error:
                            logging.warning(f"[BOT] ❌ Falha geral para {apelido}: {bot_error}")

                if not mensagem_enviada:
                    try:
                        enviar_teams_mensagem(f"{apelido}:\n{msg}")
                        for _categoria, lista_tarefas_chaves in bkt_filtrado.items():
                            for _tarefa, chave in lista_tarefas_chaves:
                                envios_realizados_responsavel.append((chave, True))
                        logging.info(f"[WEBHOOK] ✅ Enviado para {apelido}")
                    except Exception as webhook_error:
                        logging.error(f"[WEBHOOK] ❌ Falha para {apelido}: {webhook_error}")
                        for _categoria, lista_tarefas_chaves in bkt_filtrado.items():
                            for _tarefa, chave in lista_tarefas_chaves:
                                envios_realizados_responsavel.append((chave, False))

                marcar_envios_bem_sucedidos(envios_realizados_responsavel, state_storage)

                if verbose:
                    sucessos = sum(1 for _, sucesso in envios_realizados_responsavel if sucesso)
                    total = len(envios_realizados_responsavel)
                    logger.debug("[ENVIADO] %s - %d/%d tarefas enviadas com sucesso", apelido, sucessos, total)

                if rate_limit_sleep_ms > 0:
                    time.sleep(rate_limit_sleep_ms / 1000.0)

            except Exception as e:
                logging.error(f"[ERRO_ENVIO] {apelido}: {e}", exc_info=True)
                for _categoria, lista_tarefas_chaves in bkt_filtrado.items():
                    for _tarefa, chave in lista_tarefas_chaves:
                        envios_realizados_responsavel.append((chave, False))
                if rate_limit_sleep_ms > 0:
                    time.sleep(rate_limit_sleep_ms / 1000.0)

    # 8) Estatísticas finais
    counts_final = {
        "vencidas": len(buckets_globais["vencidas"]),
        "vence_hoje": len(buckets_globais["vence_hoje"]),
        "vence_em_3_dias": len(buckets_globais["vence_em_3_dias"]),
        "responsaveis_selecionados": len(mensagens_enviadas),
    }

    total_abertos_brutos = sum(1 for t in tarefas if t.get("status") in STATUS_ABERTOS)
    total_fechados_brutos = len(tarefas) - total_abertos_brutos
    zero_abertos = apenas_status_abertos and total_abertos_brutos == 0

    duration = round(time.time() - start_ts, 2)

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
            'supervisores_resumo': 1,
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

    if alertar_se_zero_abertos and zero_abertos:
        msg_warn = (f"[WARN] Nenhuma tarefa aberta na janela {t_inicio}->{t_fim} "
                    f"(coletadas={len(tarefas)}).")
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


# ================== Wrappers de compat ==================

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
    apenas_status_abertos: bool = True,
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
    modo = "dry_run" if simulacao else "live"
    return run_notification_cycle(
        execution_mode=modo,
        run_reason="azure_function",
        registrar_metricas=True,
        alertar_se_zero_abertos=True,
        verbose=True
    )
