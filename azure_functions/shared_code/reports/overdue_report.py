"""
Módulo para gerar relatórios Excel de tarefas atrasadas.
Utiliza pandas e openpyxl para criar relatórios profissionais.
"""

from __future__ import annotations
import os
import logging
from pathlib import Path
from datetime import datetime, date

def _resolve_reports_dir(base_dir: str | None = None) -> Path:
    """
    Resolve diretório persistente para relatórios:
    - Azure: $HOME/data/reports/exports
    - Local:  ./reports/exports
    """
    if base_dir and base_dir not in ("auto", ""):
        p = Path(base_dir)
    else:
        # Azure Functions: usar $HOME/data
        home = os.getenv("HOME")
        if home:
            p = Path(home) / "data" / "reports" / "exports"
        else:
            # Desenvolvimento local
            p = Path("reports") / "exports"
    
    p.mkdir(parents=True, exist_ok=True)
    return p


def gerar_relatorio_tarefas_atrasadas(tarefas_atrasadas: list, base_dir: str | None = None) -> str:
    """
    Gera relatório Excel de tarefas atrasadas.
    
    Args:
        tarefas_atrasadas: Lista de tarefas com atraso
        base_dir: Diretório de saída (opcional)
        
    Returns:
        str: Caminho do arquivo gerado
    """
    return gerar_relatorio_excel_overdue(tarefas_atrasadas, base_dir)


def gerar_relatorio_excel_overdue(tarefas_atrasadas: list, output_dir: str | None = None, hoje: date | None = None) -> str:
    """
    Gera Excel com tarefas >1 dia de atraso (ou conforme política do chamador).
    
    Args:
        tarefas_atrasadas: Lista de tarefas filtradas
        output_dir: Diretório base para salvar relatórios
        hoje: Data atual (opcional)
    
    Returns:
        Caminho do arquivo gerado (string) ou "" em caso de erro.
    """
    try:
        # Import preguiçoso para não punir cold start quando não precisa
        import pandas as pd  # type: ignore

        out_dir = _resolve_reports_dir(output_dir)
        if hoje is None:
            hoje = datetime.now().date()
        
        data_str = hoje.strftime("%Y-%m-%d")
        arquivo_datado = out_dir / f"tarefas_atrasadas_{data_str}.xlsx"
        arquivo_latest = out_dir / "tarefas_atrasadas_latest.xlsx"

        if not tarefas_atrasadas:
            # Criar arquivo indicando que não há tarefas atrasadas
            with pd.ExcelWriter(arquivo_datado, engine="openpyxl") as writer:
                pd.DataFrame({
                    "Mensagem": ["Nenhuma tarefa com atraso acima da política atual"],
                    "Data_Verificacao": [datetime.now().strftime("%Y-%m-%d %H:%M:%S")]
                }).to_excel(writer, sheet_name="Resumo", index=False)
        else:
            # Preparar dados das tarefas
            linhas = _preparar_dados_excel(tarefas_atrasadas, hoje)
            df = pd.DataFrame(linhas)
            
            # Resumo por responsável
            if not df.empty:
                grp = df.groupby("Responsável", dropna=False)["ID"].count().sort_values(ascending=False)
                df_resumo = grp.reset_index().rename(columns={"ID": "Total de Tarefas Atrasadas"})
                
                # Adicionar média de dias de atraso por responsável
                if "Dias de Atraso" in df.columns:
                    media_atraso = df.groupby("Responsável", dropna=False)["Dias de Atraso"].mean().round(1)
                    df_resumo = df_resumo.merge(
                        media_atraso.reset_index().rename(columns={"Dias de Atraso": "Média de Dias de Atraso"}),
                        on="Responsável",
                        how="left"
                    )
            else:
                df_resumo = pd.DataFrame()

            # Salvar em arquivo Excel com múltiplas abas
            with pd.ExcelWriter(arquivo_datado, engine="openpyxl") as writer:
                # Aba principal com tarefas detalhadas
                df.to_excel(writer, sheet_name="Tarefas Atrasadas", index=False)
                
                # Aba de resumo por responsável
                if not df_resumo.empty:
                    df_resumo.to_excel(writer, sheet_name="Resumo por Responsável", index=False)
                
                # Aba de estatísticas gerais
                stats = {
                    "Métrica": [
                        "Total de tarefas atrasadas",
                        "Média de dias de atraso",
                        "Maior atraso (dias)",
                        "Responsáveis únicos",
                        "Data do relatório"
                    ],
                    "Valor": [
                        len(df),
                        df["Dias de Atraso"].mean() if "Dias de Atraso" in df.columns else 0,
                        df["Dias de Atraso"].max() if "Dias de Atraso" in df.columns else 0,
                        df["Responsável"].nunique(),
                        data_str
                    ]
                }
                pd.DataFrame(stats).to_excel(writer, sheet_name="Estatísticas", index=False)

        # Criar cópia latest para facilitar acesso
        import shutil
        shutil.copy2(arquivo_datado, arquivo_latest)
        
        logging.info(f"[REPORT] Relatório Excel gerado: {arquivo_datado}")
        return str(arquivo_datado)
        
    except Exception as e:
        logging.error("[REPORT] Erro ao gerar relatório de tarefas atrasadas: %s", e)
        return ""


def _preparar_dados_excel(tarefas_atrasadas: list, hoje: date) -> list:
    """
    Prepara dados das tarefas para exportação Excel.
    Função auxiliar para testes e reutilização.
    """
    linhas = []
    for t in tarefas_atrasadas:
        nome = t.get("nome") or t.get("titulo") or "Sem nome"
        venc = t.get("dataVencimento") or ""
        cat = (t.get("categoria") or {}).get("nome") if isinstance(t.get("categoria"), dict) else t.get("categoria")
        resp = (t.get("responsavel") or {}).get("nome") if isinstance(t.get("responsavel"), dict) else t.get("responsavel") or ""
        status = t.get("status") or t.get("_statusLabel") or ""
        prioridade = t.get("prioridade") or ""
        _id = t.get("id")
        descricao = t.get("descricao", "")
        departamento = t.get("departamento", "")
        
        # Calcular dias de atraso
        try:
            from datetime import datetime as _dt
            d = _dt.strptime(venc, "%Y-%m-%d").date()
            dias_atraso = (hoje - d).days
        except Exception:
            dias_atraso = None
        
        linhas.append({
            "ID": _id,
            "Nome da Tarefa": nome,
            "Descrição": descricao,
            "Data Vencimento": venc,
            "Dias de Atraso": dias_atraso,
            "Responsável": resp or "Não informado",
            "Departamento": departamento or "N/A",
            "Categoria": cat or "N/A",
            "Prioridade": prioridade or "N/A",
            "Status": status
        })
    
    return linhas
