"""
Módulo de utilitários para tratamento robusto de erros, execução em lote e resilience.

Fornece funções para executar operações em lote com tratamento de erro,
logging adequado, rate limiting, circuit breaker e retry policies.
"""

import os
import logging
import asyncio
import time
import random
import functools
from functools import wraps
from typing import List, Tuple, Callable, Any, Optional, Union
from datetime import datetime, timedelta
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger(__name__)

class CircuitState(Enum):
    """Estados do Circuit Breaker."""
    CLOSED = "closed"      # Funcionamento normal
    OPEN = "open"          # Falhas detectadas, bloqueando requests
    HALF_OPEN = "half_open"  # Testando se serviço se recuperou

@dataclass
class RateLimitConfig:
    """Configuração de rate limiting."""
    requests_per_second: float = 10.0
    burst_capacity: int = 20
    window_size_seconds: int = 60

@dataclass
class CircuitBreakerConfig:
    """Configuração do circuit breaker."""
    failure_threshold: int = 5
    recovery_timeout_seconds: int = 60
    half_open_max_calls: int = 3
    success_threshold: int = 2

@dataclass
class RetryConfig:
    """Configuração de retry."""
    max_attempts: int = 3
    base_delay_seconds: float = 1.0
    max_delay_seconds: float = 30.0
    exponential_base: float = 2.0
    jitter: bool = True

def safe_execute_batch(functions: List[Tuple[Callable, tuple, dict]], continue_on_error: bool = True) -> List[Tuple[bool, Any, Optional[Exception]]]:
    """
    Executa uma série de funções, registrando erros mas continuando execução.
    
    Args:
        functions: Lista de tuplas (func, args, kwargs) para executar
        continue_on_error: Se True, continua após erro; se False, levanta exceção
        
    Returns:
        List[Tuple[bool, Any, Optional[Exception]]]: Para cada função:
            - bool: True se sucesso, False se falha
            - Any: resultado da função ou None se falhou
            - Optional[Exception]: exceção se houve falha, None se sucesso
    """
    results = []
    
    for i, (func, args, kwargs) in enumerate(functions):
        try:
            logger.debug(f"Executando função {i+1}/{len(functions)}: {func.__name__}")
            result = func(*args, **kwargs)
            results.append((True, result, None))
            logger.debug(f"Função {func.__name__} executada com sucesso")
            
        except Exception as e:
            logger.error(f"Erro executando {func.__name__}: {e}", exc_info=True)
            results.append((False, None, e))
            
            if not continue_on_error:
                logger.error(f"Parando execução em lote devido ao erro em {func.__name__}")
                raise
                
    # Log do resumo
    successful = sum(1 for success, _, _ in results if success)
    total = len(results)
    logger.info(f"Execução em lote concluída: {successful}/{total} funções executadas com sucesso")
    
    return results

async def safe_execute_batch_async(functions: List[Tuple[Callable, tuple, dict]], continue_on_error: bool = True, max_concurrent: int = 5) -> List[Tuple[bool, Any, Optional[Exception]]]:
    """
    Versão assíncrona de safe_execute_batch com controle de concorrência.
    
    Args:
        functions: Lista de tuplas (async_func, args, kwargs) para executar
        continue_on_error: Se True, continua após erro; se False, levanta exceção
        max_concurrent: Máximo de funções executando simultaneamente
        
    Returns:
        List[Tuple[bool, Any, Optional[Exception]]]: Status de cada execução
    """
    semaphore = asyncio.Semaphore(max_concurrent)
    results = [None] * len(functions)  # Pre-allocate para manter ordem
    
    async def execute_with_semaphore(index: int, func: Callable, args: tuple, kwargs: dict):
        async with semaphore:
            try:
                logger.debug(f"Executando função assíncrona {index+1}/{len(functions)}: {func.__name__}")
                
                if asyncio.iscoroutinefunction(func):
                    result = await func(*args, **kwargs)
                else:
                    result = func(*args, **kwargs)
                    
                results[index] = (True, result, None)
                logger.debug(f"Função {func.__name__} executada com sucesso")
                
            except Exception as e:
                logger.error(f"Erro executando {func.__name__}: {e}", exc_info=True)
                results[index] = (False, None, e)
                
                if not continue_on_error:
                    logger.error(f"Parando execução em lote devido ao erro em {func.__name__}")
                    raise
    
    # Cria tasks para todas as funções
    tasks = [
        execute_with_semaphore(i, func, args, kwargs)
        for i, (func, args, kwargs) in enumerate(functions)
    ]
    
    # Executa todas as tasks
    await asyncio.gather(*tasks, return_exceptions=continue_on_error)
    
    # Log do resumo
    successful = sum(1 for success, _, _ in results if success)
    total = len(results)
    logger.info(f"Execução assíncrona em lote concluída: {successful}/{total} funções executadas com sucesso")
    
    return results

