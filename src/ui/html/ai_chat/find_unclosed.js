const fs = require('fs');
const code = fs.readFileSync('script.js', 'utf8');
const lines = code.split('\n');

let depth = 0;
let depth1Line = null, depth2Line = null, depth3Line = null;
let depth1Content = '', depth2Content = '', depth3Content = '';

lines.forEach((line, i) => {
    const opens = (line.match(/{/g) || []).length;
    const closes = (line.match(/}/g) || []).length;
    const oldDepth = depth;
    depth += opens - closes;
    
    // Track when we enter depth 1, 2, 3
    if (oldDepth === 0 && depth === 1) {
        depth1Line = i + 1;
        depth1Content = line.trim().substring(0, 120);
    }
    if (oldDepth === 1 && depth === 2) {
        depth2Line = i + 1;
        depth2Content = line.trim().substring(0, 120);
    }
    if (oldDepth === 2 && depth === 3) {
        depth3Line = i + 1;
        depth3Content = line.trim().substring(0, 120);
    }
});

console.log('Final depth:', depth);
if (depth >= 3) {
    console.log('\n*** UNCLOSED BLOCKS ***');
    console.log(`Depth 1 opened at line ${depth1Line}: ${depth1Content}`);
    console.log(`Depth 2 opened at line ${depth2Line}: ${depth2Content}`);
    console.log(`Depth 3 opened at line ${depth3Line}: ${depth3Content}`);
}
