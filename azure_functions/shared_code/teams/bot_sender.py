import os
import json
import logging
import asyncio
from typing import Optional, Union
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
        
        # Validações robustas no construtor
        if not self.adapter:
            self.logger.error("❌ BotFrameworkAdapter não fornecido!")
            
        if not self.app_id:
            self.logger.warning("⚠️ app_id não fornecido - mensagens proativas podem falhar")
            
        if self.conversation_storage:
            if hasattr(self.conversation_storage, 'store_conversation_reference'):
                self.logger.info("✅ ConversationReferenceStorage VÁLIDO conectado ao BotSender")
            else:
                self.logger.error("❌ ConversationReferenceStorage INVÁLIDO - métodos ausentes!")
        else:
            self.logger.warning("⚠️ ConversationReferenceStorage não fornecido - funcionalidade limitada")
    
    async def send_message(self, user_id: str, message: str, card_json: Optional[Union[str, dict]] = None) -> bool:
        """
        Envia mensagem proativa para um usuário específico.
        
        Args:
            user_id: ID do usuário no Teams
            message: Mensagem a ser enviada (pode ser texto simples ou fallback para card)
            card_json: JSON de um Adaptive Card (opcional)
            
        Returns:
            bool: True se enviado com sucesso, False caso contrário
        """
        # Verificar se conversation_storage está disponível
        if not self.conversation_storage:
            self.logger.warning(f"ConversationStorage não configurado - não é possível enviar para {user_id}")
            return False
            
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
                if card_json:
                    # Envio como cartão adaptativo (tolerante a str ou dict)
                    try:
                        if isinstance(card_json, str):
                            card_data = json.loads(card_json)
                        elif isinstance(card_json, dict):
                            card_data = card_json
                        else:
                            raise TypeError("card_json must be str or dict")

                        card_attachment = Attachment(
                            content_type="application/vnd.microsoft.card.adaptive",
                            content=card_data
                        )
                        activity = Activity(
                            type="message",
                            text=message,  # fallback
                            attachments=[card_attachment]
                        )
                        resp = await turn_context.send_activity(activity)
                        self.logger.info(f"Cartão adaptativo enviado para {user_id} id={getattr(resp, 'id', None)}")
                        # tentar gravar id da activity no storage
                        try:
                            if getattr(resp, 'id', None):
                                existing = self.references.get(user_id, {})
                                if isinstance(existing, dict):
                                    existing.setdefault('last_activity', {})
                                    existing['last_activity']['id'] = resp.id
                                    existing['last_activity']['timestamp'] = datetime.utcnow().isoformat()
                                    self.references[user_id] = existing
                                    self.save()
                        except Exception:
                            self.logger.debug("Falha ao salvar last_activity", exc_info=True)
                    except Exception as e:
                        self.logger.error(f"Erro ao enviar cartão: {e}")
                        await turn_context.send_activity(message)  # fallback de texto
                else:
                    await turn_context.send_activity(message)
                
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

    def send_direct_message(self, activity_body: dict, text: str) -> None:
        """Apenas um wrapper síncrono para enviar resposta direta ao autor da activity."""
        try:
            user_id = (activity_body or {}).get("from", {}).get("id")
            if not user_id:
                self.logger.warning("send_direct_message: from.id ausente no payload")
                return
            
            # Enviar de forma segura em qualquer thread
            try:
                import asyncio
                try:
                    loop = asyncio.get_running_loop()
                    loop.create_task(self.send_message(user_id, text))
                except RuntimeError:
                    asyncio.run(self.send_message(user_id, text))
            except Exception as e:
                self.logger.error(f"send_direct_message falhou: {e}", exc_info=True)
        except Exception as e:
            self.logger.error(f"send_direct_message falhou: {e}", exc_info=True)

