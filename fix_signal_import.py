# fix_signal_import.py
# Script to fix Signal import in agent_bridge.py

import os
import re

# Path to the file
FILE_PATH = os.path.join(
    "C:\\Users\\Hakeem1\\OneDrive\\Desktop\\Cortex_Ai_Agent\\Cortex",
    "src\\ai\\agent_bridge.py"
)

# Read the file with UTF-8 encoding
with open(FILE_PATH, "r", encoding="utf-8") as f:
    content = f.read()

# Fix the import statement
old_import = "from PyQt6.QtCore import QObject, pyqtSignal as Signal, QTimer, QThread, QEventLoop, QMutex, QMutexLocker, Qt, QCoreApplication, QUrl, QByteArray, QBuffer, QIODevice"
new_import = "from PyQt6.QtCore import QObject, pyqtSignal, QTimer, QThread, QEventLoop, QMutex, QMutexLocker, Qt, QCoreApplication, QUrl, QByteArray, QBuffer, QIODevice"

# Replace the import statement
content = content.replace(old_import, new_import)

# Fix the Signal usage in the class
content = content.replace(
    "self.file_edit_notification = Signal(str, str, str)",
    "self.file_edit_notification = pyqtSignal(str, str, str)"
)

# Write the changes back with UTF-8 encoding
with open(FILE_PATH, "w", encoding="utf-8") as f:
    f.write(content)

print("Signal import and usage fixed in agent_bridge.py")