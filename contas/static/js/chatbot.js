document.addEventListener('DOMContentLoaded', function() {
    const chatFab = document.getElementById('chat-fab');
    const chatWindow = document.getElementById('chat-window');
    const closeChat = document.getElementById('close-chat');
    const chatInput = document.getElementById('chat-input');
    const sendBtn = document.getElementById('send-btn');
    const messagesContainer = document.getElementById('chat-messages');

    // Estado local para contas e cartões
    let userContas = [];
    let userCartoes = [];
    let dataLoaded = false;

    // Carrega dados financeiros APENAS quando abrir o chat para evitar requests duplicados na home
    function loadFinancialData() {
        if (dataLoaded) return;
        
        Promise.all([
            fetch('/api/contas/').then(r => r.json()),
            fetch('/api/cartoes/').then(r => r.json())
        ]).then(([contas, cartoes]) => {
            userContas = contas;
            userCartoes = cartoes;
            dataLoaded = true;
            console.log("Chatbot: Dados financeiros carregados.");
        }).catch(err => console.error("Erro ao carregar dados financeiros", err));
    }

    // Toggle Chat Window
    chatFab.addEventListener('click', () => {
        loadFinancialData(); // Lazy load
        chatWindow.classList.toggle('open');
        if (chatWindow.classList.contains('open')) {
            setTimeout(() => chatInput.focus(), 300);
        }
    });

    closeChat.addEventListener('click', () => {
        chatWindow.classList.remove('open');
    });

    // Send Message Logic
    function sendMessage() {
        const text = chatInput.value.trim();
        if (!text) return;

        // Add User Message
        appendMessage(text, 'user');
        chatInput.value = '';

        // Add Loading Indicator
        const loadingId = appendLoading();

        fetch(API_CHAT_URL, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': CSRF_TOKEN
            },
            body: JSON.stringify({ message: text })
        })
        .then(response => response.json())
        .then(data => {
            removeLoading(loadingId);
            if (data.error) {
                appendMessage("❌ Erro: " + data.error, 'bot');
            } else if (data.is_action) {
                appendActionCard(data.response);
            } else {
                appendMessage(data.response, 'bot');
            }
        })
        .catch(error => {
            removeLoading(loadingId);
            appendMessage("❌ Erro de conexão. Tente novamente.", 'bot');
            console.error('Error:', error);
        });
    }

    sendBtn.addEventListener('click', sendMessage);
    chatInput.addEventListener('keypress', (e) => {
        if (e.key === 'Enter') sendMessage();
    });

    // Helper Functions
    function appendMessage(text, role) {
        const div = document.createElement('div');
        div.className = `message ${role}`;
        
        // Verifica se é objeto (pode acontecer se vier do historico) ou string
        let content = (typeof text === 'object') ? JSON.stringify(text) : text;

        let formattedText = content.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>');
        formattedText = formattedText.replace(/\n/g, '<br>');

        div.innerHTML = formattedText;
        messagesContainer.appendChild(div);
        scrollToBottom();
    }

    // --- PERSISTÊNCIA DO CHAT (SessionStorage + Nav Type) ---
    // Reseta apenas no reload forçado (F5), mantém na navegação
    try {
        const navEntries = performance.getEntriesByType("navigation");
        if (navEntries.length > 0 && navEntries[0].type === 'reload') {
            sessionStorage.removeItem('chat_history_html');
            console.log("Chat resetado (Page Reload)");
        } else {
            const savedChat = sessionStorage.getItem('chat_history_html');
            if (savedChat) {
                messagesContainer.innerHTML = savedChat;
                scrollToBottom();
                // Reatacha listeners aos botões reconstruídos do HTML salvo
                reattachListeners(); 
            }
        }
    } catch (e) {
        console.warn("Erro na persistência do chat:", e);
    }

    function saveChatState() {
        sessionStorage.setItem('chat_history_html', messagesContainer.innerHTML);
    }

    // Reattach listeners after restoring HTML from storage
    function reattachListeners() {
        document.querySelectorAll('.action-card').forEach(card => {
             // Como não temos o objeto 'data' original aqui facilmente, 
             // e o HTML já está renderizado, assumimos que se estiver 'Processando' ou 'Sucesso',
             // não precisa rebindar ação. Se estiver pendente, removemos para evitar click morto
             // ou idealmente re-bindamos. Por simplificação:
             // Se o card ainda tem botões ativos, avisamos que expirou ou removemos.
             // Melhor UX: remover cards pendentes antigos para não quebrar lógica
             if(card.querySelector('button:not([disabled])')) {
                 card.remove(); 
             }
        });
    }

    // --- UTILS EVENTOS ---
    function dispatchUpdateEvent(type) {
        // Dispara evento global para quem estiver ouvindo (listagem, gerenciar, etc)
        document.dispatchEvent(new CustomEvent(type));
        // Dispara evento genérico também
        document.dispatchEvent(new CustomEvent('dataChanged'));
    }

    // --- RENDERIZAÇÃO DE CARDS DE AÇÃO ---
    function appendActionCard(actionData) {
        const div = document.createElement('div');
        div.className = 'message bot';
        
        // Header com o fallback text
        div.innerHTML = `<div><strong>${actionData.text_fallback}</strong></div>`;
        messagesContainer.appendChild(div);

        // Dispatcher baseado no tipo de ação
        switch(actionData.action) {
            case 'create_transaction':
            case 'edit_transaction':
            case 'delete_transaction':
                renderTransactionCard(actionData, div);
                break;
            case 'create_category':
            case 'edit_category':
            case 'delete_category':
                renderCategoryCard(actionData, div);
                break;
            case 'create_account':
            case 'edit_account':
            case 'delete_account':
                renderAccountCard(actionData, div);
                break;
            case 'create_card':
            case 'edit_card':
            case 'delete_card':
                renderCardCard(actionData, div);
                break;
            default:
                div.innerHTML += `<div class="text-danger">Ação desconhecida: ${actionData.action}</div>`;
        }
        
        scrollToBottom();
        saveChatState(); // Salva estado
    }

    function appendMessage(text, role) {
        const div = document.createElement('div');
        div.className = `message ${role}`;
        
        let content = (typeof text === 'object') ? JSON.stringify(text) : text;
        let formattedText = content.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>');
        formattedText = formattedText.replace(/\n/g, '<br>');

        div.innerHTML = formattedText;
        messagesContainer.appendChild(div);
        scrollToBottom();
        saveChatState(); // Salva estado
    }

    // --- CARD: TRANSAÇÃO ---
    function renderTransactionCard(actionData, containerDiv) {
        const data = actionData.data || actionData; // Fallback se passar direto
        const action = actionData.action || 'create_transaction';
        
        const cardDiv = document.createElement('div');
        cardDiv.className = 'action-card mt-2';
        
        let title = "Confirmar Transação";
        let btnText = "Confirmar";
        let btnClass = "btn-success";
        
        if (action === 'edit_transaction') {
            title = "Editar Transação"; 
            btnText = "Salvar Alterações";
        }
        if (action === 'delete_transaction') {
            title = "Excluir Transação"; 
            btnText = "Excluir Definitivamente"; 
            btnClass = "btn-danger";
        }

        if (action === 'delete_transaction') {
            cardDiv.innerHTML = `
                <h6><i class="bi bi-trash"></i> ${title}</h6>
                <input type="hidden" id="act-id" value="${data.id || ''}">
                <p class="text-danger mb-2 small">Tem certeza que deseja excluir: <strong>${data.descricao}</strong> (R$ ${data.valor})?</p>
                <div class="d-flex gap-2 mt-3">
                    <button class="btn btn-sm ${btnClass} w-100" id="btn-confirm-tx"><i class="bi bi-check-lg"></i> ${btnText}</button>
                    <button class="btn btn-sm btn-outline-secondary w-100" id="btn-cancel-tx">Cancelar</button>
                </div>
            `;
        } else {
            // Create / Edit
            cardDiv.innerHTML = `
                <h6><i class="bi bi-pencil-square"></i> ${title}</h6>
                <input type="hidden" id="act-id" value="${data.id || ''}">
                
                <label class="small text-muted">Descrição</label>
                <input type="text" class="form-control form-control-sm mb-2" id="act-desc" value="${data.descricao || ''}">
                
                <div class="row g-2">
                    <div class="col-6">
                        <label class="small text-muted">Valor (R$)</label>
                        <input type="number" step="0.01" class="form-control form-control-sm" id="act-valor" value="${data.valor}">
                    </div>
                    <div class="col-6">
                        <label class="small text-muted">Tipo</label>
                        <select class="form-select form-select-sm" id="act-tipo">
                            <option value="D" ${data.tipo === 'D' ? 'selected' : ''}>Despesa</option>
                            <option value="R" ${data.tipo === 'R' ? 'selected' : ''}>Receita</option>
                        </select>
                    </div>
                </div>

                <label class="small text-muted mt-2">Categoria</label>
                ${(() => {
                    if (data.available_categories && data.available_categories.length > 0) {
                        let html = '<select class="form-select form-select-sm mb-2" id="act-cat">';
                        html += '<option value="">-- Selecione --</option>';
                        let current = data.categoria || data.categoria_nome || '';
                        data.available_categories.forEach(cat => {
                            let sel = (cat === current) ? 'selected' : '';
                            html += `<option value="${cat}" ${sel}>${cat}</option>`;
                        });
                        // Se o valor atual não estiver na lista (ex: nova cat inferida), adiciona
                        if (current && !data.available_categories.includes(current)) {
                             html += `<option value="${current}" selected>${current}</option>`;
                        }
                        return html + '</select>';
                    } else {
                        return `<input type="text" class="form-control form-control-sm mb-2" id="act-cat" value="${data.categoria || data.categoria_nome || ''}">`;
                    }
                })()}

                <div class="row g-2">
                    <div class="col-6">
                        <label class="small text-muted">Data</label>
                        <input type="date" class="form-control form-control-sm" id="act-data" value="${data.data || new Date().toISOString().split('T')[0]}">
                    </div>
                    <div class="col-6">
                        <label class="small text-muted">Pago em (Conta/Cartão)</label>
                        <select class="form-select form-select-sm" id="act-pagamento">
                            ${gerarOpcoesPagamento(data.conta || data.conta_nome, data.cartao || data.cartao_nome)}
                        </select>
                    </div>
                </div>

                <div class="d-flex gap-2 mt-3">
                    <button class="btn btn-sm ${btnClass} w-100" id="btn-confirm-tx"><i class="bi bi-check-lg"></i> ${btnText}</button>
                    <button class="btn btn-sm btn-outline-secondary w-100" id="btn-cancel-tx">Cancelar</button>
                </div>
            `;
        }
        
        containerDiv.appendChild(cardDiv);

        cardDiv.querySelector('#btn-confirm-tx').addEventListener('click', () => executarAcaoTransacao(action, cardDiv));
        cardDiv.querySelector('#btn-cancel-tx').addEventListener('click', () => { 
            cardDiv.remove(); 
            appendMessage("Cancelado.", 'bot'); 
            saveChatState();
        });
    }

    // --- CARD: CATEGORIA ---
    function renderCategoryCard(actionData, containerDiv) {
        const data = actionData.data;
        const action = actionData.action;
        const cardDiv = document.createElement('div');
        cardDiv.className = 'action-card mt-2 border-warning';
        
        let title = "Nova Categoria";
        let btnclass = "btn-primary";
        if(action === 'edit_category') title = "Editar Categoria";
        if(action === 'delete_category') { title = "Excluir Categoria"; btnclass = "btn-danger"; }

        let contentObj = '';
        if (action === 'delete_category') {
            contentObj = `<p class="text-danger mb-2 small">Tem certeza que deseja excluir a categoria ID <strong>${data.id}</strong>? Essa ação não pode ser desfeita.</p>`;
        } else {
            contentObj = `
                <label class="small text-muted">Nome da Categoria</label>
                <input type="text" class="form-control form-control-sm" id="cat-nome" value="${data.nome || data.novo_nome || ''}">
            `;
        }

        cardDiv.innerHTML = `
            <h6 class="text-warning"><i class="bi bi-tags"></i> ${title}</h6>
            <input type="hidden" id="cat-id" value="${data.id || ''}">
            ${contentObj}
            <div class="d-flex gap-2 mt-3">
                <button class="btn btn-sm ${btnclass} w-100" id="btn-confirm-cat">Confirmar</button>
                <button class="btn btn-sm btn-outline-secondary w-100" id="btn-cancel-cat">Cancelar</button>
            </div>
        `;
        containerDiv.appendChild(cardDiv);

        cardDiv.querySelector('#btn-confirm-cat').addEventListener('click', () => executarAcaoCategoria(action, cardDiv));
        cardDiv.querySelector('#btn-cancel-cat').addEventListener('click', () => { 
            cardDiv.remove(); 
            appendMessage("Cancelado.", 'bot');
            saveChatState();
        });
    }


    // --- CARD: CONTA ---
    function renderAccountCard(actionData, containerDiv) {
        const data = actionData.data;
        const action = actionData.action;
        const cardDiv = document.createElement('div');
        cardDiv.className = 'action-card mt-2 border-info';
        
        let title = "Nova Conta";
        let btnclass = "btn-primary";
        if(action === 'edit_account') title = "Editar Conta";
        if(action === 'delete_account') { title = "Excluir Conta"; btnclass = "btn-danger"; }

        let contentObj = '';
        if (action === 'delete_account') {
            contentObj = `<p class="text-danger mb-2 small">Tem certeza que deseja excluir a conta ID <strong>${data.id}</strong>?</p>`;
        } else {
            contentObj = `
                <label class="small text-muted">Nome</label>
                <input type="text" class="form-control form-control-sm mb-2" id="conta-nome" value="${data.nome || ''}">
                <label class="small text-muted">Instituição</label>
                <input type="text" class="form-control form-control-sm mb-2" id="conta-inst" value="${data.instituicao || ''}">
                <label class="small text-muted">Saldo Inicial</label>
                <input type="number" step="0.01" class="form-control form-control-sm" id="conta-saldo" value="${data.saldo_inicial || 0}">
            `;
        }

        cardDiv.innerHTML = `
            <h6 class="text-info"><i class="bi bi-wallet2"></i> ${title}</h6>
            <input type="hidden" id="conta-id" value="${data.id || ''}">
            ${contentObj}
            <div class="d-flex gap-2 mt-3">
                <button class="btn btn-sm ${btnclass} w-100" id="btn-confirm-conta">Confirmar</button>
                <button class="btn btn-sm btn-outline-secondary w-100" id="btn-cancel-conta">Cancelar</button>
            </div>
        `;
        containerDiv.appendChild(cardDiv);

        cardDiv.querySelector('#btn-confirm-conta').addEventListener('click', () => executarAcaoConta(action, cardDiv));
        cardDiv.querySelector('#btn-cancel-conta').addEventListener('click', () => { 
            cardDiv.remove(); 
            appendMessage("Cancelado.", 'bot');
            saveChatState();
        });
    }

    // --- CARD: CARTÃO ---
    function renderCardCard(actionData, containerDiv) {
        const data = actionData.data;
        const action = actionData.action;
        const cardDiv = document.createElement('div');
        cardDiv.className = 'action-card mt-2 border-primary';
        
        let title = "Novo Cartão";
        let btnclass = "btn-primary";
        if(action === 'edit_card') title = "Editar Cartão";
        if(action === 'delete_card') { title = "Excluir Cartão"; btnclass = "btn-danger"; }

        let contentObj = '';
        if (action === 'delete_card') {
            contentObj = `<p class="text-danger mb-2 small">Tem certeza que deseja excluir o cartão <strong>${data.nome}</strong>?</p>`;
        } else {
            contentObj = `
                <label class="small text-muted">Nome</label>
                <input type="text" class="form-control form-control-sm mb-2" id="card-nome" value="${data.nome || ''}">
                <div class="row g-2">
                    <div class="col-6">
                        <label class="small text-muted">Limite</label>
                        <input type="number" step="0.01" class="form-control form-control-sm" id="card-limite" value="${data.limite || ''}">
                    </div>
                     <div class="col-6">
                        <label class="small text-muted">Bandeira</label>
                        <select class="form-select form-select-sm" id="card-bandeira">
                            <option value="MASTERCARD" ${data.bandeira === 'MASTERCARD' ? 'selected' : ''}>Mastercard</option>
                            <option value="VISA" ${data.bandeira === 'VISA' ? 'selected' : ''}>Visa</option>
                        </select>
                    </div>
                </div>
                <div class="row g-2 mt-2">
                    <div class="col-6">
                        <label class="small text-muted">Dia Venc.</label>
                        <input type="number" class="form-control form-control-sm" id="card-venc" value="${data.dia_vencimento || ''}">
                    </div>
                    <div class="col-6">
                        <label class="small text-muted">Dia Fech.</label>
                        <input type="number" class="form-control form-control-sm" id="card-fech" value="${data.dia_fechamento || ''}">
                    </div>
                </div>
            `;
        }

        cardDiv.innerHTML = `
            <h6 class="text-primary"><i class="bi bi-credit-card"></i> ${title}</h6>
            <input type="hidden" id="card-id" value="${data.id || ''}">
            ${contentObj}
            <div class="d-flex gap-2 mt-3">
                <button class="btn btn-sm ${btnclass} w-100" id="btn-confirm-card">Confirmar</button>
                <button class="btn btn-sm btn-outline-secondary w-100" id="btn-cancel-card">Cancelar</button>
            </div>
        `;
        containerDiv.appendChild(cardDiv);

        cardDiv.querySelector('#btn-confirm-card').addEventListener('click', () => executarAcaoCartao(action, cardDiv));
        cardDiv.querySelector('#btn-cancel-card').addEventListener('click', () => { 
            cardDiv.remove(); 
            appendMessage("Cancelado.", 'bot');
            saveChatState();
        });
    }

    // --- EXECUÇÃO: TRANSAÇÃO ---
    function executarAcaoTransacao(action, cardElement) {
        const id = cardElement.querySelector('#act-id').value;
        
        let url = '/api/transacoes/';
        let method = 'POST';
        let body = {};
        
        if (action !== 'delete_transaction') {
            const pagamentoSel = cardElement.querySelector('#act-pagamento').value;
            const [tipoPgto, nomePgto] = pagamentoSel.split(':'); 
            
            body = {
                descricao: cardElement.querySelector('#act-desc').value,
                valor: cardElement.querySelector('#act-valor').value,
                tipo: cardElement.querySelector('#act-tipo').value,
                categoria_nome: cardElement.querySelector('#act-cat').value,
                data: cardElement.querySelector('#act-data').value,
                conta_nome: (tipoPgto === 'CONTA') ? nomePgto : '',
                cartao_nome: (tipoPgto === 'CARTAO') ? nomePgto : ''
            };
        }

        if (action === 'edit_transaction') {
            url += `${id}/`; 
            method = 'PUT';
        } 
        else if (action === 'delete_transaction') {
            url += `${id}/`; 
            method = 'DELETE';
            body = {};
        }

        enviarRequest(url, method, body, cardElement, "Transação processada!", 'transactionCreated');
    }

    // --- EXECUÇÃO: CATEGORIA ---
    function executarAcaoCategoria(action, cardElement) {
        const id = cardElement.querySelector('#cat-id').value;
        const nome = cardElement.querySelector('#cat-nome') ? cardElement.querySelector('#cat-nome').value : null;
        
        let url = '/api/categorias/';
        let method = 'POST';
        let body = { nome };

        if(action === 'edit_category') { url += `${id}/`; method = 'PUT'; }
        if(action === 'delete_category') { url += `${id}/`; method = 'DELETE'; body = {}; }

        enviarRequest(url, method, body, cardElement, "Categoria atualizada!", 'categoryUpdated');
    }

    // --- EXECUÇÃO: CONTA ---
    function executarAcaoConta(action, cardElement) {
        const id = cardElement.querySelector('#conta-id').value;
        const nome = cardElement.querySelector('#conta-nome') ? cardElement.querySelector('#conta-nome').value : null;
        
        let url = '/api/contas/';
        let method = 'POST';
        let body = {};
        
        if (action !== 'delete_account') {
            body = {
                nome: nome,
                instituicao: cardElement.querySelector('#conta-inst').value,
                saldo_inicial: cardElement.querySelector('#conta-saldo').value
            };
        }

        if(action === 'edit_account') { url += `${id}/`; method = 'PUT'; }
        if(action === 'delete_account') { url += `${id}/`; method = 'DELETE'; body = {}; }

        enviarRequest(url, method, body, cardElement, "Conta atualizada!", 'accountUpdated');
    }
    
    // --- EXECUÇÃO: CARTÃO ---
    function executarAcaoCartao(action, cardElement) {
        const id = cardElement.querySelector('#card-id').value;
        const nome = cardElement.querySelector('#card-nome') ? cardElement.querySelector('#card-nome').value : null;
        
        let url = '/api/cartoes/';
        let method = 'POST';
        let body = {};
        
        if (action !== 'delete_card') {
            body = {
                nome: nome,
                limite: cardElement.querySelector('#card-limite').value,
                dia_vencimento: cardElement.querySelector('#card-venc').value,
                dia_fechamento: cardElement.querySelector('#card-fech').value,
                bandeira: cardElement.querySelector('#card-bandeira').value
            };
        }

        if(action === 'edit_card') { url += `${id}/`; method = 'PUT'; }
        if(action === 'delete_card') { url += `${id}/`; method = 'DELETE'; body = {}; }

        enviarRequest(url, method, body, cardElement, "Cartão atualizado!", 'cardUpdated');
    }

    // --- HELPER DE REQUEST GENÉRICO ---
    function enviarRequest(url, method, body, cardElement, successMsg, customEventType) {
        const btn = cardElement.querySelector('button'); // Pega o primeiro botão (Confirmar)
        btn.disabled = true;
        btn.innerHTML = '<span class="spinner-border spinner-border-sm"></span> Processando...';

        fetch(url, {
            method: method,
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': CSRF_TOKEN
            },
            body: Object.keys(body).length > 0 ? JSON.stringify(body) : null
        })
        .then(async r => {
             if (r.status === 204) return {};
             if (r.ok) return r.json(); 
             // Tenta extrair erro do JSON
             let errorMsg = "Erro na requisição";
             try {
                 const errData = await r.json();
                 // Se for erro de validação (DRF retorna objeto {campo: [erros]})
                 if (typeof errData === 'object') {
                     // Pega o primeiro valor da primeira chave
                     const values = Object.values(errData);
                     if (values.length > 0) errorMsg = values[0][0] || JSON.stringify(errData);
                     else errorMsg = JSON.stringify(errData);
                 }
             } catch(e) {
                 console.error("Erro ao fazer parse do JSON de erro:", e);
             }
             console.error("Erro API:", r.status, r.statusText, errorMsg);
             throw new Error(errorMsg);
        })
        .then(data => {
            cardElement.innerHTML = `<div class="text-success"><i class="bi bi-check-circle-fill"></i> ${successMsg}</div>`;
            if(customEventType) dispatchUpdateEvent(customEventType);
            saveChatState(); // Salva estado atualizado (card sucesso)
        })
        .catch(err => {
            // Remove o prefixo "Error: " se existir
            let msg = err.toString().replace('Error: ', '');
            alert('❌ ' + msg);
            btn.disabled = false;
            btn.innerHTML = 'Tentar Novamente';
        });
    }

    function appendLoading() {
        const id = 'loading-' + Date.now();
        const div = document.createElement('div');
        div.id = id;
        div.className = 'message bot loading-dots';
        div.innerHTML = '<span></span><span></span><span></span>';
        messagesContainer.appendChild(div);
        scrollToBottom();
        return id;
    }

    function removeLoading(id) {
        const el = document.getElementById(id);
        if (el) el.remove();
    }

    function scrollToBottom() {
        messagesContainer.scrollTop = messagesContainer.scrollHeight;
    }

    function gerarOpcoesPagamento(contaSugerida, cartaoSugerido) {
        let html = '';
        
        // 1. Determina quem deve ser selecionado por padrão
        let selectedValue = '';
        let foundMatch = false;

        // Busca match em Contas
        if (contaSugerida && userContas.length > 0) {
            const match = userContas.find(c => c.nome.toLowerCase().includes(contaSugerida.toLowerCase()));
            if (match) {
                selectedValue = `CONTA:${match.nome}`;
                foundMatch = true;
            }
        }

        // Busca match em Cartões (se não achou em contas ou se cartaoSugerido é prioritário?)
        // Se cartaoSugerido existe, ele veio da IA, então tem prioridade
        if (cartaoSugerido && userCartoes.length > 0) {
            const match = userCartoes.find(c => c.nome.toLowerCase().includes(cartaoSugerido.toLowerCase()));
            if (match) {
                selectedValue = `CARTAO:${match.nome}`;
                foundMatch = true;
            }
        }

        // Regras de Fallback (Default)
        if (!foundMatch) {
            if (cartaoSugerido && userCartoes.length > 0) {
                // IA sugeriu cartão (ex: "crédito") mas não achou nome -> Default: 1º Cartão
                selectedValue = `CARTAO:${userCartoes[0].nome}`;
            } else if (userContas.length > 0) {
                // Caso contrário (sem sugestão ou sugestão de conta falha) -> Default: 1ª Conta
                selectedValue = `CONTA:${userContas[0].nome}`;
            }
        }

        // 2. Gera HTML
        // --- CONTAS ---
        if (userContas.length > 0) {
            html += '<optgroup label="Contas">';
            userContas.forEach(conta => {
                const val = `CONTA:${conta.nome}`;
                const isSel = (val === selectedValue);
                html += `<option value="${val}" ${isSel ? 'selected' : ''}>${conta.nome}</option>`;
            });
            html += '</optgroup>';
        }

        // --- CARTÕES ---
        if (userCartoes.length > 0) {
            html += '<optgroup label="Cartões de Crédito">';
            userCartoes.forEach(cartao => {
                const val = `CARTAO:${cartao.nome}`;
                const isSel = (val === selectedValue);
                html += `<option value="${val}" ${isSel ? 'selected' : ''}>${cartao.nome}</option>`;
            });
            html += '</optgroup>';
        }
        
        // Se não tiver nada, adiciona opção vazia
        if (html === '') {
             html = '<option value="">Nenhuma conta/cartão</option>';
        }
        
        return html;
    }
});
