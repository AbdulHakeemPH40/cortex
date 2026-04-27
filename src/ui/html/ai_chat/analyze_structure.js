const fs = require('fs');
let content = fs.readFileSync('script.js', 'utf8');
const lines = content.split('\n');

console.log('Total lines:', lines.length);

// The initMarked() function starts at line 459 (index 458)
// It contains marked.use({ at line 473 (index 472)
// But it never closes!

// We need to find where initMarked() should logically end.
// Looking at the code, there's a large object definition that ends around line 945
// That object is INSIDE marked.use({ renderer: { ... } })

// Let's find the right place to close it
// The object ending with '};' at line 945 (index 944) is the FOLDER_ICON_MAP
// which is NOT part of marked.use

// Actually, let me trace the structure more carefully
// I'll look for where the renderer configuration should end

let depth = 0;
let markedUseStart = -1;
let initMarkedStart = -1;

for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    
    if (i === 458 && line.includes('function initMarked()')) {
        initMarkedStart = i;
        console.log('Found initMarked at line', i + 1);
    }
    
    if (i === 472 && line.includes('marked.use({')) {
        markedUseStart = i;
        console.log('Found marked.use at line', i + 1);
    }
    
    // Track depth after these points
    if (i > 472 && i < 1000) {
        const opens = (line.match(/{/g) || []).length;
        const closes = (line.match(/}/g) || []).length;
        depth += opens - closes;
        
        // Look for where depth returns to the level after marked.use({
        if (depth === 0 && i > 500 && line.trim() === '});') {
            console.log('Potential close for marked.use at line', i + 1);
            console.log('  Context:', line);
            console.log('  Next line:', lines[i + 1]);
            console.log('  Line after:', lines[i + 2]);
        }
    }
}

// The issue is clear: marked.use({ opens at 473 but never closes
// We need to find the last renderer method and close it properly

// Let me search for the pattern where renderer methods end
// Looking for the structure: renderer: { code: ..., table: ..., ... }

console.log('\nSearching for renderer closure patterns...');
