import json
from pathlib import Path
from threading import RLock
from datetime import date, datetime, timedelta
import logging

def _json_dumps_safe(obj, **kwargs) -> str:
    """Serializa objetos para JSON com suporte a date/datetime."""
    def _default(o):
        if isinstance(o, (date, datetime)):
            return o.isoformat()
        elif isinstance(o, timedelta):
            return str(o)  # timedelta não tem isoformat()
        return str(o)
    return json.dumps(obj, ensure_ascii=False, default=_default, **kwargs)

_STATE_FILE = Path("storage/notification_state.json")
_LOCK = RLock()

def _ensure_file():
    if not _STATE_FILE.parent.exists():
        _STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    if not _STATE_FILE.exists():
        _STATE_FILE.write_text(_json_dumps_safe({"entries": []}))

def load_state():
    with _LOCK:
        _ensure_file()
        try:
            data = json.loads(_STATE_FILE.read_text(encoding="utf-8"))
            if "entries" not in data:
                data["entries"] = []
            return data
        except Exception:
            return {"entries": []}

def save_state(data):
    with _LOCK:
        _STATE_FILE.write_text(_json_dumps_safe(data, indent=2))

def already_sent(key: str) -> bool:
    data = load_state()
    return key in data["entries"]

def register_sent(key: str):
    data = load_state()
    if key not in data["entries"]:
        data["entries"].append(key)
        save_state(data)

def purge_older_than(days: int = 7):
    """
    Remove entradas com data anterior a hoje - days (segurança).
    Formato chave: YYYY-MM-DD|apelido|...
    """
    today = date.today()
    data = load_state()
    kept = []
    for k in data["entries"]:
        try:
            d_str = k.split("|", 1)[0]
            y, m, d = map(int, d_str.split("-"))
            kd = date(y, m, d)
            delta = (today - kd).days
            if delta <= days:
                kept.append(k)
        except Exception:
            # se formato inesperado, mantemos por segurança
            kept.append(k)
    if len(kept) != len(data["entries"]):
        data["entries"] = kept
        save_state(data)


# ===============================================================
# NOVA API: Idempotência Granular JSON-Friendly 
# ===============================================================

class NotificationStateStorage:
    """Storage robusto para idempotência por tarefa/responsável/dia"""
    
    def __init__(self, file_path: str = None):
        if file_path:
            self.file_path = Path(file_path)
        else:
            # Usar path padrão mas com estrutura expandida
            self.file_path = Path("storage/notification_state_v2.json")
        self._data = self._load_state()
    
    def _load_state(self) -> dict:
        """Carrega estado do arquivo JSON"""
        try:
            if self.file_path.exists():
                with open(self.file_path, 'r', encoding='utf-8') as f:
                    return json.load(f)
        except Exception as e:
            logging.warning(f"Erro ao carregar estado: {e}")
        return {"sent_today": {}, "metadata": {"version": "2.0", "created": datetime.now().isoformat()}}
    
    def _save_state(self):
        """Salva estado no arquivo JSON"""
        try:
            self.file_path.parent.mkdir(parents=True, exist_ok=True)
            # Atualizar metadata
            self._data["metadata"]["last_updated"] = datetime.now().isoformat()
            
            with open(self.file_path, 'w', encoding='utf-8') as f:
                json.dump(self._data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logging.error(f"Erro ao salvar estado: {e}")
    
    def get_sent_today(self, chave_individual: str) -> bool:
        """Verifica se chave específica foi enviada hoje"""
        dia = chave_individual.split("|", 1)[0]
        enviados_dia = self._data.get("sent_today", {}).get(dia, [])
        # Converte para set em memória para busca rápida
        return chave_individual in set(enviados_dia)
    
    def mark_sent_today(self, chave_individual: str):
        """Marca chave específica como enviada hoje (JSON-friendly)"""
        dia = chave_individual.split("|", 1)[0]
        
        # Inicializa estrutura se necessário
        if "sent_today" not in self._data:
            self._data["sent_today"] = {}
        if dia not in self._data["sent_today"]:
            self._data["sent_today"][dia] = []
        
        # Adiciona apenas se não existe (evita duplicatas)
        if chave_individual not in self._data["sent_today"][dia]:
            self._data["sent_today"][dia].append(chave_individual)
        
        self._cleanup_old_dates()
        self._save_state()
    
    def _cleanup_old_dates(self):
        """Remove dados antigos (>7 dias) para manter storage limpo"""
        if "sent_today" not in self._data:
            return
            
        cutoff = datetime.now() - timedelta(days=7)
        cutoff_str = cutoff.strftime('%Y-%m-%d')
        
        dates_to_remove = [
            data for data in self._data["sent_today"].keys() 
            if data < cutoff_str
        ]
        
        for data in dates_to_remove:
            del self._data["sent_today"][data]
            
        if dates_to_remove:
            logging.info(f"🧹 Limpeza automática: removidos {len(dates_to_remove)} dias antigos")


# Funções auxiliares globais para integração com notification_engine
def criar_chave_idempotencia(tarefa_id: str, responsavel: str, data: date) -> str:
    """Cria chave única por tarefa/responsável/dia"""
    return f"{data:%Y-%m-%d}|{responsavel}|{tarefa_id}"


def aplicar_filtro_idempotencia(buckets_originais: dict, apelido: str, hoje_brt: date, state_storage) -> dict:
    """Filtra tarefas já enviadas mantendo estrutura de buckets"""
    buckets_filtrados = {}
    
    for bucket_nome, lista_tarefas in buckets_originais.items():
        tarefas_nao_enviadas = []
        
        for tarefa in lista_tarefas:
            chave = criar_chave_idempotencia(
                str(tarefa.get("id", "")), 
                apelido, 
                hoje_brt
            )
            
            if not state_storage.get_sent_today(chave):
                tarefas_nao_enviadas.append((tarefa, chave))
        
        if tarefas_nao_enviadas:
            buckets_filtrados[bucket_nome] = tarefas_nao_enviadas
    
    return buckets_filtrados


def marcar_envios_bem_sucedidos(envios_realizados: list, state_storage):
    """Marca como enviado apenas após sucesso (evita fantasmas)"""
    for chave, sucesso in envios_realizados:
        if sucesso:
            state_storage.mark_sent_today(chave)
            logging.info(f"✅ Marcado como enviado: {chave}")


# Instância global para compatibility
_global_state_storage = None

def get_global_state_storage():
    """Retorna instância global thread-safe"""
    global _global_state_storage
    if _global_state_storage is None:
        _global_state_storage = NotificationStateStorage()
    return _global_state_storage
