function toggleJobStatus(jobId, checkbox) {
    const toggleBg = checkbox.nextElementSibling;
    const toggleKnob = toggleBg.nextElementSibling;
    
    fetch(`/api/cron/${jobId}/toggle`, {
        method: 'POST'
    })
    .then(res => res.json())
    .then(data => {
        if (data.status === 'success') {
            if (data.is_active) {
                toggleBg.style.backgroundColor = 'rgba(16, 185, 129, 0.6)';
                toggleKnob.style.transform = 'translateX(24px)';
            } else {
                toggleBg.style.backgroundColor = 'rgba(255,255,255,0.15)';
                toggleKnob.style.transform = 'translateX(0)';
            }
            showToast('Cron job status updated!');
        } else {
            showToast('Error updating job status.');
            // Revert visual state
            checkbox.checked = !checkbox.checked;
        }
    })
    .catch(err => {
        console.error(err);
        showToast('Error communicating with server.');
        checkbox.checked = !checkbox.checked;
    });
}

function deleteJob(jobId) {
    if (!confirm('Are you sure you want to delete this cron job?')) {
        return;
    }

    fetch(`/api/cron/${jobId}`, {
        method: 'DELETE'
    })
    .then(res => res.json())
    .then(data => {
        if (data.status === 'success') {
            showToast('Cron job deleted successfully!');
            setTimeout(() => window.location.reload(), 1000);
        } else {
            showToast('Error deleting job.');
        }
    })
    .catch(err => {
        console.error(err);
        showToast('Error communicating with server.');
    });
}

function saveCronPreferences() {
    const payload = {
        cron_pref_1: document.getElementById('cronPref1')?.value || '',
        cron_pref_2: document.getElementById('cronPref2')?.value || '',
        cron_pref_3: document.getElementById('cronPref3')?.value || '',
        cron_pref_4: document.getElementById('cronPref4')?.value || '',
        cron_pref_5: document.getElementById('cronPref5')?.value || '',
    };

    fetch('/api/cron/preferences', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
    })
    .then(res => res.json())
    .then(data => {
        if (data.status === 'success') {
            showToast('Cron worker preferences saved successfully!');
        } else {
            showToast('Error saving preferences.');
        }
    })
    .catch(err => {
        console.error(err);
        showToast('Error communicating with server.');
    });
}

let editingCronJobId = null;

function updateCronKind() {
    const once = document.querySelector('input[name="cronKind"][value="once"]').checked;
    document.getElementById('cronExpression').style.display = once ? 'none' : '';
    document.getElementById('cronRunAt').style.display = once ? '' : 'none';
    document.querySelector('.cron-hint').style.display = once ? 'none' : '';
}

function openCronModal(jobId = null) {
    const job = jobId ? cronJobs.find(j => j.id === jobId) : null;
    editingCronJobId = job ? job.id : null;
    document.getElementById('cronModalTitle').textContent = job ? 'Edit cron job' : 'New cron job';
    document.getElementById('cronChatField').style.display = job ? 'none' : '';
    document.getElementById('cronActiveField').style.display = job ? '' : 'none';
    document.getElementById('cronError').textContent = '';

    const once = job ? !job.cron_expression : false;
    document.querySelector(`input[name="cronKind"][value="${once ? 'once' : 'cron'}"]`).checked = true;
    document.getElementById('cronDescription').value = job ? job.description : '';
    document.getElementById('cronContent').value = job ? job.content : '';
    document.getElementById('cronScript').value = job ? job.script : '';
    document.getElementById('cronExpression').value = job ? job.cron_expression : '';
    document.getElementById('cronRunAt').value = once ? job.next_run.slice(0, 16).replace(' ', 'T') : '';
    document.getElementById('cronMaxExecutions').value = job && job.max_executions ? job.max_executions : '';
    document.getElementById('cronActive').checked = job ? job.is_active : true;
    updateCronKind();

    document.getElementById('cronModal').style.display = 'flex';
    document.getElementById('cronDescription').focus();
}

function closeCronModal() {
    document.getElementById('cronModal').style.display = 'none';
}

function saveCronJob() {
    const once = document.querySelector('input[name="cronKind"][value="once"]').checked;
    const body = {
        description: document.getElementById('cronDescription').value,
        content: document.getElementById('cronContent').value,
        script: document.getElementById('cronScript').value,
        cron_expression: once ? '' : document.getElementById('cronExpression').value.trim(),
        next_run: once ? document.getElementById('cronRunAt').value : '',
        max_executions: document.getElementById('cronMaxExecutions').value,
    };
    let url = '/api/cron';
    let method = 'POST';
    if (editingCronJobId) {
        url = `/api/cron/${editingCronJobId}`;
        method = 'PUT';
        body.is_active = document.getElementById('cronActive').checked;
    } else {
        body.session_id = document.getElementById('cronChat').value;
    }

    const saveBtn = document.getElementById('cronSaveBtn');
    saveBtn.disabled = true;
    fetch(url, {
        method: method,
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body)
    })
    .then(res => res.json().then(data => ({ ok: res.ok, data })))
    .then(({ ok, data }) => {
        if (ok && data.status === 'success') {
            showToast(editingCronJobId ? 'Cron job updated!' : 'Cron job created!');
            setTimeout(() => window.location.reload(), 600);
        } else {
            document.getElementById('cronError').textContent = data.error || 'Error saving the cron job.';
            saveBtn.disabled = false;
        }
    })
    .catch(err => {
        console.error(err);
        document.getElementById('cronError').textContent = 'Error communicating with server.';
        saveBtn.disabled = false;
    });
}

document.addEventListener('keydown', e => {
    if (e.key === 'Escape') closeCronModal();
});
