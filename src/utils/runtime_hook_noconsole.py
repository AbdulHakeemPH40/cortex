"""
PyInstaller Runtime Hook - Prevent Console Window Popups
This runs BEFORE the application starts to globally suppress console windows.
"""
import sys
import os

# Only apply on Windows
if sys.platform == 'win32':
    try:
        import ctypes
        
        # Get the console window handle
        kernel32 = ctypes.windll.kernel32
        user32 = ctypes.windll.user32
        
        # If we have a console window, hide it immediately
        hwnd = kernel32.GetConsoleWindow()
        if hwnd:
            # SW_HIDE = 0
            user32.ShowWindow(hwnd, 0)
        
        # Windows constants
        CREATE_NO_WINDOW = 0x08000000
        STARTF_USESHOWWINDOW = 0x00000001
        SW_HIDE = 0
        
        # Monkey-patch ALL subprocess methods to always hide windows
        import subprocess
        
        # Store original functions
        _original_popen = subprocess.Popen
        _original_run = subprocess.run
        _original_call = subprocess.call
        _original_check_output = subprocess.check_output
        _original_check_call = subprocess.check_call
        
        def _get_hidden_kwargs(kwargs):
            """Add console-hiding flags to kwargs."""
            # Add CREATE_NO_WINDOW flag
            if 'creationflags' not in kwargs:
                kwargs['creationflags'] = CREATE_NO_WINDOW
            else:
                kwargs['creationflags'] |= CREATE_NO_WINDOW
            
            # Add startupinfo to hide window
            if 'startupinfo' not in kwargs:
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= STARTF_USESHOWWINDOW
                startupinfo.wShowWindow = SW_HIDE
                kwargs['startupinfo'] = startupinfo
            else:
                kwargs['startupinfo'].dwFlags |= STARTF_USESHOWWINDOW
                kwargs['startupinfo'].wShowWindow = SW_HIDE
            
            return kwargs
        
        # Patch Popen
        def _patched_popen(*args, **kwargs):
            kwargs = _get_hidden_kwargs(kwargs)
            return _original_popen(*args, **kwargs)
        
        # Patch run
        def _patched_run(*args, **kwargs):
            kwargs = _get_hidden_kwargs(kwargs)
            return _original_run(*args, **kwargs)
        
        # Patch call
        def _patched_call(*args, **kwargs):
            kwargs = _get_hidden_kwargs(kwargs)
            return _original_call(*args, **kwargs)
        
        # Patch check_output
        def _patched_check_output(*args, **kwargs):
            kwargs = _get_hidden_kwargs(kwargs)
            return _original_check_output(*args, **kwargs)
        
        # Patch check_call
        def _patched_check_call(*args, **kwargs):
            kwargs = _get_hidden_kwargs(kwargs)
            return _original_check_call(*args, **kwargs)
        
        # Apply all patches
        subprocess.Popen = _patched_popen
        subprocess.run = _patched_run
        subprocess.call = _patched_call
        subprocess.check_output = _patched_check_output
        subprocess.check_call = _patched_check_call
        
        # Also patch os.popen (legacy)
        _original_os_popen = os.popen
        def _patched_os_popen(cmd, mode='r', buffering=-1):
            # os.popen doesn't have creationflags, so we can't patch it directly
            # But it's rarely used in modern code
            return _original_os_popen(cmd, mode, buffering)
        os.popen = _patched_os_popen
        
    except Exception as e:
        # Silently fail - don't crash the app
        pass
