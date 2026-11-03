let currentEditWorkerId = null;
let workerToDeleteId = null;

// Workers saved before thinking levels existed only have thinking_enabled.
function workerThinkingLevel(worker) {
    return worker.thinking_level || (worker.thinking_enabled ? 'medium' : 'disabled');
}

// Ordered: the first quantization is the preferred one.
let selectedQuantizations = [];

function workerQuantizations(worker) {
    try {
        const list = JSON.parse(worker.quantizations || '[]');
        return Array.isArray(list) ? list : [];
    } catch (e) {
        return [];
    }
}

function setQuantizations(list) {
    selectedQuantizations = list.slice();
    renderQuantizations();
}

function renderQuantizations() {
    const selected = document.getElementById('quantizationSelected');
    const available = document.getElementById('quantizationAvailable');
    if (!selected || !available) return;
    selected.innerHTML = '';
    available.innerHTML = '';

    if (!selectedQuantizations.length) {
        const empty = document.createElement('span');
        empty.className = 'quant-empty';
        empty.innerText = 'Any (OpenRouter only). Click the tags below in order of preference; drag to reorder.';
        selected.appendChild(empty);
    }
    selectedQuantizations.forEach((q, index) => {
        const tag = document.createElement('span');
        tag.className = 'quant-tag';
        tag.draggable = true;
        tag.dataset.index = index;
        tag.innerHTML = `<span class="quant-rank">${index + 1}</span>${q}`;
        const remove = document.createElement('button');
        remove.type = 'button';
        remove.className = 'quant-remove';
        remove.title = 'Remove';
        remove.innerText = '×';
        remove.onclick = () => setQuantizations(selectedQuantizations.filter(x => x !== q));
        tag.appendChild(remove);
        tag.addEventListener('dragstart', e => {
            e.dataTransfer.setData('text/plain', String(index));
            tag.classList.add('dragging');
        });
        tag.addEventListener('dragend', () => tag.classList.remove('dragging'));
        tag.addEventListener('dragover', e => e.preventDefault());
        tag.addEventListener('drop', e => {
            e.preventDefault();
            const from = parseInt(e.dataTransfer.getData('text/plain'), 10);
            if (isNaN(from) || from === index) return;
            const list = selectedQuantizations.slice();
            const [moved] = list.splice(from, 1);
            list.splice(index, 0, moved);
            setQuantizations(list);
        });
        selected.appendChild(tag);
    });

    (window.APP_STATE.quantizations || [])
        .filter(q => !selectedQuantizations.includes(q))
        .forEach(q => {
            const tag = document.createElement('span');
            tag.className = 'quant-tag';
            tag.title = 'Add';
            tag.innerText = '+ ' + q;
            tag.onclick = () => setQuantizations([...selectedQuantizations, q]);
            available.appendChild(tag);
        });
}

function openWorkerModal() {
    document.getElementById('workerModal').style.display = 'flex';
}

function closeWorkerModal() {
    document.getElementById('workerModal').style.display = 'none';
    document.getElementById('workerForm').reset();
    document.getElementById('is_default').checked = false;
    document.getElementById('thinking_level').value = 'disabled';
    document.getElementById('tools_enabled').checked = true;
    document.getElementById('show_tools_results').checked = false;
    document.getElementById('worker_temperature').value = '';
    setQuantizations([]);
    document.getElementById('modalTitle').innerText = 'Add New Worker';
    currentEditWorkerId = null;
}

function editWorkerById(id) {
    if (!window.APP_STATE || !window.APP_STATE.registeredWorkers) return;
    const worker = window.APP_STATE.registeredWorkers.find(w => w.id === id);
    if (worker) {
        currentEditWorkerId = worker.id;
        document.getElementById('worker_name').value = worker.worker_name;
        document.getElementById('worker_model').value = worker.worker_model;
        document.getElementById('worker_instructions').value = worker.worker_instructions || '';
        document.getElementById('worker_temperature').value = worker.temperature == null ? '' : worker.temperature;
        document.getElementById('is_default').checked = !!worker.is_default;
        document.getElementById('thinking_level').value = workerThinkingLevel(worker);
        setQuantizations(workerQuantizations(worker));
        document.getElementById('tools_enabled').checked = worker.tools_enabled === undefined ? true : !!worker.tools_enabled;
        document.getElementById('show_tools_results').checked = worker.show_tools_results === undefined ? true : !!worker.show_tools_results;
        document.getElementById('modalTitle').innerText = 'Edit Worker';
        openWorkerModal();
    } else {
        showToast('Worker not found.');
    }
}

