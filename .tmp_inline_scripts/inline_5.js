
    /**
     * Agent Mode Controller
     * Manages Think/Read/Explore/Surf/Dive modes with animations
     */
    (function() {
        'use strict';
        
        const MODES = ['think', 'read', 'explore', 'surf', 'dive'];
        let currentMode = null;
        let completedModes = [];
        
        /**
         * Show the mode indicator
         */
        window.showAgentMode = function() {
            const indicator = document.getElementById('agent-mode-indicator');
            if (indicator) {
                indicator.style.display = 'block';
                indicator.classList.add('fade-in');
            }
        };
        
        /**
         * Hide the mode indicator
         */
        window.hideAgentMode = function() {
            const indicator = document.getElementById('agent-mode-indicator');
            if (indicator) {
                indicator.style.display = 'none';
            }
            // Reset all modes
            currentMode = null;
            completedModes = [];
            updateModeDisplay();
        };
        
        /**
         * Set the current active mode
         * @param {string} mode - One of: think, read, explore, surf, dive
         */
        window.setAgentMode = function(mode) {
            if (!MODES.includes(mode)) {
                console.warn('[AgentMode] Invalid mode:', mode);
                return;
            }
            
            // Mark previous modes as completed
            const modeIndex = MODES.indexOf(mode);
            completedModes = MODES.slice(0, modeIndex);
            currentMode = mode;
            
            updateModeDisplay();
            
            console.log('[AgentMode] Mode changed to:', mode);
        };
        
        /**
         * Update the visual display of modes
         */
        function updateModeDisplay() {
            const indicators = document.querySelectorAll('.mode-indicator');
            
            indicators.forEach(el => {
                const mode = el.getAttribute('data-mode');
                
                // Reset classes
                el.classList.remove('active', 'completed');
                
                if (mode === currentMode) {
                    el.classList.add('active');
                } else if (completedModes.includes(mode)) {
                    el.classList.add('completed');
                }
            });
        }
        
        /**
         * Progress to next mode automatically
         */
        window.progressAgentMode = function() {
            const currentIndex = MODES.indexOf(currentMode);
            const nextIndex = currentIndex + 1;
            
            if (nextIndex < MODES.length) {
                window.setAgentMode(MODES[nextIndex]);
            }
        };
        
        /**
         * Use-case based mode triggers
         */
        window.triggerThinkMode = function() {
            window.showAgentMode();
            window.setAgentMode('think');
        };
        
        window.triggerReadMode = function() {
            window.showAgentMode();
            window.setAgentMode('read');
        };
        
        window.triggerExploreMode = function() {
            window.showAgentMode();
            window.setAgentMode('explore');
        };
        
        window.triggerSurfMode = function() {
            window.showAgentMode();
            window.setAgentMode('surf');
        };
        
        window.triggerDiveMode = function() {
            window.showAgentMode();
            window.setAgentMode('dive');
        };
        
        /**
         * Trigger mode based on agent activity type
         * @param {string} activityType - Activity type (thinking, reading, searching, writing, analyzing)
         */
        window.triggerModeByActivity = function(activityType) {
            const activityMap = {
                'thinking': 'think',
                'planning': 'think',
                'reasoning': 'think',
                'reading': 'read',
                'file_read': 'read',
                'searching': 'explore',
                'browsing': 'surf',
                'writing': 'dive',
                'editing': 'dive',
                'analyzing': 'explore',
                'debugging': 'dive'
            };
            
            const mode = activityMap[activityType] || 'think';
            window.showAgentMode();
            window.setAgentMode(mode);
        };
        
        console.log('[AgentMode] Controller initialized');
    })();
    
