// --- Enhanced AI Chat JavaScript ---
// Features: Task progress tracking, queue management, completion status

// --- Global Variables ---
var bridge = null;
var term = null;
var fitAddon = null;
var currentChatId = null;
var chats = JSON.parse(localStorage.getItem('cortex_chats') || '[]');

var currentAssistantMessage = null;
var currentContent = "";
var renderPending = false;
var lastRenderTime = 0;
var RENDER_INTERVAL = 32;

// Task tracking
var currentTask = null;
var taskQueue = [];

// --- Initialization ---

function initTerminal() {
    var container = document.getElementById('terminal-container');
    if (!container) return;

    if (typeof Terminal === 'undefined') {
        setTimeout(initTerminal, 50);
        return;
    }

    term = new Terminal({
        fontFamily: "'Cascadia Code', 'Consolas', monospace",
        fontSize: 12,
        cursorBlink: true,
        theme: { background: '#0c0c0c', foreground: '#cccccc' }
    });

    fitAddon = new FitAddon.FitAddon();
    term.loadAddon(fitAddon);
    term.open(container);
    fitAddon.fit();

    term.onData(function (data) { if (bridge) bridge.on_terminal_input(data); });

    window.addEventListener('resize', function () {
        if (fitAddon) fitAddon.fit();
        if (bridge) bridge.on_terminal_resize(term.cols, term.rows);
    });
}

function initMarked() {
    if (typeof marked === 'undefined') {
        setTimeout(initMarked, 50);
        return;
    }
    var renderer = new marked.Renderer();
    renderer.code = function (code, language) {
        var codeText = typeof code === 'object' ? code.text : code;
        var lang = (language || 'text').toLowerCase();
        
        // Specialized Tree Rendering
        if (lang === 'tree' || (lang === 'plaintext' && codeText.includes('├──') || codeText.includes('└──'))) {
            return renderProjectTree(codeText);
        }

        var highlighted;
        try { highlighted = hljs.highlight(codeText, { language: hljs.getLanguage(lang) ? lang : 'plaintext' }).value; }
        catch (e) { highlighted = codeText; }
        var isShell = ['bash', 'sh', 'powershell', 'ps1', 'cmd', 'shell'].includes(lang);
        var runBtn = isShell ? '<button class="run-btn" onclick="runCode(this)" title="Run in terminal"><i class="fas fa-play"></i> Run</button>' : '';
        return '<div class="code-block-container">' +
            '<div class="code-header">' +
            '<span class="code-lang">' + lang.toUpperCase() + '</span>' +
            '<div class="code-actions">' + runBtn + '<button class="copy-btn" onclick="copyToClipboard(this)" title="Copy"><i class="fas fa-copy"></i> Copy</button></div>' +
            '</div>' +
            '<pre><code class="hljs language-' + lang + '">' + highlighted + '</code></pre>' +
            '</div>';
    };

    function renderProjectTree(text) {
        var lines = text.trim().split('\n');
        var html = '<div class="project-tree">';
        lines.forEach(line => {
            var isDir = line.trim().endsWith('/') || !line.includes('.');
            var icon = isDir ? 'fa-folder' : 'fa-file';
            var commentSplit = line.split('#');
            var mainLine = commentSplit[0];
            var comment = commentSplit.length > 1 ? '<span class="comment"># ' + escapeHtml(commentSplit[1]) + '</span>' : '';
            
            html += '<div class="tree-node">';
            html += '<i class="fas ' + icon + '"></i>';
            html += '<div class="tree-text"><span>' + escapeHtml(mainLine) + '</span>' + comment + '</div>';
            html += '</div>';
        });
        html += '</div>';
        return html;
    }
    renderer.table = function (header, body) {
        return '<div class="table-wrapper"><table><thead>' + header + '</thead><tbody>' + body + '</tbody></table></div>';
    };
    marked.setOptions({ renderer: renderer, breaks: true, gfm: true });
}

