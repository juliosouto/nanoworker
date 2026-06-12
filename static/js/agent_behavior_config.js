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
    setupToggle('showToolsResultsToggle', 'showToolsResultsKnob');

    const requireAtToggle = document.getElementById('requireAtToggle');
    if(requireAtToggle) requireAtToggle.addEventListener('change', autoSaveToggles);

    const useRecipesToggle = document.getElementById('useRecipesToggle');
    if(useRecipesToggle) useRecipesToggle.addEventListener('change', autoSaveToggles);

    const showToolsResultsToggle = document.getElementById('showToolsResultsToggle');
    if(showToolsResultsToggle) showToolsResultsToggle.addEventListener('change', autoSaveToggles);

    const slider = document.getElementById('autonomousModeSlider');
    const sliderValue = document.getElementById('autonomousModeValue');
    const minusBtn = document.getElementById('autonomousModeMinus');
    const plusBtn = document.getElementById('autonomousModePlus');

    const sliceSlider = document.getElementById('sliceSizeSlider');
    const sliceSliderValue = document.getElementById('sliceSizeValue');
    const sliceMinusBtn = document.getElementById('sliceSizeMinus');
    const slicePlusBtn = document.getElementById('sliceSizePlus');

    if(slider) {
        slider.addEventListener('input', function() {
            if(sliderValue) sliderValue.textContent = this.value;
        });
        slider.addEventListener('change', autoSaveToggles);
    }

    if(sliceSlider) {
        sliceSlider.addEventListener('input', function() {
            if(sliceSliderValue) sliceSliderValue.textContent = this.value;
        });
        sliceSlider.addEventListener('change', autoSaveToggles);
    }

    if(minusBtn) minusBtn.addEventListener('click', () => {
        if(slider) updateSlider(parseInt(slider.value) - 1);
    });

    if(plusBtn) plusBtn.addEventListener('click', () => {
        if(slider) updateSlider(parseInt(slider.value) + 1);
    });

    if(sliceMinusBtn) sliceMinusBtn.addEventListener('click', () => {
        if(sliceSlider) updateSliceSlider(parseInt(sliceSlider.value) - 50);
    });

    if(slicePlusBtn) slicePlusBtn.addEventListener('click', () => {
        if(sliceSlider) updateSliceSlider(parseInt(sliceSlider.value) + 50);
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

function updateSliceSlider(val) {
    const sliceSlider = document.getElementById('sliceSizeSlider');
    const sliceSliderValue = document.getElementById('sliceSizeValue');
    if(!sliceSlider) return;
    let newVal = parseInt(val);
    if (isNaN(newVal)) return;
    if (newVal < 200) newVal = 200;
    if (newVal > 2000) newVal = 2000;
    newVal = Math.round(newVal / 50) * 50;
    sliceSlider.value = newVal;
    if(sliceSliderValue) sliceSliderValue.textContent = newVal;
    autoSaveToggles();
}

function autoSaveToggles() {
    const requireAtPrefix = document.getElementById('requireAtToggle')?.checked;
    const useRecipesAsTools = document.getElementById('useRecipesToggle')?.checked;
    const showToolsResults = document.getElementById('showToolsResultsToggle')?.checked;
    const autonomousMode = parseInt(document.getElementById('autonomousModeSlider')?.value) || 1;
    const sliceSizeTokens = parseInt(document.getElementById('sliceSizeSlider')?.value) || 250;

    fetch('/api/settings', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            require_at_prefix: requireAtPrefix,
            use_recipes_as_tools: useRecipesAsTools,
            show_tools_results: showToolsResults,
            autonomous_mode: autonomousMode,
            message_slice_size_tokens: sliceSizeTokens
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
