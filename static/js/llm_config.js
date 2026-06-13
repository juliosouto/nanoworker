document.addEventListener('DOMContentLoaded', () => {
    if(window.APP_STATE && window.APP_STATE.llmPref1) {
        const p1 = document.getElementById('llmPref1');
        const p2 = document.getElementById('llmPref2');
        const p3 = document.getElementById('llmPref3');
        const p4 = document.getElementById('llmPref4');
        const p5 = document.getElementById('llmPref5');
        
        if (p1) p1.value = window.APP_STATE.llmPref1;
        if (p2) p2.value = window.APP_STATE.llmPref2;
        if (p3) p3.value = window.APP_STATE.llmPref3;
        if (p4) p4.value = window.APP_STATE.llmPref4;
        if (p5) p5.value = window.APP_STATE.llmPref5;
    }
});

function saveSettings() {
    const llmPref1 = document.getElementById('llmPref1')?.value;
    const llmPref2 = document.getElementById('llmPref2')?.value;
    const llmPref3 = document.getElementById('llmPref3')?.value;
    const llmPref4 = document.getElementById('llmPref4')?.value;
    const llmPref5 = document.getElementById('llmPref5')?.value;

    const payload = {};
    if (llmPref1 !== undefined) payload.llm_pref_1 = llmPref1;
    if (llmPref2 !== undefined) payload.llm_pref_2 = llmPref2;
    if (llmPref3 !== undefined) payload.llm_pref_3 = llmPref3;
    if (llmPref4 !== undefined) payload.llm_pref_4 = llmPref4;
    if (llmPref5 !== undefined) payload.llm_pref_5 = llmPref5;

    fetch('/api/settings', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
    }).then(res => res.json()).then(data => {
        if (data.status === 'success') {
            showToast('Preference order updated successfully!');
        } else {
            showToast('Error saving settings.');
        }
    });
}

function openModelModal() {
    document.getElementById('addModelModal').style.display = 'flex';
}

let currentDuplicateFromId = null;
let currentEditModelId = null;

function closeModelModal() {
    document.getElementById('addModelModal').style.display = 'none';
    document.getElementById('addModelForm').reset();
    document.querySelector('#addModelModal h3').innerText = 'Add New Model';
    currentDuplicateFromId = null;
    currentEditModelId = null;
    const input = document.getElementById('new_api_key');
    if(input) {
        input.type = 'password';
    }
    const eyeIcon = document.getElementById('eyeIcon');
    if(eyeIcon) {
        eyeIcon.innerHTML = '<path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"></path><circle cx="12" cy="12" r="3"></circle>';
    }
}

function toggleNewApiKeyVisibility() {
    const input = document.getElementById('new_api_key');
    const eyeIcon = document.getElementById('eyeIcon');
    if (input.type === 'password') {
        input.type = 'text';
        eyeIcon.innerHTML = '<path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24"></path><line x1="1" y1="1" x2="23" y2="23"></line>';
    } else {
        input.type = 'password';
        eyeIcon.innerHTML = '<path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"></path><circle cx="12" cy="12" r="3"></circle>';
    }
}

function saveNewModel() {
    const payload = {
        model_name: document.getElementById('new_model_name').value,
        provider: document.getElementById('new_provider').value,
        api_key: document.getElementById('new_api_key').value,
        enabled: document.getElementById('new_enabled').checked,
        json_output: document.getElementById('new_json_output').checked,
        thinking: document.getElementById('new_thinking').checked,
        function_calling: document.getElementById('new_function_calling').checked,
        context_window: document.getElementById('new_context_window').value,
        max_output_tokens: document.getElementById('new_max_output_tokens').value,
        text_input: document.getElementById('new_text_input').checked,
        image_input: document.getElementById('new_image_input').checked,
        audio_input: document.getElementById('new_audio_input').checked,
        video_input: document.getElementById('new_video_input').checked,
        document_input: document.getElementById('new_document_input').checked,
        text_output: document.getElementById('new_text_output').checked,
        image_output: document.getElementById('new_image_output').checked,
        audio_output: document.getElementById('new_audio_output').checked,
        video_output: document.getElementById('new_video_output').checked,
        document_output: document.getElementById('new_document_output').checked,
        rate_tpm: document.getElementById('new_rate_tpm').value,
        rate_rpm: document.getElementById('new_rate_rpm').value,
        rate_rpd: document.getElementById('new_rate_rpd').value
    };

    if (currentDuplicateFromId) {
        payload.duplicate_from_id = currentDuplicateFromId;
    }

    if (!payload.model_name || !payload.provider) {
        showToast('Model name and provider are required');
        return;
    }

    const method = currentEditModelId ? 'PUT' : 'POST';
    const url = currentEditModelId ? `/api/llm_models/${currentEditModelId}` : '/api/llm_models';

    fetch(url, {
        method: method,
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
    }).then(res => res.json()).then(data => {
        if (data.status === 'success') {
            showToast(currentEditModelId ? 'Model updated successfully!' : 'Model added successfully!');
            closeModelModal();
            setTimeout(() => window.location.reload(), 1000);
        } else {
            showToast('Error saving model: ' + (data.error || 'Unknown error'));
        }
    }).catch(err => {
        console.error(err);
        showToast('Error saving model');
    });
}

let modelToDeleteId = null;

function deleteModel(id, name) {
    modelToDeleteId = id;
    document.getElementById('deleteModelNameText').innerText = `"${name}"`;
    document.getElementById('deleteModelModal').style.display = 'flex';
}

