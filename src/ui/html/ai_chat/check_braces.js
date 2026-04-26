const fs = require('fs');
const code = fs.readFileSync('script.js', 'utf8');
const lines = code.split('\n');

let depth = 0;
let depthHistory = [];

lines.forEach((line, i) => {
    const opens = (line.match(/{/g) || []).length;
    const closes = (line.match(/}/g) || []).length;
    const oldDepth = depth;
    depth += opens - closes;
    
    // Track when depth changes
    if (opens !== closes) {
        depthHistory.push({
            line: i + 1,
            depth: oldDepth,
            newDepth: depth,
            change: opens - closes,
            content: line.trim().substring(0, 100)
        });
    }
});

console.log('Final depth:', depth);
console.log('\nLast 20 depth changes:');
depthHistory.slice(-20).forEach(h => {
    console.log(`Line ${h.line}: depth ${h.depth} -> ${h.newDepth} (${h.change > 0 ? '+' : ''}${h.change})`);
    console.log(`  ${h.content}`);
});
