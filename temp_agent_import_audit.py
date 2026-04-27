import ast
import json
from pathlib import Path


ROOT = Path(r"c:\Users\Hakeem1\OneDrive\Desktop\Cortex_Ai_Agent\Cortex")
AGENT_SRC = ROOT / "src" / "agent" / "src"
ROOT_SRC = ROOT / "src"


def list_py_files(base: Path):
    return [p for p in base.rglob("*.py") if "__pycache__" not in p.parts]


def module_to_file(module: str):
    parts = module.split(".")
    candidates = []

    # absolute packages reachable in this repo
    candidates.append(ROOT.joinpath(*parts).with_suffix(".py"))
    candidates.append(ROOT.joinpath(*parts) / "__init__.py")
    candidates.append(ROOT_SRC.joinpath(*parts).with_suffix(".py"))
    candidates.append(ROOT_SRC.joinpath(*parts) / "__init__.py")
    candidates.append(AGENT_SRC.joinpath(*parts).with_suffix(".py"))
    candidates.append(AGENT_SRC.joinpath(*parts) / "__init__.py")

    # special case: "src.agent.src.xxx" should map under AGENT_SRC
    if module.startswith("src.agent.src."):
        sub = module[len("src.agent.src."):].split(".")
        candidates.append(AGENT_SRC.joinpath(*sub).with_suffix(".py"))
        candidates.append(AGENT_SRC.joinpath(*sub) / "__init__.py")
    elif module == "src.agent.src":
        candidates.append(AGENT_SRC / "__init__.py")

    for c in candidates:
        if c.exists():
            return c
    return None


def resolve_relative(file_path: Path, level: int, module: str | None):
    base = file_path.parent
    for _ in range(level - 1):
        base = base.parent
    if module:
        base = base.joinpath(*module.split("."))
    if base.with_suffix(".py").exists():
        return base.with_suffix(".py")
    if (base / "__init__.py").exists():
        return base / "__init__.py"
    return None


def check_file(file_path: Path):
    issues = []
    text = file_path.read_text(encoding="utf-8", errors="ignore")
    try:
        tree = ast.parse(text)
    except SyntaxError as e:
        issues.append({
            "type": "syntax_error",
            "file": str(file_path),
            "line": e.lineno or 0,
            "detail": str(e),
        })
        return issues

    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            module = node.module or ""
            level = node.level or 0
            if level > 0:
                target = resolve_relative(file_path, level, module if module else None)
                if target is None:
                    issues.append({
                        "type": "missing_module",
                        "file": str(file_path),
                        "line": node.lineno,
                        "detail": f"from {'.'*level}{module} import ...",
                    })
            else:
                # focus local packages only; skip common third-party/stdlib roots
                root = module.split(".")[0] if module else ""
                if root in {"src", "agent", "tools", "utils", "services", "memdir", "constants", "query", "tasks", "hooks", "skills", "state", "api", "coordinator", "assistant", "voice", "entrypoints", "bootstrap", "bun", "agent_types"}:
                    target = module_to_file(module)
                    if target is None:
                        issues.append({
                            "type": "missing_module",
                            "file": str(file_path),
                            "line": node.lineno,
                            "detail": f"from {module} import ...",
                        })
        elif isinstance(node, ast.Import):
            for alias in node.names:
                name = alias.name
                root = name.split(".")[0]
                if root in {"src", "agent", "tools", "utils", "services", "memdir", "constants", "query", "tasks", "hooks", "skills", "state", "api", "coordinator", "assistant", "voice", "entrypoints", "bootstrap", "bun", "agent_types"}:
                    target = module_to_file(name)
                    if target is None:
                        issues.append({
                            "type": "missing_module",
                            "file": str(file_path),
                            "line": node.lineno,
                            "detail": f"import {name}",
                        })
    return issues


def main():
    files = list_py_files(AGENT_SRC)
    all_issues = []
    for f in files:
        all_issues.extend(check_file(f))

    out = ROOT / "agent_import_audit_report.json"
    out.write_text(json.dumps(all_issues, indent=2), encoding="utf-8")
    print(f"Scanned files: {len(files)}")
    print(f"Issues found: {len(all_issues)}")
    print(f"Report: {out}")
    for i in all_issues[:120]:
        rel = Path(i["file"]).relative_to(ROOT)
        print(f"{rel}:{i['line']} -> {i['detail']}")


if __name__ == "__main__":
    main()
