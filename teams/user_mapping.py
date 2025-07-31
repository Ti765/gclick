"""
Módulo compartilhado para mapeamento de usuários G-Click para Teams IDs.

Este módulo centraliza a lógica de mapeamento de apelidos do G-Click para IDs do Teams,
incluindo suporte ao modo de teste onde todas as notificações são redirecionadas
para um usuário específico.
"""

import os
import logging
from typing import Optional, Dict

logger = logging.getLogger(__name__)

# Mapeamento de apelidos G-Click para IDs do Teams
_GCLICK_TO_TEAMS = {
    "neusag.glip": os.getenv("TEAMS_ID_NEUSAG"),
    "sueli.coelho": os.getenv("TEAMS_ID_SUELI"), 
    "daniele.rocha": os.getenv("TEAMS_ID_DANIELE"),
    "luciana.cavallari": os.getenv("TEAMS_ID_LUCIANA"),
    "dayane.glip": os.getenv("TEAMS_ID_DAYANE"),
    "nathalian.glip": os.getenv("TEAMS_ID_NATHALIAN"),
    "daiane.glip": os.getenv("TEAMS_ID_DAIANE"),
    "edvaldo.goncalves": os.getenv("TEAMS_ID_EDVALDO"),
    "patricia.barbosa": os.getenv("TEAMS_ID_PATRICIA"),
    "cilene.glip": os.getenv("TEAMS_ID_CILENE"),
    # Usuário para testes e desenvolvimento
    "mauricio.bernej": "4a5a678b-f3c1-4a7d-af41-1b97686a0b6b",
    "mauricio.bernejo": "4a5a678b-f3c1-4a7d-af41-1b97686a0b6b"
}

def mapear_apelido_para_teams_id(apelido: str) -> Optional[str]:
    """
    Mapeia um apelido do G-Click para um ID do Teams.
    
    Quando TEST_MODE=true, redireciona TODAS as notificações para o ID de teste,
    independente do responsável original. Isso permite testar o sistema completo
    sem enviar notificações para os usuários reais.
    
    Args:
        apelido: Apelido do usuário no G-Click (ex: "mauricio.bernej")
        
    Returns:
        Optional[str]: ID do Teams correspondente ou None se não encontrado
        
    Example:
        >>> # Modo normal
        >>> mapear_apelido_para_teams_id("mauricio.bernej")
        "4a5a678b-f3c1-4a7d-af41-1b97686a0b6b"
        
        >>> # Modo de teste (TEST_MODE=true)
        >>> mapear_apelido_para_teams_id("qualquer.usuario") 
        "4a5a678b-f3c1-4a7d-af41-1b97686a0b6b"  # Redirecionado
    """
    if not apelido:
        logger.warning("Apelido vazio fornecido para mapeamento")
        return None
        
    # Verificar se estamos em modo de teste
    test_mode = os.environ.get("TEST_MODE", "false").lower() in ("true", "1", "yes")
    test_user_id = os.environ.get("TEST_USER_TEAMS_ID", "4a5a678b-f3c1-4a7d-af41-1b97686a0b6b")
    
    # Se estiver em modo de teste, redirecionar TODAS as notificações para o usuário de teste
    if test_mode:
        logger.info(f"[TEST_MODE] Redirecionando notificação de '{apelido}' para usuário de teste: {test_user_id}")
        return test_user_id
    
    # Verificar primeiro no mapeamento fixo
    result = _GCLICK_TO_TEAMS.get(apelido.lower())
    
    # Se não encontrou, tentar variáveis de ambiente dinâmicas
    # Formato: TEAMS_ID_USUARIO_EMPRESA (ex: TEAMS_ID_MAURICIO_BERNEJ)
    if not result:
        env_var = f"TEAMS_ID_{apelido.upper().replace('.', '_')}"
        result = os.getenv(env_var)
        if result:
            logger.debug(f"ID do Teams encontrado via variável de ambiente {env_var}")
    
    if not result:
        logger.warning(f"Usuário '{apelido}' não mapeado para Teams ID")
    else:
        logger.debug(f"Usuário '{apelido}' mapeado para Teams ID: {result[:10]}...")
    
    return result

def get_all_mapped_users() -> Dict[str, str]:
    """
    Retorna todos os usuários mapeados com seus IDs do Teams.
    
    Útil para debug e verificação de configuração.
    
    Returns:
        Dict[str, str]: Dicionário com apelido -> Teams ID (apenas os definidos)
    """
    return {k: v for k, v in _GCLICK_TO_TEAMS.items() if v}

def is_test_mode() -> bool:
    """
    Verifica se o sistema está executando em modo de teste.
    
    Returns:
        bool: True se TEST_MODE está ativo, False caso contrário
    """
    return os.environ.get("TEST_MODE", "false").lower() in ("true", "1", "yes")

def get_test_user_id() -> str:
    """
    Retorna o ID do usuário de teste configurado.
    
    Returns:
        str: ID do Teams para o usuário de teste
    """
    return os.environ.get("TEST_USER_TEAMS_ID", "4a5a678b-f3c1-4a7d-af41-1b97686a0b6b")

def validate_teams_id(teams_id: str) -> bool:
    """
    Valida se um ID do Teams tem o formato esperado.
    
    Args:
        teams_id: ID a ser validado
        
    Returns:
        bool: True se válido, False caso contrário
    """
    if not teams_id:
        return False
        
    # IDs do Teams geralmente têm formato: UUID ou 29:UUID
    import re
    
    # Padrão UUID: 8-4-4-4-12 caracteres hexadecimais
    uuid_pattern = r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
    
    # Padrão Teams: 29:UUID ou 28:UUID  
    teams_pattern = r'^2[89]:[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
    
    return bool(re.match(uuid_pattern, teams_id, re.IGNORECASE) or 
                re.match(teams_pattern, teams_id, re.IGNORECASE))

def log_mapping_status():
    """
    Registra no log o status atual do mapeamento.
    
    Útil para debug e verificação de configuração.
    """
    mapped_users = get_all_mapped_users()
    test_mode = is_test_mode()
    test_user = get_test_user_id()
    
    logger.info(f"Mapeamento de usuários: {len(mapped_users)} usuários configurados")
    logger.info(f"Modo de teste: {'ATIVO' if test_mode else 'INATIVO'}")
    
    if test_mode:
        logger.info(f"Usuário de teste: {test_user}")
    
    for apelido, teams_id in mapped_users.items():
        if teams_id:
            is_valid = validate_teams_id(teams_id)
            logger.debug(f"  {apelido} -> {teams_id[:10]}... {'✓' if is_valid else '✗'}")
