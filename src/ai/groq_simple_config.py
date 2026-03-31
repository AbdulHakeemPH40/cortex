"""
Simplified Groq Agent Configuration
Focus: Reliability over complexity
"""

# Only 6 essential tools for Groq - keeps it simple and reliable
GROQ_ESSENTIAL_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read content of a file. REQUIRED: path (string)",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Path to the file"}
                },
                "required": ["path"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "Write content to a file. REQUIRED: path (string), content (string)",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Path to the file"},
                    "content": {"type": "string", "description": "Content to write"}
                },
                "required": ["path", "content"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "edit_file",
            "description": "Edit a file by replacing text. REQUIRED: path (string), old_string (string), new_string (string)",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Path to the file"},
                    "old_string": {"type": "string", "description": "Text to find"},
                    "new_string": {"type": "string", "description": "Text to replace with"}
                },
                "required": ["path", "old_string", "new_string"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "list_directory",
            "description": "List files in a directory. REQUIRED: path (string)",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Directory path"}
                },
                "required": ["path"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "run_command",
            "description": "Run a terminal command. REQUIRED: command (string)",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "Command to execute"}
                },
                "required": ["command"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "search_code",
            "description": "Search for text in codebase. REQUIRED: query (string)",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Text to search for"}
                },
                "required": ["query"]
            }
        }
    }
]

# Simplified system prompt - crystal clear
GROQ_SIMPLE_PROMPT = """You are an AI Agent that helps users by using tools.

## AVAILABLE TOOLS (6 total):

1. **read_file** - Read a file
   - REQUIRED: path
   - Example: {"path": "src/main.py"}

2. **write_file** - Write/create a file
   - REQUIRED: path, content
   - Example: {"path": "src/main.py", "content": "print('hello')"}

3. **edit_file** - Edit existing file
   - REQUIRED: path, old_string, new_string
   - Example: {"path": "src/main.py", "old_string": "x=1", "new_string": "x=2"}

4. **list_directory** - List files in directory
   - REQUIRED: path
   - Example: {"path": "src"}

5. **run_command** - Run terminal command
   - REQUIRED: command
   - Example: {"command": "python --version"}

6. **search_code** - Search in codebase
   - REQUIRED: query
   - Example: {"query": "def main"}

## CRITICAL RULES:

1. **ALWAYS** include ALL required parameters
2. **NEVER** call a tool without required parameters
3. If unsure about a value, ask the user first
4. After each tool call, wait for the result

## WORKFLOW:

1. Understand what the user wants
2. Choose the right tool
3. Verify ALL required parameters are present
4. Call the tool
5. Review the result
6. Continue or finish

## EXAMPLE SESSION:

User: "Create a hello.py file"
AI: I'll create that file for you.
Tool: write_file({"path": "hello.py", "content": "print('Hello World')"})
AI: File created successfully!

## IF YOU MAKE A MISTAKE:

The system will tell you what's wrong. Fix it and try again.
"""

# Groq configuration for reliability
GROQ_RELIABLE_CONFIG = {
    "model": "llama-3.3-70b-versatile",  # Most reliable for tool calling
    "temperature": 0.2,  # Lower = more deterministic
    "max_tokens": 4096,
    "top_p": 0.95,
    "stream": True,
    "tools": GROQ_ESSENTIAL_TOOLS,
    "tool_choice": "auto"
}


def validate_tool_call(tool_name: str, arguments: dict) -> tuple[bool, str]:
    """
    Validate a tool call before sending to API
    Returns: (is_valid, error_message)
    """
    required_params = {
        "read_file": ["path"],
        "write_file": ["path", "content"],
        "edit_file": ["path", "old_string", "new_string"],
        "list_directory": ["path"],
        "run_command": ["command"],
        "search_code": ["query"]
    }
    
    if tool_name not in required_params:
        return False, f"Unknown tool: {tool_name}"
    
    required = required_params[tool_name]
    missing = [p for p in required if p not in arguments or not arguments[p]]
    
    if missing:
        return False, f"Missing required parameters: {', '.join(missing)}"
    
    return True, ""


def get_simple_groq_config():
    """Get simplified configuration for reliable Groq usage"""
    return {
        "tools": GROQ_ESSENTIAL_TOOLS,
        "system_prompt": GROQ_SIMPLE_PROMPT,
        "config": GROQ_RELIABLE_CONFIG
    }
