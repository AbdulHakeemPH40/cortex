"""
Windows Toast Notification Utility
Shows native Windows notifications when AI tasks complete.

Uses PowerShell + Windows.UI.Notifications for native toast popups
with ToastGeneric template for clean title + body presentation.
"""

import subprocess
import threading
from typing import Optional


def show_toast_notification(title: str, message: str, duration: str = "short", app_id: str = "Cortex AI Agent") -> None:
    """
    Show a Windows toast notification popup.
    
    Args:
        title: Notification title (bold, first line)
        message: Notification body text (second line, clean/minimal)
        duration: "short" (7s) or "long" (25s)
        app_id: Application identifier for the notification
    """
    # Sanitize XML-unsafe characters
    title_safe = title.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
    message_safe = message.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
    
    try:
        toast_script = f'''
[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null
[Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime] | Out-Null

$template = @"
<toast activationType="protocol" duration="{duration}" scenario="reminder">
    <visual>
        <binding template="ToastGeneric">
            <text id="1">{title_safe}</text>
            <text id="2">{message_safe}</text>
        </binding>
    </visual>
    <audio src="ms-winsoundevent:Notification.Default" loop="false"/>
</toast>
"@

$xml = New-Object Windows.Data.Xml.Dom.XmlDocument
$xml.LoadXml($template)
$toast = [Windows.UI.Notifications.ToastNotification]::new($xml)
$toast.SuppressPopup = $false
$toast.ExpirationTime = [DateTime]::Now.AddSeconds(10)
[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier("{app_id}").Show($toast)
'''
        def run_powershell():
            try:
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
                    timeout=12,
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
    """Show notification for AI task completion — clean, minimal format."""
    show_toast_notification(
        title="Cortex AI — Task Complete",
        message=task_summary[:120] if len(task_summary) > 120 else task_summary,
        duration="short"
    )
