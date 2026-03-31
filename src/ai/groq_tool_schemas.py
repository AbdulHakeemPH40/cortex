"""
Groq Tool Schema Reference
Complete parameter requirements for ALL 38 tools
Helps Groq understand what parameters are required for proper tool calling
"""

GROQ_TOOL_SCHEMAS = {
    # File Operations (11 tools)
    "read_file": {
        "required": ["path"],
        "optional": ["start_line", "end_line", "numbered"],
        "description": "Read file content with optional line numbers and range"
    },
    "write_file": {
        "required": ["path", "content"],
        "optional": [],
        "description": "Write content to a file"
    },
    "edit_file": {
        "required": ["path", "old_string", "new_string"],
        "optional": ["expected_occurrences"],
        "description": "Surgical find-and-replace editing"
    },
    "inject_after": {
        "required": ["path", "anchor", "new_code"],
        "optional": [],
        "description": "Insert code after a specific anchor line"
    },
    "add_import": {
        "required": ["path", "import_statement"],
        "optional": [],
        "description": "Add import statement to file"
    },
    "insert_at_line": {
        "required": ["path", "line", "content"],
        "optional": [],
        "description": "Insert content at specific line number"
    },
    "get_file_outline": {
        "required": ["path"],
        "optional": [],
        "description": "Get function/class summary with line numbers"
    },
    "delete_lines": {
        "required": ["path", "start_line", "end_line"],
        "optional": [],
        "description": "Delete lines from file"
    },
    "replace_lines": {
        "required": ["path", "start_line", "end_line", "new_code"],
        "optional": [],
        "description": "Replace lines with new code"
    },
    "find_usages": {
        "required": ["symbol"],
        "optional": ["file_pattern"],
        "description": "Find symbol usages across codebase"
    },
    "analyze_file": {
        "required": ["path"],
        "optional": ["analysis_type"],
        "description": "Deep analysis of file structure"
    },
    
    # Path Operations (3 tools)
    "delete_path": {
        "required": ["path"],
        "optional": ["recursive"],
        "description": "Delete file or directory"
    },
    "list_directory": {
        "required": [],
        "optional": ["path", "show_hidden"],
        "description": "List directory contents"
    },
    "undo_last_action": {
        "required": [],
        "optional": [],
        "description": "Undo last AI file operation"
    },
    
    # Terminal Operations (3 tools)
    "run_command": {
        "required": ["command"],
        "optional": ["timeout"],
        "description": "Run terminal command"
    },
    "read_terminal": {
        "required": [],
        "optional": ["lines"],
        "description": "Read terminal output"
    },
    "bash": {
        "required": ["command"],
        "optional": ["cwd"],
        "description": "Run interactive bash command"
    },
    
    # Git Operations (4 tools)
    "git_status": {
        "required": [],
        "optional": [],
        "description": "Get git repository status"
    },
    "git_diff": {
        "required": [],
        "optional": ["file_path", "staged"],
        "description": "Show git diff"
    },
    "git_commit": {
        "required": ["message"],
        "optional": ["files", "stage_all"],
        "description": "Commit changes to git"
    },
    
    # Search Operations (8 tools)
    "search_code": {
        "required": ["query"],
        "optional": ["file_pattern"],
        "description": "Search code with regex"
    },
    "search_codebase": {
        "required": ["query"],
        "optional": ["target_directories"],
        "description": "Semantic code search by meaning"
    },
    "semantic_search": {
        "required": ["query"],
        "optional": ["limit", "chunk_types"],
        "description": "Deep semantic search using embeddings"
    },
    "find_function": {
        "required": ["name"],
        "optional": ["file_pattern"],
        "description": "Find function definitions"
    },
    "find_class": {
        "required": ["name"],
        "optional": ["file_pattern"],
        "description": "Find class definitions"
    },
    "find_symbol": {
        "required": ["name"],
        "optional": ["symbol_type", "file_pattern"],
        "description": "Find any symbol by name"
    },
    "grep": {
        "required": ["pattern"],
        "optional": ["include", "exclude_dirs"],
        "description": "Search with regex (ripgrep)"
    },
    "glob": {
        "required": ["pattern"],
        "optional": ["exclude_dirs"],
        "description": "Find files matching pattern"
    },
    
    # Code Quality (4 tools)
    "debug_error": {
        "required": ["error_text"],
        "optional": ["file_path", "line_number"],
        "description": "Analyze error and suggest fixes"
    },
    "check_syntax": {
        "required": ["file_path"],
        "optional": [],
        "description": "Check file syntax"
    },
    "get_problems": {
        "required": [],
        "optional": ["file_paths"],
        "description": "Check for compile/lint errors"
    },
    "verify_fix": {
        "required": [],
        "optional": ["test_command", "check_scenario", "file_paths"],
        "description": "Verify fix works"
    },
    
    # LSP Operations (2 tools)
    "lsp_find_references": {
        "required": ["symbol", "file_path", "line", "character"],
        "optional": [],
        "description": "Find symbol references using LSP"
    },
    "lsp_go_to_definition": {
        "required": ["symbol", "file_path", "line", "character"],
        "optional": [],
        "description": "Go to symbol definition using LSP"
    },
    
    # Memory Operations (1 tool)
    "search_memory": {
        "required": ["query"],
        "optional": ["category", "depth"],
        "description": "Search past memories/decisions"
    },
    
    # Task Management (1 tool)
    "task": {
        "required": ["operation"],
        "optional": ["command", "task_id"],
        "description": "Manage background tasks"
    },
    
    # Interactive (1 tool)
    "question": {
        "required": ["question"],
        "optional": ["type"],
        "description": "Ask user for clarification"
    }
}


