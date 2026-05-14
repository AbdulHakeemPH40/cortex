# Cortex AI Agent IDE — Security Audit Report

**Date**: May 13, 2026
**Version**: 1.0.15
**Scope**: Full codebase audit — API key storage, data-at-rest, network surfaces, logging, bundled binaries, installer

---

## Severity Legend

| Level | Meaning |
|-------|---------|
| 🔴 **CRITICAL** | Direct API key exposure or theft path. Must fix before distribution. |
| 🟠 **HIGH** | Significant attack surface. Should fix soon. |
| 🟡 **MEDIUM** | Risk exists but requires local access or unlikely conditions. |
| 🟢 **LOW** | Minor concern — sanitization or hardening opportunity. |
| ℹ️ **INFO** | Design observation — not a vulnerability but worth documenting. |

---

## 1. API Key Management

### 🔴 Finding 1.1 — Weak Encryption for `keys.enc` (Deterministic Key Derivation)

**File**: `src/core/key_manager.py` lines 52–65

```python
system_data = f"{os.environ.get('USERNAME', 'user')}_{os.environ.get('COMPUTERNAME', 'pc')}"
salt = b'cortex_salt_v1'  # In production, use random salt stored separately
kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=100000,)
key = base64.urlsafe_b64encode(kdf.derive(system_data.encode()))
```

**Issue**: The encryption key for `~/.cortex/keys.enc` is derived from:
- **USERNAME** + **COMPUTERNAME** (both visible in `systeminfo`/`whoami`)
- A **hardcoded static salt** (`b'cortex_salt_v1'` — same on every install worldwide)
- 100,000 PBKDF2 iterations (good, but moot given the above)

**Attack Scenario**: Any process (or malware) running on the victim's PC can read USERNAME and COMPUTERNAME, read `~/.cortex/keys.enc`, and decrypt it using the exact same algorithm. The static salt means there is ZERO per-installation entropy. **This is effectively security-by-obscurity.**

**Remediation**:
- Use Windows DPAPI (`cryptography.hazmat.primitives.ciphers` or `win32crypt.CryptProtectData`) which ties encryption to the user's login credential
- Or generate a random salt per installation, stored in `~/.cortex/.salt` with restricted ACLs
- Or use `keyring` library (wraps Windows Credential Manager natively)

---

### 🔴 Finding 1.2 — API Keys in Plaintext `.env` File

**File**: `.env` (not in repo, but generated per installation)

**Issue**: All API keys (`MISTRAL_API_KEY`, `DEEPSEEK_API_KEY`, `OPENAI_API_KEY`, etc.) are stored in **unencrypted plaintext** in the `.env` file at the Cortex installation directory. Any process with read access to the user's file system can steal all API keys with a single `type .env`.

**Attack Scenario**:
- Malware scans `~\AppData\Local\Programs\Cortex\.env` or the install directory
- Another user on the same PC (if installed to a shared location) reads the file
- A malicious npm package / Python package with filesystem access reads `.env`
- IT admin doing backups inadvertently captures the file

**Current Mitigations**: `.gitignore` excludes `.env` from source control (good). The installer copies `.env.example` → `.env` on first install using `onlyifdoesntexist` flag.

**Remediation**:
- Store API keys exclusively in Windows Credential Manager via `keyring` library
- Delete the `.env` file after first-run migration to secure storage
- Or at minimum: set restrictive NTFS ACLs on `.env` (readable only by current user, not `Everyone`/`Authenticated Users`)

---

### 🔴 Finding 1.3 — API Keys Fetched FROM Remote Server (logic-practice.com)

**File**: `src/agent/src/utils/auth.py` lines 127–183, 406–446

```python
DEFAULT_SERVER_URL = "https://logic-practice.com"

class LogicPracticeServer:
    async def fetch_api_keys(self) -> Dict[str, str]:
        url = f"{self.config.server_url}/api/v1/keys"
        # ... fetches ALL provider API keys from logic-practice.com
```

**Issue**: Cortex has a **centralized API-key distribution system**. The `CortexAuthManager` priority chain is:
1. Environment variables → 2. `logic-practice.com` server → 3. Local cache → 4. Helper commands

