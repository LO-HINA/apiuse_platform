// 鉴权守卫: 没有 token 跳登录页
(function () {
    if (!(localStorage.getItem('access_token') || localStorage.getItem('token'))) {
        window.location.href = '/login';
    }
})();

document.addEventListener('DOMContentLoaded', function () {
    // Render shared sidebar
    renderSidebar({
        activePath: '/channels/usage',
        showHistory: false,
        showHint: true,
        hintTitle: '用量管理',
        hintText: '查看 API 使用量和统计信息，了解各模型的使用情况。',
        showUserFooter: false,
    });

    // ── Mock data ──
    var mockUsageData = [
        { date: '2026-06-20', model: 'gpt-4o-mini', requests: 523, input_tokens: 45230, output_tokens: 12340 },
        { date: '2026-06-20', model: 'gpt-4o', requests: 156, input_tokens: 28900, output_tokens: 5670 },
        { date: '2026-06-19', model: 'gpt-4o-mini', requests: 487, input_tokens: 39120, output_tokens: 10890 },
        { date: '2026-06-19', model: 'deepseek-chat', requests: 234, input_tokens: 34500, output_tokens: 8900 },
        { date: '2026-06-18', model: 'gpt-4o-mini', requests: 612, input_tokens: 51200, output_tokens: 15670 },
        { date: '2026-06-18', model: 'gpt-4o', requests: 98, input_tokens: 18300, output_tokens: 3450 },
        { date: '2026-06-17', model: 'gpt-4o-mini', requests: 445, input_tokens: 38700, output_tokens: 10230 },
        { date: '2026-06-17', model: 'deepseek-chat', requests: 312, input_tokens: 42100, output_tokens: 12340 },
        { date: '2026-06-16', model: 'gpt-4o-mini', requests: 378, input_tokens: 30100, output_tokens: 8760 },
        { date: '2026-06-16', model: 'gpt-4o', requests: 167, input_tokens: 31200, output_tokens: 6540 },
    ];

    var el = {
        tbody: document.getElementById('usage-tbody'),
        modelFilter: document.getElementById('model-filter'),
        refreshBtn: document.getElementById('refresh-btn'),
    };

    bindEvents();
    renderUsage();

    function bindEvents() {
        el.modelFilter.addEventListener('change', renderUsage);
        el.refreshBtn.addEventListener('click', function () {
            renderUsage();
            showNotice('数据已刷新。');
        });
    }

    function renderUsage() {
        var filterModel = el.modelFilter.value;
        var filtered = filterModel
            ? mockUsageData.filter(function (row) { return row.model === filterModel; })
            : mockUsageData;

        // Calculate stats
        var totalRequests = 0;
        var todayRequests = 0;
        var monthRequests = 0;
        var today = '2026-06-20';
        var monthStart = '2026-06-01';

        for (var i = 0; i < mockUsageData.length; i++) {
            var row = mockUsageData[i];
            totalRequests += row.requests;
            if (row.date >= monthStart) monthRequests += row.requests;
            if (row.date === today) todayRequests += row.requests;
        }

        document.getElementById('stat-total').textContent = formatNumber(totalRequests);
        document.getElementById('stat-today').textContent = formatNumber(todayRequests);
        document.getElementById('stat-month').textContent = formatNumber(monthRequests);
        document.getElementById('table-summary').textContent =
            '显示 ' + filtered.length + ' 条记录' + (filterModel ? '（已筛选）' : '');

        el.tbody.innerHTML = '';
        if (!filtered.length) {
            var tr = document.createElement('tr');
            var td = document.createElement('td');
            td.className = 'empty-row';
            td.colSpan = 6;
            td.textContent = '没有匹配的用量记录。';
            tr.appendChild(td);
            el.tbody.appendChild(tr);
            return;
        }

        for (var i = 0; i < filtered.length; i++) {
            el.tbody.appendChild(usageRow(filtered[i]));
        }
    }

    function usageRow(row) {
        var tr = document.createElement('tr');

        var tdDate = document.createElement('td');
        tdDate.textContent = row.date;
        tdDate.className = 'date-cell';

        var tdModel = document.createElement('td');
        var chip = document.createElement('span');
        chip.className = 'model-chip';
        chip.textContent = row.model;
        tdModel.appendChild(chip);

        var tdReq = document.createElement('td');
        tdReq.textContent = formatNumber(row.requests);
        tdReq.className = 'num-cell';

        var tdIn = document.createElement('td');
        tdIn.textContent = formatNumber(row.input_tokens);
        tdIn.className = 'num-cell';

        var tdOut = document.createElement('td');
        tdOut.textContent = formatNumber(row.output_tokens);
        tdOut.className = 'num-cell';

        var tdTotal = document.createElement('td');
        tdTotal.textContent = formatNumber(row.input_tokens + row.output_tokens);
        tdTotal.className = 'num-cell total-cell';

        tr.append(tdDate, tdModel, tdReq, tdIn, tdOut, tdTotal);
        return tr;
    }

    function formatNumber(num) {
        return String(num).replace(/\B(?=(\d{3})+(?!\d))/g, ',');
    }

    function showNotice(message) {
        var notice = document.getElementById('notice');
        if (!notice) {
            notice = document.createElement('section');
            notice.id = 'notice';
            notice.className = 'notice';
            var main = document.querySelector('.usage-main');
            if (main) main.insertBefore(notice, main.querySelector('.stats-grid'));
        }
        if (!message) {
            notice.hidden = true;
            notice.textContent = '';
            return;
        }
        notice.hidden = false;
        notice.textContent = message;
        notice.classList.remove('error');
    }
});
