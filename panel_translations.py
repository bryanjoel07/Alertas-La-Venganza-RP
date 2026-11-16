"""Store-panel translations for the exact language manifest in the supplied script.

Source: community_sanctions_system_1.42.2.zip/locales/css_languages.json.
Spanish is served by the existing panels and is deliberately not a button.
These are translations of the Discord store panels, not copies of paid script code.
"""

LANGUAGES = (
    {'code': 'en', 'name': 'English', 'emoji': '🇬🇧'},
    {'code': 'pt-BR', 'name': 'Português (Brasil)', 'emoji': '🇧🇷'},
    {'code': 'fr', 'name': 'Français', 'emoji': '🇫🇷'},
    {'code': 'de', 'name': 'Deutsch', 'emoji': '🇩🇪'},
)

UI_TEXT = {
    'en': {
        'Unirme a la comunidad':'Join the community', 'Ayuda y compras':'Help and purchases',
        'Avisos':'Announcements', 'Actualizaciones':'Updates', 'Visitar tienda oficial':'Visit the official store',
        'Selecciona el motivo de tu consulta':'Select the reason for your inquiry',
        'Compras y pedidos':'Purchases and orders', 'Instalación y soporte':'Installation and support',
        'Reportar un error':'Report a bug', 'Colaboraciones':'Partnerships',
        'Proponer una mejora':'Suggest an improvement', 'Escribir mi reseña':'Write my review',
        'Tickets abiertos':'Open tickets', 'Tickets cerrados':'Closed tickets',
        'Configurar enlace de Tebex':'Set the Tebex store link',
        'Mi bienvenida':'My welcome card',
        'Tienda en activación':'Store activation pending',
    },
    'pt-BR': {
        'Unirme a la comunidad':'Entrar na comunidade', 'Ayuda y compras':'Ajuda e compras',
        'Avisos':'Avisos', 'Actualizaciones':'Atualizações', 'Visitar tienda oficial':'Visitar a loja oficial',
        'Selecciona el motivo de tu consulta':'Selecione o motivo do seu contato',
        'Compras y pedidos':'Compras e pedidos', 'Instalación y soporte':'Instalação e suporte',
        'Reportar un error':'Relatar um erro', 'Colaboraciones':'Parcerias',
        'Proponer una mejora':'Sugerir uma melhoria', 'Escribir mi reseña':'Escrever minha avaliação',
        'Tickets abiertos':'Tickets abertos', 'Tickets cerrados':'Tickets fechados',
        'Configurar enlace de Tebex':'Configurar o link do Tebex',
        'Mi bienvenida':'Minha mensagem de boas-vindas',
        'Tienda en activación':'Loja aguardando ativação',
    },
    'fr': {
        'Unirme a la comunidad':'Rejoindre la communauté', 'Ayuda y compras':'Aide et achats',
        'Avisos':'Annonces', 'Actualizaciones':'Mises à jour', 'Visitar tienda oficial':'Visiter la boutique officielle',
        'Selecciona el motivo de tu consulta':'Choisissez le motif de votre demande',
        'Compras y pedidos':'Achats et commandes', 'Instalación y soporte':'Installation et assistance',
        'Reportar un error':'Signaler un bug', 'Colaboraciones':'Partenariats',
        'Proponer una mejora':'Proposer une amélioration', 'Escribir mi reseña':'Rédiger mon avis',
        'Tickets abiertos':'Tickets ouverts', 'Tickets cerrados':'Tickets fermés',
        'Configurar enlace de Tebex':'Configurer le lien Tebex',
        'Mi bienvenida':'Ma carte de bienvenue',
        'Tienda en activación':'Boutique en cours d’activation',
    },
    'de': {
        'Unirme a la comunidad':'Der Community beitreten', 'Ayuda y compras':'Hilfe und Käufe',
        'Avisos':'Ankündigungen', 'Actualizaciones':'Updates', 'Visitar tienda oficial':'Offiziellen Shop besuchen',
        'Selecciona el motivo de tu consulta':'Wähle den Grund deiner Anfrage',
        'Compras y pedidos':'Käufe und Bestellungen', 'Instalación y soporte':'Installation und Support',
        'Reportar un error':'Fehler melden', 'Colaboraciones':'Partnerschaften',
        'Proponer una mejora':'Verbesserung vorschlagen', 'Escribir mi reseña':'Bewertung schreiben',
        'Tickets abiertos':'Offene Tickets', 'Tickets cerrados':'Geschlossene Tickets',
        'Configurar enlace de Tebex':'Tebex-Shoplink einrichten',
        'Mi bienvenida':'Meine Willkommenskarte',
        'Tienda en activación':'Shopaktivierung ausstehend',
    },
}

