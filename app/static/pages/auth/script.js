document.addEventListener('DOMContentLoaded', () => {
    const els = {
        loginForm: document.getElementById('login-form'),
        registerForm: document.getElementById('register-form'),
        authLoading: document.getElementById('auth-loading'),
        loginError: document.getElementById('login-error'),
        regError: document.getElementById('reg-error'),
        loginBtn: document.getElementById('login-btn'),
        registerBtn: document.getElementById('register-btn'),
        loginUsername: document.getElementById('login-username'),
        loginPassword: document.getElementById('login-password'),
        regUsername: document.getElementById('reg-username'),
        regDisplayName: document.getElementById('reg-display-name'),
        regPassword: document.getElementById('reg-password'),
        regConfirmPassword: document.getElementById('reg-confirm-password'),
    };

    document.getElementById('switch-to-register').addEventListener('click', (e) => { e.preventDefault(); showPanel('register'); });
    document.getElementById('switch-to-login').addEventListener('click', (e) => { e.preventDefault(); showPanel('login'); });
    els.loginBtn.addEventListener('click', handleLogin);
    els.registerBtn.addEventListener('click', handleRegister);
    els.loginPassword.addEventListener('keydown', (e) => { if (e.key === 'Enter') handleLogin(); });
    els.regConfirmPassword.addEventListener('keydown', (e) => { if (e.key === 'Enter') handleRegister(); });

    checkAuthStatus();

    async function checkAuthStatus() {
        showPanel('loading');
        try {
            const res = await fetch('/api/auth/status');
            const data = await res.json();
            showPanel(data.has_users ? 'login' : 'register');
        } catch {
            showPanel('login');
            showError(els.loginError, '无法连接服务器');
        }
    }

    function showPanel(panel) {
        els.loginForm.hidden = panel !== 'login';
        els.registerForm.hidden = panel !== 'register';
        els.authLoading.hidden = panel !== 'loading';
        els.loginError.hidden = true;
        els.regError.hidden = true;
        els.loginBtn.disabled = false;
        els.registerBtn.disabled = false;
        if (panel === 'login') els.loginUsername.focus();
        if (panel === 'register') els.regUsername.focus();
    }

    function showError(el, msg) {
        el.textContent = msg;
        el.hidden = false;
    }

    function setLoading(btn, loading) {
        btn.disabled = loading;
        btn.textContent = loading ? '请稍候...' : btn.dataset.label;
    }

    async function handleLogin() {
        const username = els.loginUsername.value.trim();
        const password = els.loginPassword.value;

        if (!username || !password) { showError(els.loginError, '请填写用户名和密码'); return; }

        els.loginBtn.dataset.label = '登 录';
        setLoading(els.loginBtn, true);
        els.loginError.hidden = true;

        try {
            const res = await fetch('/api/auth/login', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ username, password }),
            });
            const data = await res.json();
            if (!res.ok) {
                showError(els.loginError, data.detail || '登录失败');
                setLoading(els.loginBtn, false);
                return;
            }
            localStorage.setItem('access_token', data.access_token);
            window.location.href = '/';
        } catch {
            showError(els.loginError, '网络错误，请稍后重试');
            setLoading(els.loginBtn, false);
        }
    }

    async function handleRegister() {
        const username = els.regUsername.value.trim();
        const displayName = els.regDisplayName.value.trim() || null;
        const password = els.regPassword.value;
        const confirm = els.regConfirmPassword.value;

        if (!username) { showError(els.regError, '请填写用户名'); return; }
        if (username.length < 3) { showError(els.regError, '用户名至少3个字符'); return; }
        if (!password) { showError(els.regError, '请填写密码'); return; }
        if (password.length < 8) { showError(els.regError, '密码至少8位'); return; }
        if (password !== confirm) { showError(els.regError, '两次密码不一致'); return; }

        els.registerBtn.dataset.label = '注 册';
        setLoading(els.registerBtn, true);
        els.regError.hidden = true;

        try {
            const res = await fetch('/api/auth/register', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ username, password, display_name: displayName }),
            });
            const data = await res.json();
            if (!res.ok) {
                showError(els.regError, data.detail || '注册失败');
                setLoading(els.registerBtn, false);
                return;
            }
            localStorage.setItem('access_token', data.access_token);
            window.location.href = '/';
        } catch {
            showError(els.regError, '网络错误，请稍后重试');
            setLoading(els.registerBtn, false);
        }
    }
});
