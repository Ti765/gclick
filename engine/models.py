from __future__ import annotations
from dataclasses import dataclass
from datetime import date
from typing import List, Optional

@dataclass
class Tarefa:
    id: str
    status: str
    data_vencimento: date
    titulo: Optional[str] = None
    departamento_id: Optional[int] = None
    raw: dict | None = None  # manter referência ao dict original se necessário

@dataclass
class GrupoResponsavel:
    responsavel_id: str
    nome: str
    tarefas: List[Tarefa]

@dataclass
class NotificationMetrics:
    tasks_total_raw: int
    tasks_open_after_filter: int
    tasks_vencidas: int
    tasks_vence_hoje: int
    tasks_vence_proximos: int

    def to_dict(self) -> dict:
        return {
            "tasks_total_raw": self.tasks_total_raw,
            "tasks_open_after_filter": self.tasks_open_after_filter,
            "tasks_vencidas": self.tasks_vencidas,
            "tasks_vence_hoje": self.tasks_vence_hoje,
            "tasks_vence_proximos": self.tasks_vence_proximos,
        }