def retry_on_failure(max_attempts: int = 3, delay: float = 1.0, backoff_factor: float = 2.0, exceptions: tuple = (Exception,)):
    """
    Decorator que adiciona retry automático com backoff exponencial.
    
    Args:
        max_attempts: Número máximo de tentativas
        delay: Delay inicial entre tentativas (segundos)
        backoff_factor: Fator de multiplicação do delay a cada retry
        exceptions: Tupla de exceções que devem triggerar retry
        
    Returns:
        Decorator function
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            current_delay = delay
            last_exception = None
            
            for attempt in range(max_attempts):
                try:
                    return func(*args, **kwargs)
                except exceptions as e:
                    last_exception = e
                    if attempt == max_attempts - 1:
                        # Última tentativa - relança a exceção
                        logger.error(f"Função {func.__name__} falhou após {max_attempts} tentativas: {e}")
                        raise
                    else:
                        logger.warning(f"Tentativa {attempt + 1}/{max_attempts} de {func.__name__} falhou: {e}. Tentando novamente em {current_delay}s...")
                        time.sleep(current_delay)
                        current_delay *= backoff_factor
            
            # Não deveria chegar aqui, mas por segurança
            raise last_exception
            
        return wrapper
    return decorator

def async_retry_on_failure(max_attempts: int = 3, delay: float = 1.0, backoff_factor: float = 2.0, exceptions: tuple = (Exception,)):
    """
    Versão assíncrona do decorator retry_on_failure.
    """
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            current_delay = delay
            last_exception = None
            
            for attempt in range(max_attempts):
                try:
                    return await func(*args, **kwargs)
                except exceptions as e:
                    last_exception = e
                    if attempt == max_attempts - 1:
                        logger.error(f"Função {func.__name__} falhou após {max_attempts} tentativas: {e}")
                        raise
                    else:
                        logger.warning(f"Tentativa {attempt + 1}/{max_attempts} de {func.__name__} falhou: {e}. Tentando novamente em {current_delay}s...")
                        await asyncio.sleep(current_delay)
                        current_delay *= backoff_factor
            
            raise last_exception
            
        return wrapper
    return decorator

class ErrorCounter:
    """
    Contador de erros para monitoramento de saúde do sistema.
    """
    
    def __init__(self):
        self.counts = {}
        self.recent_errors = []
        self.max_recent = 100  # Máximo de erros recentes para manter
    
    def add_error(self, error_type: str, error_message: str = "", timestamp: Optional[float] = None):
        """
        Adiciona um erro ao contador.
        
        Args:
            error_type: Tipo/categoria do erro
            error_message: Mensagem do erro (opcional)
            timestamp: Timestamp do erro (opcional, usa time.time() se None)
        """
        if timestamp is None:
            timestamp = time.time()
            
        # Atualiza contador por tipo
        self.counts[error_type] = self.counts.get(error_type, 0) + 1
        
        # Adiciona aos erros recentes
        self.recent_errors.append({
            "type": error_type,
            "message": error_message,
            "timestamp": timestamp
        })
        
        # Limita tamanho da lista de erros recentes
        if len(self.recent_errors) > self.max_recent:
            self.recent_errors = self.recent_errors[-self.max_recent:]
            
        logger.debug(f"Erro adicionado ao contador: {error_type} (total: {self.counts[error_type]})")
    
    def get_summary(self) -> dict:
        """
        Retorna um resumo dos erros.
        
        Returns:
            dict: Resumo com contadores e estatísticas
        """
        total_errors = sum(self.counts.values())
        
        # Erros das últimas 24 horas
        day_ago = time.time() - (24 * 60 * 60)
        recent_24h = [e for e in self.recent_errors if e["timestamp"] > day_ago]
        
        # Erros da última hora
        hour_ago = time.time() - (60 * 60)
        recent_1h = [e for e in self.recent_errors if e["timestamp"] > hour_ago]
        
        return {
            "total_errors": total_errors,
            "errors_by_type": dict(self.counts),
            "errors_last_24h": len(recent_24h),
            "errors_last_hour": len(recent_1h),
            "most_recent_errors": self.recent_errors[-5:] if self.recent_errors else []
        }
    
    def reset(self):
        """Reseta todos os contadores."""
        self.counts.clear()
        self.recent_errors.clear()
        logger.info("Contador de erros resetado")

# Instância global para contagem de erros
global_error_counter = ErrorCounter()

def log_error_and_count(error_type: str, exception: Exception, extra_info: str = ""):
    """
    Registra um erro no log e no contador global.
    
    Args:
        error_type: Tipo/categoria do erro
        exception: Exceção capturada
        extra_info: Informações adicionais sobre o contexto do erro
    """
    error_message = f"{str(exception)} {extra_info}".strip()
    
    logger.error(f"[{error_type}] {error_message}", exc_info=True)
    global_error_counter.add_error(error_type, error_message)

# Exemplo de uso das funções de resiliência
async def example_resilient_notification_batch(user_notifications: List[dict]):
    """
    Exemplo de como usar as funções de resiliência para envio de notificações em lote.
    
    Args:
        user_notifications: Lista de dicionários com dados de notificação
    """
    from teams.bot_sender import BotSender  # Import local para evitar circular
    
    # Preparar funções para execução em lote
    bot_sender = BotSender()
    notification_functions = []
    
    for notification in user_notifications:
        user_id = notification["user_id"]
        message = notification["message"]
        card_json = notification.get("card_json")
        
        if card_json:
            func = bot_sender.send_card
            args = (user_id, card_json, message)
        else:
            func = bot_sender.send_message
            args = (user_id, message)
        
        kwargs = {}
        notification_functions.append((func, args, kwargs))
    
    # Executar em lote usando o safe_execute_batch existente
    results = safe_execute_batch(notification_functions, continue_on_error=True)
    
    # Processar resultados para retornar estatísticas
    successful = sum(1 for success, _, _ in results if success)
    failed = len(results) - successful
    
    logger.info(f"Notificações enviadas: {successful} sucesso, {failed} falhas")
    
    return {
        "sent": successful,
        "failed": failed,
        "total": len(results),
        "details": results
    }

# =============================================================
# SISTEMA DE RESILIENCE P2 - RATE LIMITING & CIRCUIT BREAKER
# =============================================================

class RateLimiter:
    """Rate limiter usando token bucket algorithm."""
    
    def __init__(self, config: RateLimitConfig):
        self.config = config
        self.tokens = config.burst_capacity
        self.last_update = time.time()
        self.requests_count = 0
        self.window_start = time.time()
        
        logger.info("⏱️ Rate limiter configurado: %.1f req/s, burst=%d", 
                   config.requests_per_second, config.burst_capacity)
    
    def can_proceed(self) -> bool:
        """Verifica se request pode prosseguir."""
        now = time.time()
        elapsed = now - self.last_update
        self.last_update = now
        
        # Reabastecimento de tokens
        tokens_to_add = elapsed * self.config.requests_per_second
        self.tokens = min(self.config.burst_capacity, self.tokens + tokens_to_add)
        
        if self.tokens >= 1.0:
            self.tokens -= 1.0
            self.requests_count += 1
            return True
        
        logger.warning("🚫 Rate limit atingido: %.1f tokens restantes", self.tokens)
        return False
    
    def get_stats(self) -> dict:
        """Retorna estatísticas do rate limiter."""
        return {
            "tokens_available": round(self.tokens, 2),
            "requests_in_window": self.requests_count,
            "rate_limit": self.config.requests_per_second
        }

class CircuitBreaker:
    """Circuit breaker para proteger contra falhas em cascata."""
    
    def __init__(self, name: str, config: CircuitBreakerConfig):
        self.name = name
        self.config = config
        self.state = CircuitState.CLOSED
        self.failure_count = 0
        self.success_count = 0
        self.last_failure_time = 0
        
        logger.info("🔌 Circuit breaker '%s' inicializado", name)
    
    def can_execute(self) -> bool:
        """Verifica se pode executar operação."""
        if self.state == CircuitState.CLOSED:
            return True
        
        if self.state == CircuitState.OPEN:
            if time.time() - self.last_failure_time >= self.config.recovery_timeout_seconds:
                self.state = CircuitState.HALF_OPEN
                logger.info("🔄 Circuit breaker '%s' mudou para HALF_OPEN", self.name)
                return True
            return False
        
        return True  # HALF_OPEN allows execution
    
    def on_success(self):
        """Registra sucesso na operação."""
        if self.state == CircuitState.HALF_OPEN:
            self.success_count += 1
            if self.success_count >= self.config.success_threshold:
                self.state = CircuitState.CLOSED
                self.failure_count = 0
                logger.info("✅ Circuit breaker '%s' FECHADO", self.name)
        elif self.state == CircuitState.CLOSED:
            self.failure_count = max(0, self.failure_count - 1)
    
    def on_failure(self):
        """Registra falha na operação."""
        self.last_failure_time = time.time()
        self.failure_count += 1
        
        if self.failure_count >= self.config.failure_threshold:
            self.state = CircuitState.OPEN
            logger.warning("🚨 Circuit breaker '%s' ABERTO (%d falhas)", 
                         self.name, self.failure_count)
    
    def get_stats(self) -> dict:
        """Retorna estatísticas do circuit breaker."""
        return {
            "name": self.name,
            "state": self.state.value,
            "failure_count": self.failure_count,
            "can_execute": self.can_execute()
        }

class ResilienceManager:
    """Gerenciador central de resilience."""
    
    def __init__(self):
        self.rate_limiter = RateLimiter(RateLimitConfig(
            requests_per_second=float(os.getenv("RATE_LIMIT_RPS", "10")),
            burst_capacity=int(os.getenv("RATE_LIMIT_BURST", "20"))
        ))
        
        self.circuit_breakers = {}
        self._setup_circuit_breakers()
        
        logger.info("🛡️ Resilience manager inicializado")
    
    def _setup_circuit_breakers(self):
        """Configura circuit breakers para diferentes serviços."""
        services = ["gclick_api", "teams_bot", "storage"]
        
        for service in services:
            config = CircuitBreakerConfig(
                failure_threshold=int(os.getenv(f"CB_{service.upper()}_THRESHOLD", "5")),
                recovery_timeout_seconds=int(os.getenv(f"CB_{service.upper()}_TIMEOUT", "60"))
            )
            self.circuit_breakers[service] = CircuitBreaker(service, config)
    
    def get_circuit_breaker(self, service: str) -> CircuitBreaker:
        """Obtém circuit breaker para um serviço específico."""
        if service not in self.circuit_breakers:
            config = CircuitBreakerConfig()
            self.circuit_breakers[service] = CircuitBreaker(service, config)
        return self.circuit_breakers[service]
    
    def can_execute(self, service: str = "default", check_rate_limit: bool = True) -> bool:
        """Verifica se operação pode ser executada."""
        if check_rate_limit and not self.rate_limiter.can_proceed():
            return False
        
        circuit_breaker = self.get_circuit_breaker(service)
        return circuit_breaker.can_execute()
    
    def on_success(self, service: str = "default"):
        """Registra sucesso de operação."""
        circuit_breaker = self.get_circuit_breaker(service)
        circuit_breaker.on_success()
    
    def on_failure(self, service: str = "default"):
        """Registra falha de operação."""
        circuit_breaker = self.get_circuit_breaker(service)
        circuit_breaker.on_failure()
    
    def get_stats(self) -> dict:
        """Retorna estatísticas completas."""
        return {
            "rate_limiter": self.rate_limiter.get_stats(),
            "circuit_breakers": {
                name: cb.get_stats() 
                for name, cb in self.circuit_breakers.items()
            }
        }

# Instância global do resilience manager
resilience_manager = ResilienceManager()

def resilient(service: str = "default", check_rate_limit: bool = True):
    """Decorator para aplicar resilience a funções."""
    def decorator(func):
        def wrapper(*args, **kwargs):
            if not resilience_manager.can_execute(service, check_rate_limit):
                raise Exception(f"Resilience check failed for service: {service}")
            
            try:
                result = func(*args, **kwargs)
                resilience_manager.on_success(service)
                return result
            except Exception as e:
                resilience_manager.on_failure(service)
                raise
        return wrapper
    return decorator
