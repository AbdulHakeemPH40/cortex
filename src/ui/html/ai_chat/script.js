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
    if (!container) return;
    
    // Show the container if hidden
    if (container.style.display === 'none') {
        container.style.display = 'flex';
    }

    var isOpen = container.classList.toggle('open');

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
    
    // Use marked's built-in renderer with minimal overrides
    // marked v15+ uses a different API - we use extensions instead of renderer overrides
    
    // First, let's create a simple extension for code blocks
    marked.use({
        renderer: {
            code: function(token) {
                var code = token.text || '';
                var lang = (token.lang || 'text').toLowerCase();
                
                // Specialized Tree Rendering
                if (lang === 'tree' || (lang === 'plaintext' && (code.includes('├──') || code.includes('└──')))) {
                    return renderProjectTree(code);
                }

                var highlighted;
                try { 
                    highlighted = hljs.highlight(code, { language: hljs.getLanguage(lang) ? lang : 'plaintext' }).value; 
                } catch (e) { 
                    highlighted = escapeHtml(code); 
                }
                var isShell = ['bash', 'sh', 'powershell', 'ps1', 'cmd', 'shell'].includes(lang);
                var runBtn = isShell ? '<button class="run-btn" onclick="runCode(this)" title="Run in terminal"><i class="fas fa-play"></i> Run</button>' : '';
                return '<div class="code-block-container">' +
                    '<div class="code-header">' +
                    '<span class="code-lang">' + lang.toUpperCase() + '</span>' +
                    '<div class="code-actions">' + runBtn + '<button class="copy-btn" onclick="copyToClipboard(this)" title="Copy"><i class="fas fa-copy"></i> Copy</button></div>' +
                    '</div>' +
                    '<pre><code class="hljs language-' + lang + '">' + highlighted + '</code></pre>' +
                    '</div>';
            },
            
            table: function(token) {
                var header = token.header ? '<tr>' + token.header.map(cell => '<th>' + this.parser.parseInline(cell.tokens) + '</th>').join('') + '</tr>' : '';
                var body = token.rows ? token.rows.map(row => '<tr>' + row.map(cell => '<td>' + this.parser.parseInline(cell.tokens) + '</td>').join('') + '</tr>').join('') : '';
                return '<div class="table-wrapper"><table><thead>' + header + '</thead><tbody>' + body + '</tbody></table></div>';
            },
            
            heading: function(token) {
                var text = this.parser.parseInline(token.tokens);
                var depth = token.depth;
                var cleanText = text.replace(/<[^>]+>/g, '');
                var id = cleanText.toLowerCase().replace(/[^\w]+/g, '-');
                return '<h' + depth + ' id="' + id + '" class="md-heading md-h' + depth + '">' + text + '</h' + depth + '>';
            },
            
            listitem: function(token) {
                var text = this.parser.parseInline(token.tokens);
                
                // Check for task list pattern
                var taskMatch = text.match(/^\s*\[([ xX])\]\s*/);
                if (taskMatch) {
                    var isChecked = taskMatch[1].toLowerCase() === 'x';
                    var checkedClass = isChecked ? 'checked' : '';
                    var taskText = text.replace(/^\s*\[([ xX])\]\s*/, '');
                    var checkedIcon = isChecked 
                        ? '<svg class="task-check" width="16" height="16" viewBox="0 0 24 24" fill="currentColor"><path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm-2 15l-5-5 1.41-1.41L10 14.17l7.59-7.59L19 8l-9 9z"/></svg>'
                        : '<svg class="task-circle" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="9"/></svg>';
                    return '<li class="task-item ' + checkedClass + '">' + checkedIcon + '<span class="task-text">' + taskText + '</span></li>';
                }
                return '<li>' + text + '</li>';
            },
            
            codespan: function(token) {
                return '<code class="inline-code">' + escapeHtml(token.text) + '</code>';
            },
            
            link: function(token) {
                var text = this.parser.parseInline(token.tokens);
                var title = token.title ? ' title="' + escapeHtml(token.title) + '"' : '';
                return '<a href="' + token.href + '"' + title + ' target="_blank" rel="noopener">' + text + '</a>';
            },
            
            blockquote: function(token) {
                var text = this.parser.parse(token.tokens);
                return '<blockquote class="md-blockquote">' + text + '</blockquote>';
            },
            
            text: function(token) {
                var text = token.text;
                if (typeof text !== 'string') return text;
                
                // Pattern to detect file paths with optional line numbers
                var filePattern = /(`?)([\w\-/.\\]+\.(?:py|js|ts|jsx|tsx|html|css|scss|java|cpp|c|go|rs|php|rb|swift|kt|json|xml|yaml|yml|md|vue))(?::(\d+))?(`?)/gi;
                
                return text.replace(filePattern, function(match, backtick1, filePath, lineNum, backtick2) {
                    if (backtick1 === '`' && backtick2 === '`') {
                        return match;
                    }
                    var cleanPath = filePath.replace(/\\/g, '/');
                    var fileName = cleanPath.split('/').pop();
                    var lineAttr = lineNum ? ', ' + lineNum : '';
                    var lineDisplay = lineNum ? ':' + lineNum : '';
                    var escapedPath = cleanPath.replace(/'/g, "\\'");
                    return '<span class="file-link" onclick="window.openFile(\'' + escapedPath + '\'' + lineAttr + ')">' +
                           '<i class="fas fa-file-code"></i> ' + fileName + lineDisplay +
                           '</span>';
                });
            }
        }
    });
    
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
    
    // Configure marked with all options
    marked.setOptions({ 
        breaks: true, 
        gfm: true,
        pedantic: false,
        smartLists: true,
        smartypants: false
    });
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
    
    // Mark as ready when everything is loaded
    if (window.markReady) window.markReady();

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
        
        // Smart paste handler - converts copied code to file references
        // Store pending paste text to handle async result from Python
        window._pendingSmartPasteText = null;
        window._smartPasteTimeout = null;
        
        input.onpaste = function(e) {
            e.preventDefault();
            
            // Get pasted content
            var pastedText = (e.clipboardData || window.clipboardData).getData('text');
            
            // Check if it looks like code (multiple lines or contains code patterns)
            var lines = pastedText.split('\n');
            var isCodeLike = lines.length > 2 || 
                            /^(function|def|class|import|from|const|let|var|if|for|while|return|public|private|async|await|switch|case|try|catch)\s/.test(pastedText) ||
                            /[{}\[\]();]/.test(pastedText);
            
            if (isCodeLike && bridge) {
                // Store the text and ask Python to check
                window._pendingSmartPasteText = pastedText;
                
                // Set a timeout to handle case where Python doesn't respond
                window._smartPasteTimeout = setTimeout(function() {
                    if (window._pendingSmartPasteText) {
                        insertTextAtCursor(input, window._pendingSmartPasteText);
                        window._pendingSmartPasteText = null;
                    }
                }, 2000); // 2 second timeout
                
                bridge.on_check_smart_paste(pastedText);
            } else {
                // Not code-like, paste normally
                insertTextAtCursor(input, pastedText);
            }
        };
        
        // Handler called by Python with the result
        window.handleSmartPasteResult = function(result) {
            // Clear the timeout
            if (window._smartPasteTimeout) {
                clearTimeout(window._smartPasteTimeout);
                window._smartPasteTimeout = null;
            }
            
            var input = document.getElementById('chatInput');
            if (!input) return;
            
            var textToInsert;
            
            if (result && result.isMatch) {
                // Insert file reference instead of raw code
                textToInsert = result.filePath.split(/[\\/]/).pop() + ' ' + result.lineRange;
            } else {
                // Paste normally using the stored text
                textToInsert = window._pendingSmartPasteText || '';
            }
            
            if (textToInsert) {
                insertTextAtCursor(input, textToInsert);
            }
            window._pendingSmartPasteText = null;
        };
        
        setTimeout(function () { if (input) input.focus(); }, 200);
    }
    
    // Helper function to insert text at cursor position
    function insertTextAtCursor(textarea, text) {
        var start = textarea.selectionStart;
        var end = textarea.selectionEnd;
        var value = textarea.value;
        
        textarea.value = value.substring(0, start) + text + value.substring(end);
        textarea.selectionStart = textarea.selectionEnd = start + text.length;
        
        // Trigger input event to resize
        textarea.dispatchEvent(new Event('input'));
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
        try {
            content.innerHTML = marked.parse(text);
        } catch (e) {
            console.error('Markdown parse error in appendMessage:', e);
            content.textContent = text;
        }
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
    
    // Show AI thinking animation
    showThinkingIndicator();
    
    bridge.on_message_submitted(text);

    input.value = '';
    input.style.height = 'auto';
    
    // Show stop button, hide send button
    var sendBtn = document.getElementById('sendBtn');
    var stopBtn = document.getElementById('stopBtn');
    if (sendBtn) sendBtn.style.display = 'none';
    if (stopBtn) stopBtn.style.display = 'flex';
}

