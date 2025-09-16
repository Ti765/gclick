"""
Sistema de cache inteligente para melhorar performance do G-Click Teams.
Implementa cache em memória com TTL e invalidação automática.
"""

import os
import time
import json
import logging
from typing import Any, Dict, Optional, Callable
from datetime import datetime, timedelta, date
from dataclasses import dataclass
from threading import Lock
import hashlib

logger = logging.getLogger(__name__)

def _json_dumps_safe(obj) -> str:
    """Serializa objetos para JSON com suporte a date/datetime."""
    def _default(o):
        if isinstance(o, (date, datetime)):
            return o.isoformat()
        elif isinstance(o, timedelta):
            return str(o)  # timedelta não tem isoformat()
        return str(o)
    return json.dumps(obj, ensure_ascii=False, default=_default)

@dataclass
class CacheEntry:
    """Entrada do cache com metadados."""
    value: Any
    created_at: float
    ttl_seconds: int
    access_count: int = 0
    last_accessed: float = 0
    
    def __post_init__(self):
        if self.last_accessed == 0:
            self.last_accessed = self.created_at
    
    def is_expired(self) -> bool:
        """Verifica se a entrada expirou."""
        return time.time() - self.created_at > self.ttl_seconds
    
    def touch(self):
        """Atualiza timestamp de último acesso."""
        self.access_count += 1
        self.last_accessed = time.time()

