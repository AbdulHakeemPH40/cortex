# AskUserQuestion Integration Plan

## Current status
`AskUserQuestion` is **partially integrated**, not fully end-to-end.

What already exists:
- agent-side tool registration exists in `src/agent/src/tool_registry.py`
- tool references exist in bundled skills
- bridge dispatch path for `AskUserQuestion` exists in `src/ai/agent_bridge.py`
- main window connects agent question signals to chat UI and connects chat answers back to the bridge in `src/main_window.py`
- AI chat Python widget exposes `show_question(...)` and `answer_question_requested` in `src/ui/components/ai_chat.py`
- web UI already contains `aichat.html`, `style.css`, and `script.js`
- JavaScript already implements `window.showQuestionCard(...)` and answer submission through `window.bridge.on_answer_question(...)`
- `aichat.html` already includes the required container and asset loading:
  - `#chatMessages`
  - `style.css`
  - `qrc:///qtwebchannel/qwebchannel.js`
  - `script.js`
- `aichat.html` already includes a reusable permission-card template

So the UI layer is **not missing from scratch**. The HTML, CSS, and JS structure already exists.

## UI integration assessment

### What already exists in the UI

#### HTML
File:
- `src/ui/html/ai_chat/aichat.html`

Confirmed present:
- main chat container `#chatMessages`
- stylesheet include for `style.css`
- Qt WebChannel script include
- app script include for `script.js`
- permission card template: `#permission-card-template`

This means the page already has the DOM structure needed for interactive cards.

#### JavaScript
File:
- `src/ui/html/ai_chat/script.js`

Confirmed present:
- `window.showQuestionCard(info)`
- rendering logic for:
  - text questions
  - confirm questions
  - choice questions
  - permission-style questions
- `window.submitInteractionAnswer(id, answer, scope)`
- `window.submitInteractionByInput(id)`
- callback into Python through:
  - `window.bridge.on_answer_question(id, answerWithScope)`

This means the UI JavaScript already supports rendering AskUserQuestion cards and sending answers back to Python.

#### CSS
Files:
- `src/ui/html/ai_chat/style.css`
- possibly additional inline styles inside `aichat.html`

Current finding:
- the base AI chat CSS definitely exists and is loaded
- permission-card styling likely exists in `aichat.html` inline sections and/or other CSS blocks
- however, a direct grep of `style.css` did **not** confirm selectors such as:
  - `.interaction-card`
  - `.interaction-header`
  - `.interaction-input`
  - `.interaction-btn`
  - `.interaction-choice-btn`
  - `.permission-status`

So the JS behavior exists, but not all AskUserQuestion-specific styling is confirmed inside `style.css` itself.

### UI conclusion
The UI integration is **partially already implemented**:
- HTML: present
- JS: present
- CSS: base chat CSS is present, but dedicated AskUserQuestion card styling is not fully confirmed in `style.css`

So the UI is **close**, but still needs verification and likely cleanup/hardening.

## Confirmed integration flow today

### Existing forward flow
1. agent/tool decides to ask a user question
2. bridge dispatches AskUserQuestion in `src/ai/agent_bridge.py`
3. main window receives `user_question_requested`
4. `_on_ai_question_requested(...)` builds a payload
5. `AIChatWidget.show_question(info)` forwards to bridge/UI layer
6. JS `window.showQuestionCard(info)` renders a card inside `#chatMessages`
7. user clicks or types an answer
8. JS calls `window.bridge.on_answer_question(id, answerWithScope)`
9. Python `on_answer_question(...)` emits `answer_question_requested`
10. main window connects that signal to `self._ai_agent.user_responded`

### Main problem in the return flow
The current bridge still does **not clearly complete the suspend/resume loop** after the user answers.
That is the main reason AskUserQuestion is still not fully integrated.

## Issues still blocking full integration

### 1) Agent suspend/resume is incomplete
Even though UI answer submission exists, the bridge must reliably:
- track pending question IDs
- map answer to the correct waiting tool call
- resume the agent/tool execution
- return a final tool result into the agent loop

Without that, the feature is only visual/UI-complete, not execution-complete.

### 2) Signal contract must be verified and normalized
Need to ensure these layers agree on the same payload shape:
- `agent_bridge.user_question_requested`
- `main_window._on_ai_question_requested(...)`
- `AIChatWidget.show_question(...)`
- JS `window.showQuestionCard(info)`
- JS `window.bridge.on_answer_question(id, answer)`
- Python `on_answer_question(...)`
- bridge `user_responded(...)`

