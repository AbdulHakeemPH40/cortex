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
        ('src/ui/components/terminal.html', 'src/ui/components'),
        ('src/ui/components/assets', 'src/ui/components/assets'),
        ('src/ui/themes', 'src/ui/themes'),
        ('src/assets', 'src/assets'),
        ('.env', '.'),
    ],
    hiddenimports=[
        'winpty',          # pywinpty package imports as winpty
        'winpty._winpty',  # C extension module
        'PyQt6.QtWebEngineWidgets',
        'PyQt6.QtWebChannel',
        'PyQt6.QtWebEngineCore',
        'PyQt6.sip',
        'src.ai.providers.deepseek_provider',
        'src.ai.providers.together_provider',
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
