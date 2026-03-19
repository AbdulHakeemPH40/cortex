import re

# Read the file
with open('src/ui/html/ai_chat/script.js', 'r', encoding='utf-8') as f:
    content = f.read()

# Find and replace the saveProjectChats function
old_pattern = r'''// Save chats for current project
function saveProjectChats\(chatList\) \{
    var key = getStorageKey\(\);
    try \{
        var data = JSON\.stringify\(chatList\);
        console\.log\('\[CHAT\] SAVE - Key:', key\);
        console\.log\('\[CHAT\] SAVE - Saving', chatList\.length, 'chat\(s\),', data\.length, 'chars'\);
        localStorage\.setItem\(key, data\);
        // Verify save worked
        var verify = localStorage\.getItem\(key\);
        console\.log\('\[CHAT\] SAVE - Verified:', verify \? 'OK \(' \+ verify\.length \+ ' chars\)' : 'FAILED'\);
    \} catch \(e\) \{
        console\.error\('\[CHAT\] SAVE ERROR:', e\.message\);
    \}
\}'''

new_function = '''// Save chats for current project - saves to both localStorage and file
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
            var result = bridge.save_chats_to_file(key, data);
            if (result === "OK") {
                console.log('[CHAT] SAVE - File backup: SUCCESS');
            } else {
                console.error('[CHAT] SAVE - File backup: FAILED:', result);
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
}'''

# Replace the pattern
new_content = re.sub(old_pattern, new_function, content, flags=re.MULTILINE)

if new_content == content:
    print("Pattern not found - check the exact formatting")
else:
    # Write back
    with open('src/ui/html/ai_chat/script.js', 'w', encoding='utf-8') as f:
        f.write(new_content)
    print("✅ Successfully updated saveProjectChats function")
