
    /**
     * Tool Operation Card Controller
     * Manages dynamic cards for create/edit/delete/read/terminal operations
     */
    (function() {
        'use strict';
        
        const activeCards = new Map();
        
        /**
         * Show a tool operation card
         * @param {string} operationId - Unique ID for this operation
         * @param {string} type - Type: 'create', 'edit', 'delete', 'read', 'terminal'
         * @param {string} fileName - Name of the file being operated on
         * @param {string} status - Status: 'pending', 'running', 'completed', 'failed'
         */
        window.showToolOperation = function(operationId, type, fileName, status = 'pending') {
            // Remove existing card with same ID if present
            if (activeCards.has(operationId)) {
                removeToolCard(operationId);
            }
            
            const card = createToolCard(operationId, type, fileName, status);
            const chatContainer = document.querySelector('.chat-messages') || document.querySelector('#chat-container');
            
            if (chatContainer) {
                chatContainer.appendChild(card);
                activeCards.set(operationId, card);
                
                // Auto-scroll to show new card
                chatContainer.scrollTop = chatContainer.scrollHeight;
            }
            
            console.log('[ToolCard] Showed:', operationId, type, fileName);
        };
        
        /**
         * Update the status of an existing tool operation card
         * @param {string} operationId - The operation ID
         * @param {string} newStatus - New status: 'running', 'completed', 'failed'
         */
        window.updateToolOperation = function(operationId, newStatus) {
            const card = activeCards.get(operationId);
            if (!card) {
                console.warn('[ToolCard] Card not found:', operationId);
                return;
            }
            
            const statusEl = card.querySelector('.tool-operation-status');
            if (statusEl) {
                statusEl.className = 'tool-operation-status ' + newStatus;
                statusEl.textContent = newStatus;
            }
            
            // Remove completed cards after delay
            if (newStatus === 'completed' || newStatus === 'failed') {
                setTimeout(() => {
                    removeToolCard(operationId);
                }, 3000);
            }
            
            console.log('[ToolCard] Updated:', operationId, newStatus);
        };
        
        /**
         * Create a tool operation card element
         */
        function createToolCard(operationId, type, fileName, status) {
            const card = document.createElement('div');
            card.className = 'tool-operation-card ' + type;
            card.id = 'tool-op-' + operationId;
            
            const icons = {
                create: '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path><polyline points="14 2 14 8 20 8"></polyline><line x1="12" y1="18" x2="12" y2="12"></line><line x1="9" y1="15" x2="15" y2="15"></line></svg>',
                edit: '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"></path><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"></path></svg>',
                delete: '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"></polyline><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path></svg>',
                read: '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path><polyline points="14 2 14 8 20 8"></polyline></svg>',
                terminal: '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="4 17 10 11 4 5"></polyline><line x1="12" y1="19" x2="20" y2="19"></line></svg>'
            };
            
            const titles = {
                create: 'Creating file',
                edit: 'Editing file',
                delete: 'Deleting file',
                read: 'Reading file',
                terminal: 'Running command'
            };
            
            card.innerHTML = `
                <div class="tool-operation-icon">${icons[type] || icons.read}</div>
                <div class="tool-operation-content">
                    <div class="tool-operation-title">${titles[type] || 'Operation'}</div>
                    <div class="tool-operation-file">${fileName}</div>
                </div>
                <div class="tool-operation-status ${status}">${status}</div>
            `;
            
            return card;
        }
        
        /**
         * Remove a tool operation card with animation
         */
        function removeToolCard(operationId) {
            const card = activeCards.get(operationId);
            if (card) {
                card.classList.add('removing');
                setTimeout(() => {
                    if (card.parentNode) {
                        card.parentNode.removeChild(card);
                    }
                    activeCards.delete(operationId);
                }, 300);
            }
        }
        
        /**
         * Clear all tool operation cards
         */
        window.clearToolOperations = function() {
            activeCards.forEach((card, id) => {
                removeToolCard(id);
            });
        };
        
        console.log('[ToolCard] Controller initialized');
    })();
    