function initBridge() {
    console.log("Cortex: Initializing QWebChannel Bridge...");

    var transport = (window.qt && window.qt.webChannelTransport) || (typeof qt !== 'undefined' && qt.webChannelTransport);

    if (typeof QWebChannel === 'undefined' || !transport) {
        setTimeout(initBridge, 200);
        return;
    }

    try {
        new QWebChannel(transport, function (channel) {
            bridge = channel.objects.bridge;
            if (!bridge) {
                console.error("Cortex: Bridge object 'bridge' not found on channel.");
                return;
            }

            bridge.clear_chat_requested.connect(clearMessages);
            bridge.terminal_output.connect(function (data) { if (term) term.write(data); });

            console.log("Cortex: Bridge Successfully Connected.");
            var sendBtn = document.getElementById('sendBtn');
            if (sendBtn) sendBtn.disabled = false;

            loadChatHistory();
            if (chats.length > 0) loadChat(chats[0].id);
            else startNewChat();
        });
    } catch (e) {
        console.error("Cortex: Error during QWebChannel init: " + e.message);
        setTimeout(initBridge, 500);
    }
}

document.addEventListener('DOMContentLoaded', function () {
    initMarked();
    initTerminal();
    initBridge();

    // Event Listeners
    var toggle = document.getElementById('toggle-history-btn');
    if (toggle) toggle.onclick = toggleSidebar;

    var close = document.getElementById('close-sidebar-btn');
    if (close) close.onclick = toggleSidebar;

    var newChatBtn = document.getElementById('new-chat-btn');
    if (newChatBtn) newChatBtn.onclick = startNewChat;

    var send = document.getElementById('sendBtn');
    if (send) send.onclick = sendMessage;

    var stop = document.getElementById('stopBtn');
    if (stop) stop.onclick = stopGeneration;

    var genPlan = document.getElementById('generate-plan-btn');
    if (genPlan) genPlan.onclick = function() {
        if (bridge) bridge.on_generate_plan();
    };

    var clear = document.getElementById('clear-chat-btn');
    if (clear) clear.onclick = function () {
        if (confirm('Clear all messages in this conversation?')) {
            var chat = chats.find(function (c) { return c.id === currentChatId; });
            if (chat) {
                chat.messages = [];
                saveChats();
                clearMessages();
            }
        }
    };

    var input = document.getElementById('chatInput');
    if (input) {
        input.onkeydown = function (e) {
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                sendMessage();
            }
        };
        input.oninput = function () {
            input.style.height = 'auto';
            input.style.height = (input.scrollHeight) + 'px';
        };
        setTimeout(function () { if (input) input.focus(); }, 200);
    }
});

// --- Task Progress & Status Functions ---

function onTaskProgress(taskId, stepName, percentage) {
    console.log(`Task ${taskId}: ${stepName} - ${percentage}%`);
    
    // Update or create progress indicator
    var progressId = 'progress-' + taskId;
    var existingProgress = document.getElementById(progressId);
    
    if (!existingProgress) {
        // Create new progress indicator
        var progressHTML = `
            <div id="${progressId}" class="task-progress-container">
                <div class="task-progress-header">
                    <span class="task-name">${escapeHtml(stepName)}</span>
                    <span class="task-percentage">${percentage}%</span>
                </div>
                <div class="task-progress-bar">
                    <div class="task-progress-fill" style="width: ${percentage}%"></div>
                </div>
            </div>
        `;
        
        // Add to current assistant message or create new
        if (currentAssistantMessage) {
            var content = currentAssistantMessage.querySelector('.message-content');
            if (content) {
                var tempDiv = document.createElement('div');
                tempDiv.innerHTML = progressHTML;
                content.appendChild(tempDiv.firstElementChild);
            }
        }
    } else {
        // Update existing
        var percentageSpan = existingProgress.querySelector('.task-percentage');
        var fillDiv = existingProgress.querySelector('.task-progress-fill');
        var nameSpan = existingProgress.querySelector('.task-name');
        
        if (percentageSpan) percentageSpan.textContent = percentage + '%';
        if (fillDiv) fillDiv.style.width = percentage + '%';
        if (nameSpan) nameSpan.textContent = stepName;
    }
    
    scrollToBottom();
}

function onTaskStepCompleted(taskId, stepName, result) {
    console.log(`Task ${taskId}: Step "${stepName}" completed - ${result}`);
    
    // Add completion marker
    appendSystemMessage(`✅ Completed: ${stepName}`);
}

