#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Smoke test para validar integração Timer → Engine → BotSender
Teste de integração real antes do deploy
"""

import os
import sys
import logging
from pathlib import Path
from dotenv import load_dotenv

# Adicionar o diretório raiz ao path
sys.path.insert(0, str(Path(__file__).parent.parent))

def setup_test_environment():
    """Configura ambiente de teste."""
    # Carregar .env
    load_dotenv()
    
    # Forçar configurações de teste
    os.environ["TEST_MODE"] = "true"
    os.environ["SIMULACAO"] = "true"
    os.environ["LOG_LEVEL"] = "WARNING"  # Reduzir logs para o teste
    
    # Configurar logging mínimo para o teste
    logging.basicConfig(
        level=logging.WARNING,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

def test_engine_bot_injection():
    """Testa se o bot_sender foi injetado corretamente no engine."""
    print("🧪 Testando injeção de bot_sender no engine...")
    
    try:
        # Importar function_app para triggar a injeção
        print("  📦 Importando function_app...")
        import azure_functions.function_app
        
        # Importar engine
        print("  📦 Importando notification engine...")
        import engine.notification_engine as ne
        
        # Verificar se bot_sender foi injetado
        if ne.bot_sender is None:
            print("❌ bot_sender não foi injetado no engine")
            return False
        
        print(f"✅ bot_sender injetado: {type(ne.bot_sender).__name__}")
        
        # Verificar se adapter foi injetado
        if hasattr(ne, 'adapter') and ne.adapter is not None:
            print(f"✅ adapter injetado: {type(ne.adapter).__name__}")
        
        # Verificar se conversation_storage foi injetado
        if hasattr(ne, 'conversation_storage') and ne.conversation_storage is not None:
            print(f"✅ conversation_storage injetado: {type(ne.conversation_storage).__name__}")
        
        # Verificar se tem os métodos necessários
        required_methods = ['send_message', 'send_card']
        for method in required_methods:
            if not hasattr(ne.bot_sender, method):
                print(f"❌ Método {method} não encontrado")
                return False
        
        print("✅ Todos os métodos necessários presentes")
        return True
        
    except Exception as e:
        print(f"❌ Erro ao testar injeção: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_timer_execution_path():
    """Simula execução de timer para verificar se usa bot direto."""
    print("\n🧪 Testando caminho de execução do timer...")
    
    try:
        # Importar função do timer
        from azure_functions.function_app import _execute_notification_cycle
        
        # Executar de forma segura (simulação)
        print("🔄 Executando ciclo de notificação simulado...")
        _execute_notification_cycle("smoke_test")
        
        print("✅ Timer executou sem erros")
        return True
        
    except Exception as e:
        print(f"❌ Erro na execução do timer: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_bot_sender_availability():
    """Testa se o bot_sender está disponível nos módulos corretos."""
    print("\n🧪 Testando disponibilidade do bot_sender...")
    
    try:
        # Verificar no function_app
        from azure_functions.function_app import bot_sender as fa_bot_sender
        print(f"✅ function_app.bot_sender: {type(fa_bot_sender).__name__}")
        
        # Verificar no engine
        import engine.notification_engine as ne
        if ne.bot_sender is not None:
            print(f"✅ engine.notification_engine.bot_sender: {type(ne.bot_sender).__name__}")
            
            # Verificar se são o mesmo objeto
            if fa_bot_sender is ne.bot_sender:
                print("✅ Mesmo objeto compartilhado entre módulos")
            else:
                print("⚠️  Objetos diferentes - pode ser problema")
                return False
        else:
            print("❌ engine.notification_engine.bot_sender é None")
            return False
            
        return True
        
    except Exception as e:
        print(f"❌ Erro ao verificar bot_sender: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_run_cycle_integration():
    """Testa integração completa do run_cycle."""
    print("\n🧪 Testando integração completa do run_cycle...")
    
    try:
        # Importar função
        from engine.notification_engine import run_cycle
        
        # Executar em modo simulação
        print("🔄 Executando run_cycle(simulacao=True)...")
        run_cycle(simulacao=True)
        
        print("✅ run_cycle executou sem erros")
        return True
        
    except Exception as e:
        print(f"❌ Erro no run_cycle: {e}")
        import traceback
        traceback.print_exc()
        return False

def main():
    """Executa smoke tests de integração."""
    print("🚀 SMOKE TEST - INTEGRAÇÃO TIMER → ENGINE → BOT")
    print("=" * 50)
    
    # Configurar ambiente
    setup_test_environment()
    
    tests = [
        ("1. Injeção de Bot", test_engine_bot_injection),
        ("2. Disponibilidade Bot", test_bot_sender_availability), 
        ("3. Execução Timer", test_timer_execution_path),
        ("4. Run Cycle Completo", test_run_cycle_integration),
    ]
    
    results = {}
    for name, test_func in tests:
        print(f"\n--- {name} ---")
        try:
            results[name] = test_func()
        except Exception as e:
            print(f"❌ Erro inesperado em {name}: {e}")
            results[name] = False
    
    print("\n" + "=" * 50)
    print("📊 RESUMO SMOKE TEST")
    print("=" * 50)
    
    for name, success in results.items():
        status = "✅ PASS" if success else "❌ FAIL"
        print(f"{status} {name}")
    
    total_pass = sum(results.values())
    print(f"\nResultado: {total_pass}/{len(tests)} testes passaram")
    
    if total_pass == len(tests):
        print("🎉 SMOKE TEST PASSOU - Sistema pronto para deploy!")
        print("🚀 Integração Timer → Engine → Bot funcionando perfeitamente!")
    else:
        print("⚠️  Alguns testes falharam - verificar antes do deploy")
        return 1
    
    return 0

if __name__ == "__main__":
    exit_code = main()
    sys.exit(exit_code)
