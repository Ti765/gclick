import os
import time
from datetime import date, timedelta
from collections import defaultdict
from typing import Dict, List, Any, Tuple, Optional
import datetime as dt

import yaml

from gclick.tarefas import listar_tarefas_page, normalizar_tarefa
from gclick.responsaveis import listar_responsaveis_tarefa
from teams.webhook import enviar_teams_mensagem
from storage.state import already_sent, register_sent, purge_older_than

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
    # Altere o caminho do import se estiver em outro local!
    from teams.bot_sender import BotSender, mapear_apelido_para_teams_id
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
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}

# =============================================================
# Classificação Temporal
# =============================================================

def classificar(tarefa: Dict[str, Any], hoje: date, dias_proximos: int) -> Optional[str]:
    dt_txt = tarefa.get("dataVencimento")
    if not dt_txt:
        return None
    try:
        dt_venc = date.fromisoformat(dt_txt)
    except Exception:
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
        page_tasks, meta = listar_tarefas_page(
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
            page_tasks, meta = listar_tarefas_page(
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

def run_notification_cycle(
    *,
    dias_proximos: int = 3,
    categoria: str = "Obrigacao",
    usar_full_scan: bool = True,
    page_size: int = 200,
    max_pages: Optional[int] = None,
    apenas_status_abertos: bool = True,
    max_responsaveis_lookup: int = 100,
    limite_responsaveis_notificar: int = 50,
    detalhar_limite: int = 5,
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
    """Executa um ciclo de notificação e registra métricas padronizadas.
    Retorna dicionário com estatísticas principais.
    """
    start_ts = time.time()
    if run_id is None:
        run_id = new_run_id('notify')

    hoje = date.today()
    t_inicio = hoje
    t_fim = hoje + timedelta(days=dias_proximos)

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

    # 3. Classificação global
    buckets_globais = {"vencidas": [], "vence_hoje": [], "vence_em_3_dias": []}
    norm_tarefas = [normalizar_tarefa(t) for t in tarefas_filtradas]
    for nt in norm_tarefas:
        cls = classificar(nt, hoje, dias_proximos)
        if cls:
            buckets_globais[cls].append(nt)

    relevantes = buckets_globais["vencidas"] + buckets_globais["vence_hoje"] + buckets_globais["vence_em_3_dias"]
    if verbose:
        print("[INFO] Classificação global:", {k: len(v) for k, v in buckets_globais.items()}, "relevantes=", len(relevantes))

    # 4. Agrupamento de responsáveis
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

    # 6. Construção das mensagens e idempotência
    mensagens_enviadas: List[Tuple[str, str, str]] = []
    for apelido, bkt in responsaveis_ordenados:
        total_resp = sum(len(lst) for lst in bkt.values())
        if total_resp == 0:
            continue
        msg = formatar_mensagem_individual(apelido, bkt, limite_detalhe=detalhar_limite)
        if not msg:
            continue
        ids = sorted({t['id'] for lst in bkt.values() for t in lst})
        key = f"{hoje.isoformat()}|{apelido}|{','.join(ids)}"
        if not repetir_no_mesmo_dia and already_sent(key):
            if verbose:
                print(f"[SKIP] Já notificado hoje: {apelido} ({len(ids)} tarefas).")
            continue
        mensagens_enviadas.append((apelido, key, msg))

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
        
        # Depois, envia individualmente:
        for apelido, key, msg in mensagens_enviadas:
            try:
                mensagem_enviada = False
                
                # Tenta enviar via bot primeiro (se disponível)
                if bot_sender:
                    teams_id = mapear_apelido_para_teams_id(apelido)
                    if teams_id:
                        try:
                            import asyncio
                            loop = asyncio.get_event_loop()
                            if loop.is_running():
                                asyncio.ensure_future(bot_sender.send_message(teams_id, msg))
                            else:
                                loop.run_until_complete(bot_sender.send_message(teams_id, msg))
                            mensagem_enviada = True
                            logging.info(f"[BOT] Enviado para {apelido} (teams_id: {teams_id})")
                        except Exception as bot_error:
                            logging.warning(f"[BOT] Falha para {apelido}: {bot_error}")
                
                # Fallback para webhook se bot falhou ou não está disponível
                if not mensagem_enviada:
                    enviar_teams_mensagem(f"{apelido}:\n{msg}")
                    logging.info(f"[WEBHOOK] Enviado para {apelido}")
                
                register_sent(key)
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