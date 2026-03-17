"""
Project Analyzer for Cortex AI Agent IDE
Provides comprehensive project analysis and warmup functionality
"""

import os
import json
import ast
from pathlib import Path
from typing import Dict, List, Optional, Any, Set
from dataclasses import dataclass, field
from collections import defaultdict
import subprocess
from src.utils.logger import get_logger

log = get_logger("project_analyzer")


@dataclass
class ProjectStats:
    """Project statistics"""
    total_files: int = 0
    total_lines: int = 0
    code_lines: int = 0
    comment_lines: int = 0
    blank_lines: int = 0
    test_files: int = 0
    test_coverage: Optional[float] = None


@dataclass
class TechnologyStack:
    """Detected technology stack"""
    languages: List[str] = field(default_factory=list)
    frameworks: List[str] = field(default_factory=list)
    build_tools: List[str] = field(default_factory=list)
    databases: List[str] = field(default_factory=list)
    package_managers: List[str] = field(default_factory=list)


@dataclass
class ProjectStructure:
    """Project structure analysis"""
    root_name: str = ""
    directories: List[str] = field(default_factory=list)
    entry_points: List[str] = field(default_factory=list)
    config_files: List[str] = field(default_factory=list)
    documentation: List[str] = field(default_factory=list)
    tests_location: Optional[str] = None


@dataclass
class ProjectAnalysis:
    """Complete project analysis result"""
    project_root: str
    project_type: str = "Unknown"
    project_name: str = ""
    stats: ProjectStats = field(default_factory=ProjectStats)
    stack: TechnologyStack = field(default_factory=TechnologyStack)
    structure: ProjectStructure = field(default_factory=ProjectStructure)
    dependencies: Dict[str, List[str]] = field(default_factory=dict)
    recent_commits: List[str] = field(default_factory=list)
    git_branch: Optional[str] = None
    uncommitted_changes: int = 0
    open_issues: Optional[int] = None
    readme_content: Optional[str] = None
    architecture_summary: Optional[str] = None