function duplicateWorkerById(id) {
    if (!window.APP_STATE || !window.APP_STATE.registeredWorkers) return;
    const worker = window.APP_STATE.registeredWorkers.find(w => w.id === id);
    if (worker) {
        currentEditWorkerId = null;
        // The name is how users mention a worker, so the copy starts without
        // one; it is never the default either (only one worker can be).
        document.getElementById('worker_name').value = '';
        document.getElementById('worker_model').value = worker.worker_model;
        document.getElementById('worker_instructions').value = worker.worker_instructions || '';
        document.getElementById('worker_temperature').value = worker.temperature == null ? '' : worker.temperature;
        document.getElementById('is_default').checked = false;
        document.getElementById('thinking_level').value = workerThinkingLevel(worker);
        setQuantizations(workerQuantizations(worker));
        document.getElementById('tools_enabled').checked = worker.tools_enabled === undefined ? true : !!worker.tools_enabled;
        document.getElementById('show_tools_results').checked = worker.show_tools_results === undefined ? true : !!worker.show_tools_results;
        document.getElementById('modalTitle').innerText = 'Duplicate Worker';
        openWorkerModal();
        document.getElementById('worker_name').focus();
    } else {
        showToast('Worker not found for duplication.');
    }
}

function saveWorker() {
    const payload = {
        worker_name: document.getElementById('worker_name').value,
        worker_model: document.getElementById('worker_model').value,
        worker_instructions: document.getElementById('worker_instructions').value,
        temperature: document.getElementById('worker_temperature').value === '' ? null : parseFloat(document.getElementById('worker_temperature').value),
        is_default: document.getElementById('is_default').checked,
        thinking_level: document.getElementById('thinking_level').value,
        quantizations: selectedQuantizations,
        tools_enabled: document.getElementById('tools_enabled').checked,
        show_tools_results: document.getElementById('show_tools_results').checked
    };

    if (!payload.worker_name || !payload.worker_model) {
        showToast('Worker name and model are required.');
        return;
    }

    const method = currentEditWorkerId ? 'PUT' : 'POST';
    const url = currentEditWorkerId ? `/api/workers/${currentEditWorkerId}` : '/api/workers';

    fetch(url, {
        method: method,
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
    }).then(res => res.json()).then(data => {
        if (data.status === 'success') {
            showToast(currentEditWorkerId ? 'Worker updated successfully!' : 'Worker added successfully!');
            closeWorkerModal();
            setTimeout(() => window.location.reload(), 800);
        } else {
            showToast('Error saving worker: ' + (data.error || 'Unknown error'));
        }
    }).catch(err => {
        console.error(err);
        showToast('Error saving worker');
    });
}

function deleteWorker(id, name) {
    workerToDeleteId = id;
    document.getElementById('deleteWorkerNameText').innerText = `"${name}"`;
    document.getElementById('deleteWorkerModal').style.display = 'flex';
}

function closeDeleteModal() {
    document.getElementById('deleteWorkerModal').style.display = 'none';
    workerToDeleteId = null;
}

function confirmDeleteWorker() {
    if (!workerToDeleteId) return;

    fetch(`/api/workers/${workerToDeleteId}`, {
        method: 'DELETE'
    }).then(res => res.json()).then(data => {
        if (data.status === 'success') {
            showToast('Worker deleted successfully!');
            closeDeleteModal();
            setTimeout(() => window.location.reload(), 800);
        } else {
            showToast('Error deleting worker: ' + (data.error || 'Unknown error'));
        }
    }).catch(err => {
        console.error(err);
        showToast('Error deleting worker');
    });
}

document.addEventListener('DOMContentLoaded', renderQuantizations);