TRANSLATIONS = {
    'en': {
        'welcome': ('👑 Welcome to EssChino Studio',
            'Scripts to bring your project to life.\n\n**Start here**\n📜 Read {rules}.\n'
            '📦 Explore {catalog} and {demos}.\n🛒 Shop through {shop}.\n🎫 Get help in {support}.\n'
            '🔔 Choose your notifications using the buttons on this message.\n\nOur team helps you through private tickets.'),
        'rules': ('📜 EssChino rules',
            '1. Respect members and staff. No harassment, discrimination or spam.\n'
            '2. Use the appropriate channel for each inquiry. Support and order questions belong in tickets.\n'
            '3. Do not share paid scripts, leaks, other people’s licenses or material without permission.\n'
            '4. Never post passwords, tokens, license keys or payment details.\n'
            '5. Buy only through the official store linked in this server. Staff do not request payments through direct messages.\n'
            '6. Before buying, review the requirements, dependencies, compatibility, delivery and terms stated on the product page and in Tebex.\n'
            '7. Support must verify your order before you receive the Customer role. A screenshot or order reference alone does not prove a purchase.\n'
            '8. Reviews must describe real experiences; report problems through a ticket.\n\nModerators may remove content that breaks these rules.'),
        'announcements': ('📢 Official announcements',
            'Important EssChino Studio news is published here.\n\nEnable the notifications you want in {welcome}. '
            'For technical changes, check {changelog}; for help, use {support}. We do not send promotions through direct messages.'),
        'shop': ('🛒 EssChino official store',
            '{shop_intro}\n\nCheck product compatibility and terms before paying. Orders are processed through Tebex; do not post payment details in Discord.'),
        'shop_configured': ('', 'Browse our products and complete your purchase securely in our Tebex store.\n\n{shop_url}'),
        'shop_pending': ('', 'We are preparing access to the official store. In the meantime, explore {catalog} and open a private inquiry in {support}.'),
        'catalog': ('📦 Script catalog',
            'This channel contains the official listings for our products.\n\nEach listing will include the **name, features, supported framework, dependencies, version, demonstration and purchase link**. '
            'Current prices and terms are available on Tebex.\n\nLooking for a particular resource? Ask in {support}. Only published products are available; this message does not announce stock or compatibility.'),
        'demos': ('🎬 Demonstrations',
            'Find videos and working examples of published scripts here.\n\nBefore buying, compare the demonstration with the product listing and its requirements. '
            'If you need to check a particular feature, open a ticket in {support}. No demonstrations have been published yet.'),
        'offers': ('🏷️ Official offers',
            'Promotions will be announced here with the included product, conditions and end date.\n\nThe final amount is always the one shown by Tebex at checkout. '
            'No promotions are currently announced in this channel.'),
        'changelog': ('🔄 Versions and updates',
            'Each update will include **product · version · changes · new requirements · update steps**.\n\n'
            'Back up your server and configuration before updating. Enable your notifications in {welcome}. No versions have been published yet.'),
        'buying': ('🧾 How to buy',
            '**1. Choose your script** in {catalog} and watch its demonstration.\n'
            '**2. Check the requirements:** framework, versions, dependencies and license type.\n'
            '**3. Open the official store** through {shop}.\n'
            '**4. Complete your Tebex order** using the identity or account required by that product. Keep the email and order reference.\n'
            '**5. Check delivery** by following the Tebex and product instructions.\n'
            '**6. Open a ticket** in {support} for problems or to verify your purchase and receive the Customer role.\n\n'
            'Do not send card details, passwords or private keys through Discord. Applicable taxes, delivery details and terms are shown at checkout.'),
        'support': ('🎫 EssChino support center',
            'Choose a reason from the menu to open a private channel.\n\n'
            '🛒 **Purchases and orders** · questions, delivery and customer verification.\n'
            '🛠️ **Installation and support** · requirements, configuration and troubleshooting.\n'
            '🐛 **Bugs** · steps to reproduce, version and error logs.\n'
            '🤝 **Partnerships** · proposals and business inquiries.\n\n'
            'Include the product, order reference if you have one, and an explanation. Hide passwords, tokens and license keys. '
            'Avoid duplicate tickets; staff respond according to availability.'),
        'faq': ('❓ Frequently asked questions',
            '**Is it compatible with my server?**\nCheck the framework, versions and dependencies in the product listing. Ask before buying if anything is unclear.\n\n'
            '**Where do I download my purchase?**\nFollow the Tebex email and delivery instructions; this depends on the product.\n\n'
            '**How do I get the Customer role?**\nOpen a purchase ticket. Staff will check your order in Tebex.\n\n'
            '**Can I share or resell a script?**\nCheck its license; purchasing does not authorize redistribution.\n\n'
            '**Are refunds or license transfers available?**\nRead the terms published in the store and at checkout. Open a private ticket to have your case reviewed.\n\n'
            '**What information does support need?**\nProduct, version, environment, steps to reproduce and relevant errors with sensitive information hidden.'),
        'install': ('📚 Installation guide',
            '**Before you start**\nBack up your files, configuration and database. Check the exact product requirements.\n\n'
            '**Install the resource**\nUse only the official delivery. Follow the script’s README, install its dependencies and apply SQL only when its documentation instructs you to. Respect the loading order.\n\n'
            '**Configure and test**\nAdjust the documented options, test in a testing environment first, and check the console and logs. Do not overwrite old configurations without comparing them.\n\n'
            '**If something fails**\nOpen a ticket with the product, version, framework, steps and error text. Hide keys and credentials. '
            'This general guide does not replace the instructions for each script.'),
        'general': ('💬 EssChino community',
            'Introduce yourself, share ideas and chat with the community.\n\nFor purchases or technical problems, use {support} so staff can follow your case privately.'),
        'suggestions': ('💡 Your next idea',
            'Suggest improvements using this format:\n\n**Need:** what do you want to solve?\n**Proposal:** how would it work?\n'
            '**Example:** when would you use it?\n\nYou can support other ideas with reactions. Suggestions do not imply a development commitment or delivery date.'),
        'reviews': ('⭐ Customer experiences',
            'Members with the Customer role, granted after purchase verification, can post here.\n\nShare the product, how you use it and your real experience. '
            'Do not post order references, personal information or paid files. Open a ticket to resolve problems. No reviews have been published yet.'),
        'staff': ('👥 EssChino team',
            'Coordinate customer support and official content here.\n\n**Before publishing:** check requirements, links, the Tebex price and product terms.\n'
            '**Before verifying a customer:** check the order in the actual Tebex dashboard; do not accept a screenshot alone.\n'
            '**Tickets:** collect diagnostic information, avoid asking for secrets and keep the transcript when closing.\n'
            '**Privacy:** do not copy order information into public channels.'),
        'management': ('📋 Support management',
            'Private tickets open in **Tickets Abiertos** at the top of the server. When closed, they move to **Tickets Cerrados**.\n\n'
            'Each case supports closing, reopening, transcript download and purchase verification after checking the order in Tebex.\n\n'
            'Use `/studio tickets` to view open and closed cases. Assign team roles only to people who should handle orders.'),
        'log': ('📋 Support log',
            'Ticket openings, closures, reopenings and customer verifications are recorded here.\n\nClosed tickets retain private access. '
            'The pre-installation state and copies of previous channels are stored on the bot’s private volume.'),
        'direction': ('👑 EssChino management',
            'This original channel keeps its history and remains private to the owner and bot '
            '(Discord also permits access to accounts with Administrator).\n\n'
            '**Store:** configure the official link using the button below.\n'
            '**Products:** publish real product listings in the catalog and demonstrations in their dedicated channel.\n'
            '**Team:** assign Administration, Developer and Support roles only to trusted people.\n'
            '**Customers:** check the order in Tebex and use Verify purchase in its ticket. Automatic Tebex payment verification has not been configured.\n'
            '**Branding:** the logo is the server icon; the banner appears in the panels. The native server banner depends on Discord enabling BANNER.\n\n'
            'Copies of the installation and previous channels remain on the bot’s private volume.'),
        'setup': ('✅ EssChino configured',
            'This channel and its history have been kept private. The other original channels have been backed up and removed; '
            'Information, Store, Support, Community and Team are available.\n\n'
            '**Branding:** server logo and banner in the main panels.\n'
            '**Support:** private tickets, history retained on closing, transcripts and the Customer role after a real order is checked.\n'
            '**Notifications:** optional roles for announcements and updates.\n\n{setup_shop}'),
        'setup_pending': ('', 'The official Tebex link is still needed to connect the purchase button. You can enter it using the configuration button above.'),
        'setup_configured': ('', 'The official Tebex link is connected to the purchase panel.'),
    },
    'pt-BR': {
        'welcome': ('👑 Boas-vindas à EssChino Studio',
            'Scripts para dar forma ao seu projeto.\n\n**Comece por aqui**\n📜 Leia {rules}.\n'
            '📦 Explore {catalog} e {demos}.\n🛒 Compre por {shop}.\n🎫 Peça ajuda em {support}.\n'
            '🔔 Escolha seus avisos nos botões desta mensagem.\n\nNossa equipe atende você por tickets privados.'),
        'rules': ('📜 Regras da EssChino',
            '1. Respeite os membros e a equipe. Sem assédio, discriminação ou spam.\n'
            '2. Use o canal adequado para cada assunto. Suporte e dúvidas sobre pedidos devem ser tratados por ticket.\n'
            '3. Não compartilhe scripts pagos, vazamentos, licenças de outras pessoas ou material sem autorização.\n'
            '4. Nunca publique senhas, tokens, chaves de licença ou dados de pagamento.\n'
            '5. Compre apenas pela loja oficial vinculada neste servidor. A equipe não solicita pagamentos por mensagens privadas.\n'
            '6. Antes de comprar, confira requisitos, dependências, compatibilidade, entrega e condições informadas no produto e no Tebex.\n'
            '7. O suporte precisa verificar seu pedido antes de conceder o cargo Cliente. Uma captura de tela ou referência de pedido, por si só, não comprova uma compra.\n'
            '8. As avaliações devem relatar experiências reais; problemas são atendidos por ticket.\n\nA moderação poderá remover conteúdo que descumpra estas regras.'),
        'announcements': ('📢 Comunicados oficiais',
            'As novidades importantes da EssChino Studio são publicadas aqui.\n\nAtive os avisos de seu interesse em {welcome}. '
            'Para mudanças técnicas, consulte {changelog}; para ajuda, use {support}. Não enviamos promoções por mensagem privada.'),
        'shop': ('🛒 Loja oficial da EssChino',
            '{shop_intro}\n\nConfira a compatibilidade e as condições do produto antes de pagar. Os pedidos são processados pelo Tebex; não publique dados de pagamento no Discord.'),
        'shop_configured': ('', 'Explore os produtos e conclua sua compra com segurança em nossa loja Tebex.\n\n{shop_url}'),
        'shop_pending': ('', 'Estamos preparando o acesso à loja oficial. Enquanto isso, consulte os produtos em {catalog} e abra uma consulta privada em {support}.'),
        'catalog': ('📦 Catálogo de scripts',
            'Este canal reúne as fichas oficiais dos nossos produtos.\n\nCada publicação informará **nome, recursos, framework compatível, dependências, versão, demonstração e link de compra**. '
            'O preço atual e as condições estão disponíveis no Tebex.\n\nProcura um recurso específico? Pergunte em {support}. Apenas os produtos publicados estão disponíveis; esta mensagem não anuncia estoque nem compatibilidades.'),
        'demos': ('🎬 Demonstrações',
            'Aqui você encontrará vídeos e exemplos do funcionamento dos scripts publicados.\n\nAntes de comprar, compare a demonstração com a ficha do produto e seus requisitos. '
            'Se precisar confirmar uma função específica, abra um ticket em {support}. Ainda não há demonstrações publicadas.'),
        'offers': ('🏷️ Ofertas oficiais',
            'As promoções serão anunciadas aqui com o produto incluído, as condições e a data de encerramento.\n\n'
            'O valor final é sempre aquele exibido pelo Tebex ao concluir o pedido. Atualmente não há promoções anunciadas neste canal.'),
        'changelog': ('🔄 Versões e atualizações',
            'Cada atualização incluirá **produto · versão · alterações · novos requisitos · etapas de atualização**.\n\n'
            'Faça um backup do servidor e da configuração antes de atualizar. Ative seus avisos em {welcome}. Ainda não há versões publicadas.'),
        'buying': ('🧾 Como comprar',
            '**1. Escolha seu script** em {catalog} e assista à demonstração.\n'
            '**2. Confira os requisitos:** framework, versões, dependências e modalidade da licença.\n'
            '**3. Acesse a loja oficial** por {shop}.\n'
            '**4. Conclua o pedido no Tebex** com a identidade ou conta exigida pelo produto. Guarde o e-mail e a referência do pedido.\n'
            '**5. Confira a entrega** seguindo as instruções do Tebex e do produto.\n'
            '**6. Abra um ticket** em {support} para problemas ou para verificar sua compra e receber o cargo Cliente.\n\n'
            'Não envie dados de cartão, senhas ou chaves privadas pelo Discord. Os impostos, a entrega e as condições aplicáveis são exibidos no checkout.'),
        'support': ('🎫 Central de suporte EssChino',
            'Selecione o motivo no menu para abrir um canal privado.\n\n'
            '🛒 **Compras e pedidos** · dúvidas, entrega e verificação de cliente.\n'
            '🛠️ **Instalação e suporte** · requisitos, configuração e diagnóstico.\n'
            '🐛 **Erros** · passos para reproduzir, versão e registros do problema.\n'
            '🤝 **Parcerias** · propostas e contatos comerciais.\n\n'
            'Inclua o produto, a referência do pedido, se houver, e uma explicação. Oculte senhas, tokens e chaves de licença. '
            'Evite tickets duplicados; a equipe responde conforme a disponibilidade.'),
        'faq': ('❓ Perguntas frequentes',
            '**É compatível com meu servidor?**\nConfira o framework, as versões e as dependências na ficha. Pergunte antes de comprar se houver dúvidas.\n\n'
            '**Onde baixo minha compra?**\nSiga o e-mail e as instruções de entrega do Tebex; isso depende do produto.\n\n'
            '**Como recebo o cargo Cliente?**\nAbra um ticket de compras. A equipe verificará seu pedido no Tebex.\n\n'
            '**Posso compartilhar ou revender um script?**\nConsulte a licença do produto; comprar não autoriza a redistribuição.\n\n'
            '**Há reembolsos ou transferências de licença?**\nConsulte as condições publicadas na loja e no checkout. Abra um ticket privado para analisar seu caso.\n\n'
            '**De quais informações o suporte precisa?**\nProduto, versão, ambiente, passos do problema e erros relevantes, com os dados sensíveis ocultos.'),
        'install': ('📚 Guia de instalação',
            '**Antes de começar**\nFaça um backup dos arquivos, da configuração e do banco de dados. Confira os requisitos exatos do produto.\n\n'
            '**Instale o recurso**\nUse apenas a entrega oficial. Siga o README do script, instale as dependências e aplique SQL somente quando a documentação orientar. Respeite a ordem de carregamento.\n\n'
            '**Configure e teste**\nAjuste as opções documentadas, teste primeiro em um ambiente de testes e confira o console e os registros. Não sobrescreva configurações antigas sem compará-las.\n\n'
            '**Se algo falhar**\nAbra um ticket com o produto, a versão, o framework, os passos e o texto do erro. Oculte chaves e credenciais. '
            'Este guia geral não substitui as instruções específicas de cada script.'),
        'general': ('💬 Comunidade EssChino',
            'Apresente-se, compartilhe ideias e converse com a comunidade.\n\nPara compras ou problemas técnicos, use {support}, assim a equipe acompanha seu caso em privado.'),
        'suggestions': ('💡 Sua próxima ideia',
            'Sugira melhorias neste formato:\n\n**Necessidade:** o que você quer resolver?\n**Proposta:** como funcionaria?\n'
            '**Exemplo:** em qual situação você usaria?\n\nVocê pode apoiar outras ideias com reações. As sugestões não implicam compromisso de desenvolvimento nem data de entrega.'),
        'reviews': ('⭐ Experiências de clientes',
            'Este espaço permite publicações de membros com o cargo Cliente, concedido após a verificação de uma compra.\n\n'
            'Compartilhe o produto, como você o utiliza e sua experiência real. Não publique referências de pedido, dados pessoais ou arquivos pagos. '
            'Para resolver problemas, abra um ticket. Ainda não há avaliações publicadas.'),
        'staff': ('👥 Equipe EssChino',
            'Coordene aqui o atendimento e os conteúdos oficiais.\n\n**Antes de publicar:** confira os requisitos, os links, o preço no Tebex e as condições do produto.\n'
            '**Antes de verificar um cliente:** confira o pedido no painel real do Tebex; não aceite apenas uma captura de tela.\n'
            '**Tickets:** reúna o diagnóstico, evite pedir segredos e guarde a transcrição ao fechar.\n'
            '**Privacidade:** não copie informações de pedidos para canais públicos.'),
        'management': ('📋 Gestão do suporte',
            'Os tickets privados são abertos em **Tickets Abiertos**, no topo do servidor. Ao serem fechados, passam para **Tickets Cerrados**.\n\n'
            'Cada caso permite fechar, reabrir, baixar sua transcrição e verificar uma compra depois de conferir o pedido no Tebex.\n\n'
            'Use `/studio tickets` para consultar os casos abertos e fechados. Atribua os cargos da equipe apenas a quem deve atender pedidos.'),
        'log': ('📋 Registro do suporte',
            'Aqui são registradas aberturas, encerramentos, reaberturas e verificações de clientes.\n\nOs tickets fechados mantêm acesso privado. '
            'O estado anterior à instalação e as cópias dos canais anteriores ficam no volume privado do bot.'),
        'direction': ('👑 Direção da EssChino',
            'Este canal original mantém seu histórico e fica privado para o proprietário e o bot '
            '(o Discord também permite acesso a contas com Administrador).\n\n'
            '**Loja:** configure o link oficial no botão abaixo.\n'
            '**Produtos:** publique as fichas reais no Catálogo e as demonstrações no canal correspondente.\n'
            '**Equipe:** atribua os cargos de Administração, Desenvolvedor e Suporte apenas a pessoas de confiança.\n'
            '**Clientes:** confira o pedido no Tebex e use Verificar compra no ticket. A verificação automática de pagamentos do Tebex não está configurada.\n'
            '**Identidade visual:** o logo está no ícone; o banner aparece nos painéis. O cabeçalho nativo do servidor depende da função BANNER do Discord.\n\n'
            'As cópias da instalação e dos canais anteriores permanecem no volume privado do bot.'),
        'setup': ('✅ EssChino configurado',
            'Este canal e seu histórico foram mantidos em privado. Os demais canais originais foram copiados e removidos; '
            'Informações, Loja, Suporte, Comunidade e Equipe estão disponíveis.\n\n'
            '**Identidade visual:** logo do servidor e banner nos painéis principais.\n'
            '**Suporte:** tickets privados, histórico mantido no encerramento, transcrições e cargo Cliente após a conferência de um pedido real.\n'
            '**Avisos:** cargos opcionais para anúncios e atualizações.\n\n{setup_shop}'),
        'setup_pending': ('', 'Falta o link oficial do Tebex para conectar o botão de compra. Você pode informá-lo no botão de configuração acima.'),
        'setup_configured': ('', 'O link oficial do Tebex está conectado ao painel de compra.'),
    },
    'fr': {
        'welcome': ('👑 Bienvenue chez EssChino Studio',
            'Des scripts pour donner forme à votre projet.\n\n**Commencez ici**\n📜 Lisez {rules}.\n'
            '📦 Explorez {catalog} et {demos}.\n🛒 Achetez via {shop}.\n🎫 Demandez de l’aide dans {support}.\n'
            '🔔 Choisissez vos notifications à l’aide des boutons de ce message.\n\nNotre équipe vous accompagne dans des tickets privés.'),
        'rules': ('📜 Règlement EssChino',
            '1. Respectez les membres et l’équipe. Aucun harcèlement, aucune discrimination ni aucun spam.\n'
            '2. Utilisez le canal adapté à chaque demande. L’assistance et les questions sur les commandes passent par les tickets.\n'
            '3. Ne partagez pas de scripts payants, de fuites, de licences appartenant à autrui ni de contenu sans autorisation.\n'
            '4. Ne publiez jamais de mots de passe, de jetons, de clés de licence ni de données de paiement.\n'
            '5. Achetez uniquement dans la boutique officielle liée à ce serveur. L’équipe ne demande pas de paiement par message privé.\n'
            '6. Avant tout achat, vérifiez les prérequis, dépendances, compatibilités, modalités de livraison et conditions indiqués sur la fiche du produit et sur Tebex.\n'
            '7. L’assistance doit vérifier votre commande avant de vous attribuer le rôle Client. Une capture d’écran ou une référence de commande ne suffit pas à prouver un achat.\n'
            '8. Les avis doivent décrire des expériences réelles ; les problèmes sont traités par ticket.\n\nLa modération peut supprimer les contenus qui enfreignent ce règlement.'),
        'announcements': ('📢 Annonces officielles',
            'Les nouvelles importantes d’EssChino Studio sont publiées ici.\n\nActivez les notifications qui vous intéressent dans {welcome}. '
            'Pour les changements techniques, consultez {changelog} ; pour obtenir de l’aide, utilisez {support}. Nous n’envoyons pas de promotions par message privé.'),
        'shop': ('🛒 Boutique officielle EssChino',
            '{shop_intro}\n\nVérifiez la compatibilité et les conditions du produit avant de payer. Les commandes sont traitées par Tebex ; ne publiez pas de données de paiement sur Discord.'),
        'shop_configured': ('', 'Découvrez nos produits et effectuez vos achats en toute sécurité dans notre boutique Tebex.\n\n{shop_url}'),
        'shop_pending': ('', 'Nous préparons l’accès à la boutique officielle. En attendant, consultez les produits dans {catalog} et ouvrez une demande privée dans {support}.'),
        'catalog': ('📦 Catalogue de scripts',
            'Ce canal rassemble les fiches officielles de nos produits.\n\nChaque publication précisera le **nom, les fonctionnalités, le framework compatible, les dépendances, la version, la démonstration et le lien d’achat**. '
            'Le prix actuel et les conditions sont disponibles sur Tebex.\n\nVous recherchez une ressource précise ? Posez votre question dans {support}. Seuls les produits publiés sont disponibles ; ce message n’annonce aucun stock ni aucune compatibilité.'),
        'demos': ('🎬 Démonstrations',
            'Vous trouverez ici des vidéos et des exemples de fonctionnement des scripts publiés.\n\nAvant tout achat, comparez la démonstration avec la fiche du produit et ses prérequis. '
            'Pour vérifier une fonctionnalité précise, ouvrez un ticket dans {support}. Aucune démonstration n’a encore été publiée.'),
        'offers': ('🏷️ Offres officielles',
            'Les promotions seront annoncées ici avec le produit concerné, les conditions et la date de fin.\n\n'
            'Le montant final est toujours celui affiché par Tebex lors de la validation de la commande. Aucune promotion n’est actuellement annoncée dans ce canal.'),
        'changelog': ('🔄 Versions et mises à jour',
            'Chaque mise à jour précisera **le produit · la version · les changements · les nouveaux prérequis · les étapes de mise à jour**.\n\n'
            'Sauvegardez votre serveur et sa configuration avant toute mise à jour. Activez vos notifications dans {welcome}. Aucune version n’a encore été publiée.'),
        'buying': ('🧾 Comment acheter',
            '**1. Choisissez votre script** dans {catalog} et regardez sa démonstration.\n'
            '**2. Vérifiez les prérequis :** framework, versions, dépendances et type de licence.\n'
            '**3. Accédez à la boutique officielle** via {shop}.\n'
            '**4. Finalisez la commande sur Tebex** avec l’identité ou le compte demandé par le produit. Conservez l’e-mail et la référence de commande.\n'
            '**5. Vérifiez la livraison** en suivant les instructions de Tebex et du produit.\n'
            '**6. Ouvrez un ticket** dans {support} en cas de problème ou pour faire vérifier votre achat et obtenir le rôle Client.\n\n'
            'N’envoyez pas de données de carte bancaire, de mots de passe ni de clés privées sur Discord. Les taxes, modalités de livraison et conditions applicables sont affichées au paiement.'),
        'support': ('🎫 Centre d’assistance EssChino',
            'Choisissez un motif dans le menu pour ouvrir un canal privé.\n\n'
            '🛒 **Achats et commandes** · questions, livraison et vérification des clients.\n'
            '🛠️ **Installation et assistance** · prérequis, configuration et diagnostic.\n'
            '🐛 **Bugs** · étapes de reproduction, version et journaux d’erreur.\n'
            '🤝 **Partenariats** · propositions et demandes commerciales.\n\n'
            'Indiquez le produit, la référence de commande si vous en avez une et une explication. Masquez les mots de passe, les jetons et les clés de licence. '
            'Évitez les tickets en double ; l’équipe répond selon ses disponibilités.'),
        'faq': ('❓ Questions fréquentes',
            '**Est-ce compatible avec mon serveur ?**\nVérifiez le framework, les versions et les dépendances sur la fiche. Posez vos questions avant d’acheter en cas de doute.\n\n'
            '**Où télécharger mon achat ?**\nSuivez l’e-mail et les instructions de livraison de Tebex ; cela dépend du produit.\n\n'
            '**Comment obtenir le rôle Client ?**\nOuvrez un ticket d’achat. L’équipe vérifiera votre commande dans Tebex.\n\n'
            '**Puis-je partager ou revendre un script ?**\nConsultez sa licence ; l’achat n’autorise pas la redistribution.\n\n'
            '**Les remboursements ou transferts de licence sont-ils possibles ?**\nConsultez les conditions publiées dans la boutique et au paiement. Ouvrez un ticket privé pour faire examiner votre cas.\n\n'
            '**De quelles informations l’assistance a-t-elle besoin ?**\nProduit, version, environnement, étapes du problème et erreurs pertinentes, après masquage des données sensibles.'),
        'install': ('📚 Guide d’installation',
            '**Avant de commencer**\nSauvegardez vos fichiers, votre configuration et votre base de données. Vérifiez les prérequis exacts du produit.\n\n'
            '**Installez la ressource**\nUtilisez uniquement la livraison officielle. Suivez le README du script, installez les dépendances et exécutez du SQL seulement si la documentation le demande. Respectez l’ordre de chargement.\n\n'
            '**Configurez et testez**\nAjustez les options documentées, testez d’abord dans un environnement de test, puis consultez la console et les journaux. N’écrasez pas d’anciennes configurations sans les comparer.\n\n'
            '**En cas de problème**\nOuvrez un ticket en indiquant le produit, la version, le framework, les étapes et le texte de l’erreur. Masquez les clés et les identifiants secrets. '
            'Ce guide général ne remplace pas les instructions propres à chaque script.'),
        'general': ('💬 Communauté EssChino',
            'Présentez-vous, partagez vos idées et échangez avec la communauté.\n\nPour les achats ou les problèmes techniques, utilisez {support} afin que l’équipe puisse suivre votre dossier en privé.'),
        'suggestions': ('💡 Votre prochaine idée',
            'Proposez des améliorations selon ce format :\n\n**Besoin :** quel problème souhaitez-vous résoudre ?\n**Proposition :** comment cela fonctionnerait-il ?\n'
            '**Exemple :** dans quelle situation l’utiliseriez-vous ?\n\nVous pouvez soutenir les autres idées avec des réactions. Les suggestions ne constituent ni un engagement de développement ni une date de livraison.'),
        'reviews': ('⭐ Expériences clients',
            'Les membres disposant du rôle Client, attribué après vérification d’un achat, peuvent publier ici.\n\n'
            'Indiquez le produit, son utilisation et votre expérience réelle. Ne publiez pas de références de commande, de données personnelles ni de fichiers payants. '
            'Ouvrez un ticket pour résoudre un problème. Aucun avis n’a encore été publié.'),
        'staff': ('👥 Équipe EssChino',
            'Coordonnez ici l’assistance et les contenus officiels.\n\n**Avant de publier :** vérifiez les prérequis, les liens, le prix sur Tebex et les conditions du produit.\n'
            '**Avant de vérifier un client :** contrôlez la commande dans le véritable tableau de bord Tebex ; n’acceptez pas uniquement une capture d’écran.\n'
            '**Tickets :** recueillez les éléments de diagnostic, évitez de demander des secrets et conservez la transcription à la fermeture.\n'
            '**Confidentialité :** ne recopiez pas les informations des commandes dans les canaux publics.'),
        'management': ('📋 Gestion de l’assistance',
            'Les tickets privés sont créés dans **Tickets Abiertos**, tout en haut du serveur. À leur fermeture, ils passent dans **Tickets Cerrados**.\n\n'
            'Chaque dossier permet la fermeture, la réouverture, le téléchargement de sa transcription et la vérification d’un achat après contrôle de la commande dans Tebex.\n\n'
            'Utilisez `/studio tickets` pour consulter les dossiers ouverts et fermés. Attribuez les rôles de l’équipe uniquement aux personnes qui doivent traiter les commandes.'),
        'log': ('📋 Journal de l’assistance',
            'Les ouvertures, fermetures, réouvertures et vérifications de clients sont enregistrées ici.\n\nLes tickets fermés conservent un accès privé. '
            'L’état précédant l’installation et les copies des anciens canaux sont conservés sur le volume privé du bot.'),
        'direction': ('👑 Direction d’EssChino',
            'Ce canal d’origine conserve son historique et reste privé pour le propriétaire et le bot '
            '(Discord autorise également l’accès aux comptes disposant d’Administrateur).\n\n'
            '**Boutique :** configurez le lien officiel avec le bouton ci-dessous.\n'
            '**Produits :** publiez les véritables fiches dans le catalogue et les démonstrations dans le canal prévu.\n'
            '**Équipe :** attribuez les rôles Administration, Développeur et Assistance uniquement à des personnes de confiance.\n'
            '**Clients :** contrôlez la commande dans Tebex et utilisez Vérifier l’achat dans son ticket. La vérification automatique des paiements Tebex n’est pas configurée.\n'
            '**Identité visuelle :** le logo sert d’icône ; la bannière apparaît dans les panneaux. La bannière native du serveur dépend de l’activation de BANNER par Discord.\n\n'
            'Les copies de l’installation et des anciens canaux restent sur le volume privé du bot.'),
        'setup': ('✅ EssChino configuré',
            'Ce canal et son historique ont été conservés en privé. Les autres canaux d’origine ont été sauvegardés puis supprimés ; '
            'Informations, Boutique, Assistance, Communauté et Équipe sont disponibles.\n\n'
            '**Identité visuelle :** logo du serveur et bannière dans les principaux panneaux.\n'
            '**Assistance :** tickets privés, historique conservé à la fermeture, transcriptions et rôle Client après contrôle d’une commande réelle.\n'
            '**Notifications :** rôles facultatifs pour les annonces et les mises à jour.\n\n{setup_shop}'),
        'setup_pending': ('', 'Le lien officiel Tebex manque encore pour relier le bouton d’achat. Vous pouvez le renseigner avec le bouton de configuration ci-dessus.'),
        'setup_configured': ('', 'Le lien officiel Tebex est relié au panneau d’achat.'),
    },
    'de': {
        'welcome': ('👑 Willkommen bei EssChino Studio',
            'Scripts, die dein Projekt zum Leben erwecken.\n\n**Hier geht’s los**\n📜 Lies {rules}.\n'
            '📦 Entdecke {catalog} und {demos}.\n🛒 Kaufe über {shop}.\n🎫 Erhalte Hilfe in {support}.\n'
            '🔔 Wähle deine Benachrichtigungen über die Buttons dieser Nachricht.\n\nUnser Team hilft dir über private Tickets.'),
        'rules': ('📜 EssChino-Regeln',
            '1. Respektiere Mitglieder und Team. Keine Belästigung, Diskriminierung oder Spam.\n'
            '2. Nutze für jede Anfrage den passenden Kanal. Support und Fragen zu Bestellungen gehören in ein Ticket.\n'
            '3. Teile keine kostenpflichtigen Scripts, Leaks, fremden Lizenzen oder Inhalte ohne Erlaubnis.\n'
            '4. Veröffentliche niemals Passwörter, Tokens, Lizenzschlüssel oder Zahlungsdaten.\n'
            '5. Kaufe nur im offiziellen Shop, der auf diesem Server verlinkt ist. Das Team fordert keine Zahlungen per Direktnachricht an.\n'
            '6. Prüfe vor dem Kauf die Voraussetzungen, Abhängigkeiten, Kompatibilität, Lieferung und Bedingungen auf der Produktseite und bei Tebex.\n'
            '7. Der Support muss deine Bestellung prüfen, bevor du die Kundenrolle erhältst. Ein Screenshot oder eine Bestellreferenz allein ist kein Kaufnachweis.\n'
            '8. Bewertungen müssen echte Erfahrungen wiedergeben; Probleme werden über Tickets bearbeitet.\n\nDie Moderation darf Inhalte entfernen, die gegen diese Regeln verstoßen.'),
        'announcements': ('📢 Offizielle Ankündigungen',
            'Hier werden wichtige Neuigkeiten von EssChino Studio veröffentlicht.\n\nAktiviere die gewünschten Benachrichtigungen in {welcome}. '
            'Technische Änderungen findest du in {changelog}; Hilfe erhältst du über {support}. Wir verschicken keine Werbung per Direktnachricht.'),
        'shop': ('🛒 Offizieller EssChino-Shop',
            '{shop_intro}\n\nPrüfe vor der Zahlung die Kompatibilität und Bedingungen des Produkts. Bestellungen werden über Tebex abgewickelt; veröffentliche keine Zahlungsdaten auf Discord.'),
        'shop_configured': ('', 'Entdecke unsere Produkte und schließe deinen Einkauf sicher in unserem Tebex-Shop ab.\n\n{shop_url}'),
        'shop_pending': ('', 'Wir bereiten den Zugang zum offiziellen Shop vor. Bis dahin findest du die Produkte in {catalog} und kannst in {support} eine private Anfrage öffnen.'),
        'catalog': ('📦 Script-Katalog',
            'Dieser Kanal enthält die offiziellen Beschreibungen unserer Produkte.\n\nJeder Beitrag nennt **Name, Funktionen, unterstütztes Framework, Abhängigkeiten, Version, Vorführung und Kauflink**. '
            'Aktuelle Preise und Bedingungen findest du bei Tebex.\n\nSuchst du eine bestimmte Ressource? Frage in {support}. Nur veröffentlichte Produkte sind verfügbar; diese Nachricht kündigt weder Lagerbestand noch Kompatibilität an.'),
        'demos': ('🎬 Vorführungen',
            'Hier findest du Videos und Funktionsbeispiele der veröffentlichten Scripts.\n\nVergleiche die Vorführung vor dem Kauf mit der Produktbeschreibung und ihren Voraussetzungen. '
            'Öffne für Fragen zu einer bestimmten Funktion ein Ticket in {support}. Es wurden noch keine Vorführungen veröffentlicht.'),
        'offers': ('🏷️ Offizielle Angebote',
            'Aktionen werden hier mit dem betreffenden Produkt, den Bedingungen und dem Enddatum angekündigt.\n\n'
            'Maßgeblich ist immer der endgültige Betrag, den Tebex beim Abschluss der Bestellung anzeigt. In diesem Kanal sind derzeit keine Aktionen angekündigt.'),
        'changelog': ('🔄 Versionen und Updates',
            'Jedes Update enthält **Produkt · Version · Änderungen · neue Voraussetzungen · Aktualisierungsschritte**.\n\n'
            'Sichere deinen Server und die Konfiguration vor jedem Update. Aktiviere deine Benachrichtigungen in {welcome}. Es wurden noch keine Versionen veröffentlicht.'),
        'buying': ('🧾 So kaufst du ein',
            '**1. Wähle dein Script** in {catalog} und sieh dir die Vorführung an.\n'
            '**2. Prüfe die Voraussetzungen:** Framework, Versionen, Abhängigkeiten und Lizenzart.\n'
            '**3. Öffne den offiziellen Shop** über {shop}.\n'
            '**4. Schließe die Bestellung bei Tebex ab**, mit der Identität oder dem Konto, das das Produkt verlangt. Bewahre die E-Mail und die Bestellreferenz auf.\n'
            '**5. Prüfe die Lieferung** anhand der Anweisungen von Tebex und des Produkts.\n'
            '**6. Öffne ein Ticket** in {support}, wenn es Probleme gibt oder du deinen Kauf für die Kundenrolle prüfen lassen möchtest.\n\n'
            'Sende keine Kartendaten, Passwörter oder privaten Schlüssel über Discord. Anfallende Steuern, Lieferinformationen und Bedingungen werden an der Kasse angezeigt.'),
        'support': ('🎫 EssChino-Supportcenter',
            'Wähle einen Grund aus dem Menü, um einen privaten Kanal zu öffnen.\n\n'
            '🛒 **Käufe und Bestellungen** · Fragen, Lieferung und Kundenverifizierung.\n'
            '🛠️ **Installation und Support** · Voraussetzungen, Konfiguration und Fehlerdiagnose.\n'
            '🐛 **Fehler** · Schritte zum Nachstellen, Version und Fehlerprotokolle.\n'
            '🤝 **Partnerschaften** · Vorschläge und geschäftliche Anfragen.\n\n'
            'Nenne das Produkt, falls vorhanden die Bestellreferenz, und beschreibe dein Anliegen. Verberge Passwörter, Tokens und Lizenzschlüssel. '
            'Vermeide doppelte Tickets; das Team antwortet je nach Verfügbarkeit.'),
        'faq': ('❓ Häufig gestellte Fragen',
            '**Ist es mit meinem Server kompatibel?**\nPrüfe Framework, Versionen und Abhängigkeiten in der Produktbeschreibung. Frage bei Unklarheiten vor dem Kauf nach.\n\n'
            '**Wo lade ich meinen Kauf herunter?**\nFolge der E-Mail und den Lieferanweisungen von Tebex; dies hängt vom Produkt ab.\n\n'
            '**Wie erhalte ich die Kundenrolle?**\nÖffne ein Ticket zu deinem Kauf. Das Team prüft deine Bestellung bei Tebex.\n\n'
            '**Darf ich ein Script teilen oder weiterverkaufen?**\nPrüfe die Lizenz; der Kauf erlaubt keine Weiterverbreitung.\n\n'
            '**Gibt es Erstattungen oder Lizenzübertragungen?**\nLies die Bedingungen im Shop und an der Kasse. Öffne ein privates Ticket, damit dein Fall geprüft werden kann.\n\n'
            '**Welche Angaben braucht der Support?**\nProdukt, Version, Umgebung, Schritte zum Fehler und relevante Fehlermeldungen mit verborgenen sensiblen Daten.'),
        'install': ('📚 Installationsanleitung',
            '**Bevor du beginnst**\nSichere Dateien, Konfiguration und Datenbank. Prüfe die genauen Voraussetzungen des Produkts.\n\n'
            '**Ressource installieren**\nNutze ausschließlich die offizielle Lieferung. Folge der README des Scripts, installiere die Abhängigkeiten und führe SQL nur aus, wenn die Dokumentation es verlangt. Beachte die Ladereihenfolge.\n\n'
            '**Konfigurieren und testen**\nPasse die dokumentierten Optionen an, teste zuerst in einer Testumgebung und prüfe Konsole sowie Protokolle. Überschreibe alte Konfigurationen nicht, ohne sie zu vergleichen.\n\n'
            '**Wenn etwas nicht funktioniert**\nÖffne ein Ticket mit Produkt, Version, Framework, Arbeitsschritten und Fehlertext. Verberge Schlüssel und Zugangsdaten. '
            'Diese allgemeine Anleitung ersetzt nicht die spezifischen Anweisungen des jeweiligen Scripts.'),
        'general': ('💬 EssChino-Community',
            'Stell dich vor, teile Ideen und unterhalte dich mit der Community.\n\nNutze bei Käufen oder technischen Problemen {support}, damit das Team deinen Fall privat bearbeiten kann.'),
        'suggestions': ('💡 Deine nächste Idee',
            'Schlage Verbesserungen in diesem Format vor:\n\n**Bedarf:** Welches Problem möchtest du lösen?\n**Vorschlag:** Wie würde es funktionieren?\n'
            '**Beispiel:** Wann würdest du es nutzen?\n\nDu kannst andere Ideen mit Reaktionen unterstützen. Vorschläge begründen weder eine Entwicklungszusage noch einen Liefertermin.'),
        'reviews': ('⭐ Kundenerfahrungen',
            'Hier können Mitglieder mit der Kundenrolle schreiben, die nach Prüfung eines Kaufs vergeben wird.\n\n'
            'Beschreibe das Produkt, deine Nutzung und deine tatsächliche Erfahrung. Veröffentliche keine Bestellreferenzen, persönlichen Daten oder kostenpflichtigen Dateien. '
            'Öffne bei Problemen ein Ticket. Es wurden noch keine Bewertungen veröffentlicht.'),
        'staff': ('👥 EssChino-Team',
            'Koordiniert hier den Support und die offiziellen Inhalte.\n\n**Vor der Veröffentlichung:** Prüft Voraussetzungen, Links, den Tebex-Preis und die Produktbedingungen.\n'
            '**Vor der Kundenverifizierung:** Prüft die Bestellung im tatsächlichen Tebex-Dashboard; akzeptiert nicht nur einen Screenshot.\n'
            '**Tickets:** Sammelt Diagnoseinformationen, fordert keine Geheimnisse an und bewahrt das Protokoll beim Schließen auf.\n'
            '**Datenschutz:** Kopiert keine Bestellinformationen in öffentliche Kanäle.'),
        'management': ('📋 Supportverwaltung',
            'Private Tickets werden in **Tickets Abiertos** ganz oben auf dem Server geöffnet. Beim Schließen wechseln sie zu **Tickets Cerrados**.\n\n'
            'Jeder Fall kann geschlossen und wieder geöffnet werden; außerdem lassen sich sein Protokoll herunterladen und Käufe nach Prüfung der Bestellung bei Tebex bestätigen.\n\n'
            'Nutze `/studio tickets`, um offene und geschlossene Fälle anzuzeigen. Vergib Teamrollen nur an Personen, die Bestellungen bearbeiten sollen.'),
        'log': ('📋 Supportprotokoll',
            'Hier werden das Öffnen, Schließen und Wiederöffnen von Tickets sowie Kundenverifizierungen protokolliert.\n\nGeschlossene Tickets bleiben privat zugänglich. '
            'Der Zustand vor der Einrichtung und Kopien der früheren Kanäle liegen auf dem privaten Datenträger des Bots.'),
        'direction': ('👑 EssChino-Verwaltung',
            'Dieser ursprüngliche Kanal behält seinen Verlauf und bleibt für den Eigentümer und den Bot privat '
            '(Discord erlaubt auch Konten mit Administrator den Zugriff).\n\n'
            '**Shop:** Richte den offiziellen Link über den Button unten ein.\n'
            '**Produkte:** Veröffentliche echte Produktbeschreibungen im Katalog und Vorführungen im dafür vorgesehenen Kanal.\n'
            '**Team:** Vergib Verwaltungs-, Entwickler- und Supportrollen nur an vertrauenswürdige Personen.\n'
            '**Kunden:** Prüfe die Bestellung bei Tebex und nutze Kauf verifizieren im zugehörigen Ticket. Eine automatische Tebex-Zahlungsprüfung ist nicht eingerichtet.\n'
            '**Gestaltung:** Das Logo dient als Symbol; das Banner erscheint in den Panels. Das native Serverbanner setzt voraus, dass Discord BANNER freischaltet.\n\n'
            'Kopien der Einrichtung und der früheren Kanäle bleiben auf dem privaten Datenträger des Bots.'),
        'setup': ('✅ EssChino eingerichtet',
            'Dieser Kanal und sein Verlauf wurden privat erhalten. Die anderen ursprünglichen Kanäle wurden gesichert und entfernt; '
            'Informationen, Shop, Support, Community und Team stehen bereit.\n\n'
            '**Gestaltung:** Serverlogo und Banner in den Hauptpanels.\n'
            '**Support:** Private Tickets, Verlaufserhalt beim Schließen, Protokolle und Kundenrolle nach Prüfung einer tatsächlichen Bestellung.\n'
            '**Benachrichtigungen:** Freiwillige Rollen für Ankündigungen und Updates.\n\n{setup_shop}'),
        'setup_pending': ('', 'Der offizielle Tebex-Link fehlt noch für den Kaufbutton. Du kannst ihn über den Konfigurationsbutton oben eingeben.'),
        'setup_configured': ('', 'Der offizielle Tebex-Link ist mit dem Kaufpanel verknüpft.'),
    },
}
