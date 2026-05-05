/**
 * OpenCode Enhancement - Permission Card Support
 * Add these functions to your aichat.html or script.js
 */

// Global storage for permission scopes
window.permissionScopes = {};

/**
 * Display a permission card in the chat
 * @param {string} requestId - The permission request ID
 * @param {string} html - The HTML content of the permission card
 */
function showPermissionCard(requestId, html) {
    console.log('[Permission] Showing permission card:', requestId);
    
    // Create message container
    const messageDiv = document.createElement('div');
    messageDiv.className = 'message permission-message';
    messageDiv.id = 'perm-message-' + requestId;
    
    // Create bubble
    const bubble = document.createElement('div');
    bubble.className = 'message-bubble permission';
    bubble.innerHTML = html;
    
    messageDiv.appendChild(bubble);
    
    // Add to chat
    const chatContainer = document.getElementById('chat-messages');
    if (chatContainer) {
        chatContainer.appendChild(messageDiv);
        chatContainer.scrollTop = chatContainer.scrollHeight;
    }
    
    // Initialize scope storage
    window.permissionScopes[requestId] = 'session';
}

/**
 * Select permission scope (Session/Workspace/Global)
 * @param {string} requestId - The permission request ID
 * @param {string} scope - The selected scope
 */
function selectScope(requestId, scope) {
    console.log('[Permission] Selected scope:', scope, 'for request:', requestId);
    
    // Store selection
    window.permissionScopes[requestId] = scope;
    
    // Update UI
    const card = document.getElementById('perm-card-' + requestId);
    if (card) {
        const buttons = card.querySelectorAll('.scope-btn');
        buttons.forEach(btn => {
            btn.classList.remove('active');
            if (btn.dataset.scope === scope) {
                btn.classList.add('active');
            }
        });
    }
}

/**
 * Grant permission
 * @param {string} requestId - The permission request ID
 */
function grantPermission(requestId) {
    console.log('[Permission] Granting permission:', requestId);
    
    const scope = window.permissionScopes[requestId] || 'session';
    
    // Send to Python
    if (bridge && bridge.on_permission_card_response) {
        bridge.on_permission_card_response(requestId, true, scope);
    }
    
    // Update UI
    disablePermissionCard(requestId, 'Granted ✓');
}

/**
 * Grant limited permission (read-only)
 * @param {string} requestId - The permission request ID
 */
function grantLimited(requestId) {
    console.log('[Permission] Granting limited permission:', requestId);
    
    // Send to Python with limited scope
    if (bridge && bridge.on_permission_card_response) {
        bridge.on_permission_card_response(requestId, true, 'limited');
    }
    
    // Update UI
    disablePermissionCard(requestId, 'Limited Access ✓');
}

/**
 * Deny permission
 * @param {string} requestId - The permission request ID
 */
function denyPermission(requestId) {
    console.log('[Permission] Denying permission:', requestId);
    
    // Send to Python
    if (bridge && bridge.on_permission_card_response) {
        bridge.on_permission_card_response(requestId, false, 'denied');
    }
    
    // Update UI
    disablePermissionCard(requestId, 'Denied ✗');
}

/**
 * Disable permission card after response
 * @param {string} requestId - The permission request ID
 * @param {string} statusText - Status text to display
 */
function disablePermissionCard(requestId, statusText) {
    const card = document.getElementById('perm-card-' + requestId);
    if (card) {
        // Disable all buttons
        const buttons = card.querySelectorAll('button');
        buttons.forEach(btn => {
            btn.disabled = true;
            btn.style.opacity = '0.5';
        });
        
        // Add status indicator
        const statusDiv = document.createElement('div');
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
}

/**
 * Check if permission card functions are available
 */
function checkPermissionSupport() {
    console.log('[Permission] Permission card support loaded');
    return {
        showPermissionCard: typeof showPermissionCard === 'function',
        selectScope: typeof selectScope === 'function',
        grantPermission: typeof grantPermission === 'function',
        denyPermission: typeof denyPermission === 'function'
    };
}

// Export for use in other scripts
if (typeof module !== 'undefined' && module.exports) {
    module.exports = {
        showPermissionCard,
        selectScope,
        grantPermission,
        grantLimited,
        denyPermission,
        disablePermissionCard,
        checkPermissionSupport
    };
}
