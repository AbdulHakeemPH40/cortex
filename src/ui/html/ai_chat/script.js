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
var RENDER_INTERVAL = 32; // ~30fps for smooth visual but low CPU

// --- Initialization ---

function initTerminal() {
    var inner = document.getElementById('terminal-inner');
    if (!inner) return;

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
    term.open(inner);

    window.addEventListener('resize', function () {
        if (fitAddon) fitAddon.fit();
        if (bridge) bridge.on_terminal_resize(term.cols, term.rows);
    });

    term.onData(function (data) { if (bridge) bridge.on_terminal_input(data); });
}

function toggleTerminal() {
    var container = document.getElementById('terminal-container');
    var handle    = document.getElementById('terminal-resize-handle');
    var toggleBtn = document.getElementById('toggle-terminal-btn');
    if (!container) return;

    var isOpen = container.classList.toggle('open');
    if (handle) handle.classList.toggle('visible', isOpen);
    if (toggleBtn) toggleBtn.classList.toggle('active', isOpen);

    if (isOpen) {
        // Give the CSS transition time to expand, then fit
        setTimeout(function () {
            if (fitAddon) fitAddon.fit();
            if (term) term.focus();
        }, 280);
    }
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

    // Terminal is now shown inline in chat or via window.showTerminal() when needed

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
    
    // Auto-close sidebar on mobile/small screens or whenever a chat is selected
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
    onComplete(); // Reset UI state
}

// --- Workflow State (Internal) ---
var currentPlan = "";
var currentTasks = "";
var currentWalkthrough = "";

function onChunk(chunk) {
    var container = document.getElementById('chatMessages');
    if (!container) return;

    // Auto-show terminal when AI starts responding (for command visibility)
    if (!currentAssistantMessage && chunk.trim()) {
        // Check if this is the start of a response
        if (window.showTerminal && !document.getElementById('terminal-container').classList.contains('open')) {
            // Only show terminal if the chunk indicates a tool might be used
            // This is a subtle indicator - terminal will be ready but not intrusive
        }
    }

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

    // Simplified: Just render markdown. 
    // The backend will handle saving specialized tags to files and opening them.
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
        
        // Render final content including any tags that didn't close yet
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
    // Handle interactive blocks that need to stay in chat
    // Permission tag removed - backend no longer requires confirmation
    if (currentContent.includes('<options>')) handleOptionsTag();
    if (currentContent.includes('<diff>')) handleDiffTag(); // Keep for legacy compatibility if needed
    if (currentContent.includes('<file_edited>')) handleFileEditedTag();
}

// Dead code removed: switchTab, handleAgenticContent, renderAgenticView

function handlePermissionTag() {
    // DISABLED: Permission system removed - commands execute without confirmation
    // Remove permission tags from display but don't show UI
    var startTag = '<permission>';
    var endTag = '</permission>';
    var startIndex = currentContent.indexOf(startTag);
    var endIndex = currentContent.indexOf(endTag);
    
    if (startIndex !== -1 && endIndex !== -1) {
        // Auto-approve and remove from display
        var data = currentContent.substring(startIndex + startTag.length, endIndex);
        if (bridge) {
            try {
                var actions = JSON.parse(data);
                bridge.on_message_submitted('yes');
            } catch(e) {
                bridge.on_message_submitted('yes');
            }
        }
        // Remove tag from content
        currentContent = currentContent.substring(0, startIndex) + currentContent.substring(endIndex + endTag.length);
    }
}

