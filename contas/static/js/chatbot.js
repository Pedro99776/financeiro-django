document.addEventListener('DOMContentLoaded', function() {
    const chatFab = document.getElementById('chat-fab');
    const chatWindow = document.getElementById('chat-window');
    const closeChat = document.getElementById('close-chat');
    const chatInput = document.getElementById('chat-input');
    const sendBtn = document.getElementById('send-btn');
    const messagesContainer = document.getElementById('chat-messages');

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
        
        // Formata Markdown básico (**negrito**)
        let formattedText = text.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>');
        
        // Converte quebras de linha
        formattedText = formattedText.replace(/\n/g, '<br>');

        div.innerHTML = formattedText;
        messagesContainer.appendChild(div);
        scrollToBottom();
        
        // Verifica se é um comando de ação (Exemplo para futuro: Preview Card)
        // detectar_action_card(text, div);
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
});
