"""
Memory System Test Runner.

Runs all P0-P4 tests with comprehensive reporting.

Usage:
    python run_memory_tests.py              # Run all tests
    python run_memory_tests.py --p0         # Run only P0 tests
    python run_memory_tests.py --p1         # Run only P1 tests
    python run_memory_tests.py --p3         # Run only P3 tests
    python run_memory_tests.py --p4         # Run only P4 tests
    python run_memory_tests.py --integration  # Run integration tests
    python run_memory_tests.py --verbose    # Verbose output
    python run_memory_tests.py --coverage   # Generate coverage report
"""

import sys
import os
import subprocess
import argparse
from pathlib import Path


def run_tests(test_files=None, verbose=False, coverage=False, html_report=False):
    """Run pytest on specified test files."""
    
    # Build pytest command
    cmd = [
        sys.executable, "-m", "pytest",
        "-v" if verbose else "-q",
        "--tb=short",
    ]
    
    if coverage:
        cmd.extend([
            "--cov=src/agent/src/memdir",
            "--cov=src/ui/dialogs/memory_manager",
            "--cov=src/ui/components/ai_chat",
            "--cov-report=term-missing",
        ])
        
        if html_report:
            cmd.append("--cov-report=html:tests/memory/htmlcov")
    
    # Add test files
    if test_files:
        cmd.extend(test_files)
    else:
        cmd.append("tests/memory/")
    
    print(f"\n{'='*80}")
    print(f"Running: {' '.join(cmd)}")
    print(f"{'='*80}\n")
    
    # Run pytest
    result = subprocess.run(cmd, cwd=Path(__file__).parent)
    
    return result.returncode


def main():
    parser = argparse.ArgumentParser(description="Memory System Test Runner")
    parser.add_argument("--p0", action="store_true", help="Run P0 error handling tests")
    parser.add_argument("--p1", action="store_true", help="Run P1 semantic search tests")
    parser.add_argument("--p2", action="store_true", help="Run P2 memory UI tests")
    parser.add_argument("--p3", action="store_true", help="Run P3 consolidation tests")
    parser.add_argument("--p4", action="store_true", help="Run P4 cross-project tests")
    parser.add_argument("--integration", action="store_true", help="Run integration tests")
    parser.add_argument("--all", action="store_true", help="Run all tests")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose output")
    parser.add_argument("--coverage", "-c", action="store_true", help="Generate coverage report")
    parser.add_argument("--html", action="store_true", help="Generate HTML coverage report")
    
    args = parser.parse_args()
    
    # If no specific tests selected, run all
    if not any([args.p0, args.p1, args.p2, args.p3, args.p4, args.integration]):
        args.all = True
    
    # Collect test files
    test_files = []
    
    if args.p0 or args.all:
        test_files.append("tests/memory/test_p0_error_handling.py")
    
    if args.p1 or args.all:
        test_files.append("tests/memory/test_p1_semantic_search.py")
    
    if args.p2 or args.all:
        # P2 tests would be UI tests (if created)
        print("\n⚠️  P2 UI tests: Manual testing required for UI components")
    
    if args.p3 or args.all:
        test_files.append("tests/memory/test_p3_consolidation.py")
    
    if args.p4 or args.all:
        test_files.append("tests/memory/test_p4_cross_project.py")
    
    if args.integration or args.all:
        test_files.append("tests/memory/test_integration_memory_system.py")
    
    # Run tests
    exit_code = run_tests(
        test_files=test_files,
        verbose=args.verbose,
        coverage=args.coverage,
        html_report=args.html
    )
    
    # Print summary
    print(f"\n{'='*80}")
    if exit_code == 0:
        print("✅ ALL TESTS PASSED!")
    else:
        print("❌ SOME TESTS FAILED")
    print(f"{'='*80}\n")
    
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
