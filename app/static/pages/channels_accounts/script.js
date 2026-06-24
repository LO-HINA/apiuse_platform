// 鉴权守卫: 没有 token 跳登录页
(function authGuard() {
    if (!(localStorage.getItem('access_token') || localStorage.getItem('token'))) {
        window.location.href = '/login';
    }
})();

document.addEventListener('DOMContentLoaded', function () {
    // Render shared sidebar
    renderSidebar({
        activePath: '/channels/accounts',
        showHistory: false,
        showHint: true,
        hintTitle: '号池管理',
        hintText: '启动时读取本地渠道配置，页面只展示脱敏后的 key。',
        showUserFooter: false,
    });

    var defaultModels = [
        'gpt-4o-mini',
        'gpt-4o',
        'gpt-4.1-mini',
        'gpt-4.1',
        'o4-mini',
        'deepseek-chat',
        'deepseek-reasoner',
        'Qwen/Qwen2.5-72B-Instruct',
    ];

    var state = {
        channels: [],
        filter: '',
        modelOptions: defaultModels.slice(),
        redirectMode: 'visual',
        editingId: null,
        editingChannel: null,
    };

    var el = {
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
        modalTitle: document.getElementById('channel-modal-title'),
        keyCreateField: document.getElementById('key-create-field'),
        keyEditField: document.getElementById('key-edit-field'),
        keyMask: document.getElementById('channel-key-mask'),
        newKey: document.getElementById('channel-new-key'),
        batchField: document.getElementById('channel-batch-field'),
    };

    bindEvents();
    renderModelOptions();
    addRedirectRow();
    loadModelOptions({ quiet: true });
    loadChannels();

    function bindEvents() {
        el.openModalBtn.addEventListener('click', function () { openModal(); });
        el.closeModalBtn.addEventListener('click', closeModal);
        el.cancelModalBtn.addEventListener('click', closeModal);
        el.modal.addEventListener('click', function (event) {
            if (event.target === el.modal) closeModal();
        });
        document.addEventListener('keydown', function (event) {
            if (event.key === 'Escape' && !el.modal.hidden) closeModal();
        });

        el.refreshBtn.addEventListener('click', loadChannels);
        el.toggleImportBtn.addEventListener('click', function () {
            el.importPanel.hidden = !el.importPanel.hidden;
        });
        el.importSubmitBtn.addEventListener('click', importChannels);
        el.fetchModelsBtn.addEventListener('click', function () { loadModelOptions({ quiet: false }); });
        el.addRedirectRowBtn.addEventListener('click', function () { addRedirectRow(); });
        el.batch.addEventListener('change', updateKeyInputMode);
        el.searchInput.addEventListener('input', function () {
            state.filter = el.searchInput.value.trim().toLowerCase();
            renderChannels();
        });
        el.form.addEventListener('submit', submitForm);

        document.querySelectorAll('.segment').forEach(function (button) {
            button.addEventListener('click', function () { setRedirectMode(button.dataset.mode); });
        });
    }

    function token() {
        return localStorage.getItem('access_token') || localStorage.getItem('token') || '';
    }

    async function api(path, options) {
        options = options || {};
        var headers = {
            'Content-Type': 'application/json',
            ...(options.headers || {}),
        };
        var accessToken = token();
        if (accessToken) {
            headers.Authorization = 'Bearer ' + accessToken;
        }

        var response = await fetch(path, { ...options, headers: headers });
        var data = await response.json().catch(function () { return null; });
        if (!response.ok) {
            var message = (data && data.message) || (data && data.detail) || ('请求失败: ' + response.status);
            throw new Error(message);
        }
        return data;
    }

    async function loadChannels() {
        try {
            showNotice('');
            var channels = await api('/api/admin/channels');
            state.channels = Array.isArray(channels) ? channels : [];
            renderChannels();
        } catch (err) {
            state.channels = [];
            renderChannels();
            showNotice(err.message + '。请确认已使用管理员账号登录。', true);
        }
    }

    async function loadModelOptions(opts) {
        try {
            var result = await api('/api/admin/channels/model-options');
            if (Array.isArray(result && result.models) && result.models.length) {
                state.modelOptions = result.models;
                renderModelOptions();
            }
            if (!opts.quiet) showNotice('模型列表已刷新。');
        } catch (err) {
            renderModelOptions();
            if (!opts.quiet) showNotice(err.message, true);
        }
    }

    async function submitForm(event) {
        event.preventDefault();
        if (state.editingId) {
            await updateChannel();
        } else {
            await createChannels();
        }
    }

    async function createChannels() {
        var payloads = collectPayloads();
        if (!payloads) return;

        el.submitBtn.disabled = true;
        el.submitBtn.textContent = '提交中';
        var createdCount = 0;

        try {
            for (var i = 0; i < payloads.length; i++) {
                await api('/api/admin/channels', {
                    method: 'POST',
                    body: JSON.stringify(payloads[i]),
                });
                createdCount += 1;
            }
            closeModal();
            showNotice('已创建 ' + createdCount + ' 个渠道。');
            await loadChannels();
        } catch (err) {
            if (createdCount > 0) {
                await loadChannels();
                showNotice('已创建 ' + createdCount + ' 个渠道，随后失败：' + err.message, true);
            } else {
                showNotice(err.message, true);
            }
        } finally {
            el.submitBtn.disabled = false;
            el.submitBtn.textContent = '确认';
        }
    }

    async function updateChannel() {
        var channel = state.editingChannel;
        if (!channel || !el.form.reportValidity()) {
            showNotice('请补齐必填项。', true);
            return;
        }
        var name = el.name.value.trim();
        var selectedModel = el.model.value.trim();
        if (!name) { showNotice('请填写名称。', true); el.name.focus(); return; }
        if (!selectedModel) { showNotice('请填写模型名称。', true); el.model.focus(); return; }

        var modelRedirect;
        try {
            modelRedirect = readModelRedirect();
        } catch (err) {
            showNotice(err.message, true);
            return;
        }

        var payload = {
            name: name,
            provider_type: el.group.value,
            base_url: emptyToNull(el.baseUrl.value),
            organization: emptyToNull(el.organization.value),
            models: [selectedModel],
            custom_model_name: emptyToNull(el.customModel.value),
            group: el.group.value || 'default',
            model_redirect: modelRedirect,
            weight: channel.weight,
            enabled: channel.enabled,
        };
        var newKey = el.newKey.value.trim();
        if (newKey) payload.api_key = newKey;

        var targetId = state.editingId;
        el.submitBtn.disabled = true;
        el.submitBtn.textContent = '提交中';
        try {
            await api('/api/admin/channels/' + targetId, {
                method: 'PUT',
                body: JSON.stringify(payload),
            });
            closeModal();
            showNotice('已更新渠道 ' + targetId + '。');
            await loadChannels();
        } catch (err) {
            showNotice(err.message, true);
        } finally {
            el.submitBtn.disabled = false;
            el.submitBtn.textContent = '确认';
        }
    }

    async function deleteChannel(channel) {
        if (!confirm('确认删除渠道 ' + channel.id + ' (' + channel.name + ') ？此操作不可恢复。')) return;
        try {
            showNotice('');
            await api('/api/admin/channels/' + channel.id, { method: 'DELETE' });
            showNotice('已删除渠道 ' + channel.id + '。');
            await loadChannels();
        } catch (err) {
            showNotice(err.message, true);
        }
    }

    async function exportChannel(channelId) {
        try {
            showNotice('');
            var resp = await fetch('/api/admin/channels/' + channelId + '/export', {
                headers: { Authorization: 'Bearer ' + token() },
            });
            if (!resp.ok) {
                var data = await resp.json().catch(function () { return null; });
                var message = (data && data.message) || (data && data.detail) || ('导出失败: ' + resp.status);
                showNotice(message, true);
                return;
            }
            var blob = await resp.blob();
            var url = URL.createObjectURL(blob);
            var a = document.createElement('a');
            a.href = url;
            a.download = channelId + '.json';
            document.body.appendChild(a);
            a.click();
            document.body.removeChild(a);
            URL.revokeObjectURL(url);
            showNotice('已导出 ' + channelId + '.json。');
        } catch (err) {
            showNotice(err.message, true);
        }
    }

    async function importChannels() {
        var rawText = el.bulkInput.value.trim();
        if (!rawText) {
            showNotice('请先粘贴要导入的账号。', true);
            return;
        }

        try {
            var result = await api('/api/admin/channels/bulk-import', {
                method: 'POST',
                body: JSON.stringify({ raw_text: rawText }),
            });
            var failed = (result.errors && result.errors.length) ? ('，失败 ' + result.errors.length + ' 行') : '';
            showNotice('已导入 ' + result.imported + ' 个账号' + failed + '。');
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

        var name = el.name.value.trim();
        var keys = collectKeys();
        var selectedModel = el.model.value.trim();
        var customModel = el.customModel.value.trim();

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

        var modelRedirect;
        try {
            modelRedirect = readModelRedirect();
        } catch (err) {
            showNotice(err.message, true);
            return null;
        }

        var basePayload = {
            provider_type: el.group.value,
            base_url: emptyToNull(el.baseUrl.value),
            organization: emptyToNull(el.organization.value),
            models: [selectedModel],
            custom_model_name: emptyToNull(customModel),
            group: el.group.value || 'default',
            model_redirect: modelRedirect,
            weight: 1,
            enabled: true,
        };

        return keys.map(function (apiKey, index) {
            return {
                ...basePayload,
                name: el.batch.checked ? name + '-' + String(index + 1).padStart(2, '0') : name,
                api_key: apiKey,
            };
        });
    }

    function collectKeys() {
        var raw = el.key.value.trim();
        if (!raw) return [];
        if (!el.batch.checked) return [raw];
        return raw
            .split(/[\n,]+/)
            .map(function (item) { return item.trim(); })
            .filter(Boolean);
    }

    function emptyToNull(value) {
        var normalized = String(value || '').trim();
        return normalized || null;
    }

    function openModal() {
        state.editingId = null;
        state.editingChannel = null;
        resetForm();
        setCreateMode();
        el.modal.hidden = false;
        requestAnimationFrame(function () { el.name.focus(); });
    }

    function openEditModal(channel) {
        state.editingId = channel.id;
        state.editingChannel = channel;
        resetForm();
        setEditMode(channel);
        el.modal.hidden = false;
        requestAnimationFrame(function () { el.name.focus(); });
    }

    function closeModal() {
        el.modal.hidden = true;
        state.editingId = null;
        state.editingChannel = null;
        resetForm();
    }

    function resetForm() {
        el.form.reset();
        el.group.value = 'openai_compat';
        state.redirectMode = 'visual';
        el.redirectVisual.innerHTML = '';
        el.redirectManual.value = '';
        addRedirectRow();
        updateRedirectModeView();
        updateKeyInputMode();
        renderModelOptions();
        if (el.newKey) el.newKey.value = '';
    }

    function setCreateMode() {
        el.modalTitle.textContent = '创建新的渠道';
        el.keyCreateField.hidden = false;
        el.keyEditField.hidden = true;
        el.batchField.hidden = false;
        el.key.required = true;
    }

    function setEditMode(channel) {
        el.modalTitle.textContent = '编辑渠道：' + channel.name;
        el.keyCreateField.hidden = true;
        el.keyEditField.hidden = false;
        el.batchField.hidden = true;
        el.key.required = false;
        el.keyMask.value = channel.api_key_masked || '';
        el.name.value = channel.name || '';
        el.group.value = channel.provider_type || 'openai_compat';
        el.organization.value = channel.organization || '';
        el.baseUrl.value = channel.base_url || '';
        var models = channel.models || [];
        el.model.value = models.length ? models[0] : '';
        el.customModel.value = '';
        renderRedirectRows(channel.model_redirect || {});
        updateRedirectModeView();
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
        var datalist = document.getElementById('model-suggestions');
        datalist.innerHTML = '';
        for (var i = 0; i < state.modelOptions.length; i++) {
            var opt = document.createElement('option');
            opt.value = state.modelOptions[i];
            datalist.appendChild(opt);
        }
    }

    function addRedirectRow(source, target) {
        source = source || '';
        target = target || '';
        var row = document.createElement('div');
        row.className = 'redirect-row';

        var sourceInput = document.createElement('input');
        sourceInput.type = 'text';
        sourceInput.placeholder = '原模型';
        sourceInput.value = source;
        sourceInput.className = 'redirect-source';

        var arrow = document.createElement('span');
        arrow.className = 'redirect-arrow';
        arrow.textContent = '\u2192';

        var targetInput = document.createElement('input');
        targetInput.type = 'text';
        targetInput.placeholder = '目标模型';
        targetInput.value = target;
        targetInput.className = 'redirect-target';

        var removeBtn = document.createElement('button');
        removeBtn.type = 'button';
        removeBtn.className = 'remove-redirect-btn';
        removeBtn.textContent = '\u00d7';
        removeBtn.setAttribute('aria-label', '删除重定向');
        removeBtn.addEventListener('click', function () {
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
                var redirect = readVisualRedirect(false);
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
                var redirect = readManualRedirect();
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
        document.querySelectorAll('.segment').forEach(function (button) {
            button.classList.toggle('active', button.dataset.mode === state.redirectMode);
        });
        var isManual = state.redirectMode === 'manual';
        el.redirectVisual.hidden = isManual;
        el.addRedirectRowBtn.hidden = isManual;
        el.redirectManual.hidden = !isManual;
    }

    function renderRedirectRows(redirect) {
        el.redirectVisual.innerHTML = '';
        var entries = Object.entries(redirect);
        if (!entries.length) {
            addRedirectRow();
            return;
        }
        for (var i = 0; i < entries.length; i++) {
            addRedirectRow(entries[i][0], entries[i][1]);
        }
    }

    function readModelRedirect() {
        return state.redirectMode === 'manual'
            ? readManualRedirect()
            : readVisualRedirect(true);
    }

    function readManualRedirect() {
        var text = el.redirectManual.value.trim();
        if (!text) return {};

        var parsed;
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
        var result = {};
        var rows = el.redirectVisual.querySelectorAll('.redirect-row');
        for (var i = 0; i < rows.length; i++) {
            var row = rows[i];
            var source = row.querySelector('.redirect-source').value.trim();
            var target = row.querySelector('.redirect-target').value.trim();
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
        var result = {};
        for (var key in value) {
            if (value.hasOwnProperty(key)) {
                var k = String(key || '').trim();
                var v = String(value[key] || '').trim();
                if (k && v) result[k] = v;
            }
        }
        return result;
    }

    function filteredChannels() {
        if (!state.filter) return state.channels;
        return state.channels.filter(function (channel) {
            var haystack = [
                channel.id,
                channel.name,
                channel.base_url,
                channel.api_key_masked,
                channel.group,
                ...(channel.models || []),
                ...Object.keys(channel.model_redirect || {}),
                ...Object.values(channel.model_redirect || {}),
            ].join(' ').toLowerCase();
            return haystack.indexOf(state.filter) !== -1;
        });
    }

    function renderChannels() {
        var rows = filteredChannels();
        document.getElementById('stat-total').textContent = String(state.channels.length);
        document.getElementById('stat-enabled').textContent = String(
            state.channels.filter(function (item) { return item.enabled; }).length
        );
        document.getElementById('stat-failures').textContent = String(
            state.channels.reduce(function (sum, item) { return sum + (item.failure_count || 0); }, 0)
        );
        document.getElementById('table-summary').textContent =
            '显示 ' + rows.length + ' / ' + state.channels.length + ' 个账号';

        el.tbody.innerHTML = '';
        if (!rows.length) {
            var tr = document.createElement('tr');
            var td = document.createElement('td');
            td.className = 'empty-row';
            td.colSpan = 8;
            td.textContent = state.channels.length ? '没有匹配的账号。' : '还没有账号，先添加或批量导入。';
            tr.appendChild(td);
            el.tbody.appendChild(tr);
            return;
        }

        for (var i = 0; i < rows.length; i++) {
            el.tbody.appendChild(channelRow(rows[i]));
        }
    }

    function channelRow(channel) {
        var tr = document.createElement('tr');
        tr.append(
            cell(channel.id, 'mono'),
            cell(channel.name),
            keyCell(channel),
            cell(channel.base_url, 'mono'),
            modelCell(channel.models || []),
            groupCell(channel.group || 'default'),
            statusCell(channel.enabled),
            actionCell(channel)
        );
        return tr;
    }

    function actionCell(channel) {
        var td = document.createElement('td');
        td.className = 'action-cell';
        var wrap = document.createElement('div');
        wrap.className = 'action-wrap';

        var editBtn = document.createElement('button');
        editBtn.type = 'button';
        editBtn.className = 'ghost-btn small-action-btn';
        editBtn.textContent = '编辑';
        editBtn.addEventListener('click', function () { openEditModal(channel); });

        var exportBtn = document.createElement('button');
        exportBtn.type = 'button';
        exportBtn.className = 'ghost-btn small-action-btn';
        exportBtn.textContent = '导出';
        exportBtn.addEventListener('click', function () { exportChannel(channel.id); });

        var deleteBtn = document.createElement('button');
        deleteBtn.type = 'button';
        deleteBtn.className = 'ghost-btn small-action-btn danger-btn';
        deleteBtn.textContent = '删除';
        deleteBtn.addEventListener('click', function () { deleteChannel(channel); });

        wrap.append(editBtn, exportBtn, deleteBtn);
        td.appendChild(wrap);
        return td;
    }

    function cell(text, className) {
        className = className || '';
        var td = document.createElement('td');
        td.textContent = text || '-';
        if (className) td.className = className;
        return td;
    }

    function keyCell(channel) {
        var td = document.createElement('td');
        td.className = 'key-cell';
        var span = document.createElement('span');
        span.className = 'mono';
        span.textContent = channel.api_key_masked;
        td.appendChild(span);
        return td;
    }

    function modelCell(models) {
        var td = document.createElement('td');
        var wrap = document.createElement('div');
        wrap.className = 'models';
        var shown = models.length ? models.slice(0, 3) : ['默认模型'];
        for (var i = 0; i < shown.length; i++) {
            var chip = document.createElement('span');
            chip.className = 'model-chip';
            chip.textContent = shown[i];
            wrap.appendChild(chip);
        }
        if (models.length > 3) {
            var chip = document.createElement('span');
            chip.className = 'model-chip';
            chip.textContent = '+' + (models.length - 3);
            wrap.appendChild(chip);
        }
        td.appendChild(wrap);
        return td;
    }

    function groupCell(group) {
        var td = document.createElement('td');
        var pill = document.createElement('span');
        pill.className = 'group-pill';
        pill.textContent = group;
        td.appendChild(pill);
        return td;
    }

    function statusCell(enabled) {
        var td = document.createElement('td');
        var pill = document.createElement('span');
        pill.className = 'status-pill ' + (enabled ? 'enabled' : 'disabled');
        pill.textContent = enabled ? '启用' : '禁用';
        td.appendChild(pill);
        return td;
    }

    function showNotice(message, isError) {
        isError = isError || false;
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