**Attack Scenarios**:
- **Server compromise**: If `logic-practice.com` is breached, ALL users' API keys for ALL providers are exposed
- **MITM/DNS poisoning**: If an attacker redirects `logic-practice.com` to their own server, they harvest every user's API keys
- **Insider threat**: Anyone with access to the `logic-practice.com` backend can read all API keys in plaintext
- **TLS interception**: Corporate proxy with TLS inspection could log API keys from the server response

**Remediation**:
- NEVER send user's own API keys TO a third-party server. Keys should only flow from user → provider
- If this is a "bring your own keys" model: the server should be optional, clearly disclosed, and NEVER receive user keys
- If this is a managed service: keys should be encrypted client-side before transmission (the server should hold encrypted blobs it cannot decrypt)
- Add a prominent UI toggle: "Use Cortex Cloud Key Management" — default OFF
- Document this behavior in a privacy policy / EULA shown during installation

---

### 🔴 Finding 1.4 — Code Content Sent to SiliconFlow for Embeddings (Every Search)

**File**: `src/core/siliconflow_embeddings.py` lines 35–49

```python
class SiliconFlowEmbeddings:
    API_URL = "https://api.siliconflow.com/v1/embeddings"
```

**File**: `src/core/semantic_search.py` line 58

```python
self.embeddings_provider = get_siliconflow_embeddings()
```

**Issue**: Every time the AI performs a semantic search (triggered on every agentic message), **your code content is sent to `api.siliconflow.com`** in China. This includes:
- Your project file contents
- Function signatures, code structure
- Potentially proprietary/confidential source code

**Attack Scenarios**:
- SiliconFlow could log and analyze all embedding requests, building a profile of your codebase
- Network intermediary could intercept the embedding API calls
- No local-only embedding fallback exists (the system ALWAYS calls cloud)

**Remediation**:
- Add a **local embeddings** option (e.g., `all-MiniLM-L6-v2` via `sentence-transformers`, already imported in `src/agent/src/sentence_transformers.py`)
- Add a settings toggle: "Use local embeddings (offline)" vs "Cloud embeddings (SiliconFlow)"
- Rate-limit embedding calls to avoid accidental bulk exfiltration
- At minimum: clearly disclose this in the privacy notice

---

## 2. Local Data Storage

### 🟠 Finding 2.1 — SQLite Database Unencrypted (Chat History, Code, Files)

**File**: `src/core/database.py` lines 121–140

```python
db_path = str(cortex_dir / "cortex.db")
conn = sqlite3.connect(self.db_path)
```

**Issue**: The Cortex database at `~/.cortex/cortex.db` stores:
- **All chat messages** (user prompts + AI responses) — plaintext
- **Code chunks** (function bodies, class definitions) indexed from your projects — plaintext
- **File metadata** (paths, hashes, modification times)
- **Project memory** (key-value context store)
- **Embeddings vectors** (numerical, not directly readable)

The database uses **no encryption at rest** — no SQLCipher, no SEE, no page-level encryption.

**Attack Scenario**: Anyone with filesystem access to `~/.cortex/cortex.db` can read your entire chat history, including sensitive questions, code snippets, and AI analysis of your codebase.

**Remediation**:
- Use SQLCipher (open-source encrypted SQLite) with a key derived from Windows DPAPI
- Or encrypt individual sensitive columns (message content, code chunks) before INSERT
- Set restrictive NTFS ACLs on `~/.cortex/` directory

---

### 🟠 Finding 2.2 — Chat History JSON Files at `~/.cortex/chats/`

**File**: `src/core/chat_history.py` line 38

```python
self._json_dir = Path.home() / ".cortex" / "chats"
```

**Issue**: Chat history is also stored as JSON files in `~/.cortex/chats/` — unencrypted, human-readable.

**Remediation**: Same as 2.1 — encrypt at rest or restrict ACLs.

---

### 🟡 Finding 2.3 — `.cortex/settings.local.json` Contains Runtime Configuration