function onTaskCompleted(taskId, summary) {
    console.log(`Task ${taskId} completed:`, summary);
    
    // Remove progress indicator
    var progressId = 'progress-' + taskId;
    var progressEl = document.getElementById(progressId);
    if (progressEl) {
        progressEl.style.opacity = '0.5';
        progressEl.classList.add('completed');
    }
    
    // Show completion message
    var completionHTML = `
        <div class="task-completion">
            <div class="completion-icon">✅</div>
            <div class="completion-message">Task Completed Successfully!</div>
            <div class="completion-summary">${marked.parse(summary)}</div>
        </div>
    `;
    
    if (currentAssistantMessage) {
        var content = currentAssistantMessage.querySelector('.message-content');
        if (content) {
            var tempDiv = document.createElement('div');
            tempDiv.innerHTML = completionHTML;
            content.appendChild(tempDiv.firstElementChild);
        }
    }
    
    // Reset UI
    onComplete();
    scrollToBottom();
}

function onTaskFailed(taskId, error) {
    console.log(`Task ${taskId} failed:`, error);
    
    var errorHTML = `
        <div class="task-error">
            <div class="error-icon">❌</div>
            <div class="error-message">Task Failed</div>
            <div class="error-details">${escapeHtml(error)}</div>
        </div>
    `;
    
    appendMessage(errorHTML, 'assistant', true);
    onComplete();
}

function onTaskCancelled(taskId) {
    console.log(`Task ${taskId} cancelled`);
    
    appendSystemMessage('⏹️ Task cancelled by user');
    onComplete();
}

function onQueueStatusChanged(queueLength) {
    console.log(`Queue status: ${queueLength} tasks pending`);
    
    if (queueLength > 0) {
        appendSystemMessage(`📋 ${queueLength} task(s) in queue`);
    }
}

function onCurrentTaskChanged(taskId) {
    console.log(`Current task changed to: ${taskId || 'none'}`);
    currentTask = taskId;
}

function updateTaskStatus(status) {
    console.log('Task status update:', status);
    
    // Update UI with queue status
    if (status.queue_length > 0) {
        showQueueIndicator(status);
    }
}

function showQueueIndicator(status) {
    // Implementation for showing queue status in UI
    var indicator = document.getElementById('queue-indicator');
    if (!indicator) {
        indicator = document.createElement('div');
        indicator.id = 'queue-indicator';
        indicator.className = 'queue-indicator';
        var header = document.getElementById('header');
        if (header) header.appendChild(indicator);
    }
    
    indicator.innerHTML = `
        <span class="queue-count">${status.queue_length}</span>
        <span class="queue-label">queued</span>
    `;
    indicator.style.display = status.queue_length > 0 ? 'flex' : 'none';
}

// --- Chat Management ---

function toggleSidebar() {
    var sidebar = document.getElementById('history-sidebar');
    if (sidebar) sidebar.classList.toggle('collapsed');
}

function saveChats() {
    localStorage.setItem('cortex_chats', JSON.stringify(chats));
    renderHistoryList();
}

function loadChatHistory() {
    chats = JSON.parse(localStorage.getItem('cortex_chats') || '[]');
    renderHistoryList();
}

function renderHistoryList() {
    var list = document.getElementById('chat-history-list');
    if (!list) return;
    list.innerHTML = '';
    chats.forEach(function (chat) {
        var item = document.createElement('div');
        item.className = 'history-item' + (chat.id === currentChatId ? ' active' : '');
        
        var titleSpan = document.createElement('span');
        titleSpan.textContent = chat.title;
        
        var deleteBtn = document.createElement('button');
        deleteBtn.className = 'delete-chat-btn';
        deleteBtn.title = 'Delete Chat';
        deleteBtn.innerHTML = '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="3 6 5 6 21 6"></polyline><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path></svg>';
        
        deleteBtn.onclick = function(e) {
            e.stopPropagation();
            deleteChat(chat.id);
        };

        item.appendChild(titleSpan);
        item.appendChild(deleteBtn);
        
        item.onclick = function () { loadChat(chat.id); };
        list.appendChild(item);
    });
}

