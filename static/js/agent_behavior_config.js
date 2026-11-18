// Toggle visual logic
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

document.addEventListener('DOMContentLoaded', () => {
    setupToggle('requireAtToggle', 'requireAtKnob');
    setupToggle('useRecipesToggle', 'useRecipesKnob');
    setupToggle('planBeforeExecutionToggle', 'planBeforeExecutionKnob');
    setupToggle('historyRagToggle', 'historyRagKnob');
    setupToggle('decisionModelToggle', 'decisionModelKnob');
    setupDecisionModel();

    const requireAtToggle = document.getElementById('requireAtToggle');
    if(requireAtToggle) requireAtToggle.addEventListener('change', autoSaveToggles);

    const useRecipesToggle = document.getElementById('useRecipesToggle');
    if(useRecipesToggle) useRecipesToggle.addEventListener('change', autoSaveToggles);

    const planBeforeExecutionToggle = document.getElementById('planBeforeExecutionToggle');
    if(planBeforeExecutionToggle) planBeforeExecutionToggle.addEventListener('change', autoSaveToggles);

    const historyRagToggle = document.getElementById('historyRagToggle');
    if(historyRagToggle) historyRagToggle.addEventListener('change', autoSaveToggles);

    const historyRagSearchType = document.getElementById('historyRagSearchType');
    if(historyRagSearchType) historyRagSearchType.addEventListener('change', () => {
        updateRagVisibility();
        autoSaveToggles();
    });

    ['historyRagK', 'historyRagFetchK', 'historyRagScoreThreshold', 'historyRagLambda'].forEach(id => {
        const el = document.getElementById(id);
        if(el) el.addEventListener('change', autoSaveToggles);
    });

    updateRagVisibility();

    document.getElementById('ragSourcesSave')?.addEventListener('click', saveRagSources);

    const slider = document.getElementById('autonomousModeSlider');
    const sliderValue = document.getElementById('autonomousModeValue');
    const minusBtn = document.getElementById('autonomousModeMinus');
    const plusBtn = document.getElementById('autonomousModePlus');

    const historySizeInput = document.getElementById('historySizeInput');
    const sliceMinusBtn = document.getElementById('sliceSizeMinus');
    const slicePlusBtn = document.getElementById('sliceSizePlus');

    if(slider) {
        slider.addEventListener('input', function() {
            if(sliderValue) sliderValue.textContent = this.value;
        });
        slider.addEventListener('change', autoSaveToggles);
    }

    if(historySizeInput) {
        historySizeInput.addEventListener('change', () => {
            sanitizeHistorySizeInput();
            autoSaveToggles();
        });
    }

    if(minusBtn) minusBtn.addEventListener('click', () => {
        if(slider) updateSlider(parseInt(slider.value) - 1);
    });

    if(plusBtn) plusBtn.addEventListener('click', () => {
        if(slider) updateSlider(parseInt(slider.value) + 1);
    });

    if(sliceMinusBtn) sliceMinusBtn.addEventListener('click', () => {
        if(historySizeInput) updateHistorySize(parseInt(historySizeInput.value) - 10);
    });

    if(slicePlusBtn) slicePlusBtn.addEventListener('click', () => {
        if(historySizeInput) updateHistorySize(parseInt(historySizeInput.value) + 10);
    });

    loadUserMemories();
});

function updateSlider(val) {
    const slider = document.getElementById('autonomousModeSlider');
    const sliderValue = document.getElementById('autonomousModeValue');
    if(!slider) return;
    let newVal = parseInt(val);
    if (isNaN(newVal)) return;
    if (newVal < 1) newVal = 1;
    if (newVal > 20) newVal = 20;
    slider.value = newVal;
    if(sliderValue) sliderValue.textContent = newVal;
    autoSaveToggles();
}

function sanitizeHistorySizeInput() {
    const historySizeInput = document.getElementById('historySizeInput');
    if(!historySizeInput) return;
    let newVal = parseInt(historySizeInput.value);
    if (isNaN(newVal)) newVal = 10000;
    if (newVal < 0) newVal = 0;
    if (newVal > 1000000) newVal = 1000000;
    historySizeInput.value = newVal;
}

function updateHistorySize(val) {
    const historySizeInput = document.getElementById('historySizeInput');
    if(!historySizeInput) return;
    let newVal = parseInt(val);
    if (isNaN(newVal)) return;
    if (newVal < 0) newVal = 0;
    if (newVal > 1000000) newVal = 1000000;
    historySizeInput.value = newVal;
    autoSaveToggles();
}

