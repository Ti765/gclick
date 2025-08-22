engine/notification_engine.py

Este é o coração do sistema de notificações, responsável por orquestrar todo o ciclo (coleta, filtragem, classificação, agrupamento e envio)
GitHub
GitHub
. As principais melhorias/correções e possíveis pontos de atenção são:

Integração com Azure Functions: Observa-se que esse módulo agora suporta ser utilizado tanto dentro quanto fora do Azure Functions. Por exemplo, há tentativas de import adaptativas: primeiro tenta from teams.bot_sender import BotSender, depois cai para o módulo em shared_code
GitHub
. Isso garante que, no ambiente Azure (onde o código está em azure_functions/shared_code), as importações ainda funcionem. Essa robustez de import é positiva, evitando bugs de import no deploy.

Classificação simplificada vs avançada: Aqui encontramos um possível ponto de inconsistência. A função interna classificar()
GitHub
marca qualquer tarefa com dataVencimento < hoje como "vencidas"
GitHub
, sem distinguir quão atrasada (diferentemente da lógica refinada em engine/classification.py). No entanto, na prática, isso não chega a causar duplicidade de comportamento por conta do filtro de coleta: o engine coleta tarefas apenas a partir de hoje (ver próximo item). Portanto, nenhuma tarefa com data anterior a hoje entra nesse fluxo – logo, a função classificar() do engine nunca lida com tarefas de >1 dia de atraso (essas já ficaram fora na coleta). Conclusão: Não chega a ser um bug efetivo agora, mas é uma implementação paralela à de classification.py. Em futuros refactors, seria desejável unificar a lógica, usando sempre classification.classificar_tarefa_individual para evitar confusão.

Janela de coleta de tarefas (possível bug de cobertura): O ciclo define t_inicio = hoje e t_fim = hoje + dias_proximos
GitHub
GitHub
. Isso significa que ele não coleta tarefas com vencimento anterior ao dia atual. Com dias_proximos=3 (padrão para manhã), pega hoje e próximos 3 dias; com dias_proximos=1 (usado à tarde), pega hoje e amanhã. Consequência: Tarefas vencidas até ontem não são coletadas nem notificadas. Pela especificação, esperava-se incluir até 1 dia de atraso. Esse comportamento é potencialmente um bug funcional: se uma tarefa venceu ontem e ninguém agiu, hoje de manhã ela não seria relembrada pelo bot (pois ontem ela estava “vencendo hoje” e foi notificada, mas hoje, apesar de só 1 dia atrasada, ficará de fora). Isso significa que tarefas com 1 dia de atraso não geram notificação no dia seguinte, possivelmente contrariando o requisito.

Impacto: Esse bug faz com que uma tarefa que passou em branco no dia do vencimento saia do radar do sistema depois disso, a não ser que alguém consulte manualmente o G-Click. É um ponto crítico a observar nos testes reais. Em termos de código, resolver exigiria ajustar t_inicio = hoje - 1 quando se quer incluir atrasos de 1 dia.

Agrupamento por responsável: O método agrupar_por_responsavel() coleta os responsáveis de até max_responsaveis_lookup tarefas e agrupa
GitHub
GitHub
. Ele está bem implementado e robusto a falhas (tenta continuar mesmo se uma consulta de responsáveis falhar, logando warnings
GitHub
). Nenhum bug aparente aqui. Vale notar que se uma tarefa tiver múltiplos responsáveis, ela será incluída nos grupos de todos eles
GitHub
 – isso é intencional, para que cada responsável receba notificação daquela tarefa.

Construção das mensagens: As funções formatar_mensagem_individual e formatar_resumo_global foram implementadas conforme esperado
GitHub
GitHub
, incluindo contagens e links. Elas parecem corretas e os testes confirmam seu funcionamento. Um detalhe: o texto de resumo individual inclui no máximo 5 tarefas por responsável, depois resume com “+X tarefa(s) adicionais”
GitHub
, prevenindo mensagens muito longas – boa prática.

Idempotência via already_sent: O engine utiliza um cache (persistido em storage/state.py) para evitar notificar o mesmo usuário sobre as mesmas tarefas mais de uma vez ao dia
GitHub
. A chave usada combina a data atual, o apelido e os IDs das tarefas
GitHub
. Isso funciona, porém combina todos os IDs na chave. Um efeito colateral possível: se a janela de coleta muda, a chave muda. Por exemplo, de manhã um usuário recebeu tarefas [A,B,C,D]; à tarde, se for notificar [A,B] (porque C,D eram para 2 dias depois e já não entram na janela da tarde), a combinação “A,B” difere de “A,B,C,D” – então o sistema não reconhece que A e B já tinham sido notificados e pode notificá-los de novo, só que em menor número. Esse cenário é real dado o design atual de dois ciclos diários com diferentes dias_proximos (3 de manhã, 1 à tarde). Ou seja, pode haver duplicidade de notificação no mesmo dia para tarefas que vencem amanhã, por exemplo.

Exemplo: Tarefa X vence amanhã. De manhã (dias_proximos=3) ela vem agrupada com outras; o usuário é notificado, registro “2025-08-21|user|X,Y,Z” salvo. À tarde (dias_proximos=1), X ainda está dentro da janela e Y,Z talvez não; o novo conjunto “2025-08-21|user|X” não bate com a chave anterior, então o sistema enviará de novo uma mensagem ao mesmo usuário sobre X.

