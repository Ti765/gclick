"""
Smoke tests específicos para validar a funcionalidade do Azure Function e shared_code
"""
import os
import sys
from pathlib import Path

# Configura paths para imports
current_dir = Path(__file__).parent.absolute()
project_root = current_dir.parent  # gclick_teams root
sys.path.append(str(current_dir))
sys.path.append(str(project_root))

# Configura variáveis de ambiente mínimas para teste
os.environ.setdefault("GCLICK_API_BASE", "https://app.gclick.com.br")
os.environ.setdefault("GCLICK_CLIENT_ID", "test_client")
os.environ.setdefault("GCLICK_CLIENT_SECRET", "test_secret")

def test_shared_code_imports():
    """Testa imports críticos do shared_code"""
    print("\n--- 1. Validação de Imports ---")
    try:
        # Testa imports relativos
        from shared_code.teams import cards, user_mapping
        from shared_code.engine import notification_engine
        from shared_code.reports import overdue_report
        
        # Verifica funções de teams
        print("  Verificando módulo teams...")
        assert hasattr(user_mapping, 'mapear_apelido_para_teams_id'), "Função mapear_apelido_para_teams_id não encontrada"
        
        # Verifica engine
        print("  Verificando módulo engine...")
        assert hasattr(notification_engine, 'run_notification_cycle'), "Função run_notification_cycle não encontrada"
        
        # Verifica reports
        print("  Verificando módulo reports...")
        assert hasattr(overdue_report, 'gerar_relatorio_tarefas_atrasadas'), "Função gerar_relatorio_tarefas_atrasadas não encontrada"
        
        print("✅ Imports básicos OK")
    except ImportError as e:
        print(f"❌ Falha nos imports: {e}")
        return False
    except AssertionError as e:
        print(f"❌ Falha na validação: {e}")
        return False
    return True

def test_function_app_initialization():
    """Testa inicialização básica do function_app"""
    print("\n--- 2. Inicialização do Function App ---")
    try:
        import function_app
        print(f"✅ function_app importado: {function_app}")
        
        if hasattr(function_app, 'bot_sender'):
            print("✅ bot_sender inicializado")
        else:
            print("❌ bot_sender não encontrado")
            return False
            
    except Exception as e:
        print(f"❌ Falha ao inicializar function_app: {e}")
        return False
    return True

def test_config_loading():
    """Testa carregamento das configurações"""
    print("\n--- 3. Carregamento de Configurações ---")
    try:
        from shared_code.config import loader
        
        # Verifica se o módulo tem as funções esperadas
        assert hasattr(loader, 'load_config'), "Função load_config não encontrada"
        
        # Testa configs principais
        configs = [
            'notifications.yaml',
            'config.yaml',
            'scheduling.yaml'
        ]
        
        config_base = Path(current_dir) / 'shared_code' / 'config'
        if not config_base.exists():
            print(f"❌ Diretório de configuração não encontrado: {config_base}")
            return False
            
        success = False
        for config in configs:
            config_path = config_base / config
            if config_path.exists():
                try:
                    cfg = loader.load_config(str(config_path))
                    print(f"✅ {config} carregado: {len(cfg)} chaves")
                    success = True
                except Exception as e:
                    print(f"⚠️ Erro ao carregar {config}: {e}")
            else:
                print(f"⚠️ Arquivo não encontrado: {config}")
                
        if not success:
            print("❌ Nenhum arquivo de configuração foi carregado com sucesso")
            return False
                
    except Exception as e:
        print(f"❌ Falha ao carregar configs: {e}")
        return False
    return True

def run_smoke_tests():
    """Executa todos os smoke tests"""
    print("\n=== SMOKE TESTS - AZURE FUNCTIONS ===")
    print("Validando componentes críticos...")
    
    results = {
        "imports": test_shared_code_imports(),
        "function_app": test_function_app_initialization(),
        "configs": test_config_loading()
    }
    
    print("\n=== RESUMO DOS TESTES ===")
    for test, passed in results.items():
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"{status} {test}")
        
    total_passed = sum(1 for r in results.values() if r)
    total_tests = len(results)
    
    print(f"\nResultado: {total_passed}/{total_tests} testes passaram")
    if total_passed < total_tests:
        print("⚠️ Alguns testes falharam - verificar antes do deploy")
        return False
    return True

if __name__ == '__main__':
    success = run_smoke_tests()
    sys.exit(0 if success else 1)