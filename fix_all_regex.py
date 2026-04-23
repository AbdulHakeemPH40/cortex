# Fix all broken newline regex patterns in script.js

file_path = r'c:\Users\Hakeem1\OneDrive\Desktop\Cortex_Ai_Agent\Cortex\src\ui\html\ai_chat\script.js'

with open(file_path, 'r', encoding='utf-8') as f:
    content = f.read()

# Count occurrences before
broken_count = content.count("/{4,}/g")
print(f"Found {broken_count} broken regex pattern(s): /{{4,}}/g")

# Fix: Replace broken regex with proper escaped version
# Pattern 1: /\n{4,}/g should replace 4+ newlines with 3 newlines
content = content.replace(
    "text = text.replace(/{4,}/g, '');",
    "text = text.replace(/\\n{4,}/g, '\\n\\n\\n');"
)

# Verify fix
with open(file_path, 'r', encoding='utf-8') as f:
    verify = f.read()
    
fixed_count = verify.count("\\n{4,}/g")
print(f"✅ Fixed! Now has {fixed_count} correct regex pattern(s): /\\n{{4,}}/g")

print("\nDone! The JS syntax error should be resolved.")
