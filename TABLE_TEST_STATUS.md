# Table Rendering Test Status

## 📊 Current Test Results

### ✅ PASSED (Regex in script.js)
| Test | Description | Status | In script.js? |
|------|-------------|--------|---------------|
| **T1** | Perfect Table (baseline) | ✅ PASS | ✅ YES |
| **B4** | Bold markers merged with text | ✅ PASS | ✅ YES |
| **B7** | Code block without backticks | ✅ PASS | ✅ YES |
| **B8** | Heading merged with paragraph | ✅ PASS | ✅ YES |

### ❌ FAILED (Regex in table_test.html ONLY - testing phase)
| Test | Description | Status | New Fix # | In script.js? |
|------|-------------|--------|-----------|---------------|
| **B1** | Missing newline between rows + empty cells `| | |` | ❌ FAIL | FIX 7, 9 | ❌ NO |
| **B2** | Text merged with table header | ❌ FAIL | FIX 12, 13 | ❌ NO |
| **B3** | Separator line at wrong position | ❌ FAIL | FIX 8, 9, 13 | ❌ NO |
| **B5** | Large multi-column table with line breaks | ❌ FAIL | FIX 10, 14 | ❌ NO |
| **B6** | Double pipes merging rows `||` | ❌ FAIL | FIX 10 | ❌ NO |
| **T2** | Bold merged with table | ❌ FAIL | FIX 1, 11 | ❌ NO |
| **T3** | Heading merged with table | ❌ FAIL | FIX 1, 11 | ❌ NO |
| **T4** | Triple pipes in table rows `|||` | ❌ FAIL | FIX 3 | ❌ NO |
| **T5** | Clean 2-column table | ❌ FAIL | - (should pass) | ❌ NO |
| **T6** | Tab-separated content | ❌ FAIL | FIX 12 | ❌ NO |

---

## 🔄 Workflow

```
behavior.txt (raw broken data)
    ↓
table_test.html (ALL test cases + NEW regex fixes)
    ↓ Test in browser
    ↓
If PASS → Copy regex to script.js
If FAIL → Keep in table_test.html, write new fix
    ↓ Repeat until all PASS
```

---

## 📝 Regex Fix Status

### ✅ Production (script.js lines 4556-4628)
- FIX 1: Split text ending with `:` before table
- FIX 2: Fix `||` between header and separator
- FIX 3: Fix `|||` triple pipes
- FIX 4: Fix `||` between cells (with guard)
- FIX 5: Ensure blank line before table
- FIX 6: Normalize pipe spacing

### 🧪 Testing Only (table_test.html lines 116-166)
- FIX 7: Fix empty cells `| | |`
- FIX 8: Fix separator merged with next row
- FIX 9: Fix text followed by pipe without newline
- FIX 10: Fix double pipes between ANY rows
- FIX 11: Fix bold/text merged without space
- FIX 12: Convert tab-separated to pipe tables
- FIX 13: Fix trailing `| ---` at end of line
- FIX 14: Ensure blank line before tables

---

## 🎯 Next Steps

1. **Open table_test.html in browser**
2. **Check which tests now PASS with FIX 7-14**
3. **For each PASS:** Copy that FIX to script.js
4. **For each FAIL:** Analyze why, write new FIX in table_test.html
5. **Repeat** until all 14 tests PASS
6. **Sync all passing FIX** to script.js

---

## 📂 Files

- **Test File:** `src/ui/html/ai_chat/table_test.html` (307 lines)
- **Production:** `src/ui/html/ai_chat/script.js` (line 4494-4633)
- **Source Data:** `behavior.txt` (77 lines)

---

**Last Updated:** Testing phase with FIX 7-14 added to table_test.html