function deleteChat(id) {
    if (!confirm('Delete this conversation?')) return;
    
    chats = chats.filter(function(chat) { return chat.id !== id; });
    saveChats();
    
    if (currentChatId === id) {
        if (chats.length > 0) {
            loadChat(chats[0].id);
        } else {
            startNewChat();
        }
    }
}

function startNewChat() {
    currentChatId = Date.now().toString();
    var newChat = {
        id: currentChatId,
        title: 'New Conversation',
        messages: [],
        timestamp: Date.now()
    };
    chats.unshift(newChat);
    saveChats();
    clearMessages();
}

function loadChat(id) {
    var chat = chats.find(function (c) { return c.id === id; });
    if (!chat) return;
    currentChatId = id;
    clearMessages();
    chat.messages.forEach(function (msg) {
        appendMessage(msg.text, msg.sender, false);
    });
    renderHistoryList();
    
    var sidebar = document.getElementById('history-sidebar');
    if (sidebar && !sidebar.classList.contains('collapsed')) {
        sidebar.classList.add('collapsed');
    }
}

function clearMessages() {
    var container = document.getElementById('chatMessages');
    if (!container) return;
    container.innerHTML = '';
    currentAssistantMessage = null;
    currentContent = "";

    var chat = chats.find(function (c) { return c.id === currentChatId; });
    if (!chat || chat.messages.length === 0) {
        var emptyState = document.createElement('div');
        emptyState.id = 'empty-state';
        emptyState.innerHTML = `<svg width="60" height="60" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1" stroke-linecap="round" stroke-linejoin="round" style="margin: 0 auto 20px auto; display: block; opacity: 0.6;"><path d="M9.5 2A2.5 2.5 0 0 1 12 4.5v15a2.5 2.5 0 0 1-4.96.44 2.5 2.5 0 0 1-2.96-3.08 3 3 0 0 1-.34-5.58 2.5 2.5 0 0 1 1.32-4.24 2.5 2.5 0 0 1 4.44-2.54Z"></path><path d="M14.5 2A2.5 2.5 0 0 0 12 4.5v15a2.5 2.5 0 0 0 4.96.44 2.5 2.5 0 0 0 2.96-3.08 3 3 0 0 0 .34-5.58 2.5 2.5 0 0 0-1.32-4.24 2.5 2.5 0 0 0-4.44-2.54Z"></path></svg><p>Start a new conversation with Cortex AI</p>`;
        container.appendChild(emptyState);
    }
}

function appendMessage(text, sender, shouldSave) {
    var container = document.getElementById('chatMessages');
    if (!container) return null;

    var emptyState = document.getElementById('empty-state');
    if (emptyState) emptyState.remove();

    var bubble = document.createElement('div');
    bubble.className = 'message-bubble ' + sender;
    var content = document.createElement('div');
    content.className = 'message-content';

    if (sender === 'user') {
        content.textContent = text;
    } else {
        content.innerHTML = marked.parse(text);
    }
    
    // Add Copy Message Button
    var copyBtn = document.createElement('button');
    copyBtn.className = 'copy-msg-btn';
    copyBtn.title = 'Copy Message';
    copyBtn.innerHTML = `<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect width="14" height="14" x="8" y="8" rx="2" ry="2"></rect><path d="M4 16c-1.1 0-2-.9-2-2V4c0-1.1.9-2 2-2h10c1.1 0 2 .9 2 2"></path></svg>`;
    copyBtn.onclick = function(e) {
        e.stopPropagation();
        copyMessage(text, copyBtn);
    };
    bubble.appendChild(copyBtn);
    
    bubble.appendChild(content);
    container.appendChild(bubble);
    container.scrollTop = container.scrollHeight;
    
    if (sender === 'assistant' && window.MathJax && window.MathJax.typeset) {
        window.MathJax.typeset([bubble]);
    }

    if (shouldSave) {
        var chat = chats.find(function (c) { return c.id === currentChatId; });
        if (chat) {
            chat.messages.push({ text: text, sender: sender });
            if (chat.messages.length === 1 && sender === 'user') {
                chat.title = text.substring(0, 30) + (text.length > 30 ? '...' : '');
            }
            saveChats();
        }
    }
    return bubble;
}

