# 🔧 DeepSeek Model Selection Fix - Performance Mode Bypass

## 🐛 Problem

When selecting **DeepSeek V4 Pro** from the model dropdown, the system was **ignoring the selection** and routing to **Mistral** instead.

### Terminal Log Evidence:

```
Line 343: [MainWindow] Model changed to: deepseek-v4-pro (provider: deepseek) ✅ CORRECT!
Line 346: [AIChat] Routing text-only message through performance mode: performance
Line 346: [AIChat] Text routing: provider=mistral, model=mistral-medium-latest ❌ WRONG!
Line 351: [MainWindow] Model changed to: mistral-medium-latest (provider: mistral) ❌ OVERRIDDEN!
Line 358: [BRIDGE] provider=mistral model=mistral-medium-latest ❌ WRONG PROVIDER!
```

**User Intent**: Select DeepSeek V4 Pro  
**Actual Behavior**: System used Mistral Medium instead

---

## 🔍 Root Cause Analysis

### **The Performance Mode System**

The `ai_chat.py` file has a **performance mode routing system** that was designed to automatically select Mistral models based on performance preferences:

```python
# PERFORMANCE_CONFIGS - Hardcoded to Mistral only!
PERFORMANCE_CONFIGS = {
    PerformanceMode.EFFICIENT: PerformanceConfig(
        main_agent_model="mistral-small-latest",  # ❌ Mistral only
    ),
    PerformanceMode.AUTO: PerformanceConfig(
        main_agent_model="mistral-small-latest",  # ❌ Mistral only
    ),
    PerformanceMode.PERFORMANCE: PerformanceConfig(
        main_agent_model="mistral-medium-latest",  # ❌ Mistral only
    ),
    PerformanceMode.ULTIMATE: PerformanceConfig(
        main_agent_model="mistral-large-latest",  # ❌ Mistral only
    ),
}
```

### **The Bypass Problem**

When a user sends a message, the code flow was:

```python
# In ai_chat.py _send_message()
perf_mode = get_performance_mode_from_settings()  # e.g., "performance"
config = get_mode_config(perf_mode)

# ❌ PROBLEM: Always routes to performance mode if not "auto"
if perf_mode != PerformanceMode.AUTO:
    self._process_text_message_through_performance(text, config)
    return  # ← Never reaches agent_bridge with user's model!
```

The `_process_text_message_through_performance()` method then **hardcoded Mistral**:

```python
def _process_text_message_through_performance(self, text, config):
    provider_name = "mistral"  # ❌ HARDCODED!
    model_id = config.main_agent_model or "mistral-small-latest"  # ❌ IGNORES USER SELECTION!
    
    log.info(f"[AIChat] Text routing: provider={provider_name}, model={model_id}")
    # Routes to Mistral, ignoring user's DeepSeek selection
```

### **Why This Happened**

The performance mode system was designed when **Mistral was the only provider**. When DeepSeek was added, the system wasn't updated to **respect user model selection** from the dropdown.

---

## ✅ Fix Applied

### **File**: [ai_chat.py](file:///c:/Users/Hakeem1/OneDrive/Desktop/Cortex_Ai_Agent/Cortex/src/ui/components/ai_chat.py#L1827-L1857)

Added a check **before** the performance mode routing to detect if the user selected a **non-Mistral model**:

```python
# Check if performance mode routing should be used
perf_mode_str = self._get_performance_mode_from_settings()
perf_mode = get_performance_mode(perf_mode_str)
config = get_mode_config(perf_mode)

# ✅ NEW: Check if user selected a non-Mistral model (e.g., DeepSeek)
# If so, bypass performance mode and use agent_bridge directly
# This respects user's explicit model selection from dropdown
try:
    from src.config.settings import get_settings
    settings = get_settings()
    # Check if there's a user-selected model in settings
    user_model = settings.get("ai", "model_id", default="")
    if user_model and not user_model.startswith("mistral") and not user_model.startswith("codestral"):
        # User selected a non-Mistral model (e.g., deepseek-v4-pro)
        # Bypass performance mode and use agent_bridge directly
        log.info(f"[AIChat] User selected non-Mistral model: {user_model}, bypassing performance mode")
        context = ""
        if self._get_code_context:
            context = self._get_code_context()
        self.message_sent.emit(text, context)
        return  # ← Exit early, skip performance mode
except Exception as e:
    log.warning(f"[AIChat] Failed to check user model selection: {e}")

# If performance mode is not 'auto' or has special model selection, route through performance system
if perf_mode != PerformanceMode.AUTO or config.main_agent_model or config.vision_model:
    log.info(f"[AIChat] Routing text-only message through performance mode: {perf_mode.value}")
    self._process_text_message_through_performance(text, config)
    return
```

