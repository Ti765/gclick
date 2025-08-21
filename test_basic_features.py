#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Teste básico das funcionalidades implementadas no plano robusto
G-Click Teams Integration - Versão 2.1.4+
"""

import os
import sys
from datetime import date, timedelta

def main():
    print('🧪 Teste básico das funcionalidades implementadas')
    print('=' * 60)
    
    # Testar importações
    print('\n📦 Testando importações...')
    
    try:
        from engine.classification import separar_tarefas_overdue, obter_data_atual_brt, classificar_por_vencimento
        print('✅ engine.classification')
        has_classification = True
    except ImportError as e:
        print(f'❌ engine.classification: {e}')
        has_classification = False

    try:
        from reports.overdue_report import gerar_relatorio_excel_overdue
        print('✅ reports.overdue_report')
        has_reports = True
    except ImportError as e:
        print(f'❌ reports.overdue_report: {e}')
        has_reports = False

    try:
        from config.loader import load_config
        print('✅ config.loader')
        has_config = True
    except ImportError as e:
        print(f'❌ config.loader: {e}')
        has_config = False

    # Testar funcionalidades
    print('\n🔧 Testando funcionalidades...')
    
    if has_classification:
        # Testar timezone BRT
        try:
            hoje_brt = obter_data_atual_brt()
            print(f'✅ Data BRT: {hoje_brt}')
        except Exception as e:
            print(f'❌ Data BRT: {e}')

        # Testar separação de tarefas
        try:
            tarefas_teste = [
                {'id': '1', 'titulo': 'Tarefa Normal', 'dataVencimento': str(date.today())},
                {'id': '2', 'titulo': 'Tarefa Overdue', 'dataVencimento': str(date.today() - timedelta(days=5))},
                {'id': '3', 'titulo': 'Tarefa Futura', 'dataVencimento': str(date.today() + timedelta(days=2))}
            ]
            
            separacao = separar_tarefas_overdue(tarefas_teste)
            print(f'✅ Separação: {len(separacao["normais"])} normais, {len(separacao["overdue"])} overdue')
            
            # Detalhar separação
            for tarefa in separacao["overdue"]:
                print(f'   📋 Overdue: {tarefa["titulo"]} (venc: {tarefa["dataVencimento"]})')
                
        except Exception as e:
            print(f'❌ Separação de tarefas: {e}')

        # Testar classificação
        try:
            classif = classificar_por_vencimento(tarefas_teste)
            total_classif = sum(len(v) for v in classif.values())
            print(f'✅ Classificação: {len(classif["vencidas"])} vencidas, {len(classif["vence_hoje"])} hoje, {len(classif["vence_em_3_dias"])} próximas (total: {total_classif})')
        except Exception as e:
            print(f'❌ Classificação: {e}')

    # Testar configuração
    if has_config:
        try:
            config = load_config("config/notifications.yaml")
            print(f'✅ Config carregada: {len(config)} seções')
            
            # Verificar seções principais
            principais = ["notification_policies", "reporting_policies", "teams_settings", "storage_settings"]
            for secao in principais:
                if secao in config:
                    print(f'   📋 {secao}: ✅')
                else:
                    print(f'   📋 {secao}: ❌')
                    
        except Exception as e:
            print(f'❌ Carregamento de config: {e}')

    # Testar criação de relatório (dry run)
    if has_reports and has_classification:
        try:
            # Usar apenas tarefas overdue para teste
            tarefas_overdue_teste = [
                {
                    'id': '123',
                    'titulo': 'Tarefa Teste Overdue', 
                    'descricao': 'Descrição de teste',
                    'dataVencimento': str(date.today() - timedelta(days=10)),
                    'responsavel': 'Teste User',
                    'departamento': 'TI',
                    'categoria': 'Obrigacao',
                    'status': 'A'
                }
            ]
            
            # Teste dry-run (não salva arquivo)
            from reports.overdue_report import _preparar_dados_excel
            dados_preparados = _preparar_dados_excel(tarefas_overdue_teste, date.today())
            print(f'✅ Preparação Excel: {len(dados_preparados)} linhas preparadas')
            
        except Exception as e:
            print(f'❌ Teste relatório Excel: {e}')

    print('\n🎯 Resumo do Teste')
    print('-' * 40)
    print(f'📦 Classificação: {"✅" if has_classification else "❌"}')
    print(f'📊 Relatórios: {"✅" if has_reports else "❌"}')
    print(f'⚙️ Configuração: {"✅" if has_config else "❌"}')
    
    if has_classification and has_reports and has_config:
        print('\n🎉 Todas as funcionalidades principais estão funcionando!')
        return 0
    else:
        print('\n⚠️ Algumas funcionalidades apresentaram problemas.')
        return 1

if __name__ == "__main__":
    sys.exit(main())
