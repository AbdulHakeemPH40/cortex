# -*- mode: python ; coding: utf-8 -*-
import os
import sys
import glob
import shutil

# Get the directory containing this spec file
project_root = os.path.dirname(os.path.abspath(sys.argv[0])) if hasattr(sys, 'argv') else os.getcwd()

block_cipher = None

# ── Bundle ripgrep (rg.exe) for GrepTool ──────────────────────────────────────
# Download ripgrep and place rg.exe in bin/ folder
ripgrep_binaries = []
rg_path = os.path.join(project_root, 'bin', 'rg.exe')
if os.path.exists(rg_path):
    ripgrep_binaries.append((rg_path, 'bin'))
    print(f"Found ripgrep: {rg_path}")
else:
    print("WARNING: rg.exe not found in bin/ - GrepTool will not work!")
    print("Download from: https://github.com/BurntSushi/ripgrep/releases")

# Find pywinpty DLLs
winpty_dlls = []
try:
    import winpty
    winpty_dir = os.path.dirname(winpty.__file__)
    # winpty ships winpty.dll and winpty-agent.exe
    for pattern in ['*.dll', '*.exe', '*.pyd']:
        matches = glob.glob(os.path.join(winpty_dir, pattern))
        for match in matches:
            winpty_dlls.append((match, 'winpty'))
    print(f"Found {len(winpty_dlls)} winpty binaries: {winpty_dlls}")
except ImportError:
    print("winpty not installed — skipping")

# Combine all binaries
all_binaries = winpty_dlls + ripgrep_binaries

