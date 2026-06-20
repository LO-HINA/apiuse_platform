// 鉴权守卫: 没有 token 跳登录页
(function authGuard() {
    if (!getAccessToken()) {
        window.location.href = '/login';
    }
})();

function getAccessToken() {
    return localStorage.getItem('access_token') || localStorage.getItem('token') || '';
}

document.addEventListener('DOMContentLoaded', () => {
    const chatMain = document.getElementById('chat-main');
    const chatContainer = document.getElementById('chat-container');
    const messageInput = document.getElementById('message-input');
    const sendBtn = document.getElementById('send-btn');
    const statusIndicator = document.getElementById('status-indicator');
    const newChatBtn = document.getElementById('new-chat-btn');
    const composerForm = document.getElementById('composer-form');

    let currentStreamController = null;
    let currentSessionId = null;
    let selectedModel = null;
    let availableModels = [];

    // 用户信息 + 登出
    const logoutBtn = document.getElementById('logout-btn');
    if (logoutBtn) {
        logoutBtn.addEventListener('click', () => {
            clearAccessToken();
            window.location.href = '/login';
        });
    }

    loadUserInfo();
    initModelSelector();

    // ------------------------------------------------------------------
    // 模型选择器
    // ------------------------------------------------------------------

    async function initModelSelector() {
        const btn = document.getElementById('model-selector-btn');
        const dropdown = document.getElementById('model-dropdown');
        const modelList = document.getElementById('model-list');
        const textEl = document.getElementById('model-selector-text');

        if (!btn || !dropdown || !modelList) return;

        // 加载所有可用模型
        try {
            const res = await fetch('/api/channels/models');
            if (!res.ok) throw new Error('Failed to load models');
            availableModels = await res.json();
        } catch (err) {
            textEl.textContent = '无可用模型';
            return;
        }

        // 默认选中第一个可用模型
        const firstAvailable = availableModels.find(m => m.available);
        if (firstAvailable) {
            selectedModel = firstAvailable.model;
            textEl.textContent = selectedModel;
        } else {
            textEl.textContent = availableModels.length > 0 ? '无可用模型' : '选择模型';
        }

        renderModelList();

        // 点击按钮切换下拉菜单
        btn.addEventListener('click', (e) => {
            e.stopPropagation();
            const isHidden = dropdown.hasAttribute('hidden');
            if (isHidden) {
                renderModelList();
                dropdown.removeAttribute('hidden');
                btn.setAttribute('aria-expanded', 'true');
            } else {
                dropdown.setAttribute('hidden', '');
                btn.setAttribute('aria-expanded', 'false');
            }
        });

        // 点击外部关闭
        document.addEventListener('click', (e) => {
            const wrapper = document.getElementById('model-selector-wrapper');
            if (!wrapper.contains(e.target)) {
                dropdown.setAttribute('hidden', '');
                btn.setAttribute('aria-expanded', 'false');
            }
        });

        // Esc 键关闭
        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape' && !dropdown.hasAttribute('hidden')) {
                dropdown.setAttribute('hidden', '');
                btn.setAttribute('aria-expanded', 'false');
                btn.focus();
            }
        });
    }

    function renderModelList() {
        const modelList = document.getElementById('model-list');
        const textEl = document.getElementById('model-selector-text');
        if (!modelList) return;

        if (availableModels.length === 0) {
            modelList.innerHTML = '<div class="model-empty">暂无可用模型</div>';
            return;
        }

        modelList.innerHTML = '';
        for (const item of availableModels) {
            const button = document.createElement('button');
            button.type = 'button';
            button.className = 'model-item';
            if (!item.available) {
                button.classList.add('disabled');
            }
            if (item.model === selectedModel) {
                button.classList.add('selected');
            }

            const checkSvg = document.createElement('span');
            checkSvg.className = 'model-check';
            checkSvg.innerHTML = '<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="3"><polyline points="20 6 9 17 4 12"></polyline></svg>';

            const nameSpan = document.createElement('span');
            nameSpan.className = 'model-name';
            nameSpan.textContent = item.model;

            const channelSpan = document.createElement('span');
            channelSpan.className = 'model-channel';
            channelSpan.textContent = item.channel_name;

            button.append(checkSvg, nameSpan, channelSpan);

            if (!item.available) {
                button.title = '该账号当前不可用';
            } else {
                button.addEventListener('click', () => {
                    selectedModel = item.model;
                    if (textEl) textEl.textContent = selectedModel;
                    // 关闭 dropdown
                    const dropdown = document.getElementById('model-dropdown');
                    const btn = document.getElementById('model-selector-btn');
                    if (dropdown) dropdown.setAttribute('hidden', '');
                    if (btn) btn.setAttribute('aria-expanded', 'false');
                    // 重新渲染高亮状态
                    renderModelList();
                });
            }

            modelList.appendChild(button);
        }
    }

    async function loadUserInfo() {
        const token = getAccessToken();
        if (!token) return;
        try {
            const res = await fetch('/api/auth/me', {
                headers: { Authorization: `Bearer ${token}` },
            });
            if (!res.ok) {
                clearAccessToken();
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
        if (currentStreamController) {
            currentStreamController.abort();
            currentStreamController = null;
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
        if (!text || currentStreamController) return;

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

    async function streamAIResponse(userMessage) {
        const aiContentNode = appendMessage('ai', '');
        showStatus();

        const params = new URLSearchParams({ message: userMessage });
        if (currentSessionId) {
            params.set('session_id', currentSessionId);
        }
        if (selectedModel) {
            params.set('model', selectedModel);
        }

        const controller = new AbortController();
        currentStreamController = controller;
        sendBtn.disabled = true;

        let buffer = '';
        let doneByProtocol = false;

        try {
            const token = getAccessToken();
            if (!token) {
                window.location.href = '/login';
                return;
            }

            const response = await fetch(`/api/chat/stream?${params.toString()}`, {
                method: 'GET',
                headers: {
                    Accept: 'text/event-stream',
                    Authorization: `Bearer ${token}`,
                },
                signal: controller.signal,
            });

            if (response.status === 401) {
                clearAccessToken();
                window.location.href = '/login';
                return;
            }

            if (!response.ok || !response.body) {
                throw new Error(await responseErrorMessage(response));
            }

            const reader = response.body.getReader();
            const decoder = new TextDecoder();

            while (!doneByProtocol) {
                const { value, done } = await reader.read();
                if (done) break;
                buffer += decoder.decode(value, { stream: true });
                doneByProtocol = drainSseFrames(false);
            }

            buffer += decoder.decode();
            if (!doneByProtocol) {
                drainSseFrames(true);
            }
        } catch (err) {
            if (err.name === 'AbortError') {
                return;
            }
            console.error('chat stream failed', err);
            const message = err instanceof Error && err.message ? err.message : '连接出错，请稍后重试';
            if (!aiContentNode.textContent) {
                aiContentNode.textContent = `[${message}]`;
            } else {
                aiContentNode.textContent += `\n[${message}]`;
            }
            scrollToBottom();
        } finally {
            closeStream();
        }

        function drainSseFrames(flushRest) {
            const frames = buffer.split(/\r?\n\r?\n/);
            buffer = flushRest ? '' : frames.pop() || '';

            for (const frame of frames) {
                if (handleSseFrame(frame)) {
                    return true;
                }
            }

            if (flushRest && buffer.trim()) {
                return handleSseFrame(buffer);
            }
            return false;
        }

        function handleSseFrame(frame) {
            const data = frame
                .split(/\r?\n/)
                .filter((line) => line.startsWith('data:'))
                .map((line) => line.slice(5).trimStart())
                .join('\n')
                .trim();

            if (!data) return false;
            if (data === '[DONE]') return true;

            let payload;
            try {
                payload = JSON.parse(data);
            } catch (err) {
                aiContentNode.textContent += data;
                scrollToBottom();
                return false;
            }

            if (typeof payload.session_id === 'string') {
                currentSessionId = payload.session_id;
            } else if (typeof payload.token === 'string') {
                aiContentNode.textContent += payload.token;
                scrollToBottom();
            } else if (typeof payload.error === 'string') {
                aiContentNode.textContent += `\n[错误] ${payload.error}`;
                scrollToBottom();
            }
            return false;
        }

        function closeStream() {
            if (currentStreamController === controller) {
                currentStreamController = null;
            }
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

    function clearAccessToken() {
        localStorage.removeItem('access_token');
        localStorage.removeItem('token');
    }

    async function responseErrorMessage(response) {
        const fallback = `请求失败: ${response.status}`;
        const contentType = response.headers.get('content-type') || '';
        try {
            if (contentType.includes('application/json')) {
                const data = await response.json();
                return data?.message || data?.detail || fallback;
            }
            const text = await response.text();
            return text ? `${fallback} ${text.slice(0, 160)}` : fallback;
        } catch (err) {
            return fallback;
        }
    }
});