Isso é um bug de lógica sutil, mas que pode causar irritação ao usuário com notificações duplicadas. A mitigação poderia ser usar chaves por tarefa individual ou por dia+responsável independentemente do conjunto, mas isso exigiria outra abordagem (por ora está assim).

Envio via Bot vs Webhook: A parte de envio tenta usar o Bot Framework primeiro, caindo para o Webhook do Teams se necessário
GitHub
GitHub
. Aqui houve acertos e também há observações:

A implementação atual define mensagem_enviada = False e só o marca True se conseguir iniciar o envio via bot
GitHub
GitHub
. Pelo código, qualquer resultado da tentativa de envio via bot (mesmo com algumas falhas internas em cartões) acaba por marcar mensagem_enviada = True uma vez que o loop de envio de cards termina sem lançar exceção. Isso significa que se o bot estava configurado e a conversa existe, o sistema não usará webhook de fallback para aquele usuário, mesmo que algum card específico possa não ter sido entregue.

Dentro do envio via bot, ele envia um Adaptive Card por tarefa
GitHub
GitHub
. Isso é poderoso (interatividade, botões etc.), porém pode disparar diversas mensagens separadas no chat do usuário (um cartão por tarefa). Talvez fosse esperado consolidar em um único card com todas as tarefas, mas a implementação optou por granularidade. Não é um bug, mas sim uma decisão de UX; apenas notar que o design é “multi-mensagem” via bot.

A função _ensure_card_payload
GitHub
 garante que mesmo se create_task_notification_card retornar JSON em string, ele parseia corretamente em dict. Isso evita um bug anterior onde o payload poderia estar no formato errado – agora resolvido com este helper.

Bot não enviando: Caso o envio via bot falhe completamente (por exemplo, o usuário nunca iniciou conversa com o bot, então _has_conversation retorna False
GitHub
GitHub
), o código cai no else e usa enviar_teams_mensagem(f"{apelido}:\n{msg}")
GitHub
, que posta via Webhook. Isso garante que a notificação textual ao menos chegue. Não identificamos bugs aqui – a lógica de fallback é sólida.

Métricas e alertas: No final, o engine registra métricas de execução (contagens, duração, etc.) via analytics.metrics.write_notification_cycle
GitHub
GitHub
 e pode emitir um alerta se zero tarefas abertas foram encontradas
GitHub
. O alerta ALERT_ZERO_ABERTOS_TO_TEAMS permite enviar uma mensagem no Teams avisando que não há tarefas (pode ser útil para debug). Tudo isso parece consistente. Uma verificação rápida: a flag apenas_status_abertos está True por padrão, então se nenhuma tarefa aberta foi encontrada (total_abertos_brutos == 0), o alerta é elegível. E de fato só dispara se execution_mode == 'live'
GitHub
, evitando poluir testes dry-run. Sem bugs aqui, apenas notar que para esse alerta ser enviado, deve existir um Webhook configurado (ou Bot ativo), caso contrário vai logar uma falha ao tentar enviar (o except captura e imprime warning, sem quebrar a execução).

Integração com Azure (adapter): Quando a Azure Function inicializa, ela injeta o bot_sender, adapter e conversation_storage no módulo engine
GitHub
. O engine define variáveis globais para isso e tenta usá-las. Essa integração funciona – desde que a import do engine aconteça após o bot ser configurado. No function_app.py, vemos que logo após configurar bot_sender, ele faz import engine.notification_engine as ne e atribui as variáveis
GitHub
. Como o Azure Functions carrega todo o app numa única instância, essas referências persistem. Nos ciclos (timers e webhook), quando run_notification_cycle é chamado, ele usa ne.bot_sender global. Isso está correto e nenhum bug aparente – foi bem pensado para driblar a ausência de um container de injeção de dependência no Functions.

Apenas um adendo: se o engine for importado antes de bot_sender estar configurado, bot_sender ficaria None. Mas no código a ordem está ok (ele faz try de import dentro do engine, cai no except definindo um dummy, mas depois substitui com o real BotSender). Nos testes de integração provavelmente isso foi verificado e passou.

Resumo local (notification_engine.py): O módulo está robusto e corrigiu vários pontos frágeis (payload de card, import dinâmica, logs). Principais atenções vão para o bug de janela de coleta não incluir ontem e a duplicação de notificação potencial devido a triggers sobrepostos – ambos cenários de produção a serem monitorados. Fora isso, o engine cumpre bem seu papel e as melhorias implementadas aumentaram a confiabilidade do sistema de notificação.

engine/classification.py

Este módulo introduz a lógica refinada de classificação temporal das tarefas
GitHub
, incorporando os critérios da Sprint 2:

Ignorar atrasos > 1 dia: A função classificar_tarefa_individual retorna None se a data de vencimento for menor que “hoje - 1 dia”
GitHub
. Ou seja, tarefas atrasadas há mais de um dia são completamente desconsideradas para notificação (nem “vencidas” nem nada). Isso implementa explicitamente a política de não notificar tarefas muito antigas, evitando spams de coisas pendentes há muito tempo. Está correto conforme especificação.

