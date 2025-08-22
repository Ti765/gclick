#!/usr/bin/env python3
"""
Teste das melhorias P2: Cache inteligente, resilience e monitoramento
"""

import asyncio
import logging
import time
from engine.cache import IntelligentCache
from engine.resilience import resilience_manager, resilient, RateLimiter, CircuitBreaker
from engine.resilience import RateLimitConfig, CircuitBreakerConfig

# Configurar logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def test_intelligent_cache():
    """Teste do sistema de cache inteligente."""
    print("\n🔍 === TESTE: Cache Inteligente ===")
    
    # Criar instância de cache
    cache = IntelligentCache(max_size=5, default_ttl=2)
    
    # Teste 1: Set e Get básico
    cache.set("key1", "value1")
    result = cache.get("key1")
    assert result == "value1", f"Expected 'value1', got {result}"
    print("✅ Set/Get básico: OK")
    
    # Teste 2: TTL expiration
    cache.set("key_ttl", "temp_value", ttl=1)
    assert cache.get("key_ttl") == "temp_value"
    time.sleep(1.5)
    assert cache.get("key_ttl") is None
    print("✅ TTL expiration: OK")
    
    # Teste 3: LRU eviction
    for i in range(10):
        cache.set(f"key_{i}", f"value_{i}")
    
    # Verificar que apenas os últimos 5 estão no cache
    for i in range(5):
        assert cache.get(f"key_{i}") is None, f"key_{i} should be evicted"
    for i in range(5, 10):
        assert cache.get(f"key_{i}") == f"value_{i}", f"key_{i} should exist"
    print("✅ LRU eviction: OK")
    
    # Teste 4: Estatísticas
    stats = cache.get_stats()
    assert "hits" in stats
    assert "misses" in stats
    assert "cache_size" in stats
    print(f"✅ Estatísticas: {stats}")

def test_rate_limiter():
    """Teste do rate limiter."""
    print("\n⏱️ === TESTE: Rate Limiter ===")
    
    config = RateLimitConfig(requests_per_second=2.0, burst_capacity=3)
    limiter = RateLimiter(config)
    
    # Teste 1: Burst capacity
    for i in range(3):
        assert limiter.can_proceed(), f"Request {i+1} should be allowed (burst)"
    print("✅ Burst capacity: OK")
    
    # Teste 2: Rate limiting
    assert not limiter.can_proceed(), "4th request should be denied"
    print("✅ Rate limiting: OK")
    
    # Teste 3: Recovery over time
    time.sleep(1)  # Esperar reabastecimento de tokens
    assert limiter.can_proceed(), "Request should be allowed after recovery"
    print("✅ Recovery over time: OK")
    
    # Teste 4: Estatísticas
    stats = limiter.get_stats()
    assert "tokens_available" in stats
    assert "requests_in_window" in stats
    print(f"✅ Estatísticas: {stats}")

def test_circuit_breaker():
    """Teste do circuit breaker."""
    print("\n🔌 === TESTE: Circuit Breaker ===")
    
    config = CircuitBreakerConfig(failure_threshold=3, recovery_timeout_seconds=2)
    breaker = CircuitBreaker("test_service", config)
    
    # Teste 1: Estado inicial (CLOSED)
    assert breaker.can_execute(), "Should be able to execute initially"
    print("✅ Estado inicial CLOSED: OK")
    
    # Teste 2: Failures leading to OPEN
    for i in range(3):
        breaker.on_failure()
    
    assert not breaker.can_execute(), "Should be OPEN after failures"
    print("✅ Estado OPEN após falhas: OK")
    
    # Teste 3: Recovery to HALF_OPEN
    time.sleep(2.5)  # Esperar timeout de recovery
    assert breaker.can_execute(), "Should be HALF_OPEN after timeout"
    print("✅ Estado HALF_OPEN após timeout: OK")
    
    # Teste 4: Success leading to CLOSED
    breaker.on_success()
    assert breaker.can_execute(), "Should be CLOSED after success"
    print("✅ Estado CLOSED após sucesso: OK")
    
    # Teste 5: Estatísticas
    stats = breaker.get_stats()
    assert "name" in stats
    assert "state" in stats
    assert "failure_count" in stats
    print(f"✅ Estatísticas: {stats}")

def test_resilience_manager():
    """Teste do gerenciador de resilience."""
    print("\n🛡️ === TESTE: Resilience Manager ===")
    
    # Teste 1: Verificação combinada
    result = resilience_manager.can_execute("test_service", check_rate_limit=True)
    print(f"✅ Can execute: {result}")
    
    # Teste 2: Registrar sucesso
    resilience_manager.on_success("test_service")
    print("✅ Success registration: OK")
    
    # Teste 3: Registrar falha
    resilience_manager.on_failure("test_service")
    print("✅ Failure registration: OK")
    
    # Teste 4: Estatísticas completas
    stats = resilience_manager.get_stats()
    assert "rate_limiter" in stats
    assert "circuit_breakers" in stats
    print(f"✅ Estatísticas completas: {stats}")

@resilient(service="test_decorated_function", check_rate_limit=False)
def test_decorated_function(should_fail=False):
    """Função de teste com decorator de resilience."""
    if should_fail:
        raise Exception("Simulated failure")
    return "success"

def test_resilience_decorator():
    """Teste do decorator de resilience."""
    print("\n🎯 === TESTE: Decorator de Resilience ===")
    
    # Teste 1: Execução bem-sucedida
    result = test_decorated_function(should_fail=False)
    assert result == "success", f"Expected 'success', got {result}"
    print("✅ Execução bem-sucedida: OK")
    
    # Teste 2: Tratamento de falha
    try:
        test_decorated_function(should_fail=True)
        assert False, "Should have raised exception"
    except Exception as e:
        assert str(e) == "Simulated failure"
        print("✅ Tratamento de falha: OK")

def main():
    """Função principal do teste."""
    print("🚀 === INICIANDO TESTES P2: Cache, Resilience e Monitoramento ===")
    
    try:
        test_intelligent_cache()
        test_rate_limiter()
        test_circuit_breaker()
        test_resilience_manager()
        test_resilience_decorator()
        
        print("\n🎉 === TODOS OS TESTES P2 PASSARAM! ===")
        print("✅ Cache inteligente funcionando")
        print("✅ Rate limiter funcionando")
        print("✅ Circuit breaker funcionando")
        print("✅ Resilience manager funcionando")
        print("✅ Decorator de resilience funcionando")
        
        return True
        
    except Exception as e:
        print(f"\n❌ === FALHA NOS TESTES P2 ===")
        print(f"Erro: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = main()
    exit(0 if success else 1)
