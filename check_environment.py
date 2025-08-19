#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Script para verificar e configurar o ambiente no Windows
"""

import os
import sys
import locale
from pathlib import Path
from dotenv import load_dotenv

def check_python_encoding():
    """Verifica encoding do Python"""
    print("🔍 VERIFICANDO ENCODING DO PYTHON")
    print("-" * 50)
    
    print(f"sys.getdefaultencoding(): {sys.getdefaultencoding()}")
    print(f"sys.stdout.encoding: {sys.stdout.encoding}")
    print(f"sys.stderr.encoding: {sys.stderr.encoding}")
    print(f"locale.getpreferredencoding(): {locale.getpreferredencoding()}")
    
    # Verificar variável de ambiente
    pythonioencoding = os.environ.get('PYTHONIOENCODING')
    print(f"PYTHONIOENCODING: {pythonioencoding}")
    
    # Teste de caracteres especiais
    try:
        test_string = "Teste: àáâãäçèéêëìíîïñòóôõöùúûüý 🎯 ✅"
        print(f"Teste UTF-8: {test_string}")
        print("✅ Encoding funcionando corretamente")
    except UnicodeError as e:
        print(f"❌ Erro de encoding: {e}")
        
    print()

def check_env_file():
    """Verifica se .env existe e está carregado"""
    print("🔍 VERIFICANDO ARQUIVO .env")
    print("-" * 50)
    
    env_path = Path('.env')
    if env_path.exists():
        print(f"✅ Arquivo .env encontrado: {env_path.absolute()}")
        
        # Carregar .env
        load_dotenv()
        
        # Verificar variáveis importantes
        important_vars = [
            'TEST_MODE',
            'TEST_USER_TEAMS_ID', 
            'MicrosoftAppId',
            'MicrosoftAppPassword',
            'GCLICK_CLIENT_ID',
            'PYTHONIOENCODING'
        ]
        
        print("\nVariáveis carregadas:")
        for var in important_vars:
            value = os.environ.get(var)
            if value:
                # Mascarar valores sensíveis
                if 'PASSWORD' in var or 'SECRET' in var or 'TOKEN' in var:
                    display_value = value[:8] + "***" if len(value) > 8 else "***"
                else:
                    display_value = value
                print(f"  {var}: {display_value}")
            else:
                print(f"  {var}: ❌ NÃO DEFINIDA")
                
    else:
        print(f"❌ Arquivo .env não encontrado em: {env_path.absolute()}")
        
    print()

def check_modules():
    """Verifica se os módulos podem ser importados"""
    print("🔍 VERIFICANDO IMPORTS DOS MÓDULOS")
    print("-" * 50)
    
    modules_to_test = [
        ('teams.user_mapping', 'mapear_apelido_para_teams_id'),
        ('teams.bot_sender', 'BotSender'),
        ('gclick.auth', 'get_access_token'),
        ('storage.state', 'already_sent'),
        ('engine.notification_engine', 'run_cycle'),
    ]
    
    for module_name, item_name in modules_to_test:
        try:
            module = __import__(module_name, fromlist=[item_name])
            getattr(module, item_name)
            print(f"✅ {module_name}.{item_name}")
        except ImportError as e:
            print(f"❌ {module_name}.{item_name}: {e}")
        except AttributeError as e:
            print(f"❌ {module_name}.{item_name}: {e}")
            
    print()

def check_storage_files():
    """Verifica se arquivos de storage existem"""
    print("🔍 VERIFICANDO ARQUIVOS DE STORAGE")
    print("-" * 50)
    
    storage_files = [
        'storage/notification_state.json',
        'storage/metrics/metrics_aggregate.json'
    ]
    
    for file_path in storage_files:
        path = Path(file_path)
        if path.exists():
            print(f"✅ {file_path}")
        else:
            print(f"❌ {file_path} (será criado quando necessário)")
            # Criar diretórios se não existirem
            path.parent.mkdir(parents=True, exist_ok=True)
            
    print()

def main():
    """Função principal"""
    print("=" * 60)
    print("🔧 DIAGNÓSTICO DO AMBIENTE - GCLICK TEAMS")
    print("=" * 60)
    print()
    
    # Verificar diretório atual
    print(f"📁 Diretório atual: {Path.cwd()}")
    print(f"🐍 Python: {sys.version}")
    print(f"💻 Sistema: {sys.platform}")
    print()
    
    # Executar verificações
    check_python_encoding()
    check_env_file()
    check_modules()
    check_storage_files()
    
    print("=" * 60)
    print("🏁 DIAGNÓSTICO CONCLUÍDO")
    print("=" * 60)
    
    # Dicas para Windows
    print("\n💡 DICAS PARA WINDOWS:")
    print("- Se houver problemas de encoding, execute:")
    print("  set PYTHONIOENCODING=utf-8")
    print("- Para PowerShell:")
    print("  $env:PYTHONIOENCODING='utf-8'")
    print("- Ou adicione PYTHONIOENCODING=utf-8 no .env")
    print()

if __name__ == "__main__":
    main()
