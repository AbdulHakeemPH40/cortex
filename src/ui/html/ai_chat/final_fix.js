const fs = require('fs');
let content = fs.readFileSync('script.js', 'utf8');
const lines = content.split('\n');

console.log('Analyzing structure to find where initMarked() should close...');

// Track brace depth starting from line 473 (marked.use)
let depth = 0;
let inMarkedUse = false;
let closeLocation = -1;

for (let i = 0; i < 800; i++) {
    const line = lines[i];
    
    if (i === 472) { // Line 473 (0-indexed: 472)
        inMarkedUse = true;
        console.log('Starting marked.use at line', i + 1);
    }
    
    if (inMarkedUse && i > 472) {
        const opens = (line.match(/{/g) || []).length;
        const closes = (line.match(/}/g) || []).length;
        const oldDepth = depth;
        depth += opens - closes;
        
        // We're looking for when depth returns to -1 (one less than marked.use({ which added +1)
        // But we need to account for renderer: { which adds another +1
        
        if (i >= 770 && i <= 780 && depth <= 0) {
            console.log(`Line ${i+1}: depth ${oldDepth} -> ${depth}, line: "${line.trim()}"`);
            if (depth === -2 && line.trim() === '});') {
                closeLocation = i;
                console.log('*** Found potential closing at line', i + 1);
            }
        }
    }
}

// Since the structure is: marked.use({ renderer: { ... } })
// We need depth to go from +2 back to 0
// That means we need: });  (closes renderer object with }, then closes use({ with })

// Actually, let me just manually find the right spot
// After renderProjectTree ends at line 774, there should be more renderer methods
// OR the renderer object should close

// Let me check what's at line 775-780
console.log('\nLines 774-780:');
for (let i = 773; i < 780; i++) {
    console.log(`${i+1}: ${lines[i]}`);
}