function appendSystemMessage(text) {
    // Add a system message (not saved to chat history)
    var container = document.getElementById('chatMessages');
    if (!container) return;

    var msgDiv = document.createElement('div');
    msgDiv.className = 'system-message';
    msgDiv.textContent = text;
    container.appendChild(msgDiv);
    scrollToBottom();
}

function copyMessage(text, btn) {
    navigator.clipboard.writeText(text).then(function() {
        var originalHtml = btn.innerHTML;
        btn.innerHTML = '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="#4BB543" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"></polyline></svg>';
        setTimeout(function() { btn.innerHTML = originalHtml; }, 2000);
    });
}

function sendMessage() {
    var input = document.getElementById('chatInput');
    if (!input) return;
    var text = input.value.trim();
    if (!text) return;

    if (!bridge) {
        console.warn("Cortex: Bridge connection not ready.");
        return;
    }

    appendMessage(text, 'user', true);
    bridge.on_message_submitted(text);

    input.value = '';
    input.style.height = 'auto';
    
    // Show stop button, hide send button
    var sendBtn = document.getElementById('sendBtn');
    var stopBtn = document.getElementById('stopBtn');
    if (sendBtn) sendBtn.style.display = 'none';
    if (stopBtn) stopBtn.style.display = 'flex';
}

function stopGeneration() {
    if (bridge) bridge.on_stop();
    onComplete();
}

function onChunk(chunk) {
    var container = document.getElementById('chatMessages');
    if (!container) return;

    if (!currentAssistantMessage) {
        currentAssistantMessage = document.createElement('div');
        currentAssistantMessage.className = 'message-bubble assistant';
        var content = document.createElement('div');
        content.className = 'message-content';
        currentAssistantMessage.appendChild(content);
        container.appendChild(currentAssistantMessage);
        currentContent = "";
    }

    currentContent += chunk;
    
    // Throttled Rendering
    if (!renderPending) {
        renderPending = true;
        requestAnimationFrame(function() {
            renderPending = false;
            updateStreamingUI();
        });
    }
}

function updateStreamingUI() {
    var container = document.getElementById('chatMessages');
    if (!currentAssistantMessage || !container) return;

    var contentDiv = currentAssistantMessage.querySelector('.message-content');
    if (!contentDiv) return;

    contentDiv.innerHTML = marked.parse(currentContent);
    
    container.scrollTop = container.scrollHeight;
}

function onComplete() {
    if (currentAssistantMessage) {
        var text = currentContent;
        var chat = chats.find(function (c) { return c.id === currentChatId; });
        if (chat) {
            chat.messages.push({ text: text, sender: 'assistant' });
            saveChats();
        }
        
        var contentDiv = currentAssistantMessage.querySelector('.message-content');
        if (contentDiv) {
            contentDiv.innerHTML = marked.parse(text);
            handlePostRenderSpecialTags(contentDiv);
        }

        if (window.MathJax && window.MathJax.typeset) {
            window.MathJax.typeset([currentAssistantMessage]);
        }
    }
    currentAssistantMessage = null;
    currentContent = "";
    
    // Hide stop button, show send button
    var sendBtn = document.getElementById('sendBtn');
    var stopBtn = document.getElementById('stopBtn');
    if (sendBtn) sendBtn.style.display = 'flex';
    if (stopBtn) stopBtn.style.display = 'none';
}

function handlePostRenderSpecialTags(container) {
    if (currentContent.includes('<permission>')) handlePermissionTag();
    if (currentContent.includes('<options>')) handleOptionsTag();
    if (currentContent.includes('<diff>')) handleDiffTag();
}

function handlePermissionTag() {
    var startTag = '<permission>';
    var endTag = '</permission>';
    var startIndex = currentContent.indexOf(startTag);
    var endIndex = currentContent.indexOf(endTag);
    
    var contentDiv = currentAssistantMessage.querySelector('.message-content');
    
    if (startIndex !== -1 && endIndex !== -1) {
        var textBefore = currentContent.substring(0, startIndex);
        var data = currentContent.substring(startIndex + startTag.length, endIndex);
        var textAfter = currentContent.substring(endIndex + endTag.length);
        
        contentDiv.innerHTML = marked.parse(textBefore) + renderPermissionBlock(data) + marked.parse(textAfter);
    }
}

