var bridge = null;
var term = null;
var fitAddon = null;
var currentChatId = null;
var currentProjectPath = ''; // Current project path for isolated chat history
var bridgeReady = false; // Flag to track if bridge is initialized

// Get storage key based on current project
function getStorageKey() {
    if (currentProjectPath) {
        // Normalize path: convert backslashes to forward slashes and lowercase for consistency
        var normalizedPath = currentProjectPath.replace(/\\/g, '/').toLowerCase().trim();
        
        // Use a simple hash function instead of btoa for better compatibility
        var hash = 0;
        for (var i = 0; i < normalizedPath.length; i++) {
            var char = normalizedPath.charCodeAt(i);
            hash = ((hash << 5) - hash) + char;
            hash = hash & hash; // Convert to 32bit integer
        }
        var hashStr = Math.abs(hash).toString(16);
        var key = 'cortex_chats_' + hashStr;
        console.log('[CHAT] Storage key for path "' + currentProjectPath + '" (normalized: "' + normalizedPath + '") = ' + key);
        return key;
    }
    console.log('[CHAT] No project path, using default key');
    return 'cortex_chats';
}

// Load chats for current project
function loadProjectChats() {
    var key = getStorageKey();
    try {
        var data = localStorage.getItem(key);
        console.log('[CHAT] LOAD - Key:', key);
        console.log('[CHAT] LOAD - Data:', data ? 'found (' + data.length + ' chars)' : 'NULL (no saved chats)');
        var parsed = JSON.parse(data || '[]');
        console.log('[CHAT] LOAD - Parsed', parsed.length, 'chat(s)');
        if (parsed.length > 0) {
            parsed.forEach(function(c, i) {
                console.log('[CHAT]   Chat ' + (i+1) + ': "' + c.title + '" with ' + c.messages.length + ' messages');
            });
            return parsed;
        }
        
        // If localStorage is empty or returns NULL, try loading from file
        console.log('[CHAT] LOAD - localStorage empty or no data, trying file-based storage...');
        return loadChatsFromFile();
    } catch (e) {
        console.error('[CHAT] LOAD ERROR:', e.message);
        // On error, try loading from file
        console.log('[CHAT] LOAD - Error in localStorage, trying file-based storage...');
        return loadChatsFromFile();
    }
}

// FILE-BASED FALLBACK - Save chats for current project
function saveProjectChatsToFile(chatList) {
    var key = getStorageKey();
    var data = JSON.stringify(chatList);
    var success = false;
    
    console.log('[CHAT] SAVE FILE - Saving', chatList.length, 'chat(s),', data.length, 'chars');
    
    try {
        if (bridge && typeof bridge.save_chats_to_file === 'function') {
            var result = bridge.save_chats_to_file(key, data);
            if (result === "OK") {
                console.log('[CHAT] SAVE FILE - SUCCESS');
                success = true;
            } else {
                console.error('[CHAT] SAVE FILE - FAILED:', result);
            }
        } else {
            console.warn('[CHAT] SAVE FILE - Bridge not ready');
        }
    } catch (e) {
        console.error('[CHAT] SAVE FILE - ERROR:', e.message);
    }
    
    return success;
}

// FILE-BASED FALLBACK - Load chats from file
function loadChatsFromFile() {
    var key = getStorageKey();
    console.log('[CHAT] LOAD FILE - Key:', key);
    
    if (!bridge || typeof bridge.load_chats_from_file !== 'function') {
        console.warn('[CHAT] LOAD FILE - Bridge not ready');
        return [];
    }
    
    try {
        // The bridge method returns a string directly (synchronous)
        var result = bridge.load_chats_from_file(key);
        console.log('[CHAT] LOAD FILE - Raw result type:', typeof result);
        console.log('[CHAT] LOAD FILE - Raw result:', result);
        
        // If result is a Promise or looks like "[object Promise]", we need to handle it differently
        if (result && result.toString() === '[object Promise]') {
            console.error('[CHAT] LOAD FILE - Got Promise instead of direct result. Bridge not ready.');
            return [];
        }
        
        // Check if we got a valid string result
        if (result && typeof result === 'string' && result !== "[]") {
            console.log('[CHAT] LOAD FILE - Found', result.length, 'chars of data');
            try {
                var parsed = JSON.parse(result);
                console.log('[CHAT] LOAD FILE - Successfully parsed', parsed.length, 'chats');
                return parsed;
            } catch (parseError) {
                console.error('[CHAT] LOAD FILE - JSON parse error:', parseError.message);
                console.error('[CHAT] LOAD FILE - Invalid JSON:', result.substring(0, 100));
            }
        } else if (result === "[]") {
            console.log('[CHAT] LOAD FILE - Empty array returned (no saved chats)');
            return [];
        }
    } catch (e) {
        console.error('[CHAT] LOAD FILE - ERROR:', e.message);
        console.error('[CHAT] LOAD FILE - Error stack:', e.stack);
    }
    
    console.log('[CHAT] LOAD FILE - No data or error occurred');
    return [];
}

// Save chats for current project - saves to both localStorage and file
function saveProjectChats(chatList) {
    var key = getStorageKey();
    var data = JSON.stringify(chatList);
    var saveSuccess = false;
    
    console.log('[CHAT] SAVE - Saving', chatList.length, 'chat(s),', data.length, 'chars');
    
    // Method 1: localStorage (fast but may not persist)
    try {
        localStorage.setItem(key, data);
        var verify = localStorage.getItem(key);
        if (verify) {
            console.log('[CHAT] SAVE - localStorage: OK (' + verify.length + ' chars)');
            saveSuccess = true;
        } else {
            console.error('[CHAT] SAVE - localStorage: FAILED (verify returned null)');
        }
    } catch (e) {
        console.error('[CHAT] SAVE ERROR (localStorage):', e.message);
    }
    
    // Method 2: File-based storage (reliable fallback)
    try {
        if (bridge && typeof bridge.save_chats_to_file === 'function') {
            var result = bridge.save_chats_to_file(key, data);
            if (result === "OK") {
                console.log('[CHAT] SAVE - File backup: SUCCESS');
            } else {
                console.error('[CHAT] SAVE - File backup: FAILED:', result);
            }
        } else {
            console.warn('[CHAT] SAVE - File backup: Bridge not ready');
        }
    } catch (e) {
        console.error('[CHAT] SAVE ERROR (file backup):', e.message);
    }
    
    if (!saveSuccess) {
        console.error('[CHAT] SAVE - ALL METHODS FAILED - chats may be lost on restart!');
    }
    
    return saveSuccess;
}

// Initialize chats as empty - will be loaded when project is set
var chats = [];

var currentAssistantMessage = null;
var currentContent = "";
var renderPending = false;
var lastRenderTime = 0;
var RENDER_INTERVAL = 32; // ~30fps for smooth visual but low CPU
var userScrolled = false; // Track if user manually scrolled
var _taskSummaryBuffer = ""; // Accumulates <task_summary>...</task_summary> during streaming
var _inTaskSummary = false;  // True while receiving a task_summary block

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

                // Just render <pre><code> — let injectCodeBlockHeader() add the header
                var highlighted;
                try {
                    highlighted = hljs.highlight(code, { language: hljs.getLanguage(lang) ? lang : 'plaintext' }).value;
                } catch (e) {
                    highlighted = escapeHtml(code);
                }
                // Store lang as data attribute so injectCodeBlockHeader can read it
                return '<pre data-lang="' + escapeHtml(lang) + '"><code class="hljs language-' + lang + '">' + highlighted + '</code></pre>';
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
    html += '<svg class="tree-header-icon" viewBox="0 0 24 24" fill="currentColor" width="16" height="16"><path d="M20 6h-8l-2-2H4c-1.1 0-1.99.9-1.99 2L2 18c0 1.1.9 2 2 2h16c1.1 0 2-.9 2-2V8c0-1.1-.9-2-2-2zm0 12H4V8h16v10z"/></svg>';
    html += '<span>' + (projectName || 'Project Structure') + '</span>';
    html += '</div>';
    html += '<div class="project-tree">' + treeContent + '</div>';
    html += '</div>';
    
    return html;
}

function getFileIconForTree(ext, isDir) {
    if (isDir) {
        return '<svg viewBox="0 0 24 24" fill="#dcb67a" width="14" height="14"><path d="M10 4H4c-1.1 0-1.99.9-1.99 2L2 18c0 1.1.9 2 2 2h16c1.1 0 2-.9 2-2V8c0-1.1-.9-2-2-2h-8l-2-2z"/></svg>';
    }
    
    var iconMap = {
        'py': '<span class="ft-badge ft-py">PY</span>',
        'js': '<span class="ft-badge ft-js">JS</span>',
        'ts': '<span class="ft-badge ft-ts">TS</span>',
        'html': '<span class="ft-badge ft-html">&lt;&gt;</span>',
        'css': '<span class="ft-badge ft-css">CSS</span>',
        'md': '<span class="ft-badge ft-md">MD</span>',
        'json': '<span class="ft-badge ft-json">{ }</span>',
        'yml': '<span class="ft-badge ft-yaml">YML</span>',
        'yaml': '<span class="ft-badge ft-yaml">YML</span>',
        'txt': '<span class="ft-badge ft-txt">TXT</span>',
        'sh': '<span class="ft-badge ft-sh">SH</span>',
        'bat': '<span class="ft-badge ft-sh">BAT</span>',
        'ps1': '<span class="ft-badge ft-sh">PS1</span>',
        'xml': '<span class="ft-badge ft-xml">XML</span>'
    };
    
    return iconMap[ext] || '<span class="ft-badge ft-default">📄;</span>';
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
            bridgeReady = true;
            var sendBtn = document.getElementById('sendBtn');
            if (sendBtn) sendBtn.disabled = false;

            // Start with empty chat - project-specific history will load when setProjectInfo is called
            console.log('Bridge ready, waiting for setProjectInfo to load project chats');
            if (!currentProjectPath) {
                // Only start a new chat if no project is set yet
                startNewChat();
            }
        });
    } catch (e) {
        console.error("Cortex: Error during QWebChannel init: " + e.message);
        setTimeout(initBridge, 500);
    }
}

