(function () {
    const PER_PAGE = 50;
    const state = { days: 7, query: '', page: 1, totalPages: 1, open: new Set() };
    const els = {
        search: document.getElementById('costSearch'),
        days: document.getElementById('costDays'),
        stats: document.getElementById('costStats'),
        results: document.getElementById('costResults'),
        models: document.getElementById('costModels'),
        prev: document.getElementById('costPrev'),
        next: document.getElementById('costNext'),
        pageInfo: document.getElementById('costPageInfo'),
    };

    function escapeHtml(value) {
        return String(value ?? '').replace(/[&<>"']/g, (ch) => ({
            '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
        }[ch]));
    }

    // Costs are tiny (fractions of a cent): keep enough digits to compare.
    function money(value) {
        if (value === null || value === undefined) return '—';
        const v = Number(value);
        if (v === 0) return '$0';
        if (v < 0.01) return '$' + v.toFixed(6);
        return '$' + v.toFixed(4);
    }

    function num(value) {
        return value === null || value === undefined ? '—' : Number(value).toLocaleString();
    }

    // SQLite CURRENT_TIMESTAMP is UTC without a zone marker.
    function when(ts) {
        if (!ts) return '';
        const d = new Date(ts.replace(' ', 'T') + 'Z');
        return isNaN(d) ? ts : d.toLocaleString([], { dateStyle: 'short', timeStyle: 'short' });
    }

    // WhatsApp prompts carry "[Message from: ...]" labels; keep them, they say who asked.
    function promptText(p) {
        return p.prompt || '(prompt not found: ' + p.message_in_id + ')';
    }

    function renderStats(totals, days) {
        const missing = totals.calls_without_cost || 0;
        const stats = [
            ['Total cost', money(totals.cost || 0), missing ? `${missing} call(s) without cost` : `last ${days} day(s)`],
            ['Prompts', num(totals.prompts || 0), 'with at least one model call'],
            ['Cost per prompt', totals.prompts ? money((totals.cost || 0) / totals.prompts) : '—', 'average'],
            ['Model calls', num(totals.calls || 0), totals.prompts ? (totals.calls / totals.prompts).toFixed(1) + ' per prompt' : ''],
            ['Tokens', num((totals.input_tokens || 0) + (totals.output_tokens || 0)),
                `${num(totals.input_tokens || 0)} in / ${num(totals.output_tokens || 0)} out`],
        ];
        els.stats.innerHTML = stats.map(([label, value, hint]) =>
            `<div class="cost-stat"><div class="label">${label}</div><div class="value">${value}</div><div class="hint">${escapeHtml(hint)}</div></div>`
        ).join('');
    }

    function renderModels(rows) {
        if (!rows.length) {
            els.models.innerHTML = '<tr><td class="cost-empty">No model calls in this period.</td></tr>';
            return;
        }
        els.models.innerHTML = '<tr><th>Model</th><th class="n">Calls</th><th class="n">Input</th><th class="n">Output</th><th class="n">Cost</th></tr>' +
            rows.map((r) => `<tr><td>${escapeHtml(r.model)}</td><td class="n">${num(r.calls)}</td><td class="n">${num(r.input_tokens)}</td><td class="n">${num(r.output_tokens)}</td><td class="n">${money(r.cost)}</td></tr>`).join('');
    }

    function promptRow(p) {
        const models = (p.models || '').split(',').filter(Boolean)
            .map((m) => `<span class="cost-badge">${escapeHtml(m)}</span>`).join('');
        const partial = p.calls_without_cost && p.cost !== null
            ? `<div class="cost-meta">${p.calls_without_cost} call(s) without cost</div>` : '';
        return `
            <div class="cost-row" data-id="${escapeHtml(p.message_in_id)}">
                <div class="cost-meta">${escapeHtml(when(p.started_at))}<br>${escapeHtml(p.worker || '')}<br>${escapeHtml(p.channel_id || '')}</div>
                <div class="cost-prompt-col"><div class="cost-prompt">${escapeHtml(promptText(p))}</div><div>${models}</div></div>
                <div class="cost-num cost-meta cost-col-tokens">${num(p.input_tokens)} in<br>${num(p.output_tokens)} out${p.reasoning_tokens ? '<br>' + num(p.reasoning_tokens) + ' reasoning' : ''}</div>
                <div class="cost-num cost-meta cost-col-calls">${num(p.calls)} call(s)<br>${num(p.tool_calls)} tool call(s)${p.latency_ms ? '<br>' + (p.latency_ms / 1000).toFixed(1) + 's' : ''}</div>
                <div class="cost-num"><span class="cost-money">${money(p.cost)}</span>${partial}</div>
                <div class="cost-detail" style="display: none;"></div>
            </div>`;
    }

    function callsTable(calls) {
        if (!calls.length) return '<div class="cost-meta">No calls recorded.</div>';
        const head = ['Time', 'Stage', 'Model', 'Served by', 'Input', 'Cached', 'Output', 'Reasoning', 'Tools', 'Finish', 'Latency', 'Cost'];
        const rows = calls.map((c) => `<tr>
            <td>${escapeHtml(when(c.created_at))}</td>
            <td>${escapeHtml(c.stage || c.stack || '')}</td>
            <td>${escapeHtml(c.response_model || c.model || '')}</td>
            <td>${escapeHtml(c.upstream_provider || c.provider || '')}</td>
            <td class="n">${num(c.input_tokens)}</td>
            <td class="n">${num(c.cached_tokens)}</td>
            <td class="n">${num(c.output_tokens)}</td>
            <td class="n">${num(c.reasoning_tokens)}</td>
            <td class="n">${num(c.tool_calls)}</td>
            <td>${escapeHtml(c.finish_reason || '')}</td>
            <td class="n">${c.latency_ms ? (c.latency_ms / 1000).toFixed(1) + 's' : '—'}</td>
            <td class="n">${money(c.cost)}</td>
        </tr>`).join('');
        return `<table><tr>${head.map((h) => `<th>${h}</th>`).join('')}</tr>${rows}</table>`;
    }

    async function toggleDetail(row) {
        const detail = row.querySelector('.cost-detail');
        const id = row.dataset.id;
        if (detail.style.display !== 'none') {
            detail.style.display = 'none';
            state.open.delete(id);
            return;
        }
        state.open.add(id);
        detail.style.display = 'block';
        detail.innerHTML = '<div class="cost-meta">Loading…</div>';
        try {
            const res = await fetch(`/api/costs/prompts/${encodeURIComponent(id)}/calls`);
            const data = await res.json();
            detail.innerHTML = callsTable(data.calls || []);
        } catch (e) {
            detail.innerHTML = '<div class="cost-meta">Could not load the calls.</div>';
        }
    }

    async function load() {
        const params = new URLSearchParams({ days: state.days, page: state.page, per_page: PER_PAGE });
        if (state.query) params.set('q', state.query);
        els.results.innerHTML = '<div class="cost-empty">Loading…</div>';
        let data;
        try {
            const res = await fetch('/api/costs/prompts?' + params);
            data = await res.json();
        } catch (e) {
            els.results.innerHTML = '<div class="cost-empty">Could not load the costs.</div>';
            return;
        }
        renderStats(data.totals || {}, data.days);
        renderModels(data.by_model || []);
        state.totalPages = Math.max(1, Math.ceil((data.total || 0) / PER_PAGE));
        els.pageInfo.textContent = `Page ${state.page} of ${state.totalPages} · ${num(data.total || 0)} prompt(s)`;
        els.prev.disabled = state.page <= 1;
        els.next.disabled = state.page >= state.totalPages;
        if (!data.prompts || !data.prompts.length) {
            els.results.innerHTML = '<div class="cost-list"><div class="cost-empty">No prompts with model calls in this period.</div></div>';
            return;
        }
        els.results.innerHTML = '<div class="cost-list">' +
            '<div class="cost-row cost-head"><div>When / worker</div><div>Prompt</div><div class="cost-num cost-col-tokens">Tokens</div><div class="cost-num cost-col-calls">Calls</div><div class="cost-num">Cost</div></div>' +
            data.prompts.map(promptRow).join('') + '</div>';
        els.results.querySelectorAll('.cost-row[data-id]').forEach((row) => {
            row.addEventListener('click', (e) => {
                if (e.target.closest('.cost-detail')) return;
                toggleDetail(row);
            });
            if (state.open.has(row.dataset.id)) toggleDetail(row);
        });
    }

    let searchTimer = null;
    els.search.addEventListener('input', () => {
        clearTimeout(searchTimer);
        searchTimer = setTimeout(() => {
            state.query = els.search.value.trim();
            state.page = 1;
            load();
        }, 300);
    });
    els.days.addEventListener('change', () => {
        state.days = Number(els.days.value);
        state.page = 1;
        load();
    });
    els.prev.addEventListener('click', () => { if (state.page > 1) { state.page--; load(); } });
    els.next.addEventListener('click', () => { if (state.page < state.totalPages) { state.page++; load(); } });

    load();
})();