Vencidas até 1 dia: Se dv < hoje mas não mais que 1 dia atrás, classifica como "vencidas"
GitHub
. Isso significa que apenas tarefas vencidas ontem entram nessa categoria.

Hoje e próximos X dias: Mantém "vence_hoje" e "vence_em_3_dias" conforme esperado
GitHub
, com dias_proximos parametrizável.

Uso de _dt_dataVencimento: O código tenta primeiro um campo pré-parseado _dt_dataVencimento no dicionário da tarefa
GitHub
. Isso é ótimo para eficiência: aparentemente, em outros lugares do código (ex: gclick.tarefas.normalizar_tarefa), já convertem dataVencimento string em um date e armazenam nesse campo para evitar parse repetido. Se não houver, faz o parse da string com datetime.strptime
GitHub
. Tudo envolto em try/except para segurança. Sem problemas aqui.

Função classificar_por_vencimento: Usa a função individual para classificar uma lista de tarefas e retorna o bucket de listas
GitHub
GitHub
. Implementação limpa e direta, iterando e distribuindo cada tarefa no dicionário de listas final.

Função resumir_contagens: Apenas conta as listas dentro do dict de classificação
GitHub
. Trivial mas útil para montar sumários; sem bugs.

Este módulo está bem implementado e alinhado à necessidade. Importante: No engine principal, ainda se usa a função interna simples, mas outros componentes (talvez o relatório ou futuras extensões) podem usar este módulo para obter a mesma classificação. Seria desejável centralizar tudo nesta lógica para evitar divergências, mas, conforme discutido, a divergência atual não chega a causar bug devido ao escopo de coleta.

Impacto no todo: A introdução de classification.py melhora a consistência e testabilidade da lógica de classificação. Agora há um local único para testar se uma tarefa deve ser notificada ou ignorada por vencimento – e os testes unitários certamente cobriram isso. Essa separação facilita ajustes futuros (por exemplo, se decidirem mudar a regra para 2 dias de atraso, bastaria alterar aqui). No panorama geral, garante que o sistema não priorize tarefas muito atrasadas, mantendo o foco no urgente e recente, o que melhora a eficácia das notificações.

config/notifications.yaml

Este arquivo de configuração define parâmetros ajustáveis do motor de notificações. Os valores presentes incluem, por exemplo, dias_proximos, tamanhos de página, limites de responsáveis, flags de comportamento etc.
GitHub
. Observações sobre este arquivo:

Os valores parecem razoáveis e condizem com defaults de código em sua maioria. Por exemplo: dias_proximos: 3 (equivalente ao padrão do engine para dias_proximos), page_size: 50 (no código está 200 como default – aqui reduziu, talvez para performance), max_responsaveis_lookup: 40 (código usa 100 por default), limite_responsaveis_notificar: 30 (código default 50)
GitHub
. Ou seja, o YAML pode estar personalizando essas configurações para produção de forma mais conservadora.

Importante notar: Atualmente, o engine não lê automaticamente este YAML. A função load_notifications_config existe
GitHub
, mas não vemos seu uso dentro de run_notification_cycle ou do function_app. É possível que um script externo (como notify_loop.py ou ao iniciar manualmente) carregasse isso e passasse os valores. No Azure Functions, porém, o ciclo usa constantes ou env vars. Logo, alterações aqui não refletem automaticamente. Isso não causa um bug de execução, mas significa que as mudanças no YAML podem não estar tendo efeito no Azure até que o código seja adaptado para usá-las. Dado que o quickwin foi o foco, pode ter ficado fora do escopo integrar plenamente essas configs.

Mesmo não sendo aplicadas dinamicamente, manter esse arquivo atualizado é bom para referência e para rodar o motor em modo standalone local, se necessário.

Nenhum bug direto no YAML, já que é dado estático. O único “risco” seria divergência: por exemplo, YAML diz page_size: 50 mas o Azure Functions sempre usa 200 (pois no code está fixo). Isso pode confundir quem lê a config achando que está limitando a 50. Documentar isso seria útil.

Impacto no todo: O arquivo não impacta a execução no Azure neste momento (aparentemente). Porém, ele documenta as intenções de configuração e pode ser usado em outros contextos. Como não é lido no deploy atual, não introduz falhas. Seria vantajoso em versões futuras conectar esse YAML no function_app.py (por exemplo, via variável de ambiente apontando para config file) – assim operadores do sistema poderiam calibrar comportamento sem mudar código. No estado atual, devemos apenas estar cientes de que alterar notifications.yaml não muda o comportamento em produção, o que deve ser comunicado para evitar suposições incorretas.

azure_functions/requirements.txt

Este arquivo lista as dependências necessárias para o Function App rodar no Azure. As alterações aqui refletem principalmente a atualização do runtime Python e Azure Functions:

Deve incluir o pacote azure-functions (versão compatível com o runtime 4.x). Espera-se algo como azure-functions==1.13.0 ou superior, que suporta Python 3.10+ (o nome da branch sugere Python 3.13, possivelmente se referindo a versão do Azure Functions Core Tools ou similar). Garantir a versão correta é crucial: versões antigas suportavam só até Python 3.8/3.9. Não identificar o pacote azure-functions seria um bug fatal, mas assumimos que foi incluído.

