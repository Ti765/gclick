import os
import json
import logging
import asyncio
from typing import Optional
from pathlib import Path
from datetime import datetime

from botbuilder.core import BotFrameworkAdapter, TurnContext
from botbuilder.schema import Activity, ConversationReference, Attachment
from botframework.connector.auth import MicrosoftAppCredentials

# REMOVIDO: from teams.user_mapping import mapear_apelido_para_teams_id
# (import não usado neste arquivo)

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
    
    async def send_message(self, user_id: str, message: str, card_json: Optional[str] = None) -> bool:
        """
        Envia mensagem proativa para um usuário específico.
        
        Args:
            user_id: ID do usuário no Teams
            message: Mensagem a ser enviada (pode ser texto simples ou fallback para card)
            card_json: JSON de um Adaptive Card (opcional)
            
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
                response = None
                if card_json:
                    # Envio como cartão adaptativo
                    try:
                        card_data = json.loads(card_json)
                        card_attachment = Attachment(
                            content_type="application/vnd.microsoft.card.adaptive",
                            content=card_data
                        )
                        activity = Activity(
                            type="message",
                            text=message,  # Texto de fallback caso o card não renderize
                            attachments=[card_attachment]
                        )
                        response = await turn_context.send_activity(activity)
                        self.logger.info(f"Cartão adaptativo enviado para {user_id}")
                    except json.JSONDecodeError as e:
                        self.logger.error(f"Erro ao parsear JSON do cartão: {e}")
                        response = await turn_context.send_activity(message)
                    except Exception as e:
                        self.logger.error(f"Erro ao enviar cartão: {e}")
                        response = await turn_context.send_activity(message)
                else:
                    # Envio como mensagem texto simples
                    response = await turn_context.send_activity(message)

                # Tentar gravar o id da activity no conversation_storage se disponível
                try:
                    if response and hasattr(response, 'id') and response.id and self.conversation_storage:
                        # Normalizar storage para suportar dict ou objeto com .references
                        # Se for dict-like storage (ConversationReferenceStorage in this module)
                        if hasattr(self.conversation_storage, 'references') and isinstance(self.conversation_storage.references, dict):
                            existing = self.conversation_storage.references.get(user_id, {})
                            if isinstance(existing, dict):
                                existing.setdefault('last_activity', {})
                                existing['last_activity']['id'] = response.id
                                existing['last_activity']['timestamp'] = datetime.utcnow().isoformat()
                                self.conversation_storage.references[user_id] = existing
                                # tentar persistir
                                if hasattr(self.conversation_storage, 'save'):
                                    try:
                                        self.conversation_storage.save()
                                    except Exception:
                                        self.logger.debug("Falha ao salvar conversation_storage após atualizar last_activity", exc_info=True)
                except Exception:
                    # Não obrigar a persistência se falhar
                    self.logger.debug("Não foi possível salvar last_activity no storage para %s", user_id, exc_info=True)
                
            # Continua a conversa usando a referência armazenada
            await self.adapter.continue_conversation(cref, _send_callback, self.app_id)
            self.logger.info(f"Mensagem enviada com sucesso para user_id={user_id}")
            return True
        except Exception as e:
            self.logger.error(f"Falha ao enviar mensagem para user_id={user_id}: {e}", exc_info=True)
            return False
    
    async def send_card(self, user_id: str, card_json: str, fallback_message: str = "Notificação do G-Click") -> bool:
        """
        Envia um cartão adaptativo para um usuário específico.
        
        Args:
            user_id: ID do usuário no Teams
            card_json: JSON do Adaptive Card
            fallback_message: Mensagem de fallback caso o cartão não seja suportado
            
        Returns:
            bool: True se enviado com sucesso, False caso contrário
        """
        return await self.send_message(user_id, fallback_message, card_json)

    async def update_card(self, user_id: str, activity_id: str, card_json: str, fallback_message: str = "Notificação do G-Click") -> bool:
        """
        Atualiza um cartão/adaptive card previamente enviado (replace/update activity).
        """
        cref_data = self.conversation_storage.get(user_id)
        if not cref_data:
            self.logger.warning(f"Nenhuma referência para user_id={user_id} (update_card)")
            return False

        try:
            if isinstance(cref_data, dict):
                cref = ConversationReference().deserialize(cref_data)
            else:
                cref = cref_data
        except Exception as e:
            self.logger.error(f"Erro ao deserializar referência para update_card {user_id}: {e}")
            return False

        try:
            MicrosoftAppCredentials.trust_service_url(cref.service_url)

            async def _update_callback(turn_context: TurnContext):
                try:
                    card_data = json.loads(card_json)
                    card_attachment = Attachment(
                        content_type="application/vnd.microsoft.card.adaptive",
                        content=card_data
                    )
                    activity = Activity(type="message", id=activity_id, text=fallback_message, attachments=[card_attachment])
                    await turn_context.update_activity(activity)
                    self.logger.info(f"Cartão atualizado para {user_id} activity_id={activity_id}")
                    return True
                except Exception as e:
                    self.logger.error(f"Erro ao atualizar cartão para {user_id}: {e}", exc_info=True)
                    return False

            await self.adapter.continue_conversation(cref, _update_callback, self.app_id)
            return True
        except Exception as e:
            self.logger.error(f"Falha ao atualizar mensagem para user_id={user_id}: {e}", exc_info=True)
            return False

class ConversationReferenceStorage:
    """Armazenamento persistente para referências de conversação."""
    
    def __init__(self, file_path=None):
        # Usar caminho absoluto baseado no diretório do projeto para compatibilidade com Azure
        if file_path is None:
            project_root = Path(__file__).parent.parent
            file_path = project_root / "storage" / "conversation_references.json"
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
            
    def store_conversation_reference(self, user_id: str, conversation_data: dict = None, **kwargs):
        """
        Armazena referência de conversa com dados estruturados e robustos.
        
        Args:
            user_id: ID do usuário no Teams
            conversation_data: Dados estruturados da conversa (nova API)
            **kwargs: Compatibilidade com API antiga (conversation_id, service_url, etc.)
        """
        try:
            if conversation_data:
                # Nova API: dados estruturados
                reference_data = {
                    "user_id": user_id,
                    "conversation_data": conversation_data,
                    "stored_at": datetime.utcnow().isoformat(),
                    "version": "2.0"
                }
            else:
                # API de compatibilidade: construir a partir de kwargs
                conversation_id = kwargs.get("conversation_id")
                service_url = kwargs.get("service_url", "")
                activity_data = kwargs.get("activity_data", {})
                
                if not conversation_id:
                    logging.warning(f"conversation_id ausente para user_id={user_id}")
                    return
                
                # Construir dados estruturados a partir da API antiga
                reference_data = {
                    "user_id": user_id,
                    "conversation_data": {
                        "user": {
                            "id": user_id,
                            "name": activity_data.get("from", {}).get("name", ""),
                            "aad_object_id": activity_data.get("from", {}).get("aadObjectId"),
                            "role": "user"
                        },
                        "conversation": {
                            "id": conversation_id,
                            "name": activity_data.get("conversation", {}).get("name"),
                            "conversation_type": activity_data.get("conversation", {}).get("conversationType", "personal"),
                            "tenant_id": activity_data.get("conversation", {}).get("tenantId")
                        },
                        "channel_id": activity_data.get("channelId", "msteams"),
                        "service_url": service_url,
                        "locale": activity_data.get("locale", "pt-BR"),
                        "timezone": activity_data.get("timezone", "America/Sao_Paulo"),
                        "last_activity": {
                            "type": activity_data.get("type"),
                            "timestamp": datetime.utcnow().isoformat(),
                            "id": activity_data.get("id")
                        }
                    },
                    "stored_at": datetime.utcnow().isoformat(),
                    "version": "2.0"
                }
            
            # Armazenar usando novo formato
            self.references[user_id] = reference_data
            self.save()
            logging.info(f"ConversationReference robusta armazenada para user_id={user_id}")
            
        except Exception as e:
            logging.error(f"Erro ao armazenar ConversationReference para {user_id}: {e}")

    def get_conversation_reference(self, user_id: str):
        """
        Obtém referência de conversa por ID, compatível com formatos antigo e novo.
        
        Args:
            user_id: ID do usuário no Teams
            
        Returns:
            dict ou ConversationReference: Dados da conversa ou None se não encontrado
        """
        ref_data = self.references.get(user_id)
        if not ref_data:
            return None
            
        # Verificar se é formato novo (v2.0)
        if isinstance(ref_data, dict) and ref_data.get("version") == "2.0":
            return ref_data["conversation_data"]
        
        # Formato antigo ou ConversationReference object
        return ref_data
        
    def add(self, user_id, reference):
        """Adiciona/atualiza referência e salva (compatibilidade com API antiga)."""
        # Armazena a referência original (ConversationReference ou dict)
        self.references[user_id] = reference
        self.save()
        logging.info(f"Referência adicionada para user_id={user_id}")
        
    def get(self, user_id):
        """Obtém referência por ID (compatibilidade com API antiga)."""
        ref_data = self.references.get(user_id)
        if not ref_data:
            return None
            
        # Para compatibilidade, retornar dados da conversa se for formato novo
        if isinstance(ref_data, dict) and ref_data.get("version") == "2.0":
            # Tentar reconstruir ConversationReference a partir dos dados estruturados
            try:
                conv_data = ref_data["conversation_data"]
                conversation = conv_data.get("conversation", {})
                user = conv_data.get("user", {})
                
                # Criar ConversationReference básico para compatibilidade
                cref_dict = {
                    "user": {
                        "id": user.get("id"),
                        "name": user.get("name"),
                        "aadObjectId": user.get("aad_object_id")
                    },
                    "conversation": {
                        "id": conversation.get("id"),
                        "name": conversation.get("name"),
                        "conversationType": conversation.get("conversation_type", "personal"),
                        "tenantId": conversation.get("tenant_id")
                    },
                    "channelId": conv_data.get("channel_id", "msteams"),
                    "serviceUrl": conv_data.get("service_url", ""),
                    "locale": conv_data.get("locale", "pt-BR")
                }
                return cref_dict
            except Exception as e:
                logging.warning(f"Erro ao converter formato novo para antigo: {e}")
                return ref_data
        
        # Formato antigo
        return ref_data
        
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