function renderPermissionBlock(data) {
    try {
        var actions = JSON.parse(data);
        // Use first action's info as the command display, fall back to raw
        var cmdText = (actions[0] && actions[0].info) ? actions[0].info : JSON.stringify(actions);

        var html = '<div class="perm-card">';
        html += '<div class="perm-title"><i class="fas fa-terminal"></i> PERMISSION REQUIRED</div>';
        html += '<div class="perm-cmd"><code>' + escapeHtml(cmdText) + '</code></div>';
        html += '<div class="perm-actions">';
        html += '<button class="perm-yes" onclick="confirmPermission(true)"><i class="fas fa-play"></i> Yes, Run</button>';
        html += '<button class="perm-no"  onclick="confirmPermission(false)"><i class="fas fa-times"></i> Cancel</button>';
        html += '<label class="perm-always"><input type="checkbox" id="always-allow-check"> Always allow</label>';
        html += '</div>';
        html += '</div>';
        return html;
    } catch(e) {
        // Fallback: treat raw string as command text
        var html = '<div class="perm-card">';
        html += '<div class="perm-title"><i class="fas fa-terminal"></i> PERMISSION REQUIRED</div>';
        html += '<div class="perm-cmd"><code>' + escapeHtml(data.trim()) + '</code></div>';
        html += '<div class="perm-actions">';
        html += '<button class="perm-yes" onclick="confirmPermission(true)"><i class="fas fa-play"></i> Yes, Run</button>';
        html += '<button class="perm-no"  onclick="confirmPermission(false)"><i class="fas fa-times"></i> Cancel</button>';
        html += '<label class="perm-always"><input type="checkbox" id="always-allow-check"> Always allow</label>';
        html += '</div>';
        html += '</div>';
        return html;
    }
}

