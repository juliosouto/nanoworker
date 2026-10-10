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

// ---------------------------------------------------------------------------
// Custom per-tool settings (schema-driven, rendered inside the gear modal)
// ---------------------------------------------------------------------------
function parseToolSettingsData() {
    const el = document.getElementById('toolSettingsData');
    if (!el) return {};
    try {
        return JSON.parse(el.textContent);
    } catch (e) {
        console.error('Failed to parse tool settings data:', e);
        return {};
    }
}

function renderCustomSettings(schema, values) {
    const container = document.getElementById('modalCustomSettings');
    const modalBox = document.querySelector('#toolSettingsModal > div');
    if (!container) return;
    container.innerHTML = '';

    if (modalBox) modalBox.style.maxWidth = '400px';
    if (!schema || !schema.length) return;

    (schema || []).forEach(field => {
        const wrap = document.createElement('div');
        wrap.style.cssText = 'margin-bottom: 16px;';

        const label = document.createElement('label');
        label.textContent = field.label || field.key;
        label.style.cssText = 'display: block; font-size: 0.95rem; margin-bottom: 8px; font-weight: 500;';
        wrap.appendChild(label);

        const current = (values && Object.prototype.hasOwnProperty.call(values, field.key))
            ? values[field.key]
            : field.default;

        if (field.type === 'multi_select') {
            const list = document.createElement('div');
            list.style.cssText = 'max-height: 150px; overflow-y: auto; border: 1px solid rgba(255,255,255,0.1); border-radius: 6px; padding: 8px; display: flex; flex-direction: column; gap: 6px;';
            (field.options || []).forEach(opt => {
                const row = document.createElement('label');
                row.style.cssText = 'display: flex; align-items: center; gap: 8px; font-size: 0.9rem; cursor: pointer;';
                const cb = document.createElement('input');
                cb.type = 'checkbox';
                cb.value = opt;
                cb.setAttribute('data-setting-key', field.key);
                cb.checked = Array.isArray(current) && current.includes(opt);
                cb.style.cursor = 'pointer';
                const span = document.createElement('span');
                span.textContent = opt;
                row.appendChild(cb);
                row.appendChild(span);
                list.appendChild(row);
            });
            wrap.appendChild(list);
        } else if (field.type === 'number') {
            const input = document.createElement('input');
            input.type = 'number';
            input.setAttribute('data-setting-key', field.key);
            if (field.min != null) input.min = field.min;
            if (field.max != null) input.max = field.max;
            input.value = current != null ? current : (field.default != null ? field.default : '');
            input.style.cssText = 'background: rgba(255,255,255,0.05); border: 1px solid rgba(255,255,255,0.1); color: var(--text-main); padding: 6px 10px; border-radius: 6px; outline: none; width: 100%; box-sizing: border-box;';
            wrap.appendChild(input);
        } else {
            const input = document.createElement('input');
            input.type = 'text';
            input.setAttribute('data-setting-key', field.key);
            input.value = current != null ? current : '';
            input.style.cssText = 'background: rgba(255,255,255,0.05); border: 1px solid rgba(255,255,255,0.1); color: var(--text-main); padding: 6px 10px; border-radius: 6px; outline: none; width: 100%; box-sizing: border-box;';
            wrap.appendChild(input);
        }

        container.appendChild(wrap);
    });

    if (modalBox) modalBox.style.maxWidth = '480px';
}

function collectCustomSettings() {
    const settings = {};
    const keys = new Set();
    document.querySelectorAll('#modalCustomSettings [data-setting-key]').forEach(el => {
        keys.add(el.getAttribute('data-setting-key'));
    });
    keys.forEach(key => {
        const els = Array.from(document.querySelectorAll(`#modalCustomSettings [data-setting-key="${key}"]`));
        const first = els[0];
        if (!first) return;
        if (first.type === 'checkbox') {
            settings[key] = els.filter(el => el.checked).map(el => el.value);
        } else if (first.type === 'number') {
            const n = parseInt(first.value, 10);
            if (!isNaN(n)) settings[key] = n;
        } else {
            settings[key] = first.value;
        }
    });
    return settings;
}

function openToolModal(btn) {
    const toolName = btn.getAttribute('data-tool');
    const allowDirect = btn.getAttribute('data-direct') === 'true';
    const allowGroup = btn.getAttribute('data-group') === 'true';

    document.getElementById('modalToolTitle').textContent = `Settings: ${toolName.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase())}`;
    document.getElementById('modalToolName').value = toolName;

    document.getElementById('modalDirectToggle').checked = allowDirect;
    document.getElementById('modalGroupToggle').checked = allowGroup;

    // Custom schema-driven settings (sources, topics, limits, ...) when the
    // tool declares them.
    const allData = parseToolSettingsData();
    const entry = allData[toolName];
    renderCustomSettings(entry ? entry.schema : null, entry ? entry.values : null);

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

    const payload = {
        tool_name: toolName,
        allow_others_from_direct_msgs: allowDirect,
        allow_others_from_group_msgs: allowGroup
    };

    // Custom schema-driven settings, if the modal rendered any.
    const customSettings = collectCustomSettings();
    if (Object.keys(customSettings).length > 0) {
        payload.settings = customSettings;
    }

    fetch('/api/settings/tools', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
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
