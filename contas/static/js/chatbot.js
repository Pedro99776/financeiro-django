document.addEventListener('DOMContentLoaded', function() {
    const chatFab = document.getElementById('chat-fab');
    const chatWindow = document.getElementById('chat-window');
    const closeChat = document.getElementById('close-chat');
    const chatInput = document.getElementById('chat-input');
    const sendBtn = document.getElementById('send-btn');
    const messagesContainer = document.getElementById('chat-messages');

    // Estado local para contas
    let userContas = [];

    // Carrega contas ao iniciar
    fetch('/api/contas/')
        .then(r => r.json())
        .then(data => {
            userContas = data;
        })
        .catch(err => console.error("Erro ao carregar contas para o chat", err));

    // Toggle Chat Window
    chatFab.addEventListener('click', () => {
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

        // Call API
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
                // Renderiza Card de Ação
                appendActionCard(data.response);
            } else {
                // Texto normal
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

    // --- RENDERIZAÇÃO DE CARDS DE AÇÃO ---
    function appendActionCard(actionData) {
        const data = actionData.data;
        const div = document.createElement('div');
        div.className = 'message bot';
        
        // HTML do Formulário Pré-preenchido
        div.innerHTML = `
            <div><strong>${actionData.text_fallback}</strong></div>
            <div class="action-card">
                <h6><i class="bi bi-pencil-square"></i> Confirmar Transação</h6>
                
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
                <input type="text" class="form-control form-control-sm mb-2" id="act-cat" value="${data.categoria || ''}">

                <div class="row g-2">
                    <div class="col-6">
                        <label class="small text-muted">Data</label>
                        <input type="date" class="form-control form-control-sm" id="act-data" value="${data.data || new Date().toISOString().split('T')[0]}">
                    </div>
                    <div class="col-6">
                        <label class="small text-muted">Conta</label>
                        <select class="form-select form-select-sm" id="act-conta">
                            ${gerarOpcoesContas(data.conta)}
                        </select>
                    </div>
                </div>

                <div class="d-flex gap-2 mt-3">
                    <button class="btn btn-sm btn-success w-100" id="btn-confirm-action"><i class="bi bi-check-lg"></i> Confirmar</button>
                    <button class="btn btn-sm btn-outline-secondary w-100" id="btn-cancel-action">Cancelar</button>
                </div>
            </div>
        `;
        
        messagesContainer.appendChild(div);
        scrollToBottom();

        // Event Listeners dos Botões do Card
        div.querySelector('#btn-confirm-action').addEventListener('click', () => {
            executarAcaoCriacao(div);
        });

        div.querySelector('#btn-cancel-action').addEventListener('click', () => {
            div.remove();
            appendMessage("Cancelei a operação.", 'bot');
        });
    }

    function executarAcaoCriacao(cardElement) {
        // Coleta dados do form
        const payload = {
            descricao: cardElement.querySelector('#act-desc').value,
            valor: cardElement.querySelector('#act-valor').value,
            tipo: cardElement.querySelector('#act-tipo').value,
            categoria_nome: cardElement.querySelector('#act-cat').value,
            data: cardElement.querySelector('#act-data').value,
            conta_nome: cardElement.querySelector('#act-conta').options[cardElement.querySelector('#act-conta').selectedIndex].text
        };

        // UI Feedback
        const btn = cardElement.querySelector('#btn-confirm-action');
        btn.disabled = true;
        btn.innerHTML = '<span class="spinner-border spinner-border-sm"></span> Salvando...';

        // POST para API de Transações
        fetch('/api/transacoes/', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': CSRF_TOKEN
            },
            body: JSON.stringify(payload)
        })
        .then(r => r.json())
        .then(data => {
            if (data.id) {
                // Sucesso
                cardElement.innerHTML = `
                    <div class="text-success">
                        <i class="bi bi-check-circle-fill"></i> 
                        Transação <strong>${data.descricao}</strong> criada com sucesso!
                    </div>
                `;
                // Recarrega a página para atualizar o extrato (Soft Reload)
                // Dispara evento que a listagem.html está ouvindo
                document.dispatchEvent(new CustomEvent('transactionCreated'));
            } else {
                // Erro de validação
                alert('Erro: ' + JSON.stringify(data));
                btn.disabled = false;
                btn.innerHTML = 'Tentar Novamente';
            }
        })
        .catch(err => {
            alert('Erro de conexão ao salvar.');
            btn.disabled = false;
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

    function gerarOpcoesContas(contaSugerida) {
        if (!userContas || userContas.length === 0) {
            return '<option value="" selected>Padrão</option>';
        }
        
        let html = '';
        let selecionado = false;
        
        // Tenta encontrar match com a sugestão da IA
        userContas.forEach(conta => {
            const isMatch = contaSugerida && conta.nome.toLowerCase().includes(contaSugerida.toLowerCase());
            if (isMatch) selecionado = true;
            html += `<option value="${conta.id}" ${isMatch ? 'selected' : ''}>${conta.nome}</option>`;
        });

        // Se nada foi selecionado pela IA, seleciona a primeira conta (regra de negócio)
        if (!selecionado && !contaSugerida) {
             // O browser já seleciona o primeiro option por padrão, mas podemos forçar se quiser
        }
        
        return html;
    }
});