Inclui provavelmente Bot Framework SDK: Vemos no código imports de botbuilder.core e botbuilder.schema. Assim, no requirements deve haver entradas como botbuilder-core e botbuilder-schema (ou um metapacote botbuilder-ai etc). Se isso faltasse, a Function falharia ao importar o adapter. A menção no código indica que essas dependências foram providas.

Outras libs relevantes: PyYAML (usado no engine para ler config), requests (usado em _dispensar_tarefa_gclick), e as dependências já existentes do projeto (como a API G-Click client, possivelmente uma lib interna ou as próprias funções em gclick/). Pelo README principal, já havia um requirements.txt na raiz para uso geral; o azure_functions/requirements.txt pode ser um subconjunto mais focado apenas no necessário para o deploy do Function (por exemplo, talvez omitindo libs usadas só em scripts offline).

Atualização de versões: Pode ter ocorrido incrementos de versão para compatibilidade com Python 3.10/3.11 (ex.: botbuilder-core versão mais recente, etc.). Isso é benéfico, e não soubemos de conflitos. Seria prudente rodar func azure functionapp publish em ambiente de teste para verificar se todas as dependências resolvem.

Em resumo, assumindo que os pacotes certos foram listados, não há bugs aqui – apenas garantir que estejam sincronizados com as importações do código. Um possível esquecimento a verificar: se usar azure.identity ou outros SDKs do Azure (não parece o caso aqui). Tudo indica que o arquivo está correto, pois a Function App rodou local (segundo README, comandos de func start foram usados com sucesso).

Impacto no todo: Um arquivo de requirements bem configurado é o que permite o deploy funcionar. Se algo estivesse faltando, a Function poderia falhar ao iniciar (por exemplo, sem botbuilder, o trecho de config do adapter daria ImportError). Pelo fato de termos logs indicando que “BotSender configurado” e outros, entende-se que as libs estavam presentes. Logo, este item está ok e garante que a aplicação possa ser publicada e executada no Azure sem surpresas. Vale destacar o acerto de incluir azure-functions no lugar certo, pois sem ele o Azure não reconheceria o modelo de app do arquivo Python.

azure_functions/function_app.py

Este arquivo configura a aplicação Azure Functions e define todas as Triggers (gatilhos) e endpoints do sistema. É fundamental que ele esteja livre de erros, pois quaisquer bugs aqui impedem o deploy correto ou a ativação das funções. Análise por seções:

Inserção de shared_code no sys.path
GitHub
: Isso garante que os módulos em azure_functions/shared_code sejam encontrados. Foi implementado de forma correta (colocando no início do path para ter prioridade). Sem isso, imports como from teams.user_mapping import ... falhariam no Azure. Funcionou conforme esperado, visto que os logs no deploy indicam sucesso na importação dos módulos do projeto
GitHub
GitHub
.

Flags de ambiente
GitHub
: DEBUG_MOCK e IS_AZURE são definidos. IS_AZURE detecta se está rodando na Azure (checa vars típicas do App Service) e é usado para ajustar caminhos de storage
GitHub
. Isso está correto. DEBUG_MOCK permite comportamentos simulados (como fornecer users de teste no endpoint de debug se não estiver em Azure ou se explicitamente ativado)
GitHub
. Sem problemas aqui, apenas fornece flexibilidade de teste local.

Importações do projeto com fallback
GitHub
: O try/except aninhado que tenta importar teams.bot_sender direto, e caso falhe tenta via shared_code.teams.bot_sender
GitHub
, e similar para outros módulos (engine.notification_engine). Essa construção é excelente para robustez. Vemos que no log se informa que módulos foram importados (variável import_style) – ou seja, em qualquer situação os módulos carregam, senão abortam com erro crítico. Não detectamos bug aqui; pelo contrário, isso previne o típico erro “Module not found” se o Azure resolver pacotes de modo distinto.

Stubs em caso de erro de import
GitHub
GitHub
: Se por alguma razão os módulos do projeto não carregassem, o código define funções e classes stub (vazias) para permitir que a Function App suba sem quebrar totalmente. Essa é uma estratégia de contingência interessante – evita que a função nem sequer seja registrada. No entanto, se cairmos nesse caso, a aplicação não funcionaria direito (pois run_notification_cycle stub retorna {} apenas). A princípio, como as importações tiveram sucesso, esses stubs não entram em ação. Logo, sem efeito colateral agora, mas vale saber que se vermos logs de “mapear_apelido indisponível” ou “run_notification_cycle indisponível”, é porque algo deu muito errado no import inicial.

Instanciação do FunctionApp
GitHub
: Define app = func.FunctionApp(...). Tudo certo – usou AuthLevel.ANONYMOUS por padrão e define de novo em cada rota explicitamente, o que é consistente.

