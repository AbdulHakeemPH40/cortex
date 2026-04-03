
      // Function to check and apply fallback hljs styles
      function applyHljsStyles() {
        var testEl = document.createElement('span');
        testEl.className = 'hljs-keyword';
        testEl.style.position = 'absolute';
        testEl.style.left = '-9999px';
        document.body.appendChild(testEl);
        var computedColor = window.getComputedStyle(testEl).color;
        document.body.removeChild(testEl);
        
        // If color is not set (empty/default), use fallback styles
        if (!computedColor || computedColor === 'rgba(0, 0, 0, 0)' || computedColor === 'rgb(0, 0, 0)') {
          console.log('[Cortex] CDN hljs styles failed, using fallback');
          var fallback = document.getElementById('hljs-fallback-styles');
          if (fallback) fallback.disabled = false;
        } else {
          console.log('[Cortex] hljs styles loaded from CDN');
        }
      }
      
      // Load hljs CSS with onload handler
      var hljsLink = document.createElement('link');
      hljsLink.rel = 'stylesheet';
      hljsLink.href = 'https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/styles/dracula.min.css';
      hljsLink.onload = function() { 
        console.log('[Cortex] hljs CSS loaded from CDN');
        applyHljsStyles();
      };
      hljsLink.onerror = function() { 
        console.log('[Cortex] hljs CSS CDN failed, using fallback');
        applyHljsStyles();
      };
      document.head.appendChild(hljsLink);
      
      // Load universal syntax highlighting CSS
      var syntaxHighlightingLink = document.createElement('link');
      syntaxHighlightingLink.rel = 'stylesheet';
      syntaxHighlightingLink.href = 'syntax-highlighting.css';
      document.head.appendChild(syntaxHighlightingLink);
      
      if (window.hljs) {
        hljs.configure({
          ignoreUnescapedHTML: true,
          languages: ['python','javascript','typescript','bash','json','html','css','sql','cpp','java','rust','go']
        });
      }
      
      // Syntax highlighting with embedded language support for HTML
      window.highlightCodeWithEmbedded = function(code, lang) {
        // If explicitly HTML, try to detect and highlight embedded languages
        if (lang === 'html' || lang === 'xml') {
          // Check if code contains <style> or <script> tags
          if (code.includes('<style') || code.includes('<script')) {
            // Use highlight-auto to let hljs detect embedded languages
            return hljs.highlightAuto(code).value;
          }
        }
        
        // Normal highlight
        try {
          return hljs.highlight(code, { language: hljs.getLanguage(lang) ? lang : 'plaintext' }).value;
        } catch (e) {
          return code.replace(/</g, '&lt;').replace(/>/g, '&gt;');
        }
      };
    
