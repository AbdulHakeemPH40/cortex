# Cortex IDE Project Index

## Overview
This index provides a structured overview of the Cortex IDE project, including key directories, files, and components.

---

## Root Directory Structure
- **`.cortex/`**: Cortex-specific files and configurations.
- **`.git/`**: Git repository metadata.
- **`.pytest_cache/`**: Cached pytest files.
- **`.qoder/`**: Qoder-related files.
- **`Docs/`**: Documentation files (e.g., `app.md`, `bugs.md`).
- **`Qoder/`**: Qoder-specific files.
- **`__pycache__/`**: Python bytecode cache.
- **`bin/`**: Binary files or scripts.
- **`installer_output/`**: Output from installer scripts.
- **`node_modules/`**: Node.js dependencies.
- **`plugins/`**: Plugin files.
- **`src/`**: Main source code directory.
- **`tests/`**: Test files.
- **`tmp/`**: Temporary files.
- **`venv/`**: Python virtual environment.
- **`.env`**: Environment variables.
- **`.env.example`**: Example environment variables.
- **`.gitignore`**: Git ignore rules.
- **`build_installer.bat`**: Batch script for building the installer.
- **`cortex.spec`**: PyInstaller spec file.
- **`cortex_setup.iss`**: Inno Setup script.
- **`crash_output.log`**: Log file for crashes.
- **`index_project.py`**: Script for indexing the project.
- **`install_lsp_servers.js`**: Script for installing LSP servers.
- **`package-lock.json`**: Node.js dependency lock file.
- **`package.json`**: Node.js project configuration.
- **`requirements.txt`**: Python dependencies.
- **`requirements2.txt`**: Additional Python dependencies.
- **`terminal2.log`**: Terminal log file.

---

## Key Directories

### `src/` Directory
- **`agent/`**: Agent-related source code.
  - **`src/`**: Core agent logic and utilities.
    - **`DelFiles/`**: Files for deletion logic.
    - **`agent_types/`**: Agent type definitions.
    - **`api/`**: API-related code.
    - **`assistant/`**: Assistant logic.
    - **`bootstrap/`**: Bootstrap scripts.
    - **`bun/`**: Bun-related files.
    - **`constants/`**: Constant definitions.
    - **`coordinator/`**: Coordinator logic.
    - **`entrypoints/`**: Entry points for the agent.
    - **`hooks/`**: Hook scripts.
    - **`memdir/`**: Memory directory logic.
    - **`query/`**: Query-related logic.
    - **`services/`**: Service definitions.
    - **`skills/`**: Skill definitions.
    - **`state/`**: State management.
    - **`tasks/`**: Task management.
    - **`tools/`**: Tool definitions.
    - **`utils/`**: Utility functions.
    - **`voice/`**: Voice-related logic.
    - **`QueryEngine.py`**: Query engine implementation.
    - **`Task.py`**: Task class.
    - **`Tool.py`**: Tool class.
    - **`categorize_by_fix_type.py`**: Script for categorizing fixes.
    - **`categorize_import_errors.py`**: Script for categorizing import errors.
    - **`cleanup_terminology.py`**: Script for terminology cleanup.
    - **`commands.py`**: Command definitions.
    - **`context.py`**: Context management.
    - **`cost-tracker.py`**: Cost tracking logic.
    - **`costHook.py`**: Cost hook logic.
    - **`cost_tracker.py`**: Cost tracker implementation.
    - **`history.py`**: History management.
    - **`projectOnboardingState.py`**: Project onboarding state.
    - **`query.py`**: Query logic.
    - **`setup.py`**: Setup script.
    - **`tasks.py`**: Task management logic.
    - **`tool_registry.py`**: Tool registry.
    - **`validate_imports.py`**: Script for validating imports.

- **`ai/`**: AI-related source code.
- **`assets/`**: Static assets (e.g., images, stylesheets).
- **`config/`**: Configuration files.
- **`coordinator/`**: Coordinator logic.
- **`core/`**: Core functionality.
- **`plugin/`**: Plugin logic.
- **`services/`**: Service definitions.
- **`tests/`**: Test files.
- **`tools/`**: Tool definitions.
- **`ui/`**: User interface logic.
- **`utils/`**: Utility functions.
- **`__init__.py`**: Python package initialization.
- **`main.py`**: Main entry point.
- **`main_window.py`**: Main window logic.

---

## Key Files
- **`main.py`**: Main entry point for the application.
- **`main_window.py`**: Main UI window logic.
- **`QueryEngine.py`**: Core query engine for the agent.
- **`Tool.py`**: Defines tools used by the agent.
- **`tool_registry.py`**: Registry for tools available to the agent.
- **`context.py`**: Manages context for the agent.
- **`tasks.py`**: Manages tasks for the agent.

---

## Documentation
- **`Docs/app.md`**: Application documentation.
- **`Docs/bugs.md`**: Known bugs and issues.
- **`Docs/ask_user_question_integration_plan.md`**: Plan for integrating user questions.

---

## Dependencies
- **`requirements.txt`**: Python dependencies.
- **`requirements2.txt`**: Additional Python dependencies.
- **`package.json`**: Node.js dependencies.

---

## Configuration
- **`.env`**: Environment variables for the project.
- **`.env.example`**: Example environment variables.

---

## Build and Installation
- **`build_installer.bat`**: Script for building the installer.
- **`cortex.spec`**: PyInstaller spec file for building the executable.
- **`cortex_setup.iss`**: Inno Setup script for creating an installer.

---

## Logs
- **`crash_output.log`**: Log file for crashes.
- **`terminal2.log`**: Terminal log file.

---

## Scripts
- **`index_project.py`**: Script for indexing the project.
- **`install_lsp_servers.js`**: Script for installing LSP servers.

---

## Memory System
- **`memory/`**: Memory files for the project.
  - **`MEMORY.md`**: Index of memory files.
  - **`project_update_2024.md`**: Latest project state and updates.
  - **`project_structure.md`**: Overview of the project's directory structure.
  - **`project_index.md`**: Index of the project (this file).