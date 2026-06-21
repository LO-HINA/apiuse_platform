(function () {
    if (!(localStorage.getItem('access_token') || localStorage.getItem('token'))) {
        window.location.href = '/login';
    }
})();

document.addEventListener('DOMContentLoaded', function () {
    renderSidebar({
        activePath: '/channels/keys',
        showHistory: false,
        showHint: true,
        hintTitle: '密钥管理',
        hintText: '管理和创建 API 访问密钥。密钥用于通过 API 调用模型服务。',
        showUserFooter: false,
    });

    var keys = [];
    var modelOptions = [];

    var el = {
        tbody: document.getElementById('keys-tbody'),
        notice: document.getElementById('notice'),
        modal: document.getElementById('key-modal'),
        createBtn: document.getElementById('create-key-btn'),
        closeBtn: document.getElementById('close-key-modal-btn'),
        cancelBtn: document.getElementById('cancel-key-modal-btn'),
        closeAfterCreateBtn: document.getElementById('close-after-create-btn'),
        submitBtn: document.getElementById('submit-key-btn'),
        form: document.getElementById('key-form'),
        formFields: document.getElementById('key-form-fields'),
        keyName: document.getElementById('key-name'),
        keyQuota: document.getElementById('key-quota'),
        keyModels: document.getElementById('key-models'),
        keyValidityDays: document.getElementById('key-validity-days'),
        keyStatus: document.getElementById('key-status'),
        keyPreview: document.getElementById('key-preview'),
        keyValue: document.getElementById('key-value'),
        copyNewKeyBtn: document.getElementById('copy-new-key-btn'),
        modelSuggestions: document.getElementById('key-model-suggestions'),
        editModal: document.getElementById('edit-modal'),
        editCloseBtn: document.getElementById('edit-close-btn'),
        editCancelBtn: document.getElementById('edit-cancel-btn'),
        editForm: document.getElementById('edit-form'),
        editKeyId: document.getElementById('edit-key-id'),
        editKeyName: document.getElementById('edit-key-name'),
        editKeyQuota: document.getElementById('edit-key-quota'),
        editKeyModels: document.getElementById('edit-key-models'),
        editKeyValidityDays: document.getElementById('edit-key-validity-days'),
        editKeyStatus: document.getElementById('edit-key-status'),
        editSubmitBtn: document.getElementById('edit-submit-btn'),
        editModelSuggestions: document.getElementById('edit-model-suggestions'),
    };

    bindEvents();
    loadModelOptions();
    loadKeys();

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
        if (response.status === 204) return null;
        var data = await response.json().catch(function () { return null; });
        if (!response.ok) {
            var message = (data && data.message) || (data && data.detail) || ('请求失败: ' + response.status);
            throw new Error(message);
        }
        return data;
    }

    async function loadKeys() {
        try {
            showNotice('');
            var result = await api('/api/keys');
            keys = Array.isArray(result) ? result : [];
            renderKeys();
        } catch (err) {
            keys = [];
            renderKeys();
            showNotice(err.message + '。请确认已登录。', true);
        }
    }

    async function loadModelOptions() {
        try {
            var result = await api('/api/channels/models');
            if (Array.isArray(result) && result.length) {
                var seen = {};
                modelOptions = [];
                for (var i = 0; i < result.length; i++) {
                    var m = result[i].model;
                    if (m && !seen[m]) {
                        seen[m] = true;
                        modelOptions.push(m);
                    }
                }
            }
        } catch (e) { /* ignore */ }
        renderModelSuggestions();
    }

    function renderModelSuggestions() {
        fillDatalist(el.modelSuggestions);
        fillDatalist(el.editModelSuggestions);
    }

    function fillDatalist(datalist) {
        if (!datalist) return;
        datalist.innerHTML = '';
        var list = modelOptions.length ? modelOptions : [
            'gpt-4o-mini', 'gpt-4o', 'gpt-4.1-mini', 'gpt-4.1',
            'o4-mini', 'deepseek-chat', 'deepseek-reasoner',
            'Qwen/Qwen2.5-72B-Instruct',
        ];
        for (var i = 0; i < list.length; i++) {
            var opt = document.createElement('option');
            opt.value = list[i];
            datalist.appendChild(opt);
        }
    }

    function bindEvents() {
        el.createBtn.addEventListener('click', openCreateModal);
        el.closeBtn.addEventListener('click', closeCreateModal);
        el.cancelBtn.addEventListener('click', closeCreateModal);
        el.closeAfterCreateBtn.addEventListener('click', function () {
            closeCreateModal();
            loadKeys();
        });
        el.modal.addEventListener('click', function (e) {
            if (e.target === el.modal) closeCreateModal();
        });
        el.form.addEventListener('submit', createKey);
        el.copyNewKeyBtn.addEventListener('click', function () {
            var text = el.keyValue.textContent;
            if (!text) return;
            navigator.clipboard.writeText(text).then(function () {
                el.copyNewKeyBtn.classList.add('copied');
                setTimeout(function () { el.copyNewKeyBtn.classList.remove('copied'); }, 1200);
            }).catch(function () {});
        });

        el.editCloseBtn.addEventListener('click', closeEditModal);
        el.editCancelBtn.addEventListener('click', closeEditModal);
        el.editModal.addEventListener('click', function (e) {
            if (e.target === el.editModal) closeEditModal();
        });
        el.editForm.addEventListener('submit', updateKey);

        document.addEventListener('keydown', function (e) {
            if (e.key === 'Escape') {
                if (!el.editModal.hidden) closeEditModal();
                else if (!el.modal.hidden) closeCreateModal();
            }
        });
    }

    function renderKeys() {
        el.tbody.innerHTML = '';
        if (!keys.length) {
            var tr = document.createElement('tr');
            var td = document.createElement('td');
            td.className = 'empty-row';
            td.colSpan = 7;
            td.textContent = '还没有 API 密钥，点击上方按钮创建。';
            tr.appendChild(td);
            el.tbody.appendChild(tr);
            return;
        }
        for (var i = 0; i < keys.length; i++) {
            el.tbody.appendChild(keyRow(keys[i]));
        }
        var activeCount = keys.filter(function (k) { return k.status === 'active'; }).length;
        document.getElementById('table-summary').textContent =
            '共 ' + keys.length + ' 个密钥，' + activeCount + ' 个活跃';
    }

    function keyRow(key) {
        var tr = document.createElement('tr');

        var tdKey = document.createElement('td');
        tdKey.className = 'key-cell';
        var wrap = document.createElement('div');
        wrap.className = 'key-wrap';
        var span = document.createElement('span');
        span.className = 'mono';
        span.textContent = key.key_masked;
        span.setAttribute('data-key-id', key.id);
        span.setAttribute('data-revealed', 'false');
        wrap.appendChild(span);

        var eyeBtn = document.createElement('button');
        eyeBtn.type = 'button';
        eyeBtn.className = 'ghost-btn icon-btn reveal-btn';
        eyeBtn.title = '查看密钥';
        eyeBtn.innerHTML = '&#128065;';
        (function (kId, sp) {
            eyeBtn.addEventListener('click', function () { revealKey(kId, sp, eyeBtn); });
        })(key.id, span);
        wrap.appendChild(eyeBtn);

        var copyBtn = document.createElement('button');
        copyBtn.type = 'button';
        copyBtn.className = 'ghost-btn icon-btn copy-key-btn';
        copyBtn.title = '复制密钥';
        copyBtn.innerHTML = '&#128203;';
        copyBtn.hidden = true;
        (function (sp, btn) {
            copyBtn.addEventListener('click', function () {
                var text = sp.textContent;
                if (!text || sp.getAttribute('data-revealed') !== 'true') return;
                navigator.clipboard.writeText(text).then(function () {
                    btn.classList.add('copied');
                    setTimeout(function () { btn.classList.remove('copied'); }, 1200);
                }).catch(function () {});
            });
        })(span, copyBtn);
        wrap.appendChild(copyBtn);

        tdKey.appendChild(wrap);

        var tdName = document.createElement('td');
        tdName.textContent = key.name;

        var tdModels = document.createElement('td');
        tdModels.className = 'models-cell';
        var modelsWrap = document.createElement('div');
        modelsWrap.className = 'models';
        var modelList = key.models && key.models.length ? key.models : ['全部'];
        for (var mi = 0; mi < Math.min(modelList.length, 2); mi++) {
            var chip = document.createElement('span');
            chip.className = 'model-chip';
            chip.textContent = modelList[mi];
            modelsWrap.appendChild(chip);
        }
        if (modelList.length > 2) {
            var moreChip = document.createElement('span');
            moreChip.className = 'model-chip';
            moreChip.textContent = '+' + (modelList.length - 2);
            modelsWrap.appendChild(moreChip);
        }
        tdModels.appendChild(modelsWrap);

        var tdQuota = document.createElement('td');
        tdQuota.className = 'quota-cell';
        tdQuota.textContent = key.quota ? Number(key.quota).toLocaleString() + ' tokens' : '不限';

        var tdStatus = document.createElement('td');
        var pill = document.createElement('span');
        var statusActive = key.status === 'active';
        pill.className = 'status-pill ' + (statusActive ? 'enabled' : 'disabled');
        pill.textContent = statusActive ? '启用' : '禁用';
        tdStatus.appendChild(pill);

        var tdCreated = document.createElement('td');
        tdCreated.textContent = formatDate(key.created_at);
        tdCreated.className = 'date-cell';

        var tdActions = document.createElement('td');
        tdActions.className = 'actions-cell';

        var editBtn = document.createElement('button');
        editBtn.className = 'ghost-btn';
        editBtn.type = 'button';
        editBtn.textContent = '修改';
        (function (k) {
            editBtn.addEventListener('click', function () { openEditModal(k); });
        })(key);
        tdActions.appendChild(editBtn);

        if (key.status === 'active') {
            var revokeBtn = document.createElement('button');
            revokeBtn.className = 'ghost-btn danger-ghost';
            revokeBtn.type = 'button';
            revokeBtn.textContent = '吊销';
            (function (keyId) {
                revokeBtn.addEventListener('click', function () { revokeKey(keyId); });
            })(key.id);
            tdActions.appendChild(revokeBtn);
        }

        var deleteBtn = document.createElement('button');
        deleteBtn.className = 'ghost-btn danger-ghost';
        deleteBtn.type = 'button';
        deleteBtn.textContent = '删除';
        (function (keyId) {
            deleteBtn.addEventListener('click', function () { deleteKey(keyId); });
        })(key.id);
        tdActions.appendChild(deleteBtn);

        tr.append(tdKey, tdName, tdModels, tdQuota, tdStatus, tdCreated, tdActions);
        return tr;
    }

    function openCreateModal() {
        el.form.reset();
        el.keyStatus.value = 'active';
        el.keyQuota.value = '1000000';
        el.formFields.hidden = false;
        el.keyPreview.hidden = true;
        el.modal.hidden = false;
        document.getElementById('key-modal-title').textContent = '创建新密钥';
        el.submitBtn.textContent = '创建';
        requestAnimationFrame(function () { el.keyName.focus(); });
    }

    function closeCreateModal() {
        el.modal.hidden = true;
        el.form.reset();
        el.formFields.hidden = false;
        el.keyPreview.hidden = true;
    }

    function openEditModal(key) {
        el.editKeyId.value = key.id;
        el.editKeyName.value = key.name || '';
        el.editKeyQuota.value = key.quota || 0;
        el.editKeyModels.value = (key.models || []).join(', ');
        el.editKeyValidityDays.value = '';
        el.editKeyStatus.value = key.status || 'active';
        el.editModal.hidden = false;
        requestAnimationFrame(function () { el.editKeyName.focus(); });
    }

    function closeEditModal() {
        el.editModal.hidden = true;
        el.editForm.reset();
    }

    async function createKey(event) {
        event.preventDefault();
        var name = el.keyName.value.trim();
        if (!name) {
            showNotice('请填写密钥名称。', true);
            return;
        }

        var modelsRaw = el.keyModels.value.trim();
        var models = modelsRaw ? modelsRaw.split(/[,;，；]+/).map(function (m) { return m.trim(); }).filter(Boolean) : [];
        var quota = parseInt(el.keyQuota.value, 10) || 0;
        var validityDays = el.keyValidityDays.value ? parseInt(el.keyValidityDays.value, 10) : null;
        var keyStatus = el.keyStatus.value;

        var payload = {
            name: name,
            models: models,
            quota: quota || 0,
            status: keyStatus,
        };
        if (validityDays && validityDays > 0) {
            payload.validity_days = validityDays;
        }

        el.submitBtn.disabled = true;
        el.submitBtn.textContent = '创建中';

        try {
            var result = await api('/api/keys', {
                method: 'POST',
                body: JSON.stringify(payload),
            });

            el.formFields.hidden = true;
            el.keyPreview.hidden = false;
            el.keyValue.textContent = result.key;

            showNotice('密钥已创建，请立即复制保存。');
        } catch (err) {
            showNotice(err.message, true);
        } finally {
            el.submitBtn.disabled = false;
            el.submitBtn.textContent = '创建';
        }
    }

    async function updateKey(event) {
        event.preventDefault();
        var keyId = el.editKeyId.value;
        if (!keyId) return;

        var payload = {};

        var name = el.editKeyName.value.trim();
        if (name) payload.name = name;

        var modelsRaw = el.editKeyModels.value.trim();
        if (modelsRaw) {
            payload.models = modelsRaw.split(/[,;，；]+/).map(function (m) { return m.trim(); }).filter(Boolean);
        }

        var quota = parseInt(el.editKeyQuota.value, 10);
        if (!isNaN(quota)) payload.quota = quota;

        var validityDays = el.editKeyValidityDays.value ? parseInt(el.editKeyValidityDays.value, 10) : null;
        if (validityDays && validityDays > 0) {
            payload.validity_days = validityDays;
        }

        var status = el.editKeyStatus.value;
        if (status) payload.status = status;

        el.editSubmitBtn.disabled = true;
        el.editSubmitBtn.textContent = '保存中';

        try {
            await api('/api/keys/' + keyId, {
                method: 'PUT',
                body: JSON.stringify(payload),
            });
            closeEditModal();
            await loadKeys();
            showNotice('密钥已更新。');
        } catch (err) {
            showNotice(err.message, true);
        } finally {
            el.editSubmitBtn.disabled = false;
            el.editSubmitBtn.textContent = '保存';
        }
    }

    async function revokeKey(keyId) {
        if (!confirm('确定要吊销此密钥吗？吊销后使用该密钥的 API 请求将立即失效。此操作不可撤销。')) return;
        try {
            await api('/api/keys/' + keyId + '/revoke', { method: 'PUT' });
            await loadKeys();
            showNotice('密钥已吊销。');
        } catch (err) {
            showNotice(err.message, true);
        }
    }

    async function deleteKey(keyId) {
        if (!confirm('确定要删除此密钥吗？此操作不可撤销。')) return;
        try {
            await api('/api/keys/' + keyId, { method: 'DELETE' });
            await loadKeys();
            showNotice('密钥已删除。');
        } catch (err) {
            showNotice(err.message, true);
        }
    }

    async function revealKey(keyId, spanEl, eyeBtnEl) {
        var isRevealed = spanEl.getAttribute('data-revealed') === 'true';
        if (isRevealed) {
            var row = spanEl.closest('tr');
            var keyData = keys.find(function (k) { return k.id === keyId; });
            spanEl.textContent = keyData ? keyData.key_masked : '***';
            spanEl.setAttribute('data-revealed', 'false');
            eyeBtnEl.title = '查看密钥';
            var copyBtn = spanEl.parentElement.querySelector('.copy-key-btn');
            if (copyBtn) copyBtn.hidden = true;
            return;
        }
        eyeBtnEl.disabled = true;
        try {
            var result = await api('/api/keys/' + keyId + '/reveal', { method: 'POST' });
            spanEl.textContent = result.key;
            spanEl.setAttribute('data-revealed', 'true');
            eyeBtnEl.title = '隐藏密钥';
            var copyBtn = spanEl.parentElement.querySelector('.copy-key-btn');
            if (copyBtn) copyBtn.hidden = false;
        } catch (err) {
            showNotice('查看密钥失败: ' + err.message, true);
        } finally {
            eyeBtnEl.disabled = false;
        }
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

    function formatDate(value) {
        if (!value) return '-';
        try {
            var d = new Date(value);
            if (isNaN(d.getTime())) return value;
            return d.getFullYear() + '-' +
                String(d.getMonth() + 1).padStart(2, '0') + '-' +
                String(d.getDate()).padStart(2, '0') + ' ' +
                String(d.getHours()).padStart(2, '0') + ':' +
                String(d.getMinutes()).padStart(2, '0') + ':' +
                String(d.getSeconds()).padStart(2, '0');
        } catch (e) {
            return value;
        }
    }
});