a = Analysis(
    ['src\\main.py'],
    pathex=[project_root],
    binaries=all_binaries,  # winpty + ripgrep
    datas=[
        # ── UI HTML panels ────────────────────────────────────────────────────
        ('src/ui/html/ai_chat', 'src/ui/html/ai_chat'),
        ('src/ui/html/ai_chat/file-icons/sprite.svg', 'src/ui/html/ai_chat/file-icons'),
        ('src/ui/html/memory_manager', 'src/ui/html/memory_manager'),  # Memory manager UI
        # ── UI components & assets ────────────────────────────────────────────
        ('src/ui/components/terminal.html', 'src/ui/components'),
        ('src/ui/components/assets', 'src/ui/components/assets'),
        ('src/ui/themes', 'src/ui/themes'),
        ('src/assets', 'src/assets'),
        # ── Plugins ───────────────────────────────────────────────────────────
        ('plugins/symbol_indexer', 'plugins/symbol_indexer'),
        # ── Node.js runtime (required by all LSP servers) ─────────────────────
        ('bin/node', 'bin/node'),
        # ── LSP servers - essential for language support ──────────────────────
        ('node_modules/pyright', 'node_modules/pyright'),                              # Python/Pyright LSP
        ('node_modules/typescript-language-server', 'node_modules/typescript-language-server'),  # TS/JS LSP
        ('node_modules/typescript', 'node_modules/typescript'),                        # TypeScript runtime
        ('node_modules/bash-language-server', 'node_modules/bash-language-server'),    # Bash LSP
        ('node_modules/vscode-langservers-extracted', 'node_modules/vscode-langservers-extracted'),  # HTML/CSS/JSON LSP
        # ── VSCode language service dependencies ──────────────────────────────
        ('node_modules/vscode-html-languageservice', 'node_modules/vscode-html-languageservice'),
        ('node_modules/vscode-css-languageservice', 'node_modules/vscode-css-languageservice'),
        ('node_modules/vscode-json-languageservice', 'node_modules/vscode-json-languageservice'),
        ('node_modules/vscode-languageserver', 'node_modules/vscode-languageserver'),
        ('node_modules/vscode-languageserver-protocol', 'node_modules/vscode-languageserver-protocol'),
        ('node_modules/vscode-languageserver-textdocument', 'node_modules/vscode-languageserver-textdocument'),
        ('node_modules/vscode-languageserver-types', 'node_modules/vscode-languageserver-types'),
        ('node_modules/vscode-jsonrpc', 'node_modules/vscode-jsonrpc'),
        ('node_modules/vscode-uri', 'node_modules/vscode-uri'),
        ('node_modules/vscode-nls', 'node_modules/vscode-nls'),
        ('node_modules/jsonc-parser', 'node_modules/jsonc-parser'),
        # ── LSP binary launchers (Windows .cmd wrappers) ──────────────────────
        ('node_modules/.bin/pyright-langserver*', 'node_modules/.bin'),
        ('node_modules/.bin/pyright*', 'node_modules/.bin'),
        ('node_modules/.bin/typescript-language-server*', 'node_modules/.bin'),
        ('node_modules/.bin/bash-language-server*', 'node_modules/.bin'),
        ('node_modules/.bin/vscode-html-language-server*', 'node_modules/.bin'),
        ('node_modules/.bin/vscode-css-language-server*', 'node_modules/.bin'),
        ('node_modules/.bin/vscode-json-language-server*', 'node_modules/.bin'),
        # ── Environment / config ──────────────────────────────────────────────
        # SECURITY: Do NOT include .env with API keys! Only .env.example
        ('.env.example', '.'),
    ],
    hiddenimports=[
        # ── PyQt6 ───────────────────────────────────────────────────────────
        'winpty',                           # pywinpty package imports as winpty
        'PyQt6.QtWebEngineWidgets',
        'PyQt6.QtWebChannel',
        'PyQt6.QtWebEngineCore',
        'PyQt6.sip',
        # ── AI Providers ───────────────────────────────────────────────
        'src.ai.providers',                 # Provider registry __init__.py
        'src.ai.providers.mistral_provider',
        'src.ai.providers.siliconflow_provider',
        'src.ai.agent_bridge',              # Core agentic loop
        # ── Core modules (lazily imported via get_*() functions) ───────────
        'src.core.lsp_manager',
        'src.core.pyright_config',
        'src.core.syntax_checker',
        'src.core.key_manager',
        'src.core.siliconflow_embeddings',
        'src.core.embeddings',
        'src.core.semantic_search',
        'src.core.database',
        'src.core.git_manager',
        'src.core.file_watcher',
        'src.core.chat_history',
        'src.core.change_orchestrator',
        # Removed: src.core.live_server (does not exist)
        # Removed: src.core.html_completion (does not exist)
        # ── Additional core modules ────────────────────────────────────
        'src.core.agent_memory',
        'src.core.code_chunker',
        'src.core.codebase_index',
        'src.core.event_bus',
        'src.core.file_manager',
        'src.core.memory_storage',
        'src.core.memory_types',
        'src.core.project_manager',
        'src.core.session_manager',
        # ── Services ────────────────────────────────────────────────────
        'src.services.llm_client',
        'src.services.streaming',
        'src.services.usage_tracker',
        # ── Config & coordinator ───────────────────────────────────────
        'src.config.settings',
        'src.config.theme_manager',
        'src.coordinator.coordinator_prompt',
        'src.coordinator.agent_context',
        # ── Python stdlib / tomllib ───────────────────────────────────
        'tomllib',                          # Python 3.11+ built-in
        'tomli',                            # Fallback for older Python
        # ── Third-party libs that PyInstaller may miss ─────────────────
        'dotenv',                           # python-dotenv
        'chardet',                          # Encoding detection for file reads
        'jsonref',                          # JSON $ref resolution
        'docstring_parser',                 # Tool schema parsing
        'yaml',                             # PyYAML — config files
        'git',                              # gitpython
        'watchdog',                         # File watching
        'watchdog.observers',
        'watchdog.events',
        'fitz',                             # PyMuPDF — PDF processing
        'bs4',                              # beautifulsoup4 — HTML parsing
        'lxml',                             # lxml — XML/HTML parsing
        'openpyxl',                         # Excel files
        'docx',                             # python-docx
        'cryptography',
        'bcrypt',
        'jsbeautifier',                     # JS code formatter
        'autopep8',                         # Python code formatter
        'black',                            # Python code formatter
        'pygments',                         # Syntax highlighting
        'pygments.lexers',                  # Dynamic lexer loading
        'pygments.formatters',
        'pygments.styles',
        # ── HTTP clients ─────────────────────────────────────────────
        'requests',                         # HTTP client (used by AI providers)
        'httpx',                            # Async HTTP client
        'requests.adapters',                # Request adapters
        'requests.auth',                    # Auth handlers
        # ── AI Provider SDKs ─────────────────────────────────────────
        'openai',                           # OpenAI SDK
        'openai.types',                     # OpenAI types
        'openai.types.chat',                # Chat completion types
        'anthropic',                        # Anthropic SDK
        'anthropic.types',                  # Anthropic types
        'together',                         # Together AI SDK
        'mistralai',                        # Mistral AI SDK
        'mistralai.models',                 # Mistral models
        'mistralai.models.chat_completion_request',
        'groq',                             # Groq SDK
        'litellm',                          # LiteLLM multi-provider
        'litellm.llms',                     # LiteLLM providers
        # ── Rich (terminal formatting) ───────────────────────────────
        'rich',                             # Rich text formatting
        'rich.console',                     # Console output
        'rich.markdown',                    # Markdown rendering
        # ── Windows-specific ─────────────────────────────────────────
        'win32api',                         # pywin32 - Windows API
        'win32con',                         # pywin32 - Constants
        'win32gui',                         # pywin32 - GUI functions
        'win32process',                     # pywin32 - Process management
        # ── Data processing ────────────────────────────────────────
        'numpy',                            # Numerical computing
        'numpy.core',                       # NumPy core
        'pandas',                           # Data analysis
        'pandas.core',                      # Pandas core
        # ── Scheduling ─────────────────────────────────────────────
        'schedule',                         # Job scheduling
        # ── Image processing ───────────────────────────────────────
        'PIL',                              # Pillow - Image processing
        'PIL.Image',                        # Image module
        # ── Speech recognition ─────────────────────────────────────
        'speech_recognition',               # Voice input
        # ── Terminal utilities ─────────────────────────────────────
        'InquirerPy',                       # Interactive prompts
        'prompt_toolkit',                   # Terminal UI
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

# Add runtime hook to prevent console window popups (stored safely in src/utils/)
runtime_hooks = [
    os.path.join(project_root, 'src', 'utils', 'runtime_hook_noconsole.py')
]

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='Cortex',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,  # GUI app - no console window
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    runtime_hooks=runtime_hooks,  # Apply console suppression hook
    icon='src/assets/logo/logo.ico',
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='Cortex',
)