// --- AI Thinking Grid Animation ---
var thinkingInterval = null;
var thinkingCells = null;
var thinkingStartTime = null;
var thinkingTimerInterval = null;
var explorationItems = [];

function showThinkingAnimation() {
    var container = document.getElementById('chatMessages');
    if (!container) return;
    
    // Remove any existing thinking element
    var existingThinking = document.getElementById('thinking-animation');
    if (existingThinking) existingThinking.remove();
    
    // Record start time
    thinkingStartTime = Date.now();
    explorationItems = [];
    
    // Create modern Qoder-style thinking indicator
    var thinkingEl = document.createElement('div');
    thinkingEl.id = 'thinking-animation';
    thinkingEl.className = 'message-bubble assistant thinking-message-modern';
    thinkingEl.innerHTML = `
        <div class="thinking-header">
            <div class="thinking-icon">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <circle cx="12" cy="12" r="10"></circle>
                    <path d="M12 6v6l4 2"></path>
                </svg>
            </div>
            <span class="thinking-title">Thought</span>
            <span class="thinking-separator">·</span>
            <span class="thinking-timer" id="thinking-timer">0s</span>
        </div>
        <div class="thinking-content-text" id="thinking-main-text">
            Analyzing your request...
        </div>
        <div class="exploration-section" id="exploration-section">
            <div class="exploration-toggle" onclick="toggleExploration()">
                <svg class="exploration-chevron" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="6 9 12 15 18 9"></polyline></svg>
                <span>Exploring</span>
                <span class="exploration-status" id="exploration-status"></span>
            </div>
            <div class="exploration-list" id="exploration-list"></div>
        </div>
        <div class="thinking-dots">
            <span class="dot"></span>
            <span class="dot"></span>
            <span class="dot"></span>
        </div>
    `;
    
    container.appendChild(thinkingEl);
    container.scrollTop = container.scrollHeight;
    
    // Start timer
    thinkingTimerInterval = setInterval(updateThinkingTimer, 1000);
}