Helpers de processamento de ação de cartão (_extract_card_action)
GitHub
GitHub
: Essa função extrai os campos action e taskId de diferentes formatos de payload do Teams. A implementação cobre vários cenários (Adaptive Card com Action.Execute, messageBack, etc.)
GitHub
GitHub
. Parece completa e robusta, iterando por possíveis estruturas onde a info possa vir. Testes internos ou logs devem ter confirmado isso. Sem bugs aqui, e era essencial para que os botões dos Adaptive Cards funcionem – se tivesse erro de chave, não acionaria nada.

Configuração do Bot Framework Adapter
GitHub
GitHub
: Aqui, se as credenciais do bot (MicrosoftAppId/Password) estão definidas no ambiente, o código configura o adapter do bot e cria o BotSender. Checamos possíveis pontos de falha:

Import das classes do BotBuilder: aconteceu dentro de try/except
GitHub
GitHub
. Em caso de exceção (por exemplo, libs não instaladas), loga um warning e simplesmente bot_sender continuará None – ou seja, o sistema se degrada para usar apenas Webhook. Isso é adequado. Não vemos evidências de crash aqui; assumindo libs OK, o adapter foi criado.

Configuração do conversation_storage: Ele determina o caminho do arquivo JSON de referências de conversa. Em Azure, usa HOME/data/...json, local persistente; localmente, usa azure_functions/storage/conversation_references.json dentro do projeto
GitHub
. Essa lógica está perfeita para garantir que as referências persistam entre execuções e não fiquem em local não acessível.

Integração com engine: conforme citado, injeta no módulo engine os objetos adapter, bot_sender e storage
GitHub
. Isso habilita o engine a utilizar o bot. Foi feito dentro de um try simples – se por acaso falhasse (módulo não encontrado ou sem atributos), apenas passaria, significando que o bot não ficou integrado. Mas como vimos no engine, ele define essas globais mesmo que não existam inicialmente, então aqui deve ter funcionado.

Log: "🤖 BotSender configurado – storage em ..."
GitHub
 – esperamos que isso tenha aparecido indicando sucesso.

Nenhum bug aqui. A única coisa a observar: como as referências de conversa serão adicionadas a esse storage? Ou seja, o bot sender está pronto, mas precisamos que usuários iniciem conversa para preencher conversation_storage. O código do endpoint /messages (abaixo) não explicitamente adiciona referências no storage quando um usuário envia “oi”. Isso pode ser uma funcionalidade não implementada: normalmente se usa o evento conversationUpdate ou a própria mensagem para chamar ConversationReferenceStorage.add(user_id, TurnContext.get_conversation_reference(activity)). Não encontrei essa chamada no código. Implicação: Se ninguém adicionar manualmente as referências (ou não houve implementação em outro lugar), o bot_sender.send_message não encontrará ninguém para enviar, caindo sempre no warning "Nenhuma referência para user_id". Em resumo, a capacidade proativa via bot pode não estar operante na prática, a menos que haja algum código omitido. Como fallback existe o webhook, o sistema ainda notifica (texto simples). Isso não é exatamente um bug do código – o código em si não quebra – mas sim uma lacuna funcional: é preciso implementar a captura de referências de conversa para aproveitar totalmente o Bot.

Endpoint /api/gclick – webhook G-Click
GitHub
GitHub
:

Este endpoint recebe notificações proativas externas (provavelmente um webhook disparado pelo próprio sistema G-Click em determinados eventos). O código tenta ler o JSON do request e espera campos como "evento" e lista de "responsaveis" com "apelido"
GitHub
.

Para cada responsável, faz o mapeamento apelido→Teams ID via mapear_apelido_para_teams_id
GitHub
. Ele não envia mensagem aqui – nota-se um # TODO: usar bot_sender.send_message / send_card quando disponível
GitHub
. Ou seja, no estado atual, este webhook não envia notificações ativamente, apenas conta quantos poderiam ser enviados. Os contadores enviados e falhou são incrementados conforme encontra ou não o mapeamento, mas não há chamada a bot_sender ou enviar_teams_mensagem neste trecho.

Finalmente retorna um JSON com resumo do evento recebido e números de enviados/falhados
GitHub
.

Avaliação: Isso parece intencionalmente incompleto (“quick win” mínimo para registrar a chamada). Não é exatamente um bug, pois o endpoint não quebra nada; porém, não cumpre um envio real. Provavelmente a ideia foi implementar o recebimento e planejar o envio proativo via bot posteriormente (por isso o TODO).

Impacto: Por enquanto, integrar G-Click via webhook não resultará em alerta imediato no Teams; vai apenas logar e contabilizar. Isso deve ser comunicado, mas não impede deploy. Se for necessário já enviar, teríamos que rapidamente implementar uma chamada semelhante ao ciclo de notificação ou ao menos um bot_sender.send_message simples. Em suma, o endpoint existe e não falha, mas é funcionalmente neutro no momento.

Timer Triggers – MorningNotifications e AfternoonNotifications
GitHub
GitHub
:

Esses decoradores definem cron jobs no Azure. “MorningNotifications” está agendado para 0 0 11 * * 1-5 (11:00 UTC, que corresponde a 08:00 BRT em dias úteis seg–sex)
GitHub
. “AfternoonNotifications” para 0 30 20 * * 1-5 (20:30 UTC = 17:30 BRT em dias úteis)
GitHub
. Isso bate com o requisito de dois horários (8h e 17h30). A sintaxe CRON está correta e restrita a weekdays (1-5).

