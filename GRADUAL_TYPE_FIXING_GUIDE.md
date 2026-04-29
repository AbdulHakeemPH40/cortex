# 📅 Gradual Type Fixing Guide

## The Strategy: Fix Types Organically

**Don't stop development to fix types!** Instead, integrate type fixing into your normal workflow.

---

## 🎯 **Daily Routine (15 minutes)**

### **Step 1: Get Today's Tasks**
```bash
python daily_type_fixer.py
```

**Output**:
```
🎯 Fix these 5 errors today:

❌ Error #1:
   File: src/agent/src/constants/oauth.py:16
   Type: reportUndefinedVariable
   Issue: "OauthConfig" is not defined
   💡 Fix: Add import or define variable
```

### **Step 2: Fix ONE Error**
Open the file, fix the error, test it:

```python
# BEFORE (has error)
def get_oauth_config() -> OauthConfig:  # Error: OauthConfig not defined
    return config

# AFTER (fixed - 30 seconds)
from typing import TypedDict

class OauthConfig(TypedDict):
    client_id: str
    client_secret: str

def get_oauth_config() -> OauthConfig:
    return config
```

### **Step 3: Commit**
```bash
git add src/agent/src/constants/oauth.py
git commit -m "fix: Add OauthConfig type definition"
```

### **Step 4: Repeat Tomorrow**
```bash
python daily_type_fixer.py  # Get new 5 tasks
```

---

## 📊 **Expected Timeline**

### **Month 1: Quick Wins (78 → ~50 errors)**

**Week 1**: Fix undefined variables (15 errors)
- Run `daily_type_fixer.py` each morning
- Fix 3-5 errors/day (takes 15 minutes)
- Focus on: missing imports, undefined variables

**Week 2**: Fix Optional access (10 errors)
- Add None checks
- Pattern: `if obj: obj.method()`

**Week 3**: Fix type hints (10 errors)
- Add missing type annotations
- Fix wrong return types

**Week 4**: Fix argument types (5 errors)
- Correct function parameter types
- Ensure type compatibility

**Result**: ~50 errors remaining

---

### **Month 2: While Developing (~50 → ~25 errors)**

**Rule**: Every file you edit, fix its type errors too

```python
# You're working on a feature in editor.py
# BEFORE you leave the file:
git diff  # See what you changed
python pyright_audit.py src/ui/components/editor.py  # Check for type errors
# Fix any new errors you introduced
git commit
```

**Benefit**: Code you touch gets better over time

**Result**: ~25 errors remaining

---

### **Month 3: Stub Improvement (~25 → ~10 errors)**

Replace auto-generated stubs with real implementations:

```python
# BEFORE (auto-generated stub)
class MCPClient:
    async def connect(self) -> None:
        pass  # TODO

# AFTER (working implementation)
class MCPClient:
    async def connect(self) -> None:
        """Connect to MCP server."""
        self.connected = True
        await self._establish_connection()
```

**Result**: ~10 errors remaining

---

### **Month 4+: Polish (~10 → 0 errors)**

Fix remaining edge cases:
- Complex type unions
- Generic types
- Protocol implementations

**Result**: 0 errors! 🎉

---

## 🛠️ **Practical Examples**

### **Example 1: Missing Import (30 seconds)**

**Error**: `Import ".services.mcp.types" could not be resolved`

**Fix**:
```bash
# Create stub file
mkdir -p src/agent/src/services/mcp
echo '"""MCP types stub."""\nfrom typing import Any, Dict\n\n__all__ = []' > src/agent/src/services/mcp/types.py
```

---

### **Example 2: Undefined Variable (1 minute)**

**Error**: `"OauthConfig" is not defined`

**Fix**:
```python
# Add type definition
from typing import TypedDict

class OauthConfig(TypedDict):
    client_id: str
    client_secret: str
    redirect_uri: str
```

---

### **Example 3: Optional Access (1 minute)**

**Error**: `"setText" is not a known attribute of "None"`

**Fix**:
```python
# BEFORE
widget.setText("hello")  # Error: widget could be None

# AFTER
if widget is not None:
    widget.setText("hello")
```

---

### **Example 4: Wrong Type Hint (2 minutes)**

**Error**: `Type "float" is not assignable to declared type "int"`

**Fix**:
```python
# BEFORE
def calculate_score() -> int:
    return 95.5  # Error: float returned, int expected

# AFTER
def calculate_score() -> float:
    return 95.5
```

