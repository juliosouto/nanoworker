function setupToggle(toggleId, knobId, permType) {
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
            savePermissionState(permType, e.target.checked);

            if (e.target.checked) {
                requestOsPermission(permType);
            }
        });
    }
}

function savePermissionState(permType, isEnabled) {
    const payload = {};
    payload[`perm_${permType}`] = isEnabled;

    fetch('/api/settings', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
    }).then(res => res.json()).then(data => {
        if (data.status === 'success') {
            console.log(`Saved ${permType}: ${isEnabled}`);
            showToast(`${permType} permission ${isEnabled ? 'enabled' : 'disabled'}`);
        } else {
            showToast(`Error saving ${permType} permission`);
        }
    }).catch(err => {
        console.error(err);
        showToast(`Error saving ${permType} permission`);
    });
}

function requestOsPermission(permType) {
    const osType = (window.APP_STATE && window.APP_STATE.osType) ? window.APP_STATE.osType : '';
    let endpoint = 'linux';
    if (osType === 'Darwin') {
        endpoint = 'macos';
    } else if (osType === 'Windows') {
        endpoint = 'windows';
    }
    
    fetch(`/api/permissions/request/${endpoint}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ permission: permType })
    }).then(res => res.json()).then(data => {
        if (data.status === 'success') {
            console.log(`OS prompt triggered for ${permType} on ${endpoint}`);
        } else {
            console.error(`Error requesting OS permission: ${data.error}`);
        }
    }).catch(err => console.error(err));
}

document.addEventListener('DOMContentLoaded', () => {
    setupToggle('terminalToggle', 'terminalToggleKnob', 'terminal');
    setupToggle('playwrightToggle', 'playwrightToggleKnob', 'playwright');
    setupToggle('safariToggle', 'safariToggleKnob', 'safari');
    setupToggle('fsToggle', 'fsToggleKnob', 'fs');
    setupToggle('calendarToggle', 'calendarToggleKnob', 'calendar');
    setupToggle('contactsToggle', 'contactsToggleKnob', 'contacts');
    setupToggle('photosToggle', 'photosToggleKnob', 'photos');
    setupToggle('icloudToggle', 'icloudToggleKnob', 'icloud');
    setupToggle('notesToggle', 'notesToggleKnob', 'notes');
    setupToggle('remindersToggle', 'remindersToggleKnob', 'reminders');
    setupToggle('mailToggle', 'mailToggleKnob', 'mail');
    setupToggle('messagesToggle', 'messagesToggleKnob', 'messages');
    setupToggle('systemDataToggle', 'systemDataToggleKnob', 'system_data');
    setupToggle('screenshotToggle', 'screenshotToggleKnob', 'screenshot');
    setupToggle('webSearchToggle', 'webSearchToggleKnob', 'web_search');
    setupToggle('toolCreatorToggle', 'toolCreatorToggleKnob', 'tool_creator');
});