function confirmPermission(confirmed) {
    // DISABLED: Permission system removed - auto-approve all
    // This function is kept for backwards compatibility but does nothing
    if (bridge) {
        bridge.on_message_submitted('yes');
    }
    
    // Remove any permission cards from display
    var cards = document.querySelectorAll('.perm-card');
    cards.forEach(function(card) {
        card.style.display = 'none';
    });
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

function handleExplorationTag() {
    var startTag = '<exploration>';
    var endTag = '</exploration>';
    var startIndex = currentContent.indexOf(startTag);
    var endIndex = currentContent.indexOf(endTag);
    
    var contentDiv = currentAssistantMessage.querySelector('.message-content');
    
    if (startIndex !== -1) {
        var textBefore = currentContent.substring(0, startIndex);
        var explorationData = "";
        
        if (endIndex !== -1) {
            explorationData = currentContent.substring(startIndex + startTag.length, endIndex);
            var textAfter = currentContent.substring(endIndex + endTag.length);
            contentDiv.innerHTML = marked.parse(textBefore) + renderExplorationBlock(explorationData) + marked.parse(textAfter);
        } else {
            explorationData = currentContent.substring(startIndex + startTag.length);
            contentDiv.innerHTML = marked.parse(textBefore) + renderExplorationBlock(explorationData, true);
        }
    }
}

function handleFileEditedTag() {
    var startTag = '<file_edited>';
    var endTag = '</file_edited>';
    var startIndex = currentContent.indexOf(startTag);
    var endIndex = currentContent.indexOf(endTag);
    
    var contentDiv = currentAssistantMessage.querySelector('.message-content');
    
    if (startIndex !== -1) {
        var textBefore = currentContent.substring(0, startIndex);
        var fileData = "";
        
        if (endIndex !== -1) {
            fileData = currentContent.substring(startIndex + startTag.length, endIndex);
            var textAfter = currentContent.substring(endIndex + endTag.length);
            contentDiv.innerHTML = marked.parse(textBefore) + renderFileEditedBlock(fileData) + marked.parse(textAfter);
        } else {
            fileData = currentContent.substring(startIndex + startTag.length);
            contentDiv.innerHTML = marked.parse(textBefore) + renderFileEditedBlock(fileData, true);
        }
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

function renderExplorationBlock(data, isStreaming) {
    var lines = data.trim().split('\n');
    var html = '<div class="exploration-block' + (isStreaming ? '' : ' collapsed') + '">';
    html += '<div class="exploration-header" onclick="this.parentElement.classList.toggle(\'collapsed\')">';
    html += '<span><i class="fas fa-search"></i> Explored ' + lines.length + ' project items</span>';
    html += '<i class="fas fa-chevron-down"></i></div>';
    html += '<div class="exploration-content">';
    
    lines.forEach(line => {
        if (!line.trim()) return;
        var icon = 'fa-file';
        if (line.toLowerCase().includes('list directory')) icon = 'fa-folder-open';
        if (line.toLowerCase().includes('search')) icon = 'fa-binoculars';
        html += '<div class="exploration-item"><i class="fas ' + icon + '"></i> ' + line + '</div>';
    });
    
    if (isStreaming) {
        html += '<div class="exploration-item"><i class="fas fa-spinner fa-spin"></i> Reading project context...</div>';
    }
    html += '</div></div>';
    return html;
}

function renderFileEditedBlock(data, isStreaming) {
    if (isStreaming) return '<div class="file-edit-card"><span class="pending">⏳ Editing file...</span></div>';
    
    var filePath = data.trim();
    var fileName = filePath.split('/').pop().split('\\\\').pop();
    var escapedId = filePath.replace(/[^a-zA-Z0-9]/g, '-');
    
    return `
<div class="file-edit-card" id="edit-${escapedId}">
    <div class="file-edit-header">
        <span class="file-icon">📄</span>
        <span class="edit-label">Edited</span>
        <code class="file-name" onclick="window.openFile('${filePath.replace(/\\\\/g, '\\\\\\\\')}')">\`${fileName}\`</code>
    </div>
    <div class="file-edit-actions">
        <button class="diff-btn" onclick="window.showDiff('${filePath.replace(/\\\\/g, '\\\\\\\\')}')">
            <span class="diff-badge">DIFF</span>
        </button>
        <span class="file-path">${filePath}</span>
    </div>
</div>
    `;
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

// --- Terminal Output Display in Chat ---
function showTerminalOutputInChat(command, output, isRunning) {
    var container = document.getElementById('chatMessages');
    if (!container) return;
    
    // Remove existing terminal output if any
    var existingOutput = document.getElementById('inline-terminal-output');
    if (existingOutput) {
        existingOutput.remove();
    }
    
    var html = '<div id="inline-terminal-output" class="terminal-output-block' + (isRunning ? ' running' : '') + '">';
    html += '<div class="terminal-output-header">';
    html += '<span class="terminal-status"><i class="fas fa-terminal"></i> ' + (isRunning ? 'Running in terminal' : 'Terminal Output') + '</span>';
    if (isRunning) {
        html += '<span class="terminal-actions">';
        html += '<button class="terminal-action-btn" onclick="window.showTerminal()">Run in the background</button>';
        html += '<button class="terminal-action-btn cancel" onclick="stopGeneration()">Cancel</button>';
        html += '</span>';
    } else {
        html += '<button class="terminal-action-btn" onclick="window.showTerminal()"><i class="fas fa-external-link-alt"></i> View in terminal</button>';
    }
    html += '</div>';
    
    // Command display
    html += '<div class="terminal-command">';
    html += '<span class="prompt">$</span> ' + escapeHtml(command);
    html += '</div>';
    
    // Output display
    if (output) {
        html += '<div class="terminal-content">';
        html += '<pre>' + escapeHtml(output) + '</pre>';
        html += '</div>';
    }
    
    html += '</div>';
    
    // Insert before the current assistant message or append to container
    if (currentAssistantMessage) {
        currentAssistantMessage.insertAdjacentHTML('beforebegin', html);
    } else {
        container.insertAdjacentHTML('beforeend', html);
    }
    
    container.scrollTop = container.scrollHeight;
}

// --- File Reference Display ---
function showFileReference(filePath, lineNumber, content) {
    var container = document.getElementById('chatMessages');
    if (!container) return;
    
    var fileName = filePath.split('/').pop().split('\\').pop();
    var escapedPath = filePath.replace(/\\/g, '\\\\');
    
    var html = '<div class="file-reference-block">';
    html += '<div class="file-reference-header">';
    html += '<span class="file-icon"><i class="fas fa-file-code"></i></span>';
    html += '<span class="file-name" onclick="window.openFile(\'' + escapedPath + '\')">' + fileName + '</span>';
    if (lineNumber) {
        html += '<span class="file-line">:' + lineNumber + '</span>';
    }
    html += '<button class="file-action-btn" onclick="window.openFile(\'' + escapedPath + '\')"><i class="fas fa-external-link-alt"></i> Open</button>';
    html += '</div>';
    
    if (content) {
        html += '<div class="file-reference-content">';
        html += '<pre><code>' + escapeHtml(content) + '</code></pre>';
        html += '</div>';
    }
    
    html += '</div>';
    
    if (currentAssistantMessage) {
        var contentDiv = currentAssistantMessage.querySelector('.message-content');
        if (contentDiv) {
            contentDiv.insertAdjacentHTML('beforeend', html);
        }
    } else {
        container.insertAdjacentHTML('beforeend', html);
    }
    
    container.scrollTop = container.scrollHeight;
}

// --- Tool Execution Indicator ---
function showToolExecution(toolName, args, status) {
    var container = document.getElementById('chatMessages');
    if (!container) return;
    
    var toolId = 'tool-' + Date.now();
    var icon = 'fa-cog';
    if (toolName === 'run_command') icon = 'fa-terminal';
    else if (toolName === 'read_file') icon = 'fa-file-alt';
    else if (toolName === 'write_file') icon = 'fa-edit';
    else if (toolName === 'search_code') icon = 'fa-search';
    else if (toolName === 'list_directory') icon = 'fa-folder';
    
    var html = '<div id="' + toolId + '" class="tool-execution-block ' + status + '">';
    html += '<div class="tool-execution-header">';
    html += '<span class="tool-icon"><i class="fas ' + icon + '"></i></span>';
    html += '<span class="tool-name">' + toolName.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase()) + '</span>';
    html += '<span class="tool-status">' + status + '</span>';
    html += '</div>';
    
    if (args && Object.keys(args).length > 0) {
        html += '<div class="tool-args">';
        for (var key in args) {
            if (args.hasOwnProperty(key)) {
                html += '<span class="tool-arg"><strong>' + key + ':</strong> ' + escapeHtml(String(args[key]).substring(0, 100)) + '</span>';
            }
        }
        html += '</div>';
    }
    
    html += '</div>';
    
    if (currentAssistantMessage) {
        var contentDiv = currentAssistantMessage.querySelector('.message-content');
        if (contentDiv) {
            contentDiv.insertAdjacentHTML('beforeend', html);
        }
    } else {
        container.insertAdjacentHTML('beforeend', html);
    }
    
    container.scrollTop = container.scrollHeight;
    return toolId;
}

// --- Accept/Reject Buttons for Changes ---
function showChangeActions(filePath, changes) {
    var container = document.getElementById('chatMessages');
    if (!container) return;
    
    var escapedPath = filePath.replace(/\\/g, '\\\\');
    var actionId = 'change-action-' + Date.now();
    
    var html = '<div id="' + actionId + '" class="change-action-block">';
    html += '<div class="change-action-header">';
    html += '<span class="change-count"><i class="fas fa-file-code"></i> 1 Changed File</span>';
    html += '</div>';
    html += '<div class="change-action-buttons">';
    html += '<button class="change-btn reject" onclick="rejectChange(\'' + actionId + '\', \'' + escapedPath + '\')"><i class="fas fa-times"></i> Reject</button>';
    html += '<button class="change-btn accept" onclick="acceptChange(\'' + actionId + '\', \'' + escapedPath + '\')"><i class="fas fa-check"></i> Accept</button>';
    html += '</div>';
    html += '</div>';
    
    if (currentAssistantMessage) {
        var contentDiv = currentAssistantMessage.querySelector('.message-content');
        if (contentDiv) {
            contentDiv.insertAdjacentHTML('beforeend', html);
        }
    } else {
        container.insertAdjacentHTML('beforeend', html);
    }
    
    container.scrollTop = container.scrollHeight;
}

function acceptChange(actionId, filePath) {
    var actionBlock = document.getElementById(actionId);
    if (actionBlock) {
        actionBlock.innerHTML = '<div class="change-action-result accepted"><i class="fas fa-check-circle"></i> Changes accepted</div>';
    }
    if (bridge) bridge.on_accept_change(filePath);
}

function rejectChange(actionId, filePath) {
    var actionBlock = document.getElementById(actionId);
    if (actionBlock) {
        actionBlock.innerHTML = '<div class="change-action-result rejected"><i class="fas fa-times-circle"></i> Changes rejected</div>';
    }
    if (bridge) bridge.on_reject_change(filePath);
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

// --- Advanced Toolbar Logic ---
document.addEventListener('DOMContentLoaded', function() {
    var agentToggle = document.getElementById('agent-toggle-btn');
    var dropdownTrigger = document.querySelector('.dropdown-trigger');
    var dropdownMenu = document.querySelector('.dropdown-menu');
    var modeItems = document.querySelectorAll('.dropdown-item');
    var currentModeSpan = document.getElementById('current-mode');
    var chatInput = document.getElementById('chatInput');

    // Agent Toggle
    if (agentToggle) {
        agentToggle.addEventListener('click', function() {
            this.classList.toggle('active');
        });
    }

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
            item.onclick = function(e) {
                e.stopPropagation();
                var val = this.dataset.value;
                items.forEach(function(i) { i.classList.remove('active'); });
                this.classList.add('active');
                
                if (modeText) modeText.innerText = val;
                
                // Update trigger icon
                if (modeIcon) {
                    if (val === 'Agent') modeIcon.className = 'fas fa-infinity icon-agent';
                    else if (val === 'Ask') modeIcon.className = 'fas fa-comment-dots';
                    else if (val === 'Plan') modeIcon.className = 'fas fa-magic';
                }

                if (bridge) bridge.on_mode_changed(val);
                // Close dropdown immediately
                menu.classList.remove('show');
                menu.style.display = 'none';
            };
        });
    }

    // Model Selector Logic
    var modelDropdown = document.getElementById('model-selector');
    if (modelDropdown) {
        var modelTrigger = modelDropdown.querySelector('.dropdown-trigger');
        var modelMenu = modelDropdown.querySelector('.dropdown-menu');
        var modelItems = modelDropdown.querySelectorAll('.dropdown-item');
        var modelText = document.getElementById('current-model');
        var modelCostDisplay = document.getElementById('current-model-cost');

        modelTrigger.onclick = function(e) {
            e.stopPropagation();
            e.preventDefault();
            
            // Close other dropdowns first
            document.querySelectorAll('.dropdown-menu').forEach(function(m) {
                if (m !== modelMenu) {
                    m.classList.remove('show');
                    m.style.display = 'none';
                }
            });
            
            // Toggle show class
            var isShowing = modelMenu.classList.contains('show');
            
            // Hide menu if currently showing
            if (isShowing) {
                modelMenu.classList.remove('show');
                modelMenu.style.display = 'none';
                return;
            }
            
            // Show menu if currently hidden
            // Calculate position - place above the trigger button
            var rect = modelTrigger.getBoundingClientRect();
            var menuWidth = 280; // min-width from CSS
            var menuHeight = 350;
            var margin = 10; // minimum margin from viewport edges
            
            // Position above the trigger with some spacing
            var bottomPosition = window.innerHeight - rect.top + 8;
            var left = rect.left + (rect.width / 2);
            
            // Calculate boundaries to prevent overflow
            var halfMenuWidth = menuWidth / 2;
            var minLeft = margin + halfMenuWidth;
            var maxLeft = window.innerWidth - margin - halfMenuWidth;
            
            // Clamp left position within viewport bounds
            var clampedLeft = Math.max(minLeft, Math.min(left, maxLeft));
            
            // Adjust transform based on how much we had to shift
            var transformOffset = -(left - clampedLeft);
            var transform = 'translateX(calc(-50% + ' + transformOffset + 'px))';
            
            // Set fixed position anchored to bottom
            modelMenu.style.position = 'fixed';
            modelMenu.style.bottom = bottomPosition + 'px';
            modelMenu.style.left = clampedLeft + 'px';
            modelMenu.style.transform = transform;
            modelMenu.style.zIndex = '9999';
            modelMenu.style.top = 'auto';
            modelMenu.style.display = 'block';
            modelMenu.classList.add('show');
        };

        modelItems.forEach(function(item) {
            item.onclick = function(e) {
                e.stopPropagation();
                var modelId = this.dataset.value;
                var perf = this.dataset.perf || '1.0';
                var cost = this.dataset.cost || '$0.27/1M';
                
                // Update UI
                modelItems.forEach(function(i) { i.classList.remove('active'); });
                this.classList.add('active');
                
                // Update display text
                if (modelText) {
                    var modelName = this.querySelector('.item-text span').textContent.split(' ')[0];
                    modelText.innerText = modelName;
                }
                
                // Update cost display
                if (modelCostDisplay) {
                    modelCostDisplay.innerText = cost;
                }

                // Call Python bridge to switch model
                if (window.cortexBridge && window.cortexBridge.on_model_changed) {
                    window.cortexBridge.on_model_changed(modelId, perf, cost);
                    console.log('Model switched to:', modelId);
                } else if (window.bridge && window.bridge.on_model_changed) {
                    window.bridge.on_model_changed(modelId, perf, cost);
                    console.log('Model switched to:', modelId);
                } else {
                    console.log('Bridge not found, model:', modelId);
                }
                
                // Close dropdown immediately
                modelMenu.classList.remove('show');
                modelMenu.style.display = 'none';
                // Reset other inline styles
                modelMenu.style.position = '';
                modelMenu.style.bottom = '';
                modelMenu.style.left = '';
                modelMenu.style.transform = '';
                modelMenu.style.zIndex = '';
                modelMenu.style.top = '';
            };
        });
    }

    // Prevent dropdown menus from closing when clicking inside them
    document.querySelectorAll('.dropdown-menu').forEach(function(menu) {
        menu.addEventListener('click', function(e) {
            e.stopPropagation();
        });
    });

    // Close dropdown on outside click
    document.addEventListener('click', function(e) {
        var menus = document.querySelectorAll('.dropdown-menu');
        menus.forEach(function(m) {
            m.classList.remove('show');
            // Reset inline styles for model dropdown
            if (m.classList.contains('model-dropdown-menu')) {
                m.style.position = '';
                m.style.bottom = '';
                m.style.left = '';
                m.style.transform = '';
                m.style.zIndex = '';
                m.style.top = '';
                m.style.display = '';
            }
        });
    });

    // --- Python Hooks ---
    window.onChunk = onChunk;
    window.onComplete = onComplete;
    window.appendMessage = appendMessage;
    window.setTheme = function (isDark) {
        document.body.className = isDark ? 'dark' : 'light';
    };
    window.focusInput = function () {
        var input = document.getElementById('chatInput');
        if (input) input.focus();
    };

    window.openFile = function(filePath) {
        if (bridge) bridge.on_open_file(filePath);
    };

    window.showTerminal = function() {
        var container = document.getElementById('terminal-container');
        var handle    = document.getElementById('terminal-resize-handle');
        var toggleBtn = document.getElementById('toggle-terminal-btn');
        if (container && !container.classList.contains('open')) {
            container.classList.add('open');
            if (handle) handle.classList.add('visible');
            if (toggleBtn) toggleBtn.classList.add('active');
            setTimeout(function () {
                if (fitAddon) fitAddon.fit();
                if (term) term.focus();
            }, 280);
        }
    };

    window.showDiff = function(filePath) {
        if (bridge) bridge.on_show_diff(filePath);
    };

    window.markFileAccepted = function(filePath) {
        const escapedId = filePath.replace(/[^a-zA-Z0-9]/g, '-');
        const statusEl = document.getElementById('status-' + escapedId);
        if (statusEl) {
            statusEl.innerHTML = '<span class="accepted">✅ Changes applied automatically</span>';
        }
    };

    // --- New Qoder-like Features ---
    window.showTerminalOutput = function(command, output, isRunning) {
        showTerminalOutputInChat(command, output, isRunning);
    };

    window.showFileRef = function(filePath, lineNumber, content) {
        showFileReference(filePath, lineNumber, content);
    };

    window.showToolExec = function(toolName, args, status) {
        return showToolExecution(toolName, args, status);
    };

    window.updateToolStatus = function(toolId, status) {
        var toolBlock = document.getElementById(toolId);
        if (toolBlock) {
            toolBlock.className = 'tool-execution-block ' + status;
            var statusEl = toolBlock.querySelector('.tool-status');
            if (statusEl) {
                statusEl.textContent = status;
            }
        }
    };

    window.showChangeAction = function(filePath, changes) {
        showChangeActions(filePath, changes);
    };

    window.hideInlineTerminal = function() {
        var terminalOutput = document.getElementById('inline-terminal-output');
        if (terminalOutput) {
            terminalOutput.remove();
        }
    };
});
