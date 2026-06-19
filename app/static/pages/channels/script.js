// 鉴权守卫: 没有 token 跳登录页
(function authGuard() {
    if (!localStorage.getItem('access_token')) {
        window.location.href = '/login';
    }
})();

document.addEventListener('DOMContentLoaded', () => {
    const defaultModels = [
        'gpt-4o-mini',
        'gpt-4o',
        'gpt-4.1-mini',
        'gpt-4.1',
        'o4-mini',
        'deepseek-chat',
        'deepseek-reasoner',
        'Qwen/Qwen2.5-72B-Instruct',
    ];

    const state = {
        channels: [],
        filter: '',
        modelOptions: [...defaultModels],
        redirectMode: 'visual',
    };

    const el = {
        tbody: document.getElementById('channels-tbody'),
        notice: document.getElementById('notice'),
        importPanel: document.getElementById('import-panel'),
        form: document.getElementById('channel-form'),
        modal: document.getElementById('channel-modal'),
        openModalBtn: document.getElementById('open-channel-modal-btn'),
        closeModalBtn: document.getElementById('close-channel-modal-btn'),
        cancelModalBtn: document.getElementById('cancel-channel-modal-btn'),
        submitBtn: document.getElementById('submit-channel-btn'),
        refreshBtn: document.getElementById('refresh-btn'),
        toggleImportBtn: document.getElementById('toggle-import-btn'),
        importSubmitBtn: document.getElementById('import-submit-btn'),
        searchInput: document.getElementById('search-input'),
        bulkInput: document.getElementById('bulk-input'),
        type: document.getElementById('channel-type'),
        name: document.getElementById('channel-name'),
        key: document.getElementById('channel-key'),
        batch: document.getElementById('channel-batch'),
        organization: document.getElementById('channel-organization'),
        baseUrl: document.getElementById('channel-base-url'),
        model: document.getElementById('channel-model'),
        customModel: document.getElementById('channel-custom-model'),
        group: document.getElementById('channel-group'),
        fetchModelsBtn: document.getElementById('fetch-models-btn'),
        redirectVisual: document.getElementById('redirect-visual'),
        redirectManual: document.getElementById('redirect-manual'),
        addRedirectRowBtn: document.getElementById('add-redirect-row-btn'),
    };

    bindEvents();
    renderModelOptions();
    addRedirectRow();
    loadModelOptions({ quiet: true });
    loadChannels();

    function bindEvents() {
        el.openModalBtn.addEventListener('click', () => openModal());
        el.closeModalBtn.addEventListener('click', closeModal);
        el.cancelModalBtn.addEventListener('click', closeModal);
        el.modal.addEventListener('click', (event) => {
            if (event.target === el.modal) closeModal();
        });
        document.addEventListener('keydown', (event) => {
            if (event.key === 'Escape' && !el.modal.hidden) closeModal();
        });

        el.refreshBtn.addEventListener('click', loadChannels);
        el.toggleImportBtn.addEventListener('click', () => {
            el.importPanel.hidden = !el.importPanel.hidden;
        });
        el.importSubmitBtn.addEventListener('click', importChannels);
        el.fetchModelsBtn.addEventListener('click', () => loadModelOptions({ quiet: false }));
        el.addRedirectRowBtn.addEventListener('click', () => addRedirectRow());
        el.batch.addEventListener('change', updateKeyInputMode);
        el.searchInput.addEventListener('input', () => {
            state.filter = el.searchInput.value.trim().toLowerCase();
            renderChannels();
        });
        el.form.addEventListener('submit', createChannel);

        document.querySelectorAll('.segment').forEach((button) => {
            button.addEventListener('click', () => setRedirectMode(button.dataset.mode));
        });
    }

    function token() {
        return localStorage.getItem('access_token') || localStorage.getItem('token') || '';
    }

    async function api(path, options = {}) {
        const headers = {
            'Content-Type': 'application/json',
            ...(options.headers || {}),
        };
        const accessToken = token();
        if (accessToken) {
            headers.Authorization = `Bearer ${accessToken}`;
        }

        const response = await fetch(path, { ...options, headers });
        const data = await response.json().catch(() => null);
        if (!response.ok) {
            const message = data?.message || data?.detail || `请求失败: ${response.status}`;
            throw new Error(message);
        }
        return data;
    }

    async function loadChannels() {
        try {
            showNotice('');
            const channels = await api('/api/admin/channels');
            state.channels = Array.isArray(channels) ? channels : [];
            renderChannels();
        } catch (err) {
            state.channels = [];
            renderChannels();
            showNotice(`${err.message}。请确认已使用管理员账号登录。`, true);
        }
    }

    async function loadModelOptions({ quiet }) {
        try {
            const result = await api('/api/admin/channels/model-options');
            if (Array.isArray(result?.models) && result.models.length) {
                state.modelOptions = result.models;
                renderModelOptions();
            }
            if (!quiet) showNotice('模型列表已刷新。');
        } catch (err) {
            renderModelOptions();
            if (!quiet) showNotice(err.message, true);
        }
    }

    async function createChannel(event) {
        event.preventDefault();
        const payloads = collectPayloads();
        if (!payloads) return;

        el.submitBtn.disabled = true;
        el.submitBtn.textContent = '提交中';
        let createdCount = 0;

        try {
            for (const payload of payloads) {
                await api('/api/admin/channels', {
                    method: 'POST',
                    body: JSON.stringify(payload),
                });
                createdCount += 1;
            }
            closeModal();
            showNotice(`已创建 ${createdCount} 个渠道。`);
            await loadChannels();
        } catch (err) {
            if (createdCount > 0) {
                await loadChannels();
                showNotice(`已创建 ${createdCount} 个渠道，随后失败：${err.message}`, true);
            } else {
                showNotice(err.message, true);
            }
        } finally {
            el.submitBtn.disabled = false;
            el.submitBtn.textContent = '确认';
        }
    }

    async function importChannels() {
        const rawText = el.bulkInput.value.trim();
        if (!rawText) {
            showNotice('请先粘贴要导入的账号。', true);
            return;
        }

        try {
            const result = await api('/api/admin/channels/bulk-import', {
                method: 'POST',
                body: JSON.stringify({ raw_text: rawText }),
            });
            const failed = result.errors?.length ? `，失败 ${result.errors.length} 行` : '';
            showNotice(`已导入 ${result.imported} 个账号${failed}。`);
            el.bulkInput.value = '';
            await loadChannels();
        } catch (err) {
            showNotice(err.message, true);
        }
    }

    function collectPayloads() {
        if (!el.form.reportValidity()) {
            showNotice('请补齐必填项。', true);
            return null;
        }

        const name = el.name.value.trim();
        const keys = collectKeys();
        const selectedModel = el.model.value.trim();
        const customModel = el.customModel.value.trim();

        if (!keys.length) {
            showNotice('请填写密钥。', true);
            el.key.focus();
            return null;
        }
        if (!selectedModel) {
            showNotice('请填写模型名称。', true);
            el.model.focus();
            return null;
        }

        let modelRedirect;
        try {
            modelRedirect = readModelRedirect();
        } catch (err) {
            showNotice(err.message, true);
            return null;
        }

        const basePayload = {
            provider_type: el.type.value,
            base_url: emptyToNull(el.baseUrl.value),
            organization: emptyToNull(el.organization.value),
            models: [selectedModel],
            custom_model_name: emptyToNull(customModel),
            group: el.group.value || 'default',
            model_redirect: modelRedirect,
            weight: 1,
            enabled: true,
        };

        return keys.map((apiKey, index) => ({
            ...basePayload,
            name: el.batch.checked ? `${name}-${String(index + 1).padStart(2, '0')}` : name,
            api_key: apiKey,
        }));
    }

    function collectKeys() {
        const raw = el.key.value.trim();
        if (!raw) return [];
        if (!el.batch.checked) return [raw];
        return raw
            .split(/[\n,]+/)
            .map((item) => item.trim())
            .filter(Boolean);
    }

    function emptyToNull(value) {
        const normalized = String(value || '').trim();
        return normalized || null;
    }

    function openModal() {
        resetForm();
        el.modal.hidden = false;
        requestAnimationFrame(() => el.name.focus());
    }

    function closeModal() {
        el.modal.hidden = true;
        resetForm();
    }

    function resetForm() {
        el.form.reset();
        el.type.value = 'openai_compat';
        el.group.value = 'default';
        state.redirectMode = 'visual';
        el.redirectVisual.innerHTML = '';
        el.redirectManual.value = '';
        addRedirectRow();
        updateRedirectModeView();
        updateKeyInputMode();
        renderModelOptions();
    }

    function updateKeyInputMode() {
        if (el.batch.checked) {
            el.key.rows = 4;
            el.key.placeholder = '每行一个 sk-...，也支持英文逗号分隔';
            return;
        }
        el.key.rows = 1;
        el.key.placeholder = 'sk-...';
    }

    function renderModelOptions() {
        const datalist = document.getElementById('model-suggestions');
        datalist.innerHTML = '';
        for (const model of state.modelOptions) {
            const opt = document.createElement('option');
            opt.value = model;
            datalist.appendChild(opt);
        }
    }

    function appendOption(select, value, label) {
        const option = document.createElement('option');
        option.value = value;
        option.textContent = label;
        select.appendChild(option);
    }

    function addRedirectRow(source = '', target = '') {
        const row = document.createElement('div');
        row.className = 'redirect-row';

        const sourceInput = document.createElement('input');
        sourceInput.type = 'text';
        sourceInput.placeholder = '原模型';
        sourceInput.value = source;
        sourceInput.className = 'redirect-source';

        const arrow = document.createElement('span');
        arrow.className = 'redirect-arrow';
        arrow.textContent = '→';

        const targetInput = document.createElement('input');
        targetInput.type = 'text';
        targetInput.placeholder = '目标模型';
        targetInput.value = target;
        targetInput.className = 'redirect-target';

        const removeBtn = document.createElement('button');
        removeBtn.type = 'button';
        removeBtn.className = 'remove-redirect-btn';
        removeBtn.textContent = '×';
        removeBtn.setAttribute('aria-label', '删除重定向');
        removeBtn.addEventListener('click', () => {
            row.remove();
            if (!el.redirectVisual.children.length) addRedirectRow();
        });

        row.append(sourceInput, arrow, targetInput, removeBtn);
        el.redirectVisual.appendChild(row);
    }

    function setRedirectMode(mode) {
        if (mode === state.redirectMode) return;

        if (mode === 'manual') {
            try {
                const redirect = readVisualRedirect(false);
                el.redirectManual.value = Object.keys(redirect).length
                    ? JSON.stringify(redirect, null, 2)
                    : '';
            } catch (err) {
                showNotice(err.message, true);
                return;
            }
        }

        if (mode === 'visual') {
            try {
                const redirect = readManualRedirect();
                renderRedirectRows(redirect);
            } catch (err) {
                showNotice(err.message, true);
                return;
            }
        }

        state.redirectMode = mode;
        updateRedirectModeView();
    }

    function updateRedirectModeView() {
        document.querySelectorAll('.segment').forEach((button) => {
            button.classList.toggle('active', button.dataset.mode === state.redirectMode);
        });
        const isManual = state.redirectMode === 'manual';
        el.redirectVisual.hidden = isManual;
        el.addRedirectRowBtn.hidden = isManual;
        el.redirectManual.hidden = !isManual;
    }

    function renderRedirectRows(redirect) {
        el.redirectVisual.innerHTML = '';
        const entries = Object.entries(redirect);
        if (!entries.length) {
            addRedirectRow();
            return;
        }
        for (const [source, target] of entries) {
            addRedirectRow(source, target);
        }
    }

    function readModelRedirect() {
        return state.redirectMode === 'manual'
            ? readManualRedirect()
            : readVisualRedirect(true);
    }

    function readManualRedirect() {
        const text = el.redirectManual.value.trim();
        if (!text) return {};

        let parsed;
        try {
            parsed = JSON.parse(text);
        } catch (err) {
            throw new Error('模型重定向的 JSON 格式不正确。');
        }
        if (!parsed || Array.isArray(parsed) || typeof parsed !== 'object') {
            throw new Error('模型重定向必须是键值对象。');
        }
        return normalizeRedirect(parsed);
    }

    function readVisualRedirect(strict) {
        const result = {};
        const rows = el.redirectVisual.querySelectorAll('.redirect-row');
        for (const row of rows) {
            const source = row.querySelector('.redirect-source').value.trim();
            const target = row.querySelector('.redirect-target').value.trim();
            if (!source && !target) continue;
            if (strict && (!source || !target)) {
                throw new Error('模型重定向每一行都需要同时填写原模型和目标模型。');
            }
            if (source && target) {
                result[source] = target;
            }
        }
        return result;
    }

    function normalizeRedirect(value) {
        const result = {};
        for (const [source, target] of Object.entries(value)) {
            const key = String(source || '').trim();
            const mapped = String(target || '').trim();
            if (key && mapped) result[key] = mapped;
        }
        return result;
    }

    function filteredChannels() {
        if (!state.filter) return state.channels;
        return state.channels.filter((channel) => {
            const haystack = [
                channel.id,
                channel.name,
                channel.base_url,
                channel.api_key_masked,
                channel.group,
                ...(channel.models || []),
                ...Object.keys(channel.model_redirect || {}),
                ...Object.values(channel.model_redirect || {}),
            ].join(' ').toLowerCase();
            return haystack.includes(state.filter);
        });
    }

    function renderChannels() {
        const rows = filteredChannels();
        document.getElementById('stat-total').textContent = String(state.channels.length);
        document.getElementById('stat-enabled').textContent = String(
            state.channels.filter((item) => item.enabled).length
        );
        document.getElementById('stat-failures').textContent = String(
            state.channels.reduce((sum, item) => sum + (item.failure_count || 0), 0)
        );
        document.getElementById('table-summary').textContent =
            `显示 ${rows.length} / ${state.channels.length} 个账号`;

        el.tbody.innerHTML = '';
        if (!rows.length) {
            const tr = document.createElement('tr');
            const td = document.createElement('td');
            td.className = 'empty-row';
            td.colSpan = 8;
            td.textContent = state.channels.length ? '没有匹配的账号。' : '还没有账号，先添加或批量导入。';
            tr.appendChild(td);
            el.tbody.appendChild(tr);
            return;
        }

        for (const channel of rows) {
            el.tbody.appendChild(channelRow(channel));
        }
    }

    function channelRow(channel) {
        const tr = document.createElement('tr');
        tr.append(
            cell(channel.id, 'mono'),
            cell(channel.name),
            cell(channel.api_key_masked, 'mono'),
            cell(channel.base_url, 'mono'),
            modelCell(channel.models || []),
            groupCell(channel.group || 'default'),
            statusCell(channel.enabled),
            cell(`${channel.success_count || 0}/${channel.failure_count || 0}`, 'mono')
        );
        return tr;
    }

    function cell(text, className = '') {
        const td = document.createElement('td');
        td.textContent = text || '-';
        if (className) td.className = className;
        return td;
    }

    function modelCell(models) {
        const td = document.createElement('td');
        const wrap = document.createElement('div');
        wrap.className = 'models';
        const shown = models.length ? models.slice(0, 3) : ['默认模型'];
        for (const model of shown) {
            const chip = document.createElement('span');
            chip.className = 'model-chip';
            chip.textContent = model;
            wrap.appendChild(chip);
        }
        if (models.length > 3) {
            const chip = document.createElement('span');
            chip.className = 'model-chip';
            chip.textContent = `+${models.length - 3}`;
            wrap.appendChild(chip);
        }
        td.appendChild(wrap);
        return td;
    }

    function groupCell(group) {
        const td = document.createElement('td');
        const pill = document.createElement('span');
        pill.className = 'group-pill';
        pill.textContent = group;
        td.appendChild(pill);
        return td;
    }

    function statusCell(enabled) {
        const td = document.createElement('td');
        const pill = document.createElement('span');
        pill.className = `status-pill ${enabled ? 'enabled' : 'disabled'}`;
        pill.textContent = enabled ? '启用' : '禁用';
        td.appendChild(pill);
        return td;
    }

    function showNotice(message, isError = false) {
        if (!message) {
            el.notice.hidden = true;
            el.notice.textContent = '';
            el.notice.classList.remove('error');
            return;
        }
        el.notice.hidden = false;
        el.notice.textContent = message;
        el.notice.classList.toggle('error', isError);
    }
});