function updateRagVisibility() {
    const type = document.getElementById('historyRagSearchType')?.value;
    const thresholdRow = document.getElementById('historyRagScoreThresholdRow');
    const lambdaRow = document.getElementById('historyRagLambdaRow');
    if(thresholdRow) thresholdRow.style.display = (type === 'similarity_score_threshold') ? 'flex' : 'none';
    if(lambdaRow) lambdaRow.style.display = (type === 'mmr') ? 'flex' : 'none';
}

function saveRagSources() {
    const channels = Array.from(document.querySelectorAll('.rag-source:checked')).map(cb => cb.value);
    fetch('/api/settings', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ history_rag_allowed_channels: channels })
    })
    .then(res => {
        if (!res.ok) throw new Error('save failed');
        showToast(`Allowed sources saved (${channels.length} chat${channels.length === 1 ? '' : 's'}).`);
    })
    .catch(err => {
        console.error(err);
        showToast('Error saving allowed sources.');
    });
}

// --- Decision model (OpenRouter list) ---
let decisionModels = null;

function setupDecisionModel() {
    const toggle = document.getElementById('decisionModelToggle');
    const params = document.getElementById('decisionModelParams');
    const select = document.getElementById('decisionModelSelect');
    const search = document.getElementById('decisionModelSearch');
    if (!toggle || !params || !select) return;

    toggle.addEventListener('change', () => {
        params.style.display = toggle.checked ? 'flex' : 'none';
        if (toggle.checked && decisionModels === null) loadDecisionModels(false);
        autoSaveToggles();
    });
    select.addEventListener('change', saveDecisionModel);
    search?.addEventListener('input', renderDecisionModels);
    document.getElementById('decisionModelRefresh')?.addEventListener('click', () => loadDecisionModels(true));

    if (toggle.checked) loadDecisionModels(false);
}

function formatModelPrice(m) {
    if (m.free) return /\(free\)/i.test(m.name) ? '' : 'free';
    if (m.prompt_price == null) return '';
    // Decision models charge for input only.
    if (!m.completion_price) return `$${m.prompt_price} per 1M input`;
    return `$${m.prompt_price}/$${m.completion_price} per 1M`;
}

function loadDecisionModels(refresh) {
    const status = document.getElementById('decisionModelStatus');
    if (status) status.textContent = 'Loading the OpenRouter decision models...';
    fetch('/api/settings/decision_models' + (refresh ? '?refresh=1' : ''))
        .then(res => res.ok ? res.json() : Promise.reject(new Error('list failed')))
        .then(data => {
            decisionModels = data.models || [];
            const params = document.getElementById('decisionModelParams');
            if (params && data.selected !== undefined) params.dataset.selected = data.selected;
            renderDecisionModels();
        })
        .catch(err => {
            console.error(err);
            if (status) status.textContent = 'Could not load the OpenRouter decision models. Try Refresh.';
            const select = document.getElementById('decisionModelSelect');
            const selected = document.getElementById('decisionModelParams')?.dataset.selected || '';
            if (select) {
                select.innerHTML = '';
                select.add(new Option(selected || 'No model selected', selected));
            }
        });
}

function renderDecisionModels() {
    const select = document.getElementById('decisionModelSelect');
    const status = document.getElementById('decisionModelStatus');
    const selected = document.getElementById('decisionModelParams')?.dataset.selected || '';
    if (!select || decisionModels === null) return;
    const query = (document.getElementById('decisionModelSearch')?.value || '').trim().toLowerCase();
    const shown = decisionModels.filter(m =>
        !query || m.id.toLowerCase().includes(query) || m.name.toLowerCase().includes(query));

    select.innerHTML = '';
    select.add(new Option('Select a model...', ''));
    // The saved model stays selectable even when filtered out or delisted.
    if (selected && !shown.some(m => m.id === selected)) {
        select.add(new Option(selected, selected));
    }
    shown.forEach(m => {
        const price = formatModelPrice(m);
        select.add(new Option(price ? `${m.name} (${price})` : m.name, m.id));
    });
    select.value = selected;
    if (status) {
        const known = decisionModels.some(m => m.id === selected);
        status.textContent = !selected
            ? `${decisionModels.length} decision models available. Choose one: without a model every message goes to the full agent.`
            : known
                ? `Selected: ${selected} · ${decisionModels.length} decision models available`
                : `${selected} is not an OpenRouter decision model: messages go to the full agent until you choose one from the list.`;
        status.style.color = selected && !known ? '#f59e0b' : '';
    }
}