def validate_tool_call(tool_name: str, arguments: dict) -> tuple[bool, list]:
    """
    Validate a tool call against its schema
    
    Returns:
        (is_valid, missing_params)
    """
    if tool_name not in GROQ_TOOL_SCHEMAS:
        return False, [f"Unknown tool: {tool_name}"]
    
    schema = GROQ_TOOL_SCHEMAS[tool_name]
    required = schema.get("required", [])
    
    missing = []
    for param in required:
        if param not in arguments or arguments[param] is None or arguments[param] == "":
            missing.append(param)
    
    return len(missing) == 0, missing


def get_tool_help(tool_name: str) -> str:
    """Get help text for a tool"""
    if tool_name not in GROQ_TOOL_SCHEMAS:
        return f"Tool '{tool_name}' not found"
    
    schema = GROQ_TOOL_SCHEMAS[tool_name]
    required = schema.get("required", [])
    optional = schema.get("optional", [])
    
    help_text = f"{tool_name}: {schema['description']}\n"
    help_text += f"  Required: {', '.join(required) if required else 'None'}\n"
    if optional:
        help_text += f"  Optional: {', '.join(optional)}\n"
    
    return help_text


def get_all_tools_list() -> str:
    """Get formatted list of all tools"""
    lines = ["Available Tools (38 total):\n"]
    
    categories = {
        "File Operations": ["read_file", "write_file", "edit_file", "inject_after", "add_import", 
                           "insert_at_line", "get_file_outline", "delete_lines", "replace_lines",
                           "find_usages", "analyze_file"],
        "Path Operations": ["delete_path", "list_directory", "undo_last_action"],
        "Terminal": ["run_command", "read_terminal", "bash"],
        "Git": ["git_status", "git_diff", "git_commit"],
        "Search": ["search_code", "search_codebase", "semantic_search", "find_function",
                  "find_class", "find_symbol", "grep", "glob"],
        "Code Quality": ["debug_error", "check_syntax", "get_problems", "verify_fix"],
        "LSP": ["lsp_find_references", "lsp_go_to_definition"],
        "Other": ["search_memory", "task", "question"]
    }
    
    for category, tools in categories.items():
        lines.append(f"\n{category}:")
        for tool in tools:
            if tool in GROQ_TOOL_SCHEMAS:
                schema = GROQ_TOOL_SCHEMAS[tool]
                req = schema.get("required", [])
                lines.append(f"  - {tool}({', '.join(req)}) - {schema['description'][:50]}...")
    
    return "\n".join(lines)