class IntelligentCache:
    """
    Cache inteligente com TTL, LRU e métricas.
    
    Features:
    - TTL (Time To Live) configurável por entrada
    - LRU (Least Recently Used) eviction
    - Métricas de hit/miss
    - Invalidação por padrão de chave
    - Compressão automática para grandes objetos
    """
    
    def __init__(self, 
                 max_size: int = 1000,
                 default_ttl: int = 300,  # 5 minutos
                 enable_compression: bool = True,
                 compression_threshold: int = 1024):  # 1KB
        self.max_size = max_size
        self.default_ttl = default_ttl
        self.enable_compression = enable_compression
        self.compression_threshold = compression_threshold
        
        self._cache: Dict[str, CacheEntry] = {}
        self._lock = Lock()
        
        # Métricas
        self._stats = {
            'hits': 0,
            'misses': 0,
            'evictions': 0,
            'invalidations': 0,
            'compressions': 0,
            'total_requests': 0
        }
        
        logger.info("🗄️ Cache inteligente inicializado: max_size=%d, ttl=%ds", 
                   max_size, default_ttl)
    
    def _generate_key(self, key: str) -> str:
        """Gera chave normalizada para o cache."""
        if len(key) > 200:  # Hash chaves muito longas
            return hashlib.md5(key.encode()).hexdigest()
        return key.lower().strip()
    
    def _compress_value(self, value: Any) -> Any:
        """Comprime valores grandes se habilitado."""
        if not self.enable_compression:
            return value
            
        try:
            serialized = _json_dumps_safe(value)
            if len(serialized) > self.compression_threshold:
                import gzip
                import base64
                compressed = gzip.compress(serialized.encode())
                self._stats['compressions'] += 1
                logger.debug("🗜️ Valor comprimido: %d → %d bytes", 
                           len(serialized), len(compressed))
                return {
                    '_compressed': True,
                    '_data': base64.b64encode(compressed).decode()
                }
        except Exception as e:
            logger.warning("⚠️ Falha na compressão: %s", e)
        
        return value
    
    def _decompress_value(self, value: Any) -> Any:
        """Descomprime valores se necessário."""
        if isinstance(value, dict) and value.get('_compressed'):
            try:
                import gzip
                import base64
                compressed = base64.b64decode(value['_data'])
                decompressed = gzip.decompress(compressed).decode()
                return json.loads(decompressed)
            except Exception as e:
                logger.warning("⚠️ Falha na descompressão: %s", e)
        
        return value
    
    def _evict_lru(self):
        """Remove entradas LRU quando cache está cheio."""
        if len(self._cache) < self.max_size:
            return
            
        # Encontrar entrada menos recentemente usada
        lru_key = min(self._cache.keys(), 
                     key=lambda k: self._cache[k].last_accessed)
        
        del self._cache[lru_key]
        self._stats['evictions'] += 1
        logger.debug("📤 Entrada LRU removida: %s", lru_key)
    
    def _cleanup_expired(self):
        """Remove entradas expiradas."""
        expired_keys = [
            key for key, entry in self._cache.items()
            if entry.is_expired()
        ]
        
        for key in expired_keys:
            del self._cache[key]
            
        if expired_keys:
            logger.debug("🧹 %d entradas expiradas removidas", len(expired_keys))
    
    def get(self, key: str) -> Optional[Any]:
        """Obtém valor do cache."""
        with self._lock:
            self._stats['total_requests'] += 1
            normalized_key = self._generate_key(key)
            
            if normalized_key not in self._cache:
                self._stats['misses'] += 1
                return None
            
            entry = self._cache[normalized_key]
            
            if entry.is_expired():
                del self._cache[normalized_key]
                self._stats['misses'] += 1
                return None
            
            entry.touch()
            self._stats['hits'] += 1
            
            return self._decompress_value(entry.value)
    
    def set(self, key: str, value: Any, ttl: Optional[int] = None) -> bool:
        """Armazena valor no cache."""
        try:
            with self._lock:
                normalized_key = self._generate_key(key)
                ttl = ttl or self.default_ttl
                
                # Cleanup antes de inserir
                self._cleanup_expired()
                self._evict_lru()
                
                # Comprimir se necessário
                compressed_value = self._compress_value(value)
                
                entry = CacheEntry(
                    value=compressed_value,
                    created_at=time.time(),
                    ttl_seconds=ttl
                )
                
                self._cache[normalized_key] = entry
                
                logger.debug("💾 Cache set: %s (ttl=%ds)", normalized_key, ttl)
                return True
                
        except Exception as e:
            logger.error("❌ Erro ao armazenar no cache: %s", e)
            return False
    
    def invalidate(self, pattern: str = None, key: str = None) -> int:
        """Invalida entradas do cache."""
        with self._lock:
            removed_count = 0
            
            if key:
                # Invalidar chave específica
                normalized_key = self._generate_key(key)
                if normalized_key in self._cache:
                    del self._cache[normalized_key]
                    removed_count = 1
            elif pattern:
                # Invalidar por padrão
                keys_to_remove = [
                    k for k in self._cache.keys()
                    if pattern.lower() in k
                ]
                for k in keys_to_remove:
                    del self._cache[k]
                removed_count = len(keys_to_remove)
            else:
                # Clear completo
                removed_count = len(self._cache)
                self._cache.clear()
            
            self._stats['invalidations'] += removed_count
            
            if removed_count > 0:
                logger.info("🗑️ Cache invalidado: %d entradas removidas", removed_count)
            
            return removed_count
    
    def get_or_set(self, key: str, factory: Callable[[], Any], 
                   ttl: Optional[int] = None) -> Any:
        """Obtém do cache ou executa factory function e armazena."""
        value = self.get(key)
        if value is not None:
            return value
        
        # Cache miss - executar factory
        try:
            value = factory()
            self.set(key, value, ttl)
            return value
        except Exception as e:
            logger.error("❌ Erro na factory function para chave %s: %s", key, e)
            raise
    
    def get_stats(self) -> Dict[str, Any]:
        """Retorna estatísticas do cache."""
        with self._lock:
            total_requests = self._stats['total_requests']
            hit_rate = (self._stats['hits'] / total_requests * 100) if total_requests > 0 else 0
            
            return {
                **self._stats,
                'cache_size': len(self._cache),
                'hit_rate_percent': round(hit_rate, 2),
                'max_size': self.max_size,
                'memory_usage': {
                    'entries': len(self._cache),
                    'max_entries': self.max_size,
                    'usage_percent': round(len(self._cache) / self.max_size * 100, 2)
                }
            }
    
    def clear_stats(self):
        """Reset estatísticas."""
        with self._lock:
            self._stats = {key: 0 for key in self._stats.keys()}
            logger.info("📊 Estatísticas do cache resetadas")

# Instância global do cache
global_cache = IntelligentCache(
    max_size=int(os.getenv("CACHE_MAX_SIZE", "1000")),
    default_ttl=int(os.getenv("CACHE_DEFAULT_TTL", "300")),
    enable_compression=os.getenv("CACHE_COMPRESSION", "true").lower() == "true"
)

# Cache específicos para diferentes tipos de dados
responsaveis_cache = IntelligentCache(
    max_size=500,
    default_ttl=600,  # 10 minutos para responsáveis
    enable_compression=False
)

tarefas_cache = IntelligentCache(
    max_size=2000,
    default_ttl=180,  # 3 minutos para tarefas (dados mais voláteis)
    enable_compression=True
)

conversation_cache = IntelligentCache(
    max_size=1000,
    default_ttl=3600,  # 1 hora para conversation references
    enable_compression=False
)