class ConversationReferenceStorage:
    """Armazenamento persistente para referências de conversação."""
    
    def __init__(self, file_path=None):
        # Usar caminho absoluto baseado no diretório do projeto para compatibilidade com Azure
        if file_path is None:
            project_root = Path(__file__).parent.parent
            file_path = project_root / "storage" / "conversation_references.json"
        self.file_path = file_path
        self.logger = logging.getLogger("ConversationReferenceStorage")
        self.logger.info("🗂️  Inicializando storage em: %s", self.file_path)
        self.references = self._load()
        self.logger.info("🗂️  Storage inicializado com %d referências", len(self.references))
        
    def _load(self):
        """Carrega referências do arquivo."""
        path = Path(self.file_path)
        self.logger.info("🗂️  Tentando carregar de: %s (existe: %s)", path, path.exists())
        if path.exists():
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                self.logger.info("🗂️  Carregadas %d referências do arquivo", len(data))
                return data
            except Exception as e:
                self.logger.error("💥 Erro ao carregar referências: %s", e)
        else:
            self.logger.info("🗂️  Arquivo não existe, inicializando storage vazio")
        return {}
        
    def save(self):
        """Salva referências no arquivo com serialização correta e tratamento de erro robusto."""
        path = Path(self.file_path)
        self.logger.info("💾 Salvando %d referências em: %s", len(self.references), path)
        
        try:
            # Garantir que o diretório pai existe
            os.makedirs(path.parent, exist_ok=True)
            
            # Serializa ConversationReference objects para dict antes de salvar
            serializable_refs = {}
            for user_id, cref in self.references.items():
                try:
                    if hasattr(cref, 'serialize') and callable(getattr(cref, 'serialize')):
                        # É um ConversationReference object com método serialize
                        serializable_refs[user_id] = cref.serialize()
                        self.logger.debug("🔄 Serializado ConversationReference para user_id=%s", user_id)
                    elif isinstance(cref, dict):
                        # Já é um dict - verificar se é válido
                        serializable_refs[user_id] = cref
                        self.logger.debug("📋 Dict mantido para user_id=%s", user_id)
                    else:
                        # Tipo desconhecido - tentar converter para dict
                        self.logger.warning("⚠️ Tipo não reconhecido para user_id=%s: %s", user_id, type(cref))
                        serializable_refs[user_id] = dict(cref) if hasattr(cref, '__dict__') else str(cref)
                except Exception as serialize_err:
                    self.logger.error("💥 Erro ao serializar user_id=%s: %s", user_id, serialize_err)
                    # Pular este item em vez de falhar completamente
                    continue
                    
            # Salvar com backup se arquivo já existe
            backup_path = None
            if path.exists():
                backup_path = path.with_suffix('.json.backup')
                try:
                    import shutil
                    shutil.copy2(path, backup_path)
                    self.logger.debug("📋 Backup criado: %s", backup_path)
                except Exception as backup_err:
                    self.logger.warning("⚠️ Falha ao criar backup: %s", backup_err)
            
            # Salvar arquivo principal
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(serializable_refs, f, indent=2, ensure_ascii=False, default=str)
                
            self.logger.info("✅ Referências salvas: %d entries em %s", len(serializable_refs), self.file_path)
            
            # Remover backup se salvamento foi bem-sucedido
            if backup_path and backup_path.exists():
                try:
                    backup_path.unlink()
                    self.logger.debug("🗑️ Backup removido após salvamento bem-sucedido")
                except Exception:
                    pass  # Não é crítico se falhar
                    
        except Exception as e:
            self.logger.error("💥 Erro crítico ao salvar referências: %s", e, exc_info=True)
            # Se falhou mas existe backup, tentar restaurar
            if backup_path and backup_path.exists():
                try:
                    import shutil
                    shutil.copy2(backup_path, path)
                    self.logger.info("🔄 Backup restaurado após falha no salvamento")
                except Exception as restore_err:
                    self.logger.error("💥 Falha também na restauração do backup: %s", restore_err)
            
    def store_conversation_reference(self, user_id: str, conversation_data: dict = None, **kwargs):
        """
        Armazena referência de conversa com dados estruturados e robustos.
        
        Args:
            user_id: ID do usuário no Teams
            conversation_data: Dados estruturados da conversa (nova API)
            **kwargs: Compatibilidade com API antiga (conversation_id, service_url, etc.)
        """
        self.logger.info("💾 store_conversation_reference chamado para user_id=%s", user_id)
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
                        "bot": {
                            "id": activity_data.get("recipient", {}).get("id"),
                            "name": activity_data.get("recipient", {}).get("name"),
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
            self.logger.info("✅ ConversationReference robusta armazenada para user_id=%s", user_id)
            
        except Exception as e:
            self.logger.error("💥 Erro ao armazenar ConversationReference para %s: %s", user_id, e, exc_info=True)

    def get_conversation_reference(self, user_id: str):
        """
        Obtém referência de conversa por ID, compatível com formatos antigo e novo.
        
        Args:
            user_id: ID do usuário no Teams
            
        Returns:
            dict ou ConversationReference: Dados da conversa ou None se não encontrado
        """
        self.logger.info("🔍 get_conversation_reference chamado para user_id=%s", user_id)
        ref_data = self.references.get(user_id)
        if not ref_data:
            self.logger.warning("⚠️  Nenhuma referência encontrada para user_id=%s", user_id)
            return None
            
        try:
            # Verificar se é formato novo (v2.0)
            if isinstance(ref_data, dict) and ref_data.get("version") == "2.0":
                self.logger.info("✅ Retornando ConversationReference v2.0 para user_id=%s", user_id)
                return ref_data["conversation_data"]
            
            # Formato antigo ou ConversationReference object
            self.logger.info("✅ Retornando ConversationReference legado para user_id=%s", user_id)
            return ref_data
            
        except Exception as e:
            self.logger.error("💥 Erro ao recuperar ConversationReference para %s: %s", user_id, e, exc_info=True)
            return None
        
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
                bot = conv_data.get("bot", {})
                
                # Criar ConversationReference básico para compatibilidade (inclui bot)
                cref_dict = {
                    "user": {
                        "id": user.get("id"),
                        "name": user.get("name"),
                        "aadObjectId": user.get("aad_object_id")
                    },
                    "bot": {
                        "id": bot.get("id"),
                        "name": bot.get("name"),
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
    
    def list_all_references(self):
        """Lista todas as referências de conversa com metadados."""
        return dict(self.references)
        
    def remove(self, user_id):
        """Remove referência de um usuário."""
        if user_id in self.references:
            del self.references[user_id]
            self.save()
            return True
        return False

    async def update_card(self, user_id: str, activity_id: str, card_json: str, fallback_message: str = "Notificação do G-Click") -> bool:
        """
        Atualiza um cartão previamente enviado (replace/update activity) usando a activity id.
        """
        cref_data = self.get(user_id)
        if not cref_data:
            self.logger.warning("update_card: referência não encontrada for %s", user_id)
            return False

        try:
            if isinstance(cref_data, dict) and cref_data.get('version') == '2.0':
                conv = cref_data.get('conversation_data', cref_data)
            else:
                conv = cref_data
            cref = ConversationReference().deserialize(conv)
        except Exception as e:
            self.logger.error("update_card: erro ao desserializar cref: %s", e, exc_info=True)
            return False

        try:
            MicrosoftAppCredentials.trust_service_url(cref.service_url)

            async def _update_cb(turn_context: TurnContext):
                try:
                    card_data = json.loads(card_json) if isinstance(card_json, str) else card_json
                    card_attachment = Attachment(content_type="application/vnd.microsoft.card.adaptive", content=card_data)
                    activity = Activity(type="message", id=activity_id, text=fallback_message, attachments=[card_attachment])
                    await turn_context.update_activity(activity)
                    self.logger.info("update_card: atualizado %s id=%s", user_id, activity_id)
                    return True
                except Exception as e:
                    self.logger.error("update_card: falha ao atualizar: %s", e, exc_info=True)
                    return False

            await self.adapter.continue_conversation(cref, _update_cb, self.app_id)
            return True
        except Exception as e:
            self.logger.error("update_card: erro ao executar continue_conversation: %s", e, exc_info=True)
            return False
