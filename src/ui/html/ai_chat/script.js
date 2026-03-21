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
            // PyQt slots return promises, handle asynchronously
            var promise = bridge.save_chats_to_file(key, data);
            if (promise && typeof promise.then === 'function') {
                promise.then(function(result) {
                    if (result === "OK") {
                        console.log('[CHAT] SAVE - File backup: SUCCESS');
                    } else {
                        console.error('[CHAT] SAVE - File backup: FAILED:', result);
                    }
                }).catch(function(err) {
                    console.error('[CHAT] SAVE - File backup: ERROR:', err);
                });
            } else {
                // Synchronous fallback
                if (promise === "OK") {
                    console.log('[CHAT] SAVE - File backup: SUCCESS');
                } else {
                    console.error('[CHAT] SAVE - File backup: FAILED:', promise);
                }
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


// ── TASK COMPLETION TRACKING ─────────────────────────────────────────
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
    var statusIcon = errors > 0 ? '⚠️' : '✅';
    var statusText = errors > 0 ? 'Completed with issues' : 'Task completed';
    
    var html = '<div class="tcc-header ' + statusClass + '">' +
        '<span class="tcc-icon">' + statusIcon + '</span>' +
        '<span class="tcc-title">' + statusText + '</span>' +
        '<span class="tcc-duration">' + duration + 's</span></div>';
    
    html += '<div class="tcc-stats">';
    if (filesRead > 0) html += '<span class="tcc-stat">📄 ' + filesRead + ' read</span>';
    if (filesWritten > 0) html += '<span class="tcc-stat">✏️ ' + filesWritten + ' modified</span>';
    if (commandsRun > 0) html += '<span class="tcc-stat">⚙️ ' + commandsRun + ' commands</span>';
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
                    highlighted = hljs.highlight(code, { language: hljs.getLanguage(lang) ? lang : 'plaintext' }).value;
                } catch (e) {
                    highlighted = escapeHtml(code);
                }
                return '<pre data-lang="' + escapeHtml(lang) + '"><code class="hljs language-' + lang + '">' + highlighted + '</code></pre>';
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
                return '<code class="inline-code">' + (code || '') + '</code>';
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
        return '<svg viewBox="0 0 32 32" width="18" height="18"><path d="M3 9c0-1.1.9-2 2-2h8l3 3h11c1.1 0 2 .9 2 2v13c0 1.1-.9 2-2 2H5c-1.1 0-2-.9-2-2V9z" fill="#DCB67A"/><path d="M3 13h26v11c0 1.1-.9 2-2 2H5c-1.1 0-2-.9-2-2V13z" fill="#ECBD78"/></svg>';
    }
    
    var iconMap = {
        'py': '<svg viewBox="0 0 32 32" width="18" height="18"><defs><linearGradient id="pyg" x1="0%" y1="0%" x2="100%" y2="100%"><stop offset="0%" stop-color="#387EB8"/><stop offset="100%" stop-color="#366994"/></linearGradient><linearGradient id="pyy" x1="0%" y1="0%" x2="100%" y2="100%"><stop offset="0%" stop-color="#FFE052"/><stop offset="100%" stop-color="#FFC331"/></linearGradient></defs><path d="M15.9 5C10.3 5 10.7 7.4 10.7 7.4l.01 2.5h5.3v.7H8.7S5 10.1 5 15.8c0 5.7 3.2 5.5 3.2 5.5h1.9v-2.6s-.1-3.2 3.1-3.2h5.4s3 .05 3-2.9V8.5S22.1 5 15.9 5z" fill="url(#pyg)"/><circle cx="12.5" cy="8.2" r="1.1" fill="#fff" opacity=".8"/><path d="M16.1 27c5.6 0 5.2-2.4 5.2-2.4l-.01-2.5h-5.3v-.7h7.3S27 21.9 27 16.2c0-5.7-3.2-5.5-3.2-5.5h-1.9v2.6s.1 3.2-3.1 3.2h-5.4s-3-.05-3 2.9v4.6S9.9 27 16.1 27z" fill="url(#pyy)"/><circle cx="19.5" cy="23.8" r="1.1" fill="#fff" opacity=".8"/></svg>',
        'js': '<svg viewBox="0 0 32 32" width="18" height="18"><rect width="32" height="32" rx="3" fill="#F7DF1E"/><path d="M20.8 24.3c.5.9 1.2 1.5 2.4 1.5 1 0 1.6-.5 1.6-1.2 0-.8-.7-1.1-1.8-1.6l-.6-.3c-1.8-.8-3-1.7-3-3.7 0-1.9 1.4-3.3 3.6-3.3 1.6 0 2.7.5 3.5 1.9l-1.9 1.2c-.4-.8-.9-1.1-1.6-1.1-.7 0-1.2.5-1.2 1.1 0 .8.5 1.1 1.6 1.5l.6.3c2.1.9 3.3 1.8 3.3 3.9 0 2.2-1.7 3.5-4 3.5-2.2 0-3.7-1.1-4.4-2.5l2-.1z" fill="#222"/><path d="M12.2 24.6c.4.6.7 1.2 1.6 1.2.8 0 1.3-.3 1.3-1.5V16h2.4v8.3c0 2.5-1.5 3.7-3.6 3.7-1.9 0-3-1-3.6-2.2l1.9-1.2z" fill="#222"/></svg>',
        'ts': '<svg viewBox="0 0 32 32" width="18" height="18"><rect width="32" height="32" rx="3" fill="#3178C6"/><path d="M18 17.4h3.4v.9H19v1.2h2.2v.9H19V23h-1V17.4zM9 17.4h5.8v1H12V23h-1v-4.6H9v-1z" fill="#fff"/><path d="M14.2 19.9c0-1.8 1.2-2.7 2.8-2.7.7 0 1.3.1 1.8.4l-.3.9c-.4-.2-.9-.3-1.4-.3-1 0-1.7.6-1.7 1.7 0 1.1.7 1.8 1.8 1.8.3 0 .6 0 .8-.1v-1.2H17v-.9h2v2.7c-.5.3-1.2.5-2 .5-1.8 0-2.8-1-2.8-2.8z" fill="#fff"/></svg>',
        'jsx': '<svg viewBox="0 0 32 32" width="18" height="18"><circle cx="16" cy="16" r="2.5" fill="#61DAFB"/><ellipse cx="16" cy="16" rx="11" ry="4.2" fill="none" stroke="#61DAFB" stroke-width="1.3"/><ellipse cx="16" cy="16" rx="11" ry="4.2" fill="none" stroke="#61DAFB" stroke-width="1.3" transform="rotate(60 16 16)"/><ellipse cx="16" cy="16" rx="11" ry="4.2" fill="none" stroke="#61DAFB" stroke-width="1.3" transform="rotate(120 16 16)"/></svg>',
        'tsx': '<svg viewBox="0 0 32 32" width="18" height="18"><circle cx="16" cy="16" r="2.5" fill="#61DAFB"/><ellipse cx="16" cy="16" rx="11" ry="4.2" fill="none" stroke="#61DAFB" stroke-width="1.3"/><ellipse cx="16" cy="16" rx="11" ry="4.2" fill="none" stroke="#61DAFB" stroke-width="1.3" transform="rotate(60 16 16)"/><ellipse cx="16" cy="16" rx="11" ry="4.2" fill="none" stroke="#61DAFB" stroke-width="1.3" transform="rotate(120 16 16)"/></svg>',
        'html': '<svg viewBox="0 0 32 32" width="18" height="18"><path d="M4 3l2.3 25.7L16 31l9.7-2.3L28 3z" fill="#E44D26"/><path d="M16 28.4V5.7l10.2 22.7z" fill="#F16529"/><path d="M9.4 13.5l.4 3.9H16v-3.9zM8.7 8H16V4.1H8.3zM16 21.5l-.05.01-4.1-1.1-.26-3h-3.9l.5 5.7 7.8 2.2z" fill="#EBEBEB"/><path d="M16 13.5v3.9h5.9l-.6 6.1-5.3 1.5v4l7.8-2.2.06-.6 1.2-13.1.12-1.6zm0-9.4v3.9h10.2l.08-1 .18-2.9z" fill="#fff"/></svg>',
        'css': '<svg viewBox="0 0 32 32" width="18" height="18"><path d="M4 3l2.3 25.7L16 31l9.7-2.3L28 3z" fill="#1572B6"/><path d="M16 28.4V5.7l10.2 22.7z" fill="#33A9DC"/><path d="M21.5 13.5H16v-3.9h6l.4-3.6H9.6L10 9.6h5.9v3.9H9.3l.4 3.6H16v4.1l-4.2-1.2-.3-3.1H7.7l.6 6.3 7.7 2.1z" fill="#fff"/><path d="M16 17.2v-3.7h5.1l-.5 5.2L16 19.9v4.1l7.7-2.1.1-.6 1-10.4.1-1.4H16v4zM16 5.7v3.9h5.7l.1-1 .2-2.9z" fill="#EBEBEB"/></svg>',
        'scss': '<svg viewBox="0 0 32 32" width="18" height="18"><circle cx="16" cy="16" r="13" fill="#CD6799"/><path d="M22.5 14.7c-.7-.3-1.1-.4-1.6-.6-.3-.1-.6-.2-.8-.3-.2-.1-.4-.2-.4-.4 0-.3.4-.6 1.2-.6.9 0 1.7.3 2.1.5l.8-1.8c-.5-.3-1.5-.7-2.9-.7-1.5 0-2.7.4-3.5 1.1-.7.7-1 1.5-.9 2.4.1.9.7 1.6 1.9 2.1.5.2 1 .3 1.4.5.3.1.5.2.7.3.2.2.3.4.2.7-.1.5-.7.8-1.5.8-1 0-1.9-.3-2.5-.7l-.8 1.9c.7.4 1.8.7 3 .7h.3c1.3-.05 2.4-.4 3.1-1.1.7-.7 1-1.5.9-2.5-.1-.9-.7-1.6-1.7-2.3zm-7.6-4.2c-1.5 0-2.8.5-3.7 1.3l-.8-1.2-2.1 1.2.9 1.4c-.6.9-1 2-1 3.2s.4 2.3 1.1 3.2l-1.1 1.2 1.6 1.4 1.2-1.3c.9.5 1.9.8 3.1.8 3.4 0 5.7-2.5 5.7-5.7-.1-3-2.1-5.5-4.9-5.5zm-.3 9c-1.9 0-3.2-1.4-3.2-3.3s1.3-3.3 3.2-3.3c.8 0 1.5.3 2 .8l-3.4 4.2c.4.4.9.6 1.4.6z" fill="#fff"/></svg>',
        'java': '<svg viewBox="0 0 32 32" width="18" height="18"><path d="M12.2 22.1s-1.2.7.8 1c2.4.3 3.6.2 6.2-.2 0 0 .7.4 1.6.8-5.7 2.4-12.9-.1-8.6-1.6zM11.5 19s-1.3 1 .7 1.2c2.5.3 4.5.3 8-.4 0 0 .5.5 1.2.8-7.1 2.1-15-.2-9.9-1.6z" fill="#E76F00"/><path d="M17.2 13.4c1.4 1.7-.4 3.2-.4 3.2s3.6-1.9 2-4.2c-1.5-2.2-2.6-3.3 3.6-7.1 0 0-9.8 2.4-5.2 8.1z" fill="#E76F00"/><path d="M23.2 24.4s.9.7-.9 1.3c-3.4 1-14.1 1.3-17.1 0-1.1-.5.9-1.1 1.5-1.2.6-.1 1-.1 1-.1-1.1-.8-7.4 1.6-3.2 2.3 11.6 1.9 21.1-.8 18.7-2.3zM12.6 15.9s-5.3 1.3-1.9 1.8c1.5.2 4.4.2 7.1-.1 2.2-.3 4.5-.8 4.5-.8s-.8.3-1.3.7c-5.4 1.4-15.7.8-12.8-.7 2.5-1.3 4.4-1 4.4-.9zM20.6 20.8c5.4-2.8 2.9-5.6 1.2-5.2-.4.1-.6.2-.6.2s.2-.3.5-.4c3.6-1.3 6.4 3.8-1.1 5.8 0 0 .1-.1 0-.4z" fill="#E76F00"/><path d="M18.5 3s3 3-2.9 7.7c-4.7 3.8-1.1 5.9 0 8.3-2.7-2.5-4.7-4.7-3.4-6.7 2-3 7.5-4.4 6.3-9.3z" fill="#E76F00"/></svg>',
        'kt': '<svg viewBox="0 0 32 32" width="18" height="18"><defs><linearGradient id="kot" x1="0%" y1="0%" x2="100%" y2="100%"><stop offset="0%" stop-color="#7F52FF"/><stop offset="50%" stop-color="#C811E1"/><stop offset="100%" stop-color="#E54857"/></linearGradient></defs><path d="M4 4h10l14 12-14 12H4L4 4z" fill="url(#kot)"/><path d="M18 4l14 12-14 12V4z" fill="url(#kot)" opacity=".6"/></svg>',
        'swift': '<svg viewBox="0 0 32 32" width="18" height="18"><defs><linearGradient id="swf" x1="0%" y1="0%" x2="100%" y2="100%"><stop offset="0%" stop-color="#F05138"/><stop offset="100%" stop-color="#F8981E"/></linearGradient></defs><path d="M16 4c-3 2-6 6-6 10s2 6 4 7c-1-3 1-7 4-9 2 2 4 5 3 9 2-1 4-3 4-7s-3-8-6-10h-3z" fill="url(#swf)"/><circle cx="16" cy="16" r="4" fill="#fff"/></svg>',
        'go': '<svg viewBox="0 0 32 32" width="18" height="18"><path d="M16 5C9.4 5 4 10.4 4 17s5.4 12 12 12 12-5.4 12-12S22.6 5 16 5zm0 21c-5 0-9-4-9-9s4-9 9-9 9 4 9 9-4 9-9 9z" fill="#00ACD7"/><circle cx="12.5" cy="14.5" r="1.3" fill="#00ACD7"/><circle cx="19.5" cy="14.5" r="1.3" fill="#00ACD7"/><path d="M13 19s.7 2 3 2 3-2 3-2H13z" fill="#00ACD7"/></svg>',
        'rs': '<svg viewBox="0 0 32 32" width="18" height="18"><path d="M16 3L18.1 7.3 22.8 6.2 22.7 11 27.1 12.9 24.5 17 27.1 21.1 22.7 23 22.8 27.8 18.1 26.7 16 31 13.9 26.7 9.2 27.8 9.3 23 4.9 21.1 7.5 17 4.9 12.9 9.3 11 9.2 6.2 13.9 7.3z" fill="#DEA584"/><circle cx="16" cy="17" r="5" fill="none" stroke="#DEA584" stroke-width="2"/><circle cx="16" cy="17" r="2.5" fill="#DEA584"/></svg>',
        'c': '<svg viewBox="0 0 32 32" width="18" height="18"><circle cx="16" cy="16" r="13" fill="#005B9F"/><path d="M22.5 20.4c-.8 2.5-3.1 4.3-5.8 4.3-3.4 0-6.1-2.7-6.1-6.1 0-3.4 2.7-6.1 6.1-6.1 2.8 0 5.1 1.9 5.9 4.4H20c-.6-1.3-1.9-2.1-3.3-2.1-2 0-3.7 1.6-3.7 3.7s1.7 3.7 3.7 3.7c1.5 0 2.7-.9 3.3-2.2h2.5z" fill="#fff"/></svg>',
        'cpp': '<svg viewBox="0 0 32 32" width="18" height="18"><circle cx="16" cy="16" r="13" fill="#00599C"/><path d="M18 20.4c-.8 2.5-3.1 4.3-5.8 4.3-3.4 0-6.1-2.7-6.1-6.1 0-3.4 2.7-6.1 6.1-6.1 2.8 0 5.1 1.9 5.9 4.4h-2.6c-.6-1.3-1.9-2.1-3.3-2.1-2 0-3.7 1.6-3.7 3.7s1.7 3.7 3.7 3.7c1.5 0 2.7-.9 3.3-2.2H18z" fill="#fff"/><path d="M21 13.3v1.5h-1.5V16H21v1.7h1.5V16H24v-1.2h-1.5v-1.5zm4.5 0v1.5H24V16h1.5v1.7H27V16h1.5v-1.2H27v-1.5z" fill="#fff"/></svg>',
        'cs': '<svg viewBox="0 0 32 32" width="18" height="18"><defs><linearGradient id="csg2" x1="0%" y1="0%" x2="100%" y2="100%"><stop offset="0%" stop-color="#9B4F96"/><stop offset="100%" stop-color="#68217A"/></linearGradient></defs><circle cx="16" cy="16" r="13" fill="url(#csg2)"/><path d="M10 19.8c-.8-2.1.1-4.6 2.1-5.8s4.5-1 6.3.5l-1 1.7c-1.2-.9-2.8-1.1-4.1-.3-1.3.7-1.9 2.2-1.5 3.6l-1.8.3zm12 0c-.5 1.4-1.7 2.5-3.1 2.8l-.4-1.9c.8-.2 1.4-.8 1.7-1.5l1.8.6z" fill="#fff"/><path d="M20 13.4h1.2v1.2H20zm0 2.4h1.2v1.2H20zm2.4-2.4h1.2v1.2h-1.2zm0 2.4h1.2v1.2h-1.2z" fill="#fff"/></svg>',
        'rb': '<svg viewBox="0 0 32 32" width="18" height="18"><defs><linearGradient id="rbg2" x1="0%" y1="100%" x2="100%" y2="0%"><stop offset="0%" stop-color="#FF0000"/><stop offset="100%" stop-color="#A30000"/></linearGradient></defs><path d="M22.9 5L27 9.1l.1 17.8-4.2 4.1H9L5 27.1 4.9 9.3 9 5z" fill="url(#rbg2)"/><path d="M11 10l-3 3v9l3 3h10l3-3v-9l-3-3zm.5 13l-2-2v-7l2-2h9l2 2v7l-2 2z" fill="#fff" opacity=".7"/><circle cx="16" cy="16" r="2.5" fill="#fff"/></svg>',
        'php': '<svg viewBox="0 0 32 32" width="18" height="18"><ellipse cx="16" cy="16" rx="14" ry="9" fill="#8892BF"/><path d="M10.5 12H8l-2 8h2l.5-2h2l.5 2h2zm-.5 4.5H9l.5-2h.5zm6.5-4.5h-3l-2 8h2l.5-2h1c1.7 0 3-1.3 3-3s-1.3-3-2.5-3zm-.5 4.5H16l.5-2h.5c.5 0 1 .5 1 1s-.5 1-1 1zm7.5-4.5h-3l-2 8h2l.5-2h2l.5 2h2zm-.5 4.5h-1l.5-2h.5z" fill="#fff"/></svg>',
        'dart': '<svg viewBox="0 0 32 32" width="18" height="18"><defs><linearGradient id="dart" x1="0%" y1="0%" x2="100%" y2="100%"><stop offset="0%" stop-color="#0175C2"/><stop offset="100%" stop-color="#02569B"/></linearGradient></defs><path d="M16 4L4 12v12l12 8 12-8V12z" fill="url(#dart)"/><path d="M16 4v24l12-8V12z" fill="url(#dart)" opacity=".7"/><path d="M10 14h12v2H10zm2 4h8v2h-8z" fill="#fff"/></svg>',
        'lua': '<svg viewBox="0 0 32 32" width="18" height="18"><circle cx="16" cy="16" r="13" fill="#000080"/><path d="M22 10c-2 0-3 1-3.5 2.5-.5-1-1.5-1.5-2.5-1.5-1.5 0-2.5 1-2.5 2.5 0 2 2 2.5 4 3 2 .5 4 1 4 3 0 1.5-1 2.5-2.5 2.5-2 0-3-1.5-4-3-.5 1.5-1.5 3-3 3v-2c1 0 2-.5 2.5-1.5.5 1 1.5 1.5 2.5 1.5 1.5 0 2.5-1 2.5-2.5 0-2-2-2.5-4-3-2-.5-4-1-4-3C12 8.5 13.5 7 16 7c1.5 0 2.5 1 3.5 2 .5-1.5 1.5-2.5 3-2.5v2z" fill="#fff"/></svg>',
        'r': '<svg viewBox="0 0 32 32" width="18" height="18"><rect width="32" height="32" rx="3" fill="#276DC3"/><path d="M8 8h4v16h-4zM14 8h10l-2 5h-3l-1 3h3l-2 8H14z" fill="#fff"/></svg>',
        'jl': '<svg viewBox="0 0 32 32" width="18" height="18"><circle cx="16" cy="16" r="13" fill="#9558B2"/><circle cx="16" cy="16" r="9" fill="none" stroke="#fff" stroke-width="1.5"/><circle cx="16" cy="16" r="4" fill="#fff"/><path d="M16 7v4M16 21v4M7 16h4M21 16h4" stroke="#fff" stroke-width="1.5"/></svg>',
        'zig': '<svg viewBox="0 0 32 32" width="18" height="18"><defs><linearGradient id="zig" x1="0%" y1="0%" x2="100%" y2="100%"><stop offset="0%" stop-color="#F7A800"/><stop offset="100%" stop-color="#FF9500"/></linearGradient></defs><path d="M16 4L4 16l12 12 12-12z" fill="url(#zig)"/><path d="M16 10l-6 6 6 6 6-6z" fill="#000" opacity=".3"/></svg>',
        'ex': '<svg viewBox="0 0 32 32" width="18" height="18"><defs><linearGradient id="elx" x1="0%" y1="0%" x2="100%" y2="100%"><stop offset="0%" stop-color="#4B275F"/><stop offset="100%" stop-color="#6E3A8E"/></linearGradient></defs><circle cx="16" cy="16" r="13" fill="url(#elx)"/><path d="M10 10c0-1 1-2 2-2h8c1 0 2 1 2 2v2l-6 8-6-8v-2z" fill="#fff"/><ellipse cx="16" cy="14" rx="4" ry="2" fill="#4B275F"/></svg>',
        'hs': '<svg viewBox="0 0 32 32" width="18" height="18"><defs><linearGradient id="hs" x1="0%" y1="0%" x2="100%" y2="100%"><stop offset="0%" stop-color="#5D4F85"/><stop offset="100%" stop-color="#453A6B"/></linearGradient></defs><path d="M8 4h10l6 6v18H8V4z" fill="url(#hs)"/><path d="M18 4v6h6" fill="none" stroke="#fff" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/><text x="16" y="22" font-family="Segoe UI,sans-serif" font-size="6" font-weight="bold" fill="#fff" text-anchor="middle">HS</text></svg>',
        'clj': '<svg viewBox="0 0 32 32" width="18" height="18"><circle cx="16" cy="16" r="13" fill="#588526"/><path d="M10 10l6 12 6-12H10z" fill="#96CA50"/><circle cx="16" cy="16" r="3" fill="#fff"/></svg>',
        'vue': '<svg viewBox="0 0 32 32" width="18" height="18"><polygon points="16,27 2,5 8.5,5 16,18.5 23.5,5 30,5" fill="#41B883"/><polygon points="16,20 9.5,9 13,9 16,14 19,9 22.5,9" fill="#35495E"/></svg>',
        'svelte': '<svg viewBox="0 0 32 32" width="18" height="18"><path d="M26.1 5.8c-2.8-4-8.4-5-12.4-2.3L7.2 7.7C5.3 9 4 11 3.8 13.3c-.2 1.9.3 3.8 1.4 5.3-.8 1.2-1.2 2.7-1.1 4.1.2 2.7 1.9 5.1 4.4 6.2 2.8 1.2 6 .7 8.3-1.2l6.5-4.2c1.9-1.3 3.2-3.3 3.4-5.6.2-1.9-.3-3.8-1.4-5.3.8-1.2 1.2-2.7 1.1-4.1-.1-1.1-.5-2.2-1.3-2.7z" fill="#FF3E00"/><path d="M13.7 27c-1.6.4-3.3 0-4.6-.9-1.8-1.3-2.5-3.5-1.8-5.5l.2-.5.4.3c1 .7 2 1.2 3.2 1.5l.3.1-.03.3c-.05.7.2 1.4.7 1.9.9.8 2.3.9 3.3.2l6.5-4.2c.6-.4 1-.9 1.1-1.6.1-.7-.1-1.4-.6-1.9-.9-.8-2.3-.9-3.3-.2l-2.5 1.6c-1.1.7-2.4 1-3.7.8-1.5-.2-2.8-1-3.6-2.2-1.4-2-1-4.7.9-6.2l6.5-4.2c1.6-1.1 3.7-1.3 5.5-.6 1.8.7 3 2.3 3.2 4.2.1.7 0 1.5-.3 2.2l-.2.5-.4-.3c-1-.7-2-1.2-3.2-1.5l-.3-.1.03-.3c.05-.7-.2-1.4-.7-1.9-.9-.8-2.3-.9-3.3-.2l-6.5 4.2c-.6.4-1 .9-1.1 1.6-.1.7.1 1.4.6 1.9.9.8 2.3.9 3.3.2l2.5-1.6c1.1-.7 2.4-1 3.7-.8 1.5.2 2.8 1 3.6 2.2 1.4 2 1 4.7-.9 6.2L18 26.3c-.8.5-1.5.8-2.3.7z" fill="#fff"/></svg>',
        'sql': '<svg viewBox="0 0 32 32" width="18" height="18"><ellipse cx="16" cy="10" rx="10" ry="4" fill="#4479A1"/><path d="M6 10v4c0 2.2 4.5 4 10 4s10-1.8 10-4v-4c0 2.2-4.5 4-10 4S6 12.2 6 10z" fill="#4479A1"/><path d="M6 14v4c0 2.2 4.5 4 10 4s10-1.8 10-4v-4c0 2.2-4.5 4-10 4S6 16.2 6 14z" fill="#336791"/><path d="M6 18v4c0 2.2 4.5 4 10 4s10-1.8 10-4v-4c0 2.2-4.5 4-10 4S6 20.2 6 18z" fill="#336791"/></svg>',
        'md': '<svg viewBox="0 0 32 32" width="18" height="18"><rect x="2" y="7" width="28" height="18" rx="3" fill="#42A5F5"/><path d="M7 22V10h3l3 4 3-4h3v12h-3v-7l-3 4-3-4v7zm16 0l-4-6h2.5v-6h3v6H27z" fill="#fff"/></svg>',
        'json': '<svg viewBox="0 0 32 32" width="18" height="18"><path d="M12.7 6c-1.5 0-2.5.4-3 1.1-.5.7-.5 1.7-.5 2.5v2.2c0 .8-.2 1.5-.8 1.9-.3.2-.7.3-1.4.3v4c.7 0 1.1.1 1.4.3.6.4.8 1.1.8 1.9v2.2c0 .8 0 1.8.5 2.5.5.7 1.5 1.1 3 1.1H14v-2h-1.3c-.7 0-.9-.2-1-.4-.1-.2-.1-.7-.1-1.4v-2.2c0-1.2-.3-2.2-1.2-2.8-.2-.2-.5-.3-.8-.4.3-.1.5-.2.8-.4.9-.6 1.2-1.6 1.2-2.8V9.8c0-.7 0-1.2.1-1.4.1-.2.3-.4 1-.4H14V6h-1.3zm6.6 0v2h1.3c.7 0 .9.2 1 .4.1.2.1.7.1 1.4v2.2c0 1.2.3 2.2 1.2 2.8.2.2.5.3.8.4-.3.1-.5.2-.8.4-.9.6-1.2 1.6-1.2 2.8v2.2c0 .7 0 1.2-.1 1.4-.1.2-.3.4-1 .4H18v2h1.3c1.5 0 2.5-.4 3-1.1.5-.7.5-1.7.5-2.5v-2.2c0-.8.2-1.5.8-1.9.3-.2.7-.3 1.4-.3v-4c-.7 0-1.1-.1-1.4-.3-.6-.4-.8-1.1-.8-1.9V9.8c0-.8 0-1.8-.5-2.5C21.8 6.4 20.8 6 19.3 6z" fill="#F5A623"/></svg>',
        'yaml': '<svg viewBox="0 0 32 32" width="18" height="18"><rect width="32" height="32" rx="3" fill="#CC1018"/><path d="M7 9h2.5l3 5 3-5H18l-4.5 7v6h-2v-6zm11 4h7v2h-2.5v8h-2v-8H18z" fill="#fff"/></svg>',
        'xml': '<svg viewBox="0 0 32 32" width="18" height="18"><rect width="32" height="32" rx="3" fill="#607D8B"/><circle cx="16" cy="16" r="5" fill="none" stroke="#fff" stroke-width="2"/><path d="M16 5v4M16 23v4M5 16h4M23 16h4M8.5 8.5l2.8 2.8M20.7 20.7l2.8 2.8M8.5 23.5l2.8-2.8M20.7 11.3l2.8-2.8" stroke="#fff" stroke-width="2" stroke-linecap="round"/></svg>',
        'sh': '<svg viewBox="0 0 32 32" width="18" height="18"><rect width="32" height="32" rx="3" fill="#1E1E1E"/><path d="M6 10l7 6-7 6" fill="none" stroke="#4EC9B0" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"/><path d="M16 22h10" stroke="#4EC9B0" stroke-width="2.5" stroke-linecap="round"/></svg>',
        'bat': '<svg viewBox="0 0 32 32" width="18" height="18"><rect width="32" height="32" rx="3" fill="#1E1E1E"/><path d="M6 10l7 6-7 6" fill="none" stroke="#4EC9B0" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"/><path d="M16 22h10" stroke="#4EC9B0" stroke-width="2.5" stroke-linecap="round"/></svg>',
        'ps1': '<svg viewBox="0 0 32 32" width="18" height="18"><rect width="32" height="32" rx="3" fill="#1E1E1E"/><path d="M6 10l7 6-7 6" fill="none" stroke="#4EC9B0" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"/><path d="M16 22h10" stroke="#4EC9B0" stroke-width="2.5" stroke-linecap="round"/></svg>',
        'txt': '<svg viewBox="0 0 32 32" width="18" height="18"><path d="M8 4h10l6 6v18H8V4z" fill="#9AAABB"/><path d="M18 4v6h6" fill="none" stroke="#fff" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/><line x1="10" y1="13" x2="22" y2="13" stroke="#fff" stroke-width="1.5" stroke-linecap="round"/><line x1="10" y1="17" x2="22" y2="17" stroke="#fff" stroke-width="1.5" stroke-linecap="round"/><line x1="10" y1="21" x2="18" y2="21" stroke="#fff" stroke-width="1.5" stroke-linecap="round"/></svg>',
        'env': '<svg viewBox="0 0 32 32" width="18" height="18"><rect width="32" height="32" rx="3" fill="#4A9B4F"/><path d="M8 4h10l6 6v18H8V4z" fill="#5DBA5F"/><path d="M18 4v6h6" fill="none" stroke="#fff" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/><text x="16" y="22" font-family="Segoe UI,sans-serif" font-size="7" font-weight="bold" fill="#fff" text-anchor="middle">ENV</text></svg>',
        'zip': '<svg viewBox="0 0 32 32" width="18" height="18"><rect width="32" height="32" rx="3" fill="#8E44AD"/><path d="M16 7l-2 2h-3l-1 3h3l-2 2 2 2h-3l1 3h3l2 2 2-2h3l1-3h-3l2-2-2-2h3l-1-3h-3z" fill="#F39C12"/><rect x="10" y="12" width="12" height="10" rx="1" fill="none" stroke="#fff" stroke-width="1.5"/></svg>',
        'git': '<svg viewBox="0 0 32 32" width="18" height="18"><path d="M29.5 14.5L17.5 2.5c-.7-.7-1.8-.7-2.5 0L12.4 5l3 3c.7-.2 1.5 0 2 .6.6.5.8 1.3.6 2l2.9 2.9c.7-.2 1.5 0 2 .6.9.9.9 2.3 0 3.2-.9.9-2.3.9-3.2 0-.6-.6-.8-1.5-.5-2.2L16.5 12v8c.2.1.4.2.6.4.9.9.9 2.3 0 3.2-.9.9-2.3.9-3.2 0-.9-.9-.9-2.3 0-3.2.2-.2.5-.4.7-.5v-8c-.2-.1-.5-.3-.7-.5-.6-.6-.8-1.5-.5-2.2L10.5 6.1 2.5 14c-.7.7-.7 1.8 0 2.5l12 12c.7.7 1.8.7 2.5 0l12.5-12.5c.7-.7.7-1.8 0-2.5z" fill="#F34F29"/></svg>',
        'gitignore': '<svg viewBox="0 0 32 32" width="18" height="18"><path d="M29.5 14.5L17.5 2.5c-.7-.7-1.8-.7-2.5 0L12.4 5l3 3c.7-.2 1.5 0 2 .6.6.5.8 1.3.6 2l2.9 2.9c.7-.2 1.5 0 2 .6.9.9.9 2.3 0 3.2-.9.9-2.3.9-3.2 0-.6-.6-.8-1.5-.5-2.2L16.5 12v8c.2.1.4.2.6.4.9.9.9 2.3 0 3.2-.9.9-2.3.9-3.2 0-.9-.9-.9-2.3 0-3.2.2-.2.5-.4.7-.5v-8c-.2-.1-.5-.3-.7-.5-.6-.6-.8-1.5-.5-2.2L10.5 6.1 2.5 14c-.7.7-.7 1.8 0 2.5l12 12c.7.7 1.8.7 2.5 0l12.5-12.5c.7-.7.7-1.8 0-2.5z" fill="#F34F29"/></svg>',
        'gitattributes': '<svg viewBox="0 0 32 32" width="18" height="18"><path d="M29.5 14.5L17.5 2.5c-.7-.7-1.8-.7-2.5 0L12.4 5l3 3c.7-.2 1.5 0 2 .6.6.5.8 1.3.6 2l2.9 2.9c.7-.2 1.5 0 2 .6.9.9.9 2.3 0 3.2-.9.9-2.3.9-3.2 0-.6-.6-.8-1.5-.5-2.2L16.5 12v8c.2.1.4.2.6.4.9.9.9 2.3 0 3.2-.9.9-2.3.9-3.2 0-.9-.9-.9-2.3 0-3.2.2-.2.5-.4.7-.5v-8c-.2-.1-.5-.3-.7-.5-.6-.6-.8-1.5-.5-2.2L10.5 6.1 2.5 14c-.7.7-.7 1.8 0 2.5l12 12c.7.7 1.8.7 2.5 0l12.5-12.5c.7-.7.7-1.8 0-2.5z" fill="#F34F29"/></svg>',
        'docker': '<svg viewBox="0 0 32 32" width="18" height="18"><path d="M28.8 14.5c-.5-.3-1.6-.5-2.5-.3-.1-.9-.7-1.7-1.6-2.3l-.5-.3-.4.4c-.5.6-.7 1.6-.6 2.3.1.5.3.9.6 1.3-.3.1-.8.3-1.5.3H4.1c-.3 1.3-.1 3 .9 4.2.9 1.2 2.3 1.9 4.3 1.9 4 0 7-1.8 8.9-5 1.1.1 3.4.1 4.6-2.2.1 0 .6-.3 1.6-.9l.5-.3-.1-.1z" fill="#2396ED"/><rect x="7" y="13" width="2" height="2" rx=".3" fill="#2396ED"/><rect x="9.7" y="13" width="2" height="2" rx=".3" fill="#2396ED"/><rect x="12.4" y="13" width="2" height="2" rx=".3" fill="#2396ED"/><rect x="15.1" y="13" width="2" height="2" rx=".3" fill="#2396ED"/><rect x="17.8" y="13" width="2" height="2" rx=".3" fill="#2396ED"/><rect x="12.4" y="11" width="2" height="2" rx=".3" fill="#2396ED"/><rect x="15.1" y="11" width="2" height="2" rx=".3" fill="#2396ED"/><rect x="17.8" y="11" width="2" height="2" rx=".3" fill="#2396ED"/><rect x="15.1" y="9" width="2" height="2" rx=".3" fill="#2396ED"/></svg>',
    };
    
    return iconMap[ext] || '<svg viewBox="0 0 32 32" width="18" height="18"><path d="M8 4h10l6 6v18H8V4z" fill="#90A4AE"/><path d="M18 4v6h6" fill="none" stroke="#fff" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg>';
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
            
            // Terminal output with advanced throttling to prevent UI freezing
            var _terminalOutputBuffer = '';
            var _terminalOutputTimeout = null;
            var _terminalOutputFrameId = null;
            var _terminalLastWrite = 0;
            var _terminalMaxBufferSize = 8192; // Max buffer before forced flush
            var _terminalPendingData = []; // Queue for burst handling
            
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
    initMarked();
    // Terminal is initialized lazily when first shown
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
    var cfsBody = document.getElementById('cfs-body');
    if (cfsBody) {
        cfsBody.style.display = 'none';
        cfsBody.innerHTML = '';
    }
    var cfsList = document.getElementById('cfs-list');
    if (cfsList) cfsList.innerHTML = '';
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

