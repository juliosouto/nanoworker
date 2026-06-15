function setupToggle(toggleId, knobId, settingKey) {
    const toggle = document.getElementById(toggleId);
    const knob = document.getElementById(knobId);

    function updateVisual() {
        if (toggle && knob) {
            if (toggle.checked) {
                knob.style.transform = 'translateX(32px)';
                knob.previousElementSibling.style.backgroundColor = 'rgba(59, 130, 246, 0.6)';
            } else {
                knob.style.transform = 'translateX(0)';
                knob.previousElementSibling.style.backgroundColor = 'rgba(255,255,255,0.15)';
            }
        }
    }

    if (toggle) {
        updateVisual();
        toggle.addEventListener('change', (e) => {
            updateVisual();
            saveSetting(settingKey, e.target.checked);
        });
    }
}

function saveSetting(key, isEnabled) {
    const payload = {};
    payload[key] = isEnabled;

    fetch('/api/settings', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
    }).then(res => res.json()).then(data => {
        if (data.status === 'success') {
            showToast(`Setting ${key} ${isEnabled ? 'enabled' : 'disabled'}`);
        } else {
            showToast(`Error saving setting ${key}`);
        }
    }).catch(err => {
        console.error(err);
        showToast(`Error saving setting ${key}`);
    });
}

document.addEventListener('DOMContentLoaded', () => {
    setupToggle('doubleCheckToggle', 'doubleCheckToggleKnob', 'tool_creator_double_check');

    const whisperSelect = document.getElementById('whisperModelSelect');
    if (whisperSelect) {
        whisperSelect.addEventListener('change', (e) => {
            saveSetting('whisper_model', e.target.value);
        });
    }

    const maxDownloadInput = document.getElementById('maxDownloadSizeInput');
    if (maxDownloadInput) {
        let timeoutId;
        maxDownloadInput.addEventListener('input', (e) => {
            clearTimeout(timeoutId);
            timeoutId = setTimeout(() => {
                let val = parseInt(e.target.value);
                if (isNaN(val) || val < 1) {
                    val = 100;
                    e.target.value = 100;
                }
                saveSetting('max_download_size_mb', val.toString());
            }, 800);
        });
    }
});