function closeDeleteModal() {
    document.getElementById('deleteModelModal').style.display = 'none';
    modelToDeleteId = null;
}

function confirmDeleteModel() {
    if (!modelToDeleteId) return;

    fetch(`/api/llm_models/${modelToDeleteId}`, {
        method: 'DELETE'
    }).then(res => res.json()).then(data => {
        if (data.status === 'success') {
            showToast('Model deleted successfully!');
            closeDeleteModal();
            setTimeout(() => window.location.reload(), 1000);
        } else {
            showToast('Error deleting model: ' + (data.error || 'Unknown error'));
        }
    }).catch(err => {
        console.error(err);
        showToast('Error deleting model');
    });
}

function toggleModelEnabled(id, checkbox) {
    fetch(`/api/llm_models/${id}/toggle`, {
        method: 'POST'
    }).then(res => res.json()).then(data => {
        if (data.status === 'success') {
            showToast(`Model ${data.enabled ? 'enabled' : 'disabled'} successfully!`);
        } else {
            showToast('Error toggling model status.');
            checkbox.checked = !checkbox.checked;
        }
    }).catch(err => {
        console.error(err);
        showToast('Error toggling model status');
        checkbox.checked = !checkbox.checked;
    });
}

function editModelById(id) {
    if (!window.APP_STATE || !window.APP_STATE.registeredModels) return;
    const model = window.APP_STATE.registeredModels.find(m => m.id === id);
    if (model) {
        editModel(model);
    } else {
        showToast('Model not found for editing.');
    }
}

function editModel(model) {
    openModelModal();
    currentEditModelId = model.id;
    document.querySelector('#addModelModal h3').innerText = 'Edit Model';

    document.getElementById('new_model_name').value = model.model_name || '';
    document.getElementById('new_provider').value = model.provider || '';

    const apiKeyInput = document.getElementById('new_api_key');
    if (model.has_key) {
        apiKeyInput.value = '••••••••••••';
    } else {
        apiKeyInput.value = '';
    }

    document.getElementById('new_context_window').value = model.context_window || '';
    document.getElementById('new_max_output_tokens').value = model.max_output_tokens || '';

    document.getElementById('new_enabled').checked = !!model.enabled;
    document.getElementById('new_json_output').checked = !!model.json_output;
    document.getElementById('new_thinking').checked = !!model.thinking;
    document.getElementById('new_function_calling').checked = !!model.function_calling;

    document.getElementById('new_text_input').checked = !!model.text_input;
    document.getElementById('new_image_input').checked = !!model.image_input;
    document.getElementById('new_audio_input').checked = !!model.audio_input;
    document.getElementById('new_video_input').checked = !!model.video_input;
    document.getElementById('new_document_input').checked = !!model.document_input;

    document.getElementById('new_text_output').checked = !!model.text_output;
    document.getElementById('new_image_output').checked = !!model.image_output;
    document.getElementById('new_audio_output').checked = !!model.audio_output;
    document.getElementById('new_video_output').checked = !!model.video_output;
    document.getElementById('new_document_output').checked = !!model.document_output;

    document.getElementById('new_rate_tpm').value = model.rate_tpm || '';
    document.getElementById('new_rate_rpm').value = model.rate_rpm || '';
    document.getElementById('new_rate_rpd').value = model.rate_rpd || '';
}

function duplicateModelById(id) {
    if (!window.APP_STATE || !window.APP_STATE.registeredModels) return;
    const model = window.APP_STATE.registeredModels.find(m => m.id === id);
    if (model) {
        duplicateModel(model);
    } else {
        showToast('Model not found for duplication.');
    }
}

function duplicateModel(model) {
    openModelModal();
    currentDuplicateFromId = model.id;

    document.getElementById('new_model_name').value = '';
    document.getElementById('new_provider').value = model.provider || '';

    const apiKeyInput = document.getElementById('new_api_key');
    if (model.has_key) {
        apiKeyInput.value = '••••••••••••';
    } else {
        apiKeyInput.value = '';
    }

    document.getElementById('new_context_window').value = model.context_window || '';
    document.getElementById('new_max_output_tokens').value = model.max_output_tokens || '';

    document.getElementById('new_enabled').checked = !!model.enabled;
    document.getElementById('new_json_output').checked = !!model.json_output;
    document.getElementById('new_thinking').checked = !!model.thinking;
    document.getElementById('new_function_calling').checked = !!model.function_calling;

    document.getElementById('new_text_input').checked = !!model.text_input;
    document.getElementById('new_image_input').checked = !!model.image_input;
    document.getElementById('new_audio_input').checked = !!model.audio_input;
    document.getElementById('new_video_input').checked = !!model.video_input;
    document.getElementById('new_document_input').checked = !!model.document_input;

    document.getElementById('new_text_output').checked = !!model.text_output;
    document.getElementById('new_image_output').checked = !!model.image_output;
    document.getElementById('new_audio_output').checked = !!model.audio_output;
    document.getElementById('new_video_output').checked = !!model.video_output;
    document.getElementById('new_document_output').checked = !!model.document_output;

    document.getElementById('new_rate_tpm').value = model.rate_tpm || '';
    document.getElementById('new_rate_rpm').value = model.rate_rpm || '';
    document.getElementById('new_rate_rpd').value = model.rate_rpd || '';
}
