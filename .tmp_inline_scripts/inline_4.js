
        // Debug console capture
        (function() {
            var debugContent = document.getElementById('debug-console-content');
            var originalLog = console.log;
            var originalError = console.error;
            var originalWarn = console.warn;
            
            function addToDebug(type, args) {
                if (!debugContent) return;
                var line = document.createElement('div');
                line.style.marginBottom = '3px';
                line.style.color = type === 'error' ? '#ff6b6b' : type === 'warn' ? '#ffd93d' : '#aaa';
                line.textContent = '[' + type.toUpperCase() + '] ' + Array.from(args).join(' ');
                debugContent.appendChild(line);
                debugContent.scrollTop = debugContent.scrollHeight;
            }
            
            console.log = function() { addToDebug('log', arguments); originalLog.apply(console, arguments); };
            console.error = function() { addToDebug('error', arguments); originalError.apply(console, arguments); };
            console.warn = function() { addToDebug('warn', arguments); originalWarn.apply(console, arguments); };
            
            window.onerror = function(msg, url, line, col, err) {
                addToDebug('error', [msg + ' at line ' + line]);
                return false;
            };
            
            // Toggle debug console with Ctrl+Shift+D
            document.addEventListener('keydown', function(e) {
                if (e.ctrlKey && e.shiftKey && e.key === 'D') {
                    var dc = document.getElementById('debug-console');
                    dc.style.display = dc.style.display === 'none' ? 'block' : 'none';
                }
            });
        })();
    
