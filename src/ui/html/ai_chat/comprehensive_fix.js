const fs = require('fs');
let content = fs.readFileSync('script.js', 'utf8');
const lines = content.split('\n');

console.log('Applying comprehensive fix...');

// 1. Add missing closing braces after line 774 (index 773)
// Find the line "return html;" followed by "}" which ends renderProjectTree
let insertIndex = -1;
for (let i = 770; i < 780; i++) {
    if (lines[i].trim() === '}' && lines[i-1] && lines[i-1].includes('return html')) {
        insertIndex = i + 1;
        break;
    }
}

if (insertIndex === -1) {
    console.error('Could not find insertion point!');
    process.exit(1);
}

console.log('Inserting closing braces after line', insertIndex);

// Insert the closing braces
lines.splice(insertIndex, 0, '});', '}');

// 2. Fix corrupted regex patterns (replace \n that got converted to actual newlines)
let fixedCount = 0;
for (let i = 0; i < lines.length; i++) {
    // Look for the broken pattern: text = text.replace(/
    // followed by {4,}/g, '
    // followed by empty lines
    // followed by ');
    if (lines[i] && lines[i].includes('text = text.replace(/') && 
        lines[i+1] && lines[i+1].includes('{4,}/g,')) {
        
        // Replace this broken multi-line pattern with the correct one
        lines[i] = lines[i].replace(/text = text\.replace\(\//, "text = text.replace(/\\n{4,}/g, '\\n\\n\\n'); // FIXED");
        
        // Remove the continuation lines
        let removeCount = 0;
        for (let j = i + 1; j < lines.length; j++) {
            if (lines[j].trim() === '' || lines[j].includes("');") || lines[j].includes('{4,}/g')) {
                removeCount++;
            } else {
                break;
            }
        }
        lines.splice(i + 1, removeCount);
        fixedCount++;
        console.log('Fixed regex at line', i + 1);
    }
}

console.log('Fixed', fixedCount, 'regex patterns');

// Write the fixed content
fs.writeFileSync('script.js', lines.join('\n'));
console.log('File saved successfully!');
