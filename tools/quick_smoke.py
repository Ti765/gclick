# quick smoke test for modified functions
import sys
import os
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

# permitir imports do shared_code usado pelo Azure Functions
SHARED = os.path.join(ROOT, 'azure_functions', 'shared_code')
if os.path.isdir(SHARED) and SHARED not in sys.path:
    sys.path.insert(0, SHARED)

import importlib.util

# Carregar módulo gclick.tarefas_detalhes diretamente
spec = importlib.util.spec_from_file_location("gclick.tarefas_detalhes", os.path.join(ROOT, "gclick", "tarefas_detalhes.py"))
mod_td = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod_td)
resumir_detalhes_para_card = mod_td.resumir_detalhes_para_card

# Carregar módulo teams.cards diretamente
spec2 = importlib.util.spec_from_file_location("teams.cards", os.path.join(ROOT, "teams", "cards.py"))
mod_cards = importlib.util.module_from_spec(spec2)
spec2.loader.exec_module(mod_cards)
create_task_notification_card = mod_cards.create_task_notification_card

if __name__ == '__main__':
    dummy_raw = {
        'atividades': [
            {'descricao': 'Recibo SPED Fiscal', 'concluida': True},
            {'descricao': 'Anexar DANFE', 'concluida': False},
            {'descricao': 'Conferir NFe', 'concluida': False},
            {'descricao': 'Gerar relatório', 'concluida': False},
            {'descricao': 'Enviar ao cliente', 'concluida': False},
        ],
        'observacoes': 'Texto de observacao longo'*10,
        'dataMeta': '2025-09-15'
    }
    resumo = resumir_detalhes_para_card(dummy_raw)
    print('Resumo:', resumo)

    tarefa = {'id': '4.66030', 'nome': 'Obrigações Mensais', 'dataVencimento': '2025-09-20', 'status': 'A'}
    resp = {'nome': 'Joao'}
    card = create_task_notification_card(tarefa, resp, detalhes=resumo)
    import json
    print(json.dumps(card, ensure_ascii=False, indent=2))
