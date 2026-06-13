function openSetupModal() {
    document.getElementById('setupModal').style.display = 'flex';
}

function closeSetupModal() {
    document.getElementById('setupModal').style.display = 'none';
    document.getElementById('setupForm').reset();
}

function closeConfirmModal() {
    document.getElementById('confirmSetupModal').style.display = 'none';
}

function submitSetup() {
    document.getElementById('confirmSetupModal').style.display = 'flex';
}

function executeSetup() {
    closeConfirmModal();

    const geminiKey = document.getElementById('setup_gemini_key').value;
    const openaiKey = document.getElementById('setup_openai_key').value;
    const groqKey = document.getElementById('setup_groq_key').value;
    const qwenKey = document.getElementById('setup_qwen_key').value;
    const openrouterKey = document.getElementById('setup_openrouter_key').value;

    const submitBtn = document.getElementById('setupSubmitBtn');
    const originalContent = submitBtn.innerHTML;
    submitBtn.disabled = true;
    submitBtn.innerHTML = '<span>Running...</span>';

    fetch('/api/setup', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json'
        },
        body: JSON.stringify({
            gemini_api_key: geminiKey || null,
            openai_api_key: openaiKey || null,
            groq_api_key: groqKey || null,
            qwen_api_key: qwenKey || null,
            openrouter_api_key: openrouterKey || null
        })
    })
        .then(response => response.json())
        .then(data => {
            submitBtn.disabled = false;
            submitBtn.innerHTML = originalContent;
            if (data.status === 'success') {
                showToast('Setup completed successfully! Re-initializing active configs.');
                closeSetupModal();
                setTimeout(() => {
                    window.location.reload();
                }, 1500);
            } else {
                showToast('Setup failed: ' + data.message);
            }
        })
        .catch(error => {
            submitBtn.disabled = false;
            submitBtn.innerHTML = originalContent;
            console.error('Error running setup:', error);
            showToast('An unexpected error occurred during setup.');
        });
}

function toggleLoginSystem(enabled) {
    if (!enabled) {
        // Show confirmation modal before disabling
        document.getElementById('confirmDisableLoginModal').style.display = 'flex';
        return;
    }
    executeLoginToggle(true);
}

function cancelDisableLogin() {
    document.getElementById('confirmDisableLoginModal').style.display = 'none';
    document.getElementById('loginToggle').checked = true; // revert visual toggle
}

function confirmDisableLogin() {
    document.getElementById('confirmDisableLoginModal').style.display = 'none';
    executeLoginToggle(false);
}

function executeLoginToggle(enabled) {
    fetch('/api/login/toggle', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ enabled: enabled })
    })
    .then(res => res.json())
    .then(data => {
        if(data.status === 'success') {
            const container = document.getElementById('loginTokenContainer');
            const display = document.getElementById('loginTokenDisplay');
            const modal = document.getElementById('loginSystemModal');
            const modalText = document.getElementById('loginModalText');
            const modalTokenArea = document.getElementById('loginModalTokenArea');
            const modalTokenDisplay = document.getElementById('loginModalTokenDisplay');

            if(enabled) {
                container.style.display = 'block';
                if(data.token) {
                    display.value = data.token;
                    modalTokenDisplay.value = data.token;
                }
                modalText.innerHTML = "The Login System is now <strong>ENABLED</strong>. You and other users will be required to provide the access token below to access the Web UI. <br><br>Please make sure to copy and save it in a secure place.";
                modalTokenArea.style.display = 'flex';
                modal.style.display = 'flex';
            } else {
                container.style.display = 'none';
                // We only show the success toast, no need for the info modal when disabling since we just had a confirmation modal
            }
            
            showToast(enabled ? 'Login system enabled' : 'Login system disabled');
        } else {
            showToast('Failed to toggle login system');
            document.getElementById('loginToggle').checked = !enabled;
        }
    })
    .catch(err => {
        console.error(err);
        showToast('Error toggling login system');
        document.getElementById('loginToggle').checked = !enabled;
    });
}

function closeLoginModal() {
    document.getElementById('loginSystemModal').style.display = 'none';
    
    // Hide token when closing modal
    const modalInput = document.getElementById('loginModalTokenDisplay');
    const modalIcon = document.getElementById('eyeIconModal');
    if (modalInput.type === 'text') {
        modalInput.type = 'password';
        modalIcon.innerHTML = '<path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"></path><circle cx="12" cy="12" r="3"></circle>';
    }
}

function toggleTokenVisibility(inputId, iconId) {
    const input = document.getElementById(inputId);
    const icon = document.getElementById(iconId);
    if (input.type === 'password') {
        input.type = 'text';
        icon.innerHTML = '<path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24"></path><line x1="1" y1="1" x2="23" y2="23"></line>';
    } else {
        input.type = 'password';
        icon.innerHTML = '<path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"></path><circle cx="12" cy="12" r="3"></circle>';
    }
}

function copyLoginModalToken() {
    const tokenInput = document.getElementById('loginModalTokenDisplay');
    const tempInput = document.createElement('input');
    document.body.appendChild(tempInput);
    tempInput.value = tokenInput.value;
    tempInput.select();
    document.execCommand('copy');
    document.body.removeChild(tempInput);
    showToast('Token copied to clipboard!');
}

function copyLoginToken() {
    const tokenInput = document.getElementById('loginTokenDisplay');
    tokenInput.select();
    tokenInput.setSelectionRange(0, 99999); 
    navigator.clipboard.writeText(tokenInput.value).then(() => {
        showToast('Token copied to clipboard!');
    }).catch(err => {
        console.error('Failed to copy text: ', err);
    });
}