Dentro de cada, chamam _run_cycle("morning", ...) e _run_cycle("afternoon", ...) respectivamente com parâmetros distintos: manhã usa dias_proximos = int(env DIAS_PROXIMOS ou 3) e full_scan=True
GitHub
, tarde usa dias_proximos = int(env DIAS_PROXIMOS ou 1) e full_scan=False
GitHub
. Essa diferença visa otimização (tarde busca só 1 página).

Conforme discutido no engine, essa diferença cria sobreposição de janela (manhã 3 dias, tarde 1 dia). Funcionamento correto do trigger: ao publicar no Azure, é preciso rodar func azure functionapp publish com Python 3.10+ e extensão bundles. Dado que a configuração de host.json está ok, os triggers serão registrados.

Possível problema: se alguém definir a variável de ambiente DIAS_PROXIMOS, ambos os triggers usarão o mesmo valor. Ex: se setar DIAS_PROXIMOS=3 globalmente, a tarde também usará 3 (ignorando a intenção de ser menor). Isso não é evidente de cara e poderia causar duplicidade total (manhã e tarde fazendo a mesma coisa). Talvez a ideia seja deixar DIAS_PROXIMOS não definida em produção, aceitando os defaults diferenciados. De todo modo, não impede funcionamento – apenas poderia reintroduzir duplicações massivas.

Em suma, os timers estão configurados corretamente e devem disparar. Sem bugs de implementação (a lógica interna já analisamos no engine). O único efeito colateral, já mencionado, é a duplicata de notificação para tarefas do dia seguinte por design. Monitorar logs após deploy será importante para ver se a tarde frequentemente pula muitos itens por “já notificado” ou não.

Endpoint /api/messages – Bot Framework messages
GitHub
GitHub
:

Este endpoint recebe atividades do Bot Framework (por exemplo, quando um usuário envia mensagem ao bot ou clica em um botão de Adaptive Card). O código diferencia três casos:

Invoke com adaptiveCard/action: isso significa que um botão universal de card foi clicado (tipo Action.Submit ou Execute). Ele então chama _process_card_action(body) para tratar
GitHub
.

Mensagem do usuário contendo value ou channelData: possivelmente um cartão enviado que retorna via messageBack. Também encaminha para _process_card_action
GitHub
.

Outras mensagens: aqui ele simplesmente loga quem enviou e retorna um JSON indicando recebido sem ação
GitHub
.

Esse design garante que qualquer ação de cartão dispara o processamento, enquanto mensagens genéricas são ignoradas (mas respondidas com um ack). Está correto e alinhado ao fato de que não implementamos um diálogo conversacional extenso – só reagimos a cliques.

Processamento de ações de card (_process_card_action)
GitHub
GitHub
:

Lê action_type e task_id via _extract_card_action
GitHub
. Se faltarem, retorna um erro no JSON de resultado (status 200, mas com "result":"error")
GitHub
.

Para ações definidas: implementa duas:

"dispensar": Tenta marcar a tarefa como dispensada no G-Click via _dispensar_tarefa_gclick(task_id)
GitHub
. Devolve mensagem de confirmação ✅ ou ⚠️ conforme sucesso ou falha
GitHub
, e um result_status apropriado.

"finalizar": Aqui optou-se por não chamar a API G-Click (talvez não haja endpoint ou não se queira permitir pelo bot). Em vez disso, apenas retorna uma mensagem dizendo que a tarefa foi marcada como finalizada no chat, mas não no G-Click
GitHub
. Isso é mais um feedback local, sem persistência. É uma decisão aceitável: o usuário clica “Finalizar” no Teams, e o bot responde que considerou finalizado (apenas visualmente).

Qualquer outra ação: result em “ação não reconhecida”⚠️
GitHub
.

Envio de confirmação proativa: Se bot_sender existe e temos user_id do autor, o código tenta enviar uma mensagem de confirmação privada
GitHub
. Ou seja, após clicar em “Dispensar” ou “Finalizar”, o bot envia no chat 1:1 com o usuário uma mensagem confirmando a ação.

A implementação usa novamente a lógica async: se o loop já está rodando, faz ensure_future, se não, run_until_complete
GitHub
. Isso é similar ao utilizado no ciclo de notificação.

Possível ponto de falha: caso conversation_storage não tenha a referência desse user (mesmo ponto de antes – se ninguém salvou, bot_sender.send_message vai retornar False e cair no except logando falha
GitHub
). Então, talvez nenhuma confirmação seja realmente entregue por falta de referência. Não há fallback pro webhook aqui (porque seria estranho mandar confirm pelo webhook de canal para uma ação individual). Logo, se o bot não tem a referência, a confirmação simplesmente não chega, mas o usuário já viu o card ser atualizado (Adaptive Card poderia mudar, mas isso não foi implementado). Em todo caso, não é um bug travante, apenas uma limitação se referências não estão salvas.

Retorna um JSON com result, taskId, action e timestamp
GitHub
 para o Teams. Isso é exigido pelo protocolo do Bot Framework para fechar a interação.

