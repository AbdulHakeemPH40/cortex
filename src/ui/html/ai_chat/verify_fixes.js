// Run this in browser console (F12) to verify all fixes are working

(function verifyFixes() {
    console.log("=== 🔍 CORTEX CHAT FIX VERIFICATION ===\n");
    
    var allGood = true;
    
    // Test 1: Check marked.js
    if (typeof marked !== 'undefined') {
        console.log("✅ marked.js: Loaded");
        if (typeof initMarked === 'function') {
            console.log("✅ initMarked(): Function exists");
            try {
                initMarked();
                console.log("✅ initMarked(): Executed successfully");
            } catch(e) {
                console.error("❌ initMarked(): Execution failed -", e.message);
                allGood = false;
            }
        } else {
            console.error("❌ initMarked(): NOT DEFINED - This is the main bug!");
            allGood = false;
        }
    } else {
        console.error("❌ marked.js: NOT LOADED - Check script tags in aichat.html");
        allGood = false;
    }
    
    // Test 2: Check highlight.js
    if (typeof hljs !== 'undefined') {
        console.log("✅ highlight.js: Loaded");
    } else {
        console.error("❌ highlight.js: NOT LOADED - Check script tags");
        allGood = false;
    }
    
    // Test 3: Check QWebChannel
    if (typeof QWebChannel !== 'undefined') {
        console.log("✅ QWebChannel: Library loaded");
    } else {
        console.error("❌ QWebChannel: NOT LOADED - Check qwebchannel.js path");
        allGood = false;
    }
    
    // Test 4: Check bridge
    if (typeof bridge !== 'undefined' && bridge !== null) {
        console.log("✅ Bridge: Connected with", Object.keys(bridge).length, "methods");
    } else {
        console.warn("⚠️  Bridge: Not ready yet (this is normal during initial load)");
    }
    
    // Test 5: Check DOM elements
    var input = document.getElementById('chatInput');
    var sendBtn = document.getElementById('sendBtn');
    
    if (input) {
        console.log("✅ chatInput: Element found");
        if (input.onkeydown) {
            console.log("✅ chatInput: Enter key handler attached");
        } else {
            console.warn("⚠️  chatInput: No keydown handler (might not be initialized yet)");
        }
    } else {
        console.error("❌ chatInput: Element NOT FOUND - Check aichat.html structure");
        allGood = false;
    }
    
    if (sendBtn) {
        console.log("✅ sendBtn: Element found");
        if (sendBtn.onclick) {
            console.log("✅ sendBtn: Click handler attached");
        } else {
            console.warn("⚠️  sendBtn: No click handler (might not be initialized yet)");
        }
    } else {
        console.error("❌ sendBtn: Element NOT FOUND - Check aichat.html structure");
        allGood = false;
    }
    
    // Test 6: Check terminal
    if (typeof Terminal !== 'undefined') {
        console.log("✅ xterm.js: Loaded");
    } else {
        console.warn("⚠️  xterm.js: NOT LOADED (terminal might not be available)");
    }
    
    console.log("\n=== 📊 SUMMARY ===");
    if (allGood) {
        console.log("✅ ALL CRITICAL CHECKS PASSED!");
        console.log("🎉 Chat should be fully functional!");
    } else {
        console.log("❌ SOME CHECKS FAILED - See errors above");
        console.log("📝 Review: Docs/CRITICAL_CHAT_FIX_SUMMARY.md");
    }
    
    console.log("\n=== 🔧 QUICK TEST ===");
    console.log("Try sending a message now:");
    console.log("1. Type 'test' in the chat input");
    console.log("2. Press Enter or click Send");
    console.log("3. Check console for 'Message sent to bridge successfully'");
    
})();
