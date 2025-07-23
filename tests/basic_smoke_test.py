from datetime import date, timedelta
from engine.models import Tarefa
from engine.classification import classificar_tarefas  # ajustar se nome diferente

# Supondo que classificar_tarefas retorna dict com chaves: vencidas, vence_hoje, vence_em_3_dias

def test_classificacao_basica():
    hoje = date.today()
    tarefas = [
        Tarefa(id="1", status="A", data_vencimento=hoje - timedelta(days=1)),
        Tarefa(id="2", status="A", data_vencimento=hoje),
        Tarefa(id="3", status="A", data_vencimento=hoje + timedelta(days=2)),
    ]
    r = classificar_tarefas([t.raw if t.raw else {
        'id': t.id,
        'status': t.status,
        'dataVencimento': t.data_vencimento.isoformat()
    } for t in tarefas])
    assert any(x['id'] == '1' for x in r['vencidas'])
    assert any(x['id'] == '2' for x in r['vence_hoje'])
    assert any(x['id'] == '3' for x in r['vence_em_3_dias'])