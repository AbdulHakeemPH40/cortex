"""
UI Connection Fixes for Phase 4 Features
Connects TODO System and Auto Title to Chat UI properly
"""

# Add this to main_window.py after initializing components

# Connect Phase 4 Todo Manager signals to update Chat UI
self._todo_manager.task_added.connect(self._on_todo_task_added)
self._todo_manager.task_completed.connect(self._on_todo_task_completed)
self._todo_manager.task_updated.connect(self._on_todo_task_updated)

# Connect title generator to update chat tab
self._title_generator.title_generated.connect(self._on_title_generated)

def _on_todo_task_added(self, task_id: str):
    """Handle new todo task - update chat UI in real-time."""
    task = self._todo_manager.get_task(task_id)
    if task and hasattr(self, '_ai_chat'):
        # Convert to dict and update chat UI
        task_dict = task.to_dict()
        self._ai_chat.update_todos([task_dict])
        log.info(f"Todo task added to UI: {task.description[:30]}")

def _on_todo_task_completed(self, task_id: str):
    """Handle completed todo - update chat UI."""
    task = self._todo_manager.get_task(task_id)
    if task and hasattr(self, '_ai_chat'):
        # Update the todo status in chat UI
        task_dict = task.to_dict()
        self._ai_chat.update_todos([task_dict])
        log.info(f"Todo task completed in UI: {task.description[:30]}")

def _on_todo_task_updated(self, task_id: str):
    """Handle updated todo - refresh chat UI."""
    session_id = getattr(self._ai_chat, '_current_conversation_id', 'default')
    tasks = self._todo_manager.get_session_tasks(session_id)
    if hasattr(self, '_ai_chat'):
        # Refresh all todos in chat UI
        tasks_list = [t.to_dict() for t in tasks]
        self._ai_chat.update_todos(tasks_list)

def _on_title_generated(self, conversation_id: str, title: str):
    """Handle auto-generated title - update chat tab and UI."""
    if hasattr(self, '_ai_chat') and hasattr(self._ai_chat, 'update_conversation_title'):
        # Update the chat tab title
        self._ai_chat.update_conversation_title(conversation_id, title)
        log.info(f"Chat title updated: {title}")
        
        # Also update window title if this is current chat
        current_id = getattr(self._ai_chat, '_current_conversation_id', None)
        if current_id == conversation_id:
            self.setWindowTitle(f"Cortex - {title}")
