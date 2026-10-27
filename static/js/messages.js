(function () {
    const PER_PAGE = 50;

    const state = {
        mode: 'all',
        channel: '',
        query: '',
        threshold: 0.9,
        page: 1,
        totalPages: 1,
        selected: new Set(),
        // ids of the groups currently shown (duplicates / similar), for "keep newest"
        groups: [],
    };

    const els = {
        search: document.getElementById('msgSearch'),
        channel: document.getElementById('msgChannel'),
        tabs: document.querySelectorAll('.msg-tabs button'),
        thresholdField: document.getElementById('msgThresholdField'),
        threshold: document.getElementById('msgThreshold'),
        thresholdValue: document.getElementById('msgThresholdValue'),
        results: document.getElementById('msgResults'),
        total: document.getElementById('msgTotal'),
        selectPage: document.getElementById('msgSelectPage'),
        keepNewest: document.getElementById('msgKeepNewest'),
        clearSelection: document.getElementById('msgClearSelection'),
        deleteSelected: document.getElementById('msgDeleteSelected'),
        prev: document.getElementById('msgPrev'),
        next: document.getElementById('msgNext'),
        pageInfo: document.getElementById('msgPageInfo'),
    };

    function escapeHtml(value) {
        return String(value ?? '').replace(/[&<>"']/g, (ch) => ({
            '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
        }[ch]));
    }

    function formatTimestamp(msg) {
        if (msg.msg_date) {
            const pad = (n) => String(n ?? 0).padStart(2, '0');
            return `${msg.msg_date} ${pad(msg.msg_hour)}:${pad(msg.msg_minute)}:${pad(msg.msg_second)}`;
        }
        return msg.created_at || '';
    }

    function senderLabel(msg) {
        if (msg.is_bot) return 'Bot';
        if (msg.from_me) return 'Owner';
        return msg.sender_name || msg.sender_id || 'Unknown';
    }

    function updateSelectionUi() {
        const n = state.selected.size;
        els.deleteSelected.textContent = `Delete selected (${n})`;
        els.deleteSelected.disabled = n === 0;
        els.clearSelection.disabled = n === 0;
    }

    function rowHtml(msg) {
        const checked = state.selected.has(msg.id) ? 'checked' : '';
        const vector = msg.has_vector
            ? '<span class="msg-badge ok">vector</span>'
            : '<span class="msg-badge warn">no vector</span>';
        const score = msg.similarity !== undefined && msg.similarity !== null
            ? `<span class="msg-badge score">similarity ${Number(msg.similarity).toFixed(3)} &rarr; #${escapeHtml(msg.best_match_id)}</span>`
            : '';
        return `
            <div class="msg-row" data-id="${msg.id}">
                <input type="checkbox" class="msg-check" data-id="${msg.id}" ${checked} aria-label="Select message ${msg.id}">
                <div class="msg-meta msg-meta-col">
                    <div>${escapeHtml(formatTimestamp(msg))}</div>
                    <div>${escapeHtml(senderLabel(msg))}</div>
                    <div>#${msg.id} &middot; ${escapeHtml(msg.channel_id)}</div>
                </div>
                <div>
                    <div class="msg-content">${escapeHtml(msg.content)}</div>
                    <div class="msg-badges">${vector}${score}</div>
                </div>
                <div class="msg-del">
                    <button type="button" class="msg-btn danger msg-delete-one" data-id="${msg.id}">Delete</button>
                </div>
            </div>`;
    }

    function groupHtml(group, index) {
        const label = state.mode === 'similar' ? 'Similar group' : 'Duplicate group';
        const rows = group.messages.map(rowHtml).join('');
        return `
            <div class="msg-group">
                <div class="msg-group-header">
                    <span>${label} ${index + 1}</span>
                    <span>${group.count} message${group.count === 1 ? '' : 's'}</span>
                </div>
                ${rows}
            </div>`;
    }

    function renderResults(data) {
        const groups = data.groups || [];
        const messages = data.messages || [];
        state.groups = groups;

        if (state.mode === 'all') {
            els.results.innerHTML = messages.length
                ? messages.map(rowHtml).join('')
                : '<div class="glass-panel msg-empty">No messages match these filters.</div>';
        } else {
            els.results.innerHTML = groups.length
                ? groups.map(groupHtml).join('')
                : `<div class="glass-panel msg-empty">${state.mode === 'similar'
                    ? `No similar messages found at a similarity of ${state.threshold.toFixed(2)} or higher.`
                    : 'No duplicate messages found.'}</div>`;
        }

        els.keepNewest.style.display = state.mode === 'all' ? 'none' : '';
        const total = data.total || 0;
        const scanned = data.scanned ? ` (scanned the ${data.scanned} most recent vectors)` : '';
        const noun = state.mode === 'all' ? 'messages' : (state.mode === 'similar' ? 'similar groups' : 'duplicate groups');
        els.total.textContent = `${total} ${noun}${scanned}`;

        state.totalPages = Math.max(1, Math.ceil(total / PER_PAGE));
        els.pageInfo.textContent = `Page ${state.page} of ${state.totalPages}`;
        els.prev.disabled = state.page <= 1;
        els.next.disabled = state.page >= state.totalPages;
        updateSelectionUi();
    }

    function setLoading() {
        els.results.innerHTML = '<div class="glass-panel msg-empty">Loading…</div>';
    }

    function loadMessages() {
        setLoading();
        const params = new URLSearchParams({
            mode: state.mode,
            page: state.page,
            per_page: PER_PAGE,
            threshold: state.threshold.toFixed(2),
        });
        if (state.channel) params.set('channel_id', state.channel);
        if (state.query) params.set('q', state.query);

        fetch(`/api/messages?${params.toString()}`)
            .then((res) => res.json().then((body) => ({ ok: res.ok, body })))
            .then(({ ok, body }) => {
                if (!ok) throw new Error(body.error || 'Failed to load messages');
                populateChannels(body.channels || []);
                renderResults(body);
            })
            .catch((err) => {
                console.error(err);
                els.results.innerHTML = '<div class="glass-panel msg-empty">Could not load messages.</div>';
                showToast('Error loading messages.');
            });
    }

    function populateChannels(channels) {
        const current = els.channel.value;
        const options = ['<option value="">All channels</option>']
            .concat(channels.map((c) => `<option value="${escapeHtml(c)}">${escapeHtml(c)}</option>`));
        els.channel.innerHTML = options.join('');
        if (channels.includes(current)) els.channel.value = current;
    }

    function deleteIds(ids, confirmText) {
        if (!ids.length) return;
        if (!confirm(confirmText)) return;

        fetch('/api/messages/delete', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ ids }),
        })
            .then((res) => res.json().then((body) => ({ ok: res.ok, body })))
            .then(({ ok, body }) => {
                if (!ok) throw new Error(body.error || 'Delete failed');
                ids.forEach((id) => state.selected.delete(id));
                showToast(`Deleted ${body.deleted} message(s) and ${body.vectors_deleted} vector(s).`);
                loadMessages();
            })
            .catch((err) => {
                console.error(err);
                showToast('Error deleting messages.');
            });
    }

    function pageIds() {
        return Array.from(els.results.querySelectorAll('.msg-check')).map((cb) => Number(cb.dataset.id));
    }

    function setMode(mode) {
        state.mode = mode;
        state.page = 1;
        els.tabs.forEach((b) => b.classList.toggle('active', b.dataset.mode === mode));
        els.thresholdField.style.display = mode === 'similar' ? '' : 'none';
        loadMessages();
    }

    // Event wiring
    els.tabs.forEach((btn) => btn.addEventListener('click', () => setMode(btn.dataset.mode)));

    let searchTimer = null;
    els.search.addEventListener('input', () => {
        clearTimeout(searchTimer);
        searchTimer = setTimeout(() => {
            state.query = els.search.value.trim();
            state.page = 1;
            loadMessages();
        }, 300);
    });

    els.channel.addEventListener('change', () => {
        state.channel = els.channel.value;
        state.page = 1;
        loadMessages();
    });

    els.threshold.addEventListener('input', () => {
        els.thresholdValue.textContent = Number(els.threshold.value).toFixed(2);
    });
    els.threshold.addEventListener('change', () => {
        state.threshold = Number(els.threshold.value);
        state.page = 1;
        loadMessages();
    });

    els.prev.addEventListener('click', () => {
        if (state.page > 1) { state.page -= 1; loadMessages(); }
    });
    els.next.addEventListener('click', () => {
        if (state.page < state.totalPages) { state.page += 1; loadMessages(); }
    });

    els.results.addEventListener('change', (event) => {
        const cb = event.target.closest('.msg-check');
        if (!cb) return;
        const id = Number(cb.dataset.id);
        if (cb.checked) state.selected.add(id); else state.selected.delete(id);
        updateSelectionUi();
    });

    els.results.addEventListener('click', (event) => {
        const btn = event.target.closest('.msg-delete-one');
        if (!btn) return;
        const id = Number(btn.dataset.id);
        deleteIds([id], `Delete message #${id} and its embedding/vector? This cannot be undone.`);
    });

    els.selectPage.addEventListener('click', () => {
        pageIds().forEach((id) => state.selected.add(id));
        els.results.querySelectorAll('.msg-check').forEach((cb) => { cb.checked = true; });
        updateSelectionUi();
    });

    els.keepNewest.addEventListener('click', () => {
        // Groups list messages newest first, so everything after the first id is redundant.
        state.groups.forEach((g) => g.messages.slice(1).forEach((m) => state.selected.add(m.id)));
        els.results.querySelectorAll('.msg-check').forEach((cb) => {
            cb.checked = state.selected.has(Number(cb.dataset.id));
        });
        updateSelectionUi();
    });

    els.clearSelection.addEventListener('click', () => {
        state.selected.clear();
        els.results.querySelectorAll('.msg-check').forEach((cb) => { cb.checked = false; });
        updateSelectionUi();
    });

    els.deleteSelected.addEventListener('click', () => {
        const ids = Array.from(state.selected);
        deleteIds(ids, `Delete ${ids.length} message(s) together with their embeddings and vectors? This cannot be undone.`);
    });

    updateSelectionUi();
    loadMessages();
})();
