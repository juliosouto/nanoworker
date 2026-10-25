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