---

## 🔄 New Data Flow

### **Before (Broken)**:

```
1. User selects "DeepSeek V4 Pro" in UI
   ↓
2. main_window._on_model_changed() sets: provider="deepseek", model_id="deepseek-v4-pro"
   ↓
3. User sends message "Hello"
   ↓
4. ai_chat.py checks performance mode: "performance"
   ↓
5. ❌ Routes to _process_text_message_through_performance()
   ↓
6. ❌ Hardcodes: provider="mistral", model="mistral-medium-latest"
   ↓
7. ❌ Sends to Mistral API (wrong!)
```

### **After (Fixed)**:

```
1. User selects "DeepSeek V4 Pro" in UI
   ↓
2. main_window._on_model_changed() sets: provider="deepseek", model_id="deepseek-v4-pro"
   ↓
3. Settings saved: ai.model_id = "deepseek-v4-pro"
   ↓
4. User sends message "Hello"
   ↓
5. ✅ ai_chat.py checks: user_model = settings.get("ai", "model_id")
   ↓
6. ✅ Detects: "deepseek-v4-pro" doesn't start with "mistral"
   ↓
7. ✅ Bypasses performance mode entirely!
   ↓
8. ✅ Emits message_sent signal to agent_bridge
   ↓
9. ✅ agent_bridge uses provider="deepseek", model="deepseek-v4-pro"
   ↓
10. ✅ Sends to DeepSeek API (correct!)
```

---

## 🧪 Testing

### **Test 1: DeepSeek V4 Pro Selection**

```
1. Select "DeepSeek V4 Pro" from model dropdown
2. Expected log:
   [MainWindow] Model changed to: deepseek-v4-pro (provider: deepseek)
3. Send message: "Hello"
4. Expected log:
   [AIChat] User selected non-Mistral model: deepseek-v4-pro, bypassing performance mode
   [BRIDGE] provider=deepseek model=deepseek-v4-pro
5. ✅ Should use DeepSeek API, not Mistral
```

### **Test 2: DeepSeek V4 Flash Selection**

```
1. Select "DeepSeek V4 Flash" from model dropdown
2. Expected log:
   [MainWindow] Model changed to: deepseek-v4-flash (provider: deepseek)
3. Send message: "Hello"
4. Expected log:
   [AIChat] User selected non-Mistral model: deepseek-v4-flash, bypassing performance mode
   [BRIDGE] provider=deepseek model=deepseek-v4-flash
5. ✅ Should use DeepSeek API, not Mistral
```

### **Test 3: Mistral Model Selection (Regression)**

```
1. Select "Mistral Medium" from model dropdown
2. Expected log:
   [MainWindow] Model changed to: mistral-medium-latest (provider: mistral)
3. Send message: "Hello"
4. Expected log:
   [AIChat] Routing text-only message through performance mode: performance
   [AIChat] Text routing: provider=mistral, model=mistral-medium-latest
5. ✅ Should still use performance mode for Mistral models
```

### **Test 4: Performance Mode with Mistral**

```
1. Select "Mistral Large" from model dropdown
2. Set performance mode to "Ultimate"
3. Send message: "Hello"
4. Expected log:
   [AIChat] Routing text-only message through performance mode: ultimate
   [AIChat] Text routing: provider=mistral, model=mistral-large-latest
5. ✅ Performance mode should work for Mistral models
```

---

## 📋 Model Detection Logic

The fix uses simple prefix matching to determine if a model is Mistral:

```python
# Mistral models (use performance mode):
- mistral-small-latest
- mistral-medium-latest
- mistral-large-latest
- codestral-latest

# Non-Mistral models (bypass performance mode):
- deepseek-v4-pro         ✅
- deepseek-v4-flash       ✅
- gpt-4o                  ✅
- claude-3-5-sonnet       ✅
- qwen-vl-max             ✅
```

