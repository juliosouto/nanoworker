function startNewChat() {
    const newId = Math.random().toString(36).substring(2, 9);
    window.location.href = '/chat?chat_id=' + newId + '&focus=true';
}

function handleKeyPress(event) {
    if (event.key === 'Enter') {
        sendMessage();
    }
}

let currentImageBase64 = null;
let currentFileName = null;
let currentFileMimeType = null;

function handleFileSelect(event) {
    const file = event.target.files[0];
    if (!file) return;
    currentFileName = file.name;
    currentFileMimeType = file.type;
    const reader = new FileReader();
    reader.onload = function (e) {
        currentImageBase64 = e.target.result;
        document.getElementById('filePreviewContainer').style.display = 'flex';
        if (currentFileMimeType.startsWith('image/')) {
            document.getElementById('imagePreview').src = currentImageBase64;
            document.getElementById('imagePreview').style.display = 'block';
            document.getElementById('filePreview').style.display = 'none';
        } else {
            document.getElementById('filePreviewName').innerText = currentFileName;
            document.getElementById('imagePreview').style.display = 'none';
            document.getElementById('filePreview').style.display = 'block';
        }
    };
    reader.readAsDataURL(file);
    
    // Focus the chat input after selecting a file
    document.getElementById('chatInput').focus();
}

function clearFile() {
    currentImageBase64 = null;
    currentFileName = null;
    currentFileMimeType = null;
    document.getElementById('fileInput').value = '';
    document.getElementById('filePreviewContainer').style.display = 'none';
    document.getElementById('imagePreview').src = '';
}

function appendMessage(type, content, sessionId, msgId, timeStr, imageBase64 = null, fileMimeType = null, fileName = null) {
    const list = document.querySelector('.message-list');
    // Remove empty state if present
    const emptyState = document.querySelector('.empty-state');
    if (emptyState) emptyState.remove();

    const typeLabel = type === 'in' ? 'User' : 'Agent';

    const div = document.createElement('div');
    div.className = `message-item ${type}`;
    const renderedContent = type === 'out' && typeof marked !== 'undefined' ? marked.parse(content) : content;

    let imgHtml = '';
    if (imageBase64) {
        if (!fileMimeType || fileMimeType.startsWith('image/')) {
            if (imageBase64.startsWith('path:temp/')) {
                imgHtml = `<div style="margin-bottom: 8px;"><img src="/api/temp/${imageBase64.substring(10)}" style="max-width: 100%; border-radius: 8px; max-height: 300px;"></div>`;
            } else if (imageBase64.startsWith('path:')) {
                imgHtml = `<div style="margin-bottom: 8px; padding: 8px 12px; background: rgba(255,255,255,0.05); border: 1px solid var(--border-color); border-radius: 8px; display: inline-block;">🖼️ ${fileName || 'Image Attachment'}</div>`;
            } else if (imageBase64.startsWith('uri:')) {
                imgHtml = `<div style="margin-bottom: 8px; padding: 8px 12px; background: rgba(255,255,255,0.05); border: 1px solid var(--border-color); border-radius: 8px; display: inline-block;">🖼️ ${fileName || 'Attachment'}</div>`;
            } else {
                const src = imageBase64.startsWith('data:') ? imageBase64 : `data:image/jpeg;base64,${imageBase64}`;
                imgHtml = `<div style="margin-bottom: 8px;"><img src="${src}" style="max-width: 100%; border-radius: 8px; max-height: 300px;"></div>`;
            }
        } else {
            imgHtml = `<div style="margin-bottom: 8px; padding: 8px 12px; background: rgba(255,255,255,0.05); border: 1px solid var(--border-color); border-radius: 8px; display: inline-block;">📎 ${fileName || 'Attachment'}</div>`;
        }
    }

    div.innerHTML = `
        <div class="msg-header">
            <span class="msg-type">${typeLabel}</span>
            <span class="msg-time">${timeStr}</span>
        </div>
        <div class="msg-content">${imgHtml}<div class="${type === 'out' ? 'markdown-text' : 'plain-text'}">${renderedContent}</div></div>
    `;
    list.appendChild(div);

    // Scroll to bottom
    list.scrollTop = list.scrollHeight;
}

