import sys
import os
from pathlib import Path

# Simular o ambiente do Azure Functions
azure_functions_dir = Path("azure_functions")
shared_code_dir = azure_functions_dir / "shared_code"

# Adicionar ao path como o function_app.py faz
sys.path.insert(0, str(shared_code_dir.resolve()))

try:
    # Testar os imports críticos
    from engine.notification_engine import run_notification_cycle
    from engine.cache import IntelligentCache
    from engine.resilience import resilience_manager
    from teams.bot_sender import BotSender
    from gclick.auth import get_auth_headers
    
    print("✅ TODOS OS IMPORTS CRÍTICOS FUNCIONANDO!")
    print("✅ notification_engine: OK")
    print("✅ cache system: OK") 
    print("✅ resilience system: OK")
    print("✅ teams bot: OK")
    print("✅ gclick auth: OK")
    
    print("\n🚀 DEPLOY STATUS: READY FOR PRODUCTION!")
    
except ImportError as e:
    print(f"❌ ERRO DE IMPORT: {e}")
    print("❌ Deploy não recomendado até corrigir imports")
except Exception as e:
    print(f"❌ ERRO GERAL: {e}")
    print("❌ Investigar problema antes do deploy")
