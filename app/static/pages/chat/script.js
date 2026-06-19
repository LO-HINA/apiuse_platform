// 鉴权守卫: 没有 token 跳登录页
(function authGuard() {
    if (!localStorage.getItem('access_token')) {
        window.location.href = '/login';
    }
})();

document.addEventListener('DOMContentLoaded', () => {
    const chatMain = document.getElementById('chat-main');
    const chatContainer = document.getElementById('chat-container');
    const messageInput = document.getElementById('message-input');
    const sendBtn = document.getElementById('send-btn');
    const statusIndicator = document.getElementById('status-indicator');
    const newChatBtn = document.getElementById('new-chat-btn');
    const composerForm = document.getElementById('composer-form');

    let currentEventSource = null;
    let currentSessionId = null;

    // 用户信息 + 登出
    const logoutBtn = document.getElementById('logout-btn');
    if (logoutBtn) {
        logoutBtn.addEventListener('click', () => {
            localStorage.removeItem('access_token');
            window.location.href = '/login';
        });
    }

    loadUserInfo();

    async function loadUserInfo() {
        const token = localStorage.getItem('access_token');
        if (!token) return;
        try {
            const res = await fetch('/api/auth/me', {
                headers: { Authorization: `Bearer ${token}` },
            });
            if (!res.ok) {
                localStorage.removeItem('access_token');
                window.location.href = '/login';
                return;
            }
            const user = await res.json();
            const nameEl = document.getElementById('user-name');
            const avatarEl = document.getElementById('user-avatar');
            if (nameEl) nameEl.textContent = user.display_name || user.username;
            if (avatarEl) avatarEl.textContent = (user.display_name || user.username).charAt(0).toUpperCase();
        } catch (err) {
            // 忽略网络错误，保持页面可用
        }
    }

    messageInput.addEventListener('input', resizeInput);
    messageInput.addEventListener('keydown', (event) => {
        if (event.key === 'Enter' && !event.shiftKey) {
            event.preventDefault();
            sendMessage();
        }
    });
    composerForm.addEventListener('submit', (event) => {
        event.preventDefault();
        sendMessage();
    });

    if (newChatBtn) {
        newChatBtn.addEventListener('click', resetChat);
    }

    function resizeInput() {
        messageInput.style.height = 'auto';
        messageInput.style.height = `${Math.min(messageInput.scrollHeight, 200)}px`;
        if (!messageInput.value) {
            messageInput.style.height = 'auto';
        }
    }

    function enterChatMode() {
        chatMain.classList.add('is-chatting');
    }

    function resetChat() {
        if (currentEventSource) {
            currentEventSource.close();
            currentEventSource = null;
        }

        currentSessionId = null;
        chatContainer.innerHTML = '';
        chatMain.classList.remove('is-chatting');
        sendBtn.disabled = false;
        hideStatus();
        messageInput.value = '';
        resizeInput();
        messageInput.focus();
    }

    function sendMessage() {
        const text = messageInput.value.trim();
        if (!text || currentEventSource) return;

        enterChatMode();
        appendMessage('user', text);
        messageInput.value = '';
        resizeInput();
        streamAIResponse(text);
    }

    function appendMessage(role, text) {
        const messageDiv = document.createElement('div');
        messageDiv.className = `message ${role}-message`;

        const avatarDiv = document.createElement('div');
        avatarDiv.className = 'avatar';
        avatarDiv.textContent = role === 'user' ? 'Me' : 'AI';

        const contentDiv = document.createElement('div');
        contentDiv.className = 'message-content';
        contentDiv.textContent = text;

        messageDiv.append(avatarDiv, contentDiv);
        chatContainer.appendChild(messageDiv);
        scrollToBottom();
        return contentDiv;
    }

    function scrollToBottom() {
        chatContainer.scrollTop = chatContainer.scrollHeight;
    }

    function streamAIResponse(userMessage) {
        const aiContentNode = appendMessage('ai', '');
        showStatus();

        const params = new URLSearchParams({ message: userMessage });
        if (currentSessionId) {
            params.set('session_id', currentSessionId);
        }

        const eventSource = new EventSource(`/api/chat/stream?${params.toString()}`);
        currentEventSource = eventSource;
        sendBtn.disabled = true;

        eventSource.onmessage = (event) => {
            if (event.data === '[DONE]') {
                closeStream();
                return;
            }

            let payload;
            try {
                payload = JSON.parse(event.data);
            } catch (err) {
                aiContentNode.textContent += event.data;
                scrollToBottom();
                return;
            }

            if (typeof payload.session_id === 'string') {
                currentSessionId = payload.session_id;
                return;
            }

            if (typeof payload.token === 'string') {
                aiContentNode.textContent += payload.token;
                scrollToBottom();
                return;
            }

            if (typeof payload.error === 'string') {
                aiContentNode.textContent += `\n[错误] ${payload.error}`;
                scrollToBottom();
            }
        };

        eventSource.onerror = () => {
            if (eventSource.readyState !== EventSource.CLOSED) {
                return;
            }
            if (!aiContentNode.textContent) {
                aiContentNode.textContent = '[连接出错，请稍后重试]';
            }
            closeStream();
        };

        function closeStream() {
            eventSource.close();
            currentEventSource = null;
            sendBtn.disabled = false;
            hideStatus();
            messageInput.focus();
        }
    }

    function showStatus() {
        if (statusIndicator) {
            statusIndicator.style.display = 'flex';
        }
    }

    function hideStatus() {
        if (statusIndicator) {
            statusIndicator.style.display = 'none';
        }
    }
});
