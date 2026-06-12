function setupToolToggle(toolName) {
    const toggle = document.getElementById(`toggle_${toolName}`);
    const knob = document.getElementById(`knob_${toolName}`);

    function updateVisual() {
        if (toggle && knob) {
            if (toggle.checked) {
                knob.style.transform = 'translateX(32px)';
                knob.previousElementSibling.style.backgroundColor = 'rgba(59, 130, 246, 0.6)'; // blue
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
            saveToolState(toolName, e.target.checked);
        });
    }
}

function saveToolState(toolName, isEnabled) {
    fetch('/api/settings/tools', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            tool_name: toolName,
            enabled: isEnabled
        })
    }).then(res => res.json()).then(data => {
        if (data.status === 'success') {
            showToast(`Tool ${toolName} ${isEnabled ? 'enabled' : 'disabled'}`);
        } else {
            showToast(`Error saving ${toolName}`);
        }
    }).catch(err => {
        console.error(err);
        showToast(`Error saving ${toolName}`);
    });
}

function updateModalVisuals() {
    ['modalDirectToggle', 'modalGroupToggle'].forEach(id => {
        const toggle = document.getElementById(id);
        if(!toggle) return;
        const knob = toggle.nextElementSibling.nextElementSibling;
        const slider = toggle.nextElementSibling;
        if (toggle.checked) {
            knob.style.transform = 'translateX(24px)';
            slider.style.backgroundColor = 'rgba(59, 130, 246, 0.6)';
        } else {
            knob.style.transform = 'translateX(0)';
            slider.style.backgroundColor = 'rgba(255,255,255,0.15)';
        }
    });
}

function openToolModal(btn) {
    const toolName = btn.getAttribute('data-tool');
    const allowDirect = btn.getAttribute('data-direct') === 'true';
    const allowGroup = btn.getAttribute('data-group') === 'true';

    document.getElementById('modalToolTitle').textContent = `Settings: ${toolName.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase())}`;
    document.getElementById('modalToolName').value = toolName;
    
    document.getElementById('modalDirectToggle').checked = allowDirect;
    document.getElementById('modalGroupToggle').checked = allowGroup;
    
    updateModalVisuals();
    
    const modal = document.getElementById('toolSettingsModal');
    modal.style.display = 'flex';
    // Add current button reference so we can update its data attributes later
    modal.dataset.triggerBtnId = toolName; 
}

function closeToolModal() {
    const modal = document.getElementById('toolSettingsModal');
    if(modal) modal.style.display = 'none';
}

function saveToolModal() {
    const toolName = document.getElementById('modalToolName').value;
    const allowDirect = document.getElementById('modalDirectToggle').checked;
    const allowGroup = document.getElementById('modalGroupToggle').checked;

    fetch('/api/settings/tools', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            tool_name: toolName,
            allow_others_from_direct_msgs: allowDirect,
            allow_others_from_group_msgs: allowGroup
        })
    }).then(res => res.json()).then(data => {
        if (data.status === 'success') {
            showToast(`Settings for ${toolName} saved`);
            // Update button data attributes
            const btn = document.querySelector(`.tool-settings-btn[data-tool="${toolName}"]`);
            if(btn) {
                btn.setAttribute('data-direct', allowDirect ? 'true' : 'false');
                btn.setAttribute('data-group', allowGroup ? 'true' : 'false');
            }
            closeToolModal();
        } else {
            showToast(`Error saving settings`);
        }
    }).catch(err => {
        console.error(err);
        showToast(`Error saving settings`);
    });
}

function openDeleteModal(btn) {
    const toolName = btn.getAttribute('data-tool');
    document.getElementById('deleteModalToolName').value = toolName;
    document.getElementById('deleteModalToolTitle').textContent = toolName;
    const modal = document.getElementById('deleteToolModal');
    modal.style.display = 'flex';
}

function closeDeleteModal() {
    const modal = document.getElementById('deleteToolModal');
    if(modal) modal.style.display = 'none';
}

function confirmDeleteTool() {
    const toolName = document.getElementById('deleteModalToolName').value;
    const deleteBtn = document.querySelector(`#deleteToolModal button[onclick="confirmDeleteTool()"]`);
    const originalText = deleteBtn.textContent;
    deleteBtn.textContent = 'Deleting...';
    deleteBtn.disabled = true;
    
    fetch(`/api/settings/tools/${toolName}`, {
        method: 'DELETE'
    }).then(res => res.json()).then(data => {
        if (data.status === 'success') {
            showToast(`Tool ${toolName} successfully deleted`);
            closeDeleteModal();
            // Remove the card from the DOM
            const btn = document.querySelector(`.tool-delete-btn[data-tool="${toolName}"]`);
            if(btn) {
                const card = btn.closest('.tool-card');
                if (card) {
                    card.remove();
                }
            }
        } else {
            showToast(data.message || `Error deleting tool`);
        }
    }).catch(err => {
        console.error(err);
        showToast(`Error deleting tool`);
    }).finally(() => {
        deleteBtn.textContent = originalText;
        deleteBtn.disabled = false;
    });
}

document.addEventListener('DOMContentLoaded', () => {
    // Close tool modal on click outside
    const toolModal = document.getElementById('toolSettingsModal');
    if(toolModal) {
        toolModal.addEventListener('click', function(e) {
            if (e.target === this) {
                closeToolModal();
            }
        });
    }

    // Close delete modal on click outside
    const deleteModal = document.getElementById('deleteToolModal');
    if(deleteModal) {
        deleteModal.addEventListener('click', function(e) {
            if (e.target === this) {
                closeDeleteModal();
            }
        });
    }

    // Initialize all toggles dynamically
    document.querySelectorAll('input[id^="toggle_"]').forEach(toggle => {
        const toolName = toggle.id.replace('toggle_', '');
        setupToolToggle(toolName);
    });

    // Search functionality
    const searchInput = document.getElementById('toolSearchInput');
    if (searchInput) {
        searchInput.addEventListener('input', function (e) {
            const searchTerm = e.target.value.toLowerCase();

            document.querySelectorAll('.tool-section').forEach(section => {
                let hasVisibleTools = false;

                const sectionTitleEl = section.querySelector('.section-title');
                const sectionTitle = sectionTitleEl ? sectionTitleEl.textContent.toLowerCase() : '';
                const matchSection = sectionTitle.includes(searchTerm);

                section.querySelectorAll('.tool-card').forEach(card => {
                    const title = card.querySelector('h3').textContent.toLowerCase();
                    const desc = card.querySelector('small').textContent.toLowerCase();

                    if (matchSection || title.includes(searchTerm) || desc.includes(searchTerm)) {
                        card.style.display = 'flex';
                        hasVisibleTools = true;
                    } else {
                        card.style.display = 'none';
                    }
                });

                if (hasVisibleTools) {
                    section.style.display = 'block';
                } else {
                    section.style.display = 'none';
                }
            });
        });
    }
});