class ProjectAnalyzer:
    """Analyzes project structure and generates comprehensive context"""
    
    # File type mappings
    LANGUAGE_EXTENSIONS = {
        '.py': 'Python',
        '.js': 'JavaScript',
        '.ts': 'TypeScript',
        '.jsx': 'React',
        '.tsx': 'React TypeScript',
        '.java': 'Java',
        '.kt': 'Kotlin',
        '.cpp': 'C++',
        '.c': 'C',
        '.h': 'C/C++ Header',
        '.hpp': 'C++ Header',
        '.go': 'Go',
        '.rs': 'Rust',
        '.rb': 'Ruby',
        '.php': 'PHP',
        '.swift': 'Swift',
        '.cs': 'C#',
        '.scala': 'Scala',
        '.r': 'R',
        '.m': 'Objective-C/MATLAB',
        '.mm': 'Objective-C++',
        '.lua': 'Lua',
        '.sh': 'Shell',
        '.ps1': 'PowerShell',
        '.bat': 'Batch',
        '.sql': 'SQL',
        '.html': 'HTML',
        '.css': 'CSS',
        '.scss': 'SCSS',
        '.sass': 'Sass',
        '.less': 'Less',
        '.vue': 'Vue',
        '.svelte': 'Svelte',
        '.dart': 'Dart',
        '.elm': 'Elm',
        '.clj': 'Clojure',
        '.ex': 'Elixir',
        '.exs': 'Elixir Script',
        '.hs': 'Haskell',
        '.ml': 'OCaml',
        '.fs': 'F#',
        '.fsx': 'F# Script',
        '.nim': 'Nim',
        '.cr': 'Crystal',
        '.jl': 'Julia',
    }
    
    CONFIG_PATTERNS = {
        'Python': ['requirements.txt', 'setup.py', 'pyproject.toml', 'Pipfile', 'poetry.lock'],
        'JavaScript/Node': ['package.json', 'package-lock.json', 'yarn.lock', 'pnpm-lock.yaml'],
        'TypeScript': ['tsconfig.json'],
        'Java': ['pom.xml', 'build.gradle', 'gradle.properties'],
        'Kotlin': ['build.gradle.kts'],
        'Go': ['go.mod', 'go.sum'],
        'Rust': ['Cargo.toml', 'Cargo.lock'],
        'Ruby': ['Gemfile', 'Gemfile.lock'],
        'PHP': ['composer.json', 'composer.lock'],
        'Docker': ['Dockerfile', 'docker-compose.yml', 'docker-compose.yaml', '.dockerignore'],
        'CI/CD': ['.github', '.gitlab-ci.yml', 'azure-pipelines.yml', 'Jenkinsfile'],
        'Config': ['.env', '.env.example', '.gitignore', '.editorconfig'],
    }
    
    FRAMEWORK_INDICATORS = {
        'Django': ['manage.py', 'wsgi.py', 'asgi.py', 'settings.py'],
        'Flask': ['app.py', 'application.py'],
        'FastAPI': ['main.py'],
        'React': ['src/App.js', 'src/App.jsx', 'src/App.tsx'],
        'Vue': ['vue.config.js', 'src/App.vue'],
        'Angular': ['angular.json', 'src/app/app.component.ts'],
        'Next.js': ['next.config.js', 'pages/_app.js'],
        'Express': ['server.js', 'app.js', 'index.js'],
        'Spring': ['src/main/java', 'pom.xml', 'Application.java'],
        'Rails': ['config/routes.rb', 'app/controllers'],
        'Laravel': ['artisan', 'routes/web.php'],
        'Flutter': ['pubspec.yaml', 'lib/main.dart'],
    }
    
    def __init__(self, project_root: str):
        self.project_root = Path(project_root).resolve()
        self.analysis = ProjectAnalysis(project_root=str(self.project_root))
        self._excluded_dirs = {
            '.git', '__pycache__', 'node_modules', '.venv', 'venv',
            '.tox', 'dist', 'build', '.pytest_cache', '.mypy_cache',
            '.idea', '.vs', '.vscode', 'target', 'bin', 'obj'
        }
    
    def analyze(self) -> ProjectAnalysis:
        """Perform complete project analysis"""
        log.info(f"Starting project analysis: {self.project_root}")
        
        self.analysis.project_name = self.project_root.name
        
        # Phase 1: Quick Scan
        self._analyze_structure()
        self._detect_project_type()
        self._detect_technology_stack()
        
        # Phase 2: Deep Analysis
        self._analyze_statistics()
        self._find_entry_points()
        self._analyze_dependencies()
        self._analyze_git_status()
        self._read_readme()
        
        # Phase 3: Generate Summary
        self._generate_architecture_summary()
        
        log.info(f"Project analysis complete: {self.analysis.project_type}")
        return self.analysis
    
    def _analyze_structure(self):
        """Analyze basic project structure"""
        structure = ProjectStructure(root_name=self.project_root.name)
        
        try:
            # Get top-level directories
            for item in self.project_root.iterdir():
                if item.is_dir() and item.name not in self._excluded_dirs and not item.name.startswith('.'):
                    structure.directories.append(item.name)
                elif item.is_file():
                    structure.config_files.append(item.name)
            
            # Find test directories
            test_dirs = ['tests', 'test', '__tests__', 'spec', 'specs']
            for test_dir in test_dirs:
                if (self.project_root / test_dir).exists():
                    structure.tests_location = test_dir
                    break
            
            # Find documentation
            doc_files = ['README.md', 'README.rst', 'README.txt', 'README', 
                        'CONTRIBUTING.md', 'CHANGELOG.md', 'LICENSE', 'docs']
            for doc in doc_files:
                if (self.project_root / doc).exists():
                    structure.documentation.append(doc)
        
        except Exception as e:
            log.error(f"Error analyzing structure: {e}")
        
        self.analysis.structure = structure
    
    def _detect_project_type(self):
        """Detect the primary project type"""
        # Check for specific framework indicators first
        for framework, indicators in self.FRAMEWORK_INDICATORS.items():
            for indicator in indicators:
                if (self.project_root / indicator).exists():
                    self.analysis.project_type = framework
                    if framework in ['Django', 'Flask', 'FastAPI']:
                        self.analysis.stack.languages.append('Python')
                    elif framework in ['React', 'Vue', 'Angular', 'Next.js', 'Express']:
                        self.analysis.stack.languages.append('JavaScript/TypeScript')
                    elif framework == 'Spring':
                        self.analysis.stack.languages.append('Java')
                    elif framework == 'Rails':
                        self.analysis.stack.languages.append('Ruby')
                    elif framework == 'Laravel':
                        self.analysis.stack.languages.append('PHP')
                    elif framework == 'Flutter':
                        self.analysis.stack.languages.append('Dart')
                    return
        
        # Check for config files
        for lang_type, files in self.CONFIG_PATTERNS.items():
            for file in files:
                if (self.project_root / file).exists():
                    if lang_type in ['Python']:
                        self.analysis.project_type = 'Python Project'
                    elif lang_type in ['JavaScript/Node', 'TypeScript']:
                        self.analysis.project_type = 'Node.js Project'
                    else:
                        self.analysis.project_type = f'{lang_type} Project'
                    return
        
        # Detect by file extensions
        lang_counts = defaultdict(int)
        for file_path in self._get_source_files(max_files=100):
            ext = file_path.suffix.lower()
            if ext in self.LANGUAGE_EXTENSIONS:
                lang_counts[self.LANGUAGE_EXTENSIONS[ext]] += 1
        
        if lang_counts:
            primary_lang = max(lang_counts, key=lang_counts.get)
            self.analysis.project_type = f'{primary_lang} Project'
    
    def _detect_technology_stack(self):
        """Detect the technology stack"""
        stack = TechnologyStack()
        
        # Detect languages from files
        lang_counts = defaultdict(int)
        for file_path in self._get_source_files(max_files=200):
            ext = file_path.suffix.lower()
            if ext in self.LANGUAGE_EXTENSIONS:
                lang_counts[self.LANGUAGE_EXTENSIONS[ext]] += 1
        
        # Sort by count and take top languages
        sorted_langs = sorted(lang_counts.items(), key=lambda x: x[1], reverse=True)
        stack.languages = [lang for lang, count in sorted_langs[:5]]
        
        # Detect frameworks
        for framework, indicators in self.FRAMEWORK_INDICATORS.items():
            for indicator in indicators:
                if (self.project_root / indicator).exists():
                    stack.frameworks.append(framework)
                    break
        
        # Detect build tools
        build_tools = {
            'npm': 'package-lock.json',
            'yarn': 'yarn.lock',
            'pnpm': 'pnpm-lock.yaml',
            'pip': 'requirements.txt',
            'poetry': 'poetry.lock',
            'pipenv': 'Pipfile',
            'Maven': 'pom.xml',
            'Gradle': 'build.gradle',
            'Cargo': 'Cargo.toml',
            'Bundler': 'Gemfile',
            'Composer': 'composer.json',
        }
        for tool, indicator in build_tools.items():
            if (self.project_root / indicator).exists():
                stack.build_tools.append(tool)
        
        # Detect databases
        db_indicators = {
            'PostgreSQL': ['psycopg2', 'pg', 'postgresql'],
            'MySQL': ['mysql', 'mysqldb'],
            'MongoDB': ['pymongo', 'mongodb', 'mongoose'],
            'Redis': ['redis', 'redis-py'],
            'SQLite': ['sqlite3', 'sqlite'],
            'Elasticsearch': ['elasticsearch'],
        }
        # Check dependencies for database hints
        deps_text = self._get_dependencies_text()
        for db, indicators in db_indicators.items():
            for indicator in indicators:
                if indicator in deps_text.lower():
                    stack.databases.append(db)
                    break
        
        self.analysis.stack = stack
    
    def _analyze_statistics(self):
        """Analyze code statistics"""
        stats = ProjectStats()
        
        try:
            for file_path in self._get_source_files():
                stats.total_files += 1
                
                # Check if test file
                if 'test' in file_path.name.lower() or 'spec' in file_path.name.lower():
                    stats.test_files += 1
                
                # Count lines
                try:
                    with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                        for line in f:
                            stats.total_lines += 1
                            stripped = line.strip()
                            if not stripped:
                                stats.blank_lines += 1
                            elif stripped.startswith('#') or stripped.startswith('//') or stripped.startswith('/*'):
                                stats.comment_lines += 1
                            else:
                                stats.code_lines += 1
                except Exception as e:
                    log.debug(f"Error reading {file_path}: {e}")
        
        except Exception as e:
            log.error(f"Error analyzing statistics: {e}")
        
        self.analysis.stats = stats
    
    def _find_entry_points(self):
        """Find project entry points"""
        entry_points = []
        
        common_entries = [
            'main.py', 'app.py', 'manage.py', 'server.py', 'index.js',
            'main.js', 'main.ts', 'index.ts', 'App.java', 'main.go',
            'main.rs', 'src/main.py', 'src/main.js', 'src/main.ts',
            'src/App.tsx', 'src/App.jsx', 'src/index.js', 'src/index.ts'
        ]
        
        for entry in common_entries:
            if (self.project_root / entry).exists():
                entry_points.append(entry)
        
        self.analysis.structure.entry_points = entry_points[:5]  # Top 5
    
    def _analyze_dependencies(self):
        """Analyze project dependencies"""
        deps = defaultdict(list)
        
        # Python requirements.txt
        req_file = self.project_root / 'requirements.txt'
        if req_file.exists():
            try:
                with open(req_file, 'r') as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith('#'):
                            deps['Python'].append(line.split('==')[0].split('>=')[0])
            except Exception as e:
                log.debug(f"Error reading requirements.txt: {e}")
        
        # Python setup.py
        setup_file = self.project_root / 'setup.py'
        if setup_file.exists():
            try:
                with open(setup_file, 'r') as f:
                    content = f.read()
                    if 'install_requires' in content:
                        # Extract install_requires list
                        import re
                        match = re.search(r'install_requires\s*=\s*\[(.*?)\]', content, re.DOTALL)
                        if match:
                            deps_list = match.group(1)
                            packages = re.findall(r'["\']([^"\']+)["\']', deps_list)
                            deps['Python'].extend(packages)
            except Exception as e:
                log.debug(f"Error reading setup.py: {e}")
        
        # Node.js package.json
        pkg_file = self.project_root / 'package.json'
        if pkg_file.exists():
            try:
                with open(pkg_file, 'r') as f:
                    pkg = json.load(f)
                    if 'dependencies' in pkg:
                        deps['Production'].extend(pkg['dependencies'].keys())
                    if 'devDependencies' in pkg:
                        deps['Development'].extend(pkg['devDependencies'].keys())
            except Exception as e:
                log.debug(f"Error reading package.json: {e}")
        
        self.analysis.dependencies = dict(deps)
    
    def _analyze_git_status(self):
        """Analyze git repository status"""
        try:
            # Get current branch
            result = subprocess.run(
                ['git', 'branch', '--show-current'],
                cwd=self.project_root,
                capture_output=True,
                text=True
            )
            if result.returncode == 0:
                self.analysis.git_branch = result.stdout.strip()
            
            # Get recent commits
            result = subprocess.run(
                ['git', 'log', '--oneline', '-10'],
                cwd=self.project_root,
                capture_output=True,
                text=True
            )
            if result.returncode == 0:
                self.analysis.recent_commits = result.stdout.strip().split('\n')[:5]
            
            # Get uncommitted changes count
            result = subprocess.run(
                ['git', 'status', '--short'],
                cwd=self.project_root,
                capture_output=True,
                text=True
            )
            if result.returncode == 0:
                self.analysis.uncommitted_changes = len(result.stdout.strip().split('\n'))
        
        except Exception as e:
            log.debug(f"Error analyzing git status: {e}")
    
    def _read_readme(self):
        """Read README content"""
        readme_files = ['README.md', 'README.rst', 'README.txt', 'README']
        
        for readme_name in readme_files:
            readme_path = self.project_root / readme_name
            if readme_path.exists():
                try:
                    with open(readme_path, 'r', encoding='utf-8', errors='ignore') as f:
                        content = f.read()
                        # Store first 2000 chars
                        self.analysis.readme_content = content[:2000]
                        break
                except Exception as e:
                    log.debug(f"Error reading README: {e}")
    
    def _get_source_files(self, max_files: Optional[int] = None) -> List[Path]:
        """Get list of source files to analyze"""
        files = []
        count = 0
        
        try:
            for root, dirs, filenames in os.walk(self.project_root):
                # Filter out excluded directories
                dirs[:] = [d for d in dirs if d not in self._excluded_dirs and not d.startswith('.')]
                
                for filename in filenames:
                    if max_files and count >= max_files:
                        return files
                    
                    file_path = Path(root) / filename
                    ext = file_path.suffix.lower()
                    
                    # Include known source extensions
                    if ext in self.LANGUAGE_EXTENSIONS:
                        files.append(file_path)
                        count += 1
        
        except Exception as e:
            log.error(f"Error walking project directory: {e}")
        
        return files
    
    def _get_dependencies_text(self) -> str:
        """Get combined text of dependency files"""
        text = ""
        
        dep_files = ['requirements.txt', 'package.json', 'Cargo.toml', 'Gemfile', 'composer.json']
        for dep_file in dep_files:
            file_path = self.project_root / dep_file
            if file_path.exists():
                try:
                    with open(file_path, 'r') as f:
                        text += f.read() + "\n"
                except Exception:
                    pass
        
        return text
    
    def _generate_architecture_summary(self):
        """Generate a human-readable architecture summary"""
        parts = []
        
        parts.append(f"# {self.analysis.project_name}")
        parts.append(f"\n**Type:** {self.analysis.project_type}")
        
        # Languages
        if self.analysis.stack.languages:
            parts.append(f"**Primary Languages:** {', '.join(self.analysis.stack.languages[:3])}")
        
        # Frameworks
        if self.analysis.stack.frameworks:
            parts.append(f"**Frameworks:** {', '.join(self.analysis.stack.frameworks)}")
        
        # Statistics
        stats = self.analysis.stats
        parts.append(f"\n**Statistics:**")
        parts.append(f"- Total Files: {stats.total_files}")
        parts.append(f"- Lines of Code: {stats.code_lines:,}")
        parts.append(f"- Test Files: {stats.test_files}")
        
        # Entry Points
        if self.analysis.structure.entry_points:
            parts.append(f"\n**Entry Points:**")
            for ep in self.analysis.structure.entry_points[:3]:
                parts.append(f"- `{ep}`")
        
        # Key Dependencies
        if self.analysis.dependencies:
            parts.append(f"\n**Key Dependencies:**")
            for category, deps in list(self.analysis.dependencies.items())[:2]:
                if deps:
                    top_deps = deps[:5]
                    parts.append(f"- {category}: {', '.join(top_deps)}")
        
        # Git Status
        if self.analysis.git_branch:
            parts.append(f"\n**Git Status:**")
            parts.append(f"- Branch: `{self.analysis.git_branch}`")
            parts.append(f"- Uncommitted Changes: {self.analysis.uncommitted_changes}")
        
        self.analysis.architecture_summary = "\n".join(parts)
    
    def generate_warmup_report(self) -> str:
        """Generate a comprehensive warmup report for display"""
        if not self.analysis.architecture_summary:
            self.analyze()
        
        return f"""## 👋 Welcome to {self.analysis.project_name}!

{self.analysis.architecture_summary}

---

### 🎯 Project Overview

I've analyzed your project and here's what I found:

**Project Type:** {self.analysis.project_type}
**Languages:** {', '.join(self.analysis.stack.languages[:5]) if self.analysis.stack.languages else 'N/A'}
**Frameworks:** {', '.join(self.analysis.stack.frameworks[:3]) if self.analysis.stack.frameworks else 'N/A'}

### 📊 Code Statistics
- **Total Files:** {self.analysis.stats.total_files}
- **Lines of Code:** {self.analysis.stats.code_lines:,}
- **Comments:** {self.analysis.stats.comment_lines:,}
- **Test Files:** {self.analysis.stats.test_files}

### 🚀 Entry Points
{chr(10).join([f"- `{ep}`" for ep in self.analysis.structure.entry_points[:5]]) if self.analysis.structure.entry_points else '- Not detected'}

### 📁 Key Directories
{chr(10).join([f"- `{d}/`" for d in self.analysis.structure.directories[:8]]) if self.analysis.structure.directories else '- Not detected'}

### 🔧 Build Tools
{', '.join(self.analysis.stack.build_tools) if self.analysis.stack.build_tools else 'Not detected'}

---

### 💡 What would you like to do?

I can help you with:

1. **🔍 Explore** - Understand specific files or modules
2. **✨ Enhance** - Improve existing code or add features
3. **🐛 Debug** - Find and fix issues
4. **📝 Document** - Add documentation or comments
5. **🧪 Test** - Write or improve tests
6. **🚀 Deploy** - Prepare for deployment

**Just tell me what you need!** (e.g., "Explain the auth system", "Add error handling", "Refactor the API")
"""


# Singleton instance
_analyzer = None


def get_project_analyzer(project_root: str) -> ProjectAnalyzer:
    """Get or create project analyzer"""
    global _analyzer
    if _analyzer is None or str(_analyzer.project_root) != str(Path(project_root).resolve()):
        _analyzer = ProjectAnalyzer(project_root)
    return _analyzer