function renderPermissionBlock(data) {
    try {
        var actions = JSON.parse(data);
        var html = '<div class="permission-block">';
        html += '<div class="permission-header"><i class="fas fa-shield-alt"></i> Permission Required</div>';
        html += '<div class="permission-list">';
        actions.forEach(a => {
            html += '<div class="exploration-item"><i class="fas fa-cog"></i> ' + a.info + '</div>';
        });
        html += '</div>';
        html += '<div class="permission-actions">';
        html += '<button class="permission-btn yes" onclick="confirmPermission(true)">Yes, Execute</button>';
        html += '<button class="permission-btn no" onclick="confirmPermission(false)">No, Stop</button>';
        html += '<label class="always-allow-container"><input type="checkbox" id="always-allow-check"> Always allow for this chat</label>';
        html += '</div></div>';
        return html;
    } catch(e) { return '<pre>' + data + '</pre>'; }
}

function confirmPermission(confirmed) {
    var always = document.getElementById('always-allow-check') ? document.getElementById('always-allow-check').checked : false;
    if (bridge) {
        if (always) bridge.on_always_allow_changed(true);
        bridge.on_message_submitted(confirmed ? "yes" : "no");
    }
    var block = document.querySelector('.permission-block');
    if (block) {
        block.style.opacity = '0.5';
        block.style.pointerEvents = 'none';
    }
}

function handleOptionsTag() {
    var startTag = '<options>';
    var endTag = '</options>';
    var startIndex = currentContent.indexOf(startTag);
    var endIndex = currentContent.indexOf(endTag);
    
    var contentDiv = currentAssistantMessage.querySelector('.message-content');
    
    if (startIndex !== -1 && endIndex !== -1) {
        var textBefore = currentContent.substring(0, startIndex);
        var data = currentContent.substring(startIndex + startTag.length, endIndex);
        var textAfter = currentContent.substring(endIndex + endTag.length);
        
        contentDiv.innerHTML = marked.parse(textBefore) + renderOptionsBlock(data) + marked.parse(textAfter);
    }
}

