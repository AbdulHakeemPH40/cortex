const fs = require('fs');
let content = fs.readFileSync('script.js', 'utf8');

// Fix the corrupted regex - replace the broken pattern with the correct one
const brokenPattern = /text = text\.replace\(\/[\s\n]*\{4,\}\/g, '[\s\n]*'\);/;
const fixedPattern = `text = text.replace(/\\n{4,}/g, '\\n\\n\\n');`;

content = content.replace(brokenPattern, fixedPattern);

fs.writeFileSync('script.js', content);
console.log('Fixed regex pattern');
