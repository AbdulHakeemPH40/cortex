
        window.mermaidLoaded = false;
        window.initMermaid = function() {
            if (window.mermaidLoaded) return Promise.resolve();
            return new Promise((resolve) => {
                var script = document.createElement('script');
                script.src = 'https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.min.js';
                script.onload = function() {
                    if (window.mermaid) {
                        mermaid.initialize({ startOnLoad: false, theme: 'dark' });
                        window.mermaidLoaded = true;
                    }
                    resolve();
                };
                script.onerror = function() { resolve(); };
                document.head.appendChild(script);
            });
        };
    
