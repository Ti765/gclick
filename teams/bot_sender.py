import os
import json
import logging
import asyncio
from typing import Dict, Any, Optional
from pathlib import Path

from botbuilder.core import BotFrameworkAdapter, TurnContext
from botbuilder.schema import Activity, ConversationReference
from botframework.connector.auth import MicrosoftAppCredentials

class BotSender:
    """
    Gerenciador de mensagens proativas para o Bot Framework.
    Permite enviar mensagens diretas para usuários através do Bot do Teams.
    """
    
    def __init__(self, adapter, app_id, conversation_storage):
        """
        Inicializa o sender com dependências do Bot Framework.
        
        Args:
            adapter: BotFrameworkAdapter configurado
            app_id: ID da aplicação do bot
            conversation_storage: ConversationReferenceStorage instance
        """
        self.adapter = adapter
        self.app_id = app_id
        self.conversation_storage = conversation_storage  # Storage object, não dict
        self.logger = logging.getLogger("BotSender")
    
    async def send_message(self, user_id: str, message: str) -> bool:
        """
        Envia mensagem proativa para um usuário específico.
        
        Args:
            user_id: ID do usuário no Teams
            message: Mensagem a ser enviada
            
        Returns:
            bool: True se enviado com sucesso, False caso contrário
        """
        # Usa o storage em tempo real, não uma cópia
        cref_data = self.conversation_storage.get(user_id)
        if not cref_data:
            self.logger.warning(f"Nenhuma referência para user_id={user_id}")
            return False
        
        # Reconstrói ConversationReference a partir dos dados salvos
        try:
            if isinstance(cref_data, dict):
                cref = ConversationReference().deserialize(cref_data)
            else:
                cref = cref_data  # Já é ConversationReference
        except Exception as e:
            self.logger.error(f"Erro ao deserializar referência para {user_id}: {e}")
            return False
            
        try:
            # Trust service URL para evitar erros de autenticação
            MicrosoftAppCredentials.trust_service_url(cref.service_url)
            
            # Define callback que será executado no contexto da conversa
            async def _send_callback(turn_context: TurnContext):
                await turn_context.send_activity(message)
                
            # Continua a conversa usando a referência armazenada
            await self.adapter.continue_conversation(cref, _send_callback, self.app_id)
            self.logger.info(f"Mensagem enviada com sucesso para user_id={user_id}")
            return True
        except Exception as e:
            self.logger.error(f"Falha ao enviar mensagem para user_id={user_id}: {e}", exc_info=True)
            return False

def mapear_apelido_para_teams_id(apelido: str) -> Optional[str]:
    """
    Mapeia apelido do responsável G-Click para ID do usuário no Teams.
    
    Em produção, isto poderia consultar uma tabela de mapeamento no banco de dados.
    """
    # Exemplo de mapeamento (substitua pelos seus mapeamentos reais)
    mapeamento = {
        "mauricio.bernej": "29:1xxxxx-yyyy-zzzz",  # Substitua pelos IDs reais
        "eliels.glip": "29:2xxxxx-yyyy-zzzz",      # Substitua pelos IDs reais
        # Adicione outros mapeamentos conforme necessário
    }
    return mapeamento.get(apelido.lower())

class ConversationReferenceStorage:
    """Armazenamento persistente para referências de conversação."""
    
    def __init__(self, file_path="storage/conversation_references.json"):
        self.file_path = file_path
        self.references = self._load()
        
    def _load(self):
        """Carrega referências do arquivo."""
        path = Path(self.file_path)
        if path.exists():
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                logging.error(f"Erro ao carregar referências: {e}")
        return {}
        
    def save(self):
        """Salva referências no arquivo com serialização correta."""
        path = Path(self.file_path)
        os.makedirs(path.parent, exist_ok=True)
        
        try:
            # Serializa ConversationReference objects para dict antes de salvar
            serializable_refs = {}
            for user_id, cref in self.references.items():
                if hasattr(cref, 'serialize'):
                    # É um ConversationReference object
                    serializable_refs[user_id] = cref.serialize()
                else:
                    # Já é um dict
                    serializable_refs[user_id] = cref
                    
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(serializable_refs, f, indent=2, ensure_ascii=False)
                
            logging.info(f"Referências salvas: {len(serializable_refs)} entries em {self.file_path}")
        except Exception as e:
            logging.error(f"Erro ao salvar referências: {e}")
            
    def add(self, user_id, reference):
        """Adiciona/atualiza referência e salva."""
        # Armazena a referência original (ConversationReference ou dict)
        self.references[user_id] = reference
        self.save()
        logging.info(f"Referência adicionada para user_id={user_id}")
        
    def get(self, user_id):
        """Obtém referência por ID."""
        return self.references.get(user_id)
        
    def list_users(self):
        """Lista todos os user_ids com referências salvas."""
        return list(self.references.keys())
        
    def remove(self, user_id):
        """Remove referência de um usuário."""
        if user_id in self.references:
            del self.references[user_id]
            self.save()
            return True
        return False
