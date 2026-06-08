document.addEventListener('DOMContentLoaded', () => {
    const chatContainer = document.getElementById('chat-container');
    const messageInput = document.getElementById('message-input');
    const sendBtn = document.getElementById('send-btn');
    const statusIndicator = document.getElementById('status-indicator');
    const newChatBtn = document.getElementById('new-chat-btn');

    // 当前进行中的 SSE 连接，没有则为 null
    let currentEventSource = null;

    // 当前会话 ID。null 表示"还没会话"或"想开新会话",发请求时不带 session_id
    // 让后端新建一个;非空则带上,后端会复用同一会话的历史,实现"AI 有记忆"。
    // 学习要点:这是"无状态前端 + 有状态后端"模式——真正的会话内容存在后端,
    // 前端只握着一张"门牌号"(session_id),刷新页面就丢,下个阶段接数据库后再考虑持久化。
    let currentSessionId = null;

    // 自动调整输入框高度
    messageInput.addEventListener('input', function() {
        this.style.height = 'auto';
        this.style.height = (this.scrollHeight) + 'px';
        if (this.value === '') {
            this.style.height = 'auto';
        }
    });

    // 监听回车键发送消息
    messageInput.addEventListener('keydown', (e) => {
        // 如果按下 Enter 且没有按下 Shift 键
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault(); // 阻止默认的换行行为
            sendMessage();
        }
    });

    // 监听点击发送按钮
    sendBtn.addEventListener('click', sendMessage);

    // "新聊天"按钮：清空当前对话区,回到只有欢迎语的初始状态
    // 学习要点：当前阶段(P0/P1)还没有真正的"会话切换",所以"新聊天"暂时就等于
    // "把界面重置一下"。等 P2 接入数据库后,这里再升级为真正切换 session_id。
    if (newChatBtn) {
        newChatBtn.addEventListener('click', resetChat);
        newChatBtn.addEventListener('keydown', (e) => {
            // 给键盘用户的可达性:Enter 或 Space 也能触发
            if (e.key === 'Enter' || e.key === ' ') {
                e.preventDefault();
                resetChat();
            }
        });
    }

    function resetChat() {
        // 流式中点"新聊天"先把流终止,避免旧 token 飘进新对话
        if (currentEventSource) {
            currentEventSource.close();
            currentEventSource = null;
        }
        // 清空 session_id,下一条消息会让后端新建一个全新的会话,
        // 旧会话的历史从此和当前界面无关(后端那边还在,只是这个 tab 不再访问)。
        currentSessionId = null;
        chatContainer.innerHTML = `
            <div class="message ai-message">
                <div class="avatar">AI</div>
                <div class="message-content">有什么问题，尽管问。</div>
            </div>
        `;
        sendBtn.disabled = false;
        if (statusIndicator) statusIndicator.style.display = 'none';
        messageInput.focus();
    }

    function sendMessage() {
        const text = messageInput.value.trim();
        if (!text) return;

        // 如果还有正在进行的流，先忽略本次发送，避免并发
        if (currentEventSource) return;

        // 1. 添加用户消息到界面
        appendMessage('user', text);

        // 2. 清空输入框并重置高度
        messageInput.value = '';
        messageInput.style.height = 'auto';

        // 3. 真正调用后端 SSE 接口
        streamAIResponse(text);
    }

    function appendMessage(role, text) {
        // 创建消息的最外层包裹
        const messageDiv = document.createElement('div');
        messageDiv.className = `message ${role}-message`;

        // 创建头像
        const avatarDiv = document.createElement('div');
        avatarDiv.className = 'avatar';
        avatarDiv.textContent = role === 'user' ? 'Me' : 'AI';

        // 创建消息内容区
        const contentDiv = document.createElement('div');
        contentDiv.className = 'message-content';
        contentDiv.textContent = text; // 使用 textContent 防范基础的 XSS 注入

        // 组合元素
        messageDiv.appendChild(avatarDiv);
        messageDiv.appendChild(contentDiv);
        chatContainer.appendChild(messageDiv);

        // 滚动到最新消息
        scrollToBottom();

        return contentDiv; // 返回内容 DOM 节点，方便后续流式追加效果
    }

    function scrollToBottom() {
        chatContainer.scrollTop = chatContainer.scrollHeight;
    }

    // 调用后端 SSE 接口，把流式 token 实时追加到界面
    function streamAIResponse(userMessage) {
        // 先在界面上创建一个空的 AI 消息框，等会儿往里追加 token
        const aiContentNode = appendMessage('ai', '');

        // 交互增强：流式开始时，展示"AI正在生成..."提示
        if (statusIndicator) {
            statusIndicator.style.display = 'flex';
        }

        // 学习要点:批次 4 把后端路由前缀从 /api/chat 改成了 /api,
        // 路径变成 /api/chat/stream。原本前端写的 /api/chat/chat/stream 是旧路径,
        // 不修这一行任何消息都连不上后端。
        // EventSource 只支持 GET,中文 / & / # 必须 encodeURIComponent。
        // 用 URLSearchParams 比手拼字符串更稳:它会自动把每个 value 做 percent-encode,
        // 不会因为消息里有特殊字符(& = ? 中文)把 query string 拼坏。
        const params = new URLSearchParams({ message: userMessage });
        if (currentSessionId) {
            // 带上当前 session_id,后端会取出这个会话的历史一起喂给 AI,实现"记忆"。
            params.set('session_id', currentSessionId);
        }
        const url = `/api/chat/stream?${params.toString()}`;

        const eventSource = new EventSource(url);
        currentEventSource = eventSource;

        // 流式期间禁用发送按钮，避免重复发送
        sendBtn.disabled = true;

        eventSource.onmessage = (event) => {
            // 后端约定（见 app/modules/chat/router.py 的 SSE 协议注释）：
            //   data: {"token": "..."}    — 单段 token
            //   data: {"error": "..."}    — 流内错误事件
            //   data: [DONE]              — 结束标志
            if (event.data === '[DONE]') {
                closeStream();
                return;
            }

            let payload;
            try {
                payload = JSON.parse(event.data);
            } catch (err) {
                // 学习要点：理论上后端永远只会发上面三种格式,
                // 但解析失败时也别把界面卡死,降级当成纯文本展示。
                aiContentNode.textContent += event.data;
                scrollToBottom();
                return;
            }

            if (typeof payload.session_id === 'string') {
                // 后端在流的第一帧告诉我们当前会话 ID,存下来下次发消息带回去。
                // 即使本次后续 AI 调用失败,也已经拿到了 session_id,重试时能复用同一会话。
                currentSessionId = payload.session_id;
            } else if (typeof payload.token === 'string') {
                // 每收到一段就追加到 DOM,浏览器自动重排出现打字机效果
                aiContentNode.textContent += payload.token;
                scrollToBottom();
            } else if (typeof payload.error === 'string') {
                // 流内错误：HTTP 状态码已经是 200,只能在数据里告诉前端出错了
                aiContentNode.textContent += `\n[错误] ${payload.error}`;
                scrollToBottom();
            }
        };

        eventSource.onerror = () => {
            // 学习要点：onerror 触发的原因有两类:
            //   1) 真的出错(网络断/后端挂掉) → readyState === CLOSED
            //   2) 浏览器在自动重连中           → readyState === CONNECTING
            // 第二种我们不该当错误处理,否则一闪而过的网络抖动会让消息显示"出错"。
            if (eventSource.readyState !== EventSource.CLOSED) {
                return;
            }
            // 如果 AI 消息框还是空的,说明压根没收到任何数据,补一个错误提示
            if (aiContentNode.textContent === '') {
                aiContentNode.textContent = '[连接出错,请稍后重试]';
            }
            closeStream();
        };

        function closeStream() {
            eventSource.close();
            currentEventSource = null;
            sendBtn.disabled = false;

            // 交互增强：流式结束或终止时，隐藏"AI正在生成..."提示
            if (statusIndicator) {
                statusIndicator.style.display = 'none';
            }
        }
    }
});