---

## 🎯 Why This Matters

### **User Experience:**
- ✅ **User intent is respected** - selecting DeepSeek actually uses DeepSeek
- ✅ **No silent overrides** - system doesn't ignore user choices
- ✅ **Clear logging** - shows when performance mode is bypassed

### **Cost Impact:**
- ❌ **Before**: User selects DeepSeek → Charged Mistral rates ($3-8/1M)
- ✅ **After**: User selects DeepSeek → Charged DeepSeek rates ($0.10-0.50/1M)
- 💰 **Savings**: Up to **95% cheaper** with DeepSeek V4 Flash!

### **Architecture:**
- ✅ **Backward compatible** - Mistral performance modes still work
- ✅ **Provider agnostic** - works with any future provider (OpenAI, Anthropic, etc.)
- ✅ **Settings-driven** - uses existing settings infrastructure

---

## 🔗 Related Files

- [ai_chat.py#L1827-L1857](file:///c:/Users/Hakeem1/OneDrive/Desktop/Cortex_Ai_Agent/Cortex/src/ui/components/ai_chat.py#L1827-L1857) - Performance mode routing (FIXED)
- [main_window.py#L5699-L5721](file:///c:/Users/Hakeem1/OneDrive/Desktop/Cortex_Ai_Agent/Cortex/src/main_window.py#L5699-L5721) - Provider detection logic
- [agent_bridge.py#L2788-L2796](file:///c:/Users/Hakeem1/OneDrive/Desktop/Cortex_Ai_Agent/Cortex/src/ai/agent_bridge.py#L2788-L2796) - Provider type detection
- [deepseek_provider.py](file:///c:/Users/Hakeem1/OneDrive/Desktop/Cortex_Ai_Agent/Cortex/src/ai/providers/deepseek_provider.py) - DeepSeek API implementation

---

## 📝 Technical Details

### **Settings Key**:
```python
# When user selects model from dropdown:
settings.set("ai", "model_id", "deepseek-v4-pro")
settings.set("ai", "provider", "deepseek")

# ai_chat.py reads this to determine routing:
user_model = settings.get("ai", "model_id", default="")
```

### **Performance Modes Still Work**:
```python
# For Mistral models, performance mode routing still applies:
- Efficient → mistral-small-latest
- Auto → auto-select based on query complexity
- Performance → mistral-medium-latest
- Ultimate → mistral-large-latest

# For non-Mistral models, performance mode is bypassed:
- deepseek-v4-pro → uses DeepSeek directly
- deepseek-v4-flash → uses DeepSeek directly
- gpt-4o → would use OpenAI directly (when implemented)
```

---

## ✅ Verification Checklist

- [x] Non-Mistral model detection added
- [x] Performance mode bypass implemented
- [x] Mistral models still use performance mode
- [x] Logging added for debugging
- [ ] **Test with DeepSeek V4 Pro**
- [ ] **Test with DeepSeek V4 Flash**
- [ ] **Verify Mistral performance modes still work**
- [ ] **Check logs show correct provider**

---

## 🚀 Future Improvements

### **1. Provider-Aware Performance Modes**
Instead of bypassing performance mode entirely, future work could make performance modes provider-aware:

```python
# Future: Provider-specific performance configs
PERFORMANCE_CONFIGS = {
    "mistral": {
        "efficient": "mistral-small-latest",
        "performance": "mistral-medium-latest",
        "ultimate": "mistral-large-latest",
    },
    "deepseek": {
        "efficient": "deepseek-v4-flash",
        "performance": "deepseek-v4-pro",
        "ultimate": "deepseek-v4-pro",
    },
}
```

### **2. User Preference Persistence**
Remember user's provider preference separately from performance mode:

```python
settings.set("ai", "preferred_provider", "deepseek")
settings.set("ai", "performance_mode", "ultimate")
```

### **3. Model Capability Detection**
Auto-detect model capabilities and adjust routing:

```python
if model.supports_vision:
    # Use vision pipeline
elif model.context_length > 100_000:
    # Use long-context pipeline
```

---

**Fixed**: April 29, 2026  
**Status**: ✅ Code fixed, ready for testing  
**Impact**: Respects user's explicit model selection from dropdown  
**Next Step**: Restart app and test with DeepSeek model selection