function saveDecisionModel() {
    const select = document.getElementById('decisionModelSelect');
    const params = document.getElementById('decisionModelParams');
    if (!select) return;
    const model = select.value;
    fetch('/api/settings', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ decision_model: model })
    })
    .then(res => {
        if (!res.ok) throw new Error('save failed');
        if (params) params.dataset.selected = model;
        renderDecisionModels();
        showToast(model ? `Decision model saved: ${model}` : 'Decision model cleared.');
    })
    .catch(err => {
        console.error(err);
        showToast('Error saving the decision model.');
    });
}

function autoSaveToggles() {
    const requireAtPrefix = document.getElementById('requireAtToggle')?.checked;
    const useRecipesAsTools = document.getElementById('useRecipesToggle')?.checked;
    const planBeforeExecution = document.getElementById('planBeforeExecutionToggle')?.checked;
    const decisionModelEnabled = document.getElementById('decisionModelToggle')?.checked;
    const autonomousMode = parseInt(document.getElementById('autonomousModeSlider')?.value) || 1;
    const historySizeMessages = parseInt(document.getElementById('historySizeInput')?.value);
    const historyRagEnabled = document.getElementById('historyRagToggle')?.checked;
    const historyRagSearchType = document.getElementById('historyRagSearchType')?.value || 'mmr';
    const historyRagK = parseInt(document.getElementById('historyRagK')?.value) || 3;
    const historyRagFetchK = parseInt(document.getElementById('historyRagFetchK')?.value) || 20;
    const historyRagScoreThreshold = parseFloat(document.getElementById('historyRagScoreThreshold')?.value);
    const historyRagLambda = parseFloat(document.getElementById('historyRagLambda')?.value);

    fetch('/api/settings', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            require_at_prefix: requireAtPrefix,
            use_recipes_as_tools: useRecipesAsTools,
            plan_before_execution: planBeforeExecution,
            decision_model_enabled: decisionModelEnabled,
            autonomous_mode: autonomousMode,
            history_size_messages: isNaN(historySizeMessages) ? 10000 : historySizeMessages,
            history_rag_enabled: historyRagEnabled,
            history_rag_search_type: historyRagSearchType,
            history_rag_k: historyRagK,
            history_rag_fetch_k: historyRagFetchK,
            history_rag_score_threshold: isNaN(historyRagScoreThreshold) ? 0.3 : historyRagScoreThreshold,
            history_rag_lambda: isNaN(historyRagLambda) ? 0.5 : historyRagLambda
        })
    });
}

function saveIdeSettings() {
    const idePrompt = document.getElementById('idePromptInput')?.value;
    if(idePrompt === undefined) return;
    fetch('/api/settings', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ide_prompt: idePrompt })
    }).then(res => res.json()).then(data => {
        if (data.status === 'success') {
            showToast('IDE settings saved successfully!');
        } else {
            showToast('Error saving IDE settings.');
        }
    });
}

// Fetch and render user memories
function loadUserMemories() {
    fetch('/api/user_memory')
        .then(res => res.json())
        .then(memories => {
            const container = document.getElementById('memoryListContainer');
            if (!container) return;
            container.innerHTML = '';
            
            if (memories.length === 0) {
                container.innerHTML = `
                    <div style="text-align: center; color: var(--text-muted); padding: 20px;" id="noMemoryMessage">
                        No memories stored yet.
                    </div>
                `;
                return;
            }
            
            memories.forEach(mem => {
                const item = document.createElement('div');
                item.style.display = 'flex';
                item.style.alignItems = 'center';
                item.style.justifyContent = 'space-between';
                item.style.padding = '10px 12px';
                item.style.borderRadius = '8px';
                item.style.background = 'rgba(255,255,255,0.05)';
                item.style.marginBottom = '8px';
                item.style.border = '1px solid rgba(255,255,255,0.05)';
                item.style.transition = 'all 0.2s ease';
                
                const span = document.createElement('span');
                span.style.fontSize = '0.9rem';
                span.style.color = 'var(--text-main)';
                span.style.wordBreak = 'break-word';
                span.style.marginRight = '12px';
                span.style.textAlign = 'left';
                span.textContent = mem.instruction;
                
                const btnContainer = document.createElement('div');
                btnContainer.style.display = 'flex';
                btnContainer.style.gap = '4px';
                btnContainer.style.alignItems = 'center';
                btnContainer.style.flexShrink = '0';
                
                const editBtn = document.createElement('button');
                editBtn.style.background = 'rgba(255,255,255,0.08)';
                editBtn.style.border = '1px solid rgba(255,255,255,0.1)';
                editBtn.style.color = 'var(--text-muted)';
                editBtn.style.cursor = 'pointer';
                editBtn.style.padding = '4px 8px';
                editBtn.style.borderRadius = '4px';
                editBtn.style.fontSize = '0.75rem';
                editBtn.style.fontWeight = '500';
                editBtn.style.transition = 'all 0.2s';
                editBtn.textContent = 'Edit';
                editBtn.addEventListener('click', () => {
                    enterEditMode(mem.id, mem.instruction, item);
                });
                
                const deleteBtn = document.createElement('button');
                deleteBtn.style.background = 'none';
                deleteBtn.style.border = 'none';
                deleteBtn.style.color = '#ef4444';
                deleteBtn.style.cursor = 'pointer';
                deleteBtn.style.padding = '4px 8px';
                deleteBtn.style.borderRadius = '4px';
                deleteBtn.style.fontSize = '0.75rem';
                deleteBtn.style.fontWeight = '500';
                deleteBtn.style.transition = 'all 0.2s';
                deleteBtn.textContent = 'Delete';
                deleteBtn.addEventListener('click', () => {
                    deleteUserMemory(mem.id, item);
                });
                
                btnContainer.appendChild(editBtn);
                btnContainer.appendChild(deleteBtn);
                
                item.appendChild(span);
                item.appendChild(btnContainer);
                container.appendChild(item);
            });
        });
}

