# -*- mode: python ; coding: utf-8 -*-
import os
import sys
import glob

# Get the directory containing this spec file
project_root = os.path.dirname(os.path.abspath(sys.argv[0])) if hasattr(sys, 'argv') else os.getcwd()

block_cipher = None

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

a = Analysis(
    ['src\\main.py'],
    pathex=[project_root],
    binaries=winpty_dlls,  # ← ADD THIS
    datas=[
        ('src/ui/html/ai_chat', 'src/ui/html/ai_chat'),
        ('src/ui/html/ai_chat/file-icons/sprite.svg', 'src/ui/html/ai_chat/file-icons'),
        ('src/ui/components/terminal.html', 'src/ui/components'),
        ('src/ui/components/assets', 'src/ui/components/assets'),
        ('src/ui/themes', 'src/ui/themes'),
        ('src/assets', 'src/assets'),
        ('bin/node', 'bin/node'),
        # LSP servers - essential for language support
        ('node_modules/pyright', 'node_modules/pyright'),
        ('node_modules/typescript-language-server', 'node_modules/typescript-language-server'),
        ('node_modules/bash-language-server', 'node_modules/bash-language-server'),
        ('node_modules/vscode-langservers-extracted', 'node_modules/vscode-langservers-extracted'),
        ('node_modules/.bin/pyright-langserver*', 'node_modules/.bin'),
        ('node_modules/.bin/typescript-language-server*', 'node_modules/.bin'),
        ('node_modules/.bin/bash-language-server*', 'node_modules/.bin'),
        ('node_modules/.bin/vscode-html-language-server*', 'node_modules/.bin'),
        ('node_modules/.bin/vscode-css-language-server*', 'node_modules/.bin'),
        ('node_modules/.bin/vscode-json-language-server*', 'node_modules/.bin'),
        ('.env', '.'),
    ],
    hiddenimports=[
        'winpty',          # pywinpty package imports as winpty
        'PyQt6.QtWebEngineWidgets',
        'PyQt6.QtWebChannel',
        'PyQt6.QtWebEngineCore',
        'PyQt6.sip',
        'src.ai.providers.deepseek_provider',
        'src.ai.providers.mistral_provider',      # Mistral AI support
        'src.ai.providers.siliconflow_provider',
        'src.core.lsp_manager',
        'src.core.pyright_config',  # Pyright configuration management
        'tomllib',  # For pyproject.toml parsing (Python 3.11+)
        'tomli',    # Fallback for older Python versions
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
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
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