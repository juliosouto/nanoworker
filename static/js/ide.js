let currentFilePath = '';

function startNewIdeChat() {
    const newId = Math.random().toString(36).substring(2, 9);
    window.location.href = '/ide?chat_id=' + newId + '&focus=true';
}

function openFolder() {
    fetch('/api/select_folder_dialog')
        .then(res => res.json())
        .then(data => {
            if (data.error) {
                alert('Error: ' + data.error);
            } else if (data.status === 'success' && data.path) {
                const path = data.path;
                fetch('/api/set_project_path', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json'
                    },
                    body: JSON.stringify({
                        project_path: path
                    })
                }).then(res => res.json()).then(data => {
                    if (data.error) {
                        alert('Error: ' + data.error);
                    } else {
                        const display = document.getElementById('current-folder-display');
                        display.innerText = path.split('/').pop();
                        display.title = path;
                        display.style.display = 'block';
                        loadFileTree();
                    }
                }).catch(err => {
                    console.error('Error setting project path:', err);
                    alert('Failed to set project path.');
                });
            }
        })
        .catch(err => {
            console.error('Error calling folder dialog:', err);
            alert('Failed to open folder dialog.');
        });
}

function loadFileTree() {
    fetch('/api/files')
        .then(res => res.json())
        .then(data => {
            const container = document.getElementById('file-tree-container');
            container.innerHTML = '';
            const ul = document.createElement('ul');
            ul.className = 'file-tree';
            renderTreeNodes(data, ul);
            container.appendChild(ul);
        })
        .catch(err => {
            console.error('Error loading file tree:', err);
            document.getElementById('file-tree-container').innerText = 'Failed to load files.';
        });
}

function renderTreeNodes(nodes, parentElement) {
    nodes.forEach(node => {
        const li = document.createElement('li');

        if (node.type === 'directory') {
            const dirDiv = document.createElement('div');
            dirDiv.className = 'dir-item';
            dirDiv.innerHTML = `<span class="dir-toggle">▶</span> <span class="dir-icon">📁</span> <span>${node.name}</span>`;

            const childUl = document.createElement('ul');
            childUl.style.display = 'none';

            dirDiv.onclick = (e) => {
                e.stopPropagation();
                const isCollapsed = childUl.style.display === 'none';
                childUl.style.display = isCollapsed ? 'block' : 'none';
                dirDiv.querySelector('.dir-toggle').innerText = isCollapsed ? '▼' : '▶';
                dirDiv.querySelector('.dir-icon').innerText = isCollapsed ? '📂' : '📁';
            };

            li.appendChild(dirDiv);
            renderTreeNodes(node.children, childUl);
            li.appendChild(childUl);
        } else {
            const fileDiv = document.createElement('div');
            fileDiv.className = 'file-item';
            fileDiv.dataset.path = node.path;
            fileDiv.innerHTML = `<span class="file-icon">📄</span> <span>${node.name}</span>`;

            fileDiv.onclick = (e) => {
                e.stopPropagation();
                document.querySelectorAll('.file-item').forEach(el => el.classList.remove('active'));
                fileDiv.classList.add('active');
                openFile(node.path);
            };

            li.appendChild(fileDiv);
        }
        parentElement.appendChild(li);
    });
}

function openFile(path) {
    fetch(`/api/files/content?path=${encodeURIComponent(path)}`)
        .then(res => res.json())
        .then(data => {
            if (data.error) {
                alert('Error: ' + data.error);
                return;
            }
            currentFilePath = data.path;
            document.getElementById('current-file-path').value = data.path;
            document.getElementById('editor-title').innerText = `Editor - ${data.path}`;
            document.getElementById('code-editor').value = data.content;

            document.getElementById('editor-empty-state').style.display = 'none';
            document.getElementById('editor-container').style.display = 'flex';
            document.getElementById('save-file-btn').style.display = 'block';
        })
        .catch(err => console.error('Error opening file:', err));
}

function saveCurrentFile() {
    if (!currentFilePath) return;
    const content = document.getElementById('code-editor').value;
    const saveBtn = document.getElementById('save-file-btn');

    saveBtn.disabled = true;
    saveBtn.innerText = 'Saving...';

    fetch('/api/files/save', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json'
        },
        body: JSON.stringify({
            path: currentFilePath,
            content: content
        })
    })
        .then(res => res.json())
        .then(data => {
            saveBtn.disabled = false;
            saveBtn.innerText = 'Save File';
            if (data.error) {
                alert('Error saving file: ' + data.error);
            } else {
                saveBtn.style.background = '#10b981';
                saveBtn.innerText = 'Saved!';
                setTimeout(() => {
                    saveBtn.style.background = '';
                    saveBtn.innerText = 'Save File';
                }, 2000);
            }
        })
        .catch(err => {
            saveBtn.disabled = false;
            saveBtn.innerText = 'Save File';
            console.error('Error saving file:', err);
        });
}

function handleKeyPress(event) {
    if (event.key === 'Enter') {
        sendMessage();
    }
}

function appendMessage(type, content, sessionId, msgId, timeStr) {
    const list = document.querySelector('.message-list');
    const emptyState = document.querySelector('.empty-state');
    if (emptyState) emptyState.remove();

    const typeLabel = type === 'in' ? 'User' : 'Agent';

    const div = document.createElement('div');
    div.className = `message-item ${type}`;
    const renderedContent = type === 'out' && typeof marked !== 'undefined' ? marked.parse(content) : content;
    div.innerHTML = `
        <div class="msg-header">
            <span class="msg-type">${typeLabel}</span>
            <span class="msg-time">${timeStr}</span>
        </div>
        <div class="msg-content${type === 'out' ? ' markdown' : ''}">${renderedContent}</div>
        <div class="msg-footer">
            Session: ${sessionId.substring(0, 8)} | ID: ${msgId.substring(0, 8)}
        </div>
    `;
    list.appendChild(div);
    list.scrollTop = list.scrollHeight;
}

function sendMessage() {
    const input = document.getElementById('chatInput');
    const text = input.value.trim();
    if (!text) return;

    const chatId = window.APP_STATE.chatId;
    const channelId = 'ide-' + chatId;
    const senderId = 'user-ide-' + chatId;

    appendMessage('in', text, channelId, 'msg-in-pend', 'Just now');

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
        <div class="msg-content" style="white-space: pre-wrap;">
            <span class="typing-dots">
                <span>●</span><span>●</span><span>●</span>
            </span>
        </div>
    `;
    const list = document.querySelector('.message-list');
    list.appendChild(typingDiv);
    list.scrollTop = list.scrollHeight;


    fetch('/api/ide-webhook', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json'
        },
        body: JSON.stringify({
            channel_id: channelId,
            content: text,
            sender_id: senderId
        })
    }).then(res => res.json()).then(data => {
        if (data.status === 'processing') {
            // Start polling for the response
            const sessionId = data.session_id;
            const pollInterval = 1500;
            const pollTimeout = 1200000;  // 
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

                fetch(`/api/messages/poll?message_in_id=${encodeURIComponent(data.message_in_id)}&type=ide`)
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
        document.querySelectorAll('.msg-content.markdown').forEach(el => {
            el.innerHTML = marked.parse(el.textContent);
        });
    }
    const list = document.querySelector('.message-list');
    if (list) list.scrollTop = list.scrollHeight;

    // Load file tree
    loadFileTree();

    // Focus input if requested
    const urlParams = new URLSearchParams(window.location.search);
    if (urlParams.get('focus') === 'true') {
        document.getElementById('chatInput').focus();
    }
}
