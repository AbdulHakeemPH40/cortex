var bridge = null;
var term = null;
var fitAddon = null;
var currentChatId = null;
var currentProjectPath = ''; // Current project path for isolated chat history
var bridgeReady = false; // Flag to track if bridge is initialized
var _terminalBatchBuffer = '';
var _terminalFlushTimeout = null;
var _lastUserMessage = null;
var _lastUserHasImages = false;
var _lastUserImageData = null;
var _rateLimitRetryTimer = null;
var _rateLimitRetryRemaining = 0;

// Initialize batch buffer when DOM is ready
document.addEventListener('DOMContentLoaded', function() {
    _terminalBatchBuffer = '';
    _terminalFlushTimeout = null;
});

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

// --- CHAT PERSISTENCE (Consolidated & Handled for Robust Shutdown) ---

// Load chats for current project - MERGE with SQLite source-of-truth
function loadProjectChats() {
    var key = getStorageKey();
    var lsChats = [];
    try {
        var data = localStorage.getItem(key);
        lsChats = JSON.parse(data || '[]');
        console.log('[CHAT] LOAD LS - Parsed', lsChats.length, 'chat(s) from localStorage');
    } catch (e) {
        console.warn('[CHAT] LOAD LS - Error parsing localStorage:', e.message);
    }
    
    // Load from SQLite (Authority for history)
    var sqlChats = loadChatsFromSQLite() || [];
    console.log('[CHAT] LOAD SQLITE - Found', sqlChats.length, 'chat(s) in SQLite');
    
    if (sqlChats.length === 0) return lsChats;
    
    // Merge: Create a map of LS chats for easy lookup
    var lsMap = {};
    lsChats.forEach(function(c) { 
        if (c && c.id) lsMap[c.id] = c; 
    });
    
    // Build final merged list based on SQLite's authoritative list
    var merged = sqlChats.map(function(sqlChat) {
        var lsChat = lsMap[sqlChat.id];
        if (lsChat) {
            // Update LS chat metadata if SQLite has newer info
            var sqlCount = sqlChat.message_count || 0;
            var lsCount = (lsChat.messages && lsChat.messages.length) || lsChat.message_count || 0;
            
            if (sqlCount > lsCount) {
                console.log('[CHAT]   Chat "' + sqlChat.title + '" has newer messages in SQLite ('+sqlCount+' vs '+lsCount+')');
                lsChat.message_count = sqlCount;
                lsChat.truncated = true; // Mark as needing lazy load
            }
            return lsChat;
        } else {
            // New chat from SQLite that isn't in LS cache
            console.log('[CHAT]   Adding missing chat from SQLite:', sqlChat.title);
            return sqlChat;
        }
    });
    
    // Clean any thinking messages from all chats before returning
    merged.forEach(function(chat) {
        if (chat.messages && chat.messages.length > 0) {
            var originalCount = chat.messages.length;
            chat.messages = chat.messages.filter(function(msg) {
                if (!msg || !msg.text) return true;
                var text = String(msg.text);
                // Filter out thinking/temporary indicators
                var isThinking = text.includes('Thinking') || 
                                 text.includes('Analyzing your request') ||
                                 text.includes('Cortex is working');
                return !isThinking;
            });
            if (chat.messages.length !== originalCount) {
                console.log('[CHAT] CLEANUP - Removed', originalCount - chat.messages.length, 'thinking messages from chat:', chat.title);
            }
        }
    });
    
    return merged;
}

// SQLITE PERSISTENCE - Load chats metadata from SQLite
function loadChatsFromSQLite() {
    var key = getStorageKey();
    if (!bridge || typeof bridge.load_chats_from_sqlite !== 'function') {
        console.warn('[CHAT] LOAD SQLITE - Bridge not ready');
        return [];
    }
    
    try {
        var result = bridge.load_chats_from_sqlite(key);
        if (result && typeof result === 'string' && result !== "[]") {
            var parsed = JSON.parse(result);
            return parsed.map(function(c) {
                return {
                    id: c.id,
                    title: c.title,
                    created_at: c.created_at,
                    message_count: c.message_count || 0,
                    messages: [],
                    loaded: false
                };
            });
        }
    } catch (e) {
        console.error('[CHAT] LOAD SQLITE ERROR:', e.message);
    }
    return [];
}

// CONSOLIDATED SAVE - Captures partial responses and ensures persistence
function saveProjectChats(chatList) {
    if (!chatList || chatList.length === 0) {
        // Even if no chats, signal finish to allow shutdown to proceed
        if (bridge && typeof bridge.on_save_finished === 'function') bridge.on_save_finished("EMPTY");
        return false;
    }
    
    // -- IMPORTANT: Capture partial AI response if streaming during shutdown --
    if (typeof _isGenerating !== 'undefined' && _isGenerating && currentAssistantMessage && currentContent && currentContent.trim()) {
        var chat = chatList.find(function(c) { return c.id == currentChatId; });
        if (chat) {
            var messages = chat.messages || [];
            var lastMsg = messages[messages.length - 1];
            var isDuplicate = lastMsg && (lastMsg.role === 'assistant' || lastMsg.sender === 'assistant') && (lastMsg.text === currentContent || lastMsg.content === currentContent);
            
            if (!isDuplicate) {
                console.log('[CHAT] SAVE - Capturing partial AI response:', currentContent.substring(0, 30) + '...');
                if (!chat.messages) chat.messages = [];
                chat.messages.push({ 
                    text: currentContent, 
                    content: currentContent, 
                    role: 'assistant', 
                    sender: 'assistant',
                    partial: true 
                });
            }
        }
    }
    
    var key = getStorageKey();
    var fullData = JSON.stringify(chatList);
    
    // Truncate for localStorage (performance)
    var MAX_LOCAL_MESSAGES = 50;
    var storageChats = chatList.map(function(chat) {
        var messages = chat.messages || [];
        var msgCount = (typeof chat.message_count === 'number') ? chat.message_count : messages.length;
        return {
            id: chat.id,
            title: chat.title,
            created_at: chat.created_at,
            message_count: msgCount,
            messages: messages.slice(-MAX_LOCAL_MESSAGES),
            truncated: msgCount > MAX_LOCAL_MESSAGES
        };
    });
    var lsData = JSON.stringify(storageChats);
    
    console.log('[CHAT] SAVE - Persisting', chatList.length, 'chat(s) to LS and SQLite');
    
    try {
        localStorage.setItem(key, lsData);
        
        // Priority 1: Save Active Chat (Fast Path)
        var activeChat = chatList.find(function(c) { return c.id === currentChatId; });
        if (activeChat && bridge && typeof bridge.save_single_chat_to_sqlite === 'function') {
            var activeData = JSON.stringify(activeChat);
            bridge.save_single_chat_to_sqlite(key, activeData);
        } else if (bridge && typeof bridge.save_chats_to_sqlite === 'function') {
            // Fallback: Full Sync
            bridge.save_chats_to_sqlite(key, fullData);
        }
    } catch (e) {
        console.error('[CHAT] SAVE ERROR:', e.message);
    }
    
    // CRITICAL: Notify Python bridge that save is complete for shutdown handshake
    if (bridge && typeof bridge.on_save_finished === 'function') {
        bridge.on_save_finished("OK");
    }
    
    return true;
}

// Initialize chats as empty - will be loaded when project is set
var chats = [];

var _stopRequested = false; // Set by stopGeneration to suppress the Python-fired onComplete
var currentAssistantMessage = null;
var currentContent = "";
var renderPending = false;
var lastRenderTime = 0;
var RENDER_INTERVAL = 32; // ~30fps for smooth visual but low CPU
var userScrolled = false; // Track if user manually scrolled
var _taskSummaryBuffer = ""; // Accumulates <task_summary>...</task_summary> during streaming
var _inTaskSummary = false;  // True while receiving a task_summary block


// -- TASK COMPLETION TRACKING -----------------------------------------
var _taskActivities = [];
var _taskStartTime = null;

function startTaskTracking(prompt) {
    _taskActivities = [];
    _taskStartTime = Date.now();
}

function trackActivity(type, detail, status) {
    _taskActivities.push({ type: type, detail: detail, status: status, time: Date.now() });
}

function showTaskCompletionSummary() {
    // Only show if actual work was done (files modified or commands run)
    var filesWritten = _taskActivities.filter(function(a) { return a.type === 'write' || a.type === 'edit'; }).length;
    var commandsRun = _taskActivities.filter(function(a) { return a.type === 'command'; }).length;
    
    // Don't show summary if no real work was done
    if (filesWritten === 0 && commandsRun === 0) {
        _taskActivities = [];
        _taskStartTime = null;
        return;
    }
    
    var container = document.getElementById('chatMessages');
    if (!container) return;
    
    var duration = _taskStartTime ? Math.round((Date.now() - _taskStartTime) / 1000) : 0;
    var filesRead = _taskActivities.filter(function(a) { return a.type === 'read'; }).length;
    var errors = _taskActivities.filter(function(a) { return a.status === 'error'; }).length;
    
    var card = document.createElement('div');
    card.className = 'task-completion-card';
    
    var statusClass = errors > 0 ? 'has-errors' : 'success';
    var statusIcon = errors > 0 ? 'WARN' : 'OK';
    var statusText = errors > 0 ? 'Completed with issues' : 'Task completed';
    
    var html = '<div class="tcc-header ' + statusClass + '">' +
        '<span class="tcc-icon">' + statusIcon + '</span>' +
        '<span class="tcc-title">' + statusText + '</span>' +
        '<span class="tcc-duration">' + duration + 's</span></div>';
    
    html += '<div class="tcc-stats">';
    if (filesRead > 0) html += '<span class="tcc-stat">READ ' + filesRead + ' read</span>';
    if (filesWritten > 0) html += '<span class="tcc-stat">EDIT ' + filesWritten + ' modified</span>';
    if (commandsRun > 0) html += '<span class="tcc-stat">RUN ' + commandsRun + ' commands</span>';
    html += '</div>';
    
    card.innerHTML = html;
    container.appendChild(card);
    card.scrollIntoView({ behavior: 'smooth', block: 'end' });
    
    _taskActivities = [];
    _taskStartTime = null;
}

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
    if (!container) {
        console.warn('[SCROLL] chatMessages element not found, skipping scroll tracking');
        return;
    }
    
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
    
    // Lazy init terminal on first open
    if (!term && container.style.display !== 'flex') {
        initTerminal();
    }
    
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
    
    // marked v4.3.0 renderer API:
    // heading(text, depth, raw, slugger) - text is already parsed HTML
    // listitem(text, task, checked)      - text is already parsed HTML
    // table(header, body)               - both are rendered HTML strings
    // code(code, lang, escaped)         - code is the raw code text
    // codespan(code)                    - code is the raw inline code
    // link(href, title, text)           - three strings
    // blockquote(quote)                 - rendered HTML string
    marked.use({
        renderer: {
            code: function(code, lang, escaped) {
                code = code || '';
                lang = (lang || 'text').toLowerCase();

                // Specialized Tree Rendering
                if (lang === 'tree' || (lang === 'plaintext' && (code.includes('\u251C\u2500\u2500') || code.includes('\u2514\u2500\u2500')))) {
                    return renderProjectTree(code);
                }

                var highlighted;
                try {
                    // Use the improved highlighting with language normalization and embedded support
                    if (window.highlightCodeWithEmbedded) {
                        highlighted = window.highlightCodeWithEmbedded(code, lang);
                    } else {
                        // Fallback to basic highlighting
                        var normalizedLang = window.getNormalizedLanguage ? window.getNormalizedLanguage(lang) : lang;
                        if (hljs.getLanguage(normalizedLang)) {
                            highlighted = hljs.highlight(code, { language: normalizedLang }).value;
                        } else {
                            highlighted = hljs.highlightAuto(code).value;
                        }
                    }
                } catch (e) {
                    highlighted = escapeHtml(code);
                }
                
                // Get display language name (original for display, normalized for hljs class)
                var displayLang = lang;
                var hljsLang = window.getNormalizedLanguage ? window.getNormalizedLanguage(lang) : lang;
                
                return '<pre data-lang="' + escapeHtml(displayLang) + '"><code class="hljs language-' + escapeHtml(hljsLang) + '">' + highlighted + '</code></pre>';
            },

            table: function(header, body) {
                return '<div class="table-wrapper"><table><thead>' + (header || '') + '</thead><tbody>' + (body || '') + '</tbody></table></div>';
            },

            heading: function(text, depth) {
                text = text || '';
                var cleanText = text.replace(/<[^>]+>/g, '');
                var id = cleanText.toLowerCase().replace(/[^\w]+/g, '-');
                return '<h' + depth + ' id="' + id + '" class="md-heading md-h' + depth + '">' + text + '</h' + depth + '>';
            },

            listitem: function(text, task, checked) {
                text = text || '';
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

            codespan: function(code) {
                code = code || '';
                
                // Try to detect language and highlight inline code if it looks like code
                var highlighted = code;
                try {
                    // Check if inline code contains keywords that suggest a language
                    var lang = null;
                    
                    // Python detection
                    if (/\b(def|class|import|from|return|if|elif|else|for|while|try|except|with|lambda)\b/.test(code)) {
                        lang = 'python';
                    }
                    // JavaScript/TypeScript detection
                    else if (/\b(function|const|let|var|=>|async|await|class|interface|type)\b/.test(code)) {
                        lang = code.includes(':') || code.includes('interface') ? 'typescript' : 'javascript';
                    }
                    // HTML detection
                    else if (/&lt;[a-zA-Z][^&>]*&gt;/.test(code) || /<[a-zA-Z][^>]*>/.test(code)) {
                        lang = 'html';
                    }
                    // CSS detection
                    else if (/[.#][a-zA-Z_-]+\s*\{/.test(code) || /:\s*[^;]+;/.test(code)) {
                        lang = 'css';
                    }
                    // Shell/Bash detection
                    else if (/^(npm|yarn|pip|python|node|git|cd|ls|mkdir|rm|cp|mv|cat|echo)\s/.test(code)) {
                        lang = 'bash';
                    }
                    // JSON detection
                    else if (/^\{[\s\S]*\}$|^\[[\s\S]*\]$/.test(code) && /"[^"]+":/.test(code)) {
                        lang = 'json';
                    }
                    // SQL detection
                    else if (/\b(SELECT|INSERT|UPDATE|DELETE|CREATE|TABLE|WHERE|FROM|JOIN)\b/i.test(code)) {
                        lang = 'sql';
                    }
                    
                    // If language detected and it's substantial code (not just a word), highlight it
                    if (lang && (code.includes(' ') || code.includes('\n') || code.includes('(') || code.includes('{'))) {
                        var normalizedLang = window.getNormalizedLanguage ? window.getNormalizedLanguage(lang) : lang;
                        if (hljs.getLanguage(normalizedLang)) {
                            highlighted = hljs.highlight(code, { language: normalizedLang }).value;
                        }
                    }
                } catch (e) {
                    // Keep original code on error
                    highlighted = code;
                }
                
                return '<code class="inline-code' + (lang ? ' inline-code-' + lang : '') + '">' + highlighted + '</code>';
            },

            link: function(href, title, text) {
                var titleAttr = title ? ' title="' + escapeHtml(title) + '"' : '';
                return '<a href="' + (href || '#') + '"' + titleAttr + ' target="_blank" rel="noopener">' + (text || href || '') + '</a>';
            },

            blockquote: function(quote) {
                return '<blockquote class="md-blockquote">' + (quote || '') + '</blockquote>';
            }
        }
    });
    
    // Add extension for file link detection (runs after default parsing)
    marked.use({
        renderer: {
            // In v4.3.0: text(text) receives a string, not a token object
            text: function(text) {
                if (typeof text !== 'string') return text || '';
                    
                // Pattern to detect file paths with optional line numbers
                var filePattern = /(`?)([\.w\-/.\\]+\.(?:py|js|ts|jsx|tsx|html|css|scss|java|cpp|c|go|rs|php|rb|swift|kt|json|xml|yaml|yml|md|vue))(?::(\d+))?(`?)/gi;
                    
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
        
        // Parse tree structure (+--, |, etc.)
        var treeMatch = line.match(/^(\s*)([-++-\-\s]*)(.*)$/);
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

// -- OPENCODE SPRITE ICON SYSTEM ---------------------------------------------
// Uses OpenCode's file-icons/sprite.svg (1096 icons) via <use href="...#Name">
// sprite.svg is bundled at: src/ui/html/ai_chat/file-icons/sprite.svg

var SPRITE_URL = 'file-icons/sprite.svg';

// Map file extension ? OpenCode IconName
var EXT_TO_SPRITE = {
    // JS / TS
    'js': 'Javascript', 'mjs': 'Javascript', 'cjs': 'Javascript',
    'ts': 'Typescript', 'tsx': 'React_ts', 'jsx': 'React',
    'd.ts': 'TypescriptDef', 'js.map': 'JavascriptMap',
    // Web
    'html': 'Html', 'htm': 'Html',
    'css': 'Css', 'scss': 'Sass', 'sass': 'Sass', 'less': 'Less', 'styl': 'Stylus',
    // Languages
    'py': 'Python', 'pyx': 'Python', 'pyw': 'Python',
    'java': 'Java', 'kt': 'Kotlin', 'scala': 'Scala',
    'cs': 'Csharp', 'vb': 'Visualstudio',
    'cpp': 'Cpp', 'cc': 'Cpp', 'cxx': 'Cpp', 'c': 'C', 'h': 'H', 'hpp': 'Hpp',
    'rs': 'Rust', 'go': 'Go', 'rb': 'Ruby', 'php': 'Php',
    'swift': 'Swift', 'm': 'ObjectiveC', 'mm': 'ObjectiveCpp',
    'dart': 'Dart', 'lua': 'Lua', 'pl': 'Perl',
    'r': 'R', 'jl': 'Julia', 'hs': 'Haskell', 'elm': 'Elm',
    'ex': 'Elixir', 'exs': 'Elixir', 'erl': 'Erlang',
    'clj': 'Clojure', 'cljs': 'Clojure', 'ml': 'Ocaml', 'fs': 'Fsharp',
    'nim': 'Nim', 'zig': 'Zig', 'v': 'Vlang', 'odin': 'Odin',
    'gleam': 'Gleam', 'grain': 'Grain',
    // Shell
    'sh': 'Console', 'bash': 'Console', 'zsh': 'Console', 'fish': 'Console',
    'ps1': 'Powershell', 'bat': 'Console',
    // Data / config
    'json': 'Json', 'xml': 'Xml', 'yaml': 'Yaml', 'yml': 'Yaml',
    'toml': 'Toml', 'hjson': 'Hjson', 'env': 'Tune',
    'cfg': 'Settings', 'ini': 'Settings', 'conf': 'Settings',
    'properties': 'Settings',
    // Docs
    'md': 'Markdown', 'mdx': 'Mdx', 'tex': 'Tex',
    // DB / query
    'sql': 'Database', 'db': 'Database', 'sqlite': 'Database',
    'graphql': 'Graphql', 'gql': 'Graphql', 'proto': 'Proto',
    // Media
    'svg': 'Svg', 'png': 'Image', 'jpg': 'Image', 'jpeg': 'Image',
    'gif': 'Image', 'webp': 'Image', 'bmp': 'Image', 'ico': 'Favicon',
    'mp4': 'Video', 'mov': 'Video', 'avi': 'Video', 'webm': 'Video',
    'mp3': 'Audio', 'wav': 'Audio', 'flac': 'Audio',
    // Archives
    'zip': 'Zip', 'tar': 'Zip', 'gz': 'Zip', 'rar': 'Zip', '7z': 'Zip',
    // Docs
    'pdf': 'Pdf', 'doc': 'Word', 'docx': 'Word',
    'ppt': 'Powerpoint', 'pptx': 'Powerpoint',
    // Other
    'log': 'Log', 'lock': 'Lock', 'key': 'Key',
    'pem': 'Certificate', 'crt': 'Certificate',
    'wasm': 'Webassembly', 'dockerfile': 'Docker',
    // Test files
    'spec.ts': 'TestTs', 'test.ts': 'TestTs',
    'spec.js': 'TestJs', 'test.js': 'TestJs',
    'spec.tsx': 'TestJsx', 'test.tsx': 'TestJsx',
    'spec.jsx': 'TestJsx', 'test.jsx': 'TestJsx',
    // Vue / Svelte
    'vue': 'Vue', 'svelte': 'Svelte',
};

// Exact filename ? OpenCode IconName
var FILENAME_TO_SPRITE = {
    'package.json': 'Nodejs', 'package-lock.json': 'Nodejs',
    '.nvmrc': 'Nodejs', '.node-version': 'Nodejs',
    'yarn.lock': 'Yarn', 'pnpm-lock.yaml': 'Pnpm',
    'bun.lock': 'Bun', 'bun.lockb': 'Bun', 'bunfig.toml': 'Bun',
    'dockerfile': 'Docker', 'docker-compose.yml': 'Docker',
    'docker-compose.yaml': 'Docker', '.dockerignore': 'Docker',
    '.gitignore': 'Git', '.gitattributes': 'Git',
    'tsconfig.json': 'Tsconfig', 'jsconfig.json': 'Jsconfig',
    'vite.config.js': 'Vite', 'vite.config.ts': 'Vite',
    'tailwind.config.js': 'Tailwindcss', 'tailwind.config.ts': 'Tailwindcss',
    'jest.config.js': 'Jest', 'jest.config.ts': 'Jest',
    'vitest.config.js': 'Vitest', 'vitest.config.ts': 'Vitest',
    '.eslintrc': 'Eslint', '.eslintrc.js': 'Eslint', '.eslintrc.json': 'Eslint',
    '.prettierrc': 'Prettier', '.prettierrc.js': 'Prettier',
    'webpack.config.js': 'Webpack', 'rollup.config.js': 'Rollup',
    'next.config.js': 'Next', 'next.config.mjs': 'Next',
    'nuxt.config.js': 'Nuxt', 'nuxt.config.ts': 'Nuxt',
    'svelte.config.js': 'Svelte', 'astro.config.mjs': 'AstroConfig',
    'gatsby-config.js': 'Gatsby', 'remix.config.js': 'Remix',
    '.gitpod.yml': 'Gitpod', 'turbo.json': 'Turborepo',
    'cargo.toml': 'Rust', 'go.mod': 'GoMod', 'go.sum': 'GoMod',
    'requirements.txt': 'Python', 'pyproject.toml': 'Python',
    'pipfile': 'Python', 'poetry.lock': 'Poetry',
    'gemfile': 'Gemfile', 'rakefile': 'Ruby',
    'composer.json': 'Php', 'build.gradle': 'Gradle', 'pom.xml': 'Maven',
    'deno.json': 'Deno', 'deno.jsonc': 'Deno',
    'vercel.json': 'Vercel', 'netlify.toml': 'Netlify',
    '.env': 'Tune', '.env.local': 'Tune', '.env.example': 'Tune',
    '.editorconfig': 'Editorconfig', 'makefile': 'Makefile',
    'robots.txt': 'Robots', 'favicon.ico': 'Favicon',
    '.babelrc': 'Babel', 'babel.config.js': 'Babel',
    'firebase.json': 'Firebase', 'angular.json': 'Angular',
    'nx.json': 'Nx', 'lerna.json': 'Lerna',
    'cypress.config.js': 'Cypress', 'playwright.config.js': 'Playwright',
    'wrangler.toml': 'Wrangler', 'renovate.json': 'Renovate',
    'readme.md': 'Readme', 'changelog.md': 'Changelog',
    'license': 'Certificate',
};

// Folder name ? sprite icon name (collapsed / open)
var FOLDER_TO_SPRITE = {
    'src': 'FolderSrc', 'source': 'FolderSrc',
    'lib': 'FolderLib', 'libs': 'FolderLib',
    'test': 'FolderTest', 'tests': 'FolderTest', '__tests__': 'FolderTest',
    'spec': 'FolderTest', 'specs': 'FolderTest', 'e2e': 'FolderTest',
    'node_modules': 'FolderNode',
    'vendor': 'FolderPackages', 'packages': 'FolderPackages',
    'build': 'FolderBuildkite', 'dist': 'FolderDist',
    'out': 'FolderDist', 'output': 'FolderDist', 'target': 'FolderTarget',
    'config': 'FolderConfig', 'configs': 'FolderConfig',
    'env': 'FolderEnvironment', 'environments': 'FolderEnvironment',
    'docker': 'FolderDocker', 'containers': 'FolderDocker',
    'docs': 'FolderDocs', 'doc': 'FolderDocs', 'documentation': 'FolderDocs',
    'public': 'FolderPublic', 'static': 'FolderPublic',
    'assets': 'FolderImages', 'images': 'FolderImages',
    'img': 'FolderImages', 'icons': 'FolderImages', 'media': 'FolderImages',
    'fonts': 'FolderFont',
    'styles': 'FolderCss', 'stylesheets': 'FolderCss', 'css': 'FolderCss',
    'sass': 'FolderSass', 'scss': 'FolderSass',
    'scripts': 'FolderScripts', 'script': 'FolderScripts',
    'utils': 'FolderUtils', 'utilities': 'FolderUtils',
    'helpers': 'FolderHelper', 'tools': 'FolderTools',
    'components': 'FolderComponents', 'component': 'FolderComponents',
    'views': 'FolderViews', 'view': 'FolderViews',
    'layouts': 'FolderLayout', 'layout': 'FolderLayout',
    'templates': 'FolderTemplate', 'template': 'FolderTemplate',
    'hooks': 'FolderHook', 'hook': 'FolderHook',
    'store': 'FolderStore', 'stores': 'FolderStore',
    'reducers': 'FolderReduxReducer', 'reducer': 'FolderReduxReducer',
    'services': 'FolderApi', 'service': 'FolderApi',
    'api': 'FolderApi', 'apis': 'FolderApi',
    'routes': 'FolderRoutes', 'route': 'FolderRoutes',
    'middleware': 'FolderMiddleware', 'middlewares': 'FolderMiddleware',
    'controllers': 'FolderController', 'controller': 'FolderController',
    'models': 'FolderDatabase', 'model': 'FolderDatabase',
    'schemas': 'FolderDatabase', 'migrations': 'FolderDatabase',
    'types': 'FolderTypescript', 'typing': 'FolderTypescript',
    'typings': 'FolderTypescript', '@types': 'FolderTypescript',
    'interfaces': 'FolderInterface', 'interface': 'FolderInterface',
    'android': 'FolderAndroid', 'ios': 'FolderIos',
    'flutter': 'FolderFlutter', 'mobile': 'FolderMobile',
    'kubernetes': 'FolderKubernetes', 'k8s': 'FolderKubernetes',
    'terraform': 'FolderTerraform',
    'aws': 'FolderAws', 'firebase': 'FolderFirebase',
    '.github': 'FolderGithub', '.gitlab': 'FolderGitlab',
    '.circleci': 'FolderCircleci', '.git': 'FolderGit',
    'workflows': 'FolderGhWorkflows',
    '.vscode': 'FolderVscode', '.idea': 'FolderIntellij',
    '.cursor': 'FolderCursor', '.storybook': 'FolderStorybook',
    'i18n': 'FolderI18n', 'locales': 'FolderI18n', 'lang': 'FolderI18n',
    'temp': 'FolderTemp', 'tmp': 'FolderTemp',
    'logs': 'FolderLog', 'log': 'FolderLog',
    'mocks': 'FolderMock', 'mock': 'FolderMock',
    'data': 'FolderDatabase', 'database': 'FolderDatabase', 'db': 'FolderDatabase',
    'prisma': 'FolderPrisma', 'drizzle': 'FolderDrizzle',
    'functions': 'FolderFunctions', 'lambda': 'FolderFunctions',
    'security': 'FolderSecure', 'auth': 'FolderSecure',
    'keys': 'FolderKeys', 'certs': 'FolderKeys',
    'examples': 'FolderExamples', 'example': 'FolderExamples',
    'demo': 'FolderExamples', 'demos': 'FolderExamples',
    'content': 'FolderContent', 'posts': 'FolderContent',
    'jobs': 'FolderJob', 'tasks': 'FolderTasks',
    'desktop': 'FolderDesktop',
};

/**
 * Get sprite-based SVG icon for a file/folder.
 * Works in: tree view, diff cards, @mention pickers, file links.
 *
 * @param {string} nameOrExt  - filename "main.py", extension "py", or "" for folder
 * @param {boolean} isDir     - true for folders
 * @param {boolean} expanded  - if dir, use open variant
 * @param {number} size       - icon size in px (default 16)
 * @returns {string} HTML string with <svg><use> referencing sprite.svg
 */
function getFileIcon(nameOrExt, isDir, expanded, size) {
    size = size || 16;
    var iconName;

    if (isDir) {
        var folderKey = (nameOrExt || '').toLowerCase().replace(/^[._]+/, '').replace(/\/$/, '');
        // Check with leading dots too (e.g. ".github")
        var origLower = (nameOrExt || '').toLowerCase().replace(/\/$/, '');
        iconName = FOLDER_TO_SPRITE[origLower] || FOLDER_TO_SPRITE[folderKey] || 'Folder';
        if (expanded && !iconName.endsWith('Open')) iconName = iconName + 'Open';
    } else {
        var fn = (nameOrExt || '').toLowerCase();
        // 1. Exact filename match
        iconName = FILENAME_TO_SPRITE[fn];
        // 2. Compound extension (spec.ts, test.js etc)
        if (!iconName && fn.includes('.')) {
            var firstDot = fn.indexOf('.');
            var compoundExt = fn.slice(firstDot + 1);
            iconName = EXT_TO_SPRITE[compoundExt];
        }
        // 3. Last extension
        if (!iconName) {
            var lastDot = fn.lastIndexOf('.');
            if (lastDot !== -1) iconName = EXT_TO_SPRITE[fn.slice(lastDot + 1)];
        }
        // 4. Fallback
        if (!iconName) iconName = 'Document';
    }

    return '<svg class="file-type-icon" width="' + size + '" height="' + size + '" viewBox="0 0 32 32" aria-hidden="true">' +
           '<use href="' + SPRITE_URL + '#' + iconName + '"></use>' +
           '</svg>';
}

// -- Legacy alias used by tree renderer ---------------------------------------
function getFileIconForTree(ext, isDir) {
    if (isDir) {
        return getFileIcon('', true, false, 18);
    }
    return getFileIcon(ext, false, false, 18);
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
            window.bridge = channel.objects.bridge;
            if (!window.bridge) {
                console.error("Cortex: Bridge object 'bridge' not found on channel.");
                return;
            }

            window.bridgeReady = true;
            bridge = window.bridge;
            console.log('[CHAT] Bridge initialized successfully');
            
            // Re-fetch project info if it was set before bridge was ready
            if (currentProjectPath) {
                console.log('[CHAT] Bridge ready, reloading project chats for:', currentProjectPath);
                var savedChats = loadProjectChats();
                if (savedChats && savedChats.length > 0) {
                    chats = savedChats;
                    renderHistoryList();
                    loadChat(chats[0].id);
                }
            }

            bridge.clear_chat_requested.connect(clearMessages);
            
            // Terminal output with advanced throttling to prevent UI freezing
            var _terminalOutputBuffer = '';
            var _terminalOutputTimeout = null;
            var _terminalOutputFrameId = null;
            var _terminalLastWrite = 0;
            var _terminalMaxBufferSize = 8192; // Max buffer before forced flush
            var _terminalPendingData = []; // Queue for burst handling
            // Batching for AI chat terminal output (uses global vars above)
            
            function _flushTerminalOutput() {
                _terminalOutputFrameId = null;
                if (!term) {
                    _terminalOutputBuffer = '';
                    _terminalPendingData = [];
                    return;
                }
                
                // Process pending data queue first
                if (_terminalPendingData.length > 0) {
                    _terminalOutputBuffer += _terminalPendingData.join('');
                    _terminalPendingData = [];
                }
                
                if (_terminalOutputBuffer) {
                    // When terminal is hidden, accumulate in paused buffer instead
                    if (!_terminalVisible) {
                        _terminalPausedBuffer += _terminalOutputBuffer;
                        if (_terminalPausedBuffer.length > _terminalMaxPausedBuffer) {
                            _terminalPausedBuffer = _terminalPausedBuffer.slice(-_terminalMaxPausedBuffer);
                        }
                        _terminalOutputBuffer = '';
                        _terminalOutputTimeout = null;
                        return;
                    }
                    
                    // Limit buffer size to prevent memory issues
                    if (_terminalOutputBuffer.length > _terminalMaxBufferSize) {
                        _terminalOutputBuffer = _terminalOutputBuffer.slice(-_terminalMaxBufferSize);
                    }
                    term.write(_terminalOutputBuffer);
                    _terminalOutputBuffer = '';
                    _terminalLastWrite = Date.now();
                }
                _terminalOutputTimeout = null;
            }
            
            bridge.terminal_output.connect(function (data) {
                if (!term) return;
                
                // Add to pending queue for burst handling
                _terminalPendingData.push(data);
                
                // If terminal is not visible, process less frequently
                if (!_terminalVisible) {
                    if (_terminalPendingData.length > 50) { // Higher threshold when hidden
                        _flushTerminalOutput();
                    } else if (!_terminalOutputTimeout) {
                        _terminalOutputTimeout = setTimeout(_flushTerminalOutput, 100); // Slower update when hidden
                    }
                    return;
                }
                
                // If we have too many pending items, flush immediately
                if (_terminalPendingData.length > 10) {
                    if (_terminalOutputTimeout) {
                        clearTimeout(_terminalOutputTimeout);
                        _terminalOutputTimeout = null;
                    }
                    if (_terminalOutputFrameId) {
                        cancelAnimationFrame(_terminalOutputFrameId);
                        _terminalOutputFrameId = null;
                    }
                    _flushTerminalOutput();
                    return;
                }
                
                // Use requestAnimationFrame for smoother rendering when possible
                if (!_terminalOutputTimeout && !_terminalOutputFrameId) {
                    var now = Date.now();
                    var timeSinceLastWrite = now - _terminalLastWrite;
                    
                    // If last write was recent, use timeout; otherwise use rAF
                    if (timeSinceLastWrite < 32) {
                        _terminalOutputTimeout = setTimeout(function() {
                            _terminalOutputFrameId = requestAnimationFrame(_flushTerminalOutput);
                        }, 16);
                    } else {
                        _terminalOutputFrameId = requestAnimationFrame(_flushTerminalOutput);
                    }
                }
            });

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
    console.log('[INIT] DOMContentLoaded fired');
    
    try {
        console.log('[INIT] Starting initMarked()...');
        initMarked();
        
        console.log('[INIT] Starting initBridge()...');
        // Terminal is initialized lazily when first shown
        initBridge();
        
        console.log('[INIT] Starting initScrollTracking()...');
        initScrollTracking(); // Initialize scroll tracking
        
        console.log('[INIT] All initialization complete, marking ready');
    } catch (error) {
        console.error('[INIT] Error during initialization:', error);
        console.error('[INIT] Error stack:', error.stack);
    } finally {
        // Always mark as ready even if there were errors
        console.log('[INIT] Entering finally block, checking markReady...');
        if (window.markReady) {
            console.log('[INIT] Calling window.markReady()');
            window.markReady();
            console.log('[INIT] Page marked as ready - body classes:', document.body.className);
        } else {
            console.error('[INIT] ERROR: window.markReady is not defined!');
        }
    }

    // Image attachment handling
    var attachImageBtn = document.querySelector('[title="Attach Image"]');
    if (attachImageBtn) {
        attachImageBtn.onclick = function() {
            // Check if current model supports vision
            var selectedModel = document.getElementById('selected-model');
            var modelText = selectedModel ? selectedModel.textContent : '';
            
            // Vision-capable models (including SiliconFlow Qwen-VL models)
            var visionModels = [
                'Qwen', 'VL', 'Vision',  // Qwen-VL family (includes SiliconFlow)
                'GPT-4', 'Claude', 'gemini',
            ];
            
            // Models that explicitly do NOT support vision
            var nonVisionModels = ['deepseek-chat', 'DeepSeek-V3', 'deepseek-ai/DeepSeek', 'QwQ', 'Coder'];
            
            var supportsVision = false;
            var isNonVision = nonVisionModels.some(function(m) { 
                return modelText.toLowerCase().includes(m.toLowerCase()); 
            });
            
            if (!isNonVision) {
                supportsVision = visionModels.some(function(m) { 
                    return modelText.toLowerCase().includes(m.toLowerCase()); 
                });
            }
            
            if (!supportsVision) {
                alert('NOTE: Image attachment requires a vision-capable model.\n\n' +
                      'Current model: ' + modelText + '\n\n' +
                      'Please switch to a vision model like:\n' +
                      '- Qwen-VL (SiliconFlow)\n' +
                      '- GPT-4 Vision\n' +
                      '- Claude 3\n\n' +
                      'Click the model selector (top-right) to change models.');
                return;
            }
            
            // Create file input
            var input = document.createElement('input');
            input.type = 'file';
            input.accept = 'image/*';
            input.multiple = false;
            input.onchange = function(e) {
                var file = e.target.files[0];
                if (file) {
                    handleImageAttachment(file);
                }
            };
            input.click();
        };
    }

    // Event Listeners
    var toggle = document.getElementById('toggle-history-btn');
    if (toggle) toggle.onclick = toggleSidebar;

    var close = document.getElementById('close-sidebar-btn');
    if (close) close.onclick = toggleSidebar;

    var newChatBtn = document.getElementById('new-chat-btn');
    if (newChatBtn) newChatBtn.onclick = startNewChat;

    // AutoGen Multi-Agent Toggle (Compact Banner in Dropdown)
    var autogenBanner = document.getElementById('autogen-banner');
    var autogenToggleSwitch = document.getElementById('autogen-toggle-switch');
    var autogenBannerText = document.getElementById('autogen-banner-text');
    
    console.log('[AutoGen] Banner elements:', {
        banner: !!autogenBanner,
        switch: !!autogenToggleSwitch,
        text: !!autogenBannerText
    });
    
    if (autogenBanner && autogenToggleSwitch) {
        console.log('[AutoGen] Click handler attached');
        
        autogenToggleSwitch.onclick = function(e) {
            e.stopPropagation();
            e.preventDefault();
            
            console.log('[AutoGen] Toggle clicked! Bridge available:', !!bridge);
            console.log('[AutoGen] on_toggle_autogen method:', typeof (bridge && bridge.on_toggle_autogen));
            
            if (bridge && bridge.on_toggle_autogen) {
                console.log('[AutoGen] Calling bridge.on_toggle_autogen()...');
                // Toggle AutoGen using the correct method name
                bridge.on_toggle_autogen();
                
                // Update UI after small delay
                setTimeout(function() {
                    autogenBanner.classList.toggle('active');
                    var isActive = autogenBanner.classList.contains('active');
                    autogenBannerText.textContent = isActive ? 
                        'Multi-Agent: ON' : 'Multi-Agent: OFF';
                    
                    console.log('[AutoGen] UI updated, active:', isActive);
                    
                    // Show toast notification (inline to avoid hoisting issues)
                    try {
                        if (typeof showToast === 'function') {
                            showToast(
                                isActive ? '? Multi-Agent Mode ENABLED' : '? Multi-Agent Mode DISABLED',
                                isActive ? 'success' : 'info',
                                3000
                            );
                        } else {
                            console.log('[AutoGen] Mode toggled:', isActive ? 'ON' : 'OFF');
                        }
                    } catch (err) {
                        console.log('[AutoGen] Toast error:', err);
                    }
                }, 200);
            } else {
                console.error('[AutoGen] Bridge method not ready!', {
                    bridge: !!bridge,
                    on_toggle_autogen: typeof (bridge && bridge.on_toggle_autogen)
                });
            }
        };
        
        // Prevent dropdown from closing when clicking banner
        autogenBanner.onclick = function(e) {
            e.stopPropagation();
            e.preventDefault();
        };
    } else {
        console.error('[AutoGen] Banner or switch element not found!');
    }
    
    // Always Allow Toggle Handler
    var alwaysAllowBtn = document.getElementById('always-allow-toggle');
    if (alwaysAllowBtn) {
        // Check saved state
        var alwaysAllowEnabled = localStorage.getItem('cortex_always_allow') === 'true';
        if (alwaysAllowEnabled) {
            alwaysAllowBtn.classList.add('active');
        }
        
        alwaysAllowBtn.onclick = function() {
            var isActive = !alwaysAllowBtn.classList.contains('active');
            alwaysAllowBtn.classList.toggle('active');
            localStorage.setItem('cortex_always_allow', isActive);
            
            // Notify Python bridge
            if (bridge && bridge.on_always_allow_changed) {
                bridge.on_always_allow_changed(isActive);
            }
            
            // Show toast
            try {
                if (typeof showToast === 'function') {
                    showToast(
                        isActive ? '? Auto-approval ENABLED' : '? Auto-approval DISABLED',
                        isActive ? 'success' : 'info',
                        3000
                    );
                }
            } catch (err) {
                console.log('[AlwaysAllow] Toast error:', err);
            }
            
            console.log('[AlwaysAllow] Mode toggled:', isActive ? 'ON' : 'OFF');
        };
    }

    var send = document.getElementById('sendBtn');
    if (send) send.onclick = sendMessage;

    var stop = document.getElementById('stopBtn');
    if (stop) stop.onclick = stopGeneration;

    var genPlan = document.getElementById('generate-plan-btn');
    if (genPlan) genPlan.onclick = function() {
        if (bridge) bridge.on_generate_plan();
    };

    // Image paste support (Ctrl+V)
    document.addEventListener('paste', function(e) {
        // Check if chat input is focused or any input field
        var activeEl = document.activeElement;
        var isInputFocused = activeEl && (
            activeEl.id === 'chatInput' || 
            activeEl.tagName === 'TEXTAREA' ||
            activeEl.tagName === 'INPUT'
        );
        
        if (!isInputFocused) return;
        
        var items = e.clipboardData && e.clipboardData.items;
        if (!items) return;
        
        for (var i = 0; i < items.length; i++) {
            if (items[i].type && items[i].type.indexOf('image') !== -1) {
                e.preventDefault();
                
                // Check if model supports vision
                var selectedModel = document.getElementById('selected-model');
                var modelText = selectedModel ? selectedModel.textContent : '';
                var nonVisionModels = ['deepseek-chat', 'DeepSeek-V3', 'deepseek-ai/DeepSeek', 'QwQ', 'Coder'];
                var isNonVision = nonVisionModels.some(function(m) { 
                    return modelText.toLowerCase().includes(m.toLowerCase()); 
                });
                
                if (isNonVision) {
                    alert('NOTE: Image paste requires a vision-capable model.\n\n' +
                          'Current model: ' + modelText + '\n\n' +
                          'Please switch to a vision model like Qwen-VL.');
                    return;
                }
                
                var file = items[i].getAsFile();
                if (file) {
                    handleImageAttachment(file);
                    console.log('[Cortex] Image pasted via Ctrl+V');
                }
                break;
            }
        }
    });

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
            // Debounced resize via rAF to avoid forced reflow on each keystroke
            if (input._resizeRaf) cancelAnimationFrame(input._resizeRaf);
            input._resizeRaf = requestAnimationFrame(function() {
                input.style.height = 'auto';
                input.style.height = Math.min(input.scrollHeight, 280) + 'px';
            });
        };
        
        // Smart paste handler — fast path for normal text, async only for real code
        window._pendingSmartPasteText = null;
        window._smartPasteTimeout = null;
        
        input.onpaste = function(e) {
            e.preventDefault();
            var pastedText = (e.clipboardData || window.clipboardData).getData('text');
            if (!pastedText) return;

            // Trigger smart paste for any multi-line paste (3+ lines).
            // Python will verify against the editor selection — single-line or
            // unmatched text falls back to plain paste automatically.
            var isMultiLine = pastedText.split('\n').length >= 3;

            if (isMultiLine && bridge) {
                // Optimistic insert immediately so user sees the text right away,
                // then upgrade to a chip if Python confirms a match.
                insertTextAtCursor(input, pastedText);
                window._pendingSmartPasteText = pastedText;

                // Short timeout — Python has 400ms to respond
                window._smartPasteTimeout = setTimeout(function() {
                    window._pendingSmartPasteText = null;
                }, 400);

                bridge.on_check_smart_paste(pastedText);
            } else {
                // Normal text — paste instantly, no delay at all
                insertTextAtCursor(input, pastedText);
            }
        };
        
        // Handler called by Python with the result
        window.handleSmartPasteResult = function(result) {
            if (window._smartPasteTimeout) {
                clearTimeout(window._smartPasteTimeout);
                window._smartPasteTimeout = null;
            }
            var input = document.getElementById('chatInput');
            if (!input) return;

            if (result && result.isMatch && window._pendingSmartPasteText) {
                // Remove the optimistically-pasted raw code and replace with a chip
                var rawCode = window._pendingSmartPasteText;
                // Remove the raw code from the textarea value
                var val = input.value;
                var idx = val.lastIndexOf(rawCode);
                if (idx !== -1) {
                    input.value = val.slice(0, idx) + val.slice(idx + rawCode.length);
                    input.dispatchEvent(new Event('input'));
                }
                _insertFileChip(
                    result.fileName || result.filePath.split(/[\/]/).pop(),
                    result.lineRange || '',
                    result.code || rawCode,
                    result.language || ''
                );
            }
            // If no match: raw code is already visible in the textarea — nothing to do
            window._pendingSmartPasteText = null;
        };
        
        // ── File chip helpers ────────────────────────────────────────
        function _getFileIcon(language) {
            var icons = {
                'py':   '{\u00a0}',   // python
                'js':   'JS',
                'ts':   'TS',
                'html': '</>',
                'css':  '{}',
                'json': '{}',
                'md':   '#',
                'txt':  'TXT',
                'sh':   '$',
                'bat':  '$',
                'cpp':  'C+',
                'c':    'C',
                'java': 'Ja',
                'rs':   'Rs',
                'go':   'Go',
            };
            return icons[language] || '{}';
        }
        
        function _insertFileChip(fileName, lineRange, code, language) {
            // Get or create the chips container above the textarea
            var container = document.getElementById('input-container');
            var chipsArea = document.getElementById('file-chips-area');
            if (!chipsArea) {
                chipsArea = document.createElement('div');
                chipsArea.id = 'file-chips-area';
                container.insertBefore(chipsArea, container.firstChild);
            }
        
            var label = lineRange ? fileName + ' ' + lineRange : fileName;
            var icon = _getFileIcon(language);
        
            var chip = document.createElement('div');
            chip.className = 'file-chip';
            chip.dataset.code = code;
            chip.dataset.fileName = fileName;
            chip.dataset.lineRange = lineRange;
            chip.dataset.language = language;
            chip.innerHTML =
                '<span class="chip-icon">' + icon + '</span>' +
                '<span class="chip-label">' + label + '</span>' +
                '<button class="chip-remove" title="Remove">&times;</button>';
        
            chip.querySelector('.chip-remove').addEventListener('click', function(e) {
                e.stopPropagation();
                chip.remove();
                // Hide chips area if empty
                if (!chipsArea.children.length) chipsArea.style.display = 'none';
            });
        
            chipsArea.style.display = 'flex';
            chipsArea.appendChild(chip);
        }
        
        // Collect chip metadata (read-only, does NOT remove chips)
        window._collectChipMeta = function() {
            var chips = document.querySelectorAll('#file-chips-area .file-chip');
            if (!chips.length) return [];
            var meta = [];
            chips.forEach(function(chip) {
                meta.push({
                    fileName: chip.dataset.fileName || '',
                    lineRange: chip.dataset.lineRange || '',
                    language: chip.dataset.language || '',
                    code: chip.dataset.code || ''
                });
            });
            return meta;
        };

// Expose so sendMessage can collect chips
        window._collectChipCode = function() {
            var chips = document.querySelectorAll('#file-chips-area .file-chip');
            if (!chips.length) return '';
            var parts = [];
            chips.forEach(function(chip) {
                var label = chip.dataset.lineRange
                    ? chip.dataset.fileName + ' ' + chip.dataset.lineRange
                    : chip.dataset.fileName;
                var lang = chip.dataset.language || '';
                parts.push('`' + label + '`\n```' + lang + '\n' + chip.dataset.code + '\n```');
                chip.remove();
            });
            var area = document.getElementById('file-chips-area');
            if (area) area.style.display = 'none';
            return parts.join('\n\n') + '\n\n';
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
    
    // Save changed files and todos with current chat
    var currentChat = chats.find(function(c) { return c.id === currentChatId; });
    if (currentChat) {
        currentChat.changedFiles = _changedFiles;
        currentChat.todos = currentTodoList;
    }
    
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
        titleSpan.className = 'title-text'; // Add class for proper ellipsis
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
    
    chats = chats.filter(function(chat) { return chat.id != id; });
    
    // 2. Permanently delete from SQLite (if bridge available)
    if (bridge && typeof bridge.delete_chat_from_sqlite === 'function') {
        bridge.delete_chat_from_sqlite(id);
    }
    
    // 3. Clear localStorage cache for the current project to force a fresh sync
    var key = getStorageKey();
    localStorage.removeItem(key);
    
    saveChats();
    
    if (currentChatId == id) {
        if (chats.length > 0) {
            loadChat(chats[0].id);
        } else {
            startNewChat();
        }
    }
}

function startNewChat() {
    console.log('[DEBUG] === startNewChat() CALLED ===');
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
    // Clear TODOs and Changed Files for new chat
    clearTodosAndChangedFiles();
}

// Clear TODOs and Changed Files when switching projects or starting new chat
function clearTodosAndChangedFiles() {
    console.log('[DEBUG] === CLEARING TODOs and Changed Files ===');
    
    // Clear TODO section
    var todoSection = document.getElementById('todo-section');
    if (todoSection) {
        todoSection.style.display = 'none';
        console.log('[DEBUG] TODO section display set to none');
    }
    var todoBody = document.getElementById('todo-body');
    if (todoBody) {
        todoBody.style.display = 'none';
        todoBody.innerHTML = '';
    }
    var todoList = document.getElementById('todo-list');
    if (todoList) todoList.innerHTML = '';
    var todoPreview = document.getElementById('todo-preview-text');
    if (todoPreview) todoPreview.textContent = '';
    var todoCount = document.getElementById('todo-progress-count');
    if (todoCount) todoCount.textContent = '0/0';
    currentTodoList = [];
    
    // Clear Changed Files section
    var cfsSection = document.getElementById('changed-files-section');
    if (cfsSection) {
        cfsSection.style.display = 'none';
        console.log('[DEBUG] Changed Files section display set to none');
    }
    // Hide cfs-body but DO NOT wipe its innerHTML — that would destroy the static
    // #cfs-list element, causing renderChangedFileRow to fail (getElementById returns null)
    var cfsBody = document.getElementById('cfs-body');
    if (cfsBody) cfsBody.style.display = 'none';
    var cfsList = document.getElementById('cfs-list');
    if (cfsList) cfsList.innerHTML = '';  // only clear the row content, not the container
    var cfsCount = document.getElementById('cfs-count');
    if (cfsCount) cfsCount.textContent = '0';
    var cfsStatus = document.getElementById('cfs-status-text');
    if (cfsStatus) {
        cfsStatus.style.display = 'none';
        cfsStatus.textContent = '';
    }
    var cfsBulkBtns = document.getElementById('cfs-bulk-btns');
    if (cfsBulkBtns) cfsBulkBtns.style.display = 'none';
    _changedFiles = {};
    
    // Also collapse the sections
    window._todoSectionCollapsed = true;
    window._cfsCollapsed = true;
    
    console.log('[DEBUG] === CLEAR COMPLETE ===');
}
window.clearTodosAndChangedFiles = clearTodosAndChangedFiles;

function showLoadingIndicator() {
    var chatContent = document.getElementById('chat-content');
    if (!chatContent) return;
    
    // Check if indicator already exists
    if (document.getElementById('chat-lazy-loading')) return;
    
    var loader = document.createElement('div');
    loader.id = 'chat-lazy-loading';
    loader.style.cssText = 'position: absolute; top: 50%; left: 50%; transform: translate(-50%, -50%); padding: 20px; background: rgba(0,0,0,0.5); color: white; border-radius: 8px; z-index: 1000;';
    loader.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Loading chat...';
    chatContent.appendChild(loader);
}

function hideLoadingIndicator() {
    var loader = document.getElementById('chat-lazy-loading');
    if (loader && loader.parentNode) {
        loader.parentNode.removeChild(loader);
    }
}

function loadChat(id) {
    console.log('[CHAT] loadChat called with ID:', id);
    var chat = chats.find(function (c) { return c.id == id; });
    if (!chat) {
        console.error('[CHAT] Chat not found in list:', id);
        return;
    }
    console.log('[CHAT] Found chat:', chat.title, 'Messages:', chat.messages ? chat.messages.length : 0, 'Message count:', chat.message_count);
    currentChatId = id;
    
    // LAZY LOADING: If messages are not loaded yet, request them from the bridge
    var canLazyLoad = bridge && typeof bridge.load_full_chat === 'function';
    var msgCount = chat.messages ? chat.messages.length : 0;
    var needsLazyLoad = (chat.loaded === false || (msgCount === 0 && chat.message_count > 0));
    if (chat.truncated && canLazyLoad) {
        needsLazyLoad = true;
    }
    console.log('[CHAT] canLazyLoad:', canLazyLoad, 'needsLazyLoad:', needsLazyLoad, 'msgCount:', msgCount, 'message_count:', chat.message_count);
    if (needsLazyLoad && canLazyLoad) {
        console.log('[CHAT] Lazy loading messages for chat:', id);
        clearMessages();
        
        // Ensure empty state is removed or hidden during loading
        var emptyState = document.getElementById('empty-state');
        if (emptyState) emptyState.remove();
        
        showLoadingIndicator();
        console.log('[CHAT] Requesting lazy load from bridge for:', id);
        if (bridge && typeof bridge.load_full_chat === 'function') {
            bridge.load_full_chat(id);
            console.log('[CHAT] bridge.load_full_chat CALLED for ID:', id);
        } else {
            console.warn('[CHAT] Bridge not ready for lazy load. bridge exists:', !!bridge, 'type:', typeof (bridge && bridge.load_full_chat));
            hideLoadingIndicator();
        }
        return;
    }
    
    // ... rest of loadChat implementation
    
    clearMessages();
    
    // Clear changed files and TODOs before loading new chat
    clearTodosAndChangedFiles();

    normalizeMessageRoles(chat.messages);

    chat.messages.forEach(function (msg) {
        // Skip messages with undefined/empty text (handle both content and text property names)
        var msgText = msg.content || msg.text;
        var msgSender = msg.role || msg.sender;
        
        if (!msgText || msgText === 'undefined' || msgText.trim() === '') return;
        appendMessage(msgText, msgSender || 'user', false);
        // Restore tool activities (like directory listings) if present
        if (msg.toolActivities && msg.toolActivities.length > 0) {
            msg.toolActivities.forEach(function (activity) {
                if (activity.type === 'directory' && activity.contents) {
                    // Temporarily set currentAssistantMessage to last bubble for appending
                    var container = document.getElementById('chatMessages');
                    var bubbles = container.querySelectorAll('.message-bubble.assistant');
                    if (bubbles.length > 0) {
                        currentAssistantMessage = bubbles[bubbles.length - 1];
                        renderDirectoryContents(activity.path, activity.contents);
                    }
                }
            });
        }
    });
    
    // Restore changed files if present
    if (chat.changedFiles && Object.keys(chat.changedFiles).length > 0) {
        _changedFiles = chat.changedFiles;
        // Re-render changed files panel
        Object.keys(_changedFiles).forEach(function(filePath) {
            var file = _changedFiles[filePath];
            if (file.status !== 'rejected') {
                renderChangedFileRow(filePath, file.added, file.removed, file.editType, file.status);
            }
        });
        _refreshCfsHeader();
        _cfsShowAndExpand(); // ensure body is visible after restore
    }
    
    // Restore todos if present
    if (chat.todos && chat.todos.length > 0) {
        currentTodoList = chat.todos;
        updateTodos(currentTodoList, '');
    } else {
        currentTodoList = [];
        updateTodos([], '');
    }
    
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
    
    // Also clear TODOs and Changed Files when clearing messages
    clearTodosAndChangedFiles();

    var chat = chats.find(function (c) { return c.id == currentChatId; });
    
    // Only show "Start a new conversation" splash if:
    // 1. No chat selected OR
    // 2. Chat is fully loaded AND has 0 messages
    // 3. We are NOT currently showing a loading indicator
    var isLoading = document.getElementById('chat-lazy-loading') !== null;
    
    if (!isLoading && (!chat || (chat.loaded !== false && chat.messages.length === 0))) {
        var emptyState = document.createElement('div');
        emptyState.id = 'empty-state';
        emptyState.innerHTML = `<svg width="60" height="60" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1" stroke-linecap="round" stroke-linejoin="round" style="margin: 0 auto 20px auto; display: block; opacity: 0.6;"><path d="M9.5 2A2.5 2.5 0 0 1 12 4.5v15a2.5 2.5 0 0 1-4.96.44 2.5 2.5 0 0 1-2.96-3.08 3 3 0 0 1-.34-5.58 2.5 2.5 0 0 1 1.32-4.24 2.5 2.5 0 0 1 4.44-2.54Z"></path><path d="M14.5 2A2.5 2.5 0 0 0 12 4.5v15a2.5 2.5 0 0 0 4.96.44 2.5 2.5 0 0 0 2.96-3.08 3 3 0 0 0 .34-5.58 2.5 2.5 0 0 0-1.32-4.24 2.5 2.5 0 0 0-4.44-2.54Z"></path></svg><p>Start a new conversation with Cortex AI</p>`;
        container.appendChild(emptyState);
    }
}

function normalizeMessageRoles(messages) {
    if (!messages || messages.length === 0) return false;

    var hasAssistant = false;
    var hasRole = false;
    messages.forEach(function(msg) {
        var role = msg.role || msg.sender;
        if (role) {
            hasRole = true;
            if (role === 'assistant') hasAssistant = true;
        }
    });

    if (!hasAssistant && messages.length > 1) {
        messages.forEach(function(msg, idx) {
            var role = (idx % 2 === 0) ? 'user' : 'assistant';
            msg.role = role;
            msg.sender = role;
        });
        console.warn('[CHAT] No assistant roles found; applied alternating roles for display.');
        return true;
    }

    if (hasRole) {
        messages.forEach(function(msg) {
            var role = msg.role || msg.sender || 'user';
            msg.role = role;
            msg.sender = role;
        });
    }
    return false;
}

// Handle full chat load response from Python
window.handleFullChatLoad = function(conversationId, chatData) {
    console.log('[CHAT] handleFullChatLoad called for:', conversationId);
    console.log('[CHAT] Chat data received:', chatData ? 'YES' : 'NO', 'Type:', typeof chatData);
    if (chatData) {
        console.log('[CHAT] Chat data keys:', Object.keys(chatData));
        console.log('[CHAT] Messages count:', chatData.messages ? chatData.messages.length : 0);
    }
    hideLoadingIndicator();
    
    if (!chatData || !chatData.messages || chatData.messages.length === 0) {
        console.warn('[CHAT] No chat data received for:', conversationId);
        // Show empty state
        var container = document.getElementById('chatMessages');
        if (container && !document.getElementById('empty-state')) {
            var emptyState = document.createElement('div');
            emptyState.id = 'empty-state';
            emptyState.innerHTML = '<p>No chat history found</p>';
            container.appendChild(emptyState);
        }
        return;
    }
    
    console.log('[CHAT] Received', chatData.messages.length, 'messages');
    
    // Find the chat in our list
    var chat = chats.find(function(c) { return c.id == conversationId; });
    if (!chat) {
        console.error('[CHAT] Chat not found in list:', conversationId);
        return;
    }
    
    // Update chat with full data
    chat.messages = chatData.messages || [];
    chat.loaded = true;
    chat.truncated = false;
    
    // Clear and render messages
    clearMessages();
    normalizeMessageRoles(chat.messages);
    
    chat.messages.forEach(function(msg) {
        var msgText = msg.content || msg.text;
        var msgSender = msg.role || msg.sender;
        
        if (!msgText || msgText === 'undefined' || msgText.trim() === '') return;
        appendMessage(msgText, msgSender || 'user', false);
        
        // Restore tool activities
        if (msg.toolActivities && msg.toolActivities.length > 0) {
            msg.toolActivities.forEach(function(activity) {
                if (activity.type === 'directory' && activity.contents) {
                    var container = document.getElementById('chatMessages');
                    var bubbles = container.querySelectorAll('.message-bubble.assistant');
                    if (bubbles.length > 0) {
                        currentAssistantMessage = bubbles[bubbles.length - 1];
                        renderDirectoryContents(activity.path, activity.contents);
                    }
                }
            });
        }
    });
    
    // Restore changed files if present
    if (chatData.changedFiles && Object.keys(chatData.changedFiles).length > 0) {
        _changedFiles = chatData.changedFiles;
        Object.keys(_changedFiles).forEach(function(filePath) {
            var file = _changedFiles[filePath];
            if (file.status !== 'rejected') {
                renderChangedFileRow(filePath, file.added, file.removed, file.editType, file.status);
            }
        });
        _refreshCfsHeader();
    }
    
    // Restore todos if present
    if (chatData.todos && chatData.todos.length > 0) {
        currentTodoList = chatData.todos;
        updateTodos(currentTodoList, '');
    } else {
        currentTodoList = [];
        updateTodos([], '');
    }
    
    console.log('[CHAT] Chat loaded successfully:', conversationId);
};

function appendMessage(text, sender, shouldSave) {
    console.log('[CHAT] appendMessage called:', sender, 'length:', text ? text.length : 0);
    var container = document.getElementById('chatMessages');
    if (!container) return null;

    // Guard: skip undefined, null, or literal 'undefined' string
    if (text === undefined || text === null || text === 'undefined' || String(text).trim() === '') {
        console.warn('[CHAT] appendMessage: skipping undefined/empty message');
        return null;
    }
    text = String(text); // Ensure text is always a string

    var emptyState = document.getElementById('empty-state');
    if (emptyState) emptyState.remove();

    var bubble = document.createElement('div');
    bubble.className = 'message-bubble ' + sender;
    var content = document.createElement('div');
    content.className = 'message-content';

    if (sender === 'user') {
        // Check if there are chip metadata to render as visual chips
        var chipMeta = window._pendingChipMeta || [];
        window._pendingChipMeta = null;

        if (chipMeta.length > 0) {
            // Build the display text: strip out the code block context from text
            var displayText = text;
            // Remove the chip code blocks from display (they look like: `file.py 1-5`\n```lang\n...\n```)
            chipMeta.forEach(function(cm) {
                var label = cm.lineRange ? cm.fileName + ' ' + cm.lineRange : cm.fileName;
                // Build regex to strip the chip context block from display text
                var escapedLabel = label.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
                var pattern = new RegExp('`' + escapedLabel + '`\\s*```[\\s\\S]*?```\\s*', 'g');
                displayText = displayText.replace(pattern, '');
            });
            displayText = displayText.trim();

            // Render chip elements
            var chipsContainer = document.createElement('div');
            chipsContainer.className = 'message-chips-area';
            chipMeta.forEach(function(cm) {
                var chipEl = document.createElement('div');
                chipEl.className = 'message-file-chip';
                var ext = cm.language || cm.fileName.split('.').pop() || '';
                var icon = (typeof _getFileIcon === 'function') ? _getFileIcon(ext) : '{ }';
                var label = cm.lineRange ? cm.fileName + ' ' + cm.lineRange : cm.fileName;
                chipEl.innerHTML = '<span class="chip-icon">' + icon + '</span>' +
                    '<span class="chip-label">' + label + '</span>';
                chipEl.title = cm.code ? cm.code.substring(0, 200) : label;
                chipsContainer.appendChild(chipEl);
            });
            bubble.appendChild(chipsContainer);

            // Add remaining text if any
            if (displayText) {
                content.textContent = displayText;
                bubble.appendChild(content);
            }
        } else {
            content.textContent = text;
            bubble.appendChild(content);
        }
    } else {
        var parsedHtml = '';
        try {
            if (typeof marked !== 'undefined' && marked.parse) {
                parsedHtml = marked.parse(text) || '';
            } else {
                parsedHtml = formatMarkdownFallback(text);
            }
        } catch (e) {
            console.warn('[MARKDOWN] Parse error in appendMessage (using fallback):', e.message);
            parsedHtml = formatMarkdownFallback(text);
        }
        // Ensure we never set undefined
        content.innerHTML = parsedHtml || text || '';
        
        // Style ⊙Thought · Xs patterns from DeepSeek reasoning output
        content.innerHTML = content.innerHTML.replace(
            /([\u2299⊙]Thought\s*[·\xB7]\s*\d+s)/g,
            '<span class="thought-timer">$1</span>'
        );

        bubble.appendChild(content);
        
        // Apply syntax highlighting to code blocks in assistant messages
        if (sender === 'assistant' && window.hljs) {
            content.querySelectorAll('pre code').forEach(function(block) {
                if (!block.dataset.highlighted) {
                    var pre = block.parentElement;
                    var dataLang = pre ? pre.getAttribute('data-lang') : '';
                    var classMatch = block.className.match(/language-(\w+)/);
                    var classLang = classMatch ? classMatch[1] : '';
                    var lang = dataLang || classLang || 'plaintext';
                    
                    var normalizedLang = window.getNormalizedLanguage ? window.getNormalizedLanguage(lang) : lang;
                    var code = block.textContent || block.innerText || '';
                    
                    try {
                        var highlighted;
                        if (window.highlightCodeWithEmbedded) {
                            highlighted = window.highlightCodeWithEmbedded(code, lang);
                        } else if (hljs.getLanguage(normalizedLang)) {
                            highlighted = hljs.highlight(code, { language: normalizedLang }).value;
                        } else {
                            highlighted = hljs.highlightAuto(code).value;
                        }
                        if (highlighted && highlighted !== code) {
                            block.innerHTML = highlighted;
                        }
                    } catch (e) {
                        console.warn('[SYNTAX] Highlight error:', e.message);
                    }
                    block.dataset.highlighted = '1';
                }
            });
        }
    }

    container.appendChild(bubble);
    smartScroll(container);
    
    if (sender === 'assistant' && window.MathJax && window.MathJax.typeset) {
        window.MathJax.typeset([bubble]);
    }

    if (shouldSave) {
        var chat = chats.find(function (c) { return c.id == currentChatId; });
        if (chat) {
            // Skip saving "Thinking..." and other temporary indicator messages
            var isThinkingMessage = text && (
                text.includes('Thinking') || 
                text.includes('Analyzing your request') ||
                text.includes('Cortex is working')
            );
            if (isThinkingMessage) {
                console.log('[CHAT] Skipping persistence of temporary thinking indicator');
                return bubble;
            }
            
            // Include any pending tool activities with the message
            var messageData = { text: text, sender: sender, role: sender };
            if (window._pendingToolActivities && window._pendingToolActivities.length > 0) {
                messageData.toolActivities = window._pendingToolActivities;
                window._pendingToolActivities = []; // Clear after saving
            }
            chat.messages.push(messageData);
            if (chat.messages.length === 1 && sender === 'user') {
                chat.title = text.substring(0, 30) + (text.length > 30 ? '...' : '');
            }
            saveChats();
        }
    }
    
    // Re-verify title for first message if needed
    if (sender === 'user' && shouldSave) {
        var chat = chats.find(function(c) { return c.id == currentChatId; });
        if (chat && (chat.messages.length === 1 || !chat.title || chat.title === 'New Chat')) {
             chat.title = text.substring(0, 40) + (text.length > 40 ? '...' : '');
             renderHistoryList();
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

    // Collect chip metadata for display in user message bubble
    var chipMeta = (typeof window._collectChipMeta === 'function') ? window._collectChipMeta() : [];
    // Prepend any attached file chips as code context (full code for AI)
    var chipContext = (typeof window._collectChipCode === 'function') ? window._collectChipCode() : '';
    var fullText = chipContext + text;

    if (!fullText) return;

    input.value = '';
    input.style.height = 'auto';

    if (!bridge) {
        console.warn("Cortex: Bridge connection not ready.");
        return;
    }

    // Store chip metadata for display in the user bubble
    window._pendingChipMeta = chipMeta;
    if (_isGenerating) {
        _enqueueMessage(fullText);
    } else {
        _sendNow(fullText);
    }
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
            <span class="thinking-title">Working</span>
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
        var isError = icon === '?';
        var iconClass = isError ? 'error-icon' : 'success-icon';
        
        item.innerHTML = `<span class="exploration-icon ${iconClass}">${icon}</span><span class="${isError ? 'error-text' : ''}">${escapeHtml(text)}</span>`;
        list.appendChild(item);
        smartScroll(container);
    }
}

function _updateCurrentTerminalCard(line) {
    /**
     * Update the most recent running terminal card with streaming output.
     * This allows terminal cards to show live output instead of 'running...' forever.
     */
    // Find the most recent running terminal card (supports both old and new class names)
    var cards = document.querySelectorAll('.term-card.term-running, .tc.tc-running');
    if (cards.length === 0) return;

    var card = cards[cards.length - 1];
    var cardId = card.id;
    var outputId = cardId + '-output';  // buildTerminalCard uses '-output' suffix
    
    var outputEl = document.getElementById(outputId);
    if (!outputEl) {
        // Create output section if it doesn't exist yet (legacy fallback)
        outputEl = document.createElement('div');
        outputEl.className = 'term-output-body';
        outputEl.id = outputId;
        outputEl.style.display = 'block';
        outputEl.style.maxHeight = '200px';
        outputEl.style.overflowY = 'auto';
        var pre = document.createElement('pre');
        pre.className = 'term-output-text';
        outputEl.appendChild(pre);
        // Insert before footer
        var footer = card.querySelector('.term-footer');
        if (footer) {
            card.insertBefore(outputEl, footer);
        } else {
            card.appendChild(outputEl);
        }
    }

    // Append line to output (limit to last 200 lines to avoid memory bloat)
    var pre = outputEl.querySelector('pre');
    if (pre) {
        pre.textContent += line + '\n';

        // Trim if too long
        var lines = pre.textContent.split('\n');
        if (lines.length > 200) {
            pre.textContent = lines.slice(-200).join('\n');
        }

        // Auto-scroll output area
        outputEl.scrollTop = outputEl.scrollHeight;
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
        <div class="permission-header" style="display:flex;align-items:center;gap:10px;margin-bottom:10px;">
            <span style="display:inline-flex;align-items:center;padding:3px 8px;border-radius:4px;font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:0.5px;background:rgba(139,92,246,0.12);color:#a78bfa;border:1px solid rgba(139,92,246,0.2);">${getToolIcon(toolName)}</span>
            <span style="font-weight:500;font-size:13px;color:var(--text-main);">${escapeHtml(toolName)}</span>
        </div>
        <div class="permission-tool" style="font-family:'Geist Mono','JetBrains Mono',monospace;font-size:11.5px;color:var(--text-secondary);background:#111113;padding:8px 12px;border-radius:6px;border:1px solid rgba(255,255,255,0.05);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">
            ${escapeHtml(toolInfo)}
        </div>
        <div class="permission-actions" style="display:flex;gap:8px;margin-top:10px;">
            <button class="permission-allow" onclick="handlePermissionAllow()" style="background:var(--green);color:#fff;padding:5px 14px;border-radius:6px;font-size:11px;font-weight:600;border:none;cursor:pointer;transition:all 0.15s;">Allow</button>
            <button class="permission-deny" onclick="handlePermissionDeny()" style="background:rgba(255,255,255,0.06);color:var(--text-secondary);padding:5px 14px;border-radius:6px;font-size:11px;font-weight:500;border:1px solid rgba(255,255,255,0.08);cursor:pointer;transition:all 0.15s;">Deny</button>
        </div>
    `;
    
    container.appendChild(card);
    smartScroll(container);
}

function getToolIcon(toolName) {
    var name = (toolName || '').toLowerCase();
    if (name.includes('read') || name.includes('file')) return 'READ';
    if (name.includes('write') || name.includes('edit')) return 'EDIT';
    if (name.includes('run') || name.includes('command') || name.includes('terminal')) return 'RUN';
    if (name.includes('search') || name.includes('find')) return 'FIND';
    if (name.includes('list') || name.includes('dir')) return 'LIST';
    if (name.includes('git')) return 'GIT';
    return 'TOOL';
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

function hideThinkingIndicator() {
    // Alias for removeThinkingIndicator
    removeThinkingIndicator();
}

function removeThinkingIndicator() {
    // Hide the new grid animation
    hideThinkingAnimation();
}

function stopGeneration() {
    console.log('[STOP] Stopping generation...');
    if (window.bridge && window.bridge.on_stop) {
        window.bridge.on_stop();
    } else if (bridge && bridge.on_stop) {
        bridge.on_stop();
    } else {
        console.error('[STOP] Bridge or on_stop not available');
    }

    // Hide the stop button and update terminal status
    var terminalOutput = document.getElementById('inline-terminal-output');
    if (terminalOutput) {
        terminalOutput.classList.remove('running');
        var cancelBtn = terminalOutput.querySelector('.terminal-action-btn.cancel');
        if (cancelBtn) {
            cancelBtn.style.display = 'none';
        }
    }

    // ── Stop all running terminal cards (clear spinner) ──────────────
    document.querySelectorAll('.term-card.term-running').forEach(function(card) {
        // Switch card class to stopped (reuse error styling without red tint)
        card.classList.remove('term-running');
        card.classList.add('term-stopped');
        card.dataset.status = 'stopped';

        // Replace spinner with a grey stopped icon
        var iconEl = card.querySelector('.term-status-icon');
        if (iconEl) {
            iconEl.innerHTML = '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="rgba(148,163,184,0.7)" stroke-width="2.5"><rect x="3" y="3" width="18" height="18" rx="2"/></svg>';
        }

        // Update title
        var titleEl = card.querySelector('.term-title-text');
        if (titleEl) titleEl.textContent = 'Stopped';

        // Update badge
        var badgeEl = card.querySelector('.term-badge');
        if (badgeEl) {
            badgeEl.className = 'term-badge term-badge-stopped';
            badgeEl.textContent = 'Stopped';
        }
    });

    // Mark stop so the Python-fired onComplete is ignored
    _stopRequested = true;

    // Immediate UI cleanup (don't call onComplete - Python will fire it later)
    removeThinkingIndicator();
    hideThinking();
    collapseActivitySection();
    collapseFecContainer();
    currentAssistantMessage = null;
    currentContent          = '';
    _taskSummaryBuffer      = '';
    _inTaskSummary          = false;
    _isGenerating           = false;
    var sendBtn = document.getElementById('sendBtn');
    var stopBtn = document.getElementById('stopBtn');
    if (sendBtn) sendBtn.style.display = 'flex';
    if (stopBtn) stopBtn.style.display  = 'none';
    _onGenerationComplete();
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
    // Handle both calling conventions:
    // 1. showToolActivity(type, info, status) - legacy
    // 2. showToolActivity({tool_type, info, status}) - new object format from Python
    if (typeof type === 'object' && type !== null) {
        var obj = type;
        type = obj.tool_type;
        info = obj.info;
        status = obj.status;
    }
    
    var container = document.getElementById('chatMessages');
    if (!container) return;

    // When any real tool action starts, freeze/stop the Think indicator
    // so Think and tool actions never show as simultaneously active
    if (status === 'running') {
        hideThinking();
    }

    // Update thinking indicator with current activity
    var statusEl = document.getElementById('thinking-status');
    if (statusEl) {
        var activityText = '';
        // Helper: extract readable label from JSON info string
        var _parseInfoLabel = function(raw) {
            if (!raw) return '';
            if (raw.trim().startsWith('{')) {
                try {
                    var p = JSON.parse(raw);
                    return p.command || p.file_path || p.path || raw;
                } catch(e) {}
            }
            return raw;
        };
        if (type === 'read_file')      activityText = 'Reading: '   + _parseInfoLabel(info);
        else if (type === 'list_directory') activityText = 'Exploring: ' + _parseInfoLabel(info);
        else if (type === 'run_command')    activityText = 'Running: '   + _parseInfoLabel(info);
        else if (type === 'git_status')     activityText = 'Checking git status...';
        else activityText = type + '...';
        statusEl.textContent = activityText;
    }

    // -- File read/edit cards (IMMEDIATE VISIBLE CARDS) --------------
    if (type === 'read_file' || type === 'edit_file' || type === 'write_file') {
        if (!currentAssistantMessage) {
            currentAssistantMessage = document.createElement('div');
            currentAssistantMessage.className = 'message-bubble assistant';
            var ce = document.createElement('div');
            ce.className = 'message-content';
            currentAssistantMessage.appendChild(ce);
            currentContent = "";
            container.appendChild(currentAssistantMessage);
            var es = document.getElementById('empty-state');
            if (es) es.remove();
        }

        var cardsEl = currentAssistantMessage.querySelector('.fec-cards-container');
        if (!cardsEl) {
            cardsEl = document.createElement('div');
            cardsEl.className = 'fec-cards-container';
            currentAssistantMessage.appendChild(cardsEl);
        }

        // Parse file path from info - robust extraction for Python dict / JSON / plain string
        var filePath = '';
        var rawInfo = info || '';
        // 1) Regex-first: match 'path': '...' or "path": "..." (handles all Python dict formats)
        var reMatch = rawInfo.match(/['"](?:path|PATH|file|FILE)['"]\s*:\s*['"]([^'"]+)['"]/i);
        if (reMatch) {
            filePath = reMatch[1];
        } else {
            // 2) JSON / Python dict parse
            var parsedFec = null;
            try { parsedFec = JSON.parse(rawInfo); } catch(e) {
                try {
                    parsedFec = JSON.parse(rawInfo.replace(/'/g,'"').replace(/True/g,'true').replace(/False/g,'false').replace(/None/g,'null'));
                } catch(e2) {}
            }
            if (parsedFec) {
                var pv = parsedFec.path || (parsedFec.PATH && (parsedFec.PATH.path || parsedFec.PATH)) || parsedFec.file || null;
                if (pv && typeof pv === 'string') filePath = pv;
            }
        }
        if (!filePath) filePath = rawInfo.split(' ')[0]; // last fallback: first word
        
        // Check if card already exists - match by data-path containing the resolved filename
        var existingCard = null;
        var allCards = cardsEl.querySelectorAll('.fec[data-path]');
        var fileNameResolved = filePath ? filePath.split('/').pop().split('\\').pop() : '';
        for (var ci = 0; ci < allCards.length; ci++) {
            var cp = allCards[ci].dataset.path || '';
            var cpName = cp.split('/').pop().split('\\').pop();
            if (cpName && fileNameResolved && cpName === fileNameResolved && allCards[ci].dataset.status !== 'applied') {
                existingCard = allCards[ci];
                break;
            }
        }
        if (existingCard) {
            // Update existing pending card → show OK
            if (status === 'complete') {
                existingCard.classList.remove('fec-pending');
                existingCard.classList.add('fec-applied');
                existingCard.dataset.status = 'applied';
                var rightEl = existingCard.querySelector('.fec-right');
                if (rightEl) rightEl.innerHTML = '<span class="fec-status-text fec-status-applied">OK</span>';
                // Also freeze the action label text (stop implying ongoing)
                var labelEl = existingCard.querySelector('.fec-action-label');
                if (labelEl) labelEl.style.opacity = '0.4';
            }
        } else {
            // Create new file activity card
            var card = document.createElement('div');
            card.className = 'fec fec-' + (status === 'running' ? 'pending' : 'applied');
            card.dataset.path = filePath;
            card.dataset.status = status === 'running' ? 'pending' : 'applied';
            
            var fileName = filePath ? filePath.split('/').pop().split('\\').pop() : 'unknown';
            var ext = (fileName && fileName.includes('.')) ? fileName.split('.').pop().toLowerCase() : '';
            var extClass = 'fec-ext-' + (ext || 'default');

            // Action label + icon per type
            var actionLabel = type === 'read_file' ? 'Reading'
                           : type === 'edit_file'  ? 'Editing'
                           : type === 'create_file' ? 'Creating'
                           : 'Writing';
            var actionColor = type === 'read_file'  ? '#60a5fa'
                           : type === 'edit_file'   ? '#fbbf24'
                           : type === 'create_file' ? '#a78bfa'
                           : '#4ade80';

            var escapedPath = filePath.replace(/\\/g, '\\\\').replace(/'/g, "\\'");
            card.innerHTML =
                '<div class="fec-left">' +
                    '<span class="fec-ext-badge ' + extClass + '">' + (ext ? ext.toUpperCase() : 'FILE') + '</span>' +
                    '<button class="fec-name" onclick="openFileInEditor(\'' + escapedPath + '\')">'+
                        escapeHtml(fileName) +
                    '</button>' +
                    '<span class="fec-action-label" style="font-size:11px;color:' + actionColor + ';margin-left:8px;opacity:0.7;">' + actionLabel + '</span>' +
                '</div>' +
                '<div class="fec-right">' +
                    (status === 'running' ?
                        '<span style="width:10px;height:10px;border:1.5px solid transparent;border-top-color:' + actionColor + ';border-radius:50%;display:inline-block;animation:spin 0.8s linear infinite;"></span>' :
                        '<span class="fec-status-text fec-status-applied">OK</span>'
                    ) +
                '</div>';
            
            cardsEl.appendChild(card);
        }

        smartScroll(container);
        return;
    }

    // -- Terminal command card handling ------------------------------
    if (type === 'run_command') {
        if (!currentAssistantMessage) {
            currentAssistantMessage = document.createElement('div');
            currentAssistantMessage.className = 'message-bubble assistant';
            var ce = document.createElement('div');
            ce.className = 'message-content';
            currentAssistantMessage.appendChild(ce);
            currentContent = "";
            container.appendChild(currentAssistantMessage);
            var es = document.getElementById('empty-state');
            if (es) es.remove();
        }

        var cardsEl = currentAssistantMessage.querySelector('.fec-cards-container');
        if (!cardsEl) {
            cardsEl = document.createElement('div');
            cardsEl.className = 'fec-cards-container';
            currentAssistantMessage.appendChild(cardsEl);
        }

        if (status === 'running') {
            var cardId = 'term-cmd-' + Date.now();
            currentAssistantMessage.dataset.lastTermCardId = cardId;
            // Parse actual command from info JSON: {"command": "...", "timeout": N}
            var cmdStr = info;
            try {
                var infoObj = JSON.parse(info);
                if (infoObj.command) cmdStr = infoObj.command;
            } catch(e) {}
            var card = buildTerminalCard(cmdStr, '', 'running', null, cardId);
            cardsEl.appendChild(card);
        } else {
            var lastId = currentAssistantMessage.dataset.lastTermCardId;
            if (lastId) {
                var termSt   = status === 'error' ? 'error' : 'success';
                var termExit = 0;
                var termOut  = '';
                // Parse output from result JSON: {"command":..., "stdout":..., "returncode":..., "output":...}
                try {
                    var resObj = JSON.parse(info);
                    if (resObj.output)         termOut  = resObj.output;
                    else if (resObj.stdout)    termOut  = resObj.stdout + (resObj.stderr ? '\n[stderr]\n' + resObj.stderr : '');
                    if (resObj.returncode !== undefined && resObj.returncode !== 0) {
                        termExit = resObj.returncode;
                        termSt   = 'error';
                    }
                } catch(e) {
                    termOut = info || '';
                }
                updateTerminalCard(lastId, termSt, termExit, termOut);
            }
        }

        smartScroll(container);
        return;
    }

    // -- list_directory tree card ------------------------------------
    if (type === 'list_directory' && status === 'complete') {
        // Tree card is rendered via showDirectoryTree from Python
        smartScroll(container);
    }

    // Always create a fresh activity section or use the current one
    if (!currentActivitySection || !document.body.contains(currentActivitySection)) {
        currentActivitySection = document.createElement('div');
        currentActivitySection.className = 'activity-section';
        fileCount = 0;
        
        // Create collapsible header
        var header = document.createElement('div');
        header.className = 'activity-header';
        header.innerHTML = '<span class="activity-icon running"><span class="todo-spinner" style="width:10px;height:10px;"></span></span> <span class="activity-title">Exploring</span> <svg class="activity-toggle" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="6 9 12 15 18 9"></polyline></svg>';
        header.style.cursor = 'pointer';
        
        // Click handler for toggle
        header.onclick = function(e) {
            e.stopPropagation();
            var section = this.parentElement;
            var isCollapsed = section.classList.toggle('collapsed');
            var toggle = this.querySelector('.activity-toggle');
            if (toggle) {
                toggle.style.transform = isCollapsed ? 'rotate(-90deg)' : 'rotate(0deg)';
                toggle.style.transition = 'transform 0.2s ease';
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
    
    // Check if this item already exists (match by type and resolved path)
    var existingItem = null;
    var items = list.querySelectorAll('.activity-item');
    // Extract base path from info using same regex used in fec card
    var reMatchAct = info ? info.match(/['"]((?:path|PATH|file|FILE))['"]\s*:\s*['"]([^'"]+)['"]/i) : null;
    var baseInfo = reMatchAct ? reMatchAct[2].split(/[\\/]/).pop() : (info || '').split(' ')[0].split('(')[0];
    
    for (var i = 0; i < items.length; i++) {
        var itemType = items[i].getAttribute('data-type');
        var itemInfo = items[i].getAttribute('data-info');
        var reMatchItem = itemInfo ? itemInfo.match(/['"]((?:path|PATH|file|FILE))['"]\s*:\s*['"]([^'"]+)['"]/i) : null;
        var itemBaseInfo = reMatchItem ? reMatchItem[2].split(/[\\/]/).pop() : (itemInfo || '').split(' ')[0].split('(')[0];
        
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
        } else if (type === 'create_file' || type === 'create_directory' || type === 'delete_file' || type === 'delete_directory') {
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
        var opBadge = getActivityOpBadge(type);
        
        item.innerHTML = opBadge + icon + '<span class="activity-text">' + label + '</span>';
        
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
            iconEl.innerHTML = '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" style="color:#4ade80;"><polyline points="20 6 9 17 4 12"></polyline></svg>';
            iconEl.className = 'activity-icon complete';
        }
    }
    
    smartScroll(container);
}

// Professional Tool Execution Summary Display
function showToolSummary(summaryData) {
    console.log('[JS] showToolSummary called:', summaryData);
    var container = document.getElementById('chatMessages');
    if (!container || !summaryData) return;
    
    // Create or get the current assistant message
    if (!currentAssistantMessage) {
        currentAssistantMessage = document.createElement('div');
        currentAssistantMessage.className = 'message-bubble assistant';
        var ce = document.createElement('div');
        ce.className = 'message-content';
        currentAssistantMessage.appendChild(ce);
        currentContent = "";
        container.appendChild(currentAssistantMessage);
        var es = document.getElementById('empty-state');
        if (es) es.remove();
    }
    
    // Create summary card container
    var summaryCard = document.createElement('div');
    summaryCard.className = 'tool-summary-card';
    
    // Calculate totals
    var totalWrites = summaryData.file_writes ? summaryData.file_writes.length : 0;
    var totalReads = summaryData.file_reads ? summaryData.file_reads.length : 0;
    var totalCommands = summaryData.commands ? summaryData.commands.length : 0;
    var totalErrors = summaryData.errors ? summaryData.errors.length : 0;
    var totalOther = summaryData.other ? summaryData.other.length : 0;
    var grandTotal = totalWrites + totalReads + totalCommands + totalErrors + totalOther;
    
    if (grandTotal === 0) return;
    
    // Build header
    var headerHtml = '<div class="summary-header" onclick="this.parentElement.classList.toggle(\'collapsed\')">';
    headerHtml += '<span class="summary-icon">TOOLS</span>';
    headerHtml += '<span class="summary-title">Tool Execution Summary</span>';
    headerHtml += '<span class="summary-count">' + grandTotal + ' action' + (grandTotal > 1 ? 's' : '') + '</span>';
    headerHtml += '<span class="summary-toggle">Details</span>';
    headerHtml += '</div>';
    
    // Build content
    var contentHtml = '<div class="summary-content">';
    
    // File writes section
    if (totalWrites > 0) {
        contentHtml += '<div class="summary-section">';
        contentHtml += '<div class="section-header"><span class="section-icon">EDIT</span>Files Modified (' + totalWrites + ')</div>';
        contentHtml += '<div class="section-items">';
        summaryData.file_writes.forEach(function(item, index) {
            // Icon based on operation type
            var iconMap = {
                'edit': 'EDIT',
                'create': 'NEW',
                'delete': 'DEL',
                'directory': 'DIR'
            };
            var icon = iconMap[item.type] || 'FILE';
            var fileName = item.path ? item.path.split('/').pop().split('\\').pop() : 'unknown';
            contentHtml += '<div class="summary-item">';
            contentHtml += '<span class="item-icon">' + icon + '</span>';
            contentHtml += '<span class="item-name" title="' + escapeHtml(item.path) + '">' + escapeHtml(fileName) + '</span>';
            // Show diff stats if available (+X -Y)
            if (item.lines_added > 0 || item.lines_removed > 0) {
                var diffHtml = '';
                if (item.lines_added > 0) {
                    diffHtml += '<span class="item-meta diff-added">+' + item.lines_added + '</span>';
                }
                if (item.lines_removed > 0) {
                    diffHtml += '<span class="item-meta diff-removed">-' + item.lines_removed + '</span>';
                }
                contentHtml += diffHtml;
            } else if (item.line_count > 0) {
                contentHtml += '<span class="item-meta">' + item.line_count + ' lines</span>';
            }
            if (item.size) {
                contentHtml += '<span class="item-meta">' + item.size + '</span>';
            }
            // Add clickable diff link if file path is valid
            if (item.path && item.path !== 'Unknown' && !item.path.startsWith('Error')) {
                var escapedPath = item.path.replace(/\\/g, '\\\\').replace(/'/g, "\\'");
                contentHtml += '<span class="item-diff-link" onclick="showDiff(\'' + escapedPath + '\')">diff</span>';
            }
            contentHtml += '</div>';
        });
        contentHtml += '</div></div>';
    }
    
    // File reads section
    if (totalReads > 0) {
        contentHtml += '<div class="summary-section">';
        contentHtml += '<div class="section-header"><span class="section-icon">READ</span>Files Read (' + totalReads + ')</div>';
        contentHtml += '<div class="section-items">';
        summaryData.file_reads.forEach(function(item) {
            var fileName = item.path ? item.path.split('/').pop().split('\\').pop() : 'unknown';
            contentHtml += '<div class="summary-item">';
            contentHtml += '<span class="item-icon">READ</span>';
            contentHtml += '<span class="item-name">' + escapeHtml(fileName) + '</span>';
            contentHtml += '</div>';
        });
        contentHtml += '</div></div>';
    }
    
    // Commands section
    if (totalCommands > 0) {
        contentHtml += '<div class="summary-section">';
        contentHtml += '<div class="section-header"><span class="section-icon">RUN</span>Commands (' + totalCommands + ')</div>';
        contentHtml += '<div class="section-items">';
        summaryData.commands.forEach(function(item) {
            contentHtml += '<div class="summary-item">';
            contentHtml += '<span class="item-icon">RUN</span>';
            contentHtml += '<span class="item-name">' + escapeHtml(item.command || item.name) + '</span>';
            contentHtml += '</div>';
        });
        contentHtml += '</div></div>';
    }
    
    // Errors section
    if (totalErrors > 0) {
        contentHtml += '<div class="summary-section error">';
        contentHtml += '<div class="section-header"><span class="section-icon">ERR</span>Errors (' + totalErrors + ')</div>';
        contentHtml += '<div class="section-items">';
        summaryData.errors.forEach(function(item) {
            contentHtml += '<div class="summary-item error">';
            contentHtml += '<span class="item-icon">ERR</span>';
            contentHtml += '<span class="item-name">' + escapeHtml(item.name) + '</span>';
            contentHtml += '<span class="item-error">' + escapeHtml(item.error.substring(0, 100)) + '</span>';
            contentHtml += '</div>';
        });
        contentHtml += '</div></div>';
    }
    
    // Other operations
    if (totalOther > 0) {
        contentHtml += '<div class="summary-section">';
        contentHtml += '<div class="section-header"><span class="section-icon">INFO</span>Other (' + totalOther + ')</div>';
        contentHtml += '<div class="section-items">';
        summaryData.other.forEach(function(item) {
            contentHtml += '<div class="summary-item">';
            contentHtml += '<span class="item-icon">INFO</span>';
            contentHtml += '<span class="item-name">' + escapeHtml(item.name) + '</span>';
            contentHtml += '</div>';
        });
        contentHtml += '</div></div>';
    }
    
    contentHtml += '</div>';
    
    // Assemble card
    summaryCard.innerHTML = headerHtml + contentHtml;
    
    // Add to message
    currentAssistantMessage.appendChild(summaryCard);
    smartScroll(container);
}

function getFileIcon(type, info) {
    // Terminal file operations
    if (type.startsWith('terminal_')) {
        var opType = type.replace('terminal_', '');
        var icons = {
            'create': '<span class="file-icon terminal">+</span>',
            'create_dir': '<span class="file-icon folder">DIR</span>',
            'delete': '<span class="file-icon delete">DEL</span>',
            'delete_dir': '<span class="file-icon delete">DEL</span>',
            'move': '<span class="file-icon move">MOV</span>',
            'copy': '<span class="file-icon copy">COPY</span>',
            'rename': '<span class="file-icon rename">REN</span>'
        };
        return icons[opType] || '<span class="file-icon terminal">RUN</span>';
    }
    
    if (type === 'read_file' || type === 'write_file' || type === 'edit_file' || type === 'inject_after' || type === 'add_import' || type === 'create_file') {
        var ext = info ? info.split('.').pop().toLowerCase() : 'default';
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
    if (type === 'list_directory') return '<span class="file-icon folder">DIR</span>';
    if (type === 'create_directory') return '<span class="file-icon folder">DIR+</span>';
    if (type === 'delete_file') return '<span class="file-icon delete">DEL</span>';
    if (type === 'delete_directory') return '<span class="file-icon delete">DEL</span>';
    if (type === 'run_command') return '<span class="file-icon terminal">RUN</span>';
    if (type === 'search_code') return '<span class="file-icon search">FIND</span>';
    if (type === 'git_status' || type === 'git_diff') return '<span class="file-icon git">GIT</span>';
    if (type === 'thinking') return '<span class="file-icon think">THINK</span>';
    return '<span class="file-icon">FILE</span>';
}

function formatActivityLabel(type, info, status) {
    var isEdit = ['write_file', 'edit_file', 'inject_after', 'add_import'].includes(type) || type.startsWith('terminal_create') || type.startsWith('terminal_edit');
    var isCreate = ['create_file', 'create_directory'].includes(type);
    var isDelete = ['delete_file', 'delete_directory'].includes(type);
    var labelText = isEdit ? 'Editing...' : (isCreate ? 'Creating...' : (isDelete ? 'Deleting...' : 'Running'));
    var runningPrefix = status === 'running' ? '<span class="running-label">' + labelText + '</span> ' : '';
    
    // --- Parse JSON/Python-dict args to extract human-readable display info ---
    var displayInfo = info;
    var parsed = null;
    try {
        // First: try standard JSON parse
        parsed = JSON.parse(info);
    } catch(e1) {
        try {
            // Second: convert Python dict repr (single quotes) to JSON
            var jsonStr = info
                .replace(/'/g, '"')
                .replace(/True/g, 'true')
                .replace(/False/g, 'false')
                .replace(/None/g, 'null');
            parsed = JSON.parse(jsonStr);
        } catch(e2) {
            // Not parseable - use raw string
        }
    }
    if (parsed) {
        // Handle nested: {"PATH":{"path":"file"}} or {"path":"file"}
        var pathVal = parsed.path || (parsed.PATH && (parsed.PATH.path || parsed.PATH)) || parsed.file || null;
        if (pathVal && typeof pathVal === 'string') {
            displayInfo = pathVal.replace(/\\/g, '/').split('/').pop() || pathVal;
        } else if (parsed.pattern) {
            displayInfo = parsed.pattern;
        } else if (parsed.command) {
            displayInfo = parsed.command;
        } else if (parsed.entries && Array.isArray(parsed.entries)) {
            var dir = parsed.path || '.';
            displayInfo = dir.replace(/\\/g, '/').split('/').pop() || dir;
            displayInfo += ' (' + parsed.entries.length + ' items)';
        } else {
            var keys = Object.keys(parsed);
            if (keys.length === 1) {
                var v = parsed[keys[0]];
                if (typeof v === 'string') displayInfo = v.replace(/\\/g, '/').split('/').pop() || v;
            }
        }
    }
    
    displayInfo = escapeHtml(displayInfo);
    
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
        var checkmark = (status === 'complete' && !diffMatch) ? ' Done' : '';
        return status === 'running' ? runningPrefix + displayInfo : displayInfo + checkmark;
    }
    if (isCreate) {
        var action = type === 'create_directory' ? 'Created dir' : 'Created file';
        return status === 'running' ? runningPrefix + displayInfo : action + ' ' + displayInfo + ' Done';
    }
    if (isDelete) {
        var action = type === 'delete_directory' ? 'Deleted dir' : 'Deleted file';
        return status === 'running' ? runningPrefix + displayInfo : action + ' ' + displayInfo + ' Done';
    }
    if (type === 'list_directory') {
        return status === 'running' ? 'Exploring ' + displayInfo : 'Explored ' + displayInfo;
    }
    if (type === 'run_command') {
        return runningPrefix + '<code>' + displayInfo + '</code>' + (status === 'complete' ? ' Done' : '');
    }
    if (type === 'search_code' || type === 'grep_code' || type === 'search') {
        return 'Grepped code <code>' + displayInfo + '</code>';
    }
    if (type === 'git_status') {
        return status === 'running' ? 'Checking status' : 'Status retrieved';
    }
    if (type === 'git_diff') {
        return status === 'running' ? 'Getting diff' : 'Diff retrieved';
    }
    if (type === 'thinking') {
        return 'Thought - ' + displayInfo;
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

// Returns the animated operation badge pill for an activity item type
function getActivityOpBadge(type) {
    var label = '';
    switch (type) {
        case 'read_file':       label = 'Read';    break;
        case 'edit_file':
        case 'write_file':
        case 'inject_after':
        case 'add_import':      label = 'Edit';    break;
        case 'create_file':     label = 'Create';  break;
        case 'create_directory':label = 'Create';  break;
        case 'delete_file':
        case 'delete_directory':label = 'Delete';  break;
        case 'list_directory':  label = 'Explore'; break;
        case 'search':
        case 'grep_code':
        case 'search_files':
        case 'search_codebase': label = 'Search';  break;
        case 'run_command':     label = 'Run';     break;
        default:
            if (type && type.startsWith('terminal')) label = 'Run';
            break;
    }
    if (!label) return '';
    return '<span class="activity-op">' + label + '</span>';
}


// Render directory contents HTML (used for both live display and restoration)
function renderDirectoryContents(path, contents) {
    var container = document.getElementById('chatMessages');
    if (!container || !contents) return;
    
    var lines = contents.split('\n').filter(function(l) { return l.trim(); });
    if (lines.length === 0) return;
    
    // Normalize base path
    var basePath = path.replace(/\\/g, '/');
    if (!basePath.endsWith('/')) basePath += '/';
    
    // Get short folder name for display
    var shortPath = basePath.replace(/\/$/, '').split('/').pop() || basePath;
    
    // Create card-container structure — starts COLLAPSED; user can expand
    var card = document.createElement('div');
    card.className = 'dir-tree-card';  // no 'expanded' — collapsed by default
    
    // Card header with chevron + folder name
    var header = document.createElement('div');
    header.className = 'card-header';
    header.innerHTML = 
        '<svg class="card-chevron" width="14" height="14" viewBox="0 0 20 20" fill="currentColor" style="transform:rotate(-90deg);transition:transform 0.2s;">' +
            '<path d="M7.293 14.707a1 1 0 010-1.414L10.586 10 7.293 6.707a1 1 0 011.414-1.414l4 4a1 1 0 010 1.414l-4 4a1 1 0 01-1.414 0z"/>' +
        '</svg>' +
        '<span style="display:inline-flex;align-items:center;margin-right:6px;">' + (FILE_ICONS.folder ? FILE_ICONS.folder(14) : '') + '</span>' +
        '<span class="card-title" style="font-size:13px;color:var(--text-main);font-weight:500;">' + escapeHtml(shortPath) + '</span>' +
        '<span style="margin-left:auto;font-size:11px;color:var(--text-secondary);">' + lines.length + ' items</span>';
    
    header.style.cursor = 'pointer';
    header.onclick = function(e) {
        e.stopPropagation();
        var expanded = card.classList.toggle('expanded');
        var chev = header.querySelector('.card-chevron');
        if (chev) chev.style.transform = expanded ? 'rotate(0deg)' : 'rotate(-90deg)';
    };
    card.appendChild(header);
    
    // Card body with file/folder items
    var body = document.createElement('div');
    body.className = 'card-body';
    
    lines.forEach(function(line) {
        if (!line.trim()) return;
        
        // Check if it's a folder
        var isFolder = line.includes('\uD83D\uDCC1') || line.trim().endsWith('/');
        
        // Extract just the name (remove emoji and size info)
        var name = line.replace(/[\uD83D\uDCC1\uD83D\uDCC4]/g, '').replace(/\s*\([^)]*\)/g, '').replace(/\s*\d+B$/, '').trim();
        if (isFolder) name = name.replace(/\/$/, '');
        if (!name) return;
        
        var item = document.createElement('div');
        item.className = 'dir-item';
        
        // Get icon
        var iconHtml;
        if (isFolder) {
            iconHtml = FILE_ICONS.folder ? FILE_ICONS.folder(16) : '<span class="file-icon folder">DIR</span>';
        } else if (name.includes('.')) {
            var ext = name.split('.').pop().toLowerCase();
            iconHtml = getFileExtensionIcon(ext);
        } else {
            iconHtml = FILE_ICONS.default ? FILE_ICONS.default(16) : '<span class="file-icon">FILE</span>';
        }
        
        // Build full path for click handler
        var fullPath = basePath + name;
        var escapedPath = fullPath.replace(/'/g, "\\'");
        
        if (isFolder) {
            item.onclick = function() { openFolderInExplorer(escapedPath); };
        } else {
            item.onclick = function() { openFileInEditor(escapedPath); };
        }
        
        item.innerHTML = 
            '<span class="dir-item-icon">' + iconHtml + '</span>' +
            '<span class="dir-item-name">' + escapeHtml(name) + '</span>';
        body.appendChild(item);
    });
    
    card.appendChild(body);
    
    // Append to the current assistant message bubble
    if (currentAssistantMessage) {
        currentAssistantMessage.appendChild(card);
    } else {
        container.appendChild(card);
    }
    smartScroll(container);
}

// Display directory contents with file/folder icons (live display with persistence)
function showDirectoryContents(path, contents) {
    // Store tool activity for persistence
    if (!window._pendingToolActivities) window._pendingToolActivities = [];
    window._pendingToolActivities.push({
        type: 'directory',
        path: path,
        contents: contents
    });
    
    // Render the directory contents
    renderDirectoryContents(path, contents);
}

// Test function - can be called from console
function testDirectoryDisplay() {
    var testContent = "DIR agents/\nDIR skills/\nFILE plugin.json\nFILE main.py\nFILE script.js\nFILE index.html";
    showDirectoryContents("test_folder", testContent);
    console.log("Test directory display called");
}

// SVG file icons (VS Code style)
var FILE_ICONS = {
    python: function(s) { s=s||16; return '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32" width="'+s+'" height="'+s+'"><defs><linearGradient id="pyg" x1="0%" y1="0%" x2="100%" y2="100%"><stop offset="0%" stop-color="#387EB8"/><stop offset="100%" stop-color="#366994"/></linearGradient><linearGradient id="pyy" x1="0%" y1="0%" x2="100%" y2="100%"><stop offset="0%" stop-color="#FFE052"/><stop offset="100%" stop-color="#FFC331"/></linearGradient></defs><path d="M15.9 5C10.3 5 10.7 7.4 10.7 7.4l.01 2.5h5.3v.7H8.7S5 10.1 5 15.8c0 5.7 3.2 5.5 3.2 5.5h1.9v-2.6s-.1-3.2 3.1-3.2h5.4s3 .05 3-2.9V8.5S22.1 5 15.9 5z" fill="url(#pyg)"/><circle cx="12.5" cy="8.2" r="1.1" fill="#fff" opacity=".8"/><path d="M16.1 27c5.6 0 5.2-2.4 5.2-2.4l-.01-2.5h-5.3v-.7h7.3S27 21.9 27 16.2c0-5.7-3.2-5.5-3.2-5.5h-1.9v2.6s.1 3.2-3.1 3.2h-5.4s-3-.05-3 2.9v4.6S9.9 27 16.1 27z" fill="url(#pyy)"/><circle cx="19.5" cy="23.8" r="1.1" fill="#fff" opacity=".8"/></svg>'; },
    javascript: function(s) { s=s||16; return '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32" width="'+s+'" height="'+s+'"><rect width="32" height="32" rx="3" fill="#F7DF1E"/><path d="M20.8 24.3c.5.9 1.2 1.5 2.4 1.5 1 0 1.6-.5 1.6-1.2 0-.8-.7-1.1-1.8-1.6l-.6-.3c-1.8-.8-3-1.7-3-3.7 0-1.9 1.4-3.3 3.6-3.3 1.6 0 2.7.5 3.5 1.9l-1.9 1.2c-.4-.8-.9-1.1-1.6-1.1-.7 0-1.2.5-1.2 1.1 0 .8.5 1.1 1.6 1.5l.6.3c2.1.9 3.3 1.8 3.3 3.9 0 2.2-1.7 3.5-4 3.5-2.2 0-3.7-1.1-4.4-2.5l2-.1z" fill="#222"/><path d="M12.2 24.6c.4.6.7 1.2 1.6 1.2.8 0 1.3-.3 1.3-1.5V16h2.4v8.3c0 2.5-1.5 3.7-3.6 3.7-1.9 0-3-1-3.6-2.2l1.9-1.2z" fill="#222"/></svg>'; },
    typescript: function(s) { s=s||16; return '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32" width="'+s+'" height="'+s+'"><rect width="32" height="32" rx="3" fill="#3178C6"/><path d="M18 17.4h3.4v.9H19v1.2h2.2v.9H19V23h-1V17.4zM9 17.4h5.8v1H12V23h-1v-4.6H9v-1z" fill="#fff"/><path d="M14.2 19.9c0-1.8 1.2-2.7 2.8-2.7.7 0 1.3.1 1.8.4l-.3.9c-.4-.2-.9-.3-1.4-.3-1 0-1.7.6-1.7 1.7 0 1.1.7 1.8 1.8 1.8.3 0 .6 0 .8-.1v-1.2H17v-.9h2v2.7c-.5.3-1.2.5-2 .5-1.8 0-2.8-1-2.8-2.8z" fill="#fff"/></svg>'; },
    react: function(s) { s=s||16; return '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32" width="'+s+'" height="'+s+'"><circle cx="16" cy="16" r="2.5" fill="#61DAFB"/><ellipse cx="16" cy="16" rx="11" ry="4.2" fill="none" stroke="#61DAFB" stroke-width="1.3"/><ellipse cx="16" cy="16" rx="11" ry="4.2" fill="none" stroke="#61DAFB" stroke-width="1.3" transform="rotate(60 16 16)"/><ellipse cx="16" cy="16" rx="11" ry="4.2" fill="none" stroke="#61DAFB" stroke-width="1.3" transform="rotate(120 16 16)"/></svg>'; },
    vue: function(s) { s=s||16; return '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32" width="'+s+'" height="'+s+'"><polygon points="16,27 2,5 8.5,5 16,18.5 23.5,5 30,5" fill="#41B883"/><polygon points="16,20 9.5,9 13,9 16,14 19,9 22.5,9" fill="#35495E"/></svg>'; },
    svelte: function(s) { s=s||16; return '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32" width="'+s+'" height="'+s+'"><path d="M26.1 5.8c-2.8-4-8.4-5-12.4-2.3L7.2 7.7C5.3 9 4 11 3.8 13.3c-.2 1.9.3 3.8 1.4 5.3-.8 1.2-1.2 2.7-1.1 4.1.2 2.7 1.9 5.1 4.4 6.2 2.8 1.2 6 .7 8.3-1.2l6.5-4.2c1.9-1.3 3.2-3.3 3.4-5.6.2-1.9-.3-3.8-1.4-5.3.8-1.2 1.2-2.7 1.1-4.1-.1-1.1-.5-2.2-1.3-2.7z" fill="#FF3E00"/><path d="M13.7 27c-1.6.4-3.3 0-4.6-.9-1.8-1.3-2.5-3.5-1.8-5.5l.2-.5.4.3c1 .7 2 1.2 3.2 1.5l.3.1-.03.3c-.05.7.2 1.4.7 1.9.9.8 2.3.9 3.3.2l6.5-4.2c.6-.4 1-.9 1.1-1.6.1-.7-.1-1.4-.6-1.9-.9-.8-2.3-.9-3.3-.2l-2.5 1.6c-1.1.7-2.4 1-3.7.8-1.5-.2-2.8-1-3.6-2.2-1.4-2-1-4.7.9-6.2l6.5-4.2c1.6-1.1 3.7-1.3 5.5-.6 1.8.7 3 2.3 3.2 4.2.1.7 0 1.5-.3 2.2l-.2.5-.4-.3c-1-.7-2-1.2-3.2-1.5l-.3-.1.03-.3c.05-.7-.2-1.4-.7-1.9-.9-.8-2.3-.9-3.3-.2l-6.5 4.2c-.6.4-1 .9-1.1 1.6-.1.7.1 1.4.6 1.9.9.8 2.3.9 3.3.2l2.5-1.6c1.1-.7 2.4-1 3.7-.8 1.5.2 2.8 1 3.6 2.2 1.4 2 1 4.7-.9 6.2L18 26.3c-.8.5-1.5.8-2.3.7z" fill="#fff"/></svg>'; },
    html: function(s) { s=s||16; return '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32" width="'+s+'" height="'+s+'"><path d="M4 3l2.3 25.7L16 31l9.7-2.3L28 3z" fill="#E44D26"/><path d="M16 28.4V5.7l10.2 22.7z" fill="#F16529"/><path d="M9.4 13.5l.4 3.9H16v-3.9zM8.7 8H16V4.1H8.3zM16 21.5l-.05.01-4.1-1.1-.26-3h-3.9l.5 5.7 7.8 2.2z" fill="#EBEBEB"/><path d="M16 13.5v3.9h5.9l-.6 6.1-5.3 1.5v4l7.8-2.2.06-.6 1.2-13.1.12-1.6zm0-9.4v3.9h10.2l.08-1 .18-2.9z" fill="#fff"/></svg>'; },
    css: function(s) { s=s||16; return '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32" width="'+s+'" height="'+s+'"><path d="M4 3l2.3 25.7L16 31l9.7-2.3L28 3z" fill="#1572B6"/><path d="M16 28.4V5.7l10.2 22.7z" fill="#33A9DC"/><path d="M21.5 13.5H16v-3.9h6l.4-3.6H9.6L10 9.6h5.9v3.9H9.3l.4 3.6H16v4.1l-4.2-1.2-.3-3.1H7.7l.6 6.3 7.7 2.1z" fill="#fff"/><path d="M16 17.2v-3.7h5.1l-.5 5.2L16 19.9v4.1l7.7-2.1.1-.6 1-10.4.1-1.4H16v4zM16 5.7v3.9h5.7l.1-1 .2-2.9z" fill="#EBEBEB"/></svg>'; },
    scss: function(s) { s=s||16; return '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32" width="'+s+'" height="'+s+'"><circle cx="16" cy="16" r="13" fill="#CD6799"/><path d="M22.5 14.7c-.7-.3-1.1-.4-1.6-.6-.3-.1-.6-.2-.8-.3-.2-.1-.4-.2-.4-.4 0-.3.4-.6 1.2-.6.9 0 1.7.3 2.1.5l.8-1.8c-.5-.3-1.5-.7-2.9-.7-1.5 0-2.7.4-3.5 1.1-.7.7-1 1.5-.9 2.4.1.9.7 1.6 1.9 2.1.5.2 1 .3 1.4.5.3.1.5.2.7.3.2.2.3.4.2.7-.1.5-.7.8-1.5.8-1 0-1.9-.3-2.5-.7l-.8 1.9c.7.4 1.8.7 3 .7h.3c1.3-.05 2.4-.4 3.1-1.1.7-.7 1-1.5.9-2.5-.1-.9-.7-1.6-1.7-2.3zm-7.6-4.2c-1.5 0-2.8.5-3.7 1.3l-.8-1.2-2.1 1.2.9 1.4c-.6.9-1 2-1 3.2s.4 2.3 1.1 3.2l-1.1 1.2 1.6 1.4 1.2-1.3c.9.5 1.9.8 3.1.8 3.4 0 5.7-2.5 5.7-5.7-.1-3-2.1-5.5-4.9-5.5zm-.3 9c-1.9 0-3.2-1.4-3.2-3.3s1.3-3.3 3.2-3.3c.8 0 1.5.3 2 .8l-3.4 4.2c.4.4.9.6 1.4.6z" fill="#fff"/></svg>'; },
    java: function(s) { s=s||16; return '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32" width="'+s+'" height="'+s+'"><path d="M12.2 22.1s-1.2.7.8 1c2.4.3 3.6.2 6.2-.2 0 0 .7.4 1.6.8-5.7 2.4-12.9-.1-8.6-1.6zM11.5 19s-1.3 1 .7 1.2c2.5.3 4.5.3 8-.4 0 0 .5.5 1.2.8-7.1 2.1-15-.2-9.9-1.6z" fill="#E76F00"/><path d="M17.2 13.4c1.4 1.7-.4 3.2-.4 3.2s3.6-1.9 2-4.2c-1.5-2.2-2.6-3.3 3.6-7.1 0 0-9.8 2.4-5.2 8.1z" fill="#E76F00"/><path d="M23.2 24.4s.9.7-.9 1.3c-3.4 1-14.1 1.3-17.1 0-1.1-.5.9-1.1 1.5-1.2.6-.1 1-.1 1-.1-1.1-.8-7.4 1.6-3.2 2.3 11.6 1.9 21.1-.8 18.7-2.3zM12.6 15.9s-5.3 1.3-1.9 1.8c1.5.2 4.4.2 7.1-.1 2.2-.3 4.5-.8 4.5-.8s-.8.3-1.3.7c-5.4 1.4-15.7.8-12.8-.7 2.5-1.3 4.4-1 4.4-.9zM20.6 20.8c5.4-2.8 2.9-5.6 1.2-5.2-.4.1-.6.2-.6.2s.2-.3.5-.4c3.6-1.3 6.4 3.8-1.1 5.8 0 0 .1-.1 0-.4z" fill="#E76F00"/><path d="M18.5 3s3 3-2.9 7.7c-4.7 3.8-1.1 5.9 0 8.3-2.7-2.5-4.7-4.7-3.4-6.7 2-3 7.5-4.4 6.3-9.3z" fill="#E76F00"/></svg>'; },
    kotlin: function(s) { s=s||16; return '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32" width="'+s+'" height="'+s+'"><defs><linearGradient id="ktg2" x1="0%" y1="0%" x2="100%" y2="100%"><stop offset="0%" stop-color="#7F52FF"/><stop offset="49%" stop-color="#C811E1"/><stop offset="100%" stop-color="#E54857"/></linearGradient></defs><polygon points="4,4 16.5,4 4,17" fill="url(#ktg2)"/><polygon points="4,17 16.5,4 28,28 4,28" fill="url(#ktg2)"/><polygon points="16.5,4 28,4 28,16.5" fill="url(#ktg2)"/></svg>'; },
    swift: function(s) { s=s||16; return '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32" width="'+s+'" height="'+s+'"><rect width="32" height="32" rx="7" fill="#F05138"/><path d="M24.5 19.2c.1-.3.2-.6.2-1 0-2.4-2.4-4.6-5.9-5.3 2.3 1.8 3.4 4.1 2.8 5.9-.1.2-.2.4-.4.6-1.1-1.1-2.8-2.1-4.8-2.7-1.7-.5-3.3-.7-4.7-.5.5.4 1 .8 1.4 1.3 2.4 2.4 3.2 5.3 1.9 6.9-.1.1-.2.2-.3.3 1.2.2 2.6.1 4-.4 1.4-.5 2.6-1.3 3.5-2.3 1.1.3 2.1.4 3.2.3.9-.1 1.7-.3 2.4-.6l-.5-.3c-.8-.4-1.9-.8-2.8-1.2zm-12.7 2.4c-1.6-.5-2.9-1.4-3.6-2.6-.4-.7-.6-1.5-.5-2.3.1-1.4 1.1-2.7 2.7-3.4-1.6.2-3 .8-4 1.9-.7.7-1.1 1.6-1.1 2.5 0 2.2 2.2 4.1 5.5 4.8l1-.9z" fill="#fff"/></svg>'; },
    go: function(s) { s=s||16; return '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32" width="'+s+'" height="'+s+'"><path d="M16 5C9.4 5 4 10.4 4 17s5.4 12 12 12 12-5.4 12-12S22.6 5 16 5zm0 21c-5 0-9-4-9-9s4-9 9-9 9 4 9 9-4 9-9 9z" fill="#00ACD7"/><circle cx="12.5" cy="14.5" r="1.3" fill="#00ACD7"/><circle cx="19.5" cy="14.5" r="1.3" fill="#00ACD7"/><path d="M13 19s.7 2 3 2 3-2 3-2H13z" fill="#00ACD7"/></svg>'; },
    rust: function(s) { s=s||16; return '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32" width="'+s+'" height="'+s+'"><path d="M16 3L18.1 7.3 22.8 6.2 22.7 11 27.1 12.9 24.5 17 27.1 21.1 22.7 23 22.8 27.8 18.1 26.7 16 31 13.9 26.7 9.2 27.8 9.3 23 4.9 21.1 7.5 17 4.9 12.9 9.3 11 9.2 6.2 13.9 7.3z" fill="#DEA584"/><circle cx="16" cy="17" r="5" fill="none" stroke="#DEA584" stroke-width="2"/><circle cx="16" cy="17" r="2.5" fill="#DEA584"/></svg>'; },
    c: function(s) { s=s||16; return '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32" width="'+s+'" height="'+s+'"><circle cx="16" cy="16" r="13" fill="#005B9F"/><path d="M22.5 20.4c-.8 2.5-3.1 4.3-5.8 4.3-3.4 0-6.1-2.7-6.1-6.1 0-3.4 2.7-6.1 6.1-6.1 2.8 0 5.1 1.9 5.9 4.4H20c-.6-1.3-1.9-2.1-3.3-2.1-2 0-3.7 1.6-3.7 3.7s1.7 3.7 3.7 3.7c1.5 0 2.7-.9 3.3-2.2h2.5z" fill="#fff"/></svg>'; },
    cpp: function(s) { s=s||16; return '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32" width="'+s+'" height="'+s+'"><circle cx="16" cy="16" r="13" fill="#00599C"/><path d="M18 20.4c-.8 2.5-3.1 4.3-5.8 4.3-3.4 0-6.1-2.7-6.1-6.1 0-3.4 2.7-6.1 6.1-6.1 2.8 0 5.1 1.9 5.9 4.4h-2.6c-.6-1.3-1.9-2.1-3.3-2.1-2 0-3.7 1.6-3.7 3.7s1.7 3.7 3.7 3.7c1.5 0 2.7-.9 3.3-2.2H18z" fill="#fff"/><path d="M21 13.3v1.5h-1.5V16H21v1.7h1.5V16H24v-1.2h-1.5v-1.5zm4.5 0v1.5H24V16h1.5v1.7H27V16h1.5v-1.2H27v-1.5z" fill="#fff"/></svg>'; },
    csharp: function(s) { s=s||16; return '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32" width="'+s+'" height="'+s+'"><defs><linearGradient id="csg2" x1="0%" y1="0%" x2="100%" y2="100%"><stop offset="0%" stop-color="#9B4F96"/><stop offset="100%" stop-color="#68217A"/></linearGradient></defs><circle cx="16" cy="16" r="13" fill="url(#csg2)"/><path d="M10 19.8c-.8-2.1.1-4.6 2.1-5.8s4.5-1 6.3.5l-1 1.7c-1.2-.9-2.8-1.1-4.1-.3-1.3.7-1.9 2.2-1.5 3.6l-1.8.3zm12 0c-.5 1.4-1.7 2.5-3.1 2.8l-.4-1.9c.8-.2 1.4-.8 1.7-1.5l1.8.6z" fill="#fff"/><path d="M20 13.4h1.2v1.2H20zm0 2.4h1.2v1.2H20zm2.4-2.4h1.2v1.2h-1.2zm0 2.4h1.2v1.2h-1.2z" fill="#fff"/></svg>'; },
    ruby: function(s) { s=s||16; return '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32" width="'+s+'" height="'+s+'"><defs><linearGradient id="rbg2" x1="0%" y1="100%" x2="100%" y2="0%"><stop offset="0%" stop-color="#FF0000"/><stop offset="100%" stop-color="#A30000"/></linearGradient></defs><path d="M22.9 5L27 9.1l.1 17.8-4.2 4.1H9L5 27.1 4.9 9.3 9 5z" fill="url(#rbg2)"/><path d="M11 10l-3 3v9l3 3h10l3-3v-9l-3-3zm.5 13l-2-2v-7l2-2h9l2 2v7l-2 2z" fill="#fff" opacity=".7"/><circle cx="16" cy="16" r="2.5" fill="#fff"/></svg>'; },
    php: function(s) { s=s||16; return '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32" width="'+s+'" height="'+s+'"><ellipse cx="16" cy="16" rx="14" ry="9" fill="#8892BF"/><path d="M10.5 12H8l-2 8h2l.5-2h2l.5 2h2zm-.5 4.5H9l.5-2h.5zm6.5-4.5h-3l-2 8h2l.5-2h1c1.7 0 3-1.3 3-3s-1.3-3-2.5-3zm-.5 4.5H16l.5-2h.5c.5 0 1 .5 1 1s-.5 1-1 1zm7.5-4.5h-3l-2 8h2l.5-2h2l.5 2h2zm-.5 4.5h-1l.5-2h.5z" fill="#fff"/></svg>'; },
    dart: function(s) { s=s||16; return '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32" width="'+s+'" height="'+s+'"><path d="M5 18.5L8.5 5l8.5 1L5 18.5z" fill="#54C5F8"/><path d="M5 18.5L13.5 27H27L5 18.5z" fill="#01579B"/><path d="M8.5 5L27 5 27 22 17 6z" fill="#29B6F6"/><path d="M17 6L27 22 27 5z" fill="#01579B" opacity=".5"/><path d="M13.5 27L5 18.5 8.5 5z" fill="#29B6F6" opacity=".5"/></svg>'; },
    sql: function(s) { s=s||16; return '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32" width="'+s+'" height="'+s+'"><ellipse cx="16" cy="10" rx="10" ry="4" fill="#4479A1"/><path d="M6 10v4c0 2.2 4.5 4 10 4s10-1.8 10-4v-4c0 2.2-4.5 4-10 4S6 12.2 6 10z" fill="#4479A1"/><path d="M6 14v4c0 2.2 4.5 4 10 4s10-1.8 10-4v-4c0 2.2-4.5 4-10 4S6 16.2 6 14z" fill="#336791"/><path d="M6 18v4c0 2.2 4.5 4 10 4s10-1.8 10-4v-4c0 2.2-4.5 4-10 4S6 20.2 6 18z" fill="#336791"/></svg>'; },
    markdown: function(s) { s=s||16; return '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32" width="'+s+'" height="'+s+'"><rect x="2" y="7" width="28" height="18" rx="3" fill="#42A5F5"/><path d="M7 22V10h3l3 4 3-4h3v12h-3v-7l-3 4-3-4v7zm16 0l-4-6h2.5v-6h3v6H27z" fill="#fff"/></svg>'; },
    json: function(s) { s=s||16; return '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32" width="'+s+'" height="'+s+'"><path d="M12.7 6c-1.5 0-2.5.4-3 1.1-.5.7-.5 1.7-.5 2.5v2.2c0 .8-.2 1.5-.8 1.9-.3.2-.7.3-1.4.3v4c.7 0 1.1.1 1.4.3.6.4.8 1.1.8 1.9v2.2c0 .8 0 1.8.5 2.5.5.7 1.5 1.1 3 1.1H14v-2h-1.3c-.7 0-.9-.2-1-.4-.1-.2-.1-.7-.1-1.4v-2.2c0-1.2-.3-2.2-1.2-2.8-.2-.2-.5-.3-.8-.4.3-.1.5-.2.8-.4.9-.6 1.2-1.6 1.2-2.8V9.8c0-.7 0-1.2.1-1.4.1-.2.3-.4 1-.4H14V6h-1.3zm6.6 0v2h1.3c.7 0 .9.2 1 .4.1.2.1.7.1 1.4v2.2c0 1.2.3 2.2 1.2 2.8.2.2.5.3.8.4-.3.1-.5.2-.8.4-.9.6-1.2 1.6-1.2 2.8v2.2c0 .7 0 1.2-.1 1.4-.1.2-.3.4-1 .4H18v2h1.3c1.5 0 2.5-.4 3-1.1.5-.7.5-1.7.5-2.5v-2.2c0-.8.2-1.5.8-1.9.3-.2.7-.3 1.4-.3v-4c-.7 0-1.1-.1-1.4-.3-.6-.4-.8-1.1-.8-1.9V9.8c0-.8 0-1.8-.5-2.5C21.8 6.4 20.8 6 19.3 6z" fill="#F5A623"/></svg>'; },
    yaml: function(s) { s=s||16; return '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32" width="'+s+'" height="'+s+'"><rect width="32" height="32" rx="3" fill="#CC1018"/><path d="M7 9h2.5l3 5 3-5H18l-4.5 7v6h-2v-6zm11 4h7v2h-2.5v8h-2v-8H18z" fill="#fff"/></svg>'; },
    docker: function(s) { s=s||16; return '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32" width="'+s+'" height="'+s+'"><path d="M28.8 14.5c-.5-.3-1.6-.5-2.5-.3-.1-.9-.7-1.7-1.6-2.3l-.5-.3-.4.4c-.5.6-.7 1.6-.6 2.3.1.5.3.9.6 1.3-.3.1-.8.3-1.5.3H4.1c-.3 1.3-.1 3 .9 4.2.9 1.2 2.3 1.9 4.3 1.9 4 0 7-1.8 8.9-5 1.1.1 3.4.1 4.6-2.2.1 0 .6-.3 1.6-.9l.5-.3-.1-.1z" fill="#2396ED"/><rect x="7" y="13" width="2" height="2" rx=".3" fill="#2396ED"/><rect x="9.7" y="13" width="2" height="2" rx=".3" fill="#2396ED"/><rect x="12.4" y="13" width="2" height="2" rx=".3" fill="#2396ED"/><rect x="15.1" y="13" width="2" height="2" rx=".3" fill="#2396ED"/><rect x="17.8" y="13" width="2" height="2" rx=".3" fill="#2396ED"/><rect x="12.4" y="11" width="2" height="2" rx=".3" fill="#2396ED"/><rect x="15.1" y="11" width="2" height="2" rx=".3" fill="#2396ED"/><rect x="17.8" y="11" width="2" height="2" rx=".3" fill="#2396ED"/><rect x="15.1" y="9" width="2" height="2" rx=".3" fill="#2396ED"/></svg>'; },
    git: function(s) { s=s||16; return '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32" width="'+s+'" height="'+s+'"><path d="M29.5 14.5L17.5 2.5c-.7-.7-1.8-.7-2.5 0L12.4 5l3 3c.7-.2 1.5 0 2 .6.6.5.8 1.3.6 2l2.9 2.9c.7-.2 1.5 0 2 .6.9.9.9 2.3 0 3.2-.9.9-2.3.9-3.2 0-.6-.6-.8-1.5-.5-2.2L16.5 12v8c.2.1.4.2.6.4.9.9.9 2.3 0 3.2-.9.9-2.3.9-3.2 0-.9-.9-.9-2.3 0-3.2.2-.2.5-.4.7-.5v-8c-.2-.1-.5-.3-.7-.5-.6-.6-.8-1.5-.5-2.2L10.5 6.1 2.5 14c-.7.7-.7 1.8 0 2.5l12 12c.7.7 1.8.7 2.5 0l12.5-12.5c.7-.7.7-1.8 0-2.5z" fill="#F34F29"/></svg>'; },
    shell: function(s) { s=s||16; return '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32" width="'+s+'" height="'+s+'"><rect width="32" height="32" rx="3" fill="#1E1E1E"/><path d="M6 10l7 6-7 6" fill="none" stroke="#4EC9B0" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"/><path d="M16 22h10" stroke="#4EC9B0" stroke-width="2.5" stroke-linecap="round"/></svg>'; },
    lua: function(s) { s=s||16; return '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32" width="'+s+'" height="'+s+'"><circle cx="16" cy="16" r="13" fill="#000082"/><circle cx="16" cy="16" r="8" fill="none" stroke="#fff" stroke-width="2.5"/><circle cx="22" cy="10" r="3" fill="#fff"/></svg>'; },
    r: function(s) { s=s||16; return '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32" width="'+s+'" height="'+s+'"><ellipse cx="16" cy="15" rx="12" ry="12" fill="#2165B6"/><path d="M13 7h4c3.3 0 6 1.3 6 4.5 0 2-1.2 3.5-3 4.2l4 6.3h-3.5L16.5 16H13v6h-2.5V7z" fill="#fff"/><path d="M13 13.5h2.3c1.3 0 2.7-.5 2.7-2s-1.4-2-2.7-2H13z" fill="#2165B6"/></svg>'; },
    elixir: function(s) { s=s||16; return '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32" width="'+s+'" height="'+s+'"><defs><linearGradient id="exg2" x1="0%" y1="0%" x2="100%" y2="100%"><stop offset="0%" stop-color="#D9006C"/><stop offset="100%" stop-color="#6C0098"/></linearGradient></defs><path d="M16 3c-4 4-7 9-7 13.5C9 21.6 12 27 16 27s7-5.4 7-10.5C23 12 20 7 16 3z" fill="url(#exg2)"/><path d="M16 10c-2 2-3 5-3 7.5C13 20 14.5 22 16 22c1.5 0 3-2 3-4.5 0-2.5-1-5.5-3-7.5z" fill="#fff" opacity=".35"/></svg>'; },
    haskell: function(s) { s=s||16; return '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32" width="'+s+'" height="'+s+'"><polygon points="3,26 11,16 3,6 7,6 15,16 7,26" fill="#5D4F85"/><polygon points="8,26 16,16 8,6 12,6 20,16 12,26" fill="#8F4E8B"/><polygon points="16,11 29,11 26,16 29,21 16,21 19,16" fill="#5D4F85"/></svg>'; },
    clojure: function(s) { s=s||16; return '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32" width="'+s+'" height="'+s+'"><circle cx="16" cy="16" r="13" fill="#5881D8"/><circle cx="16" cy="16" r="8" fill="none" stroke="#63B132" stroke-width="2.5"/><circle cx="16" cy="16" r="3.5" fill="#63B132"/></svg>'; },
    zig: function(s) { s=s||16; return '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32" width="'+s+'" height="'+s+'"><rect width="32" height="32" rx="3" fill="#F7A41D"/><path d="M6 8h14l-6 7 6 1H6l6-7z" fill="#1B1B1B"/><path d="M12 16h14l-6 8H6l6-8z" fill="#1B1B1B"/></svg>'; },
    julia: function(s) { s=s||16; return '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32" width="'+s+'" height="'+s+'"><circle cx="11" cy="22" r="6" fill="#CB3C33"/><circle cx="21" cy="22" r="6" fill="#389826"/><circle cx="16" cy="13" r="6" fill="#9558B2"/></svg>'; },
    env: function(s) { s=s||16; return '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32" width="'+s+'" height="'+s+'"><rect width="32" height="32" rx="3" fill="#4A9B4F"/><path d="M8 4h10l6 6v18H8V4z" fill="#5DBA5F"/><path d="M18 4v6h6" fill="none" stroke="#fff" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/><text x="16" y="22" font-family="Segoe UI,sans-serif" font-size="7" font-weight="bold" fill="#fff" text-anchor="middle">ENV</text></svg>'; },
    txt: function(s) { s=s||16; return '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32" width="'+s+'" height="'+s+'"><path d="M8 4h10l6 6v18H8V4z" fill="#9AAABB"/><path d="M18 4v6h6" fill="none" stroke="#fff" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/><line x1="10" y1="13" x2="22" y2="13" stroke="#fff" stroke-width="1.5" stroke-linecap="round"/><line x1="10" y1="17" x2="22" y2="17" stroke="#fff" stroke-width="1.5" stroke-linecap="round"/><line x1="10" y1="21" x2="18" y2="21" stroke="#fff" stroke-width="1.5" stroke-linecap="round"/></svg>'; },
    config: function(s) { s=s||16; return '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32" width="'+s+'" height="'+s+'"><rect width="32" height="32" rx="3" fill="#607D8B"/><circle cx="16" cy="16" r="5" fill="none" stroke="#fff" stroke-width="2"/><path d="M16 5v4M16 23v4M5 16h4M23 16h4M8.5 8.5l2.8 2.8M20.7 20.7l2.8 2.8M8.5 23.5l2.8-2.8M20.7 11.3l2.8-2.8" stroke="#fff" stroke-width="2" stroke-linecap="round"/></svg>'; },
    default: function(s) { s=s||16; return '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32" width="'+s+'" height="'+s+'"><path d="M8 4h10l6 6v18H8V4z" fill="#90A4AE"/><path d="M18 4v6h6" fill="none" stroke="#fff" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg>'; },
    folder: function(s) { s=s||16; return '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32" width="'+s+'" height="'+s+'"><path d="M3 9c0-1.1.9-2 2-2h8l3 3h11c1.1 0 2 .9 2 2v13c0 1.1-.9 2-2 2H5c-1.1 0-2-.9-2-2V9z" fill="#4A90D9"/><path d="M3 13h26v11c0 1.1-.9 2-2 2H5c-1.1 0-2-.9-2-2V13z" fill="#5BA4E9"/></svg>'; }
};

// Extension to icon mapping
var EXT_TO_ICON = {
    'py':'python','pyw':'python','pyi':'python','ipynb':'python',
    'js':'javascript','mjs':'javascript','cjs':'javascript',
    'ts':'typescript','tsx':'react','jsx':'react',
    'vue':'vue','svelte':'svelte',
    'html':'html','htm':'html','css':'css','scss':'scss','sass':'scss','less':'scss',
    'java':'java','jar':'java','groovy':'java',
    'kt':'kotlin','kts':'kotlin',
    'swift':'swift',
    'go':'go',
    'rs':'rust',
    'c':'c','h':'c','cpp':'cpp','cxx':'cpp','cc':'cpp','hpp':'cpp',
    'cs':'csharp',
    'rb':'ruby','erb':'ruby','rake':'ruby',
    'php':'php',
    'dart':'dart',
    'sh':'shell','bash':'shell','zsh':'shell','bat':'shell','cmd':'shell','ps1':'shell',
    'sql':'sql','sqlite':'sql',
    'ex':'elixir','exs':'elixir','erl':'elixir',
    'hs':'haskell','lhs':'haskell',
    'clj':'clojure','cljs':'clojure',
    'lua':'lua',
    'r':'r','rmd':'r',
    'jl':'julia',
    'zig':'zig',
    'json':'json','json5':'json',
    'yaml':'yaml','yml':'yaml',
    'toml':'config','ini':'config','cfg':'config','env':'env',
    'txt':'txt','text':'txt',
    'md':'markdown','mdx':'markdown',
    'git':'git','gitignore':'git','gitattributes':'git',
    'dockerfile':'docker','dockerignore':'docker',
};

function getFileExtensionIcon(ext, size) {
    size = size || 16;
    var key = EXT_TO_ICON[ext.toLowerCase()];
    if (key && FILE_ICONS[key]) {
        return FILE_ICONS[key](size);
    }
    return FILE_ICONS.default(size);
}

function showThinking() {
    activityStartTime = Date.now();
    _thinkingStartTime = Date.now();
    var container = document.getElementById('chatMessages');
    if (!container) return;

    // Hide the standalone thinking-message bubble once real activity starts
    hideThinkingAnimation();

    // Show agent mode indicator with animated Think mode
    if (window.showAgentMode && window.setAgentMode) {
        window.showAgentMode();
        window.setAgentMode('think');
    }

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
            '<svg class="activity-spinner" viewBox="0 0 24 24" width="14" height="14"><circle cx="12" cy="12" r="10" fill="none" stroke="currentColor" stroke-width="2" opacity="0.15"/><path d="M12 2 A 10 10 0 1 1 2 12" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg>' +
            '<span class="activity-title"><span class="activity-text-shimmer">Working</span></span>' +
            '<svg class="activity-toggle" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="6 9 12 15 18 9"></polyline></svg>';
        header.onclick = function() {
            currentActivitySection.classList.toggle('collapsed');
            var t = header.querySelector('.activity-toggle');
            if (t) t.style.transform = currentActivitySection.classList.contains('collapsed') ? 'rotate(-90deg)' : 'rotate(0deg)';
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

    // -- FREEZE any previous thinking item ---------------------------------
    // Convert ALL existing thinking-indicator elements to static state
    var prevThinking = document.getElementById('thinking-indicator');
    if (prevThinking) {
        prevThinking.removeAttribute('id');          // de-register old id
        prevThinking.className = 'activity-item';    // removes 'thinking' class ? stops blink
        var dotsEl = prevThinking.querySelector('.thinking-dots');
        if (dotsEl) dotsEl.textContent = '.';       // replace '...' with static bullet
    }

    // -- Add new ACTIVE thinking item at the bottom of the list ------------
    var thinkingItem = document.createElement('div');
    thinkingItem.className = 'activity-item thinking';
    thinkingItem.id = 'thinking-indicator';
    thinkingItem.setAttribute('data-type', 'think');
    thinkingItem.innerHTML = '<span class="activity-op">Think</span><span class="thinking-dots">...</span> <span class="activity-text">Thinking</span>';
    list.appendChild(thinkingItem);

    // Update thinking duration every second
    if (thinkingInterval) clearInterval(thinkingInterval);
    thinkingInterval = setInterval(function() {
        var elapsed = Math.floor((Date.now() - activityStartTime) / 1000);
        var item = document.getElementById('thinking-indicator');
        if (item) {
            item.querySelector('.activity-text').textContent = 'Thinking - ' + elapsed + 's';
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
        item.className = 'activity-item complete'; // mark complete → stops ALL running animations
        var dotsEl = item.querySelector('.thinking-dots');
        if (dotsEl) {
            dotsEl.textContent = '·';           // freeze to static bullet
            dotsEl.style.animation = 'none'; // stop dotsWave even if class stays
            dotsEl.style.opacity = '0.4';
        }
        var textEl = item.querySelector('.activity-text');
        if (textEl) {
            textEl.style.animation = 'none'; // stop silverWave
            textEl.style.color = 'var(--text-dim)';
        }
        var opEl = item.querySelector('.activity-op');
        if (opEl) {
            opEl.style.animation = 'none';   // stop badgePulse
            opEl.style.opacity = '0.4';
        }
    }
    
    // Hide agent mode indicator
    if (window.hideAgentMode) {
        window.hideAgentMode();
    }
}

function clearActivitySection() {
    // Remove the entire activity section when task is complete
    if (currentActivitySection) {
        currentActivitySection.remove();
        currentActivitySection = null;
    }
}

// Collapse (not remove) the activity section on completion — shows only summary header
function collapseActivitySection() {
    if (!currentActivitySection) return;

    var section = currentActivitySection;

    // Count items for summary
    var items = section.querySelectorAll('.activity-item');
    var total = items.length;

    // Build summary label  e.g. "Explored  · 3 steps"
    var reads = 0, edits = 0, explores = 0, thoughts = 0, searches = 0;
    items.forEach(function(it) {
        var t = it.getAttribute('data-type') || '';
        if (t === 'read_file') reads++;
        else if (t === 'edit_file' || t === 'write_file') edits++;
        else if (t === 'list_directory') explores++;
        else if (t === 'think' || it.classList.contains('thinking')) thoughts++;
        else if (t === 'search_code' || t === 'grep_code' || t === 'search_codebase') searches++;
    });

    var parts = [];
    if (reads > 0)    parts.push(reads + ' read');
    if (edits > 0)    parts.push(edits + ' edit');
    if (explores > 0) parts.push(explores + ' explore');
    if (searches > 0) parts.push(searches + ' search');
    if (thoughts > 0) parts.push(thoughts + ' thought');
    var summaryLabel = parts.length ? parts.join(' · ') : (total + ' steps');

    // Update header: stop spinner, update text, rotate chevron
    var headerEl = section.querySelector('.activity-header');
    if (headerEl) {
        // Stop the spinning SVG (.activity-spinner) and replace with static check icon
        var spinnerEl = headerEl.querySelector('.activity-spinner');
        if (spinnerEl) {
            spinnerEl.style.animation = 'none';
            spinnerEl.style.opacity = '0.45';
        }
        // Also handle legacy .activity-icon if present
        var iconEl = headerEl.querySelector('.activity-icon');
        if (iconEl) {
            iconEl.className = 'activity-icon complete';
            iconEl.style.animation = 'none';
            iconEl.innerHTML = '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M21 21l-4.35-4.35"/><circle cx="11" cy="11" r="8"/></svg>';
        }
        var titleEl = headerEl.querySelector('.activity-title');
        if (titleEl) titleEl.textContent = 'Explored';

        // Add summary count chip
        var existingChip = headerEl.querySelector('.activity-summary-chip');
        if (!existingChip) {
            var chip = document.createElement('span');
            chip.className = 'activity-summary-chip';
            chip.textContent = summaryLabel;
            // Insert before the chevron toggle
            var toggle = headerEl.querySelector('.activity-toggle');
            if (toggle) headerEl.insertBefore(chip, toggle);
            else headerEl.appendChild(chip);
        }

        // Rotate chevron to point right (collapsed state)
        var toggle2 = headerEl.querySelector('.activity-toggle');
        if (toggle2) toggle2.style.transform = 'rotate(-90deg)';
    }

    // Collapse the list
    section.classList.add('collapsed');

    // Force-stop animations on ALL remaining running items inside
    section.querySelectorAll('.activity-item.running, .activity-item.thinking').forEach(function(it) {
        it.className = 'activity-item complete';
        var el;
        el = it.querySelector('.thinking-dots');
        if (el) { el.style.animation = 'none'; el.style.opacity = '0.4'; el.textContent = '·'; }
        el = it.querySelector('.activity-text');
        if (el) { el.style.animation = 'none'; el.style.color = 'var(--text-dim)'; }
        el = it.querySelector('.activity-op');
        if (el) { el.style.animation = 'none'; el.style.opacity = '0.4'; }
    });

    // Null the reference so the next response gets a fresh section
    currentActivitySection = null;
}

function updateActivityHeader(count, status) {
    var header = document.querySelector('.activity-header .activity-title');
    if (header) {
        header.textContent = status === 'complete' ? 'Explored ' + count + ' files' : 'Exploring';
    }
    var icon = document.querySelector('.activity-header .activity-icon');
    if (icon) {
        icon.textContent = status === 'complete' ? '?' : '?';
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

    // -- Build card element --------------------------------------------------
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
                        console.log('[Diff-Handler] Button clicked for path:', p);
                        console.log('[Diff-Handler] window.bridge:', !!window.bridge);
                        console.log('[Diff-Handler] window.bridge.on_show_diff:', !!(window.bridge && window.bridge.on_show_diff));
                        if (window.bridge && window.bridge.on_show_diff) window.bridge.on_show_diff(p);
                        else if (bridge && bridge.on_show_diff) bridge.on_show_diff(p);
                        else console.error('[Diff-Handler] Neither window.bridge nor bridge has on_show_diff');
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

/**
 * Update todos using NEW Cursor IDE card design
 * @param {Array} todos - Array of todo objects {id, content, status}
 * @param {string} mainTask - Optional main task description
 */
function updateTodos(todos, mainTask) {
    console.log('[TODO] updateTodos called, todos count:', todos ? todos.length : 0);
    if (!todos || !Array.isArray(todos)) {
        console.log('[TODO] Invalid todos data, returning');
        return;
    }

    // If empty todos received, don't clear existing ones
    if (todos.length === 0) {
        console.log('[TODO] Empty todos received');
        if (currentTodoList.length === 0) {
            // Remove any existing todo card
            var existingCard = document.getElementById('todo-card-container');
            if (existingCard) {
                existingCard.remove();
            }
        }
        return;
    }
    
    console.log('[TODO] Processing', todos.length, 'todos');

    // Merge new todos with existing ones (avoid duplicates by id)
    var existingIds = new Set(currentTodoList.map(function(t) { return t.id; }));
    var newTodos = todos.filter(function(t) { return !existingIds.has(t.id); });
    
    // Update status of existing todos if changed
    todos.forEach(function(todo) {
        var existing = currentTodoList.find(function(t) { return t.id === todo.id; });
        if (existing) {
            existing.status = todo.status;
            existing.content = todo.content;
        }
    });
    
    // Add new todos
    currentTodoList = currentTodoList.concat(newTodos);
    
    // Convert to new card format
    var cardTodos = currentTodoList.map(function(todo) {
        return {
            text: todo.content,
            status: (todo.status === 'COMPLETE' || todo.status === 'CANCELLED') ? 'completed' : 'active'
        };
    });
    
    // Check if todo card already exists
    var existingCard = document.getElementById('todo-card-container');
    if (existingCard) {
        // Update existing card
        existingCard.remove();
    }
    
    // Create new todo card
    var card = window.createTodoCard(cardTodos);
    card.id = 'todo-card-container';
    
    // Append or prepend to chat (todos should appear near the top)
    var chatMessages = document.getElementById('chatMessages');
    if (chatMessages) {
        // Insert after empty state but before other messages
        var emptyState = document.getElementById('empty-state');
        if (emptyState && emptyState.nextSibling) {
            chatMessages.insertBefore(card, emptyState.nextSibling);
        } else {
            chatMessages.insertBefore(card, chatMessages.firstChild);
        }
    }
    
    console.log('[TODO] Card rendered with', cardTodos.length, 'items');
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
    console.log('[JS] startStreaming called');
    var container = document.getElementById('chatMessages');
    if (!container) {
        console.error('[JS] chatMessages container not found');
        return;
    }
    
    // Remove thinking indicator
    removeThinkingIndicator();
    
    // Reset activity section for new response
    currentActivitySection = null;
    fileCount = 0;
    
    // NOTE: We no longer clear todos here - todos persist until explicitly completed
    // The AI will send new todos via updateTodos() if needed, which will merge with existing
    
    // Create new assistant message bubble
    if (!currentAssistantMessage) {
        console.log('[JS] Creating new assistant message bubble');
        currentAssistantMessage = document.createElement('div');
        currentAssistantMessage.className = 'message-bubble assistant';
        var content = document.createElement('div');
        content.className = 'message-content';
        currentAssistantMessage.appendChild(content);
        container.appendChild(currentAssistantMessage);
        currentContent = "";
        
        // Remove empty state if present
        var emptyState = document.getElementById('empty-state');
        if (emptyState) emptyState.remove();
    }
    
    smartScroll(container);
    console.log('[JS] startStreaming completed');
}

function onChunk(chunk) {
    if (chunk === undefined || chunk === null) {
        console.warn('[JS] onChunk received undefined/null chunk');
        return;
    }
    chunk = String(chunk);
    console.log('[JS] onChunk received:', chunk.substring(0, 50));
    var container = document.getElementById('chatMessages');
    if (!container) {
        console.error('[JS] chatMessages container not found in onChunk');
        return;
    }

    // -- Set thinking start time on first real content chunk --------------
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
    var explorationMatch = chunk.match(/^(READ|WRITE|RUN|SEARCH|INFO)\s*?([^\n]+)?/i);
    if (explorationMatch) {
        addExplorationItem(explorationMatch[1], (explorationMatch[2] || "" ).trim());
        return;
    }

    // Check for tool result lines
    var toolResultMatch = chunk.match(/^(\s*)(OK|DONE|ERROR|WARN|INFO|RESULT|OUTPUT)\s*(.+)$/i);
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

    // -- Task Summary: buffer for final card, suppress from stream --------
    if (chunk.includes('<task_summary>')) _inTaskSummary = true;
    if (_inTaskSummary) {
        _taskSummaryBuffer += chunk;
        if (chunk.includes('</task_summary>')) _inTaskSummary = false;
        return;
    }

    // -- Terminal output streaming: route to terminal card (BATCHED) -------
    if (chunk.includes('<terminal_output>')) {
        var termMatch = chunk.match(/<terminal_output>(.*?)<\/terminal_output>/);
        if (termMatch) {
            // Batch terminal output updates to reduce DOM manipulations
            if (!_terminalBatchBuffer) _terminalBatchBuffer = '';
            _terminalBatchBuffer += termMatch[1] + '\n';
            
            // Flush every 10 lines or 100ms
            if (!_terminalFlushTimeout) {
                _terminalFlushTimeout = setTimeout(function() {
                    if (_terminalBatchBuffer) {
                        _updateCurrentTerminalCard(_terminalBatchBuffer);
                        _terminalBatchBuffer = '';
                    }
                    _terminalFlushTimeout = null;
                }, 100);
            }
        }
        return;  // Don't add terminal output to AI text bubble
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

    // Accumulate raw content (INCLUDING custom tags - stripped at render time)
    currentContent += chunk;

    // Throttled Rendering (200ms debounce - increased to reduce UI freezing during terminal streaming)
    if (!renderPending) {
        renderPending = true;
        window._streamRenderTimeout = setTimeout(function() {
            renderPending = false;
            updateStreamingUI();
        }, 200);
    }
}

function updateStreamingUI() {
    var container = document.getElementById('chatMessages');
    if (!currentAssistantMessage || !container) return;

    var contentDiv = currentAssistantMessage.querySelector('.message-content');
    if (!contentDiv) return;

    try {
        // -- 1. Strip ALL custom tags before markdown render -----------------
        var cleanText = currentContent
            .replace(/<file_edited>[\s\S]*?<\/file_edited>/g, '')
            .replace(/<exploration>[\s\S]*?<\/exploration>/g, '')
            .replace(/<task_summary>[\s\S]*?<\/task_summary>/g, '')
            .replace(/<tasklist>[\s\S]*?<\/tasklist>/g, '')
            .replace(/<plan>[\s\S]*?<\/plan>/g, '')
            .replace(/<permission>[\s\S]*?<\/permission>/g, '')
            .replace(/[\u2299\u229a\u25ce\u29bf\u2609]Thought\s*[\u00B7\u00b7\.\xB7]\s*\d+s\s*/g, '') // strip DeepSeek ⊙Thought · Xs
            .trim();

        // -- 2. Parse markdown --------------------------------------------
        var html = '';
        try {
            if (typeof marked !== 'undefined' && marked.parse) {
                html = marked.parse(cleanText) || '';
            } else {
                html = formatMarkdownFallback(cleanText);
            }
        } catch (parseError) {
            console.warn('[MARKDOWN] Parse error, using fallback:', parseError.message);
            html = formatMarkdownFallback(cleanText);
        }

        // Ensure html is never undefined or null
        if (!html) html = cleanText || '';

        // Highlight file creation mentions
        html = highlightFileCreations(html);
        contentDiv.innerHTML = html;

        // -- 3. Syntax highlight (skip already-highlighted blocks) ----------
        if (window.hljs) {
            contentDiv.querySelectorAll('pre code').forEach(function(block) {
                if (!block.dataset.highlighted) {
                    // Get the language from data-lang attribute or class
                    var pre = block.parentElement;
                    var dataLang = pre ? pre.getAttribute('data-lang') : '';
                    var classLang = '';
                    
                    // Extract language from class (hljs language-xxx)
                    var classMatch = block.className.match(/language-(\w+)/);
                    if (classMatch) {
                        classLang = classMatch[1];
                    }
                    
                    // Use data-lang priority, then class, then auto-detect
                    var lang = dataLang || classLang || 'plaintext';
                    
                    // Normalize language name
                    var normalizedLang = window.getNormalizedLanguage ? window.getNormalizedLanguage(lang) : lang;
                    
                    // Get raw code
                    var code = block.textContent || block.innerText || '';
                    
                    try {
                        var highlighted;
                        
                        // Use improved highlighting with embedded language support
                        if (window.highlightCodeWithEmbedded) {
                            highlighted = window.highlightCodeWithEmbedded(code, lang);
                        } else if (hljs.getLanguage(normalizedLang)) {
                            highlighted = hljs.highlight(code, { language: normalizedLang }).value;
                        } else {
                            highlighted = hljs.highlightAuto(code).value;
                        }
                        
                        // Only update if we got highlighted content
                        if (highlighted && highlighted !== code) {
                            block.innerHTML = highlighted;
                        }
                    } catch (e) {
                        console.warn('[SYNTAX] Highlight error for ' + lang + ':', e.message);
                    }
                    
                    block.dataset.highlighted = '1';
                }
            });
        }

        // -- 4. Inject code block headers on new blocks -----------------
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
    
    // First, normalize line endings (Windows \r\n -> \n)
    text = text.replace(/\r\n/g, '\n').replace(/\r/g, '\n');
    
    // Process line by line for better control
    var lines = text.split('\n');
    var result = [];
    var inList = false;
    
    for (var i = 0; i < lines.length; i++) {
        var line = lines[i];
        var trimmed = line.trim();
        
        // Horizontal rule
        if (trimmed.match(/^(-{3,}|\*{3,}|_{3,})$/)) {
            if (inList) {
                result.push('</ul>');
                inList = false;
            }
            result.push('<hr>');
            continue;
        }
        
        // Headers
        if (trimmed.match(/^#{1,6}\s/)) {
            if (inList) {
                result.push('</ul>');
                inList = false;
            }
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
        
        // Blockquotes
        if (trimmed.startsWith('>')) {
            if (inList) {
                result.push('</ul>');
                inList = false;
            }
            var quoteContent = trimmed.substring(1).trim();
            result.push('<blockquote>' + processInlineMarkdown(quoteContent) + '</blockquote>');
            continue;
        }
        
        // Regular paragraph (including empty lines for spacing)
        if (trimmed || (i > 0 && lines[i-1].trim())) {
            if (trimmed) {
                result.push('<p>' + processInlineMarkdown(line) + '</p>');
            } else if (result.length > 0 && result[result.length - 1] !== '<br>') {
                // Preserve paragraph breaks
                result.push('<br>');
            }
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

// Wrap fec-cards-container in a collapsed summary group on task completion
function collapseFecContainer() {
    if (!currentAssistantMessage) return;
    var containers = currentAssistantMessage.querySelectorAll('.fec-cards-container');
    containers.forEach(function(container) {
        // Skip already-wrapped containers
        if (container.parentElement && container.parentElement.classList.contains('fec-group')) return;

        var cards = container.querySelectorAll('.fec');
        if (cards.length === 0) return;

        // --- Force-complete ALL pending cards (stop spinner → show OK) ---
        cards.forEach(function(card) {
            if (card.dataset.status !== 'applied') {
                card.classList.remove('fec-pending');
                card.classList.add('fec-applied');
                card.dataset.status = 'applied';
                var rightEl = card.querySelector('.fec-right');
                if (rightEl) rightEl.innerHTML = '<span class="fec-status-text fec-status-applied">OK</span>';
                var labelEl = card.querySelector('.fec-action-label');
                if (labelEl) labelEl.style.opacity = '0.4';
            }
        });

        // Count by type for summary label
        var reads = 0, edits = 0, creates = 0, writes = 0;
        cards.forEach(function(c) {
            var action = (c.querySelector('.fec-action-label') || {}).textContent || '';
            if (action === 'Reading')  reads++;
            else if (action === 'Editing')  edits++;
            else if (action === 'Creating') creates++;
            else writes++;
        });
        var parts = [];
        if (reads)   parts.push(reads   + (reads   === 1 ? ' file read'    : ' files read'));
        if (edits)   parts.push(edits   + (edits   === 1 ? ' file edited'   : ' files edited'));
        if (creates) parts.push(creates + (creates === 1 ? ' file created'  : ' files created'));
        if (writes)  parts.push(writes  + (writes  === 1 ? ' file written'  : ' files written'));
        var summary = parts.join(' · ') || (cards.length + ' files');

        // Build wrapper
        var group = document.createElement('div');
        group.className = 'fec-group fec-group-collapsed';

        // Summary header row
        var groupHeader = document.createElement('div');
        groupHeader.className = 'fec-group-header';
        groupHeader.innerHTML =
            '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="opacity:0.5;flex-shrink:0;"><path d="M13 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z"/><polyline points="13 2 13 9 20 9"/></svg>' +
            '<span class="fec-group-label">' + escapeHtml(summary) + '</span>' +
            '<svg class="fec-group-chevron" width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="margin-left:auto;opacity:0.4;transform:rotate(-90deg);transition:transform 0.2s;"><polyline points="6 9 12 15 18 9"></polyline></svg>';

        groupHeader.style.cursor = 'pointer';
        groupHeader.onclick = function() {
            var isCollapsed = group.classList.toggle('fec-group-collapsed');
            var chev = groupHeader.querySelector('.fec-group-chevron');
            if (chev) chev.style.transform = isCollapsed ? 'rotate(-90deg)' : 'rotate(0deg)';
        };

        // Wrap container in group
        container.parentElement.insertBefore(group, container);
        group.appendChild(groupHeader);
        group.appendChild(container);
    });
}

function onComplete() {
    // If the user already clicked Stop, Python's late-firing onComplete is a no-op
    if (_stopRequested) {
        _stopRequested = false;
        console.log('[CHAT] onComplete: suppressed (stop was requested)');
        return;
    }

    removeThinkingIndicator();
    hideThinking();
    collapseActivitySection();  // Collapse (not remove) the Working section to show summary
    collapseFecContainer();     // Collapse file read/write/create cards into summary

    // Clear any pending debounced render before final render
    if (window._streamRenderTimeout) {
        clearTimeout(window._streamRenderTimeout);
        window._streamRenderTimeout = null;
        renderPending = false;
    }

    if (currentAssistantMessage) {
        // -- Strip all custom tags for display -----------------------------
        var displayText = currentContent
            .replace(/<task_summary>[\s\S]*?<\/task_summary>/g, '')
            .replace(/<file_edited>[\s\S]*?<\/file_edited>/g, '')
            .replace(/<exploration>[\s\S]*?<\/exploration>/g, '')
            .replace(/<tasklist>[\s\S]*?<\/tasklist>/g, '')
            .replace(/<plan>[\s\S]*?<\/plan>/g, '')
            .replace(/<permission>[\s\S]*?<\/permission>/g, '')
            .replace(/[\u2299⊙]Thought\s*[\u00B7·\.\s]\s*\d+s\s*/g, '') // strip DeepSeek ⊙Thought · Xs
            .trim();

        console.log('[CHAT] onComplete: displayText length:', displayText ? displayText.length : 0);
        console.log('[CHAT] onComplete: currentAssistantMessage exists:', !!currentAssistantMessage);

        // -- Save to history (only if content is valid) ---------------------
        var chat = chats.find(function(c) { return c.id == currentChatId; });
        if (chat && displayText && displayText.trim() !== '' && displayText !== 'undefined') {
            chat.messages.push({ text: displayText, sender: 'assistant', role: 'assistant' });
            saveChats();
        }

        // -- Final markdown render ---------------------------------------
        var contentDiv = currentAssistantMessage.querySelector('.message-content');
        console.log('[CHAT] onComplete: contentDiv found:', !!contentDiv);
        
        if (contentDiv) {
            var finalHtml = '';
            try {
                finalHtml = (typeof marked !== 'undefined' && marked.parse)
                    ? (marked.parse(displayText) || '')
                    : formatMarkdownFallback(displayText);
            } catch (e) {
                finalHtml = formatMarkdownFallback(displayText);
            }
            
            // CRITICAL FIX: Ensure contentDiv is visible and has content
            contentDiv.innerHTML = finalHtml || displayText || '';
            // Hide any ⊙Thought · Xs patterns that slipped through
            contentDiv.innerHTML = contentDiv.innerHTML.replace(
                /([\u2299\u229a\u25ce\u29bf⊙⊚◎⦿]Thought\s*[\u00B7\u00b7\.\xB7]\s*\d+s)/g,
                '<span class="thought-timer">$1</span>'
            );
            contentDiv.style.display = 'block';  // Force visibility
            contentDiv.style.visibility = 'visible';
            
            console.log('[CHAT] onComplete: contentDiv.innerHTML set, length:', contentDiv.innerHTML.length);

            // -- Code block headers + syntax highlight -------------------
            contentDiv.querySelectorAll('pre code').forEach(function(block) {
                if (window.hljs) hljs.highlightElement(block);
                injectCodeBlockHeader(block);
            });
        } else {
            console.error('[CHAT] onComplete: contentDiv NOT FOUND! Message structure may be broken.');
        }

        // -- File edit cards ? KEY FIX --------------------------------
        // Render cards AFTER ensuring content is visible
        renderCustomTagsInto(currentAssistantMessage, currentContent);

        // -- Thought duration badge ----------------------------------
        var secs = getThoughtSeconds();
        if (secs >= 1) {
            currentAssistantMessage.appendChild(buildThoughtBadge(secs));
        }
        _thinkingStartTime = null;

        // -- Task summary card ---------------------------------------
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
    } else {
        console.warn('[CHAT] onComplete: currentAssistantMessage is null!');
    }

    // -- Show task completion summary ---------------------------------
    showTaskCompletionSummary();

    // -- Reset state ------------------------------------------------
    currentAssistantMessage = null;
    currentContent          = '';
    _taskSummaryBuffer      = '';
    _inTaskSummary          = false;

    var sendBtn = document.getElementById('sendBtn');
    var stopBtn = document.getElementById('stopBtn');
    if (sendBtn) sendBtn.style.display = 'flex';
    if (stopBtn) stopBtn.style.display = 'none';

    // -- Trigger queue processing ------------------------------------
    _onGenerationComplete();
}



function _startRateLimitRetry(seconds) {
    if (!_lastUserMessage || _isGenerating) return;
    if (_rateLimitRetryTimer) {
        clearInterval(_rateLimitRetryTimer);
        _rateLimitRetryTimer = null;
    }
    _rateLimitRetryRemaining = Math.max(1, seconds || 10);

    // Show waiting UI
    showThinkingIndicator();
    updateThinkingText('Rate limited. Retrying in ' + _rateLimitRetryRemaining + 's');
    var statusEl = document.getElementById('thinking-status');
    if (statusEl) statusEl.textContent = 'Waiting for provider rate limit...';

    _rateLimitRetryTimer = setInterval(function() {
        _rateLimitRetryRemaining -= 1;
        if (_rateLimitRetryRemaining <= 0) {
            clearInterval(_rateLimitRetryTimer);
            _rateLimitRetryTimer = null;
            // Retry without duplicating the user bubble
            _isGenerating = true;
            var sendBtn = document.getElementById('sendBtn');
            var stopBtn = document.getElementById('stopBtn');
            if (sendBtn) sendBtn.style.display = 'none';
            if (stopBtn) stopBtn.style.display = 'flex';
            showThinkingIndicator();
            if (_lastUserHasImages && _lastUserImageData) {
                bridge.on_message_with_images(_lastUserMessage, _lastUserImageData);
            } else {
                bridge.on_message_submitted(_lastUserMessage);
            }
            return;
        }
        updateThinkingText('Rate limited. Retrying in ' + _rateLimitRetryRemaining + 's');
    }, 1000);
}

function onError(errorMessage) {
    console.error('[CHAT] onError:', errorMessage);
    removeThinkingIndicator();
    hideThinking();
    clearActivitySection();

    // Show error in chat
    try {
        appendMessage(errorMessage || 'An error occurred.', 'system', true);
    } catch (e) {}

    // Reset UI state
    var sendBtn = document.getElementById('sendBtn');
    var stopBtn = document.getElementById('stopBtn');
    if (sendBtn) sendBtn.style.display = 'flex';
    if (stopBtn) stopBtn.style.display = 'none';

    _isGenerating = false;

    // Auto-retry for rate limits with countdown
    if (errorMessage && /rate limit|429/i.test(errorMessage)) {
        var m = errorMessage.match(/wait\s+(\d+)\s*seconds/i);
        var seconds = m ? parseInt(m[1], 10) : 15;
        _startRateLimitRetry(seconds);
        return;
    }

    _onGenerationComplete();
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
        
        var optBeforeHtml = (marked.parse(textBefore) || '');
        var optAfterHtml = (marked.parse(textAfter) || '');
        contentDiv.innerHTML = optBeforeHtml + renderOptionsBlock(data) + optAfterHtml;
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
            var beforeHtml = (marked.parse(textBefore) || '');
            var afterHtml = (marked.parse(textAfter) || '');
            contentDiv.innerHTML = beforeHtml + renderExplorationBlock(explorationData) + afterHtml;
        } else {
            explorationData = currentContent.substring(startIndex + startTag.length);
            var beforeHtml2 = (marked.parse(textBefore) || '');
            contentDiv.innerHTML = beforeHtml2 + renderExplorationBlock(explorationData, true);
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
        var parsed = (typeof marked !== 'undefined' && marked.parse)
            ? (marked.parse(cleanText) || cleanText) : cleanText;
        contentDiv.innerHTML = parsed || cleanText;
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
        var beforeHtml3 = (marked.parse(textBefore) || '');
        var afterHtml3 = (marked.parse(textAfter) || '');
        contentDiv.innerHTML = beforeHtml3 + renderTaskSummary(summaryData) + afterHtml3;
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
            var diffBeforeHtml = (marked.parse(textBefore) || '');
            var diffAfterHtml = (marked.parse(textAfter) || '');
            contentDiv.innerHTML = diffBeforeHtml + renderDiffBlock(diffData) + diffAfterHtml;
        } else {
            diffData = currentContent.substring(startIndex + startTag.length);
            var diffBeforeHtml2 = (marked.parse(textBefore) || '');
            contentDiv.innerHTML = diffBeforeHtml2 + renderDiffBlock(diffData, true);
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
    if (isStreaming) return '<div class="file-edit-inline"><span class="pending">? Editing...</span></div>';
    
    var lines = data ? data.trim().split('\n') : [''];
    var filePath = lines[0] || (data ? data.trim() : '');
    var fileName = filePath ? filePath.split('/').pop().split('\\').pop() : 'unknown';
    
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
          '<button class="fec-btn fec-diff" data-path="' + escapeHtml(filePath) + '" onclick="event.stopPropagation(); requestFecDiff(this)" title="View diff">Diff</button>' +
          '<button class="fec-btn fec-accept" onclick="acceptFileEdit(\'' + escapedPath + '\', this)" title="Accept changes">?</button>' +
          '<button class="fec-btn fec-reject" onclick="rejectFileEdit(\'' + escapedPath + '\', this)" title="Reject changes">?</button>' +
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
        html += '<div class="task-summary-header">DONE ' + escapeHtml(title) + '</div>';
        
        // Removed section
        if (removed.length > 0) {
            html += '<div class="task-summary-section">';
            html += '<div class="task-summary-label">Removed:</div>';
            html += '<ul class="task-summary-list removed">';
            removed.forEach(function(item) {
                html += '<li><span class="item-icon">DEL</span>' + escapeHtml(item) + '</li>';
            });
            html += '</ul></div>';
        }
        
        // Kept section
        if (kept.length > 0) {
            html += '<div class="task-summary-section">';
            html += '<div class="task-summary-label">Kept:</div>';
            html += '<ul class="task-summary-list kept">';
            kept.forEach(function(item) {
                html += '<li><span class="item-icon">INFO</span>' + escapeHtml(item) + '</li>';
            });
            html += '</ul></div>';
        }
        
        // Files section
        if (files.length > 0) {
            html += '<div class="task-summary-section">';
            html += '<div class="task-summary-label">Files:</div>';
            html += '<ul class="task-summary-list files">';
            files.forEach(function(item) {
                var icon = item.action === 'created' ? 'NEW' : item.action === 'deleted' ? 'DEL' : 'EDIT';
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
        return '<div class="task-summary-card"><div class="task-summary-header">DONE Task Complete</div></div>';
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

// --- Terminal Output Display in Chat (NEW Cursor IDE Card Design) ---
function showTerminalOutputInChat(command, output, isRunning) {
    console.log('[TERMINAL] Showing output in card:', command);
    
    // Create terminal card using new card system
    var card = window.createTerminalCard(command, output || '');
    
    // If running, add a pulse animation indicator
    if (isRunning) {
        var header = card.querySelector('.card-header');
        if (header) {
            var statusSpan = document.createElement('span');
            statusSpan.className = 'ml-auto text-[10px] opacity-40 pulse-timer';
            statusSpan.textContent = 'Running...';
            header.appendChild(statusSpan);
        }
    }
    
    // Append card to chat
    window.appendCardToChat(card);
}

/**
 * Mark terminal output as complete (NEW design)
 * Called from Python when terminal command finishes
 */
function completeTerminalOutput() {
    console.log('[TERMINAL] Output complete');
    
    // Find the last terminal card and update it
    var terminalCards = document.querySelectorAll('.card-container');
    terminalCards.forEach(function(card) {
        var header = card.querySelector('.card-header');
        if (header && header.textContent.includes('Run in terminal')) {
            // Remove any "Running..." indicators
            var runningIndicator = card.querySelector('.pulse-timer');
            if (runningIndicator) {
                runningIndicator.remove();
            }
            
            // Update header to show completion
            var viewLink = header.querySelector('.text-\\[10px\\]');
            if (viewLink) {
                viewLink.textContent = 'Completed ✓';
                viewLink.classList.remove('opacity-40');
                viewLink.style.color = 'var(--green-bright)';
            }
        }
    });
}

// --- File Reference Display ---
function showFileReference(filePath, lineNumber, content) {
    var container = document.getElementById('chatMessages');
    if (!container) return;
    
    var fileName = filePath ? filePath.split('/').pop().split('\\').pop() : 'unknown';
    var escapedPath = filePath ? filePath.replace(/\\/g, '\\\\') : '';
    
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

// Handle image attachment - convert to base64 and add to message
var _attachedImages = [];

function handleImageAttachment(file) {
    if (!file) return;
    
    // Check file size (max 10MB)
    var maxSize = 10 * 1024 * 1024; // 10MB
    if (file.size > maxSize) {
        alert('Image too large. Maximum size is 10MB.');
        return;
    }
    
    var reader = new FileReader();
    reader.onload = function(e) {
        var base64 = e.target.result;
        
        // Store the image data
        _attachedImages.push({
            name: file.name,
            type: file.type,
            data: base64
        });
        
        // Add image preview to input area or show notification
        showImageAttachmentPreview(file.name, base64);
        
        console.log('[Cortex] Image attached:', file.name, '(' + Math.round(file.size / 1024) + 'KB)');
    };
    reader.onerror = function() {
        alert('Failed to read image file.');
    };
    reader.readAsDataURL(file);
}

function showImageAttachmentPreview(filename, base64) {
    // Create a preview badge near the input
    var inputArea = document.getElementById('input-area');
    if (!inputArea) return;
    
    // Remove existing preview if any
    var existingPreview = document.getElementById('image-attachment-preview');
    if (existingPreview) existingPreview.remove();
    
    var preview = document.createElement('div');
    preview.id = 'image-attachment-preview';
    preview.className = 'image-attachment-preview';
    preview.innerHTML = 
        '<img src="' + base64 + '" alt="' + escapeHtml(filename) + '" />' +
        '<button class="remove-preview" onclick="removeImageAttachment()">x</button>' +
        '<span class="preview-filename">' + escapeHtml(filename) + '</span>';
    
    // Insert after input container
    var inputContainer = document.getElementById('input-container');
    if (inputContainer && inputContainer.parentNode) {
        inputContainer.parentNode.insertBefore(preview, inputContainer.nextSibling);
    }
}

function removeImageAttachment() {
    if (_attachedImages.length > 0) {
        _attachedImages.pop();
    }
    var preview = document.getElementById('image-attachment-preview');
    if (preview) preview.remove();
}

window.removeImageAttachment = removeImageAttachment;

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
            e.preventDefault();
            
            // Close other dropdowns first
            document.querySelectorAll('.dropdown-menu').forEach(function(m) {
                if (m !== menu) {
                    m.classList.remove('show');
                    m.style.display = 'none';
                }
            });
            
            // Toggle show class
            var isShowing = menu.classList.contains('show');
            
            // Hide menu if currently showing
            if (isShowing) {
                menu.classList.remove('show');
                menu.style.display = 'none';
                return;
            }
            
            // Show menu if currently hidden - calculate position
            var rect = trigger.getBoundingClientRect();
            var menuWidth = 220; // min-width from CSS
            var menuHeight = 300;
            var margin = 10; // minimum margin from viewport edges
            
            // ALWAYS position ABOVE the trigger (UPWARD)
            var bottomPosition = window.innerHeight - rect.top + 8;
            
            // Align LEFT edge of dropdown with LEFT edge of button
            var left = rect.left;
            
            // Calculate boundaries to prevent overflow
            var minLeft = margin;
            var maxLeft = window.innerWidth - menuWidth - margin;
            
            // Clamp left position within viewport bounds
            var clampedLeft = Math.max(minLeft, Math.min(left, maxLeft));
            
            // Set fixed position ABOVE (always upward)
            menu.style.position = 'fixed';
            menu.style.bottom = bottomPosition + 'px';
            menu.style.top = 'auto';
            menu.classList.add('position-top');
            
            menu.style.left = clampedLeft + 'px';
            menu.style.transform = 'none'; // No centering transform needed
            menu.style.zIndex = '100000';
            menu.style.display = 'block';
            menu.classList.add('show');
        };

        // Use event delegation on menu instead of individual item listeners
        menu.addEventListener('click', function(e) {
            e.stopPropagation();
            var item = e.target.closest('.dropdown-item');
            if (!item) return;
            
            var val = item.dataset.value;
            items.forEach(function(i) { i.classList.remove('active'); });
            item.classList.add('active');
            
            if (modeText) modeText.innerText = val;
            
            // Update textarea placeholder based on mode
            var textarea = document.getElementById('user-input');
            if (textarea) {
                switch(val) {
                    case 'Agent':
                        textarea.placeholder = 'Plan and build...';
                        break;
                    case 'Ask':
                        textarea.placeholder = 'Ask a question...';
                        break;
                    case 'Plan':
                        textarea.placeholder = 'Create a plan...';
                        break;
                    default:
                        textarea.placeholder = 'Type a message...';
                }
            }
            
            // Update trigger icon (SVG swap)
            var svgWrap = trigger.querySelector('svg.mode-icon');
            if (svgWrap) {
                if (val === 'Agent') svgWrap.innerHTML = '<path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm0 4c1.93 0 3.5 1.57 3.5 3.5S13.93 13 12 13s-3.5-1.57-3.5-3.5S10.07 6 12 6zm0 14c-2.03 0-4.43-.82-6.14-2.88C7.55 15.8 9.68 15 12 15s4.45.8 6.14 2.12C16.43 19.18 14.03 20 12 20z"/>';
                else if (val === 'Ask') svgWrap.innerHTML = '<path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>';
                else if (val === 'Plan') svgWrap.innerHTML = '<polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"/>';
            }

            if (bridge) bridge.on_mode_changed(val);
            
            // IMMEDIATELY hide dropdown
            menu.classList.remove('show');
            menu.style.display = 'none';
        });
    }

    // Model Selector Logic
    var modelDropdown = document.getElementById('model-selector');
    if (modelDropdown) {
        var modelTrigger = modelDropdown.querySelector('.dropdown-trigger');
        var modelMenu = modelDropdown.querySelector('.dropdown-menu');
        var modelItems = modelDropdown.querySelectorAll('.dropdown-item');
        var modelText = document.getElementById('selected-model');
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
            // ALWAYS position ABOVE the trigger (UPWARD)
            var rect = modelTrigger.getBoundingClientRect();
            var menuWidth = 280; // min-width from CSS
            var menuHeight = 350;
            var margin = 10; // minimum margin from viewport edges
            
            // Position ABOVE the trigger (always upward)
            var bottomPosition = window.innerHeight - rect.top + 8;
            
            // Align LEFT edge of dropdown with LEFT edge of button
            var left = rect.left;
            
            // Calculate boundaries to prevent overflow
            var minLeft = margin;
            var maxLeft = window.innerWidth - menuWidth - margin;
            
            // Clamp left position within viewport bounds
            var clampedLeft = Math.max(minLeft, Math.min(left, maxLeft));
            
            // Set fixed position ABOVE (always upward)
            modelMenu.style.position = 'fixed';
            modelMenu.style.bottom = bottomPosition + 'px';
            modelMenu.style.top = 'auto';
            modelMenu.classList.add('position-top');
            
            modelMenu.style.left = clampedLeft + 'px';
            modelMenu.style.transform = 'none'; // No centering transform
            modelMenu.style.zIndex = '100000';
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
                    var fullText = this.querySelector('.item-text span').textContent;
                    // Remove the "Active" tag text if present
                    var modelName = fullText.replace(/\s*Active\s*$/, '').trim();
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
    window.showToolSummary = showToolSummary;
    window.showThinking = showThinking;
    window.hideThinking = hideThinking;
    window.onError = onError;
    window.updateActivityHeader = updateActivityHeader;
    
    // TODO Functions
    window.updateTodos = updateTodos;
    window.toggleTodoSection = toggleTodoSection;
    window.clearTodos = clearTodos;
    
    // Chat Title Update Function (Phase 4)
    window.updateChatTitle = function(conversationId, title) {
        // Update the chat title in the chat list/history
        var chat = chats.find(function(c) { return c.id === conversationId; });
        if (chat) {
            chat.title = title;
            // Update the history list UI
            renderHistoryList();
            // Also update the page title
            document.title = title ? 'Cortex - ' + title : 'Cortex AI Chat';
            console.log('[CHAT] Title updated:', title);
        }
    };
    
    window.setTheme = function (isDark) {
        // Support both boolean (from Python) and string (from localStorage)
        var isDarkMode;
        if (typeof isDark === 'boolean') {
            isDarkMode = isDark;
        } else if (typeof isDark === 'string') {
            isDarkMode = (isDark !== 'light');
        } else {
            isDarkMode = true; // Default to dark
        }
        
        console.log('[THEME] Setting theme to:', isDarkMode ? 'dark' : 'light', '(input was:', isDark, ')');
        
        // Apply theme using classList (matches CSS .light-mode selector)
        if (!isDarkMode) {
            // Light mode
            document.body.classList.add('light-mode');
            document.body.classList.remove('dark');
            localStorage.setItem('cortex_theme', 'light');
        } else {
            // Dark mode (default)
            document.body.classList.remove('light-mode');
            document.body.classList.add('dark');
            localStorage.setItem('cortex_theme', 'dark');
        }
        
        console.log('[THEME] Theme applied - body classes:', document.body.className);
        return 'success';
    };
    window.focusInput = function () {
        var input = document.getElementById('chatInput');
        if (input) input.focus();
    };

    window.openFile = function(filePath) {
        if (bridge) bridge.on_open_file(filePath);
    };

    // Terminal visibility state for performance optimization
    var _terminalVisible = false;
    var _terminalPausedBuffer = '';
    var _terminalMaxPausedBuffer = 32768; // Max size when paused
    
    window.showTerminal = function() {
        var container = document.getElementById('terminal-container');
        if (container && !container.classList.contains('open')) {
            // Make sure container is visible
            container.style.display = 'flex';
            container.classList.add('open');
            _terminalVisible = true;
            
            // Flush any paused buffer
            if (_terminalPausedBuffer && term) {
                term.write(_terminalPausedBuffer);
                _terminalPausedBuffer = '';
            }
            
            setTimeout(function () {
                if (fitAddon) fitAddon.fit();
                if (term) term.focus();
            }, 280);
        }
    };
    
    window.hideTerminal = function() {
        var container = document.getElementById('terminal-container');
        if (container && container.classList.contains('open')) {
            container.classList.remove('open');
            container.style.display = 'none';
            _terminalVisible = false;
        }
    };
    
    window.isTerminalVisible = function() {
        return _terminalVisible;
    };

    window.showDiff = function(filePath) {
        console.log('[Diff] showDiff called with:', filePath);
        console.log('[Diff] window.bridge exists:', !!window.bridge);
        console.log('[Diff] window.bridge.on_show_diff exists:', !!(window.bridge && window.bridge.on_show_diff));
        console.log('[Diff] bridge exists:', !!bridge);
        console.log('[Diff] bridge.on_show_diff exists:', !!(bridge && bridge.on_show_diff));
        if (window.bridge && window.bridge.on_show_diff) {
            window.bridge.on_show_diff(filePath);
            console.log('[Diff] Bridge method called successfully');
        } else if (bridge && bridge.on_show_diff) {
            bridge.on_show_diff(filePath);
            console.log('[Diff] Legacy bridge method called');
        } else {
            console.error('[Diff] Bridge or on_show_diff not available. bridgeReady:', window.bridgeReady);
        }
    };

    window.markFileAccepted = function(filePath) {
        const escapedId = filePath.replace(/[^a-zA-Z0-9]/g, '-');
        const statusEl = document.getElementById('status-' + escapedId);
        if (statusEl) {
            statusEl.innerHTML = '<span class="accepted">? Changes applied automatically</span>';
        }
    };

    // --- New Qoder-like Features ---
    window.showTerminalOutput = function(command, output, isRunning) {
        showTerminalOutputInChat(command, output, isRunning);
    };

    window.completeTerminalOutput = function() {
        completeTerminalOutput();
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
    window.showThinkingIndicator = showThinkingIndicator;
    window.hideThinkingIndicator = hideThinkingIndicator;
    window.addExploration = addExplorationItem;
    window.showDirectoryContents = showDirectoryContents;
    window.updateThinkingText = updateThinkingText;
    window.toggleExploration = toggleExploration;
    
    // Handler for full chat load (lazy loading response from Python bridge)
    window.chatFullLoadHandler = function(id, messagesParsed) {
        console.log('[CHAT] >>> chatFullLoadHandler START for id:', id);
        console.log('[CHAT] id type:', typeof id, 'currentChatId:', currentChatId, 'type:', typeof currentChatId);
        
        var chat = chats.find(function(c) { return c.id == id; });
        if (chat) {
            console.log('[CHAT] Target chat object found. Setting messages (count:', messagesParsed ? messagesParsed.length : 0, ')');
            
            // Clean thinking messages from loaded data
            var cleanedMessages = (messagesParsed || []).filter(function(msg) {
                if (!msg || !(msg.content || msg.text)) return true;
                var text = String(msg.content || msg.text);
                var isThinking = text.includes('Thinking') || 
                                 text.includes('Analyzing your request') ||
                                 text.includes('Cortex is working');
                return !isThinking;
            });
            if (cleanedMessages.length !== (messagesParsed || []).length) {
                console.log('[CHAT] CLEANUP - Removed', (messagesParsed || []).length - cleanedMessages.length, 'thinking messages from SQLite load');
            }
            
            chat.messages = cleanedMessages;
            chat.loaded = true;
            chat.message_count = chat.messages.length;
            chat.truncated = false;
            normalizeMessageRoles(chat.messages);
            
            console.log('[CHAT] Comparison: currentChatId == id is', (currentChatId == id));
            if (currentChatId == id) {
                console.log('[CHAT] MATCH! rendering messages...');
                hideLoadingIndicator();
                clearMessages();
                
                if (chat.messages.length === 0) {
                   console.log('[CHAT] WARNING: No messages found in messagesParsed array.');
                }
                
                chat.messages.forEach(function(msg, index) {
                    try {
                        var msgText = msg.content || msg.text;
                        var msgSender = msg.role || msg.sender;
                        console.log('[CHAT] Message', index, ':', msgSender, 'length:', msgText ? msgText.length : 0);
                        if (msgText && msgText !== 'undefined' && msgText.trim() !== '') {
                            appendMessage(msgText, msgSender || 'user', false);
                            console.log('[CHAT] Message', index, 'appended successfully');
                        } else {
                            console.log('[CHAT] Skipping empty message', index);
                        }
                    } catch (err) {
                        console.error('[CHAT] Error rendering message at index', index, ':', err);
                    }
                });
                renderHistoryList();
                
                // Auto-scroll to bottom to show latest message
                setTimeout(function() {
                    var container = document.getElementById('chat-output') || document.getElementById('chatMessages');
                    if (container) {
                        container.scrollTop = container.scrollHeight;
                        console.log('[CHAT] Auto-scrolled to bottom after loading', chat.messages.length, 'messages');
                    }
                }, 100);
                
                console.log('[CHAT] chatFullLoadHandler: Render complete.');
            } else {
                console.warn('[CHAT] chatFullLoadHandler: currentChatId mismatch. current:', currentChatId, 'loaded:', id);
            }
        } else {
            console.error('[CHAT] chatFullLoadHandler: chat object missing for id:', id);
            console.log('[CHAT] Known chats IDs:', chats.map(function(c){ return c.id; }).join(', '));
        }
        console.log('[CHAT] <<< chatFullLoadHandler END');
    };
    
    // --- Project Directory Awareness ---
    // New method that receives chat data directly from Python
    window.setProjectInfoWithChats = function(name, path, chatsJson) {
        console.log('[CHAT] setProjectInfoWithChats called:', name, path);
        var chatsInfo = 'null';
        if (Array.isArray(chatsJson)) {
            chatsInfo = chatsJson.length + ' items';
        } else if (typeof chatsJson === 'string') {
            chatsInfo = chatsJson.length + ' chars';
        } else if (chatsJson && typeof chatsJson === 'object') {
            chatsInfo = 'object';
        }
        console.log('[CHAT] Received chat data from Python:', chatsInfo);
        
        var indicator = document.getElementById('project-indicator');
        var projectName = document.getElementById('project-name');
        
        if (!indicator || !projectName) {
            console.log('[CHAT] DOM not ready, retrying in 300ms');
            setTimeout(function() {
                window.setProjectInfoWithChats(name, path, chatsJson);
            }, 300);
            return;
        }
        
        // Clear TODOs and Changed Files when switching projects
        clearTodosAndChangedFiles();
        
        if (name && name.trim()) {
            projectName.textContent = name;
            indicator.title = path || name;
            indicator.style.display = 'inline-flex';
            
            // Always load project-specific chat history when path is provided
            if (path) {
                // Set the path first before loading
                currentProjectPath = path;
                console.log('[CHAT] ? currentProjectPath SET to:', currentProjectPath);
                
                // Parse the chats METADATA only (lazy loading - no messages yet)
                var savedChats = []; // This variable is re-declared here, but the one above is for the bridge-ready case.
                                     // The original intent of this line was to initialize for the chatsJson parsing.
                                     // We'll keep it for the chatsJson path.
                try {
                    if (Array.isArray(chatsJson)) {
                        savedChats = chatsJson;
                    } else if (typeof chatsJson === 'string') {
                        if (chatsJson && chatsJson !== "[]") {
                            savedChats = JSON.parse(chatsJson);
                        }
                    } else if (chatsJson && typeof chatsJson === 'object') {
                        if (typeof chatsJson.length === 'number') {
                            savedChats = chatsJson;
                        }
                    }
                    if (savedChats.length > 0) {
                        console.log('[CHAT] Parsed', savedChats.length, 'chat metadata from Python data');
                        
                        // Initialize chat list with metadata (sidebar shows titles only)
                        chats = savedChats.map(function(chatMeta) {
                            return {
                                id: chatMeta.id,
                                title: chatMeta.title,
                                created_at: chatMeta.created_at,
                                message_count: chatMeta.message_count || 0,
                                messages: [],  // Empty - will load on demand
                                loaded: false  // Flag: not loaded yet
                            };
                        });
                        
                        // Render sidebar immediately with metadata (FAST!)
                        renderHistoryList();
                        console.log('[CHAT] Sidebar rendered with', chats.length, 'chats (metadata only)');
                        
                        // Auto-load most recent chat if available
                        if (chats.length > 0) {
                            loadChat(chats[0].id);
                        }
                    }
                } catch (e) {
                    console.error('[CHAT] Error parsing chats from Python:', e.message);
                }
                
                if (savedChats.length === 0) {
                    console.log('[CHAT] No saved chats found in Python metadata or localStorage');
                    // If we have existing chats (e.g. from localStorage) but Python says 0, 
                    // it means the DB is empty (e.g. after deletion). 
                    // We should respect the DB and clear our local list.
                    if (chats.length > 0 && ((typeof chatsJson === 'string' && chatsJson === "[]") || (Array.isArray(chatsJson) && chatsJson.length === 0))) {
                        console.log('[CHAT] Clearing local cache as DB is empty');
                        chats = [];
                    }
                    
                    if (chats.length === 0) {
                        startNewChat();
                    }
                    renderHistoryList();
                }
            }
        } else {
            indicator.style.display = 'none';
        }
    };

    if (window._pendingProjectInfoWithChats) {
        var pendingInfo = window._pendingProjectInfoWithChats;
        window._pendingProjectInfoWithChats = null;
        window.setProjectInfoWithChats(pendingInfo.name, pendingInfo.path, pendingInfo.chatsJson);
    }

    // ============================================
    // THEME INITIALIZATION
    // ============================================
    // Note: setTheme is defined earlier in the file and supports both boolean and string
    
    // Load saved theme on startup
    (function loadSavedTheme() {
        var savedTheme = localStorage.getItem('cortex_theme');
        if (savedTheme) {
            console.log('[THEME] Loading saved theme:', savedTheme);
            window.setTheme(savedTheme);
        } else {
            // Default to dark mode
            document.body.classList.add('dark');
            console.log('[THEME] Using default dark theme');
        }
    })();

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
        
        // Clear TODOs and Changed Files when switching projects
        clearTodosAndChangedFiles();
        
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
                    console.log('[CHAT] ? currentProjectPath SET to:', currentProjectPath);
                    
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
        if (!section) return;
        // Use DOM state (expanded class) as source of truth
        if (section.classList.contains('expanded')) {
            section.classList.remove('expanded'); // CSS hides cfs-body automatically
            window._cfsCollapsed = true;
        } else {
            section.classList.add('expanded');    // CSS shows cfs-body automatically
            window._cfsCollapsed = false;
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

function clearChangedFiles() {
    _changedFiles = {};
    var list = document.getElementById('cfs-list');
    var section = document.getElementById('changed-files-section');
    if (list) list.innerHTML = '';
    if (section) section.style.display = 'none';
}

function renderChangedFileRow(filePath, added, removed, editType, status) {
    editType = editType || 'M';
    status = status || 'pending';
    
    console.log('[DEBUG] renderChangedFileRow:', filePath, 'status:', status);
    
    var section = document.getElementById('changed-files-section');
    var list    = document.getElementById('cfs-list');
    if (!section || !list) {
        console.log('[DEBUG] Missing section or list');
        return;
    }

    section.style.display = 'flex';

    var fileName    = filePath ? filePath.split('/').pop().split('\\').pop() : 'unknown';
    var esc         = filePath ? filePath.replace(/'/g, "\\'") : '';
    var badgeClass  = { 'M': 'cfs-badge-m', 'C': 'cfs-badge-c', 'D': 'cfs-badge-d' }[editType] || 'cfs-badge-m';
    var addedHtml   = added   > 0 ? '<span class="cfs-stat-added">+' + added   + '</span>' : '';
    var removedHtml = removed > 0 ? '<span class="cfs-stat-removed">-' + removed + '</span>' : '';

    var row = document.createElement('div');
    row.className = 'cfs-row' + (status === 'accepted' ? ' cfs-accepted' : '');
    row.dataset.path = filePath;
    
    // Right side: Accept button (pending) | Accepted label | Rejected label
    var rightContent = '';
    if (status === 'accepted') {
        rightContent = '<span class="cfs-row-applied">Accepted</span>';
    } else if (status === 'rejected') {
        rightContent = '<span class="cfs-row-rejected">Rejected</span>';
    } else {
        // Pending — show Accept button + small Reject icon
        rightContent =
            '<button class="cfs-row-reject-btn" onclick="event.stopPropagation();rejectChangedFile(\'' + esc + '\', this)" title="Reject changes">' +
                '<svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>' +
            '</button>' +
            '<button class="cfs-row-accept-btn" onclick="event.stopPropagation();acceptChangedFile(\'' + esc + '\', this)" title="Accept changes">' +
                'Accept' +
            '</button>';
    }
    
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
            rightContent +
        '</div>';

    list.appendChild(row);
    console.log('[DEBUG] Row appended to list');
}

function addChangedFile(filePath, added, removed, editType) {
    editType = editType || 'M';

    if (_changedFiles[filePath]) {
        var prev = _changedFiles[filePath];
        prev.added   = added;
        prev.removed = removed;
        // If the file was previously accepted/rejected and is being edited again,
        // reset to pending and refresh the row's right-side content
        if (prev.status !== 'pending') {
            prev.status   = 'pending';
            prev.editType = editType;
            // Use getElementById to avoid CSS selector failures on Windows paths
            var rightEl2 = document.getElementById('cfs-row-right-' + _escapeId(filePath));
            if (rightEl2) {
                var esc2 = filePath.replace(/'/g, "\\'");
                rightEl2.innerHTML =
                    '<button class="cfs-row-reject-btn" onclick="event.stopPropagation();rejectChangedFile(\'' + esc2 + '\', this)" title="Reject changes">' +
                        '<svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>' +
                    '</button>' +
                    '<button class="cfs-row-accept-btn" onclick="event.stopPropagation();acceptChangedFile(\'' + esc2 + '\', this)" title="Accept changes">Accept</button>';
                var row2 = rightEl2.closest('.cfs-row');
                if (row2) row2.classList.remove('cfs-accepted', 'cfs-rejected');
            }
        }
        _cfsShowAndExpand();
        _refreshCfsHeader();
        return;
    }

    _changedFiles[filePath] = { added: added, removed: removed, status: 'pending', editType: editType };
    renderChangedFileRow(filePath, added, removed, editType, 'pending');

    // Always show + expand the section whenever a new file is added
    _cfsShowAndExpand();

    _refreshCfsHeader();
}

// Centralised helper: make the Changed Files section visible and expanded
function _cfsShowAndExpand() {
    var section = document.getElementById('changed-files-section');
    if (section) {
        section.style.display = 'flex';
        section.classList.add('expanded'); // CSS rule shows cfs-body automatically
    }
    window._cfsCollapsed = false;
}

function resolveFilePath(filePath) {
    // Handle relative paths by prepending project path
    if (filePath && currentProjectPath) {
        var isRelative = !filePath.match(/^[a-zA-Z]:\\/) && !filePath.startsWith('/');
        if (isRelative) {
            var separator = currentProjectPath.includes('/') ? '/' : '\\';
            return currentProjectPath + separator + filePath;
        }
    }
    return filePath;
}

function acceptChangedFile(filePath, btn) {
    if (!_changedFiles[filePath]) return;
    _changedFiles[filePath].status = 'accepted';

    // Use getElementById with the escaped ID — avoids CSS selector failures
    // caused by Windows backslashes in data-path attribute queries.
    var rightEl = document.getElementById('cfs-row-right-' + _escapeId(filePath));
    if (rightEl) {
        rightEl.innerHTML = '<span class="cfs-row-applied">Accepted</span>';
        var row = rightEl.closest('.cfs-row');
        if (row) { row.classList.add('cfs-accepted'); row.classList.remove('cfs-rejected'); }
    }
    var resolvedPath = resolveFilePath(filePath);
    var safePath = resolvedPath.replace(/\\/g, '/');
    console.log('[DEBUG] Accepting file:', safePath);
    if (window.bridge) bridge.on_accept_file_edit(safePath);
    _refreshCfsHeader();
    markFileAccepted(filePath);
}

function rejectChangedFile(filePath, btn) {
    if (!_changedFiles[filePath]) return;
    _changedFiles[filePath].status = 'rejected';

    // Use getElementById — same reason as acceptChangedFile (backslash-safe).
    var rightEl = document.getElementById('cfs-row-right-' + _escapeId(filePath));
    if (rightEl) {
        rightEl.innerHTML = '<span class="cfs-row-rejected">Rejected</span>';
        var row = rightEl.closest('.cfs-row');
        if (row) { row.classList.add('cfs-rejected'); row.classList.remove('cfs-accepted'); }
    }
    var resolvedPath = resolveFilePath(filePath);
    var safePath = resolvedPath.replace(/\\/g, '/');
    console.log('[DEBUG] Rejecting file:', safePath);
    if (window.bridge) bridge.on_reject_file_edit(safePath);
    _refreshCfsHeader();
    markFileRejected(filePath);
}

function acceptAllChanges(e) {
    if (e) e.stopPropagation();
    Object.keys(_changedFiles).forEach(function(p) {
        if (_changedFiles[p].status === 'pending') {
            acceptChangedFile(p, null); // btn not needed
        }
    });
}

function rejectAllChanges(e) {
    if (e) e.stopPropagation();
    Object.keys(_changedFiles).forEach(function(p) {
        if (_changedFiles[p].status === 'pending') {
            rejectChangedFile(p, null); // btn not needed
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
        // Some files still awaiting decision — show bulk action buttons
        if (bulkEl) bulkEl.style.display = 'flex';
        if (statusEl) {
            // Show a summary alongside the bulk buttons
            if (accepted > 0 || rejected > 0) {
                statusEl.style.display = '';
                statusEl.textContent = 'Partially Accepted';
                statusEl.style.color = 'var(--text-muted, #8b949e)';
            } else {
                statusEl.style.display = 'none';
            }
        }
    } else if (total > 0) {
        // All files have a decision — hide bulk buttons, show final status
        if (bulkEl) bulkEl.style.display = 'none';
        if (statusEl) {
            statusEl.style.display = '';
            if (rejected === 0) {
                statusEl.textContent = 'Accepted';
                statusEl.style.color = 'var(--green-bright, #22c55e)';
            } else if (accepted === 0) {
                statusEl.textContent = 'Rejected';
                statusEl.style.color = 'var(--red, #f87171)';
            } else {
                statusEl.textContent = 'Partially Accepted';
                statusEl.style.color = 'var(--text-muted, #8b949e)';
            }
        }
    }
}

function _escapeId(str) {
    return str.replace(/[^a-zA-Z0-9]/g, '-');
}

// ================================================================
// CURSOR-STYLE FILE EDIT CARD (buildFileEditCard)
// ================================================================
function buildFileEditCard(filePath, added, removed, editType, status, original, modified) {
    editType = editType || 'M';
    status   = status   || 'pending';

    var fileName = filePath ? filePath.split('/').pop().split('\\').pop() : 'unknown';
    var ext      = fileName ? fileName.split('.').pop().toLowerCase() : 'default';
    var esc      = filePath ? filePath.replace(/'/g, "\\'") : '';

    // -- File type badge (colored, matches Cursor/Qoder) ------------------
    var ftBadge = getFileTypeBadge(ext);

    // -- Diff stats ---------------------------------------------
    // For new files (C), always show added count even if 0
    // For modified files (M), show both added and removed
    var addedHtml   = (added > 0 || editType === 'C') ? '<span class="fec-added">+'  + added   + '</span>' : '';
    var removedHtml = removed > 0 ? '<span class="fec-removed">-' + removed + '</span>' : '';

    // -- M/C/D badge ---------------------------------------------
    var mClass = { 'M': 'fec-badge-m', 'C': 'fec-badge-c', 'D': 'fec-badge-d' }[editType] || 'fec-badge-m';

    var isPending  = status === 'pending';
    var isApplied  = status === 'applied';
    var isRejected = status === 'rejected';

    var rightHtml = '';
    if (isPending) {
        // Only show Diff button for MODIFIED files (M), not for CREATED files (C)
        if (editType === 'M') {
            rightHtml =
                '<div class="fec-pending-actions">' +
                    '<button class="fec-btn-diff" data-path="' + escapeHtml(filePath) + '" onclick="event.stopPropagation(); requestFecDiff(this);">Diff</button>' +
                '</div>';
        }
    } else if (isApplied) {
        rightHtml = '<span class="fec-status-applied">Applied</span>';
    } else if (isRejected) {
        rightHtml = '<span class="fec-status-rejected">Rejected</span>';
    }

    var card = document.createElement('div');
    card.className = 'fec fec-' + status;
    card.dataset.path     = filePath;
    card.dataset.status   = status;
    card.dataset.original = original || '';
    card.dataset.modified = modified || '';

    // Click card - no diff overlay, just open file in editor
    card.onclick = function(e) {
        if (e.target.tagName === 'BUTTON') return;
        openFileInEditor(filePath);
    };

    card.innerHTML =
        '<div class="fec-left">' +
            ftBadge +
            '<button class="fec-name" onclick="event.stopPropagation(); openFileInEditor(\'' + esc + '\')" title="' + escapeHtml(filePath) + '">' +
                escapeHtml(fileName) +
            '</button>' +
            addedHtml + removedHtml +
            '<span class="fec-badge ' + mClass + '">' + editType + '</span>' +
        '</div>' +
        '<div class="fec-right">' + rightHtml + '</div>';

    return card;
}

// File type badge - SVG icons
function getFileTypeBadge(ext) {
    var badges = {
        'js':   '<svg viewBox="0 0 32 32" width="16" height="16"><rect width="32" height="32" rx="3" fill="#F7DF1E"/><path d="M20.8 24.3c.5.9 1.2 1.5 2.4 1.5 1 0 1.6-.5 1.6-1.2 0-.8-.7-1.1-1.8-1.6l-.6-.3c-1.8-.8-3-1.7-3-3.7 0-1.9 1.4-3.3 3.6-3.3 1.6 0 2.7.5 3.5 1.9l-1.9 1.2c-.4-.8-.9-1.1-1.6-1.1-.7 0-1.2.5-1.2 1.1 0 .8.5 1.1 1.6 1.5l.6.3c2.1.9 3.3 1.8 3.3 3.9 0 2.2-1.7 3.5-4 3.5-2.2 0-3.7-1.1-4.4-2.5l2-.1z" fill="#222"/><path d="M12.2 24.6c.4.6.7 1.2 1.6 1.2.8 0 1.3-.3 1.3-1.5V16h2.4v8.3c0 2.5-1.5 3.7-3.6 3.7-1.9 0-3-1-3.6-2.2l1.9-1.2z" fill="#222"/></svg>',
        'jsx':  '<svg viewBox="0 0 32 32" width="16" height="16"><circle cx="16" cy="16" r="2.5" fill="#61DAFB"/><ellipse cx="16" cy="16" rx="11" ry="4.2" fill="none" stroke="#61DAFB" stroke-width="1.3"/><ellipse cx="16" cy="16" rx="11" ry="4.2" fill="none" stroke="#61DAFB" stroke-width="1.3" transform="rotate(60 16 16)"/><ellipse cx="16" cy="16" rx="11" ry="4.2" fill="none" stroke="#61DAFB" stroke-width="1.3" transform="rotate(120 16 16)"/></svg>',
        'ts':   '<svg viewBox="0 0 32 32" width="16" height="16"><rect width="32" height="32" rx="3" fill="#3178C6"/><path d="M18 17.4h3.4v.9H19v1.2h2.2v.9H19V23h-1V17.4zM9 17.4h5.8v1H12V23h-1v-4.6H9v-1z" fill="#fff"/><path d="M14.2 19.9c0-1.8 1.2-2.7 2.8-2.7.7 0 1.3.1 1.8.4l-.3.9c-.4-.2-.9-.3-1.4-.3-1 0-1.7.6-1.7 1.7 0 1.1.7 1.8 1.8 1.8.3 0 .6 0 .8-.1v-1.2H17v-.9h2v2.7c-.5.3-1.2.5-2 .5-1.8 0-2.8-1-2.8-2.8z" fill="#fff"/></svg>',
        'tsx':  '<svg viewBox="0 0 32 32" width="16" height="16"><circle cx="16" cy="16" r="2.5" fill="#61DAFB"/><ellipse cx="16" cy="16" rx="11" ry="4.2" fill="none" stroke="#61DAFB" stroke-width="1.3"/><ellipse cx="16" cy="16" rx="11" ry="4.2" fill="none" stroke="#61DAFB" stroke-width="1.3" transform="rotate(60 16 16)"/><ellipse cx="16" cy="16" rx="11" ry="4.2" fill="none" stroke="#61DAFB" stroke-width="1.3" transform="rotate(120 16 16)"/></svg>',
        'py':   '<svg viewBox="0 0 32 32" width="16" height="16"><defs><linearGradient id="pygb" x1="0%" y1="0%" x2="100%" y2="100%"><stop offset="0%" stop-color="#387EB8"/><stop offset="100%" stop-color="#366994"/></linearGradient><linearGradient id="pyyb" x1="0%" y1="0%" x2="100%" y2="100%"><stop offset="0%" stop-color="#FFE052"/><stop offset="100%" stop-color="#FFC331"/></linearGradient></defs><path d="M15.9 5C10.3 5 10.7 7.4 10.7 7.4l.01 2.5h5.3v.7H8.7S5 10.1 5 15.8c0 5.7 3.2 5.5 3.2 5.5h1.9v-2.6s-.1-3.2 3.1-3.2h5.4s3 .05 3-2.9V8.5S22.1 5 15.9 5z" fill="url(#pygb)"/><circle cx="12.5" cy="8.2" r="1.1" fill="#fff" opacity=".8"/><path d="M16.1 27c5.6 0 5.2-2.4 5.2-2.4l-.01-2.5h-5.3v-.7h7.3S27 21.9 27 16.2c0-5.7-3.2-5.5-3.2-5.5h-1.9v2.6s.1 3.2-3.1 3.2h-5.4s-3-.05-3 2.9v4.6S9.9 27 16.1 27z" fill="url(#pyyb)"/><circle cx="19.5" cy="23.8" r="1.1" fill="#fff" opacity=".8"/></svg>',
        'html': '<svg viewBox="0 0 32 32" width="16" height="16"><path d="M4 3l2.3 25.7L16 31l9.7-2.3L28 3z" fill="#E44D26"/><path d="M16 28.4V5.7l10.2 22.7z" fill="#F16529"/><path d="M9.4 13.5l.4 3.9H16v-3.9zM8.7 8H16V4.1H8.3zM16 21.5l-.05.01-4.1-1.1-.26-3h-3.9l.5 5.7 7.8 2.2z" fill="#EBEBEB"/><path d="M16 13.5v3.9h5.9l-.6 6.1-5.3 1.5v4l7.8-2.2.06-.6 1.2-13.1.12-1.6zm0-9.4v3.9h10.2l.08-1 .18-2.9z" fill="#fff"/></svg>',
        'css':  '<svg viewBox="0 0 32 32" width="16" height="16"><path d="M4 3l2.3 25.7L16 31l9.7-2.3L28 3z" fill="#1572B6"/><path d="M16 28.4V5.7l10.2 22.7z" fill="#33A9DC"/><path d="M21.5 13.5H16v-3.9h6l.4-3.6H9.6L10 9.6h5.9v3.9H9.3l.4 3.6H16v4.1l-4.2-1.2-.3-3.1H7.7l.6 6.3 7.7 2.1z" fill="#fff"/><path d="M16 17.2v-3.7h5.1l-.5 5.2L16 19.9v4.1l7.7-2.1.1-.6 1-10.4.1-1.4H16v4zM16 5.7v3.9h5.7l.1-1 .2-2.9z" fill="#EBEBEB"/></svg>',
        'scss': '<svg viewBox="0 0 32 32" width="16" height="16"><circle cx="16" cy="16" r="13" fill="#CD6799"/><path d="M22.5 14.7c-.7-.3-1.1-.4-1.6-.6-.3-.1-.6-.2-.8-.3-.2-.1-.4-.2-.4-.4 0-.3.4-.6 1.2-.6.9 0 1.7.3 2.1.5l.8-1.8c-.5-.3-1.5-.7-2.9-.7-1.5 0-2.7.4-3.5 1.1-.7.7-1 1.5-.9 2.4.1.9.7 1.6 1.9 2.1.5.2 1 .3 1.4.5.3.1.5.2.7.3.2.2.3.4.2.7-.1.5-.7.8-1.5.8-1 0-1.9-.3-2.5-.7l-.8 1.9c.7.4 1.8.7 3 .7h.3c1.3-.05 2.4-.4 3.1-1.1.7-.7 1-1.5.9-2.5-.1-.9-.7-1.6-1.7-2.3zm-7.6-4.2c-1.5 0-2.8.5-3.7 1.3l-.8-1.2-2.1 1.2.9 1.4c-.6.9-1 2-1 3.2s.4 2.3 1.1 3.2l-1.1 1.2 1.6 1.4 1.2-1.3c.9.5 1.9.8 3.1.8 3.4 0 5.7-2.5 5.7-5.7-.1-3-2.1-5.5-4.9-5.5zm-.3 9c-1.9 0-3.2-1.4-3.2-3.3s1.3-3.3 3.2-3.3c.8 0 1.5.3 2 .8l-3.4 4.2c.4.4.9.6 1.4.6z" fill="#fff"/></svg>',
        'json': '<svg viewBox="0 0 32 32" width="16" height="16"><path d="M12.7 6c-1.5 0-2.5.4-3 1.1-.5.7-.5 1.7-.5 2.5v2.2c0 .8-.2 1.5-.8 1.9-.3.2-.7.3-1.4.3v4c.7 0 1.1.1 1.4.3.6.4.8 1.1.8 1.9v2.2c0 .8 0 1.8.5 2.5.5.7 1.5 1.1 3 1.1H14v-2h-1.3c-.7 0-.9-.2-1-.4-.1-.2-.1-.7-.1-1.4v-2.2c0-1.2-.3-2.2-1.2-2.8-.2-.2-.5-.3-.8-.4.3-.1.5-.2.8-.4.9-.6 1.2-1.6 1.2-2.8V9.8c0-.7 0-1.2.1-1.4.1-.2.3-.4 1-.4H14V6h-1.3zm6.6 0v2h1.3c.7 0 .9.2 1 .4.1.2.1.7.1 1.4v2.2c0 1.2.3 2.2 1.2 2.8.2.2.5.3.8.4-.3.1-.5.2-.8.4-.9.6-1.2 1.6-1.2 2.8v2.2c0 .7 0 1.2-.1 1.4-.1.2-.3.4-1 .4H18v2h1.3c1.5 0 2.5-.4 3-1.1.5-.7.5-1.7.5-2.5v-2.2c0-.8.2-1.5.8-1.9.3-.2.7-.3 1.4-.3v-4c-.7 0-1.1-.1-1.4-.3-.6-.4-.8-1.1-.8-1.9V9.8c0-.8 0-1.8-.5-2.5C21.8 6.4 20.8 6 19.3 6z" fill="#F5A623"/></svg>',
        'md':   '<svg viewBox="0 0 32 32" width="16" height="16"><rect x="2" y="7" width="28" height="18" rx="3" fill="#42A5F5"/><path d="M7 22V10h3l3 4 3-4h3v12h-3v-7l-3 4-3-4v7zm16 0l-4-6h2.5v-6h3v6H27z" fill="#fff"/></svg>',
        'go':   '<svg viewBox="0 0 32 32" width="16" height="16"><path d="M16 5C9.4 5 4 10.4 4 17s5.4 12 12 12 12-5.4 12-12S22.6 5 16 5zm0 21c-5 0-9-4-9-9s4-9 9-9 9 4 9 9-4 9-9 9z" fill="#00ACD7"/><circle cx="12.5" cy="14.5" r="1.3" fill="#00ACD7"/><circle cx="19.5" cy="14.5" r="1.3" fill="#00ACD7"/><path d="M13 19s.7 2 3 2 3-2 3-2H13z" fill="#00ACD7"/></svg>',
        'rs':   '<svg viewBox="0 0 32 32" width="16" height="16"><path d="M16 3L18.1 7.3 22.8 6.2 22.7 11 27.1 12.9 24.5 17 27.1 21.1 22.7 23 22.8 27.8 18.1 26.7 16 31 13.9 26.7 9.2 27.8 9.3 23 4.9 21.1 7.5 17 4.9 12.9 9.3 11 9.2 6.2 13.9 7.3z" fill="#DEA584"/><circle cx="16" cy="17" r="5" fill="none" stroke="#DEA584" stroke-width="2"/><circle cx="16" cy="17" r="2.5" fill="#DEA584"/></svg>',
        'java': '<svg viewBox="0 0 32 32" width="16" height="16"><path d="M12.2 22.1s-1.2.7.8 1c2.4.3 3.6.2 6.2-.2 0 0 .7.4 1.6.8-5.7 2.4-12.9-.1-8.6-1.6zM11.5 19s-1.3 1 .7 1.2c2.5.3 4.5.3 8-.4 0 0 .5.5 1.2.8-7.1 2.1-15-.2-9.9-1.6z" fill="#E76F00"/><path d="M17.2 13.4c1.4 1.7-.4 3.2-.4 3.2s3.6-1.9 2-4.2c-1.5-2.2-2.6-3.3 3.6-7.1 0 0-9.8 2.4-5.2 8.1z" fill="#E76F00"/><path d="M23.2 24.4s.9.7-.9 1.3c-3.4 1-14.1 1.3-17.1 0-1.1-.5.9-1.1 1.5-1.2.6-.1 1-.1 1-.1-1.1-.8-7.4 1.6-3.2 2.3 11.6 1.9 21.1-.8 18.7-2.3zM12.6 15.9s-5.3 1.3-1.9 1.8c1.5.2 4.4.2 7.1-.1 2.2-.3 4.5-.8 4.5-.8s-.8.3-1.3.7c-5.4 1.4-15.7.8-12.8-.7 2.5-1.3 4.4-1 4.4-.9zM20.6 20.8c5.4-2.8 2.9-5.6 1.2-5.2-.4.1-.6.2-.6.2s.2-.3.5-.4c3.6-1.3 6.4 3.8-1.1 5.8 0 0 .1-.1 0-.4z" fill="#E76F00"/><path d="M18.5 3s3 3-2.9 7.7c-4.7 3.8-1.1 5.9 0 8.3-2.7-2.5-4.7-4.7-3.4-6.7 2-3 7.5-4.4 6.3-9.3z" fill="#E76F00"/></svg>',
        'kt':   '<svg viewBox="0 0 32 32" width="16" height="16"><defs><linearGradient id="kotb" x1="0%" y1="0%" x2="100%" y2="100%"><stop offset="0%" stop-color="#7F52FF"/><stop offset="50%" stop-color="#C811E1"/><stop offset="100%" stop-color="#E54857"/></linearGradient></defs><path d="M4 4h10l14 12-14 12H4L4 4z" fill="url(#kotb)"/><path d="M18 4l14 12-14 12V4z" fill="url(#kotb)" opacity=".6"/></svg>',
        'swift': '<svg viewBox="0 0 32 32" width="16" height="16"><defs><linearGradient id="swfb" x1="0%" y1="0%" x2="100%" y2="100%"><stop offset="0%" stop-color="#F05138"/><stop offset="100%" stop-color="#F8981E"/></linearGradient></defs><path d="M16 4c-3 2-6 6-6 10s2 6 4 7c-1-3 1-7 4-9 2 2 4 5 3 9 2-1 4-3 4-7s-3-8-6-10h-3z" fill="url(#swfb)"/><circle cx="16" cy="16" r="4" fill="#fff"/></svg>',
        'c':    '<svg viewBox="0 0 32 32" width="16" height="16"><circle cx="16" cy="16" r="13" fill="#005B9F"/><path d="M22.5 20.4c-.8 2.5-3.1 4.3-5.8 4.3-3.4 0-6.1-2.7-6.1-6.1 0-3.4 2.7-6.1 6.1-6.1 2.8 0 5.1 1.9 5.9 4.4H20c-.6-1.3-1.9-2.1-3.3-2.1-2 0-3.7 1.6-3.7 3.7s1.7 3.7 3.7 3.7c1.5 0 2.7-.9 3.3-2.2h2.5z" fill="#fff"/></svg>',
        'cpp':   '<svg viewBox="0 0 32 32" width="16" height="16"><circle cx="16" cy="16" r="13" fill="#00599C"/><path d="M18 20.4c-.8 2.5-3.1 4.3-5.8 4.3-3.4 0-6.1-2.7-6.1-6.1 0-3.4 2.7-6.1 6.1-6.1 2.8 0 5.1 1.9 5.9 4.4h-2.6c-.6-1.3-1.9-2.1-3.3-2.1-2 0-3.7 1.6-3.7 3.7s1.7 3.7 3.7 3.7c1.5 0 2.7-.9 3.3-2.2H18z" fill="#fff"/><path d="M21 13.3v1.5h-1.5V16H21v1.7h1.5V16H24v-1.2h-1.5v-1.5zm4.5 0v1.5H24V16h1.5v1.7H27V16h1.5v-1.2H27v-1.5z" fill="#fff"/></svg>',
        'cs':   '<svg viewBox="0 0 32 32" width="16" height="16"><defs><linearGradient id="csg2b" x1="0%" y1="0%" x2="100%" y2="100%"><stop offset="0%" stop-color="#9B4F96"/><stop offset="100%" stop-color="#68217A"/></linearGradient></defs><circle cx="16" cy="16" r="13" fill="url(#csg2b)"/><path d="M10 19.8c-.8-2.1.1-4.6 2.1-5.8s4.5-1 6.3.5l-1 1.7c-1.2-.9-2.8-1.1-4.1-.3-1.3.7-1.9 2.2-1.5 3.6l-1.8.3zm12 0c-.5 1.4-1.7 2.5-3.1 2.8l-.4-1.9c.8-.2 1.4-.8 1.7-1.5l1.8.6z" fill="#fff"/><path d="M20 13.4h1.2v1.2H20zm0 2.4h1.2v1.2H20zm2.4-2.4h1.2v1.2h-1.2zm0 2.4h1.2v1.2h-1.2z" fill="#fff"/></svg>',
        'rb':   '<svg viewBox="0 0 32 32" width="16" height="16"><defs><linearGradient id="rbg2b" x1="0%" y1="100%" x2="100%" y2="0%"><stop offset="0%" stop-color="#FF0000"/><stop offset="100%" stop-color="#A30000"/></linearGradient></defs><path d="M22.9 5L27 9.1l.1 17.8-4.2 4.1H9L5 27.1 4.9 9.3 9 5z" fill="url(#rbg2b)"/><path d="M11 10l-3 3v9l3 3h10l3-3v-9l-3-3zm.5 13l-2-2v-7l2-2h9l2 2v7l-2 2z" fill="#fff" opacity=".7"/><circle cx="16" cy="16" r="2.5" fill="#fff"/></svg>',
        'php':  '<svg viewBox="0 0 32 32" width="16" height="16"><ellipse cx="16" cy="16" rx="14" ry="9" fill="#8892BF"/><path d="M10.5 12H8l-2 8h2l.5-2h2l.5 2h2zm-.5 4.5H9l.5-2h.5zm6.5-4.5h-3l-2 8h2l.5-2h1c1.7 0 3-1.3 3-3s-1.3-3-2.5-3zm-.5 4.5H16l.5-2h.5c.5 0 1 .5 1 1s-.5 1-1 1zm7.5-4.5h-3l-2 8h2l.5-2h2l.5 2h2zm-.5 4.5h-1l.5-2h.5z" fill="#fff"/></svg>',
        'dart': '<svg viewBox="0 0 32 32" width="16" height="16"><defs><linearGradient id="dartb" x1="0%" y1="0%" x2="100%" y2="100%"><stop offset="0%" stop-color="#0175C2"/><stop offset="100%" stop-color="#02569B"/></linearGradient></defs><path d="M16 4L4 12v12l12 8 12-8V12z" fill="url(#dartb)"/><path d="M16 4v24l12-8V12z" fill="url(#dartb)" opacity=".7"/><path d="M10 14h12v2H10zm2 4h8v2h-8z" fill="#fff"/></svg>',
        'lua':  '<svg viewBox="0 0 32 32" width="16" height="16"><circle cx="16" cy="16" r="13" fill="#000080"/><path d="M22 10c-2 0-3 1-3.5 2.5-.5-1-1.5-1.5-2.5-1.5-1.5 0-2.5 1-2.5 2.5 0 2 2 2.5 4 3 2 .5 4 1 4 3 0 1.5-1 2.5-2.5 2.5-2 0-3-1.5-4-3-.5 1.5-1.5 3-3 3v-2c1 0 2-.5 2.5-1.5.5 1 1.5 1.5 2.5 1.5 1.5 0 2.5-1 2.5-2.5 0-2-2-2.5-4-3-2-.5-4-1-4-3C12 8.5 13.5 7 16 7c1.5 0 2.5 1 3.5 2 .5-1.5 1.5-2.5 3-2.5v2z" fill="#fff"/></svg>',
        'r':    '<svg viewBox="0 0 32 32" width="16" height="16"><rect width="32" height="32" rx="3" fill="#276DC3"/><path d="M8 8h4v16h-4zM14 8h10l-2 5h-3l-1 3h3l-2 8H14z" fill="#fff"/></svg>',
        'jl':   '<svg viewBox="0 0 32 32" width="16" height="16"><circle cx="16" cy="16" r="13" fill="#9558B2"/><circle cx="16" cy="16" r="9" fill="none" stroke="#fff" stroke-width="1.5"/><circle cx="16" cy="16" r="4" fill="#fff"/><path d="M16 7v4M16 21v4M7 16h4M21 16h4" stroke="#fff" stroke-width="1.5"/></svg>',
        'zig':  '<svg viewBox="0 0 32 32" width="16" height="16"><defs><linearGradient id="zigb" x1="0%" y1="0%" x2="100%" y2="100%"><stop offset="0%" stop-color="#F7A800"/><stop offset="100%" stop-color="#FF9500"/></linearGradient></defs><path d="M16 4L4 16l12 12 12-12z" fill="url(#zigb)"/><path d="M16 10l-6 6 6 6 6-6z" fill="#000" opacity=".3"/></svg>',
        'ex':   '<svg viewBox="0 0 32 32" width="16" height="16"><defs><linearGradient id="elxb" x1="0%" y1="0%" x2="100%" y2="100%"><stop offset="0%" stop-color="#4B275F"/><stop offset="100%" stop-color="#6E3A8E"/></linearGradient></defs><circle cx="16" cy="16" r="13" fill="url(#elxb)"/><path d="M10 10c0-1 1-2 2-2h8c1 0 2 1 2 2v2l-6 8-6-8v-2z" fill="#fff"/><ellipse cx="16" cy="14" rx="4" ry="2" fill="#4B275F"/></svg>',
        'hs':   '<svg viewBox="0 0 32 32" width="16" height="16"><defs><linearGradient id="hsb" x1="0%" y1="0%" x2="100%" y2="100%"><stop offset="0%" stop-color="#5D4F85"/><stop offset="100%" stop-color="#453A6B"/></linearGradient></defs><path d="M8 4h10l6 6v18H8V4z" fill="url(#hsb)"/><path d="M18 4v6h6" fill="none" stroke="#fff" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/><text x="16" y="22" font-family="Segoe UI,sans-serif" font-size="6" font-weight="bold" fill="#fff" text-anchor="middle">HS</text></svg>',
        'clj':  '<svg viewBox="0 0 32 32" width="16" height="16"><circle cx="16" cy="16" r="13" fill="#588526"/><path d="M10 10l6 12 6-12H10z" fill="#96CA50"/><circle cx="16" cy="16" r="3" fill="#fff"/></svg>',
        'vue':  '<svg viewBox="0 0 32 32" width="16" height="16"><polygon points="16,27 2,5 8.5,5 16,18.5 23.5,5 30,5" fill="#41B883"/><polygon points="16,20 9.5,9 13,9 16,14 19,9 22.5,9" fill="#35495E"/></svg>',
        'svelte': '<svg viewBox="0 0 32 32" width="16" height="16"><path d="M26.1 5.8c-2.8-4-8.4-5-12.4-2.3L7.2 7.7C5.3 9 4 11 3.8 13.3c-.2 1.9.3 3.8 1.4 5.3-.8 1.2-1.2 2.7-1.1 4.1.2 2.7 1.9 5.1 4.4 6.2 2.8 1.2 6 .7 8.3-1.2l6.5-4.2c1.9-1.3 3.2-3.3 3.4-5.6.2-1.9-.3-3.8-1.4-5.3.8-1.2 1.2-2.7 1.1-4.1-.1-1.1-.5-2.2-1.3-2.7z" fill="#FF3E00"/><path d="M13.7 27c-1.6.4-3.3 0-4.6-.9-1.8-1.3-2.5-3.5-1.8-5.5l.2-.5.4.3c1 .7 2 1.2 3.2 1.5l.3.1-.03.3c-.05.7.2 1.4.7 1.9.9.8 2.3.9 3.3.2l6.5-4.2c.6-.4 1-.9 1.1-1.6.1-.7-.1-1.4-.6-1.9-.9-.8-2.3-.9-3.3-.2l-2.5 1.6c-1.1.7-2.4 1-3.7.8-1.5-.2-2.8-1-3.6-2.2-1.4-2-1-4.7.9-6.2l6.5-4.2c1.6-1.1 3.7-1.3 5.5-.6 1.8.7 3 2.3 3.2 4.2.1.7 0 1.5-.3 2.2l-.2.5-.4-.3c-1-.7-2-1.2-3.2-1.5l-.3-.1.03-.3c.05-.7-.2-1.4-.7-1.9-.9-.8-2.3-.9-3.3-.2l-6.5 4.2c-.6.4-1 .9-1.1 1.6-.1.7.1 1.4.6 1.9.9.8 2.3.9 3.3.2l2.5-1.6c1.1-.7 2.4-1 3.7-.8 1.5.2 2.8 1 3.6 2.2 1.4 2 1 4.7-.9 6.2L18 26.3c-.8.5-1.5.8-2.3.7z" fill="#fff"/></svg>',
        'sql':  '<svg viewBox="0 0 32 32" width="16" height="16"><ellipse cx="16" cy="10" rx="10" ry="4" fill="#4479A1"/><path d="M6 10v4c0 2.2 4.5 4 10 4s10-1.8 10-4v-4c0 2.2-4.5 4-10 4S6 12.2 6 10z" fill="#4479A1"/><path d="M6 14v4c0 2.2 4.5 4 10 4s10-1.8 10-4v-4c0 2.2-4.5 4-10 4S6 16.2 6 14z" fill="#336791"/><path d="M6 18v4c0 2.2 4.5 4 10 4s10-1.8 10-4v-4c0 2.2-4.5 4-10 4S6 20.2 6 18z" fill="#336791"/></svg>',
        'sh':   '<svg viewBox="0 0 32 32" width="16" height="16"><rect width="32" height="32" rx="3" fill="#1E1E1E"/><path d="M6 10l7 6-7 6" fill="none" stroke="#4EC9B0" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"/><path d="M16 22h10" stroke="#4EC9B0" stroke-width="2.5" stroke-linecap="round"/></svg>',
        'bat':  '<svg viewBox="0 0 32 32" width="16" height="16"><rect width="32" height="32" rx="3" fill="#1E1E1E"/><path d="M6 10l7 6-7 6" fill="none" stroke="#4EC9B0" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"/><path d="M16 22h10" stroke="#4EC9B0" stroke-width="2.5" stroke-linecap="round"/></svg>',
        'ps1':  '<svg viewBox="0 0 32 32" width="16" height="16"><rect width="32" height="32" rx="3" fill="#1E1E1E"/><path d="M6 10l7 6-7 6" fill="none" stroke="#4EC9B0" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"/><path d="M16 22h10" stroke="#4EC9B0" stroke-width="2.5" stroke-linecap="round"/></svg>',
        'txt':  '<svg viewBox="0 0 32 32" width="16" height="16"><path d="M8 4h10l6 6v18H8V4z" fill="#9AAABB"/><path d="M18 4v6h6" fill="none" stroke="#fff" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/><line x1="10" y1="13" x2="22" y2="13" stroke="#fff" stroke-width="1.5" stroke-linecap="round"/><line x1="10" y1="17" x2="22" y2="17" stroke="#fff" stroke-width="1.5" stroke-linecap="round"/><line x1="10" y1="21" x2="18" y2="21" stroke="#fff" stroke-width="1.5" stroke-linecap="round"/></svg>',
        'env':  '<svg viewBox="0 0 32 32" width="16" height="16"><rect width="32" height="32" rx="3" fill="#4A9B4F"/><path d="M8 4h10l6 6v18H8V4z" fill="#5DBA5F"/><path d="M18 4v6h6" fill="none" stroke="#fff" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/><text x="16" y="22" font-family="Segoe UI,sans-serif" font-size="7" font-weight="bold" fill="#fff" text-anchor="middle">ENV</text></svg>',
        'zip':  '<svg viewBox="0 0 32 32" width="16" height="16"><rect width="32" height="32" rx="3" fill="#8E44AD"/><path d="M16 7l-2 2h-3l-1 3h3l-2 2 2 2h-3l1 3h3l2 2 2-2h3l1-3h-3l2-2-2-2h3l-1-3h-3z" fill="#F39C12"/><rect x="10" y="12" width="12" height="10" rx="1" fill="none" stroke="#fff" stroke-width="1.5"/></svg>',
        'git':  '<svg viewBox="0 0 32 32" width="16" height="16"><path d="M29.5 14.5L17.5 2.5c-.7-.7-1.8-.7-2.5 0L12.4 5l3 3c.7-.2 1.5 0 2 .6.6.5.8 1.3.6 2l2.9 2.9c.7-.2 1.5 0 2 .6.9.9.9 2.3 0 3.2-.9.9-2.3.9-3.2 0-.6-.6-.8-1.5-.5-2.2L16.5 12v8c.2.1.4.2.6.4.9.9.9 2.3 0 3.2-.9.9-2.3.9-3.2 0-.9-.9-.9-2.3 0-3.2.2-.2.5-.4.7-.5v-8c-.2-.1-.5-.3-.7-.5-.6-.6-.8-1.5-.5-2.2L10.5 6.1 2.5 14c-.7.7-.7 1.8 0 2.5l12 12c.7.7 1.8.7 2.5 0l12.5-12.5c.7-.7.7-1.8 0-2.5z" fill="#F34F29"/></svg>',
        'gitignore': '<svg viewBox="0 0 32 32" width="16" height="16"><path d="M29.5 14.5L17.5 2.5c-.7-.7-1.8-.7-2.5 0L12.4 5l3 3c.7-.2 1.5 0 2 .6.6.5.8 1.3.6 2l2.9 2.9c.7-.2 1.5 0 2 .6.9.9.9 2.3 0 3.2-.9.9-2.3.9-3.2 0-.6-.6-.8-1.5-.5-2.2L16.5 12v8c.2.1.4.2.6.4.9.9.9 2.3 0 3.2-.9.9-2.3.9-3.2 0-.9-.9-.9-2.3 0-3.2.2-.2.5-.4.7-.5v-8c-.2-.1-.5-.3-.7-.5-.6-.6-.8-1.5-.5-2.2L10.5 6.1 2.5 14c-.7.7-.7 1.8 0 2.5l12 12c.7.7 1.8.7 2.5 0l12.5-12.5c.7-.7.7-1.8 0-2.5z" fill="#F34F29"/></svg>',
        'gitattributes': '<svg viewBox="0 0 32 32" width="16" height="16"><path d="M29.5 14.5L17.5 2.5c-.7-.7-1.8-.7-2.5 0L12.4 5l3 3c.7-.2 1.5 0 2 .6.6.5.8 1.3.6 2l2.9 2.9c.7-.2 1.5 0 2 .6.9.9.9 2.3 0 3.2-.9.9-2.3.9-3.2 0-.6-.6-.8-1.5-.5-2.2L16.5 12v8c.2.1.4.2.6.4.9.9.9 2.3 0 3.2-.9.9-2.3.9-3.2 0-.9-.9-.9-2.3 0-3.2.2-.2.5-.4.7-.5v-8c-.2-.1-.5-.3-.7-.5-.6-.6-.8-1.5-.5-2.2L10.5 6.1 2.5 14c-.7.7-.7 1.8 0 2.5l12 12c.7.7 1.8.7 2.5 0l12.5-12.5c.7-.7.7-1.8 0-2.5z" fill="#F34F29"/></svg>',
        'docker': '<svg viewBox="0 0 32 32" width="16" height="16"><path d="M28.8 14.5c-.5-.3-1.6-.5-2.5-.3-.1-.9-.7-1.7-1.6-2.3l-.5-.3-.4.4c-.5.6-.7 1.6-.6 2.3.1.5.3.9.6 1.3-.3.1-.8.3-1.5.3H4.1c-.3 1.3-.1 3 .9 4.2.9 1.2 2.3 1.9 4.3 1.9 4 0 7-1.8 8.9-5 1.1.1 3.4.1 4.6-2.2.1 0 .6-.3 1.6-.9l.5-.3-.1-.1z" fill="#2396ED"/><rect x="7" y="13" width="2" height="2" rx=".3" fill="#2396ED"/><rect x="9.7" y="13" width="2" height="2" rx=".3" fill="#2396ED"/><rect x="12.4" y="13" width="2" height="2" rx=".3" fill="#2396ED"/><rect x="15.1" y="13" width="2" height="2" rx=".3" fill="#2396ED"/><rect x="17.8" y="13" width="2" height="2" rx=".3" fill="#2396ED"/><rect x="12.4" y="11" width="2" height="2" rx=".3" fill="#2396ED"/><rect x="15.1" y="11" width="2" height="2" rx=".3" fill="#2396ED"/><rect x="17.8" y="11" width="2" height="2" rx=".3" fill="#2396ED"/><rect x="15.1" y="9" width="2" height="2" rx=".3" fill="#2396ED"/></svg>',
        'yaml': '<svg viewBox="0 0 32 32" width="16" height="16"><rect width="32" height="32" rx="3" fill="#CC1018"/><path d="M7 9h2.5l3 5 3-5H18l-4.5 7v6h-2v-6zm11 4h7v2h-2.5v8h-2v-8H18z" fill="#fff"/></svg>',
        'xml':  '<svg viewBox="0 0 32 32" width="16" height="16"><rect width="32" height="32" rx="3" fill="#607D8B"/><circle cx="16" cy="16" r="5" fill="none" stroke="#fff" stroke-width="2"/><path d="M16 5v4M16 23v4M5 16h4M23 16h4M8.5 8.5l2.8 2.8M20.7 20.7l2.8 2.8M8.5 23.5l2.8-2.8M20.7 11.3l2.8-2.8" stroke="#fff" stroke-width="2" stroke-linecap="round"/></svg>',
    };
    return badges[ext] || '<svg viewBox="0 0 32 32" width="16" height="16"><path d="M8 4h10l6 6v18H8V4z" fill="#90A4AE"/><path d="M18 4v6h6" fill="none" stroke="#fff" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg>';
}

// ================================================================
// RENDER CUSTOM TAGS INTO MESSAGE (renderCustomTagsInto)
// ================================================================
function renderCustomTagsInto(msgEl, fullText) {
    if (!msgEl || !fullText) {
        console.log('[DEBUG] renderCustomTagsInto: missing msgEl or fullText');
        return;
    }

    console.log('[DEBUG] renderCustomTagsInto called, fullText length:', fullText.length);

    // -- Find or create cards container --------------------------------
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
        console.log('[DEBUG] Created new cards container');
    }

    // -- Parse <file_edited> tags ------------------------------------
    var feRe = /<file_edited>([\s\S]*?)<\/file_edited>/g;
    var m;
    var matchCount = 0;
    while ((m = feRe.exec(fullText)) !== null) {
        matchCount++;
        var lines = m[1].trim().split('\n')
                        .map(function(l) { return l.trim(); })
                        .filter(Boolean);
        console.log('[DEBUG] Found file_edited tag, lines:', lines);
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

        console.log('[DEBUG] File edit:', filePath, '+', added, '-', removed, editType);

        // Don't add duplicate cards for same path
        if (cardsEl.querySelector('[data-path="' + filePath + '"]')) {
            console.log('[DEBUG] Duplicate card skipped for:', filePath);
            continue;
        }

        var card = buildFileEditCard(filePath, added, removed, editType, 'pending');
        cardsEl.appendChild(card);
        console.log('[DEBUG] Card added for:', filePath);

        // Also sync to Changed Files panel
        addChangedFile(filePath, added, removed, editType);
    }
    console.log('[DEBUG] Total file_edited tags found:', matchCount);
}

// ================================================================
// CODE BLOCK HEADER INJECTION
// ================================================================
function injectCodeBlockHeader(codeEl) {
    var pre = codeEl.parentElement;
    if (!pre || pre.tagName !== 'PRE') return;
    // Skip if already wrapped (idempotent)
    if (pre.closest('.code-block-wrapper')) return;

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

    // Wrap pre in a container so the header is OUTSIDE the scrollable pre.
    // This prevents the header from scrolling with long code lines.
    var wrapper = document.createElement('div');
    wrapper.className = 'code-block-wrapper';
    pre.parentNode.insertBefore(wrapper, pre);
    wrapper.appendChild(pre);
    wrapper.insertBefore(header, pre); // header above pre, not inside it
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
// INDUSTRY STANDARD ENHANCEMENTS - CURSOR/QODER PARITY
// ================================================================

// -- FILE EDIT CARD BRIDGE HANDLERS ------------------------------
function openFileInEditor(filePath) {
    // Handle relative paths by prepending project path
    if (filePath && currentProjectPath) {
        // Check if path is absolute (starts with drive letter like C:\ or / on Unix, or contains :\)
        var isAbsolute = /^[a-zA-Z]:\\/.test(filePath) || filePath.startsWith('/') || filePath.includes(':\\') || filePath.includes(':/');
        console.log('[DEBUG] openFileInEditor - filePath:', filePath, 'isAbsolute:', isAbsolute, 'currentProjectPath:', currentProjectPath);
        if (!isAbsolute) {
            // Normalize path separator and join with project path
            var separator = currentProjectPath.includes('/') ? '/' : '\\';
            filePath = currentProjectPath + separator + filePath;
            console.log('[DEBUG] Prepended project path, new filePath:', filePath);
        }
    }
    // Convert backslashes to forward slashes for safe bridge transmission
    var safePath = filePath.replace(/\\/g, '/');
    console.log('[DEBUG] Opening file:', safePath);
    if (window.bridge) bridge.on_open_file(safePath);
}

function requestDiff(filePath) {
    console.log('[Diff] requestDiff called with:', filePath);
    if (window.bridge && window.bridge.on_show_diff) {
        window.bridge.on_show_diff(filePath);
        console.log('[Diff] requestDiff: Bridge method called');
    } else {
        console.error('[Diff] requestDiff: Bridge or on_show_diff not available');
    }
}

function requestFecDiff(btn) {
    var filePath = btn.dataset.path;
    console.log('[Diff] requestFecDiff called with:', filePath);
    if (window.bridge && window.bridge.on_show_diff) {
        window.bridge.on_show_diff(filePath);
        console.log('[Diff] requestFecDiff: Bridge method called');
    } else {
        console.error('[Diff] requestFecDiff: Bridge or on_show_diff not available');
    }
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

// -- @ MENTION SYSTEM --------------------------------------------
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

// -- TOKEN COUNTER ------------------------------------------------
function updateTokenCounter() {
    // Token counter removed — not displayed
}

// -- SCROLL JUMP BUTTON -------------------------------------------
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

// -- LIVE TOOL ACTIVITY (onToolActivity from Python bridge) -------
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

// -- INPUT ENHANCEMENTS: @ DETECTION + TOKEN COUNTER -------------
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

// -- SCROLL JUMP BUTTON: show when user scrolls up during streaming -
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


// --------------------------------------------------------------
// THREE FEATURES IMPLEMENTATION
// --------------------------------------------------------------

// -- State variables for features ------------------------------
var _todoExpanded = false;
var _msgQueue     = [];
var _isGenerating = false;
var _queueIdSeq   = 0;

// --------------------------------------------------------------
// FEATURE 1 - PROJECT TREE CARD
// --------------------------------------------------------------

function buildProjectTreeCard(rootPath, items) {
    var card = document.createElement('div');
    card.className = 'ptree-card';
    card.dataset.root = rootPath;

    // Clean root path for display - show just folder name
    var displayPath = rootPath.replace(/\\/g, '/');
    var folderName = displayPath.replace(/\/$/, '').split('/').pop() || displayPath;

    var rootEl = document.createElement('div');
    rootEl.className = 'ptree-root';
    rootEl.innerHTML = 
        '<span class="ptree-root-icon">' + (FILE_ICONS.folder ? FILE_ICONS.folder(15) : '') + '</span>' +
        '<span style="flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">' + escapeHtml(folderName) + '</span>' +
        '<span class="ptree-root-count">' + items.length + ' items</span>' +
        '<svg class="ptree-root-chevron" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="transform:rotate(-90deg);transition:transform 0.2s;"><polyline points="6 9 12 15 18 9"></polyline></svg>';
    rootEl.dataset.path = rootPath;
    rootEl.title = rootPath;
    rootEl.onclick = function() {
        var isCollapsed = card.classList.toggle('collapsed');
        var chev = rootEl.querySelector('.ptree-root-chevron');
        if (chev) chev.style.transform = isCollapsed ? 'rotate(-90deg)' : 'rotate(0deg)';
    };
    card.appendChild(rootEl);
    // Start collapsed — contents hidden by default
    card.classList.add('collapsed');

    var list = document.createElement('div');
    list.className = 'ptree-list';

    // Build tree structure with proper connectors
    items.forEach(function(item, idx) {
        var depth = item.depth || 0;
        var isLast = item.isLast;
        var hasChildren = item.hasChildren;

        var row = document.createElement('div');
        row.className = 'ptree-item' + (isLast ? ' ptree-last' : '');
        row.style.paddingLeft = (depth * 16) + 'px';  // Indent based on depth
        row.dataset.depth = depth;

        // Determine the branch connector
        var branch = isLast ? '\u2514\u2500' : '\u251C\u2500';

        // Use SVG icons instead of emoji
        var icon = item.isDir
            ? FILE_ICONS.folder(14)
            : getFileExtensionIcon(item.name.split('.').pop().toLowerCase(), 14);

        var esc = (item.path || '').replace(/'/g, "\\'").replace(/\\/g, '\\\\');

        var sizeHtml = item.size
            ? '<span class="ptree-size">(' + escapeHtml(item.size) + ')</span>'
            : '';
        var descHtml = item.description
            ? '<span class="ptree-desc">- ' + escapeHtml(item.description) + '</span>'
            : '';

        row.innerHTML =
            '<span class="ptree-branch">' + branch + '</span>' +
            '<span class="ptree-icon">' + icon + '</span>' +
            '<button class="ptree-filename" onclick="' +
                (item.isDir
                    ? 'openFolderInExplorer(\'' + esc + '\')'
                    : 'openFileInEditor(\'' + esc + '\')') +
            '\">' + escapeHtml(item.name) + '</button>' +
            sizeHtml + descHtml;

        list.appendChild(row);
    });

    card.appendChild(list);
    return card;
}

function getFileEmoji(filename) {
    var ext = (filename || '').split('.').pop().toLowerCase();
    var map = {
        'html': 'HTML', 'htm': 'HTML',
        'js':   'JS', 'ts':  'TS', 'jsx': 'JSX', 'tsx': 'TSX',
        'css':  'CSS', 'scss': 'SCSS',
        'py':   'PY', 'java': 'JAVA', 'go':  'GO', 'rs':  'RS',
        'json': 'JSON', 'yaml': 'YAML', 'yml': 'YML',
        'md':   'MD', 'txt':  'TXT',
        'png':  'PNG', 'jpg': 'JPG', 'svg': 'SVG',
        'mp4':  'MP4', 'mp3':  'MP3',
        'zip':  'ZIP', 'tar':  'TAR',
        'sh':   'SH', 'bat':  'BAT',
    };
    return map[ext] || 'FILE';
}

function showProjectTreeCard(rootPath, items) {
    var container = document.getElementById('chatMessages');
    if (!container) return;

    var card = buildProjectTreeCard(rootPath, items);

    if (currentAssistantMessage) {
        var cardsEl = currentAssistantMessage.querySelector('.fec-cards-container');
        if (!cardsEl) {
            cardsEl = document.createElement('div');
            cardsEl.className = 'fec-cards-container';
            currentAssistantMessage.appendChild(cardsEl);
        }
        cardsEl.appendChild(card);
    } else {
        container.appendChild(card);
    }

    smartScroll(container);
}

function openFolderInExplorer(path) {
    // Convert forward slashes back to backslashes for Windows
    var windowsPath = path.replace(/\//g, '\\');
    if (window.bridge) bridge.on_open_folder(windowsPath);
}

window.showDirectoryTree = function(rootPath, items) {
    showProjectTreeCard(rootPath, items);
};

// --------------------------------------------------------------
// FEATURE 2 - TERMINAL COMMAND CARD
// --------------------------------------------------------------

function buildTerminalCard(command, output, status, exitCode, cardId) {
    var card = document.createElement('div');
    card.className = 'term-card term-' + status;
    card.id = cardId || ('term-' + Date.now());
    card.dataset.command = command;
    card.dataset.status  = status;
    card.dataset.expanded = 'true';  // start expanded

    // Status icon
    var headerIcon = {
        'running': '<span class="todo-spinner" style="width:13px;height:13px;border-width:2px;"></span>',
        'success': '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="#22c55e" stroke-width="2.5"><polyline points="20 6 9 17 4 12"></polyline></svg>',
        'error':   '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="#ef4444" stroke-width="2.5"><circle cx="12" cy="12" r="10"/><line x1="15" y1="9" x2="9" y2="15"/><line x1="9" y1="9" x2="15" y2="15"/></svg>'
    }[status] || '<span class="todo-spinner" style="width:13px;height:13px;border-width:2px;"></span>';

    // Header title — changes based on status
    var titleText = (status === 'running') ? 'Running in terminal' : 'Run in terminal';

    // Right-side badge
    var badgeHtml = '';
    if (status === 'running') {
        badgeHtml = '<span class="term-badge term-badge-running">Background</span>';
    } else if (status === 'success') {
        badgeHtml = '<span class="term-badge term-badge-done">Done</span>';
    } else if (status === 'error') {
        badgeHtml = '<span class="term-badge term-badge-failed">Failed</span>';
    }

    var exitCodeHtml = (status === 'error' && exitCode !== undefined && exitCode !== null)
        ? '<span class="term-exit-code">Exit ' + exitCode + '</span>'
        : '';

    // Parse command if passed as JSON string
    var displayCmd = command;
    if (command && command.trim().startsWith('{')) {
        try {
            var parsed = JSON.parse(command);
            if (parsed.command) displayCmd = parsed.command;
        } catch(e) {}
    }

    var formattedCmd = formatTerminalCommand(displayCmd);
    var esc = (displayCmd || '').replace(/\\/g, '\\\\').replace(/'/g, "\\'");

    var outputId = (cardId || card.id) + '-output';
    var outputHtml = output
        ? '<div class="term-output-body" id="' + outputId + '" style="display:block;">'
              + '<pre class="term-output-text">' + escapeHtml(output) + '</pre>'
          + '</div>'
        : '';

    var chevronSvg = '<svg class="term-chevron" width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" style="transition:transform 0.2s ease;transform:rotate(90deg);"><polyline points="9 18 15 12 9 6"></polyline></svg>';

    card.innerHTML =
        '<div class="term-header" onclick="toggleTermCard(this)">' +
            '<span class="term-status-icon">' + headerIcon + '</span>' +
            '<span class="term-title"><span class="term-title-text">' + titleText + '</span></span>' +
            badgeHtml +
            exitCodeHtml +
            chevronSvg +
        '</div>' +
        '<div class="term-body">' +
            '<pre class="term-command">' + formattedCmd + '</pre>' +
        '</div>' +
        (outputHtml || '') +
        '<div class="term-footer">' +
            '<span></span>' +
            '<button class="term-view-btn" onclick="event.stopPropagation();openTerminalPanel(\'' + esc + '\')">' +
                '<svg width="11" height="11" viewBox="0 0 24 24" fill="none" ' +
                    'stroke="currentColor" stroke-width="2">' +
                    '<polyline points="15 3 21 3 21 9"/>' +
                    '<path d="M21 3L9 15"/>' +
                    '<polyline points="9 21 3 21 3 15"/>' +
                '</svg>' +
                ' View in terminal' +
            '</button>' +
        '</div>';

    return card;
}

// Toggle terminal card expand / collapse
function toggleTermCard(headerEl) {
    var card = headerEl.closest('.term-card');
    if (!card) return;
    var body    = card.querySelector('.term-body');
    var output  = card.querySelector('.term-output-body');
    var footer  = card.querySelector('.term-footer');
    var chevron = headerEl.querySelector('.term-chevron');
    var isExpanded = card.dataset.expanded !== 'false';
    if (isExpanded) {
        if (body)   body.style.display   = 'none';
        if (output) output.style.display = 'none';
        if (footer) footer.style.display = 'none';
        if (chevron) chevron.style.transform = 'rotate(0deg)';
        card.dataset.expanded = 'false';
    } else {
        if (body)   body.style.display   = 'block';
        if (output) output.style.display = 'block';
        if (footer) footer.style.display = 'flex';
        if (chevron) chevron.style.transform = 'rotate(90deg)';
        card.dataset.expanded = 'true';
    }
}

function formatTerminalCommand(command) {
    if (!command) return '';

    var parts = command.split(/\s*;\s*/);
    var lines = [];

    parts.forEach(function(part) {
        part = part.trim();
        if (!part) return;

        var html = escapeHtml(part);

        html = html.replace(
            /(c:\\\\[^\s&|"'<>]+)/gi,
            '<span class="term-path">$1</span>'
        );
        html = html.replace(
            /(\/(?:home|usr|var|opt|etc|tmp)[^\s&|"'<>]*)/g,
            '<span class="term-path">$1</span>'
        );
        html = html.replace(
            /^(\s*)(cd|python|python3|node|npm|pip|dir|ls|mkdir|rm|cp|mv|git|cargo|go|java|javac|pytest|php|ruby|perl)(\s)/,
            '$1<span class="term-keyword">$2</span>$3'
        );

        lines.push(html);
    });

    return lines.join('\n');
}

function toggleTerminalOutput(outputId, btn) {
    var output = document.getElementById(outputId);
    if (!output) return;
    var isHidden = output.style.display === 'none';
    output.style.display = isHidden ? 'block' : 'none';
    var chevron = btn.querySelector('.term-chevron');
    if (chevron) chevron.textContent = isHidden ? '?' : '-';
}

function updateTerminalCard(cardId, status, exitCode, output) {
    var card = document.getElementById(cardId);
    if (!card) return;

    card.className = 'term-card term-' + status;
    card.dataset.status = status;

    // Update status icon
    var iconEl = card.querySelector('.term-status-icon');
    if (iconEl) {
        if (status === 'success') iconEl.innerHTML = '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="#22c55e" stroke-width="2.5"><polyline points="20 6 9 17 4 12"></polyline></svg>';
        if (status === 'error')   iconEl.innerHTML = '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="#ef4444" stroke-width="2.5"><circle cx="12" cy="12" r="10"/><line x1="15" y1="9" x2="9" y2="15"/><line x1="9" y1="9" x2="15" y2="15"/></svg>';
    }

    // Update title text
    var titleTextEl = card.querySelector('.term-title-text');
    if (titleTextEl) {
        titleTextEl.textContent = (status === 'running') ? 'Running in terminal' : 'Run in terminal';
    }

    // Update badge
    var badgeEl = card.querySelector('.term-badge');
    if (status === 'success') {
        if (badgeEl) { badgeEl.className = 'term-badge term-badge-done'; badgeEl.textContent = 'Done'; }
        else {
            var b = document.createElement('span');
            b.className = 'term-badge term-badge-done'; b.textContent = 'Done';
            var chevron = card.querySelector('.term-chevron');
            if (chevron) card.querySelector('.term-header').insertBefore(b, chevron);
        }
    } else if (status === 'error') {
        if (badgeEl) { badgeEl.className = 'term-badge term-badge-failed'; badgeEl.textContent = 'Failed'; }
    }

    // Update exit code
    if (status === 'error' && exitCode !== undefined) {
        var existingExit = card.querySelector('.term-exit-code');
        if (!existingExit) {
            var exitEl = document.createElement('span');
            exitEl.className = 'term-exit-code';
            exitEl.textContent = 'Exit ' + exitCode;
            var chevronEl = card.querySelector('.term-chevron');
            if (chevronEl) card.querySelector('.term-header').insertBefore(exitEl, chevronEl);
        }
    }

    if (output) {
        var outputId = cardId + '-output';
        var existingOutput = document.getElementById(outputId);
        if (existingOutput) {
            existingOutput.querySelector('.term-output-text').textContent = output;
            if (card.dataset.expanded !== 'false') existingOutput.style.display = 'block';
        } else {
            var outputDiv = document.createElement('div');
            outputDiv.className = 'term-output-body';
            outputDiv.id = outputId;
            outputDiv.style.display = card.dataset.expanded === 'false' ? 'none' : 'block';
            outputDiv.innerHTML = '<pre class="term-output-text">' + escapeHtml(output) + '</pre>';
            var footer = card.querySelector('.term-footer');
            if (footer) card.insertBefore(outputDiv, footer);
            else card.appendChild(outputDiv);
        }
    }
}

function openTerminalPanel(command) {
    if (command && command.trim()) {
        // Open terminal AND send the command to it
        if (window.bridge && bridge.on_run_in_terminal) {
            bridge.on_run_in_terminal(command);
        } else if (window.bridge && bridge.on_open_terminal) {
            bridge.on_open_terminal();
        } else if (window.showTerminal) {
            window.showTerminal();
        }
        // Show notification above the input box
        _showTerminalSentNotification(command);
    } else {
        // Just open terminal panel
        if (window.bridge && bridge.on_open_terminal) {
            bridge.on_open_terminal();
        } else if (window.showTerminal) {
            window.showTerminal();
        }
    }
}

// Show a small notification bar above the chat input when a command
// is sent to the terminal via "View in terminal".
var _termNotifyTimer = null;
function _showTerminalSentNotification(command) {
    var el = document.getElementById('terminal-notify');
    if (!el) return;

    // Truncate for display
    var displayCmd = command.length > 60 ? command.slice(0, 57) + '...' : command;

    el.innerHTML =
        '<svg class="tn-icon" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">'
            + '<polyline points="15 3 21 3 21 9"/>'
            + '<path d="M21 3L9 15"/>'
            + '<polyline points="9 21 3 21 3 15"/>'
        + '</svg>'
        + '<span>Sent to terminal:&nbsp;</span>'
        + '<span class="tn-cmd">' + escapeHtml(displayCmd) + '</span>'
        + '<button class="tn-dismiss" onclick="_dismissTerminalNotify()" title="Dismiss">&times;</button>';

    el.style.display = 'flex';

    // Auto-dismiss after 4 seconds
    if (_termNotifyTimer) clearTimeout(_termNotifyTimer);
    _termNotifyTimer = setTimeout(_dismissTerminalNotify, 4000);
}

function _dismissTerminalNotify() {
    var el = document.getElementById('terminal-notify');
    if (el) el.style.display = 'none';
    if (_termNotifyTimer) { clearTimeout(_termNotifyTimer); _termNotifyTimer = null; }
}

// ─────────────────────────────────────────────────────────────────
// DANGEROUS-COMMAND PERMISSION CARD
// Shown in the chat when the AI agent wants to run a destructive
// command (rm -rf, git reset --hard, etc.).
// ─────────────────────────────────────────────────────────────────

var _currentPermissionCardId = null;

/**
 * Called from Python (via runJavaScript) when the agent is about to
 * run a dangerous command and needs user approval.
 *
 * @param {string} command     The full command string
 * @param {string} warning     Human-readable risk note
 * @param {Array}  files       Array of affected path strings
 */
window.showPermissionCard = function(command, warning, files) {
    if (!Array.isArray(files)) {
        try { files = JSON.parse(files); } catch(e) { files = []; }
    }

    var cardId = 'perm-card-' + Date.now();
    _currentPermissionCardId = cardId;

    // Determine operation type from command for display label
    var opType = 'MODIFY';
    var cmdLower = command.toLowerCase();
    if (/\brm\b|\bdel\b|Remove-Item|rmdir/i.test(command))  opType = 'DELETE';
    else if (/\bgit\s+reset|git\s+clean|git\s+push.*force/i.test(command)) opType = 'GIT';
    else if (/\bdrop\b|\btruncate\b/i.test(command))         opType = 'DROP';

    // Build file rows
    var fileRowsHtml = '';
    if (files && files.length) {
        files.forEach(function(f) {
            var name = f.split(/[\/\\]/).pop() || f;
            fileRowsHtml +=
                '<div class="perm-file-row">'
                    + '<svg class="perm-file-icon" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">'
                        + '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>'
                        + '<polyline points="14 2 14 8 20 8"/>'
                    + '</svg>'
                    + '<span class="perm-file-name">' + escapeHtml(name) + '</span>'
                    + '<span class="perm-file-badge perm-badge-' + opType.toLowerCase() + '">'
                        + opType
                    + '</span>'
                + '</div>';
        });
    }

    // Build card HTML (matches screenshot design)
    var shortCmd = command.length > 70 ? command.slice(0, 67) + '...' : command;
    var html =
        '<div class="perm-card" id="' + cardId + '">'
            + '<div class="perm-header">'
                + '<svg class="perm-icon" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">'
                    + '<polyline points="3 6 5 6 21 6"/>'
                    + '<path d="M19 6l-1 14H6L5 6"/>'
                    + '<path d="M10 11v6"/><path d="M14 11v6"/>'
                    + '<path d="M9 6V4h6v2"/>'
                + '</svg>'
                + '<span class="perm-question">' + escapeHtml(_permissionLabel(command)) + '</span>'
                + '<div class="perm-btns">'
                    + '<button class="perm-btn perm-reject" onclick="respondPermission(\'' + cardId + '\', \'reject\')">Reject</button>'
                    + '<button class="perm-btn perm-accept" onclick="respondPermission(\'' + cardId + '\', \'accept\')">Accept</button>'
                + '</div>'
            + '</div>'
            + (fileRowsHtml ? '<div class="perm-files">' + fileRowsHtml + '</div>' : '')
            + '<div class="perm-warning">' + escapeHtml(warning) + '</div>'
        + '</div>';

    // Inject as an AI message
    var messages = document.getElementById('chatMessages');
    if (messages) {
        var wrapper = document.createElement('div');
        wrapper.className = 'message-bubble assistant';
        wrapper.innerHTML = html;
        messages.appendChild(wrapper);
        messages.scrollTop = messages.scrollHeight;
    }
};

/** Convert a command string into a brief question label. */
function _permissionLabel(cmd) {
    if (/\brm\b|\bdel\b|Remove-Item|rmdir/i.test(cmd))       return 'Delete files?';
    if (/git\s+reset\s+--hard/i.test(cmd))                    return 'Discard uncommitted changes?';
    if (/git\s+push.*--force/i.test(cmd))                     return 'Force-push (may overwrite remote)?';
    if (/git\s+clean/i.test(cmd))                             return 'Remove untracked files?';
    if (/\b(DROP|TRUNCATE)\s+(TABLE|DATABASE)/i.test(cmd))    return 'Drop database objects?';
    return 'Run potentially dangerous command?';
}

/**
 * Called by the Accept / Reject buttons on the permission card.
 * Hides the card and notifies Python.
 */
function respondPermission(cardId, decision) {
    var card = document.getElementById(cardId);
    if (card) {
        // Disable buttons to prevent double-click
        card.querySelectorAll('.perm-btn').forEach(function(b) { b.disabled = true; });

        // Update visual state
        var isAccept = (decision === 'accept');
        var label = card.querySelector('.perm-question');
        if (label) {
            label.textContent = isAccept ? '\u2713 Accepted' : '\u2715 Rejected';
        }
        var btnsEl = card.querySelector('.perm-btns');
        if (btnsEl) btnsEl.style.display = 'none';
        card.classList.add(isAccept ? 'perm-accepted' : 'perm-rejected');
    }

    // Notify Python bridge
    if (window.bridge && bridge.on_permission_respond) {
        bridge.on_permission_respond(decision);
    }
}

window.setTerminalOutput = function(cardId, output, exitCode) {
    var status = exitCode === 0 ? 'success' : 'error';
    updateTerminalCard(cardId, status, exitCode, output);
};

// --------------------------------------------------------------
// FEATURE 3 - TODO PANEL
// --------------------------------------------------------------

function updateTodos(todos, mainTask) {
    var section   = document.getElementById('todo-section');
    var list      = document.getElementById('todo-list');
    var countEl   = document.getElementById('todo-progress-count');
    var previewEl = document.getElementById('todo-preview-text');

    if (!section || !list) return;

    // If empty todos received, don't clear existing ones - persist until completed
    if (!todos || todos.length === 0) {
        // Only hide if there are no existing todos
        if (!currentTodoList || currentTodoList.length === 0) {
            section.style.display = 'none';
            list.innerHTML = '';
            _todoExpanded = false;
        }
        return;
    }

    // Merge new todos with existing ones (avoid duplicates by id)
    if (!currentTodoList) currentTodoList = [];
    var existingIds = new Set(currentTodoList.map(function(t) { return t.id; }));
    var newTodos = todos.filter(function(t) { return !existingIds.has(t.id); });
    
    // Update status and text of existing todos if changed
    todos.forEach(function(todo) {
        var existing = currentTodoList.find(function(t) { return t.id === todo.id; });
        if (existing) {
            existing.status = todo.status;
            existing.content = todo.content;
            if (todo.activeForm) existing.activeForm = todo.activeForm;
        }
    });
    
    // Add new todos
    currentTodoList = currentTodoList.concat(newTodos);

    section.style.display = 'flex';

    // Calculate stats from currentTodoList (merged list)
    var total     = currentTodoList.length;
    var completed = currentTodoList.filter(function(t) { return t.status === 'COMPLETE'; }).length;
    if (countEl) countEl.textContent = completed + '/' + total;

    // Preview: prefer the currently-active item's activeForm, then first non-done
    if (previewEl) {
        var activeItem  = currentTodoList.find(function(t) { return t.status === 'IN_PROGRESS'; });
        var firstPending = currentTodoList.find(function(t) {
            return t.status !== 'COMPLETE' && t.status !== 'CANCELLED';
        });
        var previewItem = activeItem || firstPending || currentTodoList[0];
        var previewText = (previewItem.status === 'IN_PROGRESS' && previewItem.activeForm)
            ? previewItem.activeForm
            : previewItem.content;
        previewEl.textContent = previewText;
    }

    list.innerHTML = '';
    currentTodoList.forEach(function(todo) {
        var item = document.createElement('div');
        // COMPLETE → todo-complete, IN_PROGRESS → todo-inprogress, PENDING → todo-pending
        var statusCls = 'todo-' + todo.status.toLowerCase().replace(/_/g, '');
        item.className = 'todo-item ' + statusCls;
        item.dataset.id = todo.id;

        // Show activeForm (present-continuous) while the task is in-progress
        var displayText = (todo.status === 'IN_PROGRESS' && todo.activeForm)
            ? todo.activeForm
            : todo.content;

        var iconHtml = buildTodoIcon(todo.status);
        item.innerHTML = iconHtml +
            '<span class="todo-text">' + escapeHtml(displayText) + '</span>';

        list.appendChild(item);
    });
}

function buildTodoIcon(status) {
    switch (status) {
        case 'COMPLETE':
            return '<div class="todo-icon todo-icon-done">' +
                '<svg width="8" height="8" viewBox="0 0 24 24" fill="none" ' +
                    'stroke="currentColor" stroke-width="3.5">' +
                    '<polyline points="20 6 9 17 4 12"/>' +
                '</svg></div>';
        case 'IN_PROGRESS':
            // Spinning circle animation (CSS handles the animation)
            return '<div class="todo-icon todo-icon-progress"></div>';
        case 'CANCELLED':
            return '<div class="todo-icon todo-icon-cancelled">' +
                '<svg width="8" height="8" viewBox="0 0 24 24" fill="none" ' +
                    'stroke="currentColor" stroke-width="3">' +
                    '<line x1="18" y1="6" x2="6" y2="18"/>' +
                    '<line x1="6" y1="6" x2="18" y2="18"/>' +
                '</svg></div>';
        default:
            return '<div class="todo-icon todo-icon-pending"></div>';
    }
}

function toggleTodoSection() {
    _todoExpanded = !_todoExpanded;
    var section = document.getElementById('todo-section');
    var body    = document.getElementById('todo-body');
    if (section) section.classList.toggle('expanded', _todoExpanded);
    if (body)    body.style.display = _todoExpanded ? 'block' : 'none';
}

window.updateTodos = updateTodos;
window.toggleTodoSection = toggleTodoSection;

// --------------------------------------------------------------
// FEATURE 4 - MESSAGE QUEUE SYSTEM
// --------------------------------------------------------------

function _sendNow(text) {
    _isGenerating = true;
    
    // Check if there are attached images
    var hasImages = _attachedImages.length > 0;
    
    // Store images data before clearing
    var imageData = '';
    if (hasImages) {
        imageData = JSON.stringify(_attachedImages);
        // Clear attached images
        _attachedImages = [];
        var preview = document.getElementById('image-attachment-preview');
        if (preview) preview.remove();
    }

    appendMessage(text, 'user', true);

    showThinkingIndicator();

    var sendBtn = document.getElementById('sendBtn');
    var stopBtn = document.getElementById('stopBtn');
    if (sendBtn) sendBtn.style.display = 'none';
    if (stopBtn) stopBtn.style.display = 'flex';

    // Remember last user message for retry
    _lastUserMessage = text;
    _lastUserHasImages = hasImages;
    _lastUserImageData = imageData;

    // Send message with image data if present
    if (hasImages) {
        bridge.on_message_with_images(text, imageData);
    } else {
        bridge.on_message_submitted(text);
    }
}

function _enqueueMessage(text) {
    var id = ++_queueIdSeq;
    _msgQueue.push({ id: id, text: text, timestamp: Date.now() });
    _renderQueueBar();
}

function _onGenerationComplete() {
    _isGenerating = false;

    if (_msgQueue.length > 0) {
        var next = _msgQueue.shift();
        _renderQueueBar();
        setTimeout(function() {
            _sendNow(next.text);
        }, 150);
    } else {
        var sendBtn = document.getElementById('sendBtn');
        var stopBtn = document.getElementById('stopBtn');
        if (sendBtn) sendBtn.style.display = 'flex';
        if (stopBtn) stopBtn.style.display = 'none';
    }
}

function _renderQueueBar() {
    var bar     = document.getElementById('msg-queue-bar');
    var listEl  = document.getElementById('mq-list');
    var countEl = document.getElementById('mq-count');

    if (!bar || !listEl) return;

    if (_msgQueue.length === 0) {
        bar.style.display = 'none';
        return;
    }

    bar.style.display = 'flex';
    if (countEl) countEl.textContent = _msgQueue.length;

    listEl.innerHTML = '';
    _msgQueue.forEach(function(msg) {
        var item = document.createElement('div');
        item.className = 'mq-item';
        item.dataset.id = msg.id;

        var preview = msg.text.length > 60
            ? msg.text.slice(0, 60) + '...'
            : msg.text;

        // Card with icon, text, and remove button - no serial numbers
        item.innerHTML =
            '<svg class="message-icon" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">' +
                '<path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"></path>' +
            '</svg>' +
            '<span class="mq-text">' + escapeHtml(preview) + '</span>' +
            '<button class="mq-remove" onclick="_removeFromQueue(' + msg.id + ')" ' +
                    'title="Remove from queue">×</button>';

        listEl.appendChild(item);
    });
}

function _removeFromQueue(id) {
    _msgQueue = _msgQueue.filter(function(m) { return m.id !== id; });
    _renderQueueBar();
}

function _clearQueue() {
    _msgQueue = [];
    _renderQueueBar();
}

window._removeFromQueue = _removeFromQueue;
window._clearQueue = _clearQueue;

// Indexing status bar functions
function showIndexingStatus(message, autoHide) {
    var bar = document.getElementById('indexing-bar');
    var text = document.getElementById('indexing-text');
    if (!bar || !text) return;
    
    text.textContent = message;
    bar.style.display = 'flex';
    bar.style.opacity = '1';
    
    if (autoHide) {
        clearTimeout(bar._hideTimer);
        bar._hideTimer = setTimeout(function() {
            bar.style.opacity = '0';
            setTimeout(function() {
                if (bar) bar.style.display = 'none';
                if (bar) bar.style.opacity = '1';
            }, 400);
        }, 3000);
    }
}

function hideIndexingStatus() {
    var bar = document.getElementById('indexing-bar');
    if (bar) bar.style.display = 'none';
}

window.showIndexingStatus = showIndexingStatus;
window.hideIndexingStatus = hideIndexingStatus;

// ================================================
// PERMISSION CARD SYSTEM (IN-CHAT) (NEW)
// ================================================

/**
 * Show permission card using NEW Cursor IDE card design
 * @param {string} toolName - Name of the tool requesting permission
 * @param {Object} details - Permission details {action, files, type}
 * @param {function} callback - Function to call with (approved) when user responds
 */
function showPermissionCard(toolName, details, callback) {
    console.log('[PERMISSION] Showing card for:', toolName);
    
    // Extract action and files from details
    var action = details.action || details.text || 'Permission required';
    var files = details.files || [];
    var cardId = 'permission-' + Date.now();
    
    // Create permission card using new card system
    var card = window.createPermissionCard(action, files, cardId);
    
    // Store callback for bridge communication
    card._permissionCallback = callback;
    
    // Override handlePermission to use our callback
    var originalHandlePermission = window.handlePermission;
    window.handlePermission = function(id, accepted) {
        if (id === cardId) {
            console.log('[PERMISSION] User response:', accepted ? 'ACCEPTED' : 'REJECTED');
            
            // Call the stored callback
            if (card._permissionCallback) {
                card._permissionCallback(accepted, false);
            }
            
            // Notify Python bridge
            if (window.bridge && window.bridge.on_permission_response) {
                window.bridge.on_permission_response({
                    id: id,
                    accepted: accepted,
                    tool: toolName
                });
            }
            
            // Use visual feedback from new design
            originalHandlePermission(id, accepted);
        }
    };
    
    // Append card to chat
    window.appendCardToChat(card);
}

// Expose to Python bridge
// NOTE: window.showPermissionCard is already set above (line ~7238) with the
// correct (command, warning, files) signature used by the Python bridge.
// DO NOT override it here.


// -- INTERACTIVE QUESTION SUPPORT (STOP-AND-WAIT PIPELINE) ----------

/**
 * Shows a premium interaction card in the chat for AI questions.
 * @param {Object} info - {id, text, type, choices, default}
 */
window.showQuestionCard = function(info) {
    console.log('[CHAT] showQuestionCard called:', info);
    var container = document.getElementById('chatMessages');
    if (!container) return;

    // Use Template for permissions if available (Cursor IDE Style)
    if (info.type === 'permission') {
        var template = document.getElementById('permission-card-template');
        if (template) {
            var card = template.content.cloneNode(true).querySelector('.permission-card');
            card.id = 'interaction-' + info.id;
            
            // Set tool name with icon
            var titleEl = card.querySelector('.tool-badge-name');
            if (titleEl) {
                var toolName = info.tool_name || 'Action Request';
                var toolIcon = 'TOOL';
                if (toolName.includes('write') || toolName.includes('edit')) toolIcon = 'EDIT';
                else if (toolName.includes('read')) toolIcon = 'READ';
                else if (toolName.includes('bash') || toolName.includes('command')) toolIcon = 'RUN';
                else if (toolName.includes('delete')) toolIcon = 'DEL';
                
                var iconEl = card.querySelector('.tool-badge-icon');
                if (iconEl) iconEl.textContent = toolIcon;
                titleEl.textContent = toolName;
            }
            
            // Set details content
            var detailsEl = card.querySelector('.details-content');
            if (detailsEl) detailsEl.innerHTML = info.details || '<span style="color: #6b7280;">No additional details</span>';
            
            // Handle Allow button
            var allowBtn = card.querySelector('.permission-btn-allow');
            if (allowBtn) {
                allowBtn.onclick = function() { 
                    console.log('[PERMISSION] Allow clicked for', info.id);
                    var rememberCheckbox = card.querySelector('.permission-remember-checkbox');
                    var remember = rememberCheckbox ? rememberCheckbox.checked : false;
                    console.log('[PERMISSION] Remember flag:', remember);
                    
                    // Store the remember choice
                    if (remember) {
                        window.permissionRemember[info.id] = true;
                    }
                    
                    // Set the scope and grant permission
                    window.permissionScopes[info.id] = card._selectedScope || 'session';
                    window.grantPermission(info.id, remember);
                };
            }
            
            // Handle Deny button
            var denyBtn = card.querySelector('.permission-btn-deny');
            if (denyBtn) {
                denyBtn.onclick = function() { 
                    console.log('[PERMISSION] Deny clicked for', info.id);
                    var rememberCheckbox = card.querySelector('.permission-remember-checkbox');
                    var remember = rememberCheckbox ? rememberCheckbox.checked : false;
                    
                    // Store the deny choice if remember is checked
                    if (remember) {
                        window.permissionRemember[info.id] = false;
                    }
                    
                    window.denyPermission(info.id);
                };
            }
            
            // Handle Always button
            var alwaysBtn = card.querySelector('.permission-btn-always');
            if (alwaysBtn) {
                alwaysBtn.onclick = function() { 
                    console.log('[PERMISSION] Always clicked for', info.id);
                    // Check the remember checkbox automatically when clicking Always
                    var checkbox = card.querySelector('.permission-remember-checkbox');
                    if (checkbox) checkbox.checked = true;
                    
                    // Store the "always" choice with remember=true
                    window.permissionRemember[info.id] = true;
                    window.permissionScopes[info.id] = 'global';
                    window.grantPermission(info.id, true);
                };
            }
            
            // Handle scope buttons
            var scopeButtons = card.querySelectorAll('.scope-btn');
            scopeButtons.forEach(function(btn) {
                btn.onclick = function() {
                    var scope = this.dataset.scope;
                    console.log('[PERMISSION] Scope selected:', scope);
                    card._selectedScope = scope;
                    // Update UI
                    scopeButtons.forEach(function(b) { b.classList.remove('active'); });
                    this.classList.add('active');
                };
            });
            // Set default scope
            card._selectedScope = 'session';
            
            // Handle Remember toggle - sync with localStorage
            var rememberCheckbox = card.querySelector('.permission-remember-checkbox');
            if (rememberCheckbox) {
                // Check if we should remember by default for this session
                var rememberEnabled = localStorage.getItem('cortex_permission_remember') === 'true';
                rememberCheckbox.checked = rememberEnabled;
                
                rememberCheckbox.onchange = function() {
                    localStorage.setItem('cortex_permission_remember', this.checked);
                    console.log('[CHAT] Permission remember setting:', this.checked);
                };
            }
            
            container.appendChild(card);
            // Use requestAnimationFrame for smooth scrolling (non-blocking)
            requestAnimationFrame(function() {
                container.scrollTop = container.scrollHeight;
                console.log('[CHAT] Professional permission card appended');
            });
            return;
        }
    }

    var card = document.createElement('div');
    card.className = 'interaction-card';
    card.id = 'interaction-' + info.id;

    var html = '<div class="interaction-header">' +
               '<span class="interaction-icon">?</span>' +
               '<span class="interaction-title">AI Question</span>' +
               '</div>' +
               '<div class="interaction-body">' +
               '<p class="interaction-text">' + (info.text || "I have a question before I continue.") + '</p>';

    if (info.type === 'confirm') {
        html += '<div class="interaction-actions">' +
                '<button class="interaction-btn deny" onclick="submitInteractionAnswer(\'' + info.id + '\', \'no\')">No</button>' +
                '<button class="interaction-btn approve" onclick="submitInteractionAnswer(\'' + info.id + '\', \'yes\')">Yes</button>' +
                '</div>';
    } else if (info.type === 'permission') {
        html += '<div class="interaction-permission-details">' + (info.details || "") + '</div>' +
                '<div class="interaction-actions permission-grid">' +
                '<button class="interaction-btn secondary" onclick="submitInteractionAnswer(\'' + info.id + '\', \'deny\')">Deny</button>' +
                '<button class="interaction-btn primary" onclick="submitInteractionAnswer(\'' + info.id + '\', \'allow\')">Allow</button>' +
                '<button class="interaction-btn ghost" onclick="submitInteractionAnswer(\'' + info.id + '\', \'always\')">Always</button>' +
                '</div>';
    } else if (info.type === 'choice' && info.choices && info.choices.length > 0) {
        html += '<div class="interaction-choices">';
        info.choices.forEach(function(choice) {
            html += '<button class="interaction-choice-btn" onclick="submitInteractionAnswer(\'' + info.id + '\', \'' + choice.replace(/'/g, "\\'") + '\')">' + choice + '</button>';
        });
        html += '</div>';
    } else {
        // Default text input
        html += '<div class="interaction-input-group">' +
                '<input type="text" id="input-' + info.id + '" class="interaction-input" placeholder="' + (info.default || 'Type your answer...') + '" />' +
                '<button class="interaction-submit-btn" onclick="submitInteractionByInput(\'' + info.id + '\')">Send</button>' +
                '</div>';
    }

    html += '</div>';
    card.innerHTML = html;
    container.appendChild(card);
    
    // FORCE scroll to bottom for interactions - high priority (non-blocking)
    requestAnimationFrame(function() {
        container.scrollTop = container.scrollHeight;
        console.log('[CHAT] Interaction card appended and scrolled to bottom');
    });

    // Focus input if it's a text type and handle Enter key (non-blocking)
    if (info.type !== 'confirm' && info.type !== 'choice' && info.type !== 'permission') {
        requestAnimationFrame(function() {
            var input = document.getElementById('input-' + info.id);
            if (input) {
                input.focus();
                input.onkeydown = function(e) {
                    if (e.key === 'Enter') {
                        submitInteractionByInput(info.id);
                    }
                };
            }
        });
    }
};

/**
 * Submits the answer back to the Python AIAgent.
 * @param {string} id - The interaction/permission ID
 * @param {string} answer - The answer (allow, deny, always, yes, no)
 * @param {string} scope - Optional scope (session, workspace, global)
 */
window.submitInteractionAnswer = function(id, answer, scope) {
    scope = scope || 'session';
    console.log('[CHAT] Submitting interaction answer:', id, answer, 'scope:', scope);
    var card = document.getElementById('interaction-' + id);
    if (card) {
        card.classList.add('answered');
        
        if (card.classList.contains('permission-card')) {
            // Professional card handling
            var actions = card.querySelector('.permission-card-actions');
            var remember = card.querySelector('.permission-card-remember');
            var details = card.querySelector('.permission-card-details');
            
            if (actions) actions.style.display = 'none';
            if (remember) remember.style.display = 'none';
            
            // Create compact status indicator
            var isApproved = answer === 'allow' || answer === 'always' || answer === 'yes';
            var statusText = isApproved ? (answer === 'always' ? '? Always' : '? Allowed') : '? Denied';
            var statusColor = isApproved ? '#22c55e' : '#ef4444';
            
            var statusDiv = document.createElement('div');
            statusDiv.className = 'permission-status';
            statusDiv.style.cssText = 'text-align: center; padding: 8px; color: ' + statusColor + '; font-size: 12px; font-weight: 500;';
            statusDiv.textContent = statusText;
            
            var body = card.querySelector('.permission-card-body');
            if (body) body.appendChild(statusDiv);
            
            // Store approval in localStorage if "always"
            if (answer === 'always') {
                localStorage.setItem('cortex_permission_always_' + id, 'true');
                console.log('[CHAT] Permission set to always for:', id);
            }
        } else {
            // Standard card handling
            var answeredContainer = card.querySelector('.interaction-answered') || card;
            card.innerHTML = '<div class="interaction-answered">' +
                             '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3"><polyline points="20 6 9 17 4 12"></polyline></svg>' +
                             ' Answered: ' + answer + '</div>';
        }
    }
    
    if (window.bridge && typeof window.bridge.on_answer_question === 'function') {
        // Include scope in the answer for permission requests
        var answerWithScope = answer;
        if (scope && scope !== 'session') {
            answerWithScope = answer + ':' + scope;
        }
        window.bridge.on_answer_question(id, answerWithScope);
    } else {
        console.error('[CHAT] Bridge not ready to send interaction answer');
    }
};

/**
 * Helper to submit answer from a text input field.
 */
window.submitInteractionByInput = function(id) {
    var input = document.getElementById('input-' + id);
    var answer = input ? input.value : '';
    // If empty but has a default (placeholder), use it
    if (!answer && input && input.placeholder !== 'Type your answer...') {
        answer = input.placeholder;
    }
    if (!answer) answer = ""; // Ensure not null
    window.submitInteractionAnswer(id, answer);
};

// ============================================================================
// OpenCode Enhancement - Permission Card Support
// ============================================================================

/**
 * Global storage for permission scopes
 */
window.permissionScopes = {};

/**
 * Global storage for permission remember choices
 */
window.permissionRemember = {};

/**
 * Display a permission card in the chat
 * @param {string} requestId - The permission request ID
 * @param {string} html - The HTML content of the permission card
 */
window._showPermissionCardLegacy = function(requestId, html) {
    console.log('[Permission] Showing permission card:', requestId);
    
    // Create message container
    var messageDiv = document.createElement('div');
    messageDiv.className = 'message permission-message';
    messageDiv.id = 'perm-message-' + requestId;
    
    // Create bubble
    var bubble = document.createElement('div');
    bubble.className = 'message-bubble permission';
    bubble.innerHTML = html;
    
    messageDiv.appendChild(bubble);
    
    // Add to chat
    var chatContainer = document.getElementById('chatMessages');
    if (chatContainer) {
        chatContainer.appendChild(messageDiv);
        chatContainer.scrollTop = chatContainer.scrollHeight;
    }
    
    // Initialize scope and remember storage
    window.permissionScopes[requestId] = 'session';
    window.permissionRemember[requestId] = false;
    
    // Setup scope button handlers
    // Setup permission card immediately - no delay
    var card = document.getElementById('perm-card-' + requestId) || messageDiv.querySelector('.permission-card');
    if (card) {
        card.id = 'perm-card-' + requestId;
        
        // Use event delegation for better performance
        card.addEventListener('click', function(e) {
            // Find closest button element (handles clicks on child elements)
            var target = e.target.closest('.scope-btn');
            if (target) {
                var selectedScope = target.dataset.scope;
                window.selectScope(requestId, selectedScope);
                return;
            }
            
            // Handle action button clicks - check allow FIRST before deny/always
            target = e.target.closest('.permission-btn-allow');
            if (target) {
                console.log('ALLOW BUTTON CLICKED!');
                var scope = window.permissionScopes[requestId] || 'session';
                var remember = window.permissionRemember[requestId] || false;
                window.grantPermission(requestId, remember);
                return;
            }
            
            target = e.target.closest('.permission-btn-deny');
            if (target) {
                window.denyPermission(requestId);
                return;
            }
            
            target = e.target.closest('.permission-btn-always');
            if (target) {
                window.permissionScopes[requestId] = 'global';
                var rememberCheck = card.querySelector('.permission-remember-checkbox');
                if (rememberCheck) rememberCheck.checked = true;
                window.permissionRemember[requestId] = true;
                window.grantPermission(requestId, true);
                return;
            }
            
            // Handle remember toggle click
            target = e.target.closest('.remember-toggle') || e.target.closest('.remember-label');
            if (target) {
                var rememberCheck = card.querySelector('.permission-remember-checkbox');
                if (rememberCheck) {
                    rememberCheck.checked = !rememberCheck.checked;
                    window.permissionRemember[requestId] = rememberCheck.checked;
                }
                return;
            }
        });
    }
};

/**
 * Select permission scope (Session/Workspace/Global)
 * @param {string} requestId - The permission request ID
 * @param {string} scope - The selected scope
 */
window.selectScope = function(requestId, scope) {
    console.log('[Permission] Selected scope:', scope, 'for request:', requestId);
    
    // Store selection
    window.permissionScopes[requestId] = scope;
    
    // Update UI
    var card = document.getElementById('perm-card-' + requestId);
    if (card) {
        var buttons = card.querySelectorAll('.scope-btn');
        buttons.forEach(function(btn) {
            btn.classList.remove('active');
            if (btn.dataset.scope === scope) {
                btn.classList.add('active');
            }
        });
    }
};

/**
 * Grant permission
 * @param {string} requestId - The permission request ID
 * @param {boolean} remember - Whether to remember this choice
 */
window.grantPermission = function(requestId, remember) {
    console.log('[Permission] Granting permission:', requestId, 'remember:', remember);
    
    var scope = window.permissionScopes[requestId] || 'session';
    remember = remember || window.permissionRemember[requestId] || false;
    
    // Send to Python with remember flag
    if (window.bridge && typeof window.bridge.on_permission_card_response === 'function') {
        window.bridge.on_permission_card_response(requestId, true, scope, remember);
    }
    
    // Update UI
    window.disablePermissionCard(requestId, 'Granted ?');
};

/**
 * Grant limited permission (read-only)
 * @param {string} requestId - The permission request ID
 */
window.grantLimited = function(requestId) {
    console.log('[Permission] Granting limited permission:', requestId);
    
    // Send to Python with limited scope
    if (window.bridge && typeof window.bridge.on_permission_card_response === 'function') {
        window.bridge.on_permission_card_response(requestId, true, 'limited', false);
    }
    
    // Update UI
    window.disablePermissionCard(requestId, 'Limited Access ?');
};

/**
 * Deny permission
 * @param {string} requestId - The permission request ID
 */
window.denyPermission = function(requestId) {
    console.log('[Permission] Denying permission:', requestId);
    
    // Send to Python
    if (window.bridge && typeof window.bridge.on_permission_card_response === 'function') {
        window.bridge.on_permission_card_response(requestId, false, 'denied', false);
    }
    
    // Update UI
    window.disablePermissionCard(requestId, 'Denied ?');
};

/**
 * Disable permission card after response
 * @param {string} requestId - The permission request ID
 * @param {string} statusText - Status text to display
 */
window.disablePermissionCard = function(requestId, statusText) {
    var card = document.getElementById('perm-card-' + requestId);
    if (card) {
        // Disable all buttons
        var buttons = card.querySelectorAll('button');
        buttons.forEach(function(btn) {
            btn.disabled = true;
            btn.style.opacity = '0.5';
        });
        
        // Add status indicator
        var statusDiv = document.createElement('div');
        statusDiv.className = 'permission-status';
        statusDiv.textContent = statusText;
        statusDiv.style.cssText = 'text-align: center; padding: 8px; margin-top: 8px; font-weight: bold;';
        
        if (statusText.includes('Granted')) {
            statusDiv.style.color = '#10b981';
        } else if (statusText.includes('Denied')) {
            statusDiv.style.color = '#ef4444';
        }
        
        card.appendChild(statusDiv);
        
        // Fade the card
        card.style.opacity = '0.7';
    }
};

/**
 * Create a tool execution card
 * @param {string} toolName - Name of the tool
 * @param {Object} params - Tool parameters
 * @param {string} status - Tool status (pending, executing, completed, failed)
 */
window.createToolCard = function(toolName, params, status) {
    var cardId = 'tool-' + Date.now();
    
    var card = document.createElement('div');
    card.className = 'tool-card';
    card.id = cardId;
    
    var statusClass = status || 'pending';
    var statusText = status ? status.charAt(0).toUpperCase() + status.slice(1) : 'Pending';
    
    card.innerHTML = `
        <div class="tool-header">
            <span class="tool-icon">TOOL</span>
            <span class="tool-name">${toolName}</span>
            <span class="tool-status ${statusClass}">${statusText}</span>
        </div>
        <div class="tool-progress">
            <div class="tool-progress-bar" style="width: ${status === 'completed' ? '100%' : '0%'}"></div>
        </div>
        <div class="tool-params">${JSON.stringify(params, null, 2)}</div>
    `;
    
    return { card: card, id: cardId };
};

/**
 * Update tool card status
 * @param {string} cardId - The tool card ID
 * @param {string} status - New status
 * @param {string} result - Optional result text
 */
window.updateToolCard = function(cardId, status, result) {
    var card = document.getElementById(cardId);
    if (!card) return;
    
    var statusEl = card.querySelector('.tool-status');
    var progressBar = card.querySelector('.tool-progress-bar');
    
    if (statusEl) {
        statusEl.className = 'tool-status ' + status;
        statusEl.textContent = status.charAt(0).toUpperCase() + status.slice(1);
    }
    
    if (progressBar) {
        progressBar.style.width = status === 'completed' ? '100%' : 
                                  status === 'failed' ? '0%' : '50%';
    }
    
    if (result) {
        var resultDiv = document.createElement('div');
        resultDiv.className = 'tool-result ' + (status === 'failed' ? 'error' : 'success');
        resultDiv.textContent = result;
        card.appendChild(resultDiv);
    }
};

// ============================================================================
// OpenCode Enhancement - Quick Actions
// ============================================================================

/**
 * Initialize quick action buttons
 */
window.initQuickActions = function() {
    var container = document.getElementById('quickActions');
    if (!container) return;
    
    var actions = [
        { id: 'explain', icon: 'EXP', label: 'Explain Code' },
        { id: 'fix', icon: 'FIX', label: 'Fix Issues' },
        { id: 'optimize', icon: 'OPT', label: 'Optimize' },
        { id: 'test', icon: 'TEST', label: 'Generate Tests' },
        { id: 'document', icon: 'DOC', label: 'Add Docs' }
    ];
    
    actions.forEach(function(action) {
        var btn = document.createElement('button');
        btn.className = 'quick-action-btn';
        btn.innerHTML = `<span>${action.icon}</span> ${action.label}`;
        btn.onclick = function() {
            window.handleQuickAction(action.id);
        };
        container.appendChild(btn);
    });
};

/**
 * Handle quick action button click
 * @param {string} actionId - The action ID
 */
window.handleQuickAction = function(actionId) {
    var prompts = {
        'explain': 'Explain this code to me:',
        'fix': 'Fix any issues in this code:',
        'optimize': 'Optimize this code for better performance:',
        'test': 'Generate unit tests for this code:',
        'document': 'Add documentation to this code:'
    };
    
    var input = document.getElementById('messageInput');
    if (input) {
        input.value = prompts[actionId] || '';
        input.focus();
    }
};

// Initialize quick actions when DOM is ready
document.addEventListener('DOMContentLoaded', function() {
    window.initQuickActions();
});

// -- TESTING WORKFLOW UI SUPPORT -------------------------------------

/**
 * Shows a testing status card in the chat.
 * @param {Object} info - {decision, priority, trigger, scope, tools}
 */
function showTestingCard(info) {
    console.log('[TESTING] Showing card:', info);
    
    var chatMessages = document.getElementById('chatMessages');
    if (!chatMessages) {
        console.error('[TESTING] Chat messages container not found!');
        return;
    }
    
    // Create testing card
    var card = document.createElement('div');
    card.className = 'testing-card';
    card.id = 'testing-card-' + Date.now();
    
    var priorityColor = {
        'high': '#ef4444',
        'medium': '#f59e0b',
        'low': '#10b981'
    }[info.priority] || '#6b7280';
    
    card.innerHTML = `
        <div class="testing-card-header">
            <span class="testing-icon">TEST</span>
            <span class="testing-title">Testing Mode</span>
            <span class="testing-priority" style="background: ${priorityColor}20; color: ${priorityColor};">
                ${info.priority?.toUpperCase() || 'MEDIUM'}
            </span>
        </div>
        <div class="testing-card-body">
            <div class="testing-info">
                <div><strong>Decision:</strong> ${info.decision === 'write_tests' ? 'Write Tests' : info.decision}</div>
                <div><strong>Trigger:</strong> ${info.trigger || 'Unknown'}</div>
                <div><strong>Scope:</strong> ${info.scope || 'Basic'}</div>
            </div>
            ${info.tools ? `
            <div class="testing-tools">
                <strong>Test Tools:</strong>
                <div class="tool-tags">
                    ${info.tools.map(tool => `<span class="tool-tag">${tool}</span>`).join('')}
                </div>
            </div>
            ` : ''}
        </div>
    `;
    
    chatMessages.appendChild(card);
    chatMessages.scrollTop = chatMessages.scrollHeight;
}

/**
 * Shows test results in the chat.
 * @param {Object} results - {all_passed, passed_count, failed_count, failures}
 */
function showTestResults(results) {
    console.log('[TESTING] Showing results:', results);
    
    var chatMessages = document.getElementById('chatMessages');
    if (!chatMessages) {
        console.error('[TESTING] Chat messages container not found!');
        return;
    }
    
    var statusIcon = results.all_passed ? 'PASS' : 'WARN';
    var statusColor = results.all_passed ? '#10b981' : '#f59e0b';
    var statusText = results.all_passed ? 'All Tests Passed!' : 'Tests Completed';
    
    var card = document.createElement('div');
    card.className = 'test-results-card';
    card.style.cssText = `
        background: rgba(255, 255, 255, 0.05);
        border: 1px solid ${statusColor}40;
        border-radius: 8px;
        padding: 12px;
        margin: 8px 0;
    `;
    
    card.innerHTML = `
        <div style="display: flex; align-items: center; gap: 8px; margin-bottom: 8px;">
            <span style="font-size: 20px;">${statusIcon}</span>
            <span style="font-weight: 600; color: ${statusColor};">${statusText}</span>
        </div>
        <div style="display: flex; gap: 16px; font-size: 13px;">
            <span style="color: #10b981;">PASS ${results.passed_count || 0} passed</span>
            ${results.failed_count > 0 ? `<span style="color: #ef4444;">FAIL ${results.failed_count} failed</span>` : ''}
        </div>
        ${results.failures && results.failures.length > 0 ? `
        <div style="margin-top: 8px; padding-top: 8px; border-top: 1px solid rgba(255,255,255,0.1);">
            <div style="font-size: 12px; color: #888; margin-bottom: 4px;">Failures:</div>
            ${results.failures.slice(0, 3).map(f => `
                <div style="font-size: 12px; color: #ef4444; margin: 2px 0;">
                    - ${f.name}${f.error ? `: ${f.error.substring(0, 50)}...` : ''}
                </div>
            `).join('')}
            ${results.failures.length > 3 ? `<div style="font-size: 11px; color: #666;">... and ${results.failures.length - 3} more</div>` : ''}
        </div>
        ` : ''}
    `;
    
    chatMessages.appendChild(card);
    chatMessages.scrollTop = chatMessages.scrollHeight;
}

// Expose to Python bridge
window.showTestingCard = showTestingCard;
window.showTestResults = showTestResults;

// ============================================================================
// CODE COMPLETION SYSTEM - OpenCode Style Integration
// ============================================================================

/**
 * Code Completion State
 */
window.codeCompletionState = {
    isVisible: false,
    completions: [],
    selectedIndex: 0,
    currentRequestId: null,
    debounceTimer: null
};

/**
 * Show code completion popup with suggestions
 * @param {Array} completions - Array of completion objects
 * @param {string} requestId - Unique request ID
 */
window.showCodeCompletionPopup = function(completions, requestId) {
    console.log('[CodeCompletion] Showing popup with', completions.length, 'suggestions');
    
    var popup = document.getElementById('code-completion-popup');
    var list = document.getElementById('completion-list');
    var counter = document.getElementById('completion-counter');
    var preview = document.getElementById('completion-preview');
    var actions = document.getElementById('completion-actions');
    
    if (!popup || !list) {
        console.error('[CodeCompletion] Popup elements not found');
        return;
    }
    
    // Store state
    window.codeCompletionState.completions = completions;
    window.codeCompletionState.selectedIndex = 0;
    window.codeCompletionState.currentRequestId = requestId;
    window.codeCompletionState.isVisible = true;
    
    // Update counter
    counter.textContent = completions.length + ' suggestion' + (completions.length !== 1 ? 's' : '');
    
    // Render completion items
    list.innerHTML = '';
    completions.forEach(function(completion, index) {
        var item = createCompletionItem(completion, index);
        list.appendChild(item);
    });
    
    // Show first preview
    if (completions.length > 0) {
        showCompletionPreview(completions[0]);
        preview.style.display = 'block';
        actions.style.display = 'flex';
    }
    
    // Position popup
    positionCompletionPopup();
    
    // Show popup
    popup.classList.add('visible');
    
    // Select first item
    updateCompletionSelection(0);
};

/**
 * Create a completion item element
 */
function createCompletionItem(completion, index) {
    var item = document.createElement('div');
    item.className = 'completion-item';
    item.dataset.index = index;
    
    // Determine icon based on strategy
    var icon = 'AUTO';
    var typeClass = '';
    if (completion.strategy === 'pattern') {
        icon = 'AI';
        typeClass = 'pattern';
    } else if (completion.strategy === 'ai') {
        icon = 'TPL';
        typeClass = 'ai';
    } else if (completion.strategy === 'syntax') {
        icon = 'SYN';
        typeClass = 'syntax';
    } else if (completion.strategy === 'template') {
        icon = 'FILE';
        typeClass = 'template';
    }
    
    item.classList.add(typeClass);
    
    // Confidence color
    var confidenceClass = completion.confidence >= 0.8 ? '' : 'low';
    
    item.innerHTML = `
        <div class="completion-icon">${icon}</div>
        <div class="completion-content">
            <div class="completion-label">${escapeHtml(completion.label || 'Completion')}</div>
            <div class="completion-description">${escapeHtml(completion.description || '')}</div>
        </div>
        <div class="completion-confidence ${confidenceClass}">
            ${Math.round((completion.confidence || 0) * 100)}%
        </div>
    `;
    
    // Click handler
    item.addEventListener('click', function() {
        selectCompletion(index);
    });
    
    return item;
}

/**
 * Show completion preview
 */
function showCompletionPreview(completion) {
    var preview = document.getElementById('completion-preview');
    if (!preview || !completion.preview) return;
    
    preview.textContent = completion.preview;
}

/**
 * Update selected completion
 */
function updateCompletionSelection(index) {
    var items = document.querySelectorAll('.completion-item');
    
    items.forEach(function(item, i) {
        item.classList.toggle('selected', i === index);
    });
    
    window.codeCompletionState.selectedIndex = index;
    
    // Update preview
    if (window.codeCompletionState.completions[index]) {
        showCompletionPreview(window.codeCompletionState.completions[index]);
    }
    
    // Scroll into view
    var selectedItem = items[index];
    if (selectedItem) {
        selectedItem.scrollIntoView({ block: 'nearest' });
    }
}

/**
 * Select a completion by index
 */
function selectCompletion(index) {
    updateCompletionSelection(index);
    
    var completion = window.codeCompletionState.completions[index];
    if (completion && window.bridge) {
        window.bridge.on_code_completion_selected({
            requestId: window.codeCompletionState.currentRequestId,
            index: index,
            completion: completion
        });
    }
}

/**
 * Accept the currently selected completion
 */
window.acceptCodeCompletion = function() {
    if (!window.codeCompletionState.isVisible) return;
    
    var index = window.codeCompletionState.selectedIndex;
    selectCompletion(index);
    hideCodeCompletionPopup();
};

/**
 * Dismiss the completion popup
 */
window.dismissCodeCompletion = function() {
    hideCodeCompletionPopup();
    
    if (window.bridge && window.codeCompletionState.currentRequestId) {
        window.bridge.on_code_completion_dismissed({
            requestId: window.codeCompletionState.currentRequestId
        });
    }
};

/**
 * Hide completion popup
 */
function hideCodeCompletionPopup() {
    var popup = document.getElementById('code-completion-popup');
    if (popup) {
        popup.classList.remove('visible');
    }
    
    window.codeCompletionState.isVisible = false;
    window.codeCompletionState.completions = [];
}

/**
 * Position completion popup near cursor
 */
function positionCompletionPopup() {
    var popup = document.getElementById('code-completion-popup');
    var input = document.getElementById('chatInput');
    
    if (!popup || !input) return;
    
    // Get input position
    var rect = input.getBoundingClientRect();
    
    // Position above input
    popup.style.left = rect.left + 'px';
    popup.style.top = (rect.top - popup.offsetHeight - 10) + 'px';
    popup.style.width = Math.min(500, rect.width) + 'px';
}

/**
 * Show code completion card in chat
 */
window.showCodeCompletionCard = function(completionData) {
    console.log('[CodeCompletion] Showing card:', completionData);
    
    var template = document.getElementById('code-completion-card-template');
    var container = document.getElementById('chatMessages');
    
    if (!template || !container) {
        console.error('[CodeCompletion] Template or container not found');
        return;
    }
    
    var card = template.content.cloneNode(true).querySelector('.code-completion-card');
    card.id = 'completion-card-' + completionData.requestId;
    
    // Set confidence badge
    var badge = card.querySelector('#completion-confidence-badge');
    if (badge) {
        badge.textContent = Math.round((completionData.confidence || 0.9) * 100) + '% confidence';
    }
    
    // Set explanation
    var explanation = card.querySelector('#completion-explanation');
    if (explanation) {
        explanation.textContent = completionData.explanation || 'Code completion available';
    }
    
    // Set diff content
    var diffContent = card.querySelector('#completion-diff-content');
    if (diffContent && completionData.diff) {
        diffContent.innerHTML = renderCompletionDiff(completionData.diff);
    }
    
    // Setup buttons
    var acceptBtn = card.querySelector('#card-accept-completion');
    var dismissBtn = card.querySelector('#card-dismiss-completion');
    
    if (acceptBtn) {
        acceptBtn.onclick = function() {
            if (window.bridge) {
                window.bridge.on_code_completion_accepted({
                    requestId: completionData.requestId,
                    completedCode: completionData.completedCode
                });
            }
            card.remove();
        };
    }
    
    if (dismissBtn) {
        dismissBtn.onclick = function() {
            card.remove();
        };
    }
    
    container.appendChild(card);
    container.scrollTop = container.scrollHeight;
};

/**
 * Render completion diff
 */
function renderCompletionDiff(diff) {
    if (!diff || !diff.lines) return '';
    
    return diff.lines.map(function(line) {
        var className = '';
        var prefix = ' ';
        
        if (line.type === 'added') {
            className = 'added';
            prefix = '+';
        } else if (line.type === 'removed') {
            className = 'removed';
            prefix = '-';
        }
        
        return `
            <div class="diff-line ${className}">
                <span class="diff-line-num">${prefix}</span>
                <span>${escapeHtml(line.content)}</span>
            </div>
        `;
    }).join('');
}

/**
 * Show completion indicator (loading state)
 */
window.showCompletionIndicator = function() {
    var indicator = document.getElementById('completion-indicator');
    if (indicator) {
        indicator.classList.add('visible');
    }
};

/**
 * Hide completion indicator
 */
window.hideCompletionIndicator = function() {
    var indicator = document.getElementById('completion-indicator');
    if (indicator) {
        indicator.classList.remove('visible');
    }
};

/**
 * Request code completion from Python
 */
window.requestCodeCompletion = function(code, language) {
    console.log('[CodeCompletion] Requesting completion for', language);
    
    if (window.bridge && typeof window.bridge.on_request_code_completion === 'function') {
        window.showCompletionIndicator();
        
        window.bridge.on_request_code_completion({
            code: code,
            language: language || 'python',
            cursorPosition: getInputCursorPosition(),
            timestamp: Date.now()
        });
    }
};

/**
 * Get cursor position in input
 */
function getInputCursorPosition() {
    var input = document.getElementById('chatInput');
    return input ? input.selectionStart : 0;
}

/**
 * Escape HTML special characters
 */
function escapeHtml(text) {
    if (!text) return '';
    var div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

/**
 * Setup keyboard shortcuts for code completion
 */
function setupCompletionKeyboardShortcuts() {
    document.addEventListener('keydown', function(e) {
        // Ctrl+Space or Cmd+Space to trigger completion
        if ((e.ctrlKey || e.metaKey) && e.code === 'Space') {
            e.preventDefault();
            var input = document.getElementById('chatInput');
            if (input) {
                window.requestCodeCompletion(input.value, 'python');
            }
            return;
        }
        
        // Handle completion popup navigation
        if (window.codeCompletionState.isVisible) {
            if (e.key === 'ArrowDown') {
                e.preventDefault();
                var nextIndex = (window.codeCompletionState.selectedIndex + 1) % window.codeCompletionState.completions.length;
                updateCompletionSelection(nextIndex);
            } else if (e.key === 'ArrowUp') {
                e.preventDefault();
                var prevIndex = window.codeCompletionState.selectedIndex - 1;
                if (prevIndex < 0) prevIndex = window.codeCompletionState.completions.length - 1;
                updateCompletionSelection(prevIndex);
            } else if (e.key === 'Enter') {
                e.preventDefault();
                window.acceptCodeCompletion();
            } else if (e.key === 'Escape') {
                e.preventDefault();
                window.dismissCodeCompletion();
            }
        }
    });
}

/**
 * Setup real-time completion
 */
function setupRealTimeCompletion() {
    var input = document.getElementById('chatInput');
    if (!input) return;
    
    input.addEventListener('input', function(e) {
        // Clear existing timer
        if (window.codeCompletionState.debounceTimer) {
            clearTimeout(window.codeCompletionState.debounceTimer);
        }
        
        // Debounce completion requests
        window.codeCompletionState.debounceTimer = setTimeout(function() {
            var code = input.value;
            
            // Only request completion if code looks incomplete
            if (shouldRequestCompletion(code)) {
                window.requestCodeCompletion(code, 'python');
            }
        }, 1000); // 1 second debounce
    });
}

/**
 * Check if we should request completion
 */
function shouldRequestCompletion(code) {
    if (!code || code.length < 10) return false;
    
    // Check for incomplete patterns
    var incompletePatterns = [
        /:\s*$/,  // Ends with colon (incomplete block)
        /def\s+\w+\s*\([^)]*\)\s*$/,  // Incomplete function
        /class\s+\w+\s*(:\s*)?$/,  // Incomplete class
        /try\s*:\s*$/,  // Incomplete try
        /if\s+.+:\s*$/,  // Incomplete if
        /for\s+.+:\s*$/,  // Incomplete for
        /while\s+.+:\s*$/,  // Incomplete while
        /#\s*TODO/i,  // Has TODO
        /pass\s*$/,  // Ends with pass
    ];
    
    var lines = code.split('\n');
    var lastLine = lines[lines.length - 1].trim();
    
    return incompletePatterns.some(function(pattern) {
        return pattern.test(lastLine);
    });
}

// Initialize code completion system
document.addEventListener('DOMContentLoaded', function() {
    setupCompletionKeyboardShortcuts();
    setupRealTimeCompletion();
    console.log('[CodeCompletion] System initialized');
});

// Expose functions to Python bridge
window.showCodeCompletionPopup = window.showCodeCompletionPopup;
window.acceptCodeCompletion = window.acceptCodeCompletion;
window.dismissCodeCompletion = window.dismissCodeCompletion;
window.showCodeCompletionCard = window.showCodeCompletionCard;
window.showCompletionIndicator = window.showCompletionIndicator;
window.hideCompletionIndicator = window.hideCompletionIndicator;
window.requestCodeCompletion = window.requestCodeCompletion;

// ============================================================================
// INLINE DIFF VIEWER - OpenCode Style Integration
// ============================================================================

/**
 * Show inline diff in chat
 * @param {Object} diffData - Diff data with original, modified, filePath, etc.
 */
window.showInlineDiff = function(diffData) {
    console.log('[DiffViewer] Showing inline diff for:', diffData.filePath);
    
    var container = document.createElement('div');
    container.className = 'inline-diff-container';
    container.id = 'diff-' + diffData.filePath.replace(/[^a-zA-Z0-9]/g, '_');
    
    // Header
    var header = document.createElement('div');
    header.className = 'inline-diff-header';
    header.innerHTML = `
        <div class="inline-diff-title">
            <div class="file-icon">FILE</div>
            <span>${escapeHtml(diffData.filePath)}</span>
        </div>
        <div class="inline-diff-stats">
            <div class="inline-diff-stat added">
                <span>+${diffData.additions || 0}</span>
            </div>
            <div class="inline-diff-stat removed">
                <span>-${diffData.deletions || 0}</span>
            </div>
        </div>
    `;
    container.appendChild(header);
    
    // Semantic badges
    if (diffData.semanticChanges && diffData.semanticChanges.length > 0) {
        var badgesContainer = document.createElement('div');
        badgesContainer.className = 'semantic-badges';
        
        diffData.semanticChanges.forEach(function(change) {
            var badge = document.createElement('div');
            badge.className = 'semantic-badge ' + change.type;
            badge.innerHTML = `
                <span>${getSemanticIcon(change.type)}</span>
                <span>${escapeHtml(change.description)}</span>
            `;
            badgesContainer.appendChild(badge);
        });
        
        container.appendChild(badgesContainer);
    }
    
    // Diff content
    var content = document.createElement('div');
    content.className = 'inline-diff-content';
    
    if (diffData.lines && diffData.lines.length > 0) {
        var currentHunk = null;
        
        diffData.lines.forEach(function(line) {
            if (line.type === 'hunk_header') {
                // Hunk header
                var hunkHeader = document.createElement('div');
                hunkHeader.className = 'diff-hunk-header';
                hunkHeader.innerHTML = escapeHtml(line.content);
                hunkHeader.onclick = function() {
                    this.classList.toggle('collapsed');
                    var next = this.nextElementSibling;
                    while (next && !next.classList.contains('diff-hunk-header')) {
                        next.style.display = next.style.display === 'none' ? '' : 'none';
                        next = next.nextElementSibling;
                    }
                };
                content.appendChild(hunkHeader);
                return;
            }
            
            // Diff row
            var row = document.createElement('div');
            row.className = 'diff-row ' + line.type;
            
            var lineNums = document.createElement('div');
            lineNums.className = 'diff-line-numbers';
            lineNums.innerHTML = `
                <div class="diff-line-num old">${line.lineNumber.original || ''}</div>
                <div class="diff-line-num new">${line.lineNumber.new || ''}</div>
            `;
            
            var lineContent = document.createElement('div');
            lineContent.className = 'diff-line-content';
            
            var prefix = ' ';
            if (line.type === 'added') prefix = '+';
            if (line.type === 'removed') prefix = '-';
            
            lineContent.innerHTML = `
                <span class="diff-line-prefix">${prefix}</span>
                <code>${escapeHtml(line.content)}</code>
            `;
            
            var actions = document.createElement('div');
            actions.className = 'diff-line-actions';
            actions.innerHTML = `
                <button class="diff-line-btn accept" title="Accept line" onclick="acceptDiffLine('${diffData.filePath}', ${line.lineNumber.new || line.lineNumber.original || 0})">OK</button>
                <button class="diff-line-btn reject" title="Reject line" onclick="rejectDiffLine('${diffData.filePath}', ${line.lineNumber.new || line.lineNumber.original || 0})">NO</button>
                <button class="diff-line-btn comment" title="Add comment" onclick="commentDiffLine('${diffData.filePath}', ${line.lineNumber.new || line.lineNumber.original || 0})">CMT</button>
            `;
            
            row.appendChild(lineNums);
            row.appendChild(lineContent);
            row.appendChild(actions);
            content.appendChild(row);
        });
    }
    
    container.appendChild(content);
    
    // Footer
    var footer = document.createElement('div');
    footer.className = 'inline-diff-footer';
    
    var confidencePercent = Math.round((diffData.confidence || 0.9) * 100);
    var confidenceClass = confidencePercent >= 80 ? 'high' : (confidencePercent >= 60 ? 'medium' : 'low');
    
    footer.innerHTML = `
        <div class="inline-diff-actions">
            <button class="inline-diff-btn accept-all" onclick="acceptAllDiffLines('${diffData.filePath}')">
                <span>OK</span>
                <span>Accept All</span>
            </button>
            <button class="inline-diff-btn reject-all" onclick="rejectAllDiffLines('${diffData.filePath}')">
                <span>NO</span>
                <span>Reject All</span>
            </button>
            <button class="inline-diff-btn view-full" onclick="showFullDiff('${diffData.filePath}')">
                <span>DIFF</span>
                <span>View Full Diff</span>
            </button>
        </div>
        <div class="inline-diff-confidence">
            <span>Confidence:</span>
            <div class="confidence-bar">
                <div class="confidence-fill ${confidenceClass}" style="width: ${confidencePercent}%"></div>
            </div>
            <span>${confidencePercent}%</span>
        </div>
    `;
    
    container.appendChild(footer);
    
    // Add to chat
    var chatMessages = document.getElementById('chatMessages');
    if (chatMessages) {
        chatMessages.appendChild(container);
        chatMessages.scrollTop = chatMessages.scrollHeight;
    }
};

/**
 * Get icon for semantic change type
 */
function getSemanticIcon(type) {
    var icons = {
        'bug_fix': 'FIX',
        'feature_add': 'FEAT',
        'refactor': 'REF',
        'optimization': 'OPT',
        'security': 'SEC',
        'test': 'TEST',
        'documentation': 'DOC',
        'style': 'STYLE',
        'other': 'INFO'
    };
    return icons[type] || 'INFO';
}

/**
 * Accept a single diff line
 */
window.acceptDiffLine = function(filePath, lineNumber) {
    console.log('[DiffViewer] Accepting line', lineNumber, 'in', filePath);
    if (window.bridge && window.bridge.on_diff_line_accepted) {
        window.bridge.on_diff_line_accepted({
            filePath: filePath,
            lineNumber: lineNumber
        });
    }
};

/**
 * Reject a single diff line
 */
window.rejectDiffLine = function(filePath, lineNumber) {
    console.log('[DiffViewer] Rejecting line', lineNumber, 'in', filePath);
    if (window.bridge && window.bridge.on_diff_line_rejected) {
        window.bridge.on_diff_line_rejected({
            filePath: filePath,
            lineNumber: lineNumber
        });
    }
};

/**
 * Add comment to a diff line
 */
window.commentDiffLine = function(filePath, lineNumber) {
    console.log('[DiffViewer] Adding comment to line', lineNumber, 'in', filePath);
    var comment = prompt('Enter your comment:');
    if (comment && window.bridge && window.bridge.on_diff_line_commented) {
        window.bridge.on_diff_line_commented({
            filePath: filePath,
            lineNumber: lineNumber,
            comment: comment
        });
    }
};

/**
 * Accept all diff lines for a file
 */
window.acceptAllDiffLines = function(filePath) {
    console.log('[DiffViewer] Accepting all changes in', filePath);
    if (window.bridge && window.bridge.on_accept_file_edit) {
        window.bridge.on_accept_file_edit(filePath);
    }
    
    // Update UI
    var container = document.getElementById('diff-' + filePath.replace(/[^a-zA-Z0-9]/g, '_'));
    if (container) {
        container.style.opacity = '0.5';
        container.querySelector('.inline-diff-footer').innerHTML = '<div style="padding: 12px; text-align: center; color: #22c55e;">? All changes accepted</div>';
    }
};

/**
 * Reject all diff lines for a file
 */
window.rejectAllDiffLines = function(filePath) {
    console.log('[DiffViewer] Rejecting all changes in', filePath);
    if (window.bridge && window.bridge.on_reject_file_edit) {
        window.bridge.on_reject_file_edit(filePath);
    }
    
    // Update UI
    var container = document.getElementById('diff-' + filePath.replace(/[^a-zA-Z0-9]/g, '_'));
    if (container) {
        container.style.opacity = '0.5';
        container.querySelector('.inline-diff-footer').innerHTML = '<div style="padding: 12px; text-align: center; color: #ef4444;">? All changes rejected</div>';
    }
};

/**
 * Show full diff in editor
 */
window.showFullDiff = function(filePath) {
    console.log('[DiffViewer] Opening full diff for', filePath);
    if (window.bridge && window.bridge.on_show_diff) {
        window.bridge.on_show_diff(filePath);
    }
};

// Expose diff viewer functions
window.showInlineDiff = window.showInlineDiff;
window.acceptDiffLine = window.acceptDiffLine;
window.rejectDiffLine = window.rejectDiffLine;
window.commentDiffLine = window.commentDiffLine;
window.acceptAllDiffLines = window.acceptAllDiffLines;
window.rejectAllDiffLines = window.rejectAllDiffLines;
window.showFullDiff = window.showFullDiff;


/* ================================================
   CURSOR IDE CARD COMPONENTS - DYNAMIC RENDERING
   Transforms tool execution into modern card-based UI
   ================================================ */

/**
 * Toggle card expansion (from new_aichat.html)
 * @param {HTMLElement} header - The card header element
 */
window.toggleCard = function(header) {
    header.parentElement.classList.toggle('expanded');
};

/**
 * Handle permission accept/reject (from new_aichat.html)
 * @param {string} cardId - The card ID
 * @param {boolean} accepted - Whether permission was accepted
 */
window.handlePermission = function(cardId, accepted) {
    const card = document.getElementById(cardId);
    if (!card) return;
    
    const btnGroup = card.querySelector('.btn-group');
    if (!btnGroup) return;
    
    if (accepted) {
        btnGroup.innerHTML = `<span class="text-green-500 text-[11px] font-bold">✓ ACCEPTED</span>`;
        setTimeout(() => { 
            card.classList.remove('expanded'); 
        }, 800);
        
        // Notify bridge if available
        if (window.bridge && window.bridge.on_permission_response) {
            window.bridge.on_permission_response({ id: cardId, accepted: true });
        }
    } else {
        btnGroup.innerHTML = `<span class="text-red-500 text-[11px] font-bold">✕ REJECTED</span>`;
        setTimeout(() => { 
            card.style.opacity = '0.5'; 
        }, 500);
        
        // Notify bridge if available
        if (window.bridge && window.bridge.on_permission_response) {
            window.bridge.on_permission_response({ id: cardId, accepted: false });
        }
    }
};

/**
 * Create a todo card with collapsible items
 * @param {Array} todos - Array of todo objects {text, status: 'completed'|'active'}
 * @returns {HTMLElement}
 */
window.createTodoCard = function(todos) {
    const completedCount = todos.filter(t => t.status === 'completed').length;
    const totalCount = todos.length;
    
    const card = document.createElement('div');
    card.className = 'card-container expanded';
    
    let todoItemsHTML = '';
    todos.forEach(todo => {
        const isCompleted = todo.status === 'completed';
        todoItemsHTML += `
            <div class="list-row ${isCompleted ? 'opacity-50' : ''}">
                <div class="todo-circle ${isCompleted ? 'completed' : 'active'}">
                    ${isCompleted ? 
                        '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="4"><path d="M20 6L9 17L4 12"/></svg>' :
                        '<div class="todo-spinner"></div>'
                    }
                </div>
                <span class="${isCompleted ? 'line-through text-gray-500' : 'text-white'}">${todo.text}</span>
            </div>
        `;
    });
    
    card.innerHTML = `
        <div class="card-header" onclick="toggleCard(this)">
            <svg class="card-chevron" fill="currentColor" viewBox="0 0 20 20"><path d="M7.293 14.707a1 1 0 010-1.414L10.586 10 7.293 6.707a1 1 0 011.414-1.414l4 4a1 1 0 010 1.414l-4 4a1 1 0 01-1.414 0z"/></svg>
            <span>To-dos</span>
            <span class="ml-auto text-xs text-gray-600">${completedCount}/${totalCount} done</span>
        </div>
        <div class="card-body">
            ${todoItemsHTML}
        </div>
    `;
    
    return card;
};

/**
 * Create a terminal output card
 * @param {string} command - The command that was run
 * @param {string} output - Terminal output text
 * @returns {HTMLElement}
 */
window.createTerminalCard = function(command, output) {
    const card = document.createElement('div');
    card.className = 'card-container expanded';
    
    card.innerHTML = `
        <div class="card-header" onclick="toggleCard(this)">
            <svg class="card-chevron" fill="currentColor" viewBox="0 0 20 20"><path d="M7.293 14.707a1 1 0 010-1.414L10.586 10 7.293 6.707a1 1 0 011.414-1.414l4 4a1 1 0 010 1.414l-4 4a1 1 0 01-1.414 0z"/></svg>
            <span>Run in terminal</span>
            <span class="ml-auto text-[10px] opacity-40">View Output ↗</span>
        </div>
        <div class="card-body">
            <div class="terminal-viewport">$ ${command}\n${output}</div>
        </div>
    `;
    
    return card;
};

/**
 * Create a permission request card
 * @param {string} action - Action description (e.g., "Delete temporary parts?")
 * @param {Array} files - Array of file objects {name, status: 'A'|'M'|'D'}
 * @param {string} cardId - Unique ID for this permission card
 * @returns {HTMLElement}
 */
window.createPermissionCard = function(action, files, cardId) {
    const card = document.createElement('div');
    card.className = 'card-container expanded';
    card.id = cardId || 'permission-' + Date.now();
    
    // Determine icon based on action
    let iconSVG = '<svg class="w-3.5 h-3.5 text-blue-500" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>';
    if (action.toLowerCase().includes('delete')) {
        iconSVG = '<svg class="w-3.5 h-3.5 text-red-500" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"/></svg>';
    } else if (action.toLowerCase().includes('create') || action.toLowerCase().includes('add')) {
        iconSVG = '<svg class="w-3.5 h-3.5 text-green-500" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path><polyline points="14 2 14 8 20 8"></polyline><line x1="12" y1="18" x2="12" y2="12"></line><line x1="9" y1="15" x2="15" y2="15"></line></svg>';
    }
    
    let filesHTML = '';
    files.forEach(file => {
        let statusClass = '';
        let statusText = '';
        let icon = '📄';
        
        switch(file.status) {
            case 'A':
                statusClass = 'text-add';
                statusText = 'A Created';
                icon = '🐍';
                break;
            case 'M':
                statusClass = 'text-mod';
                statusText = 'M Modified';
                icon = '🐍';
                break;
            case 'D':
                statusClass = 'text-del';
                statusText = 'D Deleted';
                icon = '📄';
                break;
        }
        
        filesHTML += `<div class="list-row"><span>${icon} ${file.name}</span> <span class="status-tag ${statusClass}">${statusText}</span></div>`;
    });
    
    card.innerHTML = `
        <div class="card-header">
            <svg class="card-chevron" fill="currentColor" viewBox="0 0 20 20"><path d="M7.293 14.707a1 1 0 010-1.414L10.586 10 7.293 6.707a1 1 0 011.414-1.414l4 4a1 1 0 010 1.414l-4 4a1 1 0 01-1.414 0z"/></svg>
            <span class="flex items-center gap-2">
                ${iconSVG}
                ${action}
            </span>
            <div class="btn-group">
                <button class="btn-reject" onclick="handlePermission('${card.id}', false)">Reject</button>
                <button class="btn-accept" onclick="handlePermission('${card.id}', true)">Accept</button>
            </div>
        </div>
        <div class="card-body">
            ${filesHTML}
        </div>
    `;
    
    return card;
};

/**
 * Create a step log entry
 * @param {string} message - Log message
 * @param {string} detail - Optional detail text
 * @returns {HTMLElement}
 */
window.createStepLog = function(message, detail) {
    const log = document.createElement('div');
    log.className = 'step-log';
    log.innerHTML = `${message}${detail ? ` <span class="opacity-60">${detail}</span>` : ''}`;
    return log;
};

/**
 * Create a "creating file" progress indicator
 * @param {string} fileName - Name of file being created
 * @returns {HTMLElement}
 */
window.createCreatingFileCard = function(fileName) {
    const card = document.createElement('div');
    card.className = 'card-container';
    card.id = 'creating-file-card';
    
    card.innerHTML = `
        <div class="flex items-center p-3 gap-3">
            <svg class="w-4 h-4 text-blue-500 pulse-timer" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>
            <span class="text-gray-400">Create file</span>
            <span class="text-gray-500 ml-auto">${fileName}</span>
        </div>
    `;
    
    return card;
};

/**
 * Append a card component to the chat container
 * @param {HTMLElement} card - The card element to append
 */
window.appendCardToChat = function(card) {
    const container = document.getElementById('chatMessages');
    if (!container) {
        console.warn('[CardUI] Chat container not found');
        return;
    }
    
    // Hide empty state if visible
    const emptyState = document.getElementById('empty-state');
    if (emptyState) emptyState.style.display = 'none';
    
    container.appendChild(card);
    
    // Auto-scroll to show new card
    container.scrollTop = container.scrollHeight;
};

/**
 * Render tool execution as a card (wrapper for backward compatibility)
 * @param {Object} toolData - Tool execution data from bridge
 */
window.renderToolAsCard = function(toolData) {
    console.log('[CardUI] Rendering tool as card:', toolData);
    
    let card = null;
    
    switch(toolData.type) {
        case 'todo':
            card = window.createTodoCard(toolData.todos || []);
            break;
        case 'terminal':
            card = window.createTerminalCard(toolData.command || '', toolData.output || '');
            break;
        case 'permission':
            card = window.createPermissionCard(
                toolData.action || 'Permission required',
                toolData.files || [],
                toolData.cardId || 'permission-' + Date.now()
            );
            break;
        case 'creating_file':
            card = window.createCreatingFileCard(toolData.fileName || 'unknown');
            break;
        default:
            console.warn('[CardUI] Unknown tool type:', toolData.type);
            return;
    }
    
    if (card) {
        window.appendCardToChat(card);
    }
};

console.log('[CardUI] Cursor IDE card components initialized');



