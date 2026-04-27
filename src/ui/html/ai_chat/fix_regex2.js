const fs = require('fs');
let content = fs.readFileSync('script.js', 'utf8');
const lines = content.split('\n');

// Find and fix lines 5241-5245 (0-indexed: 5240-5244)
// Replace the broken regex with the correct one
if (lines[5240].includes('text = text.replace(/') && lines[5241].includes('{4,}/g,')) {
    lines[5240] = '    text = text.replace(/\\n{4,}/g, \'\\n\\n\\n\');';
    // Remove lines 5241-5244 (the broken continuation)
    lines.splice(5241, 4);
    console.log('Fixed broken regex at line 5241');
} else {
    console.log('Pattern not found at expected location');
}

fs.writeFileSync('script.js', lines.join('\n'));
console.log('File updated');
