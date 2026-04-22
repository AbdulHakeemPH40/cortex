"""
Windows Toast Notification Utility
Shows native Windows notifications when AI tasks complete
"""

import subprocess
import threading
from typing import Optional


def show_toast_notification(title: str, message: str, duration: int = 5, app_id: str = "Cortex AI Agent") -> None:
    """
    Show a Windows toast notification popup.
    
    Args:
        title: Notification title
        message: Notification body text
        duration: How long to show (seconds)
        app_id: Application identifier for the notification
    """
    try:
        toast_script = f'''
[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null
[Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime] | Out-Null

$template = @"
<toast activationType="protocol" duration="short">
    <visual>
        <binding template="ToastGeneric">
            <text>{title}</text>
            <text>{message}</text>
        </binding>
    </visual>
    <audio src="ms-winsoundevent:Notification.Default"/>
</toast>
"@

$xml = New-Object Windows.Data.Xml.Dom.XmlDocument
$xml.LoadXml($template)
$toast = [Windows.UI.Notifications.ToastNotification]::new($xml)
[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier("{app_id}").Show($toast)
'''
        def run_powershell():
            try:
                # FIX: Prevent console window popup in PyInstaller builds
                import sys
                startupinfo = None
                creationflags = 0
                if sys.platform == 'win32':
                    startupinfo = subprocess.STARTUPINFO()
                    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                    startupinfo.wShowWindow = 0  # SW_HIDE
                    creationflags = subprocess.CREATE_NO_WINDOW
                
                subprocess.run(
                    ['powershell', '-WindowStyle', 'hidden', '-Command', toast_script],
                    capture_output=True,
                    timeout=duration + 2,
                    startupinfo=startupinfo,
                    creationflags=creationflags
                )
            except Exception:
                pass
        
        thread = threading.Thread(target=run_powershell, daemon=True)
        thread.start()
        
    except Exception:
        pass


def show_task_complete_notification(task_summary: str = "Task completed successfully") -> None:
    """Show notification for AI task completion."""
    show_toast_notification(
        title="✅ Cortex AI - Task Complete",
        message=task_summary[:100] if len(task_summary) > 100 else task_summary,
        duration=5
    )