function enterEditMode(id, currentInstruction, element) {
    element.innerHTML = `
        <div style="display: flex; width: 100%; gap: 8px; align-items: center;">
            <input type="text" id="editInput_${id}" 
                style="flex: 1; padding: 6px 10px; border-radius: 6px; background: rgba(0,0,0,0.4); border: 1px solid var(--border-color); color: white; font-family: inherit; font-size: 0.85rem;">
            <button id="saveBtn_${id}" style="background: #22c55e; border: none; color: white; cursor: pointer; padding: 6px 12px; border-radius: 6px; font-size: 0.8rem; font-weight: 500;">
                Save
            </button>
            <button id="cancelBtn_${id}" style="background: rgba(255,255,255,0.15); border: none; color: white; cursor: pointer; padding: 6px 12px; border-radius: 6px; font-size: 0.8rem; font-weight: 500;">
                Cancel
            </button>
        </div>
    `;
    
    const input = document.getElementById(`editInput_${id}`);
    const saveBtn = document.getElementById(`saveBtn_${id}`);
    const cancelBtn = document.getElementById(`cancelBtn_${id}`);
    
    if (input) {
        input.value = currentInstruction;
        input.focus();
        input.addEventListener('keydown', (e) => {
            if (e.key === 'Enter') saveUserMemory(id);
            if (e.key === 'Escape') loadUserMemories();
        });
    }
    
    if (saveBtn) {
        saveBtn.addEventListener('click', () => saveUserMemory(id));
    }
    
    if (cancelBtn) {
        cancelBtn.addEventListener('click', () => loadUserMemories());
    }
}

function saveUserMemory(id) {
    const input = document.getElementById(`editInput_${id}`);
    if (!input) return;
    const newInstruction = input.value.trim();
    if (!newInstruction) return;

    fetch(`/api/user_memory/${id}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ instruction: newInstruction })
    })
    .then(res => {
        if (res.ok) {
            loadUserMemories();
            showToast('Memory updated successfully!');
        } else {
            showToast('Failed to update memory.');
        }
    });
}

function escapeHtml(text) {
    return text
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#039;");
}

function addUserMemory() {
    const input = document.getElementById('newMemoryInput');
    if(!input) return;
    const instruction = input.value.trim();
    if (!instruction) return;
    
    fetch('/api/user_memory', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ instruction: instruction })
    })
    .then(res => {
        if (res.ok) {
            input.value = '';
            loadUserMemories();
            showToast('Memory added successfully!');
        } else {
            showToast('Failed to add memory.');
        }
    });
}

function deleteUserMemory(id, element) {
    if (!confirm('Are you sure you want to delete this memory?')) return;
    
    fetch(`/api/user_memory/${id}`, {
        method: 'DELETE'
    })
    .then(res => {
        if (res.ok) {
            element.style.opacity = '0';
            element.style.transform = 'scale(0.9)';
            setTimeout(() => {
                loadUserMemories();
            }, 200);
            showToast('Memory deleted successfully!');
        } else {
            showToast('Failed to delete memory.');
        }
    });
}
