"""
Teste de ponta a ponta para validar o fluxo completo de notificação do G-Click.

Este script testa:
1. Recebimento de webhook do G-Click
2. Processamento do payload
3. Mapeamento de responsáveis
4. Criação de cartões adaptativos
5. Envio via bot do Teams (simulado)

Para executar:
    python tests/test_notification_flow.py
"""

import os
import sys
import json
import logging
import asyncio
from pathlib import Path

# Ajusta caminho para importar módulos do projeto
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

# Mock das dependências do Azure Functions para teste local
class MockHttpRequest:
    def __init__(self, method="POST", body=None, headers=None):
        self.method = method
        self._body = body
        self._headers = headers or {}
        
    def get_body(self):
        return self._body
        
    def get_json(self):
        if self._body:
            return json.loads(self._body.decode('utf-8'))
        return None
        
    @property
    def headers(self):
        return self._headers

class MockHttpResponse:
    def __init__(self, body, status_code=200, headers=None):
        self.body = body
        self.status_code = status_code
        self.headers = headers or {}
        
    def get_body(self):
        return self.body

# Configuração de logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

# Payloads de teste
SAMPLE_PAYLOAD_SINGLE_TASK = {
    "evento": "tarefa_vencimento_proximo",
    "tarefa": {
        "id": "4.12345",
        "nome": "SPED - ECF (Escrituração Contábil Fiscal)",
        "dataVencimento": "2025-07-31",
        "status": "A",
        "_statusLabel": "Aberto"
    },
    "responsaveis": [
        {
            "id": "123",
            "apelido": "neusag.glip",
            "nome": "Neusa Gomes",
            "email": "neusa@exemplo.com"
        }
    ],
    "urgencia": "alta"
}

SAMPLE_PAYLOAD_MULTIPLE_RESP = {
    "evento": "tarefa_vencimento_hoje",
    "tarefa": {
        "id": "4.67890",
        "nome": "CSLL e IRPJ - LR (Livro de Registro)",
        "dataVencimento": "2025-07-30",
        "status": "A",
        "_statusLabel": "Aberto"
    },
    "responsaveis": [
        {
            "id": "124",
            "apelido": "sueli.coelho",
            "nome": "Sueli Coelho",
            "email": "sueli@exemplo.com"
        },
        {
            "id": "125",
            "apelido": "daniele.rocha",
            "nome": "Daniele Rocha", 
            "email": "daniele@exemplo.com"
        }
    ]
}

SAMPLE_PAYLOAD_INVALID = {
    "evento": "teste",
    # Faltando campo "tarefa" obrigatório
    "responsaveis": []
}

async def test_webhook_validation():
    """Testa a validação de payload do webhook."""
    print("\\n=== Teste 1: Validação de Payload ===")
    
    try:
        from azure_functions.function_app import validate_gclick_payload
        
        # Teste com payload válido
        assert validate_gclick_payload(SAMPLE_PAYLOAD_SINGLE_TASK) == True
        print("✓ Payload válido aceito")
        
        # Teste com payload inválido
        assert validate_gclick_payload(SAMPLE_PAYLOAD_INVALID) == False
        print("✓ Payload inválido rejeitado")
        
        # Teste com payload None
        assert validate_gclick_payload(None) == False
        print("✓ Payload None rejeitado")
        
        return True
        
    except Exception as e:
        print(f"✗ Falha na validação: {e}")
        return False

def test_user_mapping():
    """Testa o mapeamento de usuários G-Click para Teams."""
    print("\\n=== Teste 2: Mapeamento de Usuários ===")
    
    try:
        from teams.user_mapping import mapear_apelido_para_teams_id
        
        # Teste com usuários conhecidos (assumindo variáveis de ambiente configuradas)
        result = mapear_apelido_para_teams_id("neusag.glip")
        print(f"Mapeamento neusag.glip -> {result}")
        
        # Teste com usuário desconhecido
        result = mapear_apelido_para_teams_id("usuario.inexistente")
        assert result is None
        print("✓ Usuário inexistente retorna None")
        
        return True
        
    except Exception as e:
        print(f"✗ Falha no mapeamento: {e}")
        return False

def test_message_formatting():
    """Testa a formatação de mensagens."""
    print("\\n=== Teste 3: Formatação de Mensagens ===")
    
    try:
        from azure_functions.function_app import formatar_notificacao_tarefa
        
        tarefa = SAMPLE_PAYLOAD_SINGLE_TASK["tarefa"]
        responsavel = SAMPLE_PAYLOAD_SINGLE_TASK["responsaveis"][0]
        
        mensagem = formatar_notificacao_tarefa(tarefa, responsavel)
        
        # Verifica se contém elementos esperados
        assert "SPED - ECF" in mensagem
        assert "4.12345" in mensagem
        assert "2025-07-31" in mensagem
        assert "https://app.gclick.com.br/tarefas/4.12345" in mensagem
        
        print("✓ Mensagem formatada corretamente")
        print(f"Exemplo: {mensagem[:100]}...")
        
        return True
        
    except Exception as e:
        print(f"✗ Falha na formatação: {e}")
        return False