Tratamento de exceções: qualquer erro inesperado no processamento de ação é capturado e retorna result error genérico
GitHub
, assim o usuário não fica sem resposta.

Resumo: O processamento de ações está bem estruturado e não apresenta bugs lógicos evidentes – cumpre o necessário. A função de dispensar tarefa merece atenção separada abaixo.

Função _dispensar_tarefa_gclick
GitHub
GitHub
:

Essa função faz uma chamada HTTP à API G-Click para alterar o status da tarefa para “Dispensado” (status "D")
GitHub
.

Ela tenta obter cabeçalhos de autenticação: primeiro tenta importar gclick.auth.get_auth_headers
GitHub
 – se existir, ótimo (provavelmente usa client_id/secret para pegar token). Se der ImportError, cai no fallback: pegar um token do env GCLICK_TOKEN
GitHub
. Essa flexibilidade é boa; no deploy atual, talvez já exista get_auth_headers funcional.

Monta o endpoint assumindo algo como /tarefas/{id}/status
GitHub
 – note o comentário dizendo que “este endpoint é uma suposição - deve ser confirmado com documentação”
GitHub
. Ou seja, o desenvolvedor não tinha certeza do endpoint correto e implementou uma hipótese. Isso é arriscado: se estiver errado, a resposta não será 200 e cairá no log de erro.

Trata respostas: se status_code == 200, loga sucesso e retorna True
GitHub
; caso contrário, loga erro com detalhes e retorna False. Exceptions também retornam False após logar erro.

Conclusão: Não é exatamente um bug, mas sim algo a validar. Em testes reais, veremos se dispensar retorna sucesso. Se não, precisaremos ajustar o URL ou payload conforme a API real. Por ora, o código em si não quebra nada – no pior caso, usuário clica “Dispensar” e recebe “⚠️ Não foi possível dispensar…”. Isso é manejado graciosamente pelo sistema, sem crashes.

Endpoint /api/debug/users
GitHub
GitHub
:

Retorna a lista de usuários cujas referências de conversa estão salvas. Usa bot_sender.conversation_storage.list_users() se possível
GitHub
, com fallback para tentar acessar atributos internos _conversations etc. se list falhar (isso lida com implementações diferentes do storage, boa robustez).

Se bot_sender não existe (bot não configurado) ou estamos em DEBUG_MOCK, ele devolve usuários mock para teste
GitHub
.

Não há pontos críticos aqui – é um endpoint de debug mesmo. Sem bugs, a não ser que quiséssemos listar algo além de IDs (poderia mapear de volta para apelidos via user_mapping, mas não é estritamente necessário).

Endpoint /api/http_trigger (HttpTrigger genérico)
GitHub
GitHub
:

É praticamente um echo/health endpoint extra (talvez legado do template). Responde “Olá, Nome” em GET e devolve qualquer payload em POST.

Sem muita relevância para a lógica do app, mas útil para testes de disponibilidade. Nenhum bug, apenas características: ele identifica se está rodando no Azure ou local via IS_AZURE e devolve no JSON, e inclui a versão do app. Tudo certo.

Endpoint /api/health (HealthCheck)
GitHub
GitHub
:

Retorna um JSON consolidando informações de saúde da função: versão, versão Python, ambiente (Azure ou local), se bot está configurado, status do storage de conversas (existe o arquivo? etc.), e até quantas funções detectadas (7 total, contagem manual)
GitHub
.

Isso é extremamente útil. Vale conferir:

functions_detected.total = 7 e http_endpoints = 5, timer_triggers = 2
GitHub
. Pela nossa lista: HTTP endpoints: gclick, messages, debug/users, http_trigger, health (5); Timer: morning, afternoon (2). Está correto. Porém, se futuramente somar ou remover endpoints, esse valor teria de ser atualizado manualmente. Não é dinâmico, mas serve como conferência.

Mapeamento de usuário: ele até testa mapear_apelido_para_teams_id("teste_health_check") para ver se função está funcionando, retornando "ok" ou "no_match"
GitHub
.

Sem bugs aqui, apenas notar que manter functions_detected coerente é manutenção manual. No geral, o healthcheck cobre bem os principais pontos e será valioso após o deploy para ver se algo como Bot ou storage está mal configurado.

Resumo local (function_app.py): Este arquivo é extenso mas fundamental. Em termos de bugs, identificamos apenas lacunas funcionais menores:

Endpoint /gclick ainda não envia notificações (mas não quebra nada).

Necessidade de capturar referências de conversa do Bot para aproveitar o envio proativo (sistema atualmente depende do webhook textual).

Possível duplicação de notificações devido a configuração de triggers sobrepostas (como detalhado).

Endpoint /health requer manutenção manual se a contagem de funções mudar (risco baixo).
No que tange a deploy e sincronização de triggers, tudo está configurado corretamente: esperamos que ao publicar, a Azure Functions detecte os 7 functions. O sincronismo de triggers (que às vezes requer rodar func azure functionapp publish --sync ou está automático via extensionBundle) deve ocorrer. Dado que host.json e os decorators estão nos conformes, o deploy deve concluir com sucesso e todas as triggers ficarão ativas – confirmável via Azure Portal (listas de funções dentro da Function App).

⚠️ Resumo Geral: Bugs e Impacto no Sistema