function updateThinkingTimer() {
    var timerEl = document.getElementById('thinking-timer');
    if (timerEl && thinkingStartTime) {
        var elapsed = Math.floor((Date.now() - thinkingStartTime) / 1000);
        timerEl.textContent = elapsed + 's';
    }
}

function toggleExploration() {
    var section = document.getElementById('exploration-section');
    if (section) {
        section.classList.toggle('collapsed');
    }
}

function addExplorationItem(icon, text) {
    var list = document.getElementById('exploration-list');
    var status = document.getElementById('exploration-status');
    if (!list) return;
    
    explorationItems.push(text);
    
    var item = document.createElement('div');
    item.className = 'exploration-item';
    item.innerHTML = `<span class="exploration-icon">${icon}</span><span>${escapeHtml(text)}</span>`;
    list.appendChild(item);
    
    // Update status count
    if (status) {
        status.textContent = explorationItems.length + ' action' + (explorationItems.length > 1 ? 's' : '');
    }
    
    // Scroll to show new item
    var container = document.getElementById('chatMessages');
    if (container) container.scrollTop = container.scrollHeight;
}

function addToolResult(icon, text) {
    // Add tool result to the current message or exploration list
    var container = document.getElementById('chatMessages');
    if (!container) return;
    
    // If we have an exploration list, add there
    var list = document.getElementById('exploration-list');
    if (list) {
        var item = document.createElement('div');
        item.className = 'exploration-item tool-result';
        
        // Style based on icon type
        var isError = icon === '❌';
        var iconClass = isError ? 'error-icon' : 'success-icon';
        
        item.innerHTML = `<span class="exploration-icon ${iconClass}">${icon}</span><span class="${isError ? 'error-text' : ''}">${escapeHtml(text)}</span>`;
        list.appendChild(item);
        container.scrollTop = container.scrollHeight;
    }
}