function loadChat(id) {
    var chat = chats.find(function (c) { return c.id === id; });
    if (!chat) return;
    currentChatId = id;
    clearMessages();
    
    // Clear changed files and TODOs before loading new chat
    clearTodosAndChangedFiles();
    
    chat.messages.forEach(function (msg) {
        // Skip messages with undefined/empty text
        if (!msg.text || msg.text === 'undefined' || msg.text.trim() === '') return;
        appendMessage(msg.text, msg.sender, false);
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
            // Include any pending tool activities with the message
            var messageData = { text: text, sender: sender };
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

    input.value = '';
    input.style.height = 'auto';

    if (!bridge) {
        console.warn("Cortex: Bridge connection not ready.");
        return;
    }

    if (_isGenerating) {
        _enqueueMessage(text);
    } else {
        _sendNow(text);
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
            <span class="thinking-title">Cortex is working</span>
            <span class="thinking-subtitle" id="thinking-main-text">Analyzing your request...</span>
            <span class="thinking-status" id="thinking-status" style="font-size: 11px; color: #666; margin-top: 4px; display: block;"></span>
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
        // Create output section if it doesn't exist yet
        outputEl = document.createElement('div');
        outputEl.className = 'term-output-body';
        outputEl.id = outputId;
        outputEl.style.display = 'block';  // show immediately when streaming
        var pre = document.createElement('pre');
        pre.className = 'term-output-text';
        pre.id = outputId + '-pre';
        outputEl.appendChild(pre);
        card.appendChild(outputEl);

        // Update toggle button if exists (old style cards)
        var toggle = card.querySelector('.tc-toggle, .term-toggle');
        if (toggle) {
            var ch = toggle.querySelector('.tc-chevron, .term-chevron');
            if (ch) ch.textContent = '⌄';
        }
    }
    
    // Append line to output (limit to last 200 lines to avoid memory bloat)
    var pre = document.getElementById(outputId + '-pre');
    if (!pre) {
        // Fallback: try to find any pre inside the output element
        pre = outputEl.querySelector('pre');
    }
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

    // Update thinking indicator with current activity
    var statusEl = document.getElementById('thinking-status');
    if (statusEl) {
        var activityText = '';
        if (type === 'read_file') activityText = 'Reading: ' + info;
        else if (type === 'list_directory') activityText = 'Exploring: ' + info;
        else if (type === 'run_command') activityText = 'Running: ' + info;
        else if (type === 'git_status') activityText = 'Checking git status...';
        else activityText = type + '...';
        statusEl.textContent = activityText;
    }

    // ── File read/edit cards (IMMEDIATE VISIBLE CARDS) ──────────────
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

        // Parse file path from info (e.g., "hakeem.html (200 lines)")
        var filePath = info.split(' ')[0];
        
        // Check if card already exists for this file
        var existingCard = cardsEl.querySelector('[data-path*="' + filePath + '"]');
        if (existingCard) {
            // Update existing card status
            if (status === 'complete') {
                existingCard.classList.remove('fec-pending');
                existingCard.classList.add('fec-applied');
                existingCard.dataset.status = 'applied';
            }
        } else {
            // Create new file activity card
            var card = document.createElement('div');
            card.className = 'fec fec-' + (status === 'running' ? 'pending' : 'applied');
            card.dataset.path = filePath;
            card.dataset.status = status === 'running' ? 'pending' : 'applied';
            
            var fileName = filePath.split('/').pop().split('\\').pop();
            var ext = fileName.split('.').pop().toLowerCase();
            var extClass = 'fec-ext-' + (ext || 'default');
            
            var icon = type === 'read_file' ? '👁' : type === 'edit_file' ? '✎' : '📝';
            var actionText = type === 'read_file' ? 'Reading' : type === 'edit_file' ? 'Editing' : 'Creating';
            
            card.innerHTML = 
                '<div class="fec-left">' +
                    '<span class="fec-ext-badge ' + extClass + '">' + ext.toUpperCase() + '</span>' +
                    '<button class="fec-name" onclick="openFileInEditor(\'' + filePath.replace(/'/g, "\\'") + '\')">' +
                        fileName +
                    '</button>' +
                    '<span style="color:#666;margin-left:8px;font-size:11px;">' + actionText + '</span>' +
                '</div>' +
                '<div class="fec-right">' +
                    (status === 'running' ? 
                        '<span class="fec-status-text fec-status-pending">...</span>' :
                        '<span class="fec-status-text fec-status-applied">✓</span>'
                    ) +
                '</div>';
            
            cardsEl.appendChild(card);
        }

        smartScroll(container);
        return;
    }

    // ── Terminal command card handling ──────────────────────────────
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
            var card = buildTerminalCard(info, '', 'running', null, cardId);
            cardsEl.appendChild(card);
        } else {
            var lastId = currentAssistantMessage.dataset.lastTermCardId;
            if (lastId) {
                updateTerminalCard(
                    lastId,
                    status === 'error' ? 'error' : 'success',
                    status === 'error' ? 1 : 0,
                    ''
                );
            }
        }

        smartScroll(container);
        return;
    }

    // ── list_directory tree card ────────────────────────────────────
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
    
    if (type === 'read_file' || type === 'write_file' || type === 'edit_file' || type === 'inject_after' || type === 'add_import' || type === 'create_file') {
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
    if (type === 'create_directory') return '<span class="file-icon folder">📁+</span>';
    if (type === 'delete_file') return '<span class="file-icon delete">🗑️</span>';
    if (type === 'delete_directory') return '<span class="file-icon delete">🗑️</span>';
    if (type === 'run_command') return '<span class="file-icon terminal">⌘</span>';
    if (type === 'search_code') return '<span class="file-icon search">🔍</span>';
    if (type === 'git_status' || type === 'git_diff') return '<span class="file-icon git">GIT</span>';
    if (type === 'thinking') return '<span class="file-icon think">💭</span>';
    return '<span class="file-icon">⚙️</span>';
}

function formatActivityLabel(type, info, status) {
    var isEdit = ['write_file', 'edit_file', 'inject_after', 'add_import'].includes(type) || type.startsWith('terminal_create') || type.startsWith('terminal_edit');
    var isCreate = ['create_file', 'create_directory'].includes(type);
    var isDelete = ['delete_file', 'delete_directory'].includes(type);
    var labelText = isEdit ? 'Editing...' : (isCreate ? 'Creating...' : (isDelete ? 'Deleting...' : 'Running'));
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
    if (isCreate) {
        var action = type === 'create_directory' ? 'Created directory' : 'Created file';
        return status === 'running' ? runningPrefix + displayInfo : action + ' ' + displayInfo + ' ✓';
    }
    if (isDelete) {
        var action = type === 'delete_directory' ? 'Deleted directory' : 'Deleted file';
        return status === 'running' ? runningPrefix + displayInfo : action + ' ' + displayInfo + ' ✓';
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

// Render directory contents HTML (used for both live display and restoration)
function renderDirectoryContents(path, contents) {
    var container = document.getElementById('chatMessages');
    if (!container || !contents) return;
    
    var lines = contents.split('\n').filter(function(l) { return l.trim(); });
    if (lines.length === 0) return;
    
    // Create a simple file list container (no header, no full path)
    var list = document.createElement('div');
    list.className = 'simple-file-list';
    list.style.cssText = 'margin: 8px 0; padding: 8px 12px; background: var(--bg-secondary, #1e1e2e); border-radius: 6px; border: 1px solid var(--border-color, #3d3d5c);';
    
    // Normalize base path
    var basePath = path.replace(/\\/g, '/');
    if (!basePath.endsWith('/')) basePath += '/';
    
    lines.forEach(function(line) {
        if (!line.trim()) return;
        
        var item = document.createElement('div');
        item.style.cssText = 'display: flex; align-items: center; gap: 8px; padding: 4px 0; font-size: 13px; color: var(--text-secondary, #b0b0b0); cursor: pointer; transition: background 0.15s;';
        item.onmouseover = function() { this.style.background = 'rgba(255,255,255,0.05)'; };
        item.onmouseout = function() { this.style.background = 'transparent'; };
        
        // Check if it's a folder (ends with / or has 📁 in the line from backend)
        var isFolder = line.includes('📁') || line.trim().endsWith('/');
        
        // Extract just the name (remove emoji and size info)
        var name = line.replace(/[📁📄]/g, '').replace(/\s*\([^)]*\)/g, '').replace(/\s*\d+B$/, '').trim();
        
        var icon;
        if (isFolder) {
            // Use blue macOS-style folder icon (SVG)
            icon = '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg"><path d="M20 6h-8l-2-2H4c-1.1 0-2 .9-2 2v12c0 1.1.9 2 2 2h16c1.1 0 2-.9 2-2V8c0-1.1-.9-2-2-2z" fill="#4A90D9"/></svg>';
            // Remove trailing slash from display name
            name = name.replace(/\/$/, '');
        } else {
            // Get file extension for icon
            if (name.includes('.')) {
                var ext = name.split('.').pop().toLowerCase();
                icon = getFileExtensionIcon(ext);
            } else {
                icon = '📄';
            }
        }
        
        // Build full path for click handler
        var fullPath = basePath + name;
        var escapedPath = fullPath.replace(/'/g, "\\'");
        
        console.log('[DEBUG] renderDirectoryContents - Folder:', name, 'Full path:', fullPath);
        
        // Add click handler
        if (isFolder) {
            item.onclick = function() { 
                console.log('[DEBUG] Opening folder in explorer:', escapedPath);
                openFolderInExplorer(escapedPath); 
            };
        } else {
            item.onclick = function() { 
                console.log('[DEBUG] Opening file:', escapedPath);
                openFileInEditor(escapedPath); 
            };
        }
        
        var iconSpan = '<span style="font-size: 14px; display: inline-flex; align-items: center;">' + icon + '</span>';
        item.innerHTML = iconSpan + '<span style="flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">' + escapeHtml(name) + '</span>';
        list.appendChild(item);
    });
    
    // Append to the current assistant message bubble
    if (currentAssistantMessage) {
        currentAssistantMessage.appendChild(list);
    } else {
        container.appendChild(list);
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
    var testContent = "📁 agents/\n📁 skills/\n📄 plugin.json\n🐍 main.py\n📜 script.js\n🌐 index.html";
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

function clearActivitySection() {
    // Remove the entire activity section when task is complete
    if (currentActivitySection) {
        currentActivitySection.remove();
        currentActivitySection = null;
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

    // If empty todos received, don't clear existing ones - persist until completed
    if (todos.length === 0) {
        // Only hide if there are no existing todos
        if (currentTodoList.length === 0) {
            section.style.display = 'none';
            list.innerHTML = '';
            if (previewEl) previewEl.textContent = '';
            if (countEl)   countEl.textContent   = '0/0';
        }
        return;
    }

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
    section.style.display = 'flex';

    // Calculate stats from currentTodoList (merged list)
    var total     = currentTodoList.length;
    var completed = currentTodoList.filter(function(t) { return t.status === 'COMPLETE'; }).length;

    if (countEl) countEl.textContent = completed + '/' + total;

    // Header preview: first incomplete task text
    if (previewEl) {
        var firstIncomplete = null;
        for (var i = 0; i < currentTodoList.length; i++) {
            if (currentTodoList[i].status !== 'COMPLETE' && currentTodoList[i].status !== 'CANCELLED') {
                firstIncomplete = currentTodoList[i];
                break;
            }
        }
        previewEl.textContent = (firstIncomplete || currentTodoList[0]).content;
    }

    list.innerHTML = '';
    currentTodoList.forEach(function(todo) {
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
    
    // NOTE: We no longer clear todos here - todos persist until explicitly completed
    // The AI will send new todos via updateTodos() if needed, which will merge with existing
    
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

    // ── Terminal output streaming: route to terminal card ────────────────
    if (chunk.includes('<terminal_output>')) {
        var termMatch = chunk.match(/<terminal_output>(.*?)<\/terminal_output>/);
        if (termMatch) {
            _updateCurrentTerminalCard(termMatch[1]);
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
    clearActivitySection();  // Remove the Working section

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

        // ── Save to history (only if content is valid) ─────────────────────
        var chat = chats.find(function(c) { return c.id === currentChatId; });
        if (chat && displayText && displayText.trim() !== '' && displayText !== 'undefined') {
            chat.messages.push({ text: displayText, sender: 'assistant' });
            saveChats();
        }

        // ── Final markdown render ───────────────────────────────────────
        var contentDiv = currentAssistantMessage.querySelector('.message-content');
        if (contentDiv) {
            var finalHtml = '';
            try {
                finalHtml = (typeof marked !== 'undefined' && marked.parse)
                    ? (marked.parse(displayText) || '')
                    : formatMarkdownFallback(displayText);
            } catch (e) {
                finalHtml = formatMarkdownFallback(displayText);
            }
            contentDiv.innerHTML = finalHtml || '';

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

    // ── Show task completion summary ─────────────────────────────────
    showTaskCompletionSummary();

    // ── Reset state ────────────────────────────────────────────────
    currentAssistantMessage = null;
    currentContent          = '';
    _taskSummaryBuffer      = '';
    _inTaskSummary          = false;

    var sendBtn = document.getElementById('sendBtn');
    var stopBtn = document.getElementById('stopBtn');
    if (sendBtn) sendBtn.style.display = 'flex';
    if (stopBtn) stopBtn.style.display = 'none';

    // ── Trigger queue processing ────────────────────────────────────
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
    window.showDirectoryContents = showDirectoryContents;
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
                    renderHistoryList();
                    console.log('[CHAT] Loaded chat with', chats[0].messages.length, 'messages');
                } else {
                    // No saved chats, start fresh
                    // No saved chats, start fresh
                    chats = [];
                    startNewChat();
                    renderHistoryList();
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

    var fileName    = filePath.split('/').pop().split('\\').pop();
    var esc         = filePath.replace(/'/g, "\\'");
    var badgeClass  = { 'M': 'cfs-badge-m', 'C': 'cfs-badge-c', 'D': 'cfs-badge-d' }[editType] || 'cfs-badge-m';
    var addedHtml   = added   > 0 ? '<span class="cfs-stat-added">+' + added   + '</span>' : '';
    var removedHtml = removed > 0 ? '<span class="cfs-stat-removed">-' + removed + '</span>' : '';

    var row = document.createElement('div');
    row.className = 'cfs-row' + (status === 'accepted' ? ' cfs-accepted' : '');
    row.dataset.path = filePath;
    
    // Footer section shows only status (no individual Accept/Reject buttons)
    // User uses "Accept All" / "Reject All" buttons in footer header
    var rightContent = '';
    if (status === 'accepted') {
        rightContent = '<span class="cfs-row-applied">Applied</span>';
    } else if (status === 'rejected') {
        rightContent = '<span class="cfs-row-rejected">Rejected</span>';
    } else {
        // Pending - show status text, user can use Accept All/Reject All in header
        rightContent = '<span class="cfs-row-pending">Pending</span>';
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
        _changedFiles[filePath].added   = added;
        _changedFiles[filePath].removed = removed;
        _refreshCfsHeader();
        return;
    }

    _changedFiles[filePath] = { added: added, removed: removed, status: 'pending', editType: editType };
    renderChangedFileRow(filePath, added, removed, editType, 'pending');
    
    // Show the Changed Files section when first file is added
    var section = document.getElementById('changed-files-section');
    if (section && Object.keys(_changedFiles).length === 1) {
        section.style.display = 'block';
        // Expand the section
        window._cfsCollapsed = false;
        section.classList.add('expanded');
        var body = document.getElementById('cfs-body');
        if (body) body.style.display = 'block';
    }
    
    _refreshCfsHeader();
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
    var row = document.querySelector('.cfs-row[data-path="' + filePath + '"]');
    if (row) {
        row.classList.add('cfs-accepted');
        var rightEl = row.querySelector('.cfs-row-right');
        if (rightEl) rightEl.innerHTML = '<span class="cfs-row-applied">Applied</span>';
    }
    // Resolve relative path before sending to bridge
    var resolvedPath = resolveFilePath(filePath);
    // Convert backslashes to forward slashes for Windows paths
    // This prevents backslash escape character issues in PyQt bridge
    var safePath = resolvedPath.replace(/\\/g, '/');
    console.log('[DEBUG] Accepting file:', safePath);
    if (window.bridge) bridge.on_accept_file_edit(safePath);
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
    // Resolve relative path before sending to bridge
    var resolvedPath = resolveFilePath(filePath);
    // Convert backslashes to forward slashes for Windows paths
    var safePath = resolvedPath.replace(/\\/g, '/');
    console.log('[DEBUG] Rejecting file:', safePath);
    if (window.bridge) bridge.on_reject_file_edit(safePath);
    _refreshCfsHeader();
    markFileRejected(filePath);
}

function acceptAllChanges(e) {
    if (e) e.stopPropagation();
    console.log('[DEBUG] Accept All clicked, files:', Object.keys(_changedFiles));
    Object.keys(_changedFiles).forEach(function(p) {
        if (_changedFiles[p].status === 'pending') {
            console.log('[DEBUG] Accepting file:', p);
            var btn = document.querySelector('.cfs-row[data-path="' + p + '"] .cfs-row-accept-btn');
            if (btn) acceptChangedFile(p, btn);
        }
    });
}

function rejectAllChanges(e) {
    if (e) e.stopPropagation();
    console.log('[DEBUG] Reject All clicked, files:', Object.keys(_changedFiles));
    Object.keys(_changedFiles).forEach(function(p) {
        if (_changedFiles[p].status === 'pending') {
            console.log('[DEBUG] Rejecting file:', p);
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
function buildFileEditCard(filePath, added, removed, editType, status, original, modified) {
    editType = editType || 'M';
    status   = status   || 'pending';

    var fileName = filePath.split('/').pop().split('\\').pop();
    var ext      = fileName.split('.').pop().toLowerCase();
    var esc      = filePath.replace(/'/g, "\\'");

    // ── File type badge (colored, matches Cursor/Qoder) ──────────────────
    var ftBadge = getFileTypeBadge(ext);

    // ── Diff stats ─────────────────────────────────────────────
    // For new files (C), always show added count even if 0
    // For modified files (M), show both added and removed
    var addedHtml   = (added > 0 || editType === 'C') ? '<span class="fec-added">+'  + added   + '</span>' : '';
    var removedHtml = removed > 0 ? '<span class="fec-removed">-' + removed + '</span>' : '';

    // ── M/C/D badge ─────────────────────────────────────────────
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
                    '<button class="fec-btn-diff" onclick="event.stopPropagation(); if(window.bridge) window.bridge.on_show_diff(this.closest(\'.fec\').dataset.path || \'\');">Diff</button>' +
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

    // Click card — no diff overlay, just open file in editor
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

// File type badge — SVG icons
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
        console.log('[DEBUG] Created new cards container');
    }

    // ── Parse <file_edited> tags ────────────────────────────────────
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


// ══════════════════════════════════════════════════════════════
// THREE FEATURES IMPLEMENTATION
// ══════════════════════════════════════════════════════════════

// ── State variables for features ──────────────────────────────
var _todoExpanded = false;
var _msgQueue     = [];
var _isGenerating = false;
var _queueIdSeq   = 0;

// ══════════════════════════════════════════════════════════════
// FEATURE 1 — PROJECT TREE CARD
// ══════════════════════════════════════════════════════════════

function buildProjectTreeCard(rootPath, items) {
    var card = document.createElement('div');
    card.className = 'ptree-card';
    card.dataset.root = rootPath;

    var rootEl = document.createElement('div');
    rootEl.className = 'ptree-root';
    rootEl.textContent = rootPath;
    rootEl.dataset.path = rootPath;
    rootEl.title = 'Open folder';
    rootEl.onclick = function() {
        if (window.bridge) bridge.on_open_folder(this.dataset.path);
    };
    card.appendChild(rootEl);

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

        // Determine the branch connector
        var branch = isLast ? '└──' : '├──';

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
        'html': '📄', 'htm': '📄',
        'js':   '📄', 'ts':  '📄', 'jsx': '📄', 'tsx': '📄',
        'css':  '📄', 'scss': '📄',
        'py':   '📄', 'java': '📄', 'go':  '📄', 'rs':  '📄',
        'json': '📄', 'yaml': '📄', 'yml': '📄',
        'md':   '📄', 'txt':  '📄',
        'png':  '🖼️', 'jpg': '🖼️', 'svg': '🖼️',
        'mp4':  '🎬', 'mp3':  '🎵',
        'zip':  '📦', 'tar':  '📦',
        'sh':   '⚙️', 'bat':  '⚙️',
    };
    return map[ext] || '📄';
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

// ══════════════════════════════════════════════════════════════
// FEATURE 2 — TERMINAL COMMAND CARD
// ══════════════════════════════════════════════════════════════

function buildTerminalCard(command, output, status, exitCode, cardId) {
    var card = document.createElement('div');
    card.className = 'term-card term-' + status;
    card.id = cardId || ('term-' + Date.now());
    card.dataset.command = command;
    card.dataset.status  = status;

    var headerIcon = {
        'running': '▷',
        'success': '<span style="color:#22c55e">✓</span>',
        'error':   '<span style="color:#ef4444">⊗</span>'
    }[status] || '▷';

    var exitCodeHtml = (status === 'error' && exitCode !== undefined && exitCode !== null)
        ? '<span class="term-exit-code">Exit Code: ' + exitCode + '</span>'
        : '';

    var formattedCmd = formatTerminalCommand(command);

    var outputId = (cardId || 'term-' + Date.now()) + '-output';
    var outputHtml = output
        ? '<div class="term-output-body" id="' + outputId + '" style="display:none;">' +
              '<pre class="term-output-text">' + escapeHtml(output) + '</pre>' +
          '</div>'
        : '';

    card.innerHTML =
        '<div class="term-header">' +
            '<span class="term-status-icon">' + headerIcon + '</span>' +
            '<span class="term-title">Run in terminal</span>' +
            exitCodeHtml +
        '</div>' +
        '<div class="term-body">' +
            '<pre class="term-command">' + formattedCmd + '</pre>' +
        '</div>' +
        '<div class="term-footer">' +
            '<button class="term-output-toggle" onclick="toggleTerminalOutput(\'' + outputId + '\', this)">' +
                'Terminal Output <span class="term-chevron">›</span>' +
            '</button>' +
            '<button class="term-view-btn" onclick="openTerminalPanel()">' +
                '<svg width="11" height="11" viewBox="0 0 24 24" fill="none" ' +
                    'stroke="currentColor" stroke-width="2">' +
                    '<polyline points="15 3 21 3 21 9"/>' +
                    '<path d="M21 3L9 15"/>' +
                    '<polyline points="9 21 3 21 3 15"/>' +
                '</svg>' +
                ' View in terminal' +
            '</button>' +
        '</div>' +
        (outputHtml || '');

    return card;
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
    if (chevron) chevron.textContent = isHidden ? '⌄' : '›';
}

function updateTerminalCard(cardId, status, exitCode, output) {
    var card = document.getElementById(cardId);
    if (!card) return;

    card.className = 'term-card term-' + status;
    card.dataset.status = status;

    var iconEl = card.querySelector('.term-status-icon');
    if (iconEl) {
        if (status === 'success') iconEl.innerHTML = '<span style="color:#22c55e">✓</span>';
        if (status === 'error')   iconEl.innerHTML = '<span style="color:#ef4444">⊗</span>';
    }

    if (status === 'error' && exitCode !== undefined) {
        var titleEl = card.querySelector('.term-title');
        if (titleEl && !card.querySelector('.term-exit-code')) {
            var exitEl = document.createElement('span');
            exitEl.className = 'term-exit-code';
            exitEl.textContent = 'Exit Code: ' + exitCode;
            titleEl.insertAdjacentElement('afterend', exitEl);
        }
    }

    if (output) {
        var outputId = cardId + '-output';
        var existingOutput = document.getElementById(outputId);
        if (existingOutput) {
            existingOutput.querySelector('.term-output-text').textContent = output;
        } else {
            var outputDiv = document.createElement('div');
            outputDiv.className = 'term-output-body';
            outputDiv.id = outputId;
            outputDiv.style.display = 'none';
            outputDiv.innerHTML = '<pre class="term-output-text">' + escapeHtml(output) + '</pre>';
            card.appendChild(outputDiv);
        }
    }
}

function openTerminalPanel() {
    if (window.bridge && bridge.on_open_terminal) {
        bridge.on_open_terminal();
    } else if (window.showTerminal) {
        window.showTerminal();
    }
}

window.setTerminalOutput = function(cardId, output, exitCode) {
    var status = exitCode === 0 ? 'success' : 'error';
    updateTerminalCard(cardId, status, exitCode, output);
};

// ══════════════════════════════════════════════════════════════
// FEATURE 3 — TODO PANEL
// ══════════════════════════════════════════════════════════════

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

    section.style.display = 'flex';

    // Calculate stats from currentTodoList (merged list)
    var total     = currentTodoList.length;
    var completed = currentTodoList.filter(function(t) { return t.status === 'COMPLETE'; }).length;
    if (countEl) countEl.textContent = completed + '/' + total;

    if (previewEl) {
        var firstPending = currentTodoList.find(function(t) {
            return t.status !== 'COMPLETE' && t.status !== 'CANCELLED';
        });
        previewEl.textContent = (firstPending || currentTodoList[0]).content;
    }

    list.innerHTML = '';
    currentTodoList.forEach(function(todo) {
        var item = document.createElement('div');
        var statusCls = 'todo-' + todo.status.toLowerCase().replace('_', '');
        item.className = 'todo-item ' + statusCls;
        item.dataset.id = todo.id;

        var iconHtml = buildTodoIcon(todo.status);
        item.innerHTML = iconHtml +
            '<span class="todo-text">' + escapeHtml(todo.content) + '</span>';

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

// ══════════════════════════════════════════════════════════════
// FEATURE 4 — MESSAGE QUEUE SYSTEM
// ══════════════════════════════════════════════════════════════

function _sendNow(text) {
    _isGenerating = true;

    appendMessage(text, 'user', true);

    showThinkingIndicator();

    var sendBtn = document.getElementById('sendBtn');
    var stopBtn = document.getElementById('stopBtn');
    if (sendBtn) sendBtn.style.display = 'none';
    if (stopBtn) stopBtn.style.display = 'flex';

    bridge.on_message_submitted(text);
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

        item.innerHTML =
            '<span class="mq-position">' + (_msgQueue.indexOf(msg) + 1) + '</span>' +
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