function renderOptionsBlock(data) {
    var lines = data.trim().split('\n');
    var html = '<div class="options-block">';
    lines.forEach((line, i) => {
        if (!line.trim()) return;
        var text = line.replace(/^\d+\.\s*/, '').trim();
        html += '<div class="option-item" onclick="selectOption(\'' + text.replace(/'/g, "\\'") + '\')">';
        html += '<div class="option-number">' + (i+1) + '</div>';
        html += '<span>' + escapeHtml(text) + '</span>';
        html += '</div>';
    });
    html += '</div>';
    return html;
}

function selectOption(text) {
    var input = document.getElementById('chatInput');
    if (input) {
        input.value = text;
        sendMessage();
    }
}

function handleDiffTag() {
    var startTag = '<diff>';
    var endTag = '</diff>';
    var startIndex = currentContent.indexOf(startTag);
    var endIndex = currentContent.indexOf(endTag);
    
    var contentDiv = currentAssistantMessage.querySelector('.message-content');
    
    if (startIndex !== -1) {
        var textBefore = currentContent.substring(0, startIndex);
        var diffData = "";
        
        if (endIndex !== -1) {
            diffData = currentContent.substring(startIndex + startTag.length, endIndex);
            var textAfter = currentContent.substring(endIndex + endTag.length);
            contentDiv.innerHTML = marked.parse(textBefore) + renderDiffBlock(diffData) + marked.parse(textAfter);
        } else {
            diffData = currentContent.substring(startIndex + startTag.length);
            contentDiv.innerHTML = marked.parse(textBefore) + renderDiffBlock(diffData, true);
        }
    }
}

function renderDiffBlock(data, isStreaming) {
    try {
        var lines = data.trim().split('\n');
        var filename = "Modified File";
        if (lines[0].startsWith('File: ')) {
            filename = lines[0].replace('File: ', '');
            lines.shift();
        }
        
        var html = '<div class="diff-block">';
        html += '<div class="diff-header"><span class="filename">' + filename + '</span><span class="diff-badge">DIFF</span></div>';
        html += '<div class="diff-content">';
        
        lines.forEach(line => {
            var cls = "";
            if (line.startsWith('+')) cls = "added";
            else if (line.startsWith('-')) cls = "removed";
            else if (line.startsWith('@@')) cls = "info";
            html += '<span class="diff-line ' + cls + '">' + escapeHtml(line) + '</span>';
        });
        
        if (isStreaming) {
            html += '<span class="diff-line info">... applying changes ...</span>';
        }
        html += '</div></div>';
        return html;
    } catch(e) {
        return '<pre><code>' + data + '</code></pre>';
    }
}

function escapeHtml(text) {
    var div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

function copyToClipboard(btn) {
    var container = btn.closest('.code-block-container');
    var code = container.querySelector('code').innerText;
    navigator.clipboard.writeText(code).then(function () {
        var originalHtml = btn.innerHTML;
        btn.innerHTML = '<i class="fas fa-check"></i>';
        setTimeout(function () { btn.innerHTML = originalHtml; }, 2000);
    });
}

function runCode(btn) {
    var container = btn.closest('.code-block-container');
    var code = container.querySelector('code').innerText;
    if (bridge) bridge.on_run_command(code);
}

function scrollToBottom() {
    var container = document.getElementById('chatMessages');
    if (container) {
        container.scrollTop = container.scrollHeight;
    }
}

// --- Advanced Toolbar Logic ---
document.addEventListener('DOMContentLoaded', function() {
    var dropdownTrigger = document.querySelector('.dropdown-trigger');
    var modeItems = document.querySelectorAll('.dropdown-item');

    // Unified Mode Selector Logic
    var modeDropdown = document.getElementById('mode-selector');
    if (modeDropdown) {
        var trigger = modeDropdown.querySelector('.dropdown-trigger');
        var menu = modeDropdown.querySelector('.dropdown-menu');
        var items = modeDropdown.querySelectorAll('.dropdown-item');
        var modeText = document.getElementById('current-mode');
        var modeIcon = trigger.querySelector('i');

        trigger.onclick = function(e) {
            e.stopPropagation();
            menu.classList.toggle('show');
        };

        items.forEach(function(item) {
            item.onclick = function() {
                var val = this.dataset.value;
                items.forEach(function(i) { i.classList.remove('active'); });
                this.classList.add('active');
                
                if (modeText) modeText.innerText = val;
                
                if (modeIcon) {
                    if (val === 'Agent') modeIcon.className = 'fas fa-infinity icon-agent';
                    else if (val === 'Ask') modeIcon.className = 'fas fa-comment-dots';
                    else if (val === 'Plan') modeIcon.className = 'fas fa-magic';
                }

                if (bridge) bridge.on_mode_changed(val);
                menu.classList.remove('show');
            };
        });
    }

    // Close dropdown on outside click
    document.addEventListener('click', function() {
        var menus = document.querySelectorAll('.dropdown-menu');
        menus.forEach(function(m) { m.classList.remove('show'); });
    });

    // --- Python Hooks ---
    window.onChunk = onChunk;
    window.onComplete = onComplete;
    window.appendMessage = appendMessage;
    
    // Task management hooks
    window.onTaskProgress = onTaskProgress;
    window.onTaskStepCompleted = onTaskStepCompleted;
    window.onTaskCompleted = onTaskCompleted;
    window.onTaskFailed = onTaskFailed;
    window.onTaskCancelled = onTaskCancelled;
    window.onQueueStatusChanged = onQueueStatusChanged;
    window.onCurrentTaskChanged = onCurrentTaskChanged;
    window.updateTaskStatus = updateTaskStatus;
    
    window.setTheme = function (isDark) {
        document.body.className = isDark ? 'dark' : 'light';
    };
    window.focusInput = function () {
        var input = document.getElementById('chatInput');
        if (input) input.focus();
    };
});
