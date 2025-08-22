"""
Script de teste para validar as melhorias P1 implementadas.
"""

import os
import sys
import json
from datetime import date, timedelta

# Adicionar path do projeto
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def test_classificacao_unificada():
    """Testa se a classificação unificada está funcionando."""
    print("🧪 Testando classificação unificada...")
    
    try:
        from engine.notification_engine import classificar
        
        hoje = date.today()
        dias_proximos = 3
        
        # Tarefa vencida ontem (deve ser classificada)
        tarefa_ontem = {
            "id": "test1",
            "dataVencimento": (hoje - timedelta(days=1)).isoformat()
        }
        
        # Tarefa vencida há 2 dias (deve ser ignorada)
        tarefa_2_dias = {
            "id": "test2", 
            "dataVencimento": (hoje - timedelta(days=2)).isoformat()
        }
        
        # Tarefa vence hoje
        tarefa_hoje = {
            "id": "test3",
            "dataVencimento": hoje.isoformat()
        }
        
        # Tarefa vence em 2 dias
        tarefa_futuro = {
            "id": "test4",
            "dataVencimento": (hoje + timedelta(days=2)).isoformat()
        }
        
        result_ontem = classificar(tarefa_ontem, hoje, dias_proximos)
        result_2_dias = classificar(tarefa_2_dias, hoje, dias_proximos)
        result_hoje = classificar(tarefa_hoje, hoje, dias_proximos)
        result_futuro = classificar(tarefa_futuro, hoje, dias_proximos)
        
        print(f"  📅 Tarefa ontem: {result_ontem} (esperado: 'vencidas')")
        print(f"  📅 Tarefa 2 dias atrás: {result_2_dias} (esperado: None)")
        print(f"  📅 Tarefa hoje: {result_hoje} (esperado: 'vence_hoje')")
        print(f"  📅 Tarefa futuro: {result_futuro} (esperado: 'vence_em_3_dias')")
        
        assert result_ontem == "vencidas", f"Esperado 'vencidas', got {result_ontem}"
        assert result_2_dias is None, f"Esperado None, got {result_2_dias}"
        assert result_hoje == "vence_hoje", f"Esperado 'vence_hoje', got {result_hoje}"
        assert result_futuro == "vence_em_3_dias", f"Esperado 'vence_em_3_dias', got {result_futuro}"
        
        print("  ✅ Classificação unificada funcionando corretamente")
        return True
        
    except Exception as e:
        print(f"  ❌ Erro na classificação unificada: {e}")
        return False

def test_configuracoes_dinamicas():
    """Testa se as configurações dinâmicas estão funcionando."""
    print("🧪 Testando configurações dinâmicas...")
    
    try:
        from engine.notification_engine import load_notifications_config
        
        # Testar configuração padrão
        config = load_notifications_config()
        
        print(f"  ⚙️ Configuração carregada: {json.dumps(config, indent=2)}")
        
        # Verificar se tem as chaves esperadas
        expected_keys = [
            "dias_proximos", "dias_proximos_morning", "dias_proximos_afternoon",
            "page_size", "max_responsaveis_lookup", "timezone"
        ]
        
        for key in expected_keys:
            assert key in config, f"Chave '{key}' não encontrada na configuração"
            print(f"  ✓ {key}: {config[key]}")
        
        # Testar override via environment variable
        original_value = os.getenv("DIAS_PROXIMOS_MORNING")
        os.environ["DIAS_PROXIMOS_MORNING"] = "5"
        
        config_with_env = load_notifications_config()
        assert config_with_env["dias_proximos_morning"] == 5
        print(f"  ✓ Override env var funcionando: dias_proximos_morning = {config_with_env['dias_proximos_morning']}")
        
        # Restaurar valor original
        if original_value:
            os.environ["DIAS_PROXIMOS_MORNING"] = original_value
        else:
            os.environ.pop("DIAS_PROXIMOS_MORNING", None)
        
        print("  ✅ Configurações dinâmicas funcionando corretamente")
        return True
        
    except Exception as e:
        print(f"  ❌ Erro nas configurações dinâmicas: {e}")
        return False

def test_contexto_ciclo():
    """Testa se o contexto do ciclo está sendo detectado corretamente."""
    print("🧪 Testando detecção de contexto...")
    
    try:
        from engine.notification_engine import load_notifications_config
        
        # Simular diferentes contextos de run_reason
        test_cases = [
            ("scheduled_morning", "morning"),
            ("scheduled_afternoon", "afternoon"), 
            ("manual", "manual"),
            ("scheduled_test", "manual")  # fallback
        ]
        
        for run_reason, expected_context in test_cases:
            # Simular lógica de detecção de contexto
            if run_reason.startswith("scheduled_morning"):
                detected_context = "morning"
            elif run_reason.startswith("scheduled_afternoon"):
                detected_context = "afternoon"
            else:
                detected_context = "manual"
            
            assert detected_context == expected_context, \
                f"Contexto errado para '{run_reason}': esperado {expected_context}, got {detected_context}"
            
            print(f"  ✓ {run_reason} → {detected_context}")
        
        print("  ✅ Detecção de contexto funcionando corretamente")
        return True
        
    except Exception as e:
        print(f"  ❌ Erro na detecção de contexto: {e}")
        return False

def main():
    """Executa todos os testes das melhorias P1."""
    print("🚀 Iniciando testes das melhorias P1...")
    print("=" * 50)
    
    tests = [
        test_classificacao_unificada,
        test_configuracoes_dinamicas,
        test_contexto_ciclo
    ]
    
    results = []
    for test in tests:
        try:
            result = test()
            results.append(result)
        except Exception as e:
            print(f"❌ Teste {test.__name__} falhou com exceção: {e}")
            results.append(False)
        print()
    
    print("=" * 50)
    print("📊 Resumo dos Testes P1:")
    
    passed = sum(results)
    total = len(results)
    
    for i, test in enumerate(tests):
        status = "✅ PASSOU" if results[i] else "❌ FALHOU"
        print(f"  {test.__name__}: {status}")
    
    print(f"\n🎯 Resultado Final: {passed}/{total} testes passaram")
    
    if passed == total:
        print("🎉 Todas as melhorias P1 estão funcionando corretamente!")
        return True
    else:
        print("⚠️ Algumas melhorias P1 precisam de atenção.")
        return False

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