---

## 📈 **Tracking Progress**

### **Check Progress**
```bash
python daily_type_fixer.py --progress
```

**Output**:
```
📊 TYPE FIXING PROGRESS

✓ pyright_report.json               4456 errors
✓ pyright_report_final.json         4288 errors
✓ pyright_report_v2.json            4288 errors
✓ pyright_report_new.json             78 errors
```

### **Visual Progress**
```
Week 1:  ████████████████████ 78 errors
Week 2:  ████████████████░░░░ 63 errors
Week 3:  ██████████████░░░░░░ 50 errors
Week 4:  ████████████░░░░░░░░ 40 errors
Month 2: ██████████░░░░░░░░░░ 25 errors
Month 3: ████████░░░░░░░░░░░░ 15 errors
Month 4: ██████░░░░░░░░░░░░░░ 10 errors
Target:  ░░░░░░░░░░░░░░░░░░░░ 0 errors 🎉
```

---

## 💡 **Pro Tips**

### **1. Use Pre-commit Hook**
Create `.git/hooks/pre-commit`:
```bash
#!/bin/bash
# Check types on files you're committing
FILES=$(git diff --cached --name-only | grep '\.py$')
if [ -n "$FILES" ]; then
    echo "Checking types on modified files..."
    python -m pyright $FILES || echo "⚠️  Type warnings found"
fi
```

### **2. IDE Integration**
If using VS Code or PyCharm:
- Enable pyright/PyLance
- See errors inline as you code
- Fix them immediately

### **3. Batch Similar Errors**
```bash
# Find all files with same error type
python -c "
import json
data = json.load(open('pyright_report_new.json'))
errors = [d for d in data['diagnostics'] if 'OptionalMemberAccess' in d.get('rule', '')]
files = set(e['file'] for e in errors)
print('\n'.join(sorted(files)))
"
```

### **4. Create Fix Scripts**
For repetitive fixes, create scripts:
```python
#!/usr/bin/env python3
"""Fix all OptionalMemberAccess in one file."""
import re
from pathlib import Path

file = Path('src/ui/components/editor.py')
content = file.read_text()

# Pattern: variable.method() -> if variable: variable.method()
# (Simplified - needs careful handling)
```

---

## 🎯 **Success Metrics**

### **Weekly Goals**
- ✅ Fix 5-10 errors per week
- ✅ Spend max 15 minutes/day
- ✅ Don't break existing functionality
- ✅ Commit after each fix

### **Monthly Goals**
- ✅ Reduce errors by 25%
- ✅ Improve stub implementations
- ✅ Add type hints to new code
- ✅ Document type patterns

### **Quarterly Goals**
- ✅ <50 errors total
- ✅ All critical modules typed
- ✅ CI/CD checks types
- ✅ Team follows type standards

---

## 🚨 **What NOT to Do**

❌ **Don't** spend a week fixing all errors
❌ **Don't** stop feature development
❌ **Don't** make huge refactoring commits
❌ **Don't** ignore test coverage
❌ **Don't** break working code

✅ **Do** fix errors gradually
✅ **Do** integrate with normal workflow
✅ **Do** make small, focused commits
✅ **Do** test after each fix
✅ **Do** improve code quality over time

---

## 📝 **Daily Checklist**

```
Morning (5 minutes):
□ Run: python daily_type_fixer.py
□ Pick 1-2 easiest errors
□ Note files to edit

During Development (10 minutes):
□ Fix errors in files you're editing
□ Add type hints to new code
□ Test changes

End of Day (5 minutes):
□ Run: python pyright_audit.py
□ Note error count
□ Commit changes
□ Update progress
```

---

## 🎉 **The End Goal**

After 3-4 months:

```
✅ 0 pyright errors
✅ Full type coverage
✅ Clean, maintainable code
✅ Better IDE autocomplete
✅ Fewer runtime bugs
✅ Easier refactoring
✅ Self-documenting code
```

**But most importantly**: You achieved this **without stopping development** or disrupting your workflow!

---

## 🚀 **Start Today**

```bash
# 1. Get today's tasks
python daily_type_fixer.py

# 2. Fix the first error (takes 30 seconds)

# 3. Commit
git add .
git commit -m "fix: Add missing type definitions"

# 4. Repeat tomorrow!
```

**Remember**: Consistency beats intensity. 15 minutes/day > 8 hours/weekend! 💪