function sendMessage() {
    const input = document.getElementById('chatInput');
    const text = input.value.trim();
    if (!text) return;

    const chatId = window.APP_STATE.chatId;
    const channelId = chatId !== 'default' ? 'web-chat-' + chatId : 'web-chat';
    const senderId = chatId !== 'default' ? 'user-web-' + chatId : 'user-web';

    // Extract base64 without data URI prefix for the backend
    let b64Payload = null;
    let payloadMimeType = currentFileMimeType;
    let payloadFileName = currentFileName;

    if (currentImageBase64) {
        b64Payload = currentImageBase64.split(',')[1];
    }

    // Optimistically render user message
    appendMessage('in', text, channelId, 'msg-in-pend', 'Just now', currentImageBase64, currentFileMimeType, currentFileName);

    // Clear input and image
    clearFile();

    // Move chat to top of sidebar
    const sidebarUl = document.querySelector('.glass-panel ul');
    let activeLi = document.getElementById('sidebar-item-' + chatId);
    if (activeLi) {
        sidebarUl.prepend(activeLi);
        const timeDiv = activeLi.querySelector('.sidebar-time');
        if (timeDiv) timeDiv.innerText = 'Just now';
    } else if (sidebarUl) {
        const newLi = document.createElement('li');
        newLi.id = 'sidebar-item-' + chatId;
        newLi.innerHTML = `
            <a href="/chat?chat_id=${chatId}" style="text-decoration: none; color: inherit; display: block; padding: 10px; border-radius: 8px; background: rgba(255,255,255,0.1); border-left: 3px solid var(--accent);">
                <strong>Chat: ${chatId}</strong>
                <div class="sidebar-time" style="font-size: 0.8em; color: var(--text-muted); margin-top: 4px;">Just now</div>
            </a>
        `;
        sidebarUl.prepend(newLi);
    }

    input.value = '';
    input.disabled = true;

    // Show typing indicator
    const typingDiv = document.createElement('div');
    typingDiv.className = 'message-item out typing-indicator';
    typingDiv.innerHTML = `
        <div class="msg-header">
            <span class="msg-type">Agent</span>
            <span class="msg-time">...</span>
        </div>
        <div class="msg-content">
            <span class="typing-dots">
                <span>●</span><span>●</span><span>●</span>
            </span>
        </div>
    `;
    const list = document.querySelector('.message-list');
    list.appendChild(typingDiv);
    list.scrollTop = list.scrollHeight;


    fetch('/api/webhook', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json'
        },
        body: JSON.stringify({
            channel_id: channelId,
            content: text,
            sender_id: senderId,
            image_base64: b64Payload,
            file_mime_type: payloadMimeType,
            file_name: payloadFileName
        })
    }).then(res => res.json()).then(data => {
        if (data.status === 'received') {
            // Synchronous response (e.g. /new command)
            typingDiv.remove();
            input.disabled = false;
            input.focus();
            if (data.response_text) {
                appendMessage('out', data.response_text, data.session_id || channelId, 'msg-out-sync', data.created_at || 'Just now');
            }
            return;
        }

        if (data.status === 'processing') {
            // Start polling for the response
            const sessionId = data.session_id;
            const pollInterval = 1500;
            const pollTimeout = 1200000;
            const startTime = Date.now();
            const appendedMsgIds = new Set();

            const poller = setInterval(() => {
                if (Date.now() - startTime > pollTimeout) {
                    clearInterval(poller);
                    typingDiv.remove();
                    input.disabled = false;
                    input.focus();
                    appendMessage('out', '⏱️ Timeout: the agent took too long to respond.', sessionId, 'msg-out-timeout', 'Just now');
                    return;
                }

                fetch(`/api/messages/poll?message_in_id=${encodeURIComponent(data.message_in_id)}&type=chat`)
                    .then(res => res.json())
                    .then(pollData => {
                        if (pollData.messages) {
                            pollData.messages.forEach(msg => {
                                if (!appendedMsgIds.has(msg.id)) {
                                    appendedMsgIds.add(msg.id);
                                    appendMessage('out', msg.content, msg.session_id, msg.id, msg.created_at);
                                }
                            });
                        }

                        if (pollData.is_done) {
                            clearInterval(poller);
                            typingDiv.remove();
                            input.disabled = false;
                            input.focus();
                        }
                    })
                    .catch(err => console.error('Poll error:', err));
            }, pollInterval);
        }
    }).catch(err => {
        console.error(err);
        typingDiv.remove();
        input.disabled = false;
        input.focus();
    });
}

// Render markdown and scroll to bottom on load
window.onload = function () {
    if (typeof marked !== 'undefined') {
        document.querySelectorAll('.markdown-text').forEach(el => {
            el.innerHTML = marked.parse(el.textContent);
        });
    }
    const list = document.querySelector('.message-list');
    if (list) list.scrollTop = list.scrollHeight;

    // Focus input if requested
    const urlParams = new URLSearchParams(window.location.search);
    if (urlParams.get('focus') === 'true') {
        document.getElementById('chatInput').focus();
    }

    // Live search setup
    const searchInput = document.getElementById('chatSearch');
    let searchTimer = null;

    searchInput.addEventListener('input', function () {
        clearTimeout(searchTimer);
        const query = this.value.trim();
        const items = document.querySelectorAll('#chatSessionList > li');

        if (!query) {
            // Show all sessions when search is cleared
            items.forEach(li => li.style.display = '');
            return;
        }

        searchTimer = setTimeout(() => {
            fetch('/api/chat/search?q=' + encodeURIComponent(query))
                .then(res => res.json())
                .then(data => {
                    const matchSet = new Set(data.matching_channels || []);
                    items.forEach(li => {
                        // Extract channel_id from the sidebar item id
                        const itemId = li.id.replace('sidebar-item-', '');
                        const channelId = itemId !== 'default' ? 'web-chat-' + itemId : 'web-chat';
                        li.style.display = matchSet.has(channelId) ? '' : 'none';
                    });
                })
                .catch(err => console.error('Search error:', err));
        }, 300);
    });
}

let chatToDelete = null;

function showDeleteModal(chatId) {
    chatToDelete = chatId;
    document.getElementById('deleteModal').style.display = 'flex';
}

function closeDeleteModal() {
    chatToDelete = null;
    document.getElementById('deleteModal').style.display = 'none';
}

document.getElementById('confirmDeleteBtn')?.addEventListener('click', function () {
    if (!chatToDelete) return;

    fetch('/api/chat/' + encodeURIComponent(chatToDelete), {
        method: 'DELETE'
    })
        .then(res => res.json())
        .then(data => {
            if (data.status === 'success') {
                window.location.href = '/chat';
            } else {
                alert('Failed to delete chat.');
            }
        })
        .catch(err => console.error('Error deleting chat:', err))
        .finally(() => {
            closeDeleteModal();
        });
});
