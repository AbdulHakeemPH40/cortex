:
// UPDATED: Enhanced load and save with file-based fallback
// Load chats for current project - tries multiple storage methods
function loadProjectChats() {
    var key = getStorageKey();
    var loadedChats = [];
    
    console.log('[CHAT] LOAD - Starting load attempt with key:', key);
    
    // Attempt to load chats using multiple methods
    
    // Method 1: localStorage (fastest, but sometimes not persistent)
    try {
        var localData = localStorage.getItem(key);
        if (localData) {
            console.log('[CHAT] LOAD - Found data in localStorage (' + localData.length + ' chars)');
            loadedChats = JSON.parse(localData);
            console.log('[CHAT] LOAD - localStorage: Parsed', loadedChats.length, 'chat(s)');
            
            // If we got data from localStorage, return it immediately
            if (loadedChats.length > 0) {
                console.log('[CHAT] LOAD - Using localStorage data');
                return loadedChats;
            }
        } else {
            console.log('[CHAT] LOAD - localStorage: No data found');
        }
    } catch (e) {
        console.error('[CHAT] LOAD ERROR (localStorage):', e.message);
    }
    
    // Method 2: File-based storage (reliable fallback)
    // This will be called asynchronously after bridge is ready
    console.log('[CHAT] LOAD - Need file-based fallback or no data found');
    return loadedChats;
}

// Load chats from file using Python bridge (called after bridge initialization)
function loadChatsFromFileAsync(callback) {
    var key = getStorageKey();
    console.log('[CHAT] LOAD from file - Key:', key);
    
    if (!bridge || typeof bridge.load_chats_from_file !== 'function') {
        console.warn('[CHAT] Bridge not ready for file load');
        callback([]);
        return;
    }
    
    try {
        // Call Python method synchronously (Qt WebChannel makes it sync)
        var result = bridge.load_chats_from_file(key);
        if (result && result !== "[]") {
            console.log('[CHAT] LOAD from file - Data found (' + result.length + ' chars)');
            var parsed = JSON.parse(result);
            console.log('[CHAT] LOAD from file - Parsed', parsed.length, 'chat(s)');
            callback(parsed);
        } else {
            console.log('[CHAT] LOAD from file - No data');
            callback([]);
        }
    } catch (e) {
        console.error('[CHAT] LOAD from file ERROR:', e.message);
        callback([]);
    }
}

// Save chats for current project - uses both storage methods
function saveProjectChats(chatList) {
    var key = getStorageKey();
    var data = JSON.stringify(chatList);
    var saveSuccess = false;
    
    console.log('[CHAT] SAVE - Saving', chatList.length, 'chat(s),', data.length, 'chars');
    
    // Method 1: localStorage
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
                console.log('[CHAT] SAVE - File storage: OK');
                saveSuccess = true;
            } else {
                console.error('[CHAT] SAVE - File storage: FAILED -', result);
            }
        } else {
            console.warn('[CHAT] SAVE - Bridge not ready for file storage');
        }
    } catch (e) {
        console.error('[CHAT] SAVE ERROR (file):', e.message);
    }
    
    if (!saveSuccess) {
        console.error('[CHAT] SAVE - ALL METHODS FAILED - chats will be lost on restart!');
    }
    
    return saveSuccess;
}