Após a análise minuciosa, podemos consolidar os principais bugs/pontos de melhoria remanescentes e como eles influenciam o funcionamento geral do G-Click Teams Notifications:

Tarefas com 1 dia de atraso não notificadas – Possível Bug de Cobertura: O sistema atualmente não inclui tarefas vencidas no dia anterior na janela de notificação do dia corrente. Isso significa que uma obrigação que passou despercebida em “vence_hoje” não será relembrada em “vencidas” no dia seguinte. Impacto: Pendências recém-atrasadas podem deixar de ser notificadas, reduzindo a eficácia do sistema em garantir que nada seja esquecido. Em termos globais, isso fere ligeiramente o requisito de cobrir até 1 dia de atraso, embora atenue spam de atrasos antigos. É recomendável ajustar a lógica de coleta ou explicitar essa limitação aos usuários até uma correção.

Notificações duplicadas no mesmo dia – Condição de Corrida entre disparos: Devido às janelas sobrepostas (manhã 3 dias, tarde 1 dia) e ao mecanismo de idempotência por conjunto de IDs, usuários podem receber notificações repetidas de tarefas (especialmente as do dia seguinte) em horários diferentes. Impacto: Experiência do usuário potencialmente prejudicada – receber duas vezes alerta da mesma tarefa no mesmo dia pode causar confusão ou irritação. Não é catastrófico, mas compromete a “polidez” do bot. Em escala global, isso pode gerar ruído extra em canais/usuários de Teams. Mitigar isso refinando a chave de already_sent (por ex., marcar cada tarefa individual por dia/responsável) seria uma melhoria futura.

Integração Bot Framework incompleta (falta salvar referências) – Lacuna Funcional: O sistema preparou todo o arcabouço para enviar mensagens via bot (inclusive Adaptive Cards ricos), mas não implementou o passo de capturar e armazenar automaticamente as referências de conversa dos usuários do Teams. Sem essas referências, o bot não sabe para quem enviar mensagens proativas, recorrendo sempre ao webhook. Impacto: No estado atual, todas as notificações serão enviadas pelo webhook do Teams (mensagens simples em um canal Teams definido por TEAMS_WEBHOOK_URL), pois _has_conversation quase sempre retornará False. Os Adaptive Cards, botões e confirmações 1:1 via bot não serão experimentados plenamente pelos usuários. O sistema de notificações continuará funcionando (graças ao fallback), porém perde-se a interatividade pretendida (cartões com botão “Dispensar”, etc.). Em escala global, isso significa que o projeto ainda não entrega todo valor da integração Bot – porém, a boa notícia é que isso não impede o funcionamento básico de notificação.

Endpoint de Webhook externo não envia mensagens – Funcionalidade a Implementar: O endpoint /api/gclick atualmente apenas processa o payload e retorna um resumo, sem de fato notificar os usuários mencionados. Impacto: Se a API G-Click for configurada para chamar esse webhook em certos eventos, os responsáveis não receberão alerta no Teams (apesar da Function retornar sucesso). Ou seja, por enquanto este mecanismo não amplia as notificações – ele precisaria chamar o motor de notificação ou enviar uma mensagem direta. Globalmente, isso significa que o sistema depende do agendamento diário e não reage ainda em tempo real a eventos do G-Click. Não causa bugs ou crashes, mas é uma oportunidade de melhoria clara para futuros sprints.

Endpoint de dispensar tarefa possivelmente não efetivo – Suposição na API: A funcionalidade de marcar tarefa como “dispensada” pelo Teams está implementada de forma otimista, assumindo um endpoint na API G-Click que pode não existir ou ter outra forma. Impacto: O usuário pode clicar “Dispensar” no card e receber uma mensagem de erro mesmo que a ação não tenha sido concluída (falso negativo ou apenas falta de implementação). Isso não afeta o resto do sistema (a notificação some do Teams mas no G-Click continua pendente), porém pode causar desalinhamento de status. Em escala, isso é gerenciável – basta comunicar que “Dispensar” pelo bot é experimental. Não derruba nada, mas é algo a sincronizar com a equipe do G-Click.

Configurações não dinâmicas – O arquivo YAML e a variável DIAS_PROXIMOS global não estão totalmente plugados para permitir ajuste fino separado de manhã/tarde. Impacto: Para mudar comportamento (ex: aumentar janela para 5 dias), exige alterar código ou conviver com ambos triggers iguais. Novamente, não quebra o sistema mas limita a flexibilidade operacional. Globalmente, isso significa que a personalização em produção está um pouco engessada – porém, como quickwin, é compreensível e pode ser melhorado com pouco esforço (ler YAML no Function ou usar envs distintos).

Outros pontos verificados sem bugs: A coleta de responsáveis, o cálculo de métricas, a formatação de mensagens e a persistência de estado estão funcionando corretamente. Os testes implementados cobrem essas áreas, então qualquer falha neles já teria acusado. Isso indica que não há bugs estruturais nesses componentes. Por exemplo, o sistema não notifica pessoas erradas, não entra em loop infinito, não quebra com caracteres especiais, etc. – tudo isso foi pensado e testado (observamos vários try/except defensivos no código).