// Exposed globally for Python to call with retry logic
window.trySetProjectInfo = function(name, path, retryCount, callback) {
    retryCount = retryCount || 0;
    if (retryCount > 5) {
        console.error('[CHAT] setProjectInfo failed after', retryCount, 'attempts');
        if (callback) callback(false);
        return;
    }
    
    if (window.setProjectInfo) {
        console.log('[CHAT] Python calling setProjectInfo (attempt', retryCount + 1, ')');
        window.setProjectInfo(name, path);
        if (callback) callback(true);
    } else {
        console.log('[CHAT] setProjectInfo not ready, retrying in 200ms...');
        setTimeout(function() {
            window.trySetProjectInfo(name, path, retryCount + 1, callback);
        }, 200);
    }
};

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
    if (!currentProjectPath) {
        console.log('[CHAT] saveChats: currentProjectPath is empty, cannot save!');
        return;
    }
    console.log('[CHAT] saveChats called, saving', chats.length, 'chats for path:', currentProjectPath);
    saveProjectChats(chats);
    renderHistoryList();
}

function loadChatHistory() {
    chats = loadProjectChats();
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
    // Only save if we have a project path set
    if (currentProjectPath) {
        saveChats();
    }
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

        // ── Enhanced user bubble: text wrap + avatar ─────────────────
        var row = document.createElement('div');
        row.className = 'user-msg-row';

        var textWrap = document.createElement('div');
        textWrap.className = 'user-text-wrap';
        textWrap.appendChild(content);

        // Hover copy button (floats above bubble on hover)
        var ub = document.createElement('button');
        ub.className = 'user-copy-btn';
        ub.title = 'Copy message';
        ub.innerHTML = '<svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect width="14" height="14" x="8" y="8" rx="2"/><path d="M4 16c-1.1 0-2-.9-2-2V4c0-1.1.9-2 2-2h10c1.1 0 2 .9 2 2"/></svg> Copy';
        ub.onclick = function(e) { e.stopPropagation(); copyMessage(text, ub); };
        textWrap.appendChild(ub);

        // User avatar
        var av = document.createElement('div');
        av.className = 'user-avatar';
        av.innerHTML = '<svg width="13" height="13" viewBox="0 0 24 24" fill="currentColor"><path d="M12 12c2.21 0 4-1.79 4-4s-1.79-4-4-4-4 1.79-4 4 1.79 4 4 4zm0 2c-2.67 0-8 1.34-8 4v2h16v-2c0-2.66-5.33-4-8-4z"/></svg>';

        row.appendChild(textWrap);
        row.appendChild(av);
        bubble.appendChild(row);
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

        // Copy button for assistant messages
        var copyBtn = document.createElement('button');
        copyBtn.className = 'copy-msg-btn';
        copyBtn.title = 'Copy Message';
        copyBtn.innerHTML = '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect width="14" height="14" x="8" y="8" rx="2" ry="2"></rect><path d="M4 16c-1.1 0-2-.9-2-2V4c0-1.1.9-2 2-2h10c1.1 0 2 .9 2 2"></path></svg>';
        copyBtn.onclick = function(e) {
            e.stopPropagation();
            copyMessage(text, copyBtn);
        };
        bubble.appendChild(copyBtn);
        bubble.appendChild(content);
    }

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
    // Update text if item already exists
    if (existingItem && status === 'complete') {
        existingItem.className = 'activity-item complete';
        var badge = getStatusBadge(type, info);
        if (badge && !existingItem.querySelector('.activity-badge')) {
            existingItem.innerHTML += '<span class="activity-badge">' + badge + '</span>';
        }
        var textEl = existingItem.querySelector('.activity-text');
        if (textEl) {
            textEl.innerHTML = formatActivityLabel(type, info, 'complete');
        }
    } else if (!existingItem) {
        // Track stats for header
        if (!currentActivitySection.stats) {
            currentActivitySection.stats = { reads: 0, edits: 0, other: 0 };
        }
        
        if (type === 'read_file') {
            currentActivitySection.stats.reads++;
            fileCount++;
        } else if (['write_file', 'edit_file', 'inject_after', 'add_import'].includes(type) || type.startsWith('terminal_create') || type.startsWith('terminal_edit')) {
            currentActivitySection.stats.edits++;
            fileCount++;
        } else {
            currentActivitySection.stats.other++;
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
    
    // Update header
    var header = currentActivitySection.querySelector('.activity-title');
    if (header && fileCount > 0) {
        var stats = currentActivitySection.stats || { reads: 0, edits: 0 };
        var summary = 'Explored ' + fileCount + ' file' + (fileCount > 1 ? 's' : '');
        if (status === 'complete') {
            var details = [];
            if (stats.reads > 0) details.push(stats.reads + ' read' + (stats.reads > 1 ? 's' : ''));
            if (stats.edits > 0) details.push(stats.edits + ' edit' + (stats.edits > 1 ? 's' : ''));
            if (details.length > 0) {
                summary += ' (' + details.join(', ') + ')';
            }
        }
        header.textContent = summary;
    }
    
    if (status === 'complete') {
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
    
    if (type === 'read_file' || type === 'write_file' || type === 'edit_file' || type === 'inject_after' || type === 'add_import') {
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
    var isEdit = ['write_file', 'edit_file', 'inject_after', 'add_import'].includes(type) || type.startsWith('terminal_create') || type.startsWith('terminal_edit');
    var labelText = isEdit ? 'Editing...' : 'Running';
    var runningPrefix = status === 'running' ? '<span class="running-label">' + labelText + '</span> ' : '';
    
    var displayInfo = escapeHtml(info);
    
    // Parse +X -Y pattern if present
    var diffMatch = displayInfo.match(/\+(\d+)\s-(\d+)$/);
    if (diffMatch) {
        var added = diffMatch[1];
        var removed = diffMatch[2];
        var countHtml = '<span class="diff-count"><span class="added">+' + added + '</span> <span class="removed">-' + removed + '</span></span>';
        displayInfo = displayInfo.replace(/\+(\d+)\s-(\d+)$/, countHtml);
    }
    
    if (type === 'read_file') {
        return status === 'running' ? runningPrefix + displayInfo : displayInfo;
    }
    if (isEdit) {
        var checkmark = (status === 'complete' && !diffMatch) ? ' ✓' : '';
        return status === 'running' ? runningPrefix + displayInfo : displayInfo + checkmark;
    }
    if (type === 'list_directory') {
        return status === 'running' ? 'Exploring ' + displayInfo : 'Exploring ' + displayInfo;
    }
    if (type === 'run_command') {
        return runningPrefix + '<code>' + displayInfo + '</code>' + (status === 'complete' ? ' ✓' : '');
    }
    if (type === 'search_code') {
        return 'Grepped code <code>' + displayInfo + '</code>';
    }
    if (type === 'git_status') {
        return status === 'running' ? 'Checking status' : 'Status retrieved';
    }
    if (type === 'git_diff') {
        return status === 'running' ? 'Getting diff' : 'Diff retrieved';
    }
    if (type === 'thinking') {
        return 'Thought · ' + displayInfo;
    }
    return displayInfo;
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
    _thinkingStartTime = Date.now();
    var container = document.getElementById('chatMessages');
    if (!container) return;

    // Create assistant message bubble if not exists (activity lives INSIDE it)
    if (!currentAssistantMessage) {
        currentAssistantMessage = document.createElement('div');
        currentAssistantMessage.className = 'message-bubble assistant';
        var content = document.createElement('div');
        content.className = 'message-content';
        currentAssistantMessage.appendChild(content);
        currentContent = '';
        container.appendChild(currentAssistantMessage);
        var emptyState = document.getElementById('empty-state');
        if (emptyState) emptyState.remove();
    }

    // Create activity section INSIDE the message bubble, BEFORE message-content
    if (!currentActivitySection || !currentAssistantMessage.contains(currentActivitySection)) {
        currentActivitySection = document.createElement('div');
        currentActivitySection.className = 'activity-section';
        fileCount = 0;

        var header = document.createElement('div');
        header.className = 'activity-header';
        header.innerHTML =
            '<span class="activity-icon running">↻</span>' +
            '<span class="activity-title">Working</span>' +
            '<span class="activity-toggle">▾</span>';
        header.onclick = function() {
            currentActivitySection.classList.toggle('collapsed');
            var t = header.querySelector('.activity-toggle');
            if (t) t.textContent = currentActivitySection.classList.contains('collapsed') ? '▸' : '▾';
        };

        var list = document.createElement('div');
        list.className = 'activity-list';

        currentActivitySection.appendChild(header);
        currentActivitySection.appendChild(list);

        // Insert BEFORE message-content so activity appears above text
        var msgContent = currentAssistantMessage.querySelector('.message-content');
        currentAssistantMessage.insertBefore(currentActivitySection, msgContent);
    }

    var list = currentActivitySection.querySelector('.activity-list');
    if (!list) return;

    // ── FREEZE any previous thinking item ─────────────────────────────────
    // Convert ALL existing thinking-indicator elements to static state
    var prevThinking = document.getElementById('thinking-indicator');
    if (prevThinking) {
        prevThinking.removeAttribute('id');          // de-register old id
        prevThinking.className = 'activity-item';    // removes 'thinking' class → stops blink
        var dotsEl = prevThinking.querySelector('.thinking-dots');
        if (dotsEl) dotsEl.textContent = '•';       // replace '...' with static bullet
    }

    // ── Add new ACTIVE thinking item at the bottom of the list ────────────
    var thinkingItem = document.createElement('div');
    thinkingItem.className = 'activity-item thinking';
    thinkingItem.id = 'thinking-indicator';
    thinkingItem.innerHTML = '<span class="thinking-dots">...</span> <span class="activity-text">Thinking</span>';
    list.appendChild(thinkingItem);

    // Update thinking duration every second
    if (thinkingInterval) clearInterval(thinkingInterval);
    thinkingInterval = setInterval(function() {
        var elapsed = Math.floor((Date.now() - activityStartTime) / 1000);
        var item = document.getElementById('thinking-indicator');
        if (item) {
            item.querySelector('.activity-text').textContent = 'Thinking · ' + elapsed + 's';
        }
    }, 1000);

    smartScroll(container);
}

function hideThinking() {
    if (thinkingInterval) {
        clearInterval(thinkingInterval);
        thinkingInterval = null;
    }
    var item = document.getElementById('thinking-indicator');
    if (item) {
        item.removeAttribute('id');             // de-register so no stale id lingers
        item.className = 'activity-item';       // removes 'thinking' → stops blink
        var dotsEl = item.querySelector('.thinking-dots');
        if (dotsEl) dotsEl.textContent = '•'; // freeze to static bullet
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
// CREATED FILES CARD - Industry Standard (Cursor Style)
// ================================================

/**
 * Renders a premium "Created Files" card in the AI chat.
 * Called when the AI emits a <task_summary> JSON block on task completion.
 *
 * @param {Object} summaryData - Parsed task_summary JSON: { title, files, message }
 *   files: [{ name, path, action }] where action is "created" | "modified" | "deleted"
 */
function showCreatedFilesCard(summaryData) {
    var container = document.getElementById('chatMessages');
    if (!container || !summaryData) return;

    var files = summaryData.files || [];
    var title  = summaryData.title   || 'Task Complete';
    var msg    = summaryData.message || '';

    // ── Build card element ──────────────────────────────────────────────────
    var card = document.createElement('div');
    card.className = 'created-files-card';
    card.setAttribute('aria-label', 'Files changed by Cortex AI');

    // Header row
    var header = document.createElement('div');
    header.className = 'cfc-header';
    header.innerHTML =
        '<span class="cfc-icon"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/></svg></span>' +
        '<span class="cfc-title">' + escapeHtml(title) + '</span>' +
        '<span class="cfc-count">' + files.length + ' file' + (files.length !== 1 ? 's' : '') + '</span>';
    card.appendChild(header);

    // File list
    var list = document.createElement('div');
    list.className = 'cfc-list';

    files.forEach(function(file) {
        var action = (file.action || 'modified').toLowerCase();
        var name   = file.name   || (file.path ? file.path.split(/[\\/]/).pop() : 'unknown');
        var path   = file.path   || name;

        var row = document.createElement('div');
        row.className = 'cfc-file-row';

        // File icon by extension
        var ext = name.split('.').pop().toLowerCase();
        var fileIconHTML = getCfcFileIcon(ext);

        // Action badge
        var badgeClass = 'cfc-badge-' + action;  // created | modified | deleted
        var badgeLabel = action.charAt(0).toUpperCase() + action.slice(1);

        row.innerHTML =
            '<span class="cfc-file-icon">' + fileIconHTML + '</span>' +
            '<button class="cfc-filename" title="Open ' + escapeHtml(name) + '">' +
                escapeHtml(name) +
            '</button>' +
            '<span class="cfc-badge ' + badgeClass + '">' + badgeLabel + '</span>' +
            '<button class="cfc-diff-btn" title="View diff for ' + escapeHtml(name) + '">DIFF</button>';

        // Click handlers
        var filenameBtn = row.querySelector('.cfc-filename');
        if (filenameBtn) {
            filenameBtn.onclick = (function(p) {
                return function() {
                    if (bridge && bridge.open_file) bridge.open_file(p);
                };
            })(path);
        }

        var diffBtn = row.querySelector('.cfc-diff-btn');
        if (diffBtn) {
            if (action === 'deleted') {
                diffBtn.disabled = true;
                diffBtn.style.opacity = '0.3';
            } else {
                diffBtn.onclick = (function(p) {
                    return function() {
                        if (bridge && bridge.show_diff) bridge.show_diff(p);
                    };
                })(path);
            }
        }

        list.appendChild(row);
    });
    card.appendChild(list);

    // Optional summary message footer
    if (msg) {
        var footer = document.createElement('div');
        footer.className = 'cfc-footer';
        footer.textContent = msg;
        card.appendChild(footer);
    }

    container.appendChild(card);

    // Trigger slide-in animation after paint
    requestAnimationFrame(function() {
        card.classList.add('cfc-visible');
    });

    smartScroll(container);
}

function getCfcFileIcon(ext) {
    var icons = {
        'py':   '<span class="cfc-ext-badge py">PY</span>',
        'js':   '<span class="cfc-ext-badge js">JS</span>',
        'ts':   '<span class="cfc-ext-badge ts">TS</span>',
        'jsx':  '<span class="cfc-ext-badge js">JSX</span>',
        'tsx':  '<span class="cfc-ext-badge ts">TSX</span>',
        'html': '<span class="cfc-ext-badge html">HTML</span>',
        'css':  '<span class="cfc-ext-badge css">CSS</span>',
        'json': '<span class="cfc-ext-badge json">JSON</span>',
        'md':   '<span class="cfc-ext-badge md">MD</span>',
        'txt':  '<span class="cfc-ext-badge">TXT</span>',
        'sh':   '<span class="cfc-ext-badge sh">SH</span>',
        'yml':  '<span class="cfc-ext-badge">YML</span>',
        'yaml': '<span class="cfc-ext-badge">YAML</span>',
    };
    return icons[ext] || '<span class="cfc-ext-badge">FILE</span>';
}

// ================================================
// TODO LIST MANAGEMENT - Cursor/Qoder Style
// ================================================

var currentTodoList = [];

function updateTodos(todos, mainTask) {
    if (!todos || !Array.isArray(todos)) return;

    var section  = document.getElementById('todo-section');
    var list     = document.getElementById('todo-list');
    var previewEl = document.getElementById('todo-preview-text');
    var countEl  = document.getElementById('todo-progress-count');

    if (!section || !list) return;

    if (todos.length === 0) {
        section.style.display = 'none';
        list.innerHTML = '';
        if (previewEl) previewEl.textContent = '';
        if (countEl)   countEl.textContent   = '0/0';
        currentTodoList = [];
        return;
    }

    currentTodoList = todos;
    section.style.display = 'flex';

    var total     = todos.length;
    var completed = todos.filter(function(t) { return t.status === 'COMPLETE'; }).length;

    if (countEl) countEl.textContent = completed + '/' + total;

    // Header preview: first incomplete task text
    if (previewEl) {
        var firstIncomplete = null;
        for (var i = 0; i < todos.length; i++) {
            if (todos[i].status !== 'COMPLETE' && todos[i].status !== 'CANCELLED') {
                firstIncomplete = todos[i];
                break;
            }
        }
        previewEl.textContent = (firstIncomplete || todos[0]).content;
    }

    list.innerHTML = '';
    todos.forEach(function(todo) {
        var item = document.createElement('div');
        var statusLow = todo.status.toLowerCase().replace('_', '');
        item.className = 'todo-item todo-' + statusLow;
        item.dataset.id = todo.id;

        var iconHtml = '';
        switch (todo.status) {
            case 'COMPLETE':
                iconHtml = '<div class="todo-icon todo-icon-done"><svg width="9" height="9" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3.5"><polyline points="20 6 9 17 4 12"/></svg></div>';
                break;
            case 'IN_PROGRESS':
                iconHtml = '<div class="todo-icon todo-icon-progress"><svg width="8" height="8" viewBox="0 0 24 24" fill="currentColor"><circle cx="12" cy="12" r="5"/></svg></div>';
                break;
            case 'CANCELLED':
                iconHtml = '<div class="todo-icon todo-icon-cancelled"><svg width="8" height="8" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg></div>';
                break;
            default:
                iconHtml = '<div class="todo-icon todo-icon-pending"></div>';
        }

        item.innerHTML = iconHtml + '<span class="todo-text">' + escapeHtml(todo.content) + '</span>';
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
    var body    = document.getElementById('todo-body');
    if (!section || !body) return;
    var isExpanded = section.classList.contains('expanded');
    if (isExpanded) {
        section.classList.remove('expanded');
        body.style.display = 'none';
    } else {
        section.classList.add('expanded');
        body.style.display = 'block';
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

    // ── Set thinking start time on first real content chunk ──────────────
    if (!_thinkingStartTime && chunk.trim() && !chunk.startsWith('<')) {
        _thinkingStartTime = Date.now();
    }

    // Check for permission block (tool approval request)
    if (chunk.includes('<permission>')) {
        var permMatch = chunk.match(/<permission>\n?([\s\S]*?)\n?<\/permission>/);
        if (permMatch) {
            try {
                var permData = JSON.parse(permMatch[1]);
                renderPermissionBlock(permData);
                return;
            } catch (e) {
                console.error('Failed to parse permission block:', e);
            }
        }
    }

    // Check if this is an exploration item (tool execution feedback)
    var explorationMatch = chunk.match(/^(📁|📄|✏️|🔧|⚙️)\s*`?([^`\n]+)`?/);
    if (explorationMatch) {
        addExplorationItem(explorationMatch[1], explorationMatch[2].trim());
        return;
    }

    // Check for tool result lines
    var toolResultMatch = chunk.match(/^(\s*)(→|✓|✏️|🔧|🔍|📊|📋|❌)\s*(.+)$/);
    if (toolResultMatch) {
        addToolResult(toolResultMatch[2], toolResultMatch[3].trim());
        return;
    }

    // Skip structural exploration markers (don't show raw XML)
    if (chunk.trim() === '<exploration>' || chunk.trim() === '</exploration>') return;
    if (chunk.includes('<exploration>')) {
        updateThinkingText('Exploring project context...');
        return;
    }
    if (chunk.includes('</exploration>')) return;

    // ── Task Summary: buffer for final card, suppress from stream ────────
    if (chunk.includes('<task_summary>')) _inTaskSummary = true;
    if (_inTaskSummary) {
        _taskSummaryBuffer += chunk;
        if (chunk.includes('</task_summary>')) _inTaskSummary = false;
        return;
    }

    // Hide thinking on first real content
    if (chunk.trim() && !chunk.startsWith('<')) {
        removeThinkingIndicator();
    }

    if (!currentAssistantMessage) {
        currentAssistantMessage = document.createElement('div');
        currentAssistantMessage.className = 'message-bubble assistant';
        var content = document.createElement('div');
        content.className = 'message-content';
        currentAssistantMessage.appendChild(content);
        container.appendChild(currentAssistantMessage);
        currentContent = '';
        var emptyState = document.getElementById('empty-state');
        if (emptyState) emptyState.remove();
    }

    // Accumulate raw content (INCLUDING custom tags — stripped at render time)
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
        // ── 1. Strip ALL custom tags before markdown render ─────────────────
        var cleanText = currentContent
            .replace(/<file_edited>[\s\S]*?<\/file_edited>/g, '')
            .replace(/<exploration>[\s\S]*?<\/exploration>/g, '')
            .replace(/<task_summary>[\s\S]*?<\/task_summary>/g, '')
            .replace(/<tasklist>[\s\S]*?<\/tasklist>/g, '')
            .replace(/<plan>[\s\S]*?<\/plan>/g, '')
            .replace(/<permission>[\s\S]*?<\/permission>/g, '')
            .trim();

        // ── 2. Parse markdown ────────────────────────────────────────────
        var html = '';
        if (typeof marked !== 'undefined' && marked.parse) {
            html = marked.parse(cleanText);
        } else {
            html = formatMarkdownFallback(cleanText);
        }

        // Highlight file creation mentions
        html = highlightFileCreations(html);
        contentDiv.innerHTML = html;

        // ── 3. Syntax highlight (skip already-highlighted blocks) ──────────
        if (window.hljs) {
            contentDiv.querySelectorAll('pre code').forEach(function(block) {
                if (!block.dataset.highlighted) {
                    hljs.highlightElement(block);
                    block.dataset.highlighted = '1';
                }
            });
        }

        // ── 4. Inject code block headers on new blocks ─────────────────
        contentDiv.querySelectorAll('pre code').forEach(function(block) {
            injectCodeBlockHeader(block);
        });

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
    removeThinkingIndicator();
    hideThinking();

    if (currentAssistantMessage) {
        // ── Strip all custom tags for display ─────────────────────────────
        var displayText = currentContent
            .replace(/<task_summary>[\s\S]*?<\/task_summary>/g, '')
            .replace(/<file_edited>[\s\S]*?<\/file_edited>/g, '')
            .replace(/<exploration>[\s\S]*?<\/exploration>/g, '')
            .replace(/<tasklist>[\s\S]*?<\/tasklist>/g, '')
            .replace(/<plan>[\s\S]*?<\/plan>/g, '')
            .replace(/<permission>[\s\S]*?<\/permission>/g, '')
            .trim();

        // ── Save to history ────────────────────────────────────────────
        var chat = chats.find(function(c) { return c.id === currentChatId; });
        if (chat) {
            chat.messages.push({ text: displayText, sender: 'assistant' });
            saveChats();
        }

        // ── Final markdown render ───────────────────────────────────────
        var contentDiv = currentAssistantMessage.querySelector('.message-content');
        if (contentDiv) {
            try {
                contentDiv.innerHTML = (typeof marked !== 'undefined' && marked.parse)
                    ? marked.parse(displayText)
                    : formatMarkdownFallback(displayText);
            } catch (e) {
                contentDiv.innerHTML = formatMarkdownFallback(displayText);
            }

            // ── Code block headers + syntax highlight ───────────────────
            contentDiv.querySelectorAll('pre code').forEach(function(block) {
                if (window.hljs) hljs.highlightElement(block);
                injectCodeBlockHeader(block);
            });
        }

        // ── File edit cards ← KEY FIX ────────────────────────────────
        renderCustomTagsInto(currentAssistantMessage, currentContent);

        // ── Thought duration badge ──────────────────────────────────
        var secs = getThoughtSeconds();
        if (secs >= 1) {
            currentAssistantMessage.appendChild(buildThoughtBadge(secs));
        }
        _thinkingStartTime = null;

        // ── Task summary card ───────────────────────────────────────
        var summaryText = _taskSummaryBuffer || currentContent;
        var summaryMatch = summaryText.match(/<task_summary>([\s\S]*?)<\/task_summary>/);
        if (summaryMatch) {
            try {
                var sd = JSON.parse(summaryMatch[1].trim());
                if (sd && sd.files && sd.files.length > 0) showCreatedFilesCard(sd);
            } catch (e) { /* silent */ }
        }

        if (window.MathJax && window.MathJax.typeset) {
            window.MathJax.typeset([currentAssistantMessage]);
        }
    }

    // ── Reset state ────────────────────────────────────────────────
    currentAssistantMessage = null;
    currentContent          = '';
    _taskSummaryBuffer      = '';
    _inTaskSummary          = false;

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
    if (currentContent.includes('<task_summary>')) handleTaskSummaryTag();
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

    var contentDiv = currentAssistantMessage ? currentAssistantMessage.querySelector('.message-content') : null;
    if (!contentDiv) return;

    // Strip file_edited tags from visible text
    var cleanText = currentContent
        .replace(/<file_edited>[\s\S]*?<\/file_edited>/g, '')
        .trim();
    try {
        contentDiv.innerHTML = (typeof marked !== 'undefined' && marked.parse)
            ? marked.parse(cleanText) : cleanText;
    } catch(e) { contentDiv.innerHTML = cleanText; }

    // Inject code block headers
    contentDiv.querySelectorAll('pre code').forEach(function(block) {
        if (window.hljs) hljs.highlightElement(block);
        injectCodeBlockHeader(block);
    });

    // Append .fec cards below message content
    renderCustomTagsInto(currentAssistantMessage, currentContent);
}

function handleTaskSummaryTag() {
    var startTag = '<task_summary>';
    var endTag = '</task_summary>';
    var startIndex = currentContent.indexOf(startTag);
    var endIndex = currentContent.indexOf(endTag);
    
    var contentDiv = currentAssistantMessage.querySelector('.message-content');
    
    if (startIndex !== -1 && endIndex !== -1) {
        var textBefore = currentContent.substring(0, startIndex);
        var summaryData = currentContent.substring(startIndex + startTag.length, endIndex);
        var textAfter = currentContent.substring(endIndex + endTag.length);
        contentDiv.innerHTML = marked.parse(textBefore) + renderTaskSummary(summaryData) + marked.parse(textAfter);
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
    if (isStreaming) return '<div class="file-edit-inline"><span class="pending">⏳ Editing...</span></div>';
    
    var lines = data.trim().split('\n');
    var filePath = lines[0] || data.trim();
    var fileName = filePath.split('/').pop().split('\\').pop();
    
    // Parse change stats if available (+X -Y format)
    var changeStats = '';
    if (lines.length > 1 && lines[1].match(/[+-]\d+/)) {
        changeStats = lines[1].trim();
    }
    
    var escapedPath = filePath.replace(/\\/g, '\\\\').replace(/'/g, "\\'");
    
    return '<div class="file-edit-card" data-path="' + escapeHtml(filePath) + '">' +
        '<div class="fec-left">' +
          '<svg class="fec-icon" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M11 4H4a2 2 0 00-2 2v14a2 2 0 002 2h14a2 2 0 002-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 013 3L12 15l-4 1 1-4 9.5-9.5z"/></svg>' +
          '<button class="fec-filename" onclick="openFileInEditor(\'' + escapedPath + '\')">' + escapeHtml(fileName) + '</button>' +
          (changeStats ? '<span class="fec-stats">' + escapeHtml(changeStats) + '</span>' : '') +
        '</div>' +
        '<div class="fec-actions">' +
          '<button class="fec-btn fec-diff" onclick="requestDiff(\'' + escapedPath + '\')" title="View diff">Diff</button>' +
          '<button class="fec-btn fec-accept" onclick="acceptFileEdit(\'' + escapedPath + '\', this)" title="Accept changes">✓</button>' +
          '<button class="fec-btn fec-reject" onclick="rejectFileEdit(\'' + escapedPath + '\', this)" title="Reject changes">✗</button>' +
        '</div>' +
    '</div>';
}

// Task Summary Card - displays completion summary
function renderTaskSummary(data) {
    try {
        var summary = typeof data === 'string' ? JSON.parse(data) : data;
        var title = summary.title || 'Task Complete';
        var removed = summary.removed || [];
        var kept = summary.kept || [];
        var files = summary.files || [];
        var message = summary.message || '';
        
        var html = '<div class="task-summary-card">';
        html += '<div class="task-summary-header">✅ ' + escapeHtml(title) + '</div>';
        
        // Removed section
        if (removed.length > 0) {
            html += '<div class="task-summary-section">';
            html += '<div class="task-summary-label">Removed:</div>';
            html += '<ul class="task-summary-list removed">';
            removed.forEach(function(item) {
                html += '<li><span class="item-icon">🗑️</span>' + escapeHtml(item) + '</li>';
            });
            html += '</ul></div>';
        }
        
        // Kept section
        if (kept.length > 0) {
            html += '<div class="task-summary-section">';
            html += '<div class="task-summary-label">Kept:</div>';
            html += '<ul class="task-summary-list kept">';
            kept.forEach(function(item) {
                html += '<li><span class="item-icon">✓</span>' + escapeHtml(item) + '</li>';
            });
            html += '</ul></div>';
        }
        
        // Files section
        if (files.length > 0) {
            html += '<div class="task-summary-section">';
            html += '<div class="task-summary-label">Files:</div>';
            html += '<ul class="task-summary-list files">';
            files.forEach(function(item) {
                var icon = item.action === 'created' ? '📄' : item.action === 'deleted' ? '🗑️' : '📝';
                var status = item.action || 'modified';
                html += '<li><span class="item-icon">' + icon + '</span><code>' + escapeHtml(item.name) + '</code> <span class="file-action">' + status + '</span></li>';
            });
            html += '</ul></div>';
        }
        
        // Final message
        if (message) {
            html += '<div class="task-summary-message">' + escapeHtml(message) + '</div>';
        }
        
        html += '</div>';
        return html;
    } catch (e) {
        console.error('Task summary parse error:', e);
        return '<div class="task-summary-card"><div class="task-summary-header">✅ Task Complete</div></div>';
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

// Highlight file creation mentions with animation
function highlightFileCreations(html) {
    // Pattern: "create the <filename> file" or "creating <filename>" or similar
    // Match inline code that looks like filenames in creation context
    var patterns = [
        // "create the `filename` file" or "creating `filename`"
        { regex: /(create|creating|make|making)\s+(the\s+)?<code>([^<]+)<\/code>\s+(file|with)/gi, className: 'file-creation-highlight' },
        // "`filename` file" when preceded by creation words in same sentence
        { regex: /(I'll|I will|let me|going to)\s+[^.]*?<code>([^<]+\.(js|css|html|py|java|cpp|c|h|ts|jsx|tsx|json|md|txt))<\/code>/gi, className: 'file-creation-highlight' }
    ];
    
    patterns.forEach(function(pattern) {
        html = html.replace(pattern.regex, function(match, p1, p2, filename) {
            // Extract the actual filename from the match
            var actualFilename = filename || p2;
            if (!actualFilename) return match;
            
            return match.replace('<code>' + actualFilename + '</code>', '<code class="file-creation-pulse">' + actualFilename + '</code>');
        });
    });
    
    return html;
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
            menu.style.display = ''; // clear any inline override first
            menu.classList.toggle('show');
        };

        items.forEach(function(item) {
            item.onclick = function(e) {
                e.stopPropagation();
                var val = this.dataset.value;
                items.forEach(function(i) { i.classList.remove('active'); });
                this.classList.add('active');
                
                if (modeText) modeText.innerText = val;
                
                // Update trigger icon (SVG swap)
                var svgWrap = trigger.querySelector('svg.mode-icon');
                if (svgWrap) {
                    if (val === 'Agent') svgWrap.innerHTML = '<path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm0 4c1.93 0 3.5 1.57 3.5 3.5S13.93 13 12 13s-3.5-1.57-3.5-3.5S10.07 6 12 6zm0 14c-2.03 0-4.43-.82-6.14-2.88C7.55 15.8 9.68 15 12 15s4.45.8 6.14 2.12C16.43 19.18 14.03 20 12 20z"/>';
                    else if (val === 'Ask') svgWrap.innerHTML = '<path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>';
                    else if (val === 'Plan') svgWrap.innerHTML = '<polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"/>';
                }

                if (bridge) bridge.on_mode_changed(val);
                menu.classList.remove('show'); // class only, no inline style
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
    // New method that receives chat data directly from Python
    window.setProjectInfoWithChats = function(name, path, chatsJson) {
        console.log('[CHAT] setProjectInfoWithChats called:', name, path);
        console.log('[CHAT] Received chat data from Python:', chatsJson ? chatsJson.length + ' chars' : 'null');
        
        var indicator = document.getElementById('project-indicator');
        var projectName = document.getElementById('project-name');
        
        if (!indicator || !projectName) {
            console.log('[CHAT] DOM not ready, retrying in 300ms');
            setTimeout(function() {
                window.setProjectInfoWithChats(name, path, chatsJson);
            }, 300);
            return;
        }
        
        if (name && name.trim()) {
            projectName.textContent = name;
            indicator.title = path || name;
            indicator.style.display = 'inline-flex';
            
            // Always load project-specific chat history when path is provided
            if (path) {
                // Set the path first before loading
                currentProjectPath = path;
                console.log('[CHAT] ✅ currentProjectPath SET to:', currentProjectPath);
                
                // Parse the chats data received from Python
                var savedChats = [];
                try {
                    if (chatsJson && chatsJson !== "[]") {
                        savedChats = JSON.parse(chatsJson);
                        console.log('[CHAT] Parsed', savedChats.length, 'chats from Python data');
                    }
                } catch (e) {
                    console.error('[CHAT] Error parsing chats from Python:', e.message);
                }
                
                if (savedChats.length > 0) {
                    // We have saved chats - load them
                    chats = savedChats;
                    currentChatId = null;
                    clearMessages();
                    loadChat(chats[0].id);
                    updateChatList();
                    console.log('[CHAT] Loaded chat with', chats[0].messages.length, 'messages');
                } else {
                    // No saved chats, start fresh
                    // No saved chats, start fresh
                    chats = [];
                    startNewChat();
                    updateChatList();
                    console.log('[CHAT] Started fresh chat for new project');
                }
            }
        } else {
            indicator.style.display = 'none';
        }
    };
    
    // Keep the old method for compatibility
    window.setProjectInfo = function(name, path) {
        console.log('[CHAT] setProjectInfo called:', name, path);
        
        var indicator = document.getElementById('project-indicator');
        var projectName = document.getElementById('project-name');
        
        if (!indicator || !projectName) {
            console.log('[CHAT] DOM not ready, retrying in 300ms');
            setTimeout(function() {
                window.setProjectInfo(name, path);
            }, 300);
            return;
        }
        
        if (name && name.trim()) {
            projectName.textContent = name;
            indicator.title = path || name;
            indicator.style.display = 'inline-flex';
            
            // Always load project-specific chat history when path is provided
            if (path) {
                // Normalize the path for consistent storage key generation
                var normalizedPath = path.replace(/\\/g, '/').toLowerCase().trim();
                var oldNormalizedPath = currentProjectPath ? currentProjectPath.replace(/\\/g, '/').toLowerCase().trim() : '';
                
                console.log('[CHAT] Current path:', currentProjectPath, 'New path:', path);
                console.log('[CHAT] Normalized - Old:', oldNormalizedPath, 'New:', normalizedPath);
                
                // Only reload if path actually changed
                if (normalizedPath !== oldNormalizedPath) {
                    console.log('[CHAT] Path changed, loading project chats...');
                    
                    // Set the path first before loading
                    currentProjectPath = path;
                    console.log('[CHAT] ✅ currentProjectPath SET to:', currentProjectPath);
                    
                    // Load chats for this project
                    var savedChats = loadProjectChats();
                    console.log('[CHAT] Loaded', savedChats.length, 'chats from storage');
                    
                    // If no chats loaded and bridge might not be ready, retry after a delay
                    if (savedChats.length === 0) {
                        console.log('[CHAT] No chats loaded, will retry file loading in 500ms...');
                        setTimeout(function() {
                            var retryChats = loadProjectChats();
                            console.log('[CHAT] Retry: Loaded', retryChats.length, 'chats from storage');
                            if (retryChats.length > 0) {
                                chats = retryChats;
                                currentChatId = null;
                                clearMessages();
                                loadChat(chats[0].id);
                                renderHistoryList();
                                console.log('[CHAT] Retry successful: Loaded chat with', chats[0].messages.length, 'messages');
                            }
                        }, 500);
                    } else {
                        // We have saved chats - load them
                        chats = savedChats;
                        currentChatId = null;
                        clearMessages();
                        loadChat(chats[0].id);
                    renderHistoryList();
                        console.log('[CHAT] Loaded chat with', chats[0].messages.length, 'messages');
                    }
                    renderHistoryList();
                } else {
                    console.log('[CHAT] Path unchanged, keeping current chats');
                }
            }
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
    
    // --- Changed Files registry (new guide-style) ---
    window._cfsCollapsed = true;

    // Expose global toggleChangedFiles for header onclick
    window.toggleChangedFiles = function() {
        var section = document.getElementById('changed-files-section');
        var body    = document.getElementById('cfs-body');
        if (!section || !body) return;
        window._cfsCollapsed = !window._cfsCollapsed;
        if (window._cfsCollapsed) {
            section.classList.remove('expanded');
            body.style.display = 'none';
        } else {
            section.classList.add('expanded');
            body.style.display = 'block';
        }
    };

    // Legacy setChangedFiles kept for compat
    window.setChangedFiles = function() {};
    window.clearChangedFiles = function() {};
    window.updateFileStatus = function() {};
});

// ================================================================
// NEW GUIDE-STYLE CHANGED FILES PANEL
// ================================================================
var _changedFiles = {};  // path -> {added, removed, status, editType}

function addChangedFile(filePath, added, removed, editType) {
    editType = editType || 'M';

    if (_changedFiles[filePath]) {
        _changedFiles[filePath].added   = added;
        _changedFiles[filePath].removed = removed;
        _refreshCfsHeader();
        return;
    }

    _changedFiles[filePath] = { added: added, removed: removed, status: 'pending', editType: editType };

    var section = document.getElementById('changed-files-section');
    var list    = document.getElementById('cfs-list');
    if (!section || !list) return;

    section.style.display = 'flex';

    var fileName    = filePath.split('/').pop().split('\\').pop();
    var esc         = filePath.replace(/'/g, "\\'");
    var badgeClass  = { 'M': 'cfs-badge-m', 'C': 'cfs-badge-c', 'D': 'cfs-badge-d' }[editType] || 'cfs-badge-m';
    var addedHtml   = added   > 0 ? '<span class="cfs-stat-added">+' + added   + '</span>' : '';
    var removedHtml = removed > 0 ? '<span class="cfs-stat-removed">-' + removed + '</span>' : '';

    var row = document.createElement('div');
    row.className = 'cfs-row';
    row.dataset.path = filePath;
    row.innerHTML =
        '<div class="cfs-row-left">' +
            '<div class="cfs-file-icon">' +
                '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">' +
                    '<path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z"/>' +
                    '<polyline points="14 2 14 8 20 8"/>' +
                '</svg>' +
            '</div>' +
            '<button class="cfs-filename" onclick="openFileInEditor(\'' + esc + '\')" title="' + escapeHtml(filePath) + '">' +
                escapeHtml(fileName) +
            '</button>' +
            addedHtml + removedHtml +
            '<span class="cfs-badge ' + badgeClass + '">' + editType + '</span>' +
        '</div>' +
        '<div class="cfs-row-right" id="cfs-row-right-' + _escapeId(filePath) + '">' +
            '<div class="cfs-row-pending-actions">' +
                '<button class="cfs-row-accept-btn" onclick="acceptChangedFile(\'' + esc + '\',this)">\u2713</button>' +
                '<button class="cfs-row-reject-btn" onclick="rejectChangedFile(\'' + esc + '\',this)">\u2717</button>' +
            '</div>' +
        '</div>';

    list.appendChild(row);
    _refreshCfsHeader();
}

function acceptChangedFile(filePath, btn) {
    if (!_changedFiles[filePath]) return;
    _changedFiles[filePath].status = 'accepted';
    var row = document.querySelector('.cfs-row[data-path="' + filePath + '"]');
    if (row) {
        row.classList.add('cfs-accepted');
        var rightEl = row.querySelector('.cfs-row-right');
        if (rightEl) rightEl.innerHTML = '<span class="cfs-row-applied">Applied</span>';
    }
    if (window.bridge) bridge.on_accept_file_edit(filePath);
    _refreshCfsHeader();
    markFileAccepted(filePath);
}

function rejectChangedFile(filePath, btn) {
    if (!_changedFiles[filePath]) return;
    _changedFiles[filePath].status = 'rejected';
    var row = document.querySelector('.cfs-row[data-path="' + filePath + '"]');
    if (row) {
        row.classList.add('cfs-rejected');
        var rightEl = row.querySelector('.cfs-row-right');
        if (rightEl) rightEl.innerHTML = '<span class="cfs-row-rejected-label">Rejected</span>';
    }
    if (window.bridge) bridge.on_reject_file_edit(filePath);
    _refreshCfsHeader();
    markFileRejected(filePath);
}

function acceptAllChanges(e) {
    if (e) e.stopPropagation();
    Object.keys(_changedFiles).forEach(function(p) {
        if (_changedFiles[p].status === 'pending') {
            var btn = document.querySelector('.cfs-row[data-path="' + p + '"] .cfs-row-accept-btn');
            if (btn) acceptChangedFile(p, btn);
        }
    });
}

function rejectAllChanges(e) {
    if (e) e.stopPropagation();
    Object.keys(_changedFiles).forEach(function(p) {
        if (_changedFiles[p].status === 'pending') {
            var btn = document.querySelector('.cfs-row[data-path="' + p + '"] .cfs-row-reject-btn');
            if (btn) rejectChangedFile(p, btn);
        }
    });
}

function _refreshCfsHeader() {
    var files    = Object.values(_changedFiles);
    var total    = files.length;
    var accepted = files.filter(function(f) { return f.status === 'accepted'; }).length;
    var rejected = files.filter(function(f) { return f.status === 'rejected'; }).length;
    var pending  = files.filter(function(f) { return f.status === 'pending'; }).length;

    var countEl  = document.getElementById('cfs-count');
    var statusEl = document.getElementById('cfs-status-text');
    var bulkEl   = document.getElementById('cfs-bulk-btns');

    if (countEl) countEl.textContent = total;

    if (pending > 0) {
        if (statusEl) statusEl.style.display = 'none';
        if (bulkEl)   bulkEl.style.display   = 'flex';
    } else if (total > 0) {
        if (bulkEl) bulkEl.style.display = 'none';
        if (statusEl) {
            statusEl.style.display = '';
            if (rejected === 0)        { statusEl.textContent = 'Accepted'; statusEl.style.color = '#555'; }
            else if (accepted === 0)   { statusEl.textContent = 'Rejected'; statusEl.style.color = '#444'; }
            else { statusEl.textContent = accepted + ' accepted, ' + rejected + ' rejected'; statusEl.style.color = '#555'; }
        }
    }
}

function _escapeId(str) {
    return str.replace(/[^a-zA-Z0-9]/g, '-');
}

// ================================================================
// CURSOR-STYLE FILE EDIT CARD (buildFileEditCard)
// ================================================================
function buildFileEditCard(filePath, added, removed, editType, status) {
    editType = editType || 'M';
    status   = status   || 'pending';

    var fileName = filePath.split('/').pop().split('\\').pop();
    var ext      = fileName.split('.').pop().toLowerCase();
    var esc      = filePath.replace(/'/g, "\\'");

    // ── File type badge (colored, matches Cursor/Qoder) ──────────────────
    var ftBadge = getFileTypeBadge(ext);

    // ── Diff stats ─────────────────────────────────────────────
    var addedHtml   = added   > 0 ? '<span class="fec-added">+'  + added   + '</span>' : '';
    var removedHtml = removed > 0 ? '<span class="fec-removed">-' + removed + '</span>' : '';

    // ── M/C/D badge ─────────────────────────────────────────────
    var mClass = { 'M': 'fec-badge-m', 'C': 'fec-badge-c', 'D': 'fec-badge-d' }[editType] || 'fec-badge-m';

    var isPending  = status === 'pending';
    var isApplied  = status === 'applied';
    var isRejected = status === 'rejected';

    var rightHtml = '';
    if (isPending) {
        rightHtml =
            '<div class="fec-pending-actions">' +
                '<button class="fec-btn-diff"   onclick="requestDiff(\'' + esc + '\',this)">Diff</button>' +
                '<button class="fec-btn-accept" onclick="acceptFileEdit(\'' + esc + '\',this)">Accept</button>' +
                '<button class="fec-btn-reject" onclick="rejectFileEdit(\'' + esc + '\',this)">Reject</button>' +
            '</div>';
    } else if (isApplied) {
        rightHtml = '<span class="fec-status-applied">Applied</span>';
    } else if (isRejected) {
        rightHtml = '<span class="fec-status-rejected">Rejected</span>';
    }

    var card = document.createElement('div');
    card.className = 'fec fec-' + status;
    card.dataset.path   = filePath;
    card.dataset.status = status;

    card.innerHTML =
        '<div class="fec-left">' +
            ftBadge +
            '<button class="fec-name" onclick="openFileInEditor(\'' + esc + '\')" title="' + escapeHtml(filePath) + '">' +
                escapeHtml(fileName) +
            '</button>' +
            addedHtml + removedHtml +
            '<span class="fec-badge ' + mClass + '">' + editType + '</span>' +
        '</div>' +
        '<div class="fec-right">' + rightHtml + '</div>';

    return card;
}

// File type badge — colored, matches Cursor/Qoder Image 1
function getFileTypeBadge(ext) {
    var badges = {
        'js':   '<span class="ft-badge ft-js">JS</span>',
        'jsx':  '<span class="ft-badge ft-js">JSX</span>',
        'ts':   '<span class="ft-badge ft-ts">TS</span>',
        'tsx':  '<span class="ft-badge ft-ts">TSX</span>',
        'py':   '<span class="ft-badge ft-py">PY</span>',
        'html': '<span class="ft-badge ft-html">&lt;&gt;</span>',
        'css':  '<span class="ft-badge ft-css">CSS</span>',
        'scss': '<span class="ft-badge ft-css">SCSS</span>',
        'json': '<span class="ft-badge ft-json">{}</span>',
        'md':   '<span class="ft-badge ft-md">MD</span>',
        'go':   '<span class="ft-badge ft-go">GO</span>',
        'rs':   '<span class="ft-badge ft-rs">RS</span>',
        'java': '<span class="ft-badge ft-java">JV</span>',
        'sh':   '<span class="ft-badge ft-sh">SH</span>'
    };
    return badges[ext] || '<span class="ft-badge ft-default">&#128196;</span>';
}

// ================================================================
// RENDER CUSTOM TAGS INTO MESSAGE (renderCustomTagsInto)
// ================================================================
function renderCustomTagsInto(msgEl, fullText) {
    if (!msgEl || !fullText) return;

    // ── Find or create cards container ────────────────────────────────
    // Works with BOTH .message-bubble AND .msg structures
    var cardsEl = msgEl.querySelector('.msg-cards') ||
                  msgEl.querySelector('.fec-cards-container');

    if (!cardsEl) {
        cardsEl = document.createElement('div');
        cardsEl.className = 'fec-cards-container';
        // Insert AFTER .message-content (or at end of msgEl)
        var contentEl = msgEl.querySelector('.message-content') ||
                        msgEl.querySelector('.msg-content');
        if (contentEl && contentEl.parentNode === msgEl) {
            contentEl.insertAdjacentElement('afterend', cardsEl);
        } else {
            msgEl.appendChild(cardsEl);
        }
    }

    // ── Parse <file_edited> tags ────────────────────────────────────
    var feRe = /<file_edited>([\s\S]*?)<\/file_edited>/g;
    var m;
    while ((m = feRe.exec(fullText)) !== null) {
        var lines = m[1].trim().split('\n')
                        .map(function(l) { return l.trim(); })
                        .filter(Boolean);
        if (!lines[0]) continue;

        var filePath = lines[0];
        var added = 0, removed = 0, editType = 'M';

        if (lines[1]) {
            var fa = lines[1].match(/\+(\d+)/);
            var fr = lines[1].match(/-(\d+)/);
            if (fa) added   = parseInt(fa[1]);
            if (fr) removed = parseInt(fr[1]);
        }
        if (lines[2] && /^[MCD]$/.test(lines[2].toUpperCase())) {
            editType = lines[2].toUpperCase();
        }

        // Don't add duplicate cards for same path
        if (cardsEl.querySelector('[data-path="' + filePath + '"]')) continue;

        var card = buildFileEditCard(filePath, added, removed, editType, 'pending');
        cardsEl.appendChild(card);

        // Also sync to Changed Files panel
        addChangedFile(filePath, added, removed, editType);
    }
}

// ================================================================
// CODE BLOCK HEADER INJECTION
// ================================================================
function injectCodeBlockHeader(codeEl) {
    var pre = codeEl.parentElement;
    if (!pre || pre.tagName !== 'PRE') return;
    if (pre.querySelector('.code-header')) return; // already injected

    // Get language from data attribute or class
    var lang = pre.dataset.lang || '';
    if (!lang) {
        var langClass = null;
        codeEl.classList.forEach(function(c) {
            if (c.startsWith('language-')) langClass = c;
        });
        lang = langClass ? langClass.replace('language-', '') : 'code';
    }

    var escapedCode = codeEl.textContent || '';
    var isShell = ['bash', 'sh', 'powershell', 'ps1', 'cmd', 'shell', 'zsh'].includes(lang);

    var header = document.createElement('div');
    header.className = 'code-header';
    header.innerHTML =
        '<span class="code-lang">' + escapeHtml(lang.toUpperCase()) + '</span>' +
        '<div class="code-actions">' +
            (isShell ? '<button class="code-run-btn" title="Run in terminal">Run</button>' : '') +
            '<button class="code-copy-btn">Copy</button>' +
            '<button class="code-insert-btn">Insert</button>' +
        '</div>';

    header.querySelector('.code-copy-btn').onclick = function() {
        var btn = header.querySelector('.code-copy-btn');
        if (navigator.clipboard) {
            navigator.clipboard.writeText(escapedCode).then(function() {
                btn.textContent = '\u2713 Copied';
                setTimeout(function() { btn.textContent = 'Copy'; }, 1800);
            });
        } else {
            btn.textContent = '\u2713 Copied';
            setTimeout(function() { btn.textContent = 'Copy'; }, 1800);
        }
    };

    header.querySelector('.code-insert-btn').onclick = function() {
        if (window.bridge && bridge.on_insert_code) bridge.on_insert_code(escapedCode, lang);
    };

    if (isShell) {
        header.querySelector('.code-run-btn').onclick = function() {
            if (window.bridge) bridge.on_run_command(escapedCode);
        };
    }

    // Insert header BEFORE the code element, inside pre
    pre.insertBefore(header, codeEl);
    // Remove default top padding (header handles it)
    pre.style.paddingTop = '0';
}

// ================================================================
// GREP CARD
// ================================================================
function buildGrepCard(query, resultCount) {
    var card = document.createElement('div');
    card.className = 'grep-card';
    var shortQuery = (query || '').length > 50 ? (query || '').slice(0, 50) + '...' : (query || '');
    card.innerHTML =
        '<div class="grep-left">' +
            '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">' +
                '<circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/>' +
            '</svg>' +
            '<span class="grep-label">Grepped code</span>' +
        '</div>' +
        '<div class="grep-query">' + escapeHtml(shortQuery) + '</div>' +
        '<div class="grep-count">' + (resultCount || 0) + ' result' + ((resultCount || 0) !== 1 ? 's' : '') + '</div>';
    return card;
}

// ================================================================
// THOUGHT DURATION BADGE
// ================================================================
var _thinkingStartTime = null;

function getThoughtSeconds() {
    if (!_thinkingStartTime) return 0;
    return Math.round((Date.now() - _thinkingStartTime) / 1000);
}

function buildThoughtBadge(seconds) {
    var badge = document.createElement('div');
    badge.className = 'thought-badge';
    badge.innerHTML =
        '<svg class="thought-icon" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">' +
            '<circle cx="12" cy="12" r="9"/><polyline points="12 7 12 12 15 15"/>' +
        '</svg>' +
        '<span class="thought-text">Thought \u00b7 ' + seconds + 's</span>';
    return badge;
}

// ================================================================
// INDUSTRY STANDARD ENHANCEMENTS — CURSOR/QODER PARITY
// ================================================================

// ── FILE EDIT CARD BRIDGE HANDLERS ──────────────────────────────
function openFileInEditor(filePath) {
    if (window.bridge) bridge.on_open_file(filePath);
}

function requestDiff(filePath) {
    if (window.bridge) bridge.on_show_diff(filePath);
}

function acceptFileEdit(filePath, triggerEl) {
    var card = triggerEl
        ? triggerEl.closest('.fec')
        : document.querySelector('.fec[data-path="' + filePath + '"]');

    if (card) {
        card.dataset.status = 'applied';
        card.className = 'fec fec-applied';
        var pa = card.querySelector('.fec-pending-actions');
        var aa = card.querySelector('.fec-applied-status');
        var ra = card.querySelector('.fec-rejected-status');
        if (pa) pa.style.display = 'none';
        if (aa) aa.style.display = '';
        if (ra) ra.style.display = 'none';
    }
    if (window.bridge) bridge.on_accept_file_edit(filePath);
    if (_changedFiles[filePath] && _changedFiles[filePath].status === 'pending') {
        var btn = document.querySelector('.cfs-row[data-path="' + filePath + '"] .cfs-row-accept-btn');
        if (btn) acceptChangedFile(filePath, btn);
    }
}

function rejectFileEdit(filePath, triggerEl) {
    var card = triggerEl
        ? triggerEl.closest('.fec')
        : document.querySelector('.fec[data-path="' + filePath + '"]');

    if (card) {
        card.dataset.status = 'rejected';
        card.className = 'fec fec-rejected';
        var pa = card.querySelector('.fec-pending-actions');
        var aa = card.querySelector('.fec-applied-status');
        var ra = card.querySelector('.fec-rejected-status');
        if (pa) pa.style.display = 'none';
        if (aa) aa.style.display = 'none';
        if (ra) ra.style.display = '';
    }
    if (window.bridge) bridge.on_reject_file_edit(filePath);
    if (_changedFiles[filePath] && _changedFiles[filePath].status === 'pending') {
        var btn = document.querySelector('.cfs-row[data-path="' + filePath + '"] .cfs-row-reject-btn');
        if (btn) rejectChangedFile(filePath, btn);
    }
}

function approveActions(buttonEl) {
    if (window.bridge) bridge.on_approve_tools();
    var block = buttonEl ? buttonEl.closest('.permission-block') : null;
    if (block) {
        var btns = block.querySelector('.perm-buttons');
        if (btns) btns.innerHTML = '<span class="perm-approved">\u2713 Approved \u2014 executing...</span>';
    }
    sendMessage('yes');
}

function denyActions(buttonEl) {
    if (window.bridge) bridge.on_deny_tools();
    sendMessage('no');
}

function approveAlways(buttonEl) {
    if (window.bridge) bridge.on_always_allow();
    approveActions(buttonEl);
}

function undoLastAction() {
    if (window.bridge) bridge.on_undo_action();
}

// Called FROM Python to update file card state
function markFileAccepted(filePath) {
    acceptFileEdit(filePath, null);
}

function markFileRejected(filePath) {
    rejectFileEdit(filePath, null);
}

// ── @ MENTION SYSTEM ────────────────────────────────────────────
var _mentionAtIndex = -1;

function showMentionDropdown(query, atIdx) {
    _mentionAtIndex = atIdx;
    if (window.bridge && bridge.on_search_files) {
        bridge.on_search_files(query || '');
    }
    var dd = document.getElementById('mention-dropdown');
    if (dd) dd.style.display = 'block';
}

function hideMentionDropdown() {
    var dd = document.getElementById('mention-dropdown');
    if (dd) dd.style.display = 'none';
    _mentionAtIndex = -1;
}

// Called FROM Python with matching files
function populateMentionResults(files) {
    var results = document.getElementById('mention-results');
    if (!results) return;
    results.innerHTML = '';
    
    (files || []).slice(0, 8).forEach(function(file) {
        var item = document.createElement('div');
        item.className = 'mention-item';
        item.setAttribute('role', 'option');
        item.innerHTML = 
            '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>' +
            '<span class="mention-filename">' + escapeHtml(file.name || '') + '</span>' +
            '<span class="mention-path">' + escapeHtml(file.rel_path || '') + '</span>';
        item.onclick = function() { selectMention(file); };
        results.appendChild(item);
    });
    
    var dd = document.getElementById('mention-dropdown');
    if (dd) dd.style.display = (files && files.length > 0) ? 'block' : 'none';
}

function selectMention(file) {
    addContextPill(file.name, file.path);
    // Remove @query from input
    var input = document.getElementById('chatInput');
    if (input && _mentionAtIndex !== -1) {
        var val = input.value;
        input.value = val.substring(0, _mentionAtIndex);
    }
    hideMentionDropdown();
    if (input) input.focus();
}

function addContextPill(name, path) {
    var bar = document.getElementById('context-bar');
    if (!bar) return;
    var itemsEl = bar.querySelector('.context-items');
    if (!itemsEl) return;
    // Don't add duplicates
    if (document.querySelector('.context-pill[data-path="' + path + '"]')) return;
    
    var pill = document.createElement('div');
    pill.className = 'context-pill';
    pill.dataset.path = path;
    pill.innerHTML = 
        '<svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z"/></svg>' +
        '<span>' + escapeHtml(name) + '</span>' +
        '<button onclick="removeContextPill(\'' + path.replace(/'/g, "\\'") + '\', this)" aria-label="Remove">&times;</button>';
    
    itemsEl.appendChild(pill);
    bar.style.display = 'flex';
    
    if (window.bridge && bridge.on_add_context_file) bridge.on_add_context_file(path);
}

function removeContextPill(path, buttonEl) {
    var pill = buttonEl ? buttonEl.closest('.context-pill') : document.querySelector('.context-pill[data-path="' + path + '"]');
    if (pill) pill.remove();
    // Hide bar if no more pills
    var bar = document.getElementById('context-bar');
    if (bar && bar.querySelectorAll('.context-pill').length === 0) bar.style.display = 'none';
}

var _mentionSelectedIndex = -1;

function navigateMentionDropdown(direction) {
    var results = document.getElementById('mention-results');
    if (!results) return;
    var items = results.querySelectorAll('.mention-item');
    if (!items.length) return;
    
    _mentionSelectedIndex = Math.max(-1, Math.min(items.length - 1, _mentionSelectedIndex + direction));
    items.forEach(function(it, i) {
        it.classList.toggle('active', i === _mentionSelectedIndex);
    });
}

function selectActiveMentionItem() {
    var results = document.getElementById('mention-results');
    if (!results) return;
    var active = results.querySelector('.mention-item.active');
    if (!active) {
        active = results.querySelector('.mention-item');
    }
    if (active) active.click();
}

// ── TOKEN COUNTER ────────────────────────────────────────────────
function updateTokenCounter() {
    var input = document.getElementById('chatInput');
    if (!input) return;
    var text = input.value;
    var estimate = Math.ceil(text.length / 4);
    var counter = document.getElementById('token-counter');
    if (!counter) {
        counter = document.createElement('span');
        counter.id = 'token-counter';
        counter.className = 'token-counter';
        var container = document.getElementById('input-container');
        if (container) container.appendChild(counter);
    }
    if (estimate > 10) {
        counter.textContent = '~' + estimate + ' tokens';
        counter.style.display = 'inline';
    } else {
        counter.style.display = 'none';
    }
}

// ── SCROLL JUMP BUTTON ───────────────────────────────────────────
function showScrollJumpBtn() {
    if (document.getElementById('scroll-jump-btn')) return;
    var btn = document.createElement('button');
    btn.id = 'scroll-jump-btn';
    btn.className = 'scroll-jump-btn';
    btn.textContent = '\u2193 Jump to latest';
    btn.onclick = function() {
        userScrolled = false;
        var msgs = document.getElementById('chatMessages');
        if (msgs) msgs.scrollTo({ top: msgs.scrollHeight, behavior: 'smooth' });
        btn.remove();
    };
    var chatContainer = document.getElementById('chat-container');
    if (chatContainer) chatContainer.appendChild(btn);
}

function hideScrollJumpBtn() {
    var btn = document.getElementById('scroll-jump-btn');
    if (btn) btn.remove();
}

// ── LIVE TOOL ACTIVITY (onToolActivity from Python bridge) ───────
var TOOL_ICONS = {
    'read_file':      '\ud83d\udcc4',
    'write_file':     '\u270f\ufe0f',
    'edit_file':      '\u270f\ufe0f',
    'list_directory': '\ud83d\udcc1',
    'run_command':    '\u26a1',
    'search_code':    '\ud83d\udd0d',
    'git_status':     '\ud83c\udf3f',
    'git_diff':       '\ud83d\udd00',
    'delete_path':    '\ud83d\uddd1\ufe0f',
    'inject_after':   '\ud83d\udc89',
    'add_import':     '\ud83d\udce6'
};

function onToolActivity(toolType, info, status) {
    // Use existing showToolActivity for compatibility
    if (typeof showToolActivity === 'function') {
        showToolActivity(toolType, info, status);
    }
}

// ── INPUT ENHANCEMENTS: @ DETECTION + TOKEN COUNTER ─────────────
(function setupInputEnhancements() {
    function init() {
        var input = document.getElementById('chatInput');
        if (!input) { setTimeout(init, 100); return; }
        
        input.addEventListener('input', function() {
            updateTokenCounter();
            
            var val = input.value;
            var cursorPos = input.selectionStart;
            var atIdx = val.lastIndexOf('@', cursorPos - 1);
            
            if (atIdx !== -1 && (atIdx === 0 || /\s/.test(val[atIdx - 1]))) {
                var query = val.substring(atIdx + 1, cursorPos);
                if (!query.includes(' ')) {
                    showMentionDropdown(query, atIdx);
                } else {
                    hideMentionDropdown();
                }
            } else {
                hideMentionDropdown();
            }
        });
        
        input.addEventListener('keydown', function(e) {
            var dd = document.getElementById('mention-dropdown');
            if (dd && dd.style.display !== 'none') {
                if (e.key === 'ArrowDown') { e.preventDefault(); navigateMentionDropdown(1); return; }
                if (e.key === 'ArrowUp')   { e.preventDefault(); navigateMentionDropdown(-1); return; }
                if (e.key === 'Enter')     { e.preventDefault(); selectActiveMentionItem(); return; }
                if (e.key === 'Escape')    { hideMentionDropdown(); return; }
            }
        });
        
        // Close dropdown when clicking outside
        document.addEventListener('click', function(e) {
            var dd = document.getElementById('mention-dropdown');
            var inputArea = document.getElementById('input-area');
            if (dd && inputArea && !inputArea.contains(e.target)) {
                hideMentionDropdown();
            }
        });
    }
    init();
})();

// ── SCROLL JUMP BUTTON: show when user scrolls up during streaming ─
(function setupScrollJump() {
    function init() {
        var msgs = document.getElementById('chatMessages');
        if (!msgs) { setTimeout(init, 100); return; }
        msgs.addEventListener('scroll', function() {
            var isNearBottom = msgs.scrollHeight - msgs.scrollTop - msgs.clientHeight < 100;
            if (!isNearBottom && typeof isGenerating !== 'undefined' && isGenerating) {
                showScrollJumpBtn();
            } else if (isNearBottom) {
                hideScrollJumpBtn();
            }
        });
    }
    init();
})();