def test_adaptive_card_creation():
    """Testa a criação de cartões adaptativos."""
    print("\\n=== Teste 4: Criação de Cartões Adaptativos ===")
    
    try:
        from teams.cards import create_task_notification_card
        
        tarefa = SAMPLE_PAYLOAD_SINGLE_TASK["tarefa"]
        responsavel = SAMPLE_PAYLOAD_SINGLE_TASK["responsaveis"][0]
        
        card_json = create_task_notification_card(tarefa, responsavel)
        
        # Parseia o JSON para validar estrutura
        card_data = json.loads(card_json)
        
        # Verifica estrutura básica do Adaptive Card
        assert card_data["type"] == "AdaptiveCard"
        assert "version" in card_data
        assert "body" in card_data
        assert "actions" in card_data
        
        print("✓ Cartão adaptativo criado com sucesso")
        print(f"Versão do card: {card_data['version']}")
        print(f"Número de elementos no body: {len(card_data['body'])}")
        print(f"Número de ações: {len(card_data['actions'])}")
        
        return True
        
    except Exception as e:
        print(f"✗ Falha na criação do cartão: {e}")
        return False

async def test_webhook_endpoint_mock():
    """Testa o endpoint do webhook com dados simulados."""
    print("\\n=== Teste 5: Endpoint de Webhook (Simulado) ===")
    
    try:
        # Simula o comportamento do endpoint sem executar Azure Functions
        payload = SAMPLE_PAYLOAD_SINGLE_TASK
        
        # Testa validação
        from azure_functions.function_app import validate_gclick_payload
        if not validate_gclick_payload(payload):
            print("✗ Payload inválido")
            return False
            
        # Testa processamento de responsáveis
        responsaveis = payload.get("responsaveis", [])
        tarefa_data = payload.get("tarefa", {})
        
        processados = 0
        for resp in responsaveis:
            apelido = resp.get("apelido", "").strip()
            if apelido:
                # Simula mapeamento
                from azure_functions.function_app import mapear_apelido_para_teams_id
                teams_id = mapear_apelido_para_teams_id(apelido)
                
                if teams_id:
                    print(f"  ✓ {apelido} -> Teams ID encontrado")
                    processados += 1
                else:
                    print(f"  ⚠ {apelido} -> Teams ID não encontrado")
                    
                # Simula criação de mensagem
                from azure_functions.function_app import formatar_notificacao_tarefa
                mensagem = formatar_notificacao_tarefa(tarefa_data, resp)
                print(f"    Mensagem: {len(mensagem)} caracteres")
        
        print(f"✓ Processamento simulado concluído: {processados}/{len(responsaveis)} responsáveis")
        return True
        
    except Exception as e:
        print(f"✗ Falha no teste do endpoint: {e}")
        return False

def test_error_handling():
    """Testa tratamento de erros."""
    print("\\n=== Teste 6: Tratamento de Erros ===")
    
    try:
        from azure_functions.function_app import validate_gclick_payload, formatar_notificacao_tarefa
        
        # Teste com dados malformados
        payload_ruim = {"tarefa": {"id": ""}}  # Faltando campos obrigatórios
        result = validate_gclick_payload(payload_ruim)
        print(f"Payload malformado rejeitado: {not result}")
        
        # Teste formatação com dados parciais
        tarefa_vazia = {}
        resp_vazio = {}
        
        try:
            mensagem = formatar_notificacao_tarefa(tarefa_vazia, resp_vazio)
            print("✓ Formatação com dados vazios não quebrou")
        except Exception as e:
            print(f"⚠ Formatação com dados vazios falhou: {e}")
        
        return True
        
    except Exception as e:
        print(f"✗ Falha no teste de erros: {e}")
        return False

async def run_all_tests():
    """Executa todos os testes."""
    print("🚀 Iniciando Teste de Ponta a Ponta - G-Click Teams Notification")
    print("=" * 60)
    
    tests = [
        ("Validação de Payload", test_webhook_validation()),
        ("Mapeamento de Usuários", test_user_mapping()),
        ("Formatação de Mensagens", test_message_formatting()),
        ("Criação de Cartões", test_adaptive_card_creation()),
        ("Endpoint Simulado", test_webhook_endpoint_mock()),
        ("Tratamento de Erros", test_error_handling()),
    ]
    
    results = []
    for test_name, test_coro in tests:
        try:
            if asyncio.iscoroutine(test_coro):
                result = await test_coro
            else:
                result = test_coro
            results.append((test_name, result))
        except Exception as e:
            print(f"✗ Erro no teste '{test_name}': {e}")
            results.append((test_name, False))
    
    # Relatório final
    print("\\n" + "=" * 60)
    print("📊 RELATÓRIO FINAL")
    print("=" * 60)
    
    passed = sum(1 for _, result in results if result)
    total = len(results)
    
    for test_name, result in results:
        status = "✅ PASSOU" if result else "❌ FALHOU"
        print(f"{status} - {test_name}")
    
    print(f"\\n🎯 Resultado: {passed}/{total} testes passaram")
    
    if passed == total:
        print("🎉 Todos os testes passaram! Sistema pronto para uso.")
    else:
        print("⚠️  Alguns testes falharam. Verifique as dependências e configurações.")
    
    return passed == total

if __name__ == "__main__":
    # Configura algumas variáveis de ambiente para teste se não existirem
    if not os.getenv("TEAMS_ID_NEUSAG"):
        os.environ["TEAMS_ID_NEUSAG"] = "29:1test-user-id-neusag"
    if not os.getenv("TEAMS_ID_SUELI"):
        os.environ["TEAMS_ID_SUELI"] = "29:1test-user-id-sueli"
    
    # Executa os testes
    success = asyncio.run(run_all_tests())
    
    # Exit code baseado no resultado
    sys.exit(0 if success else 1)
