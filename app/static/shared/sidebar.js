/**
 * Shared Sidebar Renderer
 *
 * Injects the complete sidebar into the app container.
 * Call once per page, typically at the top of DOMContentLoaded.
 *
 * Options:
 *   activePath     - Current route path (e.g. '/channels/accounts')
 *   showHistory    - Show the history list section (chat page)
 *   showHint       - Show hint section (channels pages)
 *   hintTitle      - Hint section title
 *   hintText       - Hint section text
 *   showUserFooter - Show the user info + logout section (default: true)
 */

function renderSidebar(options) {
    var opts = {
        activePath: '/',
        showHistory: false,
        showHint: false,
        hintTitle: '',
        hintText: '',
        showUserFooter: true,
    };
    if (options) {
        if (options.activePath !== undefined) opts.activePath = options.activePath;
        if (options.showHistory !== undefined) opts.showHistory = options.showHistory;
        if (options.showHint !== undefined) opts.showHint = options.showHint;
        if (options.hintTitle !== undefined) opts.hintTitle = options.hintTitle;
        if (options.hintText !== undefined) opts.hintText = options.hintText;
        if (options.showUserFooter !== undefined) opts.showUserFooter = options.showUserFooter;
    }

    var appContainer = document.querySelector('.app-container');
    if (!appContainer) return;

    // Don't re-render if sidebar already exists
    if (appContainer.querySelector('.sidebar')) return;

    var isChannelsExpanded = opts.activePath.indexOf('/channels') === 0;

    var sidebar = document.createElement('aside');
    sidebar.className = 'sidebar';
    sidebar.innerHTML =
        '<div class="sidebar-top">' +
            '<a class="brand" href="/">' +
                '<span>AI Stream</span>' +
                '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true">' +
                    '<rect x="3" y="3" width="18" height="18" rx="2" ry="2"></rect>' +
                    '<line x1="9" y1="3" x2="9" y2="21"></line>' +
                '</svg>' +
            '</a>' +
            '<nav class="nav-menu" aria-label="主导航">' +
                '<a class="nav-item' + (opts.activePath === '/' ? ' active' : '') + '" href="/">' +
                    '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true">' +
                        '<path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"></path>' +
                    '</svg>' +
                    '新聊天' +
                '</a>' +
                '<a class="nav-item" href="/">' +
                    '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true">' +
                        '<circle cx="11" cy="11" r="8"></circle>' +
                        '<line x1="21" y1="21" x2="16.65" y2="16.65"></line>' +
                    '</svg>' +
                    '搜索聊天' +
                '</a>' +
                '<div class="nav-group">' +
                    '<button class="nav-item nav-parent' + (isChannelsExpanded ? ' active' : '') + '" data-expanded="' + isChannelsExpanded + '" type="button" aria-expanded="' + isChannelsExpanded + '">' +
                        '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true">' +
                            '<path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"></path>' +
                        '</svg>' +
                        '<span>channels</span>' +
                        '<svg class="chevron" viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true">' +
                            '<polyline points="9 18 15 12 9 6"></polyline>' +
                        '</svg>' +
                    '</button>' +
                    '<div class="nav-sublist' + (isChannelsExpanded ? ' expanded' : '') + '">' +
                        '<a class="nav-subitem' + (opts.activePath === '/channels/accounts' ? ' active' : '') + '" href="/channels/accounts">渠道账号</a>' +
                        '<a class="nav-subitem' + (opts.activePath === '/channels/keys' ? ' active' : '') + '" href="/channels/keys">密钥管理</a>' +
                        '<a class="nav-subitem' + (opts.activePath === '/channels/usage' ? ' active' : '') + '" href="/channels/usage">用量管理</a>' +
                    '</div>' +
                '</div>' +
            '</nav>' +
        '</div>' +
        '<div class="history-list" id="sidebar-history"' + (opts.showHistory ? '' : ' style="display:none"') + '>' +
            '<div class="history-section-title">最近</div>' +
        '</div>' +
        '<div class="sidebar-hint" id="sidebar-hint"' + (opts.showHint ? '' : ' style="display:none"') + '>' +
            '<div class="hint-title">' + _escapeHtml(opts.hintTitle) + '</div>' +
            '<p>' + _escapeHtml(opts.hintText) + '</p>' +
        '</div>' +
        '<div class="sidebar-footer" id="user-menu"' + (opts.showUserFooter ? '' : ' style="display:none"') + '>' +
            '<div class="user-info">' +
                '<div class="user-avatar" id="user-avatar">U</div>' +
                '<span class="user-name" id="user-name">用户</span>' +
            '</div>' +
            '<button id="logout-btn" class="logout-btn" type="button" title="退出登录">' +
                '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2">' +
                    '<path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"></path>' +
                    '<polyline points="16 17 21 12 16 7"></polyline>' +
                    '<line x1="21" y1="12" x2="9" y2="12"></line>' +
                '</svg>' +
            '</button>' +
        '</div>';

    appContainer.prepend(sidebar);

    // ── Collapsible channels toggle ──
    var navParent = sidebar.querySelector('.nav-parent');
    var navSublist = sidebar.querySelector('.nav-sublist');
    if (navParent && navSublist) {
        navParent.addEventListener('click', function (e) {
            e.preventDefault();
            var expanded = this.getAttribute('data-expanded') === 'true';
            var newExpanded = !expanded;
            this.setAttribute('data-expanded', String(newExpanded));
            this.setAttribute('aria-expanded', String(newExpanded));
            if (newExpanded) {
                navSublist.classList.add('expanded');
            } else {
                navSublist.classList.remove('expanded');
            }
        });
    }

    // ── Logout ──
    var logoutBtn = sidebar.querySelector('#logout-btn');
    if (logoutBtn) {
        logoutBtn.addEventListener('click', function () {
            localStorage.removeItem('access_token');
            localStorage.removeItem('token');
            window.location.href = '/login';
        });
    }

    // ── Load user info ──
    _loadUser();
}

// ── Internal helpers ──

function _loadUser() {
    var token = _getAccessToken();
    if (!token) return;
    var nameEl = document.getElementById('user-name');
    var avatarEl = document.getElementById('user-avatar');
    if (!nameEl || !avatarEl) return;

    fetch('/api/auth/me', {
        headers: { Authorization: 'Bearer ' + token }
    })
        .then(function (r) {
            if (!r.ok) throw new Error('unauthorized');
            return r.json();
        })
        .then(function (u) {
            var name = u.display_name || u.username;
            nameEl.textContent = name;
            avatarEl.textContent = name.charAt(0).toUpperCase();
        })
        .catch(function () {
            localStorage.removeItem('access_token');
            localStorage.removeItem('token');
            window.location.href = '/login';
        });
}

function _getAccessToken() {
    return localStorage.getItem('access_token') || localStorage.getItem('token') || '';
}

function _escapeHtml(str) {
    var d = document.createElement('div');
    d.textContent = str || '';
    return d.innerHTML;
}
