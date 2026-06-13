let currentEditWorkerId = null;
let workerToDeleteId = null;

function openWorkerModal() {
    document.getElementById('workerModal').style.display = 'flex';
}

function closeWorkerModal() {
    document.getElementById('workerModal').style.display = 'none';
    document.getElementById('workerForm').reset();
    document.getElementById('is_default').checked = false;
    document.getElementById('thinking_enabled').checked = false;
    document.getElementById('tools_enabled').checked = true;
    document.getElementById('show_tools_results').checked = true;
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
        document.getElementById('is_default').checked = !!worker.is_default;
        document.getElementById('thinking_enabled').checked = !!worker.thinking_enabled;
        document.getElementById('tools_enabled').checked = worker.tools_enabled === undefined ? true : !!worker.tools_enabled;
        document.getElementById('show_tools_results').checked = worker.show_tools_results === undefined ? true : !!worker.show_tools_results;
        document.getElementById('modalTitle').innerText = 'Edit Worker';
        openWorkerModal();
    } else {
        showToast('Worker not found.');
    }
}

function saveWorker() {
    const payload = {
        worker_name: document.getElementById('worker_name').value,
        worker_model: document.getElementById('worker_model').value,
        worker_instructions: document.getElementById('worker_instructions').value,
        is_default: document.getElementById('is_default').checked,
        thinking_enabled: document.getElementById('thinking_enabled').checked,
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
