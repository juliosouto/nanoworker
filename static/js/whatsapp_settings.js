let qrcode = null;

function setWaStatus(text, color) {
    const badge = document.getElementById('status-badge');
    if(badge) {
        badge.innerText = text;
        badge.style.backgroundColor = color;
    }
}

function logoutWhatsApp() {
    if (confirm("Are you sure you want to disconnect WhatsApp?")) {
        fetch('/api/whatsapp/logout', { method: 'POST' })
            .then(() => window.location.reload());
    }
}

function restartWhatsApp() {
    if (confirm("Are you sure you want to force restart the WhatsApp service?")) {
        const btn = document.getElementById('restart-wa-btn');
        if(!btn) return;
        const originalText = btn.innerText;
        btn.innerText = 'Restarting...';
        btn.disabled = true;
        fetch('/api/whatsapp/restart', { method: 'POST' })
            .then(res => res.json())
            .then(res => {
                if (res.status === 'success') {
                    alert('Service restarted successfully!');
                } else {
                    alert('Failed to restart: ' + res.message);
                }
            })
            .catch(err => {
                alert('Network error');
            })
            .finally(() => {
                btn.innerText = originalText;
                btn.disabled = false;
            });
    }
}

function setupToggle(toggleId, knobId) {
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
        toggle.addEventListener('change', updateVisual);
    }
}

function updateAllowedFieldsState() {
    const allowMentions = document.getElementById('allow-mentions');
    const allowedFrom = document.getElementById('allowed-from');
    const allowedTo = document.getElementById('allowed-to');
    if (allowMentions) {
        const isHidden = allowMentions.checked;
        
        if (allowedFrom && allowedFrom.parentElement) {
            allowedFrom.parentElement.style.display = isHidden ? 'none' : 'block';
            allowedFrom.disabled = isHidden;
        }
        if (allowedTo && allowedTo.parentElement) {
            allowedTo.parentElement.style.display = isHidden ? 'none' : 'block';
            allowedTo.disabled = isHidden;
        }
    }
}

document.addEventListener('DOMContentLoaded', () => {
    const connectWaBtn = document.getElementById('connect-wa-btn');
    if (connectWaBtn) {
        connectWaBtn.onclick = () => {
            connectWaBtn.style.display = 'none';
            setWaStatus('Generating QR Code...', 'rgba(245, 158, 11, 0.2)'); // Amber

            const eventSource = new EventSource('/api/whatsapp/auth-stream');

            eventSource.onmessage = function (event) {
                const data = JSON.parse(event.data);

                if (data.type === 'WHATSAPP_AUTH_QR') {
                    setWaStatus('Waiting for scan...', 'rgba(59, 130, 246, 0.2)'); // Blue
                    document.getElementById('qr-container').style.display = 'flex';

                    if (!qrcode) {
                        qrcode = new QRCode(document.getElementById("qrcode"), {
                            text: data.qr,
                            width: 256,
                            height: 256,
                            colorDark: "#000000",
                            colorLight: "#ffffff",
                            correctLevel: QRCode.CorrectLevel.L
                        });
                    } else {
                        qrcode.clear();
                        qrcode.makeCode(data.qr);
                    }
                } else if (data.type === 'WHATSAPP_AUTH') {
                    if (data.status === 'success') {
                        setWaStatus('Connected Successfully!', 'rgba(16, 185, 129, 0.2)'); // Green
                        document.getElementById('qr-container').style.display = 'none';
                        eventSource.close();
                        setTimeout(() => window.location.reload(), 1500);
                    } else {
                        setWaStatus('Connection Failed: ' + data.error, 'rgba(239, 68, 68, 0.2)'); // Red
                        if (connectWaBtn) connectWaBtn.style.display = 'inline-block';
                        document.getElementById('qr-container').style.display = 'none';
                        eventSource.close();
                    }
                }
            };

            eventSource.onerror = function (err) {
                console.error("SSE Error:", err);
                setWaStatus('Connection Error', 'rgba(239, 68, 68, 0.2)');
                if (connectWaBtn) connectWaBtn.style.display = 'inline-block';
                eventSource.close();
            };
        };
    }

    setupToggle('bot-enabled', 'botToggleKnob');
    setupToggle('allow-mentions', 'mentionsToggleKnob');
    setupToggle('allow-audio-mentions', 'audioMentionsToggleKnob');

    const mentionsToggle = document.getElementById('allow-mentions');
    if (mentionsToggle) {
        mentionsToggle.addEventListener('change', updateAllowedFieldsState);
        updateAllowedFieldsState(); // Run initially
    }

    const waConfigForm = document.getElementById('wa-config-form');
    if (waConfigForm) {
        waConfigForm.addEventListener('submit', function (e) {
            e.preventDefault();
            const data = {
                bot_enabled: document.getElementById('bot-enabled').checked,
                allow_mentions: document.getElementById('allow-mentions').checked,
                allow_audio_mentions: document.getElementById('allow-audio-mentions').checked,
                allowed_from: document.getElementById('allowed-from').value,
                allowed_to: document.getElementById('allowed-to').value,
                rate_limit_per_minute: document.getElementById('rate-limit').value
            };

            const btn = document.querySelector('button[form="wa-config-form"]') || this.querySelector('button[type="submit"]');
            const originalText = btn.innerText;
            btn.innerText = 'Saving...';
            btn.disabled = true;

            fetch('/api/whatsapp/config', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(data)
            })
                .then(res => res.json())
                .then(res => {
                    if (res.status === 'success') {
                        btn.innerText = 'Saved!';
                        setTimeout(() => { btn.innerText = originalText; btn.disabled = false; }, 2000);
                    } else {
                        alert('Error saving configuration');
                        btn.innerText = originalText;
                        btn.disabled = false;
                    }
                })
                .catch(err => {
                    console.error(err);
                    alert('Network error');
                    btn.innerText = originalText;
                    btn.disabled = false;
                });
        });
    }
});