function renderPermissionBlock(permData) {
    // Render tool permission request as a card
    var container = document.getElementById('chatMessages');
    if (!container) return;
    
    removeThinkingIndicator();
    
    // Handle both string and object inputs
    var tools;
    if (typeof permData === 'string') {
        try {
            tools = JSON.parse(permData);
        } catch(e) {
            tools = [{ name: 'Command', info: permData }];
        }
    } else if (Array.isArray(permData)) {
        tools = permData;
    } else if (permData && typeof permData === 'object') {
        tools = [permData];
    } else {
        tools = [{ name: 'Unknown', info: String(permData) }];
    }
    
    var card = document.createElement('div');
    card.className = 'permission-card';
    
    var toolsHtml = tools.map(function(tool) {
        var icon = getToolIcon(tool.name || 'tool');
        return `
            <div class="permission-tool">
                <span class="tool-icon">${icon}</span>
                <div class="tool-details">
                    <span class="tool-name">${escapeHtml(tool.name || 'Tool')}</span>
                    <span class="tool-info">${escapeHtml(tool.info || '')}</span>
                </div>
            </div>
        `;
    }).join('');
    
    card.innerHTML = `
        <div class="permission-header">
            <svg class="permission-icon" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>
            <span class="permission-title">Tool Execution</span>
        </div>
        <div class="permission-tools">
            ${toolsHtml}
        </div>
        <div class="permission-actions">
            <button class="permission-allow" onclick="handlePermissionAllow()">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="20 6 9 17 4 12"/></svg>
                Allow
            </button>
            <button class="permission-deny" onclick="handlePermissionDeny()">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
                Deny
            </button>
        </div>
    `;
    
    container.appendChild(card);
    container.scrollTop = container.scrollHeight;
}

function getToolIcon(toolName) {
    var name = (toolName || '').toLowerCase();
    if (name.includes('read') || name.includes('file')) return '📄';
    if (name.includes('write') || name.includes('edit')) return '✏️';
    if (name.includes('run') || name.includes('command') || name.includes('terminal')) return '⚙️';
    if (name.includes('search') || name.includes('find')) return '🔍';
    if (name.includes('list') || name.includes('dir')) return '📁';
    if (name.includes('git')) return '📦';
    return '🔧';
}

function handlePermissionAllow() {
    if (window.bridge) {
        window.bridge.handle_permission_response(true);
    }
}

function handlePermissionDeny() {
    if (window.bridge) {
        window.bridge.handle_permission_response(false);
    }
}

function updateThinkingText(text) {
    var textEl = document.getElementById('thinking-main-text');
    if (textEl) {
        textEl.textContent = text;
    }
}

function hideThinkingAnimation() {
    var thinkingEl = document.getElementById('thinking-animation');
    if (thinkingEl) {
        thinkingEl.remove();
    }
    
    if (thinkingTimerInterval) {
        clearInterval(thinkingTimerInterval);
        thinkingTimerInterval = null;
    }
    
    thinkingStartTime = null;
    explorationItems = [];
}

function showThinkingIndicator() {
    // Use the new grid animation instead of old dots
    showThinkingAnimation();
}

