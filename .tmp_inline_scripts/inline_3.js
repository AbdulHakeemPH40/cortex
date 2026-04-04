
        (function() {
            'use strict';
            
            // Global error handler
            window.onerror = function(msg, url, line, col, error) {
                console.error('[Cortex Error]', msg, 'at', url + ':' + line + ':' + col);
                if (window.bridge && bridge.on_js_error) {
                    bridge.on_js_error(JSON.stringify({ msg: msg, url: url, line: line, col: col }));
                }
                return false;
            };
            
            // Unhandled promise rejections
            window.onunhandledrejection = function(event) {
                console.error('[Cortex Unhandled Promise]', event.reason);
            };
            
            // Loading state management
            window.cortexLoaded = false;
            window.markReady = function() {
                window.cortexLoaded = true;
                document.body.classList.add('loaded');
            };
            
                        // CRITICAL: Define trySetProjectInfo IMMEDIATELY for Python to call
            window._pendingProjectInfo = null;
            window._pendingProjectInfoWithChats = null;
            window.trySetProjectInfo = function(name, path, retryCount) {
                retryCount = retryCount || 0;
                console.log('[CHAT] trySetProjectInfo called (attempt', retryCount + 1, '):', name, path);
                if (retryCount > 10) {
                    console.error('[CHAT] setProjectInfo failed after', retryCount, 'attempts');
                    return;
                }
                if (window.setProjectInfo) {
                    console.log('[CHAT] ? Calling setProjectInfo now');
                    window.setProjectInfo(name, path);
                } else {
                    console.log('[CHAT] setProjectInfo not ready, retrying in 300ms...');
                    setTimeout(function() {
                        window.trySetProjectInfo(name, path, retryCount + 1);
                    }, 300);
                }
            };
            // CRITICAL: Define trySetProjectInfoWithChats IMMEDIATELY for Python to call
            window.trySetProjectInfoWithChats = function(name, path, chatsJson, retryCount) {
                retryCount = retryCount || 0;
                console.log('[CHAT] trySetProjectInfoWithChats called (attempt', retryCount + 1, '):', name, path);
                if (retryCount > 10) {
                    console.error('[CHAT] setProjectInfoWithChats failed after', retryCount, 'attempts');
                    window._pendingProjectInfoWithChats = { name: name, path: path, chatsJson: chatsJson };
                    if (window.onPendingProjectInfoWithChats) window.onPendingProjectInfoWithChats();
                    return;
                }
                if (window.setProjectInfoWithChats) {
                    console.log('[CHAT] ? Calling setProjectInfoWithChats now');
                    window.setProjectInfoWithChats(name, path, chatsJson);
                    window._pendingProjectInfoWithChats = null;
                } else {
                    window._pendingProjectInfoWithChats = { name: name, path: path, chatsJson: chatsJson };
                    if (window.onPendingProjectInfoWithChats) window.onPendingProjectInfoWithChats();
                    console.log('[CHAT] setProjectInfoWithChats not ready, retrying in 300ms...');
                    setTimeout(function() {
                        window.trySetProjectInfoWithChats(name, path, chatsJson, retryCount + 1);
                    }, 300);
                }
            };
            console.log('[CHAT] ? window.trySetProjectInfo defined at page load');
        })();
    
