"""
Módulo de logging configurado para Azure Functions e uso local
"""
import logging
import sys
from typing import Optional

def setup_logger(name: str, level: Optional[str] = None) -> logging.Logger:
    """
    Configura logger para Azure Functions com fallback para ambiente local
    
    Args:
        name: Nome do logger (geralmente __name__)
        level: Nível de log (DEBUG, INFO, WARNING, ERROR)
    
    Returns:
        Logger configurado
    """
    logger = logging.getLogger(name)
    
    # Evita duplicação de handlers
    if logger.handlers:
        return logger
    
    # Determina nível baseado no ambiente
    if level is None:
        import os
        level = os.getenv('GCLICK_LOG_LEVEL', 'INFO').upper()
    
    logger.setLevel(getattr(logging, level, logging.INFO))
    
    # Formatter compatível com Azure Functions
    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    # Handler para stdout (Azure Functions captura automaticamente)
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    
    # Não propaga para root logger (evita duplicação)
    logger.propagate = False
    
    return logger

# Logger padrão para o projeto
default_logger = setup_logger('gclick_teams')
