"""
Script para simular o envio de payloads do G-Click para o webhook.

Este script facilita o teste manual do endpoint /api/gclick enviando
diferentes tipos de payload para validar o comportamento do sistema.

Uso:
    python tests/simulate_gclick_webhook.py --scenario single
    python tests/simulate_gclick_webhook.py --scenario multiple  
    python tests/simulate_gclick_webhook.py --scenario invalid
    python tests/simulate_gclick_webhook.py --url http://localhost:7071/api/gclick
"""

import requests
import json
import argparse
import sys
from datetime import datetime, date, timedelta

# Cenários de teste predefinidos
SCENARIOS = {
    "single": {
        "name": "Tarefa única com responsável único",
        "payload": {
            "evento": "tarefa_vencimento_proximo",
            "tarefa": {
                "id": "4.12345",
                "nome": "SPED - ECF (Escrituração Contábil Fiscal)",
                "dataVencimento": (date.today() + timedelta(days=1)).isoformat(),
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
    },
    
    "multiple": {
        "name": "Tarefa com múltiplos responsáveis",
        "payload": {
            "evento": "tarefa_vencimento_hoje",
            "tarefa": {
                "id": "4.67890",
                "nome": "CSLL e IRPJ - LR (Livro de Registro)",
                "dataVencimento": date.today().isoformat(),
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
                },
                {
                    "id": "126",
                    "apelido": "luciana.cavallari", 
                    "nome": "Luciana Cavallari",
                    "email": "luciana@exemplo.com"
                }
            ],
            "urgencia": "media"
        }
    },
    
    "overdue": {
        "name": "Tarefa vencida (1 dia de atraso)",
        "payload": {
            "evento": "tarefa_vencida",
            "tarefa": {
                "id": "4.99999",
                "nome": "Declaração IRPF - Pessoa Física",
                "dataVencimento": (date.today() - timedelta(days=1)).isoformat(),
                "status": "A",
                "_statusLabel": "Vencido"
            },
            "responsaveis": [
                {
                    "id": "127",
                    "apelido": "patricia.barbosa",
                    "nome": "Patricia Barbosa", 
                    "email": "patricia@exemplo.com"
                }
            ],
            "urgencia": "critica"
        }
    },
    
    "unknown_user": {
        "name": "Responsável não mapeado",
        "payload": {
            "evento": "tarefa_vencimento_proximo",
            "tarefa": {
                "id": "4.55555",
                "nome": "Obrigação de Teste",
                "dataVencimento": (date.today() + timedelta(days=2)).isoformat(),
                "status": "A"
            },
            "responsaveis": [
                {
                    "id": "999",
                    "apelido": "usuario.inexistente",
                    "nome": "Usuário Inexistente",
                    "email": "inexistente@exemplo.com"
                }
            ]
        }
    },
    
    "invalid": {
        "name": "Payload inválido (faltando campos obrigatórios)",
        "payload": {
            "evento": "teste_invalido",
            # Faltando campo "tarefa" obrigatório
            "responsaveis": [],
            "dados_incorretos": True
        }
    },
    
    "malformed": {
        "name": "JSON malformado",
        "payload": "{ \"evento\": \"malformed\", \"tarefa\": { \"id\": incomplete"
    }
}

def send_webhook_request(url: str, payload: dict, timeout: int = 30) -> dict:
    """
    Envia requisição POST para o webhook.
    
    Args:
        url: URL do webhook
        payload: Dados a serem enviados
        timeout: Timeout da requisição em segundos
        
    Returns:
        dict: Resposta da requisição com status, dados, etc.
    """
    try:
        headers = {
            "Content-Type": "application/json; charset=utf-8",
            "User-Agent": "G-Click-Webhook-Simulator/1.0"
        }
        
        if isinstance(payload, str):
            # Para testar JSON malformado
            response = requests.post(
                url, 
                data=payload,
                headers=headers,
                timeout=timeout
            )
        else:
            response = requests.post(
                url,
                json=payload,
                headers=headers, 
                timeout=timeout
            )
        
        result = {
            "success": True,
            "status_code": response.status_code,
            "headers": dict(response.headers),
            "response_time": response.elapsed.total_seconds()
        }
        
        # Tenta parsear resposta como JSON
        try:
            result["data"] = response.json()
        except:
            result["data"] = response.text
            
        return result
        
    except requests.exceptions.Timeout:
        return {
            "success": False,
            "error": "Timeout na requisição",
            "status_code": None
        }
    except requests.exceptions.ConnectionError:
        return {
            "success": False,
            "error": "Erro de conexão - verifique se o servidor está rodando",
            "status_code": None
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "status_code": None
        }

def print_request_info(scenario_name: str, payload: dict, url: str):
    """Imprime informações da requisição."""
    print(f"\\n{'=' * 60}")
    print(f"🚀 SIMULANDO: {scenario_name}")
    print(f"📡 URL: {url}")
    print(f"📅 Timestamp: {datetime.now().isoformat()}")
    print(f"{'=' * 60}")
    
    if isinstance(payload, str):
        print("📦 Payload (string - possivelmente malformado):")
        print(payload[:200] + ("..." if len(payload) > 200 else ""))
    else:
        print("📦 Payload:")
        print(json.dumps(payload, indent=2, ensure_ascii=False))

def print_response_info(result: dict):
    """Imprime informações da resposta."""
    print(f"\\n📬 RESPOSTA:")
    print(f"{'─' * 40}")
    
    if result["success"]:
        status = result["status_code"]
        time_ms = round(result["response_time"] * 1000, 2)
        
        if status >= 200 and status < 300:
            print(f"✅ Status: {status} (Sucesso)")
        elif status >= 400 and status < 500:
            print(f"⚠️  Status: {status} (Erro do Cliente)")
        else:
            print(f"❌ Status: {status} (Erro do Servidor)")
            
        print(f"⏱️  Tempo de resposta: {time_ms}ms")
        
        # Mostra dados da resposta
        data = result.get("data")
        if data:
            if isinstance(data, dict):
                print("📄 Dados:")
                print(json.dumps(data, indent=2, ensure_ascii=False))
            else:
                print(f"📄 Resposta: {data}")
    else:
        print(f"❌ Falha na requisição: {result['error']}")

def main():
    """Função principal."""
    parser = argparse.ArgumentParser(
        description="Simula envio de webhooks do G-Click para teste"
    )
    parser.add_argument(
        "--scenario",
        choices=list(SCENARIOS.keys()),
        default="single",
        help="Cenário de teste a executar"
    )
    parser.add_argument(
        "--url",
        default="http://localhost:7071/api/gclick",
        help="URL do webhook (padrão: localhost Azure Functions)"
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=30,
        help="Timeout da requisição em segundos"
    )
    parser.add_argument(
        "--list-scenarios",
        action="store_true",
        help="Lista todos os cenários disponíveis"
    )
    
    args = parser.parse_args()
    
    # Lista cenários se solicitado
    if args.list_scenarios:
        print("📋 Cenários disponíveis:")
        print("=" * 50)
        for key, scenario in SCENARIOS.items():
            print(f"🔹 {key}: {scenario['name']}")
        return
    
    # Executa o cenário selecionado
    scenario = SCENARIOS[args.scenario]
    scenario_name = scenario["name"]
    payload = scenario["payload"]
    
    print_request_info(scenario_name, payload, args.url)
    
    # Envia requisição
    result = send_webhook_request(args.url, payload, args.timeout)
    
    # Mostra resultado
    print_response_info(result)
    
    # Exit code baseado no sucesso
    if result["success"] and result.get("status_code", 0) < 400:
        print("\\n🎉 Teste concluído com sucesso!")
        sys.exit(0)
    else:
        print("\\n💥 Teste falhou ou retornou erro!")
        sys.exit(1)

if __name__ == "__main__":
    main()