**File**: `.cortex/settings.local.json`

**Issue**: Contains sandbox configuration, feature flags, and potentially cached tokens. No sensitive API keys were found, but the file is writable and could be used for persistence by malware.

**Remediation**: Validate integrity of settings on load (checksum/hash against tampering).

---

## 3. Network Surfaces

### 🟠 Finding 3.1 — Live Preview Server Exposes Project Files

**File**: `src/core/live_server.py` lines 57–110

```python
self._server = ThreadingHTTPServer(("127.0.0.1", self._port), Handler)
```

**Issue**: The Live Preview HTTP server binds to **`127.0.0.1`** only (safe — not exposed to network). However:
- It serves the **entire project directory** — any file in the project root is accessible via HTTP
- There's **no path traversal protection** beyond what `SimpleHTTPRequestHandler` provides
- The server uses **zero authentication** — any process on the machine can `curl http://127.0.0.1:5500/../.env` if the `.env` is in the project directory

**Attack Scenario**: Local malware or a malicious browser extension could scan `localhost:5500-5599` and exfiltrate project files through the live server.

**Remediation**:
- Block access to dotfiles (`.env`, `.git`, `.cortex`) from the HTTP handler
- Add a `CORS` header restricting origins to `null` (file://) and the IDE's webview origin
- Kill the server when the preview tab is closed (currently it stays alive)

---

### 🟡 Finding 3.2 — QWebChannel IPC (Qt WebEngine → Python Bridge)

**File**: `src/ui/components/ai_chat.py`, `src/ui/components/webview_panel.py`

**Issue**: Qt WebChannel exposes Python objects to the Chromium webview's JavaScript context. This is the core IPC mechanism. If the webview loads untrusted content (XSS, malicious HTML preview), JavaScript could call exposed Python methods.

**Current Mitigations**:
- Webview loads from `file:///` (local HTML files bundled with the app)
- The preview browser is a separate webview
- Exposed methods appear to be validated on the Python side

**Remediation**:
- Audit all `@pyqtSlot` decorated methods for input validation
- Ensure preview webview has a SEPARATE, minimal QWebChannel (not the full IDE bridge)
- Add CSP (Content Security Policy) headers to AI chat HTML to prevent XSS

---

### 🟡 Finding 3.3 — `logic-practice.com` Telemetry / Analytics Endpoint

**File**: `src/agent/src/utils/auth.py`, `src/main_window.py` line 5229

```
DEFAULT_SERVER_URL = "https://logic-practice.com"
# Will be enabled when connecting to https://logic-practice.com backend
```

**Issue**: The application has infrastructure for communicating with `logic-practice.com` — a remote server under unknown control. The comment says "Will be enabled when connecting" but the code path exists and includes:
- API key fetching (see finding 1.3)
- OAuth token management
- Cloud AI subscriber checks

**Attack Scenarios**:
- If the server is compromised, it could push malicious configurations
- The server could enable/disable features remotely via API responses
- Telemetry data about usage patterns, model preferences, and project types could be collected

**Remediation**:
- Disclose ALL remote connections in a privacy policy
- Add a global "offline mode" toggle that blocks ALL outbound connections except to AI provider APIs
- Allow users to inspect what data is sent before it leaves the machine

---

## 4. Logging & Crash Artifacts

### 🟠 Finding 4.1 — `faulthandler` Crash Dump May Contain Secrets

**File**: `src/main.py` lines 136–148

```python
import faulthandler
crash_path = crash_dir / "crash.log"
_faulthandler.enable(file=_crash_fp, all_threads=True)
_faulthandler.dump_traceback_later(120, repeat=True, file=_crash_fp)
```

**Issue**: Python's `faulthandler` writes full stack traces for ALL threads to `~/.cortex/crash.log` on crash AND every 120 seconds. These stack traces include:
- Local variable values in some Python versions
- Function arguments (which could include API keys passed as parameters)
- Full call chains showing file paths and logic

**Attack Scenario**: Crash log is plaintext on disk. If an API key was passed as a function argument anywhere in the call stack, it appears in `crash.log`.

**Remediation**:
- Disable `faulthandler` in release builds (keep for debug builds only)
- Or redirect to a memory buffer that's wiped after successful shutdown
- If keeping for diagnostics: encrypt the crash log at rest

---

### 🟡 Finding 4.2 — `terminal.log` in Project Root

**File**: `terminal.log` at project root

**Issue**: A terminal log file at `c:\Users\Hakeem1\OneDrive\Desktop\Cortex_Ai_Agent\Cortex\terminal.log` captures ALL console output including error messages, API responses, and debug logs. It is excluded from `.gitignore` via `*.log` pattern (good) but persists on disk.

**Remediation**: Move logs to `~/.cortex/logs/` instead of project root. Auto-purge logs older than 7 days.

---

### 🟡 Finding 4.3 — API Key Prefix Logged in Clear Text

**File**: `src/ai/providers/openai_provider.py` line 96

```python
log.debug(f"Creating OpenAI client with key: {self._api_key[:10]}...")
```

**Issue**: The first 10 characters of the OpenAI API key are logged. While partial, this is still sensitive (combined with other data, could help reconstruct the key).

**Remediation**: Log only "sk-****" or hash the key for logging purposes.

---

## 5. Bundled Dependencies & Binary Exposure

### 🟡 Finding 5.1 — Node.js Runtime Bundled in Installer

**File**: `cortex.spec` line 57, `build.ps1` lines 74–82

```
('bin/node', 'bin/node'),
npm install --silent
```

**Issue**: A full Node.js runtime (`node.exe`) is bundled with the installer for LSP servers. This Node binary:
- Could have its own CVEs (version unknown — check `node --version` in `bin/node/`)
- Adds ~50MB to installer size
- Is another attack surface if a malicious package sneaks into `node_modules/`

**Current Mitigation**: `package.json` / `package-lock.json` lock dependency versions. `node_modules/` is in `.gitignore`.

**Remediation**:
- Document Node.js version and check for known CVEs at build time
- Run `npm audit` as part of the build script
- Consider using `pkg` or `nexe` to bundle only the needed LSP servers as standalone executables

---

### 🟡 Finding 5.2 — Large `agent/src/` Codebase (Sedimentary Code)

**Directory**: `src/agent/src/` (200+ files)

**Issue**: This directory appears to be a ported/adapted codebase (possibly from Claude Code or a similar agentic platform). It contains:
- `LogicPracticeServer` — remote API key management (see 1.3)
- `AuthManager`, `APIKeyManager` — multiple authentication layers
- `ApiKeyHelper` — shell command execution to retrieve keys
- `PrivacyLevel`, `Analytics` — telemetry infrastructure
- AWS, GCP, Azure credential management

**Many of these modules appear unused or partially integrated**, but they still increase the attack surface.

**Remediation**:
- Audit which `agent/src/` modules are actually called from `src/ai/` and `src/core/`
- Remove or isolate unused modules before packaging
- The `agent/src/` layer should be treated as untrusted until fully audited

---

### 🟡 Finding 5.3 — Subprocess Execution (Popen Patch)

**File**: `src/utils/runtime_hook_noconsole.py` lines 32–84

```python
_original_popen = subprocess.Popen
subprocess.Popen = _patched_popen
```

**Issue**: The runtime hook **monkey-patches `subprocess.Popen` globally** to suppress console windows. While benign in intent, this demonstrates the app's ability to hook OS-level APIs — same technique malware uses.

**Remediation**: Use `creationflags` on individual Popen calls instead of a global monkey-patch.

---

## 6. Installer & Distribution

### ℹ️ Finding 6.1 — Installer Security Posture

**File**: `cortex_setup.iss`

**Positive findings**:
- `PrivilegesRequired=lowest` — no admin required (good for security)
- `PrivilegesRequiredOverridesAllowed=dialog` — user CAN escalate for all-users install
- `.env.example` → `.env` uses `onlyifdoesntexist` (won't overwrite existing keys on upgrade)
- No registry RUN keys (no auto-start persistence)
- Right-click shell integration uses `HKCU` (user hive, not system)

**Negative findings**:
- Installer is **not code-signed** (`codesign_identity=None` in cortex.spec) → Windows SmartScreen will flag it
- `.env.example` bundled in installer — users see API key template on first launch (good UX, bad if they paste real keys here)
- No uninstall cleanup of `~/.cortex/` (database, keys, logs remain after uninstall)

---

### ℹ️ Finding 6.2 — Exe Not Code-Signed

**File**: `cortex.spec` line 235

```python
codesign_identity=None,
```

**Issue**: The built `.exe` has no digital signature. Windows Defender SmartScreen will show "Windows protected your PC" warning. Users learn to click "More info → Run anyway" which trains them to bypass security warnings for unsigned binaries — making them vulnerable to ACTUAL malware using the same pattern.

**Remediation**: Obtain a code-signing certificate (EV Code Signing, ~$300-500/year). Sign both `Cortex.exe` and `Cortex_Setup.exe`.

---

## 7. Summary — Risk Matrix

| # | Finding | Severity | Attack Vector | Effort to Fix |
|---|---------|----------|---------------|---------------|
| 1.1 | Weak key encryption (static salt) | 🔴 CRITICAL | Local malware decrypts `keys.enc` | Medium (DPAPI integration) |
| 1.2 | API keys in plaintext `.env` | 🔴 CRITICAL | Any process reads `.env` | Low (keyring library) |
| 1.3 | Keys fetched from `logic-practice.com` | 🔴 CRITICAL | Server compromise, MITM | High (architectural change) |
| 1.4 | Code sent to SiliconFlow for embeddings | 🔴 CRITICAL | Privacy/data exfiltration | Medium (local embeddings fallback) |
| 2.1 | SQLite chat history unencrypted | 🟠 HIGH | Local access → read all chats | Medium (SQLCipher) |
| 3.1 | Live server exposes project files | 🟠 HIGH | Local malware scans localhost | Low (path blocklist) |
| 4.1 | Crash log may contain secrets | 🟠 HIGH | Local access → read crash.log | Low (disable in release) |
| 4.3 | API key prefix logged | 🟡 MEDIUM | Local access → read logs | Low (hash/redact) |
| 5.1 | Bundled Node.js CVEs unknown | 🟡 MEDIUM | Dependent on Node version | Low (npm audit) |
| 5.2 | Sedimentary `agent/src/` code | 🟡 MEDIUM | Unused code attack surface | Medium (audit + remove) |
| 5.3 | Global Popen monkey-patch | 🟡 MEDIUM | Supply chain / trust | Low (move to per-call) |
| 6.1 | No code signing | ℹ️ INFO | SmartScreen friction | $300-500/yr |

---

## 8. Recommended Fix Priority

### Immediate (Before Public Distribution)

1. **Delete `.env` after keyring migration** — Store keys in Windows Credential Manager via `keyring` library. Wipe `.env` after first successful migration.
2. **Disable `faulthandler` in release builds** — Crash dumps are a goldmine for attackers.
3. **Disable `logic-practice.com` server key fetching** — Until a privacy review is done, this endpoint should be dead code.
4. **Add local embeddings option** — Ship a small local model (`all-MiniLM-L6-v2`, ~22MB) as fallback.

### Short-Term (Before v1.1)

5. **Switch to DPAPI for `keys.enc`** — Replace deterministic key derivation with Windows DPAPI.
6. **Add `.env`/`.git`/`.cortex` blocklist to Live Server** — Prevent local file exfiltration.
7. **Encrypt SQLite database** — Use SQLCipher or column-level encryption for chat messages.
8. **Redact API key prefix from logs** — Replace with `sk-****`.

### Medium-Term

9. **Code-sign the exe and installer** — Essential for trust and SmartScreen pass-through.
10. **Audit and prune `agent/src/`** — Remove unused modules before they become liabilities.
11. **Add offline mode** — Global toggle to block all non-provider outbound connections.

---

*Audit performed on the Cortex AI Agent IDE codebase at `c:\Users\Hakeem1\OneDrive\Desktop\Cortex_Ai_Agent\Cortex`.*
