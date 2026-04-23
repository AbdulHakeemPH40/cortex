#!/usr/bin/env python3
"""
Project Indexer for Cortex IDE

This script indexes the project structure, key files, and dependencies
to provide a comprehensive overview of the project.
"""

import os
import json
from pathlib import Path

# --- Constants ---
PROJECT_ROOT = Path(__file__).parent.absolute()
OUTPUT_FILE = PROJECT_ROOT / "project_index.json"
IGNORE_DIRS = {".git", ".pytest_cache", "__pycache__", "venv", "node_modules", "tmp"}
IGNORE_FILES = {".env", "crash_output.log", "terminal2.log"}

# --- Helper Functions ---
def is_ignored(path: Path) -> bool:
    """Check if a path should be ignored."""
    if path.name in IGNORE_FILES:
        return True
    for part in path.parts:
        if part in IGNORE_DIRS:
            return True
    return False

def get_file_type(file_path: Path) -> str:
    """Determine the type of a file based on its extension."""
    ext = file_path.suffix.lower()
    if ext == ".py":
        return "python"
    elif ext == ".js":
        return "javascript"
    elif ext == ".json":
        return "json"
    elif ext == ".md":
        return "markdown"
    elif ext == ".html":
        return "html"
    elif ext == ".css":
        return "css"
    elif ext == ".bat":
        return "batch"
    elif ext == ".iss":
        return "inno"
    elif ext == ".spec":
        return "pyinstaller"
    elif ext == ".log":
        return "log"
    else:
        return "unknown"

def scan_directory(directory: Path) -> dict:
    """Scan a directory and return its structure."""
    structure = {
        "name": directory.name,
        "type": "directory",
        "path": str(directory),
        "children": []
    }
    
    try:
        for item in directory.iterdir():
            if is_ignored(item):
                continue
            
            if item.is_dir():
                structure["children"].append(scan_directory(item))
            else:
                structure["children"].append({
                    "name": item.name,
                    "type": "file",
                    "file_type": get_file_type(item),
                    "path": str(item),
                    "size": item.stat().st_size
                })
    except PermissionError:
        structure["error"] = "Permission denied"
    
    return structure

def identify_key_files(structure: dict) -> list:
    """Identify key files in the project structure."""
    key_files = []
    
    def traverse(node):
        if node.get("type") != "directory":
            path = Path(node["path"])
            if any(keyword in str(path) for keyword in ["main", "config", "setup", "install", "build", "test", "query", "tool", "agent"]):
                key_files.append(node)
        elif node["type"] == "directory":
            for child in node["children"]:
                traverse(child)
    
    traverse(structure)
    return key_files

def analyze_dependencies() -> dict:
    """Analyze project dependencies from requirements and package.json."""
    dependencies = {
        "python": [],
        "node": []
    }
    
    # Python dependencies
    req_files = ["requirements.txt", "requirements2.txt"]
    for req_file in req_files:
        req_path = PROJECT_ROOT / req_file
        if req_path.exists():
            with open(req_path, "r") as f:
                dependencies["python"].extend(line.strip() for line in f if line.strip() and not line.startswith("#"))
    
    # Node dependencies
    package_json = PROJECT_ROOT / "package.json"
    if package_json.exists():
        with open(package_json, "r") as f:
            data = json.load(f)
            deps = set()
            deps.update(data.get("dependencies", {}).keys())
            deps.update(data.get("devDependencies", {}).keys())
            dependencies["node"].extend(sorted(deps))
    
    return dependencies

def generate_index() -> dict:
    """Generate a comprehensive project index."""
    print(f"Scanning project at: {PROJECT_ROOT}")
    
    # Scan directory structure
    structure = scan_directory(PROJECT_ROOT)
    
    # Identify key files
    key_files = identify_key_files(structure)
    
    # Analyze dependencies
    dependencies = analyze_dependencies()
    
    # Add metadata for key files
    key_files_with_metadata = []
    for file_info in key_files:
        file_path = Path(file_info["path"])
        metadata = {
            "purpose": "Unknown",
            "dependencies": []
        }
        
        # Add purpose based on filename or path
        if "main" in file_path.name.lower():
            metadata["purpose"] = "Main entry point"
        elif "query" in file_path.name.lower():
            metadata["purpose"] = "Query engine logic"
        elif "tool" in file_path.name.lower():
            metadata["purpose"] = "Tool definitions"
        elif "context" in file_path.name.lower():
            metadata["purpose"] = "Context management"
        elif "task" in file_path.name.lower():
            metadata["purpose"] = "Task management"
        
        # Add dependencies (placeholder for now)
        if file_path.suffix == ".py":
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read()
                imports = [line.split()[1] for line in content.splitlines() if line.startswith("import ") or line.startswith("from ")]
                metadata["dependencies"] = list(set(imports))
        
        file_info["metadata"] = metadata
        key_files_with_metadata.append(file_info)
    
    # Create index
    index = {
        "project_root": str(PROJECT_ROOT),
        "structure": structure,
        "key_files": key_files_with_metadata,
        "dependencies": dependencies,
        "stats": {
            "total_files": sum(1 for _ in PROJECT_ROOT.rglob("*") if _.is_file() and not is_ignored(_)),
            "total_dirs": sum(1 for _ in PROJECT_ROOT.rglob("*") if _.is_dir() and not is_ignored(_)),
            "generated_at": str(Path(__file__).stat().st_mtime)
        }
    }
    
    return index

def save_index(index: dict):
    """Save the index to a JSON file."""
    with open(OUTPUT_FILE, "w") as f:
        json.dump(index, f, indent=2)
    print(f"Project index saved to: {OUTPUT_FILE}")

# --- Main ---
if __name__ == "__main__":
    index = generate_index()
    save_index(index)