The contract should consistently use:
- `tool_call_id` or `request_id`
- `question`
- `type`
- `choices`
- `default`
- optional metadata like `details`, `scope`, `tool_name`

### 3) CSS hardening is still needed
Even though question UI exists, the integration plan should ensure dedicated styles for:
- generic question cards
- confirm buttons
- choice buttons
- text input row
- answered state
- error state
- permission status state
- accessibility states: hover, focus, disabled

This is especially important because current JS references classes that were not confirmed in `style.css`.

### 4) Tool-side reliability still must be verified
The AskUserQuestion feature is only fully integrated if all layers work:
- tool definition loads
- tool registry exposes it
- bridge dispatch works
- UI renders correctly
- answers resume execution correctly

## Implementation plan

### Phase 1 — Verify and normalize UI contract
Files:
- `src/ai/agent_bridge.py`
- `src/main_window.py`
- `src/ui/components/ai_chat.py`
- `src/ui/html/ai_chat/script.js`

Tasks:
- define one canonical payload schema for question requests
- define one canonical payload schema for answers
- ensure `tool_call_id` / `request_id` naming is consistent
- ensure permission questions and normal questions use the same transport shape where possible
- ensure WebChannel bridge method names match exactly between JS and Python

Deliverable:
- a stable agent → UI → answer callback contract

### Phase 2 — Complete suspend/resume behavior
Files:
- `src/ai/agent_bridge.py`
- possibly agent execution loop files under `src/agent/src`

Tasks:
- store pending AskUserQuestion calls by ID
- pause execution until the user answer arrives
- on `user_responded(...)`, resolve the pending question
- feed the answer back into the agent/tool continuation path
- remove stale pending question state after completion/cancel/error

Deliverable:
- AskUserQuestion actually blocks for input and then resumes execution

### Phase 3 — Harden AI chat UI
Files:
- `src/ui/html/ai_chat/aichat.html`
- `src/ui/html/ai_chat/style.css`
- `src/ui/html/ai_chat/script.js`

Tasks:
- verify all JS-referenced classes have matching CSS
- add missing styles for `.interaction-*` classes if absent
- ensure the question card matches the existing chat design system
- support keyboard submit for text answers
- support disabled state after answer submission
- support duplicate-submission prevention
- support clearer answered/success/error states
- ensure long question text wraps correctly
- ensure choices and permission buttons are responsive

Deliverable:
- polished and reliable AskUserQuestion UI across HTML/CSS/JS

### Phase 4 — Verify tool-side loading and registration
Files:
- `src/agent/src/tools/AskUserQuestionTool/AskUserQuestionTool.py`
- `src/agent/src/tools/AskUserQuestionTool/prompt.py`
- `src/agent/src/tool_registry.py`

Tasks:
- confirm all imports are valid
- confirm the tool object builds correctly
- confirm the registry exposes it in the runtime path actually used
- confirm tool schema matches the payload expected by the bridge/UI

Deliverable:
- tool layer reliably loads and executes

### Phase 5 — End-to-end testing
Test cases:
1. text question
   - agent asks open-ended question
   - user types response
   - agent resumes and uses answer
2. confirm question
   - yes/no decision path
3. choice question
   - predefined options
4. permission-like question
   - allow/deny/always flow
5. cancellation/empty answer path
6. invalid/stale request ID path
7. multiple pending questions protection

Deliverable:
- proven end-to-end AskUserQuestion behavior

## Recommended document updates during implementation
As fixes are completed, this file should be updated to record:
- exact payload contract
- exact files changed
- whether `.interaction-*` CSS was added to `style.css` or kept inline in `aichat.html`
- whether pending-question state is single-question-only or multi-question capable
- whether permission and AskUserQuestion share a unified interaction-card component

## Definition of done
AskUserQuestion is fully integrated only when all are true:
- the tool loads without import/runtime errors
- the tool is available in the agent runtime
- the bridge can dispatch question requests reliably
- the AI chat UI can render the question card reliably
- HTML/CSS/JS assets required for the card are confirmed present and loaded
- the user can answer through the chat UI
- the answer is routed back to the exact pending tool call
- the agent resumes automatically after answer submission
- duplicate answers and stale IDs are handled safely
- at least one real end-to-end test passes for text, confirm, and choice flows

## Short final assessment
### Is the UI already there?
**Mostly yes.**
The AI chat HTML, JS, and base CSS already exist, and the JavaScript already includes AskUserQuestion rendering/submission behavior.

### Is AskUserQuestion fully integrated today?
**No.**
It is **UI-present but execution-partial**. The major remaining work is making the backend/bridge resume the waiting agent flow correctly and hardening/confirming the specific CSS + signal contract.