function removeThinkingIndicator() {
    // Hide the new grid animation
    hideThinkingAnimation();
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

    // Check for permission block (tool approval request)
    if (chunk.includes('<permission>')) {
        var permMatch = chunk.match(/<permission>\n?([\s\S]*?)\n?<\/permission>/);
        if (permMatch) {
            try {
                var permData = JSON.parse(permMatch[1]);
                renderPermissionBlock(permData);
                return;
            } catch (e) {
                console.error("Failed to parse permission block:", e);
            }
        }
    }

    // Check if this is an exploration item (tool execution feedback)
    // These come as emojis: 📁 📄 ✏️ 🔧 ⚙️
    var explorationMatch = chunk.match(/^(📁|📄|✏️|🔧|⚙️)\s*`?([^`\n]+)`?/);
    if (explorationMatch) {
        var icon = explorationMatch[1];
        var text = explorationMatch[2].trim();
        addExplorationItem(icon, text);
        // Don't hide thinking yet - more exploration might come
        return;
    }
    
    // Check for tool result lines (→ or ❌)
    var toolResultMatch = chunk.match(/^(\s*)(→|✓|✏️|🔧|🔍|📊|📋|❌)\s*(.+)$/);
    if (toolResultMatch) {
        var icon = toolResultMatch[2];
        var text = toolResultMatch[3].trim();
        addToolResult(icon, text);
        return;
    }
    
    // Check for exploration section markers
    if (chunk.includes('<exploration>')) {
        updateThinkingText("Exploring project context...");
        return;
    }
    if (chunk.includes('</exploration>')) {
        return; // Just skip the closing tag
    }
    
    // Skip file_edited tags
    if (chunk.includes('<file_edited>') || chunk.includes('</file_edited>')) {
        return;
    }
    
    // If we get actual content, hide thinking and start message
    if (chunk.trim() && !chunk.startsWith('<') && !chunk.includes('→')) {
        removeThinkingIndicator();
    }

    // Terminal output is now shown inline in chat via showTerminalOutputInChat()
    // The terminal panel is only shown when explicitly requested

    if (!currentAssistantMessage) {
        // Remove thinking indicator when first real content arrives
        removeThinkingIndicator();
        
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

    try {
        // Parse markdown content
        var html = marked.parse(currentContent);
        contentDiv.innerHTML = html;
    } catch (e) {
        console.error('Markdown parse error:', e);
        // Fallback to plain text with escaped HTML
        contentDiv.textContent = currentContent;
    }
    
    container.scrollTop = container.scrollHeight;
}

function onComplete() {
    // Remove thinking indicator if still present
    removeThinkingIndicator();
    
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
            try {
                contentDiv.innerHTML = marked.parse(text);
            } catch (e) {
                console.error('Markdown parse error in onComplete:', e);
                contentDiv.textContent = text;
            }
            handlePostRenderSpecialTags(contentDiv);
        }

        if (window.MathJax && window.MathJax.typeset) {
            window.MathJax.typeset([currentAssistantMessage]);
        }
    }
    
    // Reset for next message - but only if not continuing after tools
    // The "[Tools executed, continuing...]" marker indicates tool continuation
    if (!currentContent.includes('[Tools executed, continuing...]')) {
        currentAssistantMessage = null;
        currentContent = "";
    }
    
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
        if (container && !container.classList.contains('open')) {
            // Make sure container is visible
            container.style.display = 'flex';
            container.classList.add('open');
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
    
    // --- Context Bar Functions ---
    window.addContextItem = function(type, name, icon) {
        var contextBar = document.getElementById('context-bar');
        var contextItems = contextBar.querySelector('.context-items');
        if (!contextBar || !contextItems) return;
        
        var item = document.createElement('span');
        item.className = 'context-item';
        item.innerHTML = '<i class="fas fa-' + (icon || 'file') + '"></i> ' + escapeHtml(name);
        item.dataset.type = type;
        item.dataset.name = name;
        
        contextItems.appendChild(item);
        contextBar.style.display = 'flex';
    };
    
    window.clearContextBar = function() {
        var contextBar = document.getElementById('context-bar');
        var contextItems = contextBar.querySelector('.context-items');
        if (contextItems) contextItems.innerHTML = '';
        if (contextBar) contextBar.style.display = 'none';
    };
    
    // Context clear button handler
    var contextClearBtn = document.querySelector('.context-clear');
    if (contextClearBtn) {
        contextClearBtn.onclick = window.clearContextBar;
    }
    
    // --- Message Action Functions ---
    window.copyMessage = function(msgId) {
        var bubble = document.getElementById(msgId);
        if (!bubble) return;
        var content = bubble.querySelector('.message-content');
        if (content) {
            var text = content.innerText;
            navigator.clipboard.writeText(text).then(function() {
                showToast('Copied to clipboard');
            });
        }
    };
    
    window.regenerateMessage = function(msgId) {
        if (bridge && bridge.on_regenerate) {
            bridge.on_regenerate(msgId);
        }
    };
    
    window.insertAtCursor = function(text) {
        if (bridge && bridge.on_insert_at_cursor) {
            bridge.on_insert_at_cursor(text);
        }
    };
    
    // --- Toast Notification ---
    function showToast(message) {
        var existing = document.querySelector('.toast-notification');
        if (existing) existing.remove();
        
        var toast = document.createElement('div');
        toast.className = 'toast-notification';
        toast.textContent = message;
        toast.style.cssText = 'position:fixed;bottom:80px;left:50%;transform:translateX(-50%);background:var(--accent);color:white;padding:8px 16px;border-radius:4px;font-size:12px;z-index:10000;animation:fadeInOut 2s forwards;';
        document.body.appendChild(toast);
        
        setTimeout(function() { toast.remove(); }, 2000);
    }
    
    // Add fadeInOut animation
    var style = document.createElement('style');
    style.textContent = '@keyframes fadeInOut{0%{opacity:0;transform:translateX(-50%) translateY(10px);}10%{opacity:1;transform:translateX(-50%) translateY(0);}90%{opacity:1;transform:translateX(-50%) translateY(0);}100%{opacity:0;transform:translateX(-50%) translateY(-10px);}}';
    document.head.appendChild(style);
    
    // Expose thinking functions for Python bridge (already defined earlier)
    window.startThinking = showThinkingAnimation;
    window.stopThinking = hideThinkingAnimation;
    window.addExploration = addExplorationItem;
    window.updateThinkingText = updateThinkingText;
    window.toggleExploration = toggleExploration;
    
    // --- Project Directory Awareness ---
    window.setProjectInfo = function(name, path) {
        var indicator = document.getElementById('project-indicator');
        var projectName = document.getElementById('project-name');
        
        if (!indicator || !projectName) return;
        
        if (name && name.trim()) {
            projectName.textContent = name;
            indicator.title = path || name;
            indicator.style.display = 'inline-flex';
        } else {
            indicator.style.display = 'none';
        }
    };
    
    window.clearProjectInfo = function() {
        var indicator = document.getElementById('project-indicator');
        if (indicator) {
            indicator.style.display = 'none';
        }
    };
    
    // --- Qoder-Style TODO Section Functions ---
    window.todoItems = [];
    window.changedFiles = [];
    
    window.toggleTodoSection = function() {
        var section = document.getElementById('todo-section');
        if (section) {
            section.classList.toggle('collapsed');
        }
    };
    
    window.toggleChangedFilesSection = function() {
        var section = document.getElementById('changed-files-section');
        if (section) {
            section.classList.toggle('collapsed');
        }
    };
    
    window.setTodos = function(todos) {
        // todos: [{id, content, status: 'PENDING'|'IN_PROGRESS'|'COMPLETE'}]
        window.todoItems = todos || [];
        renderTodos();
    };
    
    window.addTodo = function(id, content, status) {
        var existing = window.todoItems.find(function(t) { return t.id === id; });
        if (existing) {
            existing.content = content;
            existing.status = status;
        } else {
            window.todoItems.push({ id: id, content: content, status: status || 'PENDING' });
        }
        renderTodos();
    };
    
    window.updateTodoStatus = function(id, status) {
        var todo = window.todoItems.find(function(t) { return t.id === id; });
        if (todo) {
            todo.status = status;
            renderTodos();
        }
    };
    
    window.clearTodos = function() {
        window.todoItems = [];
        renderTodos();
    };
    
    function renderTodos() {
        var section = document.getElementById('todo-section');
        var list = document.getElementById('todo-list');
        var status = document.getElementById('todo-status');
        
        if (!section || !list) return;
        
        if (window.todoItems.length === 0) {
            section.style.display = 'none';
            return;
        }
        
        section.style.display = 'block';
        
        var completed = window.todoItems.filter(function(t) { return t.status === 'COMPLETE'; }).length;
        var total = window.todoItems.length;
        
        if (status) {
            if (completed === total && total > 0) {
                status.textContent = total + '/' + total + ' done';
            } else {
                status.textContent = completed + '/' + total + ' done';
            }
        }
        
        list.innerHTML = '';
        window.todoItems.forEach(function(todo) {
            var item = document.createElement('div');
            item.className = 'todo-item';
            if (todo.status === 'COMPLETE') item.className += ' completed';
            if (todo.status === 'IN_PROGRESS') item.className += ' in-progress';
            
            var statusClass = todo.status.toLowerCase().replace('_', '-');
            var statusText = todo.status === 'IN_PROGRESS' ? 'In Progress' : todo.status.charAt(0) + todo.status.slice(1).toLowerCase();
            
            item.innerHTML = 
                '<div class="todo-checkbox"></div>' +
                '<span class="todo-text">' + escapeHtml(todo.content) + '</span>' +
                '<span class="todo-item-status ' + statusClass + '">' + statusText + '</span>';
            
            list.appendChild(item);
        });
    }
    
    // --- Changed Files Functions ---
    window.setChangedFiles = function(files) {
        // files: [{path, name, status: 'modified'|'accepted'|'rejected', type}]
        window.changedFiles = files || [];
        renderChangedFiles();
    };
    
    window.addChangedFile = function(path, name, status, type) {
        var existing = window.changedFiles.find(function(f) { return f.path === path; });
        if (existing) {
            existing.status = status;
        } else {
            window.changedFiles.push({ path: path, name: name || path.split(/[\\/]/).pop(), status: status || 'modified', type: type || 'file' });
        }
        renderChangedFiles();
    };
    
    window.updateFileStatus = function(path, status) {
        var file = window.changedFiles.find(function(f) { return f.path === path; });
        if (file) {
            file.status = status;
            renderChangedFiles();
        }
    };
    
    window.clearChangedFiles = function() {
        window.changedFiles = [];
        renderChangedFiles();
    };
    
    function renderChangedFiles() {
        var section = document.getElementById('changed-files-section');
        var list = document.getElementById('changed-files-list');
        var status = document.getElementById('changed-files-status');
        var actions = document.getElementById('changed-files-actions');
        
        if (!section || !list) return;
        
        if (window.changedFiles.length === 0) {
            section.style.display = 'none';
            return;
        }
        
        section.style.display = 'block';
        
        var allAccepted = window.changedFiles.every(function(f) { return f.status === 'accepted'; });
        var hasPending = window.changedFiles.some(function(f) { return f.status === 'modified'; });
        
        if (status) {
            status.textContent = allAccepted ? 'Accepted' : (hasPending ? 'Pending' : 'Mixed');
            status.style.color = allAccepted ? '#3fb950' : '#d19a66';
        }
        
        if (actions) {
            actions.style.display = hasPending ? 'flex' : 'none';
        }
        
        list.innerHTML = '';
        window.changedFiles.forEach(function(file) {
            var item = document.createElement('div');
            item.className = 'changed-file-item';
            
            var icon = getFileIcon(file.type || file.name);
            var statusClass = file.status;
            var statusDisplay = file.status === 'modified' ? 'M' : (file.status === 'accepted' ? 'Accepted' : file.status);
            
            item.innerHTML = 
                '<span class="file-type-icon">' + icon + '</span>' +
                '<span class="changed-file-name" onclick="window.openFile(\'' + file.path.replace(/\\/g, '\\\\').replace(/'/g, "\\'") + '\')">' + escapeHtml(file.name) + '</span>' +
                '<span class="changed-file-status ' + statusClass + '">' + statusDisplay + '</span>';
            
            list.appendChild(item);
        });
    }
    
    function getFileIcon(nameOrType) {
        var ext = (nameOrType || '').split('.').pop().toLowerCase();
        var icons = {
            'py': '<i class="fab fa-python" style="color:#3776ab;"></i>',
            'js': '<i class="fab fa-js" style="color:#f7df1e;"></i>',
            'ts': '<i class="fab fa-js" style="color:#3178c6;"></i>',
            'html': '<i class="fab fa-html5" style="color:#e34f26;"></i>',
            'css': '<i class="fab fa-css3" style="color:#1572b6;"></i>',
            'json': '<i class="fas fa-brackets-curly" style="color:#cbcb41;"></i>',
            'md': '<i class="fab fa-markdown" style="color:#083fa1;"></i>'
        };
        return icons[ext] || '<i class="fas fa-file-code" style="color:var(--accent);"></i>';
    }
    
    window.acceptAllChanges = function() {
        window.changedFiles.forEach(function(f) { f.status = 'accepted'; });
        renderChangedFiles();
        if (bridge && bridge.on_accept_all_changes) {
            bridge.on_accept_all_changes();
        }
    };
    
    window.rejectAllChanges = function() {
        window.changedFiles.forEach(function(f) { f.status = 'rejected'; });
        renderChangedFiles();
        if (bridge && bridge.on_reject_all_changes) {
            bridge.on_reject_all_changes();
        }
    };
});
