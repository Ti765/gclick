"""
Módulo de utilitários para tratamento robusto de erros e execução em lote.

Fornece funções para executar operações em lote com tratamento de erro,
logging adequado e capacidade de continuar execução mesmo com falhas parciais.
"""

import logging
import asyncio
from typing import List, Tuple, Callable, Any, Optional, Union
from functools import wraps
import time

logger = logging.getLogger(__name__)

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
            
        notification_functions.append((func, args, {}))
    
    # Executa em lote com tratamento de erro
    try:
        results = await safe_execute_batch_async(
            notification_functions,
            continue_on_error=True,
            max_concurrent=3  # Limita para não sobrecarregar Teams API
        )
        
        # Processa resultados
        successful_notifications = sum(1 for success, _, _ in results if success)
        failed_notifications = len(results) - successful_notifications
        
        logger.info(f"Lote de notificações processado: {successful_notifications} enviadas, {failed_notifications} falharam")
        
        # Registra erros no contador global
        for i, (success, result, error) in enumerate(results):
            if not success:
                user_id = user_notifications[i]["user_id"]
                log_error_and_count("notification_send_failed", error, f"user_id={user_id}")
        
        return {
            "total": len(results),
            "successful": successful_notifications,
            "failed": failed_notifications,
            "results": results
        }
        
    except Exception as e:
        log_error_and_count("notification_batch_failed", e, f"batch_size={len(user_notifications)}")
        raise
