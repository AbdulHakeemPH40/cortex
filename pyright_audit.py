import argparse
import json
import os
import subprocess
import sys
from pathlib import Path


DEFAULT_EXCLUDE_PATH_SUBSTRINGS = [
    "/venv/",
    "/.venv/",
    "/env/",
    "/.env/",
]


def _find_repo_root(start: Path) -> Path:
    current = start.resolve()
    for _ in range(8):
        if (current / "package.json").exists() and (current / "src").exists():
            return current
        if current.parent == current:
            break
        current = current.parent
    return start.resolve()


def _find_pyright_executable(repo_root: Path) -> list[str]:
    bin_dir = repo_root / "node_modules" / ".bin"
    candidates = [
        bin_dir / "pyright.cmd",
        bin_dir / "pyright.ps1",
        bin_dir / "pyright",
    ]
    for p in candidates:
        if p.exists():
            return [str(p)]
    return ["pyright"]


def _find_project_arg(repo_root: Path) -> list[str]:
    pyright_json = repo_root / "pyrightconfig.json"
    if pyright_json.exists():
        return ["--project", str(pyright_json)]
    pyproject_toml = repo_root / "pyproject.toml"
    if pyproject_toml.exists():
        return ["--project", str(pyproject_toml)]
    return []


def _run_pyright(repo_root: Path, extra_args: list[str]) -> dict:
    cmd = _find_pyright_executable(repo_root) + ["--outputjson"] + _find_project_arg(repo_root) + extra_args
    proc = subprocess.run(
        cmd,
        cwd=str(repo_root),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    stdout = (proc.stdout or "").strip()
    if not stdout:
        raise RuntimeError(proc.stderr.strip() or "pyright produced no output")
    try:
        return json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Failed to parse pyright JSON output: {exc}\n\n{stdout[:2000]}") from exc


def _severity_rank(sev: str | None) -> int:
    s = (sev or "").lower()
    if s == "error":
        return 0
    if s == "warning":
        return 1
    if s == "information":
        return 2
    return 3


def _normalize_path(p: str, repo_root: Path) -> str:
    if not p:
        return p
    try:
        pp = Path(p)
        if pp.is_absolute():
            return os.path.relpath(str(pp), str(repo_root))
    except Exception:
        pass
    return p


def _normalize_for_match(p: str) -> str:
    return (p or "").replace("\\", "/").lower()


def _is_excluded_path(file_path: str, exclude_path_substrings: list[str]) -> bool:
    normalized = _normalize_for_match(file_path)
    return any(sub in normalized for sub in exclude_path_substrings)


IMPORT_RELATED_RULES = {
    "reportMissingImports",
    "reportMissingModuleSource",
    "reportMissingTypeStubs",
    "reportImportCycles",
    "reportDuplicateImport",
    "reportWildcardImportFromLibrary",
}


def _iter_diagnostics(report: dict) -> list[dict]:
    diagnostics = report.get("generalDiagnostics") or []
    result = []
    for d in diagnostics:
        file_path = d.get("file") or ""
        rng = d.get("range") or {}
        start = rng.get("start") or {}
        rule = d.get("rule") or ""
        severity = d.get("severity") or ""
        message = d.get("message") or ""
        result.append(
            {
                "file": file_path,
                "line": int(start.get("line", 0)) + 1,
                "character": int(start.get("character", 0)) + 1,
                "severity": severity,
                "rule": rule,
                "message": message,
            }
        )
    return result


def main() -> int:
    parser = argparse.ArgumentParser(add_help=True)
    parser.add_argument("--errors-only", action="store_true")
    parser.add_argument("--imports-only", action="store_true")
    parser.add_argument("--json-out", default="")
    parser.add_argument(
        "--exclude-path-substr",
        action="append",
        default=[],
        help="Exclude diagnostics where the file path contains this substring (case-insensitive). Can be repeated.",
    )
    parser.add_argument(
        "--no-default-excludes",
        action="store_true",
        help="Disable the default excludes (venv/.venv/env/.env).",
    )
    parser.add_argument("--extra", nargs=argparse.REMAINDER, default=[])
    args = parser.parse_args()

    repo_root = _find_repo_root(Path.cwd())
    report = _run_pyright(repo_root, args.extra)
    diagnostics = _iter_diagnostics(report)

    exclude_path_substrings = [] if args.no_default_excludes else list(DEFAULT_EXCLUDE_PATH_SUBSTRINGS)
    exclude_path_substrings.extend(_normalize_for_match(s) for s in args.exclude_path_substr)
    if exclude_path_substrings:
        diagnostics = [d for d in diagnostics if not _is_excluded_path(d.get("file", ""), exclude_path_substrings)]

    if args.errors_only:
        diagnostics = [d for d in diagnostics if (d.get("severity") or "").lower() == "error"]

    if args.imports_only:
        diagnostics = [d for d in diagnostics if d.get("rule") in IMPORT_RELATED_RULES]

    diagnostics.sort(
        key=lambda d: (
            _severity_rank(d.get("severity")),
            _normalize_path(d.get("file", ""), repo_root),
            d.get("line", 0),
            d.get("character", 0),
            d.get("rule", ""),
        )
    )

    if args.json_out:
        out_path = Path(args.json_out)
        if not out_path.is_absolute():
            out_path = repo_root / out_path
        out_path.parent.mkdir(parents=True, exist_ok=True)
        summary = dict(report.get("summary") or {})
        summary["errorCount"] = sum(1 for d in diagnostics if (d.get("severity") or "").lower() == "error")
        summary["warningCount"] = sum(1 for d in diagnostics if (d.get("severity") or "").lower() == "warning")
        summary["informationCount"] = sum(1 for d in diagnostics if (d.get("severity") or "").lower() == "information")
        out_path.write_text(
            json.dumps({"diagnostics": diagnostics, "summary": summary, "pyrightSummary": report.get("summary")}, indent=2),
            "utf-8",
        )

    error_count = sum(1 for d in diagnostics if (d.get("severity") or "").lower() == "error")
    warning_count = sum(1 for d in diagnostics if (d.get("severity") or "").lower() == "warning")

    print(f"Pyright diagnostics: {len(diagnostics)} (errors={error_count}, warnings={warning_count})")
    for d in diagnostics[:5000]:
        rel_file = _normalize_path(d.get("file", ""), repo_root)
        sev = (d.get("severity") or "").upper()
        rule = d.get("rule") or ""
        msg = d.get("message") or ""
        line = d.get("line") or 0
        col = d.get("character") or 0
        print(f"{rel_file}:{line}:{col} {sev} {rule}: {msg}")

    return 1 if error_count > 0 else 0


if __name__ == "__main__":
    raise SystemExit(main())

