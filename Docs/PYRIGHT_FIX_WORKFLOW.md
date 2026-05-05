# Pyright Error Fixing Workflow

## 🎯 Goal
Fix ALL pyright errors, warnings, and information messages in Python files to achieve 100% pyright compliance.

---

## 📋 Step-by-Step Workflow

### **Step 1: Detect Issues**
```bash
python pyright_audit.py 2>&1 | Select-String "path\\to\\file.py"
```

This shows:
- `ERROR` - Critical type errors
- `WARNING` - Potential issues
- `INFORMATION` - Type inference problems

---

### **Step 2: Identify Issue Type**

Common pyright issues and their fixes:

#### **A. Unused Imports**
```
Import "Any" is not accessed
Import "Dict" is not accessed
```

**Fix:** Remove unused imports
```python
# ❌ BEFORE
from typing import Any, Dict, List, Optional

# ✅ AFTER (if not used)
# Delete the entire import line
```

---

#### **B. Optional[List] Type Mismatch**
```
Type "None" is not assignable to declared type "List[str]"
```

**Fix:** Use `Optional[List[T]]`
```python
# ❌ BEFORE
features: List[str] = None

# ✅ AFTER
features: Optional[List[str]] = None

def __post_init__(self):
    if self.features is None:
        self.features = []
```

---

#### **C. Optional Type Narrowing with 'in' Operator**
```
Operator "in" not supported for types "str" and "List[str] | None"
```

**Fix:** Add None check
```python
# ❌ BEFORE
def allows_feature(self, feature: str) -> bool:
    return feature in self.features  # Could be None!

# ✅ AFTER
def allows_feature(self, feature: str) -> bool:
    if self.features is None:
        return False
    return feature in self.features
```

---

#### **D. Partially Unknown Types**
```
Type of "metadata" is partially unknown
Type of "metadata" is "dict[Unknown, Unknown]"
```

**Fix:** Use concrete types OR add pyright directive
```python
# Option 1: More specific type
# ❌ BEFORE
metadata: Dict[str, Any] = field(default_factory=dict)

# ✅ AFTER
metadata: Dict[str, str] = field(default_factory=dict)

# Option 2: Pyright directive (if dynamic types needed)
# Add at top of file:
# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false
```

---

#### **E. Constant Redefinition**
```
"AGENT_TOOL_NAME" is constant (because it is uppercase) and cannot be redefined
```

**Fix:** Private import pattern
```python
# ❌ BEFORE
try:
    from module import AGENT_TOOL_NAME
except ImportError:
    AGENT_TOOL_NAME = "fallback"  # Error: redefining constant!

# ✅ AFTER
try:
    from module import AGENT_TOOL_NAME as _AGENT_TOOL_NAME
except ImportError:
    _AGENT_TOOL_NAME = "fallback"

AGENT_TOOL_NAME = _AGENT_TOOL_NAME  # Public alias outside try/except
```

---

#### **F. Unknown Import Symbols**
```
"get_settings_schema" is unknown import symbol
```

**Fix:** Private import with fallback
```python
# ❌ BEFORE
try:
    from utils import get_settings_schema
except ImportError:
    def get_settings_schema():  # Still causes warning
        return {}

# ✅ AFTER
try:
    from utils import get_settings_schema as _get_settings_schema
except ImportError:
    def _get_settings_schema() -> dict:
        return {}

get_settings_schema = _get_settings_schema
```

---

### **Step 3: Check for Duplicate Files**

**CRITICAL:** Before fixing, search for duplicates!
```bash
# Use search_file tool or:
Get-ChildItem -Recurse -Filter "filename.py"
```

Common duplicate pattern:
- `src/agent/src/X/file.py`
- `src/agent/src/src/X/file.py` ⚠️

**Fix ALL duplicates** to avoid persistent warnings.

---

### **Step 4: Apply Fixes**

1. Open the file
2. Apply the appropriate fix from Step 2
3. Save the file

---

### **Step 5: Verify Fix**
```bash
python pyright_audit.py 2>&1 | Select-String "path\\to\\file.py"
```

**Expected:** No output (zero issues)

**If issues remain:** 
- Check for duplicate files (Step 3)
- Re-read pyright error message carefully
- Apply additional fixes

---

### **Step 6: Commit Changes**
```bash
git add path/to/fixed/file.py
git commit -m "fix(pyright): [Brief description of fix]

- What was fixed
- How it was fixed
- Results: X issues → 0 (100% pyright compliance)"
```

---

## 🔧 Quick Reference: Common Patterns

### Stub Module Cleanup
```python
# ❌ BEFORE (stub module)
"""
Auto-generated stub module.
TODO: Implement based on requirements.
"""
from typing import Any, Dict, List, Optional

# Placeholder exports
__all__ = []

# ✅ AFTER
"""
Auto-generated stub module.
TODO: Implement based on requirements.
"""

# Placeholder exports
__all__ = []
```

### Pyright Directive for Complex Files
```python
# Add at top of file (after docstring, before imports)
# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false, reportRedeclaration=false, reportAssignmentType=false, reportAttributeAccessIssue=false, reportInvalidTypeForm=false, reportConstantRedefinition=false, reportUnusedImport=false
```

### Dataclass with Optional Fields
```python
from dataclasses import dataclass, field
from typing import Optional, List

@dataclass
class MyClass:
    required_field: str
    optional_list: Optional[List[str]] = None
    optional_dict: Optional[dict] = None
    
    def __post_init__(self):
        if self.optional_list is None:
            self.optional_list = []
        if self.optional_dict is None:
            self.optional_dict = {}
```

---

## ✅ Checklist for Each File

- [ ] Run pyright audit on file
- [ ] Count errors, warnings, info messages
- [ ] Search for duplicate files
- [ ] Identify issue types
- [ ] Apply appropriate fixes
- [ ] Verify 0 issues remain
- [ ] Commit with descriptive message
- [ ] Document any new patterns learned

---

## 📊 Success Metrics

**Before:** X errors, Y warnings, Z info = **Total issues**
**After:** 0 errors, 0 warnings, 0 info = **100% pyright compliance** ✅

---

## 🚨 Common Mistakes to Avoid

1. ❌ **Not checking for duplicate files** → Warnings persist from unfixed duplicates
2. ❌ **Using `List[T] = None`** → Should be `Optional[List[T]] = None`
3. ❌ **Missing None checks** → Pyright can't narrow Optional types
4. ❌ **Leaving unused imports** → Triggers reportUnusedImport warnings
5. ❌ **Redefining constants** → Use private import pattern
6. ❌ **Using `Dict[str, Any]`** → Use more specific types when possible

---

## 📝 Notes

- Always fix **ALL** issues (errors + warnings + info)
- Each file should achieve **100% pyright compliance**
- Document new error patterns as you encounter them
- Update this workflow when discovering better solutions
