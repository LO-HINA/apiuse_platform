(function () {
    if (!(localStorage.getItem('access_token') || localStorage.getItem('token'))) {
        window.location.href = '/login';
    }
})();

document.addEventListener('DOMContentLoaded', function () {
    renderSidebar({
        activePath: '/channels/usage',
        showHistory: false,
        showHint: true,
        hintTitle: '用量管理',
        hintText: '查看 API 使用量和统计信息，了解各模型的使用情况。',
        showUserFooter: false,
    });

    var el = {
        tbody: document.getElementById('usage-tbody'),
        modelFilter: document.getElementById('model-filter'),
        refreshBtn: document.getElementById('refresh-btn'),
        chartCanvas: document.getElementById('usage-chart'),
    };

    var chartTooltip = document.createElement('div');
    chartTooltip.className = 'chart-tooltip';
    el.chartCanvas.parentElement.appendChild(chartTooltip);

    var dailyData = [];
    var detailData = [];

    bindEvents();
    loadModels();
    loadUsage();

    function bindEvents() {
        el.modelFilter.addEventListener('change', loadUsage);
        el.refreshBtn.addEventListener('click', function () {
            loadUsage();
            showNotice('数据已刷新。');
        });
    }

    function apiFetch(path) {
        var token = localStorage.getItem('access_token') || localStorage.getItem('token');
        return fetch(path, {
            headers: { 'Authorization': 'Bearer ' + token },
        }).then(function (r) {
            if (r.status === 401) {
                localStorage.removeItem('access_token');
                localStorage.removeItem('token');
                window.location.href = '/login';
                return Promise.reject(new Error('unauthorized'));
            }
            return r.json();
        });
    }

    function loadModels() {
        apiFetch('/api/usage/models').then(function (models) {
            var current = el.modelFilter.value;
            el.modelFilter.innerHTML = '<option value="">全部模型</option>';
            models.forEach(function (m) {
                var opt = document.createElement('option');
                opt.value = m;
                opt.textContent = m;
                el.modelFilter.appendChild(opt);
            });
            el.modelFilter.value = current;
        }).catch(function () {});
    }

    function loadUsage() {
        var model = el.modelFilter.value;
        var detailUrl = '/api/usage/detail?days=30' + (model ? '&model=' + encodeURIComponent(model) : '');
        var dailyUrl = '/api/usage/daily?days=30';

        apiFetch(dailyUrl).then(function (data) {
            dailyData = data;
            renderStats();
            renderChart(dailyData);
        }).catch(function () {});

        apiFetch(detailUrl).then(function (data) {
            detailData = data;
            document.getElementById('table-summary').textContent =
                '显示 ' + detailData.length + ' 条记录' + (model ? '（已筛选）' : '');
            renderTable(detailData);
        }).catch(function () {});
    }

    function renderStats() {
        var totalReq = 0;
        var todayReq = 0;
        var monthReq = 0;
        var now = new Date();
        var todayStr = now.toISOString().slice(0, 10);
        var monthStr = todayStr.slice(0, 8) + '01';

        dailyData.forEach(function (row) {
            totalReq += row.requests;
            if (row.date >= monthStr) monthReq += row.requests;
            if (row.date === todayStr) todayReq += row.requests;
        });

        document.getElementById('stat-total').textContent = formatNumber(totalReq);
        document.getElementById('stat-today').textContent = formatNumber(todayReq);
        document.getElementById('stat-month').textContent = formatNumber(monthReq);
    }

    function renderTable(data) {
        el.tbody.innerHTML = '';
        if (!data.length) {
            var tr = document.createElement('tr');
            var td = document.createElement('td');
            td.className = 'empty-row';
            td.colSpan = 6;
            td.textContent = '没有匹配的用量记录。';
            tr.appendChild(td);
            el.tbody.appendChild(tr);
            return;
        }
        data.forEach(function (row) {
            el.tbody.appendChild(usageRow(row));
        });
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
        tdTotal.textContent = formatNumber(row.total_tokens);
        tdTotal.className = 'num-cell total-cell';

        tr.append(tdDate, tdModel, tdReq, tdIn, tdOut, tdTotal);
        return tr;
    }

    function formatNumber(num) {
        return String(num).replace(/\B(?=(\d{3})+(?!\d))/g, ',');
    }

    var _chartBars = [];

    function renderChart(data) {
        var canvas = el.chartCanvas;
        var dpr = window.devicePixelRatio || 1;
        var rect = canvas.getBoundingClientRect();
        canvas.width = rect.width * dpr;
        canvas.height = rect.height * dpr;
        var ctx = canvas.getContext('2d');
        ctx.scale(dpr, dpr);

        var days = data.map(function (d) { return d.date; });
        var values = data.map(function (d) { return d.total_tokens; });

        var W = rect.width;
        var H = rect.height;
        var padL = 64;
        var padR = 20;
        var padT = 16;
        var padB = 36;
        var chartW = W - padL - padR;
        var chartH = H - padT - padB;

        ctx.clearRect(0, 0, W, H);

        if (!days.length) {
            ctx.fillStyle = '#8f9bb2';
            ctx.font = '13px sans-serif';
            ctx.textAlign = 'center';
            ctx.fillText('暂无数据', W / 2, H / 2);
            _chartBars = [];
            return;
        }

        var maxVal = Math.max.apply(null, values);
        var niceMax = niceNum(maxVal);
        var ticks = 5;

        ctx.strokeStyle = '#303237';
        ctx.lineWidth = 1;
        ctx.fillStyle = '#8f9bb2';
        ctx.font = '11px sans-serif';
        ctx.textAlign = 'right';
        ctx.textBaseline = 'middle';

        for (var t = 0; t <= ticks; t++) {
            var val = (niceMax / ticks) * t;
            var y = padT + chartH - (chartH * val / niceMax);
            ctx.beginPath();
            ctx.moveTo(padL, y);
            ctx.lineTo(padL + chartW, y);
            ctx.stroke();
            ctx.fillText(shortNum(val), padL - 8, y);
        }

        var barGap = Math.max(4, chartW / days.length * 0.25);
        var barW = Math.max(6, (chartW - barGap * (days.length + 1)) / days.length);
        if (barW > 40) barW = 40;
        var totalBarsW = days.length * barW + (days.length + 1) * barGap;
        var offsetX = padL + (chartW - totalBarsW) / 2;

        _chartBars = [];

        for (var i = 0; i < days.length; i++) {
            var x = offsetX + barGap + i * (barW + barGap);
            var barH = (chartH * values[i]) / niceMax;
            var y = padT + chartH - barH;

            var grad = ctx.createLinearGradient(x, y, x, padT + chartH);
            grad.addColorStop(0, '#7aa7ff');
            grad.addColorStop(1, '#3b5998');
            ctx.fillStyle = grad;
            roundRect(ctx, x, y, barW, barH, 3);
            ctx.fill();

            ctx.fillStyle = '#8f9bb2';
            ctx.font = '10px sans-serif';
            ctx.textAlign = 'center';
            ctx.textBaseline = 'top';
            var label = days[i].slice(5);
            ctx.fillText(label, x + barW / 2, padT + chartH + 6);

            _chartBars.push({ x: x, y: y, w: barW, h: barH, date: days[i], value: values[i] });
        }
    }

    function roundRect(ctx, x, y, w, h, r) {
        r = Math.min(r, w / 2, h / 2);
        if (h < 1) h = 1;
        ctx.beginPath();
        ctx.moveTo(x + r, y);
        ctx.lineTo(x + w - r, y);
        ctx.arcTo(x + w, y, x + w, y + r, r);
        ctx.lineTo(x + w, y + h);
        ctx.lineTo(x, y + h);
        ctx.lineTo(x, y + r);
        ctx.arcTo(x, y, x + r, y, r);
        ctx.closePath();
    }

    function niceNum(val) {
        if (val <= 0) return 1;
        var exp = Math.floor(Math.log10(val));
        var frac = val / Math.pow(10, exp);
        var nice;
        if (frac <= 1) nice = 1;
        else if (frac <= 2) nice = 2;
        else if (frac <= 5) nice = 5;
        else nice = 10;
        return nice * Math.pow(10, exp);
    }

    function shortNum(n) {
        if (n >= 1e6) return (n / 1e6).toFixed(1) + 'M';
        if (n >= 1e3) return (n / 1e3).toFixed(1) + 'K';
        return String(Math.round(n));
    }

    el.chartCanvas.addEventListener('mousemove', function (e) {
        var rect = el.chartCanvas.getBoundingClientRect();
        var mx = e.clientX - rect.left;
        var my = e.clientY - rect.top;
        var hit = null;
        for (var i = 0; i < _chartBars.length; i++) {
            var b = _chartBars[i];
            if (mx >= b.x && mx <= b.x + b.w && my >= b.y && my <= b.y + b.h) {
                hit = b;
                break;
            }
        }
        if (hit) {
            chartTooltip.textContent = hit.date + '  ' + formatNumber(hit.value) + ' tokens';
            chartTooltip.style.left = (hit.x + hit.w / 2) + 'px';
            chartTooltip.style.top = (hit.y - 32) + 'px';
            chartTooltip.classList.add('visible');
        } else {
            chartTooltip.classList.remove('visible');
        }
    });

    el.chartCanvas.addEventListener('mouseleave', function () {
        chartTooltip.classList.remove('visible');
    });

    window.addEventListener('resize', function () {
        renderChart(dailyData);
    });

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
