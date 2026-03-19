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
var userScrolled = false; // Track if user manually scrolled

// Smart scroll - only auto-scroll if user is near bottom
function smartScroll(container) {
    if (!container) return;
    
    // Check if user is near bottom (within 100px)
    var isNearBottom = container.scrollHeight - container.scrollTop - container.clientHeight < 100;
    
    // Only auto-scroll if user hasn't manually scrolled or is near bottom
    if (!userScrolled || isNearBottom) {
        container.scrollTop = container.scrollHeight;
    }
}

// Track user scroll
function initScrollTracking() {
    var container = document.getElementById('chatMessages');
    if (!container) return;
    
    container.addEventListener('scroll', function() {
        // Check if user scrolled up (not at bottom)
        var isAtBottom = container.scrollHeight - container.scrollTop - container.clientHeight < 50;
        userScrolled = !isAtBottom;
    });
    
    // Reset scroll tracking when new message starts
    container.addEventListener('mousedown', function() {
        userScrolled = false;
    });
}

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
                
                // Regular list item - text is already parsed by parseInline
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
            }
        },
        tokenizer: {
            inlineText: function(src) {
                // Default inline text handling
                var defaultTokenizer = marked.Renderer.prototype;
                var match = src.match(/^([^\n]+)/);
                if (match) {
                    return {
                        type: 'text',
                        raw: match[0],
                        text: match[0]
                    };
                }
                return false;
            }
        }
    });
    
    // Add extension for file link detection (runs after default parsing)
    marked.use({
        renderer: {
            text: function(token) {
                var text = token.text;
                if (typeof text !== 'string') return text;
                
                // First process inline markdown (bold, italic, code)
                text = processInlineMarkdownNoEscape(text);
                
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
    
    // Extract project name from first line if it ends with /
    var projectName = '';
    if (lines.length > 0 && lines[0].endsWith('/')) {
        projectName = lines[0].replace(/\/$/, '');
        lines = lines.slice(1); // Remove first line from processing
    }
    
    // Build tree content
    var treeContent = '';
    lines.forEach(function(line) {
        if (!line.trim()) return;
        
        // Parse tree structure (├──, └──, │, etc.)
        var treeMatch = line.match(/^(\s*)([│├└─\-\s]*)(.*)$/);
        if (!treeMatch) return;
        
        var indent = treeMatch[1].length + treeMatch[2].length;
        var treeChars = treeMatch[2];
        var content = treeMatch[3].trim();
        
        if (!content) return; // Skip empty lines
        
        // Extract comment if present
        var commentSplit = content.split('#');
        var mainContent = commentSplit[0].trim();
        var comment = commentSplit.length > 1 ? '<span class="tree-comment"># ' + escapeHtml(commentSplit[1].trim()) + '</span>' : '';
        
        // Determine if directory or file
        var isDir = mainContent.endsWith('/') || (!mainContent.includes('.') && !mainContent.match(/\.(py|js|md|txt|json|css|html|yml|yaml|xml|sh|bat|ps1)$/i));
        
        // Get file extension for icon
        var ext = '';
        var fileName = mainContent.replace(/\/$/, '');
        if (!isDir && mainContent.includes('.')) {
            ext = mainContent.split('.').pop().toLowerCase();
        }
        
        // File icon based on extension
        var fileIcon = getFileIconForTree(ext, isDir);
        
        // Calculate indent level for responsive display
        var indentLevel = Math.floor(indent / 2);
        var paddingLeft = indentLevel * 20;
        
        treeContent += '<div class="tree-line" style="padding-left: ' + paddingLeft + 'px;">';
        treeContent += '<span class="tree-branch">' + escapeHtml(treeChars) + '</span>';
        treeContent += '<span class="tree-icon">' + fileIcon + '</span>';
        treeContent += '<span class="tree-name">' + escapeHtml(fileName) + '</span>';
        if (comment) {
            treeContent += '<span class="tree-comment-wrapper">' + comment + '</span>';
        }
        treeContent += '</div>';
    });
    
    // Wrap in a nice container like the second image
    var html = '<div class="tree-container">';
    html += '<div class="tree-header">';
    html += '<i class="fas fa-folder-open"></i> ';
    html += '<span>' + (projectName || 'Project Structure') + '</span>';
    html += '</div>';
    html += '<div class="project-tree">' + treeContent + '</div>';
    html += '</div>';
    
    return html;
}

function getFileIconForTree(ext, isDir) {
    if (isDir) {
        return '<i class="fas fa-folder" style="color: #dcb67a;"></i>';
    }
    
    var iconMap = {
        'py': '<i class="fab fa-python" style="color: #3776ab;"></i>',
        'js': '<i class="fab fa-js" style="color: #f7df1e;"></i>',
        'ts': '<i class="fab fa-js" style="color: #3178c6;"></i>',
        'html': '<i class="fab fa-html5" style="color: #e34f26;"></i>',
        'css': '<i class="fab fa-css3-alt" style="color: #264de4;"></i>',
        'md': '<i class="fas fa-file-alt" style="color: #083fa1;"></i>',
        'json': '<i class="fas fa-file-code" style="color: #292929;"></i>',
        'yml': '<i class="fas fa-file-code" style="color: #cb171e;"></i>',
        'yaml': '<i class="fas fa-file-code" style="color: #cb171e;"></i>',
        'txt': '<i class="fas fa-file-alt" style="color: #6b7280;"></i>',
        'sh': '<i class="fas fa-terminal" style="color: #4caf50;"></i>',
        'bat': '<i class="fas fa-terminal" style="color: #4caf50;"></i>',
        'ps1': '<i class="fas fa-terminal" style="color: #4caf50;"></i>',
        'xml': '<i class="fas fa-file-code" style="color: #ff6600;"></i>'
    };
    
    return iconMap[ext] || '<i class="fas fa-file" style="color: #9ca3af;"></i>';
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
    initScrollTracking(); // Initialize scroll tracking
    
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
            if (typeof marked !== 'undefined' && marked.parse) {
                content.innerHTML = marked.parse(text);
            } else {
                content.innerHTML = formatMarkdownFallback(text);
            }
        } catch (e) {
            console.error('Markdown parse error in appendMessage:', e);
            content.innerHTML = formatMarkdownFallback(text);
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
    smartScroll(container);
    
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
    
    // Create Cortex-style thinking indicator with pulsing orb
    var thinkingEl = document.createElement('div');
    thinkingEl.id = 'thinking-animation';
    thinkingEl.className = 'thinking-message';
    thinkingEl.innerHTML = `
        <div class="thinking-orb">
            <div class="thinking-orb-ring"></div>
            <div class="thinking-orb-ring"></div>
            <div class="thinking-orb-core"></div>
        </div>
        <div class="thinking-content">
            <span class="thinking-title">Cortex is thinking</span>
            <span class="thinking-subtitle" id="thinking-main-text">Analyzing your request...</span>
        </div>
        <span class="thinking-timer" id="thinking-timer">0s</span>
    `;
    
    container.appendChild(thinkingEl);
    smartScroll(container);
    
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
        smartScroll(container);
    }
}

function renderPermissionBlock(permData) {
    var container = document.getElementById('chatMessages');
    if (!container) return;
    
    removeThinkingIndicator();
    
    // Get first tool info
    var toolName = 'Tool';
    var toolInfo = '';
    if (Array.isArray(permData) && permData.length > 0) {
        toolName = permData[0].name || 'Tool';
        toolInfo = permData[0].info || '';
    } else if (typeof permData === 'object' && permData !== null) {
        toolName = permData.name || 'Tool';
        toolInfo = permData.info || '';
    }
    
    var card = document.createElement('div');
    card.className = 'permission-card';
    
    card.innerHTML = `
        <div class="permission-header">Tool Execution</div>
        <div class="permission-tool">
            <span class="tool-icon">${getToolIcon(toolName)}</span>
            <span class="tool-name">${escapeHtml(toolName)}</span>
            <span class="tool-info">${escapeHtml(toolInfo)}</span>
        </div>
        <div class="permission-actions">
            <button class="permission-allow" onclick="handlePermissionAllow()">Allow</button>
            <button class="permission-deny" onclick="handlePermissionDeny()">Deny</button>
        </div>
    `;
    
    container.appendChild(card);
    smartScroll(container);
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
    if (window.bridge && window.bridge.handle_permission_response) {
        window.bridge.handle_permission_response(true);
    }
    // Remove the permission card
    var cards = document.querySelectorAll('.permission-card');
    cards.forEach(function(card) {
        card.style.opacity = '0';
        card.style.transform = 'scale(0.95)';
        setTimeout(function() {
            card.remove();
        }, 200);
    });
}

function handlePermissionDeny() {
    if (window.bridge && window.bridge.handle_permission_response) {
        window.bridge.handle_permission_response(false);
    }
    // Remove the permission card
    var cards = document.querySelectorAll('.permission-card');
    cards.forEach(function(card) {
        card.style.opacity = '0';
        card.style.transform = 'scale(0.95)';
        setTimeout(function() {
            card.remove();
        }, 200);
    });
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

// Tool Activity Display - Industry Standard (Cursor/Qoder Style)
var activityStartTime = null;
var thinkingInterval = null;
var currentActivitySection = null;
var fileCount = 0;

function showToolActivity(type, info, status) {
    var container = document.getElementById('chatMessages');
    if (!container) return;
    
    // Always create a fresh activity section or use the current one
    if (!currentActivitySection || !document.body.contains(currentActivitySection)) {
        currentActivitySection = document.createElement('div');
        currentActivitySection.className = 'activity-section';
        fileCount = 0;
        
        // Create collapsible header
        var header = document.createElement('div');
        header.className = 'activity-header';
        header.innerHTML = '<span class="activity-icon running">↻</span> <span class="activity-title">Exploring</span> <span class="activity-toggle">▼</span>';
        header.style.cursor = 'pointer';
        
        // Click handler for toggle
        header.onclick = function(e) {
            e.stopPropagation();
            var section = this.parentElement;
            var isCollapsed = section.classList.toggle('collapsed');
            var toggle = this.querySelector('.activity-toggle');
            if (toggle) {
                toggle.textContent = isCollapsed ? '▶' : '▼';
            }
        };
        
        currentActivitySection.appendChild(header);
        
        // Create activity list
        var list = document.createElement('div');
        list.className = 'activity-list';
        currentActivitySection.appendChild(list);
        
        container.appendChild(currentActivitySection);
    }
    
    var list = currentActivitySection.querySelector('.activity-list');
    if (!list) return;
    
    // Check if this item already exists (match by type and base filename)
    var existingItem = null;
    var items = list.querySelectorAll('.activity-item');
    var baseInfo = info.split(' ')[0].split('(')[0]; // Get base filename without extras
    
    for (var i = 0; i < items.length; i++) {
        var itemType = items[i].getAttribute('data-type');
        var itemInfo = items[i].getAttribute('data-info');
        var itemBaseInfo = itemInfo ? itemInfo.split(' ')[0].split('(')[0] : '';
        
        // Match by type and base filename
        if (itemType === type && baseInfo && itemBaseInfo && 
            (itemBaseInfo === baseInfo || itemInfo.includes(baseInfo) || info.includes(itemBaseInfo))) {
            existingItem = items[i];
            break;
        }
    }
    
    // If item exists and status is updating to complete, update it
    if (existingItem && status === 'complete') {
        existingItem.className = 'activity-item complete';
        var badge = getStatusBadge(type, info);
        if (badge && !existingItem.querySelector('.activity-badge')) {
            existingItem.innerHTML += '<span class="activity-badge">' + badge + '</span>';
        }
        // Update the text to show completion
        var textEl = existingItem.querySelector('.activity-text');
        if (textEl) {
            textEl.innerHTML = formatActivityLabel(type, info, 'complete');
        }
    } else if (!existingItem) {
        // Track file count for new items
        if (type === 'read_file' || type === 'write_file' || type === 'edit_file') {
            fileCount++;
        }
        
        // Create new activity item
        var item = document.createElement('div');
        item.className = 'activity-item ' + (status || 'running');
        item.setAttribute('data-type', type);
        item.setAttribute('data-info', info);
        
        var icon = getFileIcon(type, info);
        var label = formatActivityLabel(type, info, status);
        
        item.innerHTML = icon + '<span class="activity-text">' + label + '</span>';
        
        if (status === 'complete') {
            var badge = getStatusBadge(type, info);
            if (badge) {
                item.innerHTML += '<span class="activity-badge">' + badge + '</span>';
            }
        }
        
        list.appendChild(item);
    }
    
    // Update header when complete
    if (status === 'complete') {
        var header = currentActivitySection.querySelector('.activity-title');
        if (header && fileCount > 0) {
            header.textContent = 'Explored ' + fileCount + ' file' + (fileCount > 1 ? 's' : '');
        }
        var iconEl = currentActivitySection.querySelector('.activity-icon');
        if (iconEl) {
            iconEl.textContent = '✓';
            iconEl.className = 'activity-icon complete';
        }
    }
    
    smartScroll(container);
}

function getFileIcon(type, info) {
    // Terminal file operations
    if (type.startsWith('terminal_')) {
        var opType = type.replace('terminal_', '');
        var icons = {
            'create': '<span class="file-icon terminal">+</span>',
            'create_dir': '<span class="file-icon folder">📁</span>',
            'delete': '<span class="file-icon delete">🗑️</span>',
            'delete_dir': '<span class="file-icon delete">🗑️</span>',
            'move': '<span class="file-icon move">→</span>',
            'copy': '<span class="file-icon copy">📋</span>',
            'rename': '<span class="file-icon rename">✎</span>'
        };
        return icons[opType] || '<span class="file-icon terminal">⌘</span>';
    }
    
    if (type === 'read_file' || type === 'write_file' || type === 'edit_file') {
        var ext = info.split('.').pop().toLowerCase();
        var icons = {
            'js': '<span class="file-icon js">JS</span>',
            'py': '<span class="file-icon py">PY</span>',
            'css': '<span class="file-icon css">CSS</span>',
            'html': '<span class="file-icon html">HTML</span>',
            'json': '<span class="file-icon json">JSON</span>',
            'md': '<span class="file-icon md">MD</span>',
            'ts': '<span class="file-icon ts">TS</span>',
            'tsx': '<span class="file-icon tsx">TSX</span>',
            'jsx': '<span class="file-icon jsx">JSX</span>',
            'txt': '<span class="file-icon">TXT</span>',
            'yml': '<span class="file-icon">YML</span>',
            'yaml': '<span class="file-icon">YML</span>',
            'xml': '<span class="file-icon">XML</span>',
            'sh': '<span class="file-icon terminal">SH</span>',
            'bat': '<span class="file-icon terminal">BAT</span>',
            'ps1': '<span class="file-icon terminal">PS1</span>'
        };
        return icons[ext] || '<span class="file-icon">FILE</span>';
    }
    if (type === 'list_directory') return '<span class="file-icon folder">📁</span>';
    if (type === 'run_command') return '<span class="file-icon terminal">⌘</span>';
    if (type === 'search_code') return '<span class="file-icon search">🔍</span>';
    if (type === 'git_status' || type === 'git_diff') return '<span class="file-icon git">GIT</span>';
    if (type === 'thinking') return '<span class="file-icon think">💭</span>';
    return '<span class="file-icon">⚙️</span>';
}

function formatActivityLabel(type, info, status) {
    var runningPrefix = status === 'running' ? '<span class="running-label">Running</span> ' : '';
    
    if (type === 'read_file') {
        return status === 'running' ? runningPrefix + escapeHtml(info) : escapeHtml(info);
    }
    if (type === 'write_file' || type === 'edit_file') {
        return status === 'running' ? runningPrefix + escapeHtml(info) : escapeHtml(info) + ' ✓';
    }
    if (type === 'list_directory') {
        return status === 'running' ? 'Exploring ' + escapeHtml(info) : 'Exploring ' + escapeHtml(info);
    }
    if (type === 'run_command') {
        return runningPrefix + '<code>' + escapeHtml(info) + '</code>' + (status === 'complete' ? ' ✓' : '');
    }
    if (type === 'search_code') {
        return 'Grepped code <code>' + escapeHtml(info) + '</code>';
    }
    if (type === 'git_status') {
        return status === 'running' ? 'Checking status' : 'Status retrieved';
    }
    if (type === 'git_diff') {
        return status === 'running' ? 'Getting diff' : 'Diff retrieved';
    }
    if (type === 'thinking') {
        return 'Thought · ' + info;
    }
    return escapeHtml(info);
}

function getStatusBadge(type, info) {
    if (type === 'edit_file' || type === 'write_file') {
        return '<span class="activity-badge applied">Applied</span>';
    }
    if (type === 'run_command') {
        return '<span class="activity-badge completed">Completed</span>';
    }
    if (type === 'list_directory' && info.includes('items')) {
        return '<span class="activity-badge completed">' + info + '</span>';
    }
    return '';
}

function showThinking() {
    activityStartTime = Date.now();
    var container = document.getElementById('chatMessages');
    if (!container) return;
    
    // Remove any existing thinking indicator
    var existing = document.getElementById('thinking-indicator');
    if (existing) existing.remove();
    
    // Create activity section if needed
    if (!currentActivitySection || !document.body.contains(currentActivitySection)) {
        currentActivitySection = document.createElement('div');
        currentActivitySection.className = 'activity-section';
        fileCount = 0;
        
        var header = document.createElement('div');
        header.className = 'activity-header';
        header.innerHTML = '<span class="activity-icon running">↻</span> <span class="activity-title">Exploring</span> <span class="activity-toggle">▼</span>';
        currentActivitySection.appendChild(header);
        
        var list = document.createElement('div');
        list.className = 'activity-list';
        currentActivitySection.appendChild(list);
        
        container.appendChild(currentActivitySection);
    }
    
    var list = currentActivitySection.querySelector('.activity-list');
    if (!list) return;
    
    var thinkingItem = document.createElement('div');
    thinkingItem.className = 'activity-item thinking';
    thinkingItem.id = 'thinking-indicator';
    thinkingItem.innerHTML = '<span class="thinking-dots">...</span> <span class="activity-text">Thinking</span>';
    
    list.appendChild(thinkingItem);
    smartScroll(container);
    
    // Update thinking duration every second
    thinkingInterval = setInterval(function() {
        var elapsed = Math.floor((Date.now() - activityStartTime) / 1000);
        var item = document.getElementById('thinking-indicator');
        if (item) {
            item.querySelector('.activity-text').textContent = 'Thinking · ' + elapsed + 's';
        }
    }, 1000);
}

function hideThinking() {
    if (thinkingInterval) {
        clearInterval(thinkingInterval);
        thinkingInterval = null;
    }
    var item = document.getElementById('thinking-indicator');
    if (item && activityStartTime) {
        var elapsed = Math.floor((Date.now() - activityStartTime) / 1000);
        item.className = 'activity-item complete';
        item.innerHTML = '<span class="file-icon think">💭</span> <span class="activity-text">Thought · ' + elapsed + 's</span>';
    }
}

function updateActivityHeader(count, status) {
    var header = document.querySelector('.activity-header .activity-title');
    if (header) {
        header.textContent = status === 'complete' ? 'Explored ' + count + ' files' : 'Exploring';
    }
    var icon = document.querySelector('.activity-header .activity-icon');
    if (icon) {
        icon.textContent = status === 'complete' ? '✓' : '↻';
        icon.className = 'activity-icon ' + (status === 'complete' ? 'complete' : 'running');
    }
}

function clearToolActivity() {
    if (currentActivitySection) {
        currentActivitySection.remove();
        currentActivitySection = null;
    }
    fileCount = 0;
    activityStartTime = null;
    if (thinkingInterval) {
        clearInterval(thinkingInterval);
        thinkingInterval = null;
    }
}

function updateToolActivity(itemId, status, newInfo) {
    var item = document.getElementById(itemId);
    if (item) {
        item.className = 'activity-item ' + status;
        if (newInfo) {
            var textEl = item.querySelector('.activity-text');
            if (textEl) textEl.innerHTML = newInfo;
        }
    }
}

// ================================================
// TODO LIST MANAGEMENT - Cursor/Qoder Style
// ================================================

var currentTodoList = [];

function updateTodos(todos, mainTask) {
    if (!todos || !Array.isArray(todos)) return;
    
    var section = document.getElementById('todo-section');
    var list = document.getElementById('todo-list');
    var mainTaskEl = document.getElementById('todo-main-task');
    var progressEl = document.getElementById('todo-progress-count');
    
    if (!section || !list) return;
    
    // If no todos, hide section and clear
    if (todos.length === 0) {
        section.style.display = 'none';
        list.innerHTML = '';
        if (mainTaskEl) mainTaskEl.textContent = '';
        if (progressEl) progressEl.textContent = '0/0';
        currentTodoList = [];
        return;
    }
    
    currentTodoList = todos;
    
    // Show section
    section.style.display = 'block';
    
    // Set main task title
    if (mainTaskEl && mainTask) {
        mainTaskEl.textContent = mainTask;
    }
    
    // Count completed
    var completed = todos.filter(function(t) { return t.status === 'COMPLETE'; }).length;
    var total = todos.length;
    
    if (progressEl) {
        progressEl.textContent = completed + '/' + total;
    }
    
    // Clear and rebuild list
    list.innerHTML = '';
    
    todos.forEach(function(todo) {
        var item = document.createElement('div');
        var statusClass = getStatusClass(todo.status);
        item.className = 'todo-item ' + statusClass;
        item.setAttribute('data-id', todo.id);
        
        item.innerHTML = 
            '<div class="todo-checkbox"></div>' +
            '<span class="todo-text">' + escapeHtml(todo.content) + '</span>';
        
        list.appendChild(item);
    });
}

function getStatusClass(status) {
    switch (status) {
        case 'COMPLETE': return 'completed';
        case 'IN_PROGRESS': return 'in-progress';
        case 'CANCELLED': return 'cancelled';
        default: return 'pending';
    }
}

function toggleTodoSection() {
    var section = document.getElementById('todo-section');
    if (section) {
        section.classList.toggle('collapsed');
    }
}

function clearTodos() {
    var section = document.getElementById('todo-section');
    var list = document.getElementById('todo-list');
    var mainTaskEl = document.getElementById('todo-main-task');
    var progressEl = document.getElementById('todo-progress-count');
    
    if (section) section.style.display = 'none';
    if (list) list.innerHTML = '';
    if (mainTaskEl) mainTaskEl.textContent = '';
    if (progressEl) progressEl.textContent = '0/0';
    
    currentTodoList = [];
}

function startStreaming() {
    var container = document.getElementById('chatMessages');
    if (!container) return;
    
    // Remove thinking indicator
    removeThinkingIndicator();
    
    // Reset activity section for new response
    currentActivitySection = null;
    fileCount = 0;
    
    // Clear previous todos for new response
    clearTodos();
    
    // Create new assistant message bubble
    if (!currentAssistantMessage) {
        currentAssistantMessage = document.createElement('div');
        currentAssistantMessage.className = 'message-bubble assistant';
        var content = document.createElement('div');
        content.className = 'message-content';
        currentAssistantMessage.appendChild(content);
        container.appendChild(currentAssistantMessage);
        currentContent = "";
    }
    
    smartScroll(container);
}

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
        // Ensure marked is available and properly configured
        if (typeof marked === 'undefined' || !marked.parse) {
            console.warn('marked.js not available, using fallback');
            contentDiv.innerHTML = formatMarkdownFallback(currentContent);
            return;
        }
        
        // Parse markdown with marked.js
        var html = marked.parse(currentContent);
        if (!html || html === currentContent) {
            // marked didn't parse, use fallback
            html = formatMarkdownFallback(currentContent);
        }
        contentDiv.innerHTML = html;
        
        // Apply syntax highlighting to code blocks
        if (window.hljs) {
            contentDiv.querySelectorAll('pre code').forEach(function(block) {
                hljs.highlightElement(block);
            });
        }
    } catch (e) {
        console.error('Markdown parse error:', e);
        contentDiv.innerHTML = formatMarkdownFallback(currentContent);
    }
    
    smartScroll(container);
}

// Fallback markdown formatter for when marked.js fails
function formatMarkdownFallback(text) {
    if (!text) return '';
    
    // Process line by line for better control
    var lines = text.split('\n');
    var result = [];
    var inList = false;
    
    for (var i = 0; i < lines.length; i++) {
        var line = lines[i];
        var trimmed = line.trim();
        
        // Headers
        if (trimmed.match(/^#{1,6}\s/)) {
            var level = trimmed.match(/^(#+)/)[1].length;
            var content = trimmed.replace(/^#{1,6}\s*/, '');
            result.push('<h' + level + '>' + processInlineMarkdown(content) + '</h' + level + '>');
            continue;
        }
        
        // List items
        if (trimmed.match(/^[-*]\s/)) {
            if (!inList) {
                result.push('<ul>');
                inList = true;
            }
            var content = trimmed.replace(/^[-*]\s*/, '');
            result.push('<li>' + processInlineMarkdown(content) + '</li>');
            continue;
        } else if (inList) {
            result.push('</ul>');
            inList = false;
        }
        
        // Regular paragraph
        if (trimmed) {
            result.push('<p>' + processInlineMarkdown(line) + '</p>');
        }
    }
    
    if (inList) {
        result.push('</ul>');
    }
    
    return result.join('');
}

// Process inline markdown (bold, italic, code) - for use in text renderer (no HTML escaping)
function processInlineMarkdownNoEscape(text) {
    return text
        // Bold - must come before italic
        .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
        .replace(/__(.+?)__/g, '<strong>$1</strong>')
        // Italic
        .replace(/\*(.+?)\*/g, '<em>$1</em>')
        .replace(/_(.+?)_/g, '<em>$1</em>')
        // Inline code
        .replace(/`([^`]+)`/g, '<code>$1</code>');
}

// Process inline markdown with HTML escaping - for fallback parser
function processInlineMarkdown(text) {
    return text
        // Escape HTML first
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        // Then process inline markdown
        .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
        .replace(/__(.+?)__/g, '<strong>$1</strong>')
        // Italic
        .replace(/\*(.+?)\*/g, '<em>$1</em>')
        .replace(/_(.+?)_/g, '<em>$1</em>')
        // Inline code
        .replace(/`([^`]+)`/g, '<code>$1</code>');
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
                if (typeof marked !== 'undefined' && marked.parse) {
                    contentDiv.innerHTML = marked.parse(text);
                } else {
                    contentDiv.innerHTML = formatMarkdownFallback(text);
                }
            } catch (e) {
                console.error('Markdown parse error in onComplete:', e);
                contentDiv.innerHTML = formatMarkdownFallback(text);
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
    
    smartScroll(container);
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
    
    smartScroll(container);
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
    
    smartScroll(container);
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
    
    smartScroll(container);
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
    window.startStreaming = startStreaming;
    window.onComplete = onComplete;
    window.appendMessage = appendMessage;
    window.clearChatHistory = function() {
        // Clear localStorage chat history
        localStorage.setItem('cortex_chats', '[]');
        chats = [];
        currentChatId = null;
        renderHistoryList();
    };
    window.showToolActivity = showToolActivity;
    window.updateToolActivity = updateToolActivity;
    window.clearToolActivity = clearToolActivity;
    window.showThinking = showThinking;
    window.hideThinking = hideThinking;
    window.updateActivityHeader = updateActivityHeader;
    
    // TODO Functions
    window.updateTodos = updateTodos;
    window.toggleTodoSection = toggleTodoSection;
    window.clearTodos = clearTodos;
    
    window.setTheme = function (isDark) {
        // Preserve the 'loaded' class when changing theme
        var isLoaded = document.body.classList.contains('loaded');
        document.body.className = isDark ? 'dark' : 'light';
        if (isLoaded) {
            document.body.classList.add('loaded');
        }
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
