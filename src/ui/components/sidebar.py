"""
Left Sidebar Component — File explorer, Search, Git, and AI Tools panels.
"""

import os
from pathlib import Path
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QStackedWidget,
    QPushButton, QTreeView, QLineEdit, QListWidget, QListWidgetItem,
    QLabel, QMenu, QInputDialog, QMessageBox, QFrame,
    QSizePolicy, QComboBox, QSlider, QStyledItemDelegate, QStyle,
    QApplication
)
from PyQt6.QtCore import Qt, pyqtSignal, QDir, QModelIndex, QSize, QRect, QTimer
from PyQt6.QtGui import (
    QIcon, QAction, QFont, QFileSystemModel, QColor, QPainter,
    QFontMetrics, QPalette
)
from src.utils.helpers import detect_language
from src.utils.logger import get_logger
from src.utils.icons import make_icon, make_button_icon, make_sprite_icon

log = get_logger("sidebar")

def _get_icon_name(path: str) -> str:
    """Map file/folder path → OpenCode sprite IconName (e.g. 'Python', 'Typescript')."""
    p = Path(path)
    if p.is_dir():
        folder = p.name.lower().strip('/')
        _FOLDER_MAP = {
            'src': 'FolderSrc', 'source': 'FolderSrc',
            'lib': 'FolderLib', 'libs': 'FolderLib',
            'test': 'FolderTest', 'tests': 'FolderTest',
            '__tests__': 'FolderTest', 'spec': 'FolderTest', 'e2e': 'FolderTest',
            'node_modules': 'FolderNode',
            'vendor': 'FolderPackages', 'packages': 'FolderPackages',
            'build': 'FolderBuildkite', 'dist': 'FolderDist',
            'out': 'FolderDist', 'output': 'FolderDist', 'target': 'FolderTarget',
            'config': 'FolderConfig', 'configs': 'FolderConfig',
            'env': 'FolderEnvironment', 'environments': 'FolderEnvironment',
            'docker': 'FolderDocker', 'containers': 'FolderDocker',
            'docs': 'FolderDocs', 'doc': 'FolderDocs', 'documentation': 'FolderDocs',
            'public': 'FolderPublic', 'static': 'FolderPublic',
            'assets': 'FolderImages', 'images': 'FolderImages',
            'img': 'FolderImages', 'icons': 'FolderImages', 'media': 'FolderImages',
            'fonts': 'FolderFont',
            'styles': 'FolderCss', 'stylesheets': 'FolderCss', 'css': 'FolderCss',
            'sass': 'FolderSass', 'scss': 'FolderSass',
            'scripts': 'FolderScripts', 'script': 'FolderScripts',
            'utils': 'FolderUtils', 'utilities': 'FolderUtils',
            'helpers': 'FolderHelper', 'tools': 'FolderTools',
            'components': 'FolderComponents', 'component': 'FolderComponents',
            'views': 'FolderViews', 'view': 'FolderViews',
            'layouts': 'FolderLayout', 'layout': 'FolderLayout',
            'templates': 'FolderTemplate', 'template': 'FolderTemplate',
            'hooks': 'FolderHook', 'hook': 'FolderHook',
            'store': 'FolderStore', 'stores': 'FolderStore',
            'reducers': 'FolderReduxReducer', 'reducer': 'FolderReduxReducer',
            'services': 'FolderApi', 'service': 'FolderApi',
            'api': 'FolderApi', 'apis': 'FolderApi',
            'routes': 'FolderRoutes', 'route': 'FolderRoutes',
            'middleware': 'FolderMiddleware', 'middlewares': 'FolderMiddleware',
            'controllers': 'FolderController', 'controller': 'FolderController',
            'models': 'FolderDatabase', 'model': 'FolderDatabase',
            'schemas': 'FolderDatabase', 'migrations': 'FolderDatabase',
            'types': 'FolderTypescript', 'typing': 'FolderTypescript',
            'typings': 'FolderTypescript', '@types': 'FolderTypescript',
            'android': 'FolderAndroid', 'ios': 'FolderIos',
            'flutter': 'FolderFlutter', 'mobile': 'FolderMobile',
            'kubernetes': 'FolderKubernetes', 'k8s': 'FolderKubernetes',
            'terraform': 'FolderTerraform',
            'aws': 'FolderAws', 'firebase': 'FolderFirebase',
            '.github': 'FolderGithub', '.gitlab': 'FolderGitlab',
            '.git': 'FolderGit', 'workflows': 'FolderGhWorkflows',
            '.vscode': 'FolderVscode', '.idea': 'FolderIntellij',
            '.cursor': 'FolderCursor', '.storybook': 'FolderStorybook',
            'i18n': 'FolderI18n', 'locales': 'FolderI18n', 'lang': 'FolderI18n',
            'temp': 'FolderTemp', 'tmp': 'FolderTemp',
            'logs': 'FolderLog', 'log': 'FolderLog',
            'mocks': 'FolderMock', 'mock': 'FolderMock',
            'data': 'FolderDatabase', 'database': 'FolderDatabase', 'db': 'FolderDatabase',
            'prisma': 'FolderPrisma', 'drizzle': 'FolderDrizzle',
            'functions': 'FolderFunctions', 'lambda': 'FolderFunctions',
            'security': 'FolderSecure', 'auth': 'FolderSecure',
            'keys': 'FolderKeys', 'certs': 'FolderKeys',
            'examples': 'FolderExamples', 'example': 'FolderExamples',
            'venv': 'FolderPython', '.venv': 'FolderPython',
        }
        return _FOLDER_MAP.get(folder, _FOLDER_MAP.get(folder.lstrip('.'), 'FolderBlue'))

    # Exact filename matches
    name_lower = p.name.lower()
    _FILENAME_MAP = {
        'package.json': 'Nodejs', 'package-lock.json': 'Nodejs',
        '.nvmrc': 'Nodejs', '.node-version': 'Nodejs',
        'yarn.lock': 'Yarn', 'pnpm-lock.yaml': 'Pnpm',
        'bun.lock': 'Bun', 'bun.lockb': 'Bun', 'bunfig.toml': 'Bun',
        'dockerfile': 'Docker', 'docker-compose.yml': 'Docker',
        'docker-compose.yaml': 'Docker', '.dockerignore': 'Docker',
        '.gitignore': 'Git', '.gitattributes': 'Git', '.gitmodules': 'Git',
        'tsconfig.json': 'Tsconfig', 'jsconfig.json': 'Jsconfig',
        'vite.config.js': 'Vite', 'vite.config.ts': 'Vite',
        'tailwind.config.js': 'Tailwindcss', 'tailwind.config.ts': 'Tailwindcss',
        'jest.config.js': 'Jest', 'jest.config.ts': 'Jest',
        'vitest.config.js': 'Vitest', 'vitest.config.ts': 'Vitest',
        '.eslintrc': 'Eslint', '.eslintrc.js': 'Eslint', '.eslintrc.json': 'Eslint',
        '.prettierrc': 'Prettier', '.prettierrc.js': 'Prettier',
        'webpack.config.js': 'Webpack', 'rollup.config.js': 'Rollup',
        'next.config.js': 'Next', 'next.config.mjs': 'Next',
        'nuxt.config.js': 'Nuxt', 'nuxt.config.ts': 'Nuxt',
        'svelte.config.js': 'Svelte', 'astro.config.mjs': 'AstroConfig',
        'gatsby-config.js': 'Gatsby', 'remix.config.js': 'Remix',
        'cargo.toml': 'Rust', 'go.mod': 'GoMod', 'go.sum': 'GoMod',
        'requirements.txt': 'Python', 'pyproject.toml': 'Python',
        'pipfile': 'Python', 'poetry.lock': 'Poetry',
        'gemfile': 'Gemfile', 'rakefile': 'Ruby',
        'composer.json': 'Php', 'build.gradle': 'Gradle', 'pom.xml': 'Maven',
        'deno.json': 'Deno', 'deno.jsonc': 'Deno',
        'vercel.json': 'Vercel', 'netlify.toml': 'Netlify',
        '.env': 'Tune', '.env.local': 'Tune', '.env.example': 'Tune',
        '.editorconfig': 'Editorconfig', 'makefile': 'Makefile',
        'robots.txt': 'Robots', 'favicon.ico': 'Favicon',
        '.babelrc': 'Babel', 'babel.config.js': 'Babel',
        'firebase.json': 'Firebase', 'angular.json': 'Angular',
        'nx.json': 'Nx', 'lerna.json': 'Lerna',
        'turbo.json': 'Turborepo',
        'readme.md': 'Readme', 'readme': 'Readme',
        'changelog.md': 'Changelog', 'license': 'Certificate',
        'wrangler.toml': 'Wrangler', 'renovate.json': 'Renovate',
    }
    icon = _FILENAME_MAP.get(name_lower)
    if icon:
        return icon

    # Extension map → OpenCode sprite IconName
    suffix = p.suffix.lower()
    _EXT_MAP = {
        # Python
        '.py': 'Python', '.pyw': 'Python', '.pyi': 'Python', '.pyx': 'Python',
        # JS/TS
        '.js': 'Javascript', '.mjs': 'Javascript', '.cjs': 'Javascript',
        '.ts': 'Typescript', '.tsx': 'React_ts', '.jsx': 'React',
        '.d.ts': 'TypescriptDef',
        # Web
        '.html': 'Html', '.htm': 'Html',
        '.css': 'Css', '.scss': 'Sass', '.sass': 'Sass', '.less': 'Less', '.styl': 'Stylus',
        '.vue': 'Vue', '.svelte': 'Svelte',
        # Java ecosystem
        '.java': 'Java', '.jar': 'Java', '.groovy': 'Groovy',
        '.kt': 'Kotlin', '.kts': 'Kotlin', '.scala': 'Scala',
        # .NET
        '.cs': 'Csharp', '.vb': 'Visualstudio', '.fs': 'Fsharp',
        # C/C++
        '.cpp': 'Cpp', '.cc': 'Cpp', '.cxx': 'Cpp',
        '.c': 'C', '.h': 'H', '.hpp': 'Hpp',
        # Systems
        '.rs': 'Rust', '.go': 'Go', '.nim': 'Nim', '.zig': 'Zig',
        '.v': 'Vlang', '.odin': 'Odin', '.gleam': 'Gleam',
        # Scripting
        '.rb': 'Ruby', '.erb': 'Ruby',
        '.php': 'Php',
        '.pl': 'Perl', '.pm': 'Perl',
        # Shell
        '.sh': 'Console', '.bash': 'Console', '.zsh': 'Console', '.fish': 'Console',
        '.bat': 'Console', '.cmd': 'Console', '.ps1': 'Powershell',
        # Mobile
        '.swift': 'Swift', '.dart': 'Dart', '.m': 'ObjectiveC', '.mm': 'ObjectiveCpp',
        # Functional
        '.hs': 'Haskell', '.lhs': 'Haskell', '.elm': 'Elm',
        '.ex': 'Elixir', '.exs': 'Elixir', '.erl': 'Erlang',
        '.clj': 'Clojure', '.cljs': 'Clojure', '.cljc': 'Clojure',
        '.ml': 'Ocaml', '.mli': 'Ocaml',
        '.lua': 'Lua', '.r': 'R', '.jl': 'Julia',
        # Data/config
        '.json': 'Json', '.json5': 'Json', '.jsonc': 'Json',
        '.yaml': 'Yaml', '.yml': 'Yaml',
        '.toml': 'Toml', '.ini': 'Settings', '.cfg': 'Settings', '.conf': 'Settings',
        '.xml': 'Xml', '.xsd': 'Xml', '.xsl': 'Xml',
        '.env': 'Tune',
        '.sql': 'Database', '.sqlite': 'Database', '.db': 'Database',
        '.graphql': 'Graphql', '.gql': 'Graphql',
        '.proto': 'Proto', '.wasm': 'Webassembly',
        # Docs
        '.md': 'Markdown', '.mdx': 'Mdx', '.markdown': 'Markdown', '.tex': 'Tex',
        '.rst': 'Readme',
        # Git
        '.gitignore': 'Git', '.gitattributes': 'Git',
        # Docker
        '.dockerfile': 'Docker', '.dockerignore': 'Docker',
        # Media
        '.svg': 'Svg', '.png': 'Image', '.jpg': 'Image', '.jpeg': 'Image',
        '.gif': 'Image', '.webp': 'Image', '.bmp': 'Image', '.ico': 'Favicon',
        '.mp4': 'Video', '.mov': 'Video', '.avi': 'Video', '.webm': 'Video',
        '.mp3': 'Audio', '.wav': 'Audio', '.flac': 'Audio',
        # Documents
        '.pdf': 'Pdf', '.doc': 'Word', '.docx': 'Word',
        '.ppt': 'Powerpoint', '.pptx': 'Powerpoint',
        '.xls': 'Document', '.xlsx': 'Document', '.csv': 'Document',
        # Archives
        '.zip': 'Zip', '.tar': 'Zip', '.gz': 'Zip', '.rar': 'Zip', '.7z': 'Zip',
        # Other
        '.log': 'Log', '.lock': 'Lock', '.key': 'Key',
        '.pem': 'Certificate', '.crt': 'Certificate',
        '.txt': 'Document',
    }
    return _EXT_MAP.get(suffix, 'Document')


# ── Custom delegate for VS Code-style rows ─────────────────────────────────────
class FileTreeDelegate(QStyledItemDelegate):
    """Draws each tree row with a colored icon + filename."""

    def __init__(self, model: QFileSystemModel, parent=None):
        super().__init__(parent)
        self._model = model
        self._is_dark = True

    def set_dark(self, is_dark: bool):
        self._is_dark = is_dark

    def paint(self, painter: QPainter, option, index: QModelIndex):
        self.initStyleOption(option, index)

        filepath = self._model.filePath(index)
        name = Path(filepath).name
        is_dir = Path(filepath).is_dir()

        # Row background
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        hovered  = bool(option.state & QStyle.StateFlag.State_MouseOver)
        if selected:
            painter.fillRect(option.rect, QColor("#094771" if self._is_dark else "#cce5ff"))
        elif hovered:
            painter.fillRect(option.rect, QColor("#2a2d2e" if self._is_dark else "#f0f4ff"))

        x = option.rect.left() + 2  # running x cursor

        # ── Chevron arrow for directories ──────────────────────────────────
        if is_dir:
            view = option.widget
            expanded = view.isExpanded(index) if (view and hasattr(view, 'isExpanded')) else False
            chevron = "▼" if expanded else "▶"
            chevron_rect = QRect(x, option.rect.top(), 14, option.rect.height())
            painter.save()
            arrow_color = "#cccccc" if self._is_dark else "#555555"
            painter.setPen(QColor(arrow_color))
            f0 = painter.font()
            f0.setPointSize(8)
            painter.setFont(f0)
            painter.drawText(chevron_rect,
                             Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                             chevron)
            painter.restore()
            x += 14  # shift rest right

        # ── VS Code-style SVG Icons from OpenCode sprite ─────────────────
        icon_name = _get_icon_name(filepath)
        # Mark expanded folders with open variant
        if is_dir:
            view = option.widget
            expanded = view.isExpanded(index) if (view and hasattr(view, 'isExpanded')) else False
            if expanded and not icon_name.endswith('Open'):
                icon_name = icon_name + 'Open'

        icon_size = 20
        icon = make_sprite_icon(icon_name, icon_size)
        pixmap = icon.pixmap(icon_size, icon_size)

        icon_rect = QRect(x, option.rect.top() + (option.rect.height() - icon_size) // 2, icon_size, icon_size)
        painter.drawPixmap(icon_rect, pixmap)
        x += icon_size + 6

        # ── Filename ───────────────────────────────────────────────────────
        text_rect = QRect(x, option.rect.top(),
                          option.rect.right() - x - 2,
                          option.rect.height())
        fg = "#d4d4d4" if self._is_dark else "#1a1a1a"
        if selected:
            fg = "#ffffff" if self._is_dark else "#003d80"

        painter.save()
        painter.setPen(QColor(fg))
        f2 = painter.font()
        f2.setPointSize(11)
        f2.setBold(is_dir)
        painter.setFont(f2)
        fm = QFontMetrics(f2)
        elided = fm.elidedText(name, Qt.TextElideMode.ElideMiddle, text_rect.width())
        painter.drawText(text_rect,
                         Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                         elided)
        painter.restore()

    def sizeHint(self, option, index) -> QSize:
        return QSize(120, 24)


# ── Tree View with VS Code-style QSS ──────────────────────────────────────────
TREE_QSS_DARK = """
QTreeView {
    background: #1e1e1e;
    border: none;
    outline: 0;
    font-size: 12px;
}
QTreeView::item {
    height: 24px;
    border-radius: 3px;
    padding-left: 2px;
}
QTreeView::item:hover      { 
    background: #37373d;
    color: #ffffff;
}
QTreeView::item:selected   { 
    background: #094771; 
    color: #ffffff;
    border: 1px solid #007acc;
}
QTreeView::branch {
    background: #1e1e1e;
}
QTreeView::branch:has-children:!has-siblings:closed,
QTreeView::branch:closed:has-children:has-siblings {
    image: none;
    border-image: none;
}
QTreeView::branch:open:has-children:!has-siblings,
QTreeView::branch:open:has-children:has-siblings  {
    image: none;
    border-image: none;
}
"""

TREE_QSS_LIGHT = """
QTreeView {
    background: #ffffff;
    border: none;
    outline: 0;
    font-size: 12px;
    color: #1a1a1a;
}
QTreeView::item {
    height: 24px;
    border-radius: 3px;
    padding-left: 2px;
}
QTreeView::item:hover      { 
    background: #d4d4d4;
    color: #1a1a1a;
}
QTreeView::item:selected   { 
    background: #cce5ff; 
    color: #003d80;
    border: 1px solid #007acc;
}
QTreeView::branch {
    background: #ffffff;
}
"""

SKIP_DIRS = {'.git', '__pycache__', 'node_modules', '.venv',
             '.idea', '.vs', 'build', 'dist', '.tox'}


class VsCodeFileTree(QTreeView):
    """QTreeView subclass: single-click expands folders."""
    file_deleted = pyqtSignal(str)

    def __init__(self, file_manager=None, explorer=None, parent=None):
        super().__init__(parent)
        self._file_manager = file_manager
        self._explorer = explorer  # Direct reference to FileExplorerPanel
        self.setMouseTracking(True)
        self.setExpandsOnDoubleClick(False)  # we handle manually
        self.setSelectionMode(QTreeView.SelectionMode.ExtendedSelection)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.viewport().setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.setDragDropMode(QTreeView.DragDropMode.InternalMove)

    def _find_explorer(self):
        """Return the directly linked explorer panel."""
        return self._explorer

    def keyPressEvent(self, event):
        """Handle keyboard shortcuts for file operations."""
        # ── 1. Copy / Cut / Paste (VS Code style) ───────────────────
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            if event.key() == Qt.Key.Key_C:
                self._handle_copy()
                return
            elif event.key() == Qt.Key.Key_X:
                self._handle_cut()
                return
            elif event.key() == Qt.Key.Key_V:
                self._handle_paste()
                return

        # ── 2. Delete / Backspace ──────────────────────────────────
        if event.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            paths = self._get_selected_paths()
            if paths:
                self._delete_items(paths)
                return

        super().keyPressEvent(event)
        if event.key() in (Qt.Key.Key_Up, Qt.Key.Key_Down):
            self.viewport().update()

    def _handle_copy(self):
        paths = self._get_selected_paths()
        print(f"[COPY] selected paths: {paths}")   # DEBUG
        if paths and self._explorer:
            self._explorer._clipboard_paths = paths
            self._explorer._clipboard_mode = "copy"
            print(f"[COPY] clipboard set to: {paths}")   # DEBUG
            log.info(f"📋 Copied: {', '.join([Path(p).name for p in paths])}")
        elif not paths:
            print("[COPY] Nothing selected — no paths found")
        elif not self._explorer:
            print("[COPY] ERROR: _explorer is None")

    def _handle_cut(self):
        paths = self._get_selected_paths()
        print(f"[CUT] selected paths: {paths}")   # DEBUG
        if paths and self._explorer:
            self._explorer._clipboard_paths = paths
            self._explorer._clipboard_mode = "cut"
            log.info(f"✂️ Cut: {', '.join([Path(p).name for p in paths])}")
        elif not self._explorer:
            print("[CUT] ERROR: _explorer is None")

    def _handle_paste(self):
        print(f"[PASTE] explorer={self._explorer}, clipboard={getattr(self._explorer, '_clipboard_paths', None)}")  # DEBUG
        if not self._explorer or not self._explorer._clipboard_paths:
            print("[PASTE] Aborted — clipboard empty or no explorer")
            return

        # Target directory: selected folder, or parent folder if file selected, or project root
        idx = self.currentIndex()
        if idx.isValid():
            path = self.model().filePath(idx)
            target_dir = path if Path(path).is_dir() else str(Path(path).parent)
        else:
            target_dir = self._explorer._root_path

        print(f"[PASTE] target_dir={target_dir}")  # DEBUG
        if target_dir:
            self._explorer._paste_into(target_dir)

    def _get_selected_paths(self) -> list[str]:
        """Get all selected file paths. Uses selectedIndexes() filtered to col 0.
        NOTE: selectedRows() does NOT work with QFileSystemModel — it always returns []
        because QFileSystemModel uses SelectItems not SelectRows behaviour.
        """
        seen: set[str] = set()
        paths: list[str] = []
        for idx in self.selectionModel().selectedIndexes():
            if idx.column() == 0:  # avoid duplicates from other columns
                p = self.model().filePath(idx)
                if p not in seen:
                    seen.add(p)
                    paths.append(p)
        return paths

    # ── Drag and Drop Support ──────────────────────────────────────────

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event):
        event.acceptProposedAction()

    def dropEvent(self, event):
        """Handle drops: external folder = open as project, internal = move files."""
        if event.mimeData().hasUrls():
            urls = event.mimeData().urls()
            paths = [url.toLocalFile() for url in urls if url.toLocalFile()]
            
            if not paths:
                super().dropEvent(event)
                return

            # Detect if this is an EXTERNAL drop (from Windows Explorer / Desktop)
            # by checking if the source is outside the current project root
            explorer = self._find_explorer()
            project_root = explorer._root_path if explorer else None
            
            if project_root:
                # Normalize for comparison
                norm_root = os.path.normcase(os.path.normpath(project_root))
                
                # Check if ANY dropped path is outside the project
                is_external = False
                for p in paths:
                    norm_p = os.path.normcase(os.path.normpath(p))
                    if not norm_p.startswith(norm_root):
                        is_external = True
                        break
                
                if is_external:
                    # External drop: open folder as project or open file
                    # Delegate to the main window
                    main_win = self.window()
                    if main_win and hasattr(main_win, '_open_folder_programmatic'):
                        for p in paths:
                            if os.path.isdir(p):
                                main_win._open_folder_programmatic(p)
                                event.acceptProposedAction()
                                return
                            elif os.path.isfile(p):
                                main_win._open_file(p)
                                event.acceptProposedAction()
                                return
                    event.acceptProposedAction()
                    return

            # Internal drop: move files within project
            index = self.indexAt(event.position().toPoint())
            target_dir = None
            if index.isValid():
                path = self.model().filePath(index)
                if Path(path).is_dir():
                    target_dir = path
                else:
                    target_dir = str(Path(path).parent)
            else:
                target_dir = project_root

            if target_dir and paths:
                if explorer and self._file_manager:
                    from PyQt6.QtWidgets import QMessageBox
                    
                    target_name = Path(target_dir).name
                    item_count = len(paths)
                    item_desc = f"'{Path(paths[0]).name}'" if item_count == 1 else f"these {item_count} items"
                    
                    msg = f"Are you sure you want to move {item_desc} into '{target_name}'?\n\nThis action can be undone with Ctrl+Z."
                    reply = QMessageBox.question(
                        self, 'Confirm Move', msg,
                        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                        QMessageBox.StandardButton.Yes
                    )
                    
                    if reply == QMessageBox.StandardButton.Yes:
                        for p in paths:
                            if target_dir.startswith(p):
                                continue
                            self._file_manager.move(p, target_dir)
                        event.acceptProposedAction()
                    return

        super().dropEvent(event)

    def _delete_items(self, paths):
        """Show confirmation dialog and delete multiple files/folders (moves to trash)."""
        if not paths: return
        
        from PyQt6.QtWidgets import QMessageBox
        from pathlib import Path
        
        count = len(paths)
        if count == 1:
            name = Path(paths[0]).name
            msg = f"Are you sure you want to delete '{name}'?"
        else:
            msg = f"Are you sure you want to delete {count} selected items?"
            
        msg_box = QMessageBox(
            QMessageBox.Icon.Question, "Delete",
            msg + "\n\nThis action can be undone with Ctrl+Z.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            self
        )
        msg_box.setDefaultButton(QMessageBox.StandardButton.Yes)
        
        reply = msg_box.exec()
        
        if reply == QMessageBox.StandardButton.Yes:
            if self._file_manager:
                success_count = 0
                for path in paths:
                    if self._file_manager.delete(path):
                        success_count += 1
                
                if success_count < len(paths):
                    QMessageBox.warning(self, "Delete Partial", f"Successfully deleted {success_count} of {len(paths)} items.")
            else:
                QMessageBox.critical(self, "Delete Failed", "FileManager not available")

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.RightButton:
            # Right click: select item if not already selected
            index = self.indexAt(event.pos())
            if index.isValid():
                if not self.selectionModel().isSelected(index):
                    self.setCurrentIndex(index)
            super().mousePressEvent(event)
            return

        index = self.indexAt(event.pos())
        if index.isValid():
            model = self.model()
            if hasattr(model, 'filePath'):
                path = model.filePath(index)
                if Path(path).is_dir():
                    # Handle folder expand/collapse logic
                    # If Ctrl/Shift is held, standard selection behavior applies
                    if not (event.modifiers() & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier)):
                        if self.isExpanded(index):
                            self.collapse(index)
                        else:
                            self.expand(index)
                        QTimer.singleShot(50, self.viewport().update)
                        # We still want to select it
                        self.setCurrentIndex(index)
                        return
                else:
                    # It's a file - open it on single click (if no modifiers)
                    if not (event.modifiers() & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier)):
                        path = model.filePath(index)
                        # Open the file in the editor (preview mode)
                        if hasattr(self.parent(), 'file_opened'):
                            self.parent().file_opened.emit(path)
                        elif hasattr(self.parent().parent(), 'file_opened'):
                             self.parent().parent().file_opened.emit(path)
                        # VS Code behavior: keep focus on the tree after single-click open.
                        # Since the CodeEditor explicitly tries to steal focus when opened,
                        # we must assertively steal it back.
                        self.setFocus()
                        QTimer.singleShot(10, self.setFocus)
                        QTimer.singleShot(100, self.setFocus)
                        QTimer.singleShot(250, self.setFocus)
        super().mousePressEvent(event)


# ── Main File Explorer Panel ───────────────────────────────────────────────────
class FileExplorerPanel(QWidget):
    """VS Code-style file explorer panel."""
    file_opened  = pyqtSignal(str)
    file_created = pyqtSignal(str)
    file_deleted = pyqtSignal(str)
    file_renamed = pyqtSignal(str, str)

    def __init__(self, file_manager=None, parent=None):
        super().__init__(parent)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._file_manager = file_manager
        self._root_path: str | None = None
        self._is_dark = True
        self._tree_collapsed = False

        # Internal clipboard state
        self._clipboard_paths = []
        self._clipboard_mode = "copy"  # "copy" or "cut"
        self._explorer_active = False  # VS Code-style context key: True when tree was last clicked

        # ── VS Code-style focus-aware shortcuts ────────────────────────────
        # Instead of QShortcuts (which either don't fire or conflict with
        # the editor's Ctrl+C), we install an application-level event filter.
        # It intercepts KeyPress events and checks if the file tree has focus
        # (equivalent to VS Code's `when: explorerViewletFocus && !inputFocus`).
        # If yes → handle file copy/cut/paste.  If no → pass event through.
        QApplication.instance().installEventFilter(self)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # ── Section header ─────────────────────────────────────────────────
        self._header = QWidget()
        self._header.setFixedHeight(30)
        hlay = QHBoxLayout(self._header)
        hlay.setContentsMargins(10, 0, 6, 0)

        self._section_title = QLabel("EXPLORER")
        self._section_title.setStyleSheet(
            "font-size:10px; font-weight:bold; letter-spacing:1.2px; color:#858585;"
        )
        hlay.addWidget(self._section_title)
        hlay.addStretch()

        collapse_btn = QPushButton()
        collapse_btn.setIcon(make_button_icon("collapse-all", self._is_dark, 18))
        collapse_btn.setFixedSize(24, 24)
        collapse_btn.setToolTip("Collapse All")
        collapse_btn.setStyleSheet("QPushButton { border:none; background:transparent; } QPushButton:hover { background: #3e3e42; border-radius:3px; }")
        collapse_btn.clicked.connect(self._collapse_all)
        hlay.addWidget(collapse_btn)
        layout.addWidget(self._header)

        # ── Folder title row (like VS Code's "CORTEX ∨") ─────────────────
        self._folder_row = QWidget()
        self._folder_row.setFixedHeight(26)
        flay = QHBoxLayout(self._folder_row)
        flay.setContentsMargins(6, 0, 4, 0)
        flay.setSpacing(4)

        self._folder_arrow = QLabel("▶")
        self._folder_arrow.setStyleSheet("font-size:9px; color:#cccccc;")
        self._folder_arrow.setFixedWidth(12)
        flay.addWidget(self._folder_arrow)

        self._folder_name = QLabel("NO FOLDER OPENED")
        self._folder_name.setStyleSheet(
            "font-size:11px; font-weight:bold; color:#cccccc; letter-spacing:0.5px;"
        )
        flay.addWidget(self._folder_name)
        flay.addStretch()

        # Action Toolbar
        self._action_toolbar = QWidget()
        athay = QHBoxLayout(self._action_toolbar)
        athay.setContentsMargins(0, 0, 0, 0)
        athay.setSpacing(2)

        # ── Explorer Action Icons (High-quality SVG Lucide/Codicon style) ────
        self._btn_new_file = QPushButton()
        self._btn_new_file.setIcon(make_button_icon("new-file", self._is_dark, 18))
        self._btn_new_file.setFixedSize(26, 26)
        self._btn_new_file.setToolTip("New File")
        self._btn_new_file.clicked.connect(self._new_file)
        
        self._btn_new_folder = QPushButton()
        self._btn_new_folder.setIcon(make_button_icon("new-folder", self._is_dark, 18))
        self._btn_new_folder.setFixedSize(26, 26)
        self._btn_new_folder.setToolTip("New Folder")
        self._btn_new_folder.clicked.connect(self._new_folder)

        self._btn_refresh = QPushButton()
        self._btn_refresh.setIcon(make_button_icon("refresh-explorer", self._is_dark, 18))
        self._btn_refresh.setFixedSize(26, 26)
        self._btn_refresh.setToolTip("Refresh Explorer")
        self._btn_refresh.clicked.connect(self._refresh_explorer)

        for btn in [self._btn_new_file, self._btn_new_folder, self._btn_refresh]:
            btn.setStyleSheet("QPushButton { border:none; background:transparent; } QPushButton:hover { background: #3e3e42; border-radius:3px; }")
            athay.addWidget(btn)

        flay.addWidget(self._action_toolbar)

        # self._folder_row.mousePressEvent = self._toggle_tree # Handled by click on the row but buttons should intercept
        layout.addWidget(self._folder_row)

        # ── File system model ──────────────────────────────────────────────
        self._model = QFileSystemModel()
        self._model.setReadOnly(False)
        self._model.setFilter(
            QDir.Filter.AllEntries | QDir.Filter.NoDotAndDotDot
        )
        # hide common noise dirs
        self._model.setNameFilterDisables(False)

        # ── Tree view ──────────────────────────────────────────────────────
        self._tree = VsCodeFileTree(file_manager=self._file_manager, explorer=self, parent=self)
        self._tree.setModel(self._model)
        self._tree.setHeaderHidden(True)
        for col in (1, 2, 3):
            self._tree.setColumnHidden(col, True)
        self._tree.setAnimated(True)
        self._tree.setIndentation(14)
        self._tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._tree.customContextMenuRequested.connect(self._show_context_menu)
        self._tree.doubleClicked.connect(self._on_double_click)
        # Repaint after expand/collapse so open-folder icon updates
        self._tree.expanded.connect(self._on_expanded)
        self._tree.collapsed.connect(self._on_collapsed)
        # Repaint when async directory listing finishes loading
        self._model.directoryLoaded.connect(lambda _: self._tree.viewport().update())
        # Connect file deletion signal
        self._tree.file_deleted.connect(self.file_deleted)

        # Custom delegate
        self._delegate = FileTreeDelegate(self._model)
        self._tree.setItemDelegate(self._delegate)
        self._tree.setStyleSheet(TREE_QSS_DARK)
        # Disable inline rename — double-click should only open the file
        from PyQt6.QtWidgets import QAbstractItemView
        self._tree.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)

        layout.addWidget(self._tree)
        self._tree_visible = True

    # ── Public ────────────────────────────────────────────────────────────────
    def set_project(self, folder_path: str):
        # Normalize path (convert to absolute, fix slashes)
        normalized_path = os.path.normpath(os.path.abspath(folder_path))
        log.info(f"📁 Setting project root: {normalized_path}")
        
        self._root_path = normalized_path
        name = Path(normalized_path).name.upper()
        self._folder_name.setText(name)
        self._folder_arrow.setText("▼")
        self._tree_collapsed = False
        
        # Set model root and tree root index
        idx = self._model.setRootPath(normalized_path)
        log.info(f"   ✓ Model root index: {idx.row()}, {idx.column()}")
        log.info(f"   ✓ Model root path: {self._model.filePath(idx)}")
        
        self._tree.setRootIndex(idx)
        self._tree.setVisible(True)
        log.info(f"   ✓ Tree root set successfully")
        # NO auto-expand — user expands manually; call restore_expanded_paths() after

    def get_expanded_paths(self) -> list[str]:
        """Return list of currently expanded folder paths (for session save)."""
        expanded = []
        root_idx = self._tree.rootIndex()
        def _walk(parent_idx):
            for row in range(self._model.rowCount(parent_idx)):
                idx = self._model.index(row, 0, parent_idx)
                if self._tree.isExpanded(idx):
                    path = self._model.filePath(idx)
                    expanded.append(path)
                    _walk(idx)
        _walk(root_idx)
        return expanded

    def restore_expanded_paths(self, paths: list[str]):
        """Expand the given folder paths (called after model finishes loading)."""
        if not paths:
            return
        from PyQt6.QtCore import QTimer

        def _do_restore():
            path_set = set(paths)
            root_idx = self._tree.rootIndex()
            def _walk(parent_idx):
                for row in range(self._model.rowCount(parent_idx)):
                    idx = self._model.index(row, 0, parent_idx)
                    fp = self._model.filePath(idx)
                    if fp in path_set:
                        self._tree.expand(idx)
                        _walk(idx)
            _walk(root_idx)
            self._tree.viewport().update()

        # Give the model time to populate (async directory listing)
        QTimer.singleShot(400, _do_restore)

    def is_tree_focused(self) -> bool:
        return self._tree.hasFocus()

    def rename_selected(self) -> bool:
        index = self._tree.currentIndex()
        if not index.isValid():
            return False

        path = self._model.filePath(index)
        if not path:
            return False

        if self._root_path:
            try:
                if Path(path).resolve() == Path(self._root_path).resolve():
                    return False
            except Exception:
                return False

        return self._rename_path(path)

    def _rename_path(self, path: str) -> bool:
        try:
            name, ok = QInputDialog.getText(self, "Rename", "New name:", text=Path(path).name)
            if not ok or not name or name == Path(path).name:
                return False

            new_path_obj = Path(path).parent / name
            
            # Prevent WinError 183 by explicitly checking for existence
            if new_path_obj.exists() and new_path_obj.resolve() != Path(path).resolve():
                QMessageBox.warning(
                    self, 
                    "Rename Failed", 
                    f"A file or folder with the name '{name}' already exists at this location.\n\nPlease choose a different name."
                )
                return False

            new_path = str(new_path_obj)
            Path(path).rename(new_path)
            self.file_renamed.emit(path, new_path)
            return True
        except Exception as e:
            QMessageBox.critical(self, "Rename Failed", f"Could not rename: {e}")
            return False

    def set_theme(self, is_dark: bool):
        self._is_dark = is_dark
        self._delegate.set_dark(is_dark)
        self._tree.setStyleSheet(TREE_QSS_DARK if is_dark else TREE_QSS_LIGHT)
        # header/folder row colours
        fg = "#cccccc" if is_dark else "#1a1a1a"
        bg = "#1e1e1e" if is_dark else "#f3f3f3"
        self._header.setStyleSheet(f"background:{bg};")
        self._folder_row.setStyleSheet(
            f"background:{bg}; border-bottom:1px solid "
            f"{'#3e3e42' if is_dark else '#dcdcdc'};"
        )
        self._folder_name.setStyleSheet(
            f"font-size:11px; font-weight:bold; color:{fg}; letter-spacing:0.5px;"
        )
        self._folder_arrow.setStyleSheet(f"font-size:9px; color:{fg};")
        
        # Update toolbar icons (High-quality SVG Codicon/Lucide style)
        self._btn_new_file.setIcon(make_button_icon("new-file", is_dark, 18))
        self._btn_new_folder.setIcon(make_button_icon("new-folder", is_dark, 18))
        self._btn_refresh.setIcon(make_button_icon("refresh-explorer", is_dark, 18))
        
        btn_qss = f"""
            QPushButton {{ 
                border:none; 
                background:transparent; 
            }} 
            QPushButton:hover {{ 
                background: {"#3e3e42" if is_dark else "#e5e5e5"}; 
                border-radius:3px; 
            }}
        """
        for btn in [self._btn_new_file, self._btn_new_folder, self._btn_refresh]:
            btn.setStyleSheet(btn_qss)

        self._tree.viewport().update()

    # ── Private ───────────────────────────────────────────────────────────────
    def _on_expanded(self, index: QModelIndex):
        from PyQt6.QtCore import QTimer
        QTimer.singleShot(30, self._tree.viewport().update)

    def _on_collapsed(self, index: QModelIndex):
        from PyQt6.QtCore import QTimer
        QTimer.singleShot(30, self._tree.viewport().update)

    def _is_explorer_focused(self) -> bool:
        focused = QApplication.focusWidget()
        if not focused:
            return False
        w = focused
        while w is not None:
            if w is self._tree:
                return True
            w = w.parent() if hasattr(w, 'parent') and callable(w.parent) else None
        return False

    def eventFilter(self, obj, event):
        """Application-level event filter.
        Handles Ctrl+C/X/V only when the file tree HAS FOCUS.
        """
        from PyQt6.QtCore import QEvent
        from PyQt6.QtGui import QKeySequence
        
        # On Windows, standard keys like Ctrl+C might arrive as ShortcutOverride
        if event.type() in (QEvent.Type.KeyPress, QEvent.Type.ShortcutOverride):
            if self._is_explorer_focused():
                mods = event.modifiers()
                key = event.key()
                if mods & Qt.KeyboardModifier.ControlModifier:
                    if key == Qt.Key.Key_C:
                        self._kb_copy()
                        return True
                    elif key == Qt.Key.Key_X:
                        self._kb_cut()
                        return True
                    elif key == Qt.Key.Key_V:
                        self._kb_paste()
                        return True
        return super().eventFilter(obj, event)


    def _set_system_clipboard(self, paths: list[str], mode: str):
        """Update the OS clipboard so Ctrl+V works everywhere."""
        from PyQt6.QtCore import QMimeData, QUrl
        mime = QMimeData()
        urls = [QUrl.fromLocalFile(p) for p in paths]
        mime.setUrls(urls)
        # Set text representation so pasting into editor gives file path
        mime.setText("\n".join(str(Path(p).resolve()) for p in paths))
        # Optional: could set custom mime type for 'cut' vs 'copy'
        QApplication.clipboard().setMimeData(mime)

    def _kb_copy(self):
        """Ctrl+C — copy selected files (panel-level, always fires)."""
        paths = self._tree._get_selected_paths()
        print(f"[KB COPY] paths={paths}")
        if paths:
            self._clipboard_paths = paths
            self._clipboard_mode = "copy"
            self._set_system_clipboard(paths, "copy")
            log.info(f"📋 Copied: {', '.join(Path(p).name for p in paths)}")

    def _kb_cut(self):
        """Ctrl+X — cut selected files."""
        paths = self._tree._get_selected_paths()
        print(f"[KB CUT] paths={paths}")
        if paths:
            self._clipboard_paths = paths
            self._clipboard_mode = "cut"
            self._set_system_clipboard(paths, "cut")
            log.info(f"✂️ Cut: {', '.join(Path(p).name for p in paths)}")

    def _kb_paste(self):
        """Ctrl+V — paste into currently selected/focused folder."""
        print(f"[KB PASTE] start")
        idx = self._tree.currentIndex()
        if idx.isValid():
            p = self._model.filePath(idx)
            target = p if Path(p).is_dir() else str(Path(p).parent)
        else:
            target = self._root_path
        print(f"[KB PASTE] target={target}")
        if target:
            self._paste_into(target)

    def _paste_into(self, target_dir: str):
        """Execute the actual file copy/move operations from clipboard."""
        if not self._file_manager:
            return

        from PyQt6.QtWidgets import QMessageBox
        
        # 1. Check internal clipboard first
        paths = self._clipboard_paths
        mode = self._clipboard_mode
        
        # 2. Check system clipboard if internal is empty
        if not paths:
            mime = QApplication.clipboard().mimeData()
            if mime.hasUrls():
                paths = [url.toLocalFile() for url in mime.urls() if url.isLocalFile()]
                mode = "copy"  # external pastes are always treated as copies by default
                
        if not paths:
            return

        # Confirm paste/move operation
        item_count = len(paths)
        if item_count == 0:
            return
            
        item_desc = f"'{Path(paths[0]).name}'" if item_count == 1 else f"these {item_count} items"
        verb = "move" if mode == "cut" else "copy"
        target_name = Path(target_dir).name
        
        msg = f"Are you sure you want to {verb} {item_desc} into '{target_name}'?\n\nThis action can be undone with Ctrl+Z."
        reply = QMessageBox.question(
            self, f'Confirm {verb.capitalize()}', msg,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes
        )
        
        if reply != QMessageBox.StandardButton.Yes:
            return

        success_count = 0
        for src in paths:
            if mode == "cut":
                res = self._file_manager.move(src, target_dir)
            else:
                res = self._file_manager.copy(src, target_dir)
            
            if res:
                success_count += 1

        # If it was an internal 'cut', clear clipboard after moving
        if self._clipboard_mode == "cut" and self._clipboard_paths:
            self._clipboard_paths = []
            self._clipboard_mode = "copy"

        log.info(f"Pasted {success_count} items into {target_dir}")
        self._tree.viewport().update()

    def _toggle_tree(self, _event=None):
        """Collapse/expand all items in tree (like VS Code's root arrow)."""
        if self._tree_collapsed:
            # Restore to expanded state
            self._tree.expandToDepth(0)  # expand first level only
            self._folder_arrow.setText("▼")
            self._tree_collapsed = False
        else:
            self._tree.collapseAll()
            self._folder_arrow.setText("▶")
            self._tree_collapsed = True

    def _collapse_all(self):
        self._tree.collapseAll()
        self._folder_arrow.setText("▶")
        self._tree_collapsed = True

    def _new_file(self):
        """Create a new file in the currently selected directory or root."""
        from PyQt6.QtWidgets import QInputDialog
        target_dir = self._get_selected_dir()
        if not target_dir:
            return
            
        name, ok = QInputDialog.getText(self, "New File", "File name:")
        if ok and name:
            new_path = Path(target_dir) / name
            try:
                new_path.touch()
                self._refresh_explorer()
                self.file_created.emit(str(new_path))
            except Exception as e:
                from PyQt6.QtWidgets import QMessageBox
                QMessageBox.warning(self, "Error", f"Could not create file: {e}")

    def _new_folder(self):
        """Create a new folder in the currently selected directory or root."""
        from PyQt6.QtWidgets import QInputDialog
        target_dir = self._get_selected_dir()
        if not target_dir:
            return
            
        name, ok = QInputDialog.getText(self, "New Folder", "Folder name:")
        if ok and name:
            new_path = Path(target_dir) / name
            try:
                new_path.mkdir(parents=True, exist_ok=True)
                self._refresh_explorer()
            except Exception as e:
                from PyQt6.QtWidgets import QMessageBox
                QMessageBox.warning(self, "Error", f"Could not create folder: {e}")

    def _refresh_explorer(self):
        """Force a refresh of the file system model."""
        if self._root_path:
            # QFileSystemModel monitors automatically, but we can force it
            self._model.setRootPath("")
            self._model.setRootPath(self._root_path)
            self._tree.viewport().update()

    def _get_selected_dir(self) -> str | None:
        """Helper to find target directory for new items."""
        index = self._tree.currentIndex()
        if index.isValid():
            path = self._model.filePath(index)
            if Path(path).is_dir():
                return path
            else:
                return str(Path(path).parent)
        return self._root_path

    def _on_double_click(self, index: QModelIndex):
        path = self._model.filePath(index)
        if Path(path).is_file():
            self.file_opened.emit(path)

    def _show_context_menu(self, pos):
        indexes = self._tree.selectedIndexes()
        # Filter for column 0 only
        selected_paths = [self._model.filePath(idx) for idx in indexes if idx.column() == 0]
        
        # Target for Paste is either the folder clicked on, or its parent folder if a file was clicked
        click_index = self._tree.indexAt(pos)
        target_path = self._model.filePath(click_index) if click_index.isValid() else self._root_path
        
        if not target_path:
            return

        menu = QMenu(self)
        menu.setStyleSheet(f"""
            QMenu {{ background-color: {'#252526' if self._is_dark else '#ffffff'}; color: {'#cccccc' if self._is_dark else '#333333'}; border: 1px solid #3c3c3c; }}
            QMenu::item:selected {{ background-color: #094771; color: white; }}
        """)
        
        is_dir = Path(target_path).is_dir()
        
        if is_dir:
            act_new_file   = menu.addAction("📄  New File")
            act_new_folder = menu.addAction("📁  New Folder")
            menu.addSeparator()

        if selected_paths:
            act_cut = menu.addAction("✂️  Cut")
            act_copy = menu.addAction("📋  Copy")
            menu.addSeparator()
            
        # Paste logic: Check internal or system clipboard
        can_paste = bool(self._clipboard_paths)
        if not can_paste:
            clipboard = QApplication.clipboard()
            mime = clipboard.mimeData()
            if mime.hasUrls():
                can_paste = True
                
        if can_paste:
            act_paste = menu.addAction("📥  Paste")
            menu.addSeparator()

        act_rename = menu.addAction("✏️  Rename")
        act_delete = menu.addAction("🗑️  Delete")
        menu.addSeparator()
        act_copy_path = menu.addAction("🔗  Copy Path")

        action = menu.exec(self._tree.viewport().mapToGlobal(pos))
        if not action:
            return

        txt = action.text().strip()

        if is_dir and "New File" in txt:
            self._new_file_at(target_path)
        elif is_dir and "New Folder" in txt:
            self._new_folder_at(target_path)
        elif "Cut" in txt:
            paths = selected_paths if selected_paths else [target_path]
            self._clipboard_paths = paths
            self._clipboard_mode = "cut"
            self._set_system_clipboard(paths, "cut")
            print(f"[CUT] stored: {self._clipboard_paths}")
        elif "Copy" in txt:
            paths = selected_paths if selected_paths else [target_path]
            self._clipboard_paths = paths
            self._clipboard_mode = "copy"
            self._set_system_clipboard(paths, "copy")
            print(f"[COPY] stored: {self._clipboard_paths}")
        elif "Paste" in txt:
            dest_dir = target_path if is_dir else str(Path(target_path).parent)
            print(f"[PASTE] into: {dest_dir}, clipboard: {self._clipboard_paths}")
            self._paste_into(dest_dir)
        elif "Rename" in txt:
            self._rename_path(target_path)
        elif "Delete" in txt:
            self._tree._delete_items(selected_paths if selected_paths else [target_path])
        elif "Copy Path" in txt:
            QApplication.clipboard().setText(target_path)

    def _new_file_at(self, directory):
        name, ok = QInputDialog.getText(self, "New File", "File name:")
        if ok and name:
            new_path = str(Path(directory) / name)
            try:
                Path(new_path).touch()
                self.file_created.emit(new_path)
            except Exception as e:
                QMessageBox.warning(self, "Error", f"Could not create file: {e}")

    def _new_folder_at(self, directory):
        name, ok = QInputDialog.getText(self, "New Folder", "Folder name:")
        if ok and name:
            try:
                (Path(directory) / name).mkdir(exist_ok=True)
            except Exception as e:
                QMessageBox.warning(self, "Error", f"Could not create folder: {e}")

    def _handle_paste(self, dest_dir):
        """Handle pasting from internal or external clipboard."""
        import shutil
        
        # 1. Check system clipboard first (files from Explorer)
        clipboard = QApplication.clipboard()
        mime = clipboard.mimeData()
        if mime.hasUrls():
            for url in mime.urls():
                src_path = url.toLocalFile()
                if src_path:
                    try:
                        self._copy_item(src_path, dest_dir)
                    except Exception as e:
                        log.error(f"Failed to paste external file {src_path}: {e}")
            return

        # 2. Internal clipboard
        if not self._clipboard_paths:
            return

        for src_path in self._clipboard_paths:
            try:
                if self._clipboard_mode == "cut":
                    shutil.move(src_path, dest_dir)
                else:
                    self._copy_item(src_path, dest_dir)
            except Exception as e:
                log.error(f"Failed to paste {src_path}: {e}")
                
        if self._clipboard_mode == "cut":
            self._clipboard_paths = []
            
        self._refresh_explorer()

    def _copy_item(self, src_path, dest_dir):
        """Helper to copy file or folder to destination."""
        import shutil
        src = Path(src_path)
        dest = Path(dest_dir) / src.name
        
        # Handle filename collisions (e.g. file.txt -> file (copy).txt)
        if dest.exists():
            stem = src.stem
            ext = src.suffix
            counter = 1
            while dest.exists():
                dest = Path(dest_dir) / f"{stem} (copy {counter}){ext}"
                counter += 1
                
        if src.is_dir():
            shutil.copytree(str(src), str(dest))
        else:
            shutil.copy2(str(src), str(dest))



class SearchPanel(QWidget):
    file_opened = pyqtSignal(str, int)  # path, line number

    def __init__(self, parent=None):
        super().__init__(parent)
        self._root = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        self._header = QLabel("SEARCH")
        layout.addWidget(self._header)

        self._search_input = QLineEdit()
        self._search_input.setPlaceholderText("Search in files...")
        self._search_input.returnPressed.connect(self._do_search)
        layout.addWidget(self._search_input)

        self._results = QListWidget()
        self._results.itemDoubleClicked.connect(self._open_result)
        layout.addWidget(self._results)

        self._status = QLabel("")
        layout.addWidget(self._status)
        self.set_theme(True)

    def set_theme(self, is_dark: bool):
        color = "#858585" if is_dark else "#666666"
        self._header.setStyleSheet(f"font-size:10px; font-weight:bold; color:{color}; letter-spacing:1px;")
        self._status.setStyleSheet(f"font-size:11px; color:{color};")

    def set_root(self, root: str):
        self._root = root

    def _do_search(self):
        query = self._search_input.text().strip()
        if not query or not self._root:
            return
        self._results.clear()
        found = 0
        for dirpath, _, files in os.walk(self._root):
            if any(skip in dirpath for skip in ['.git', '__pycache__', 'node_modules', 'venv', '.venv']):
                continue
            for fname in files:
                fpath = os.path.join(dirpath, fname)
                try:
                    with open(fpath, 'r', encoding='utf-8', errors='ignore') as f:
                        for lineno, line in enumerate(f, 1):
                            if query.lower() in line.lower():
                                rel = os.path.relpath(fpath, self._root)
                                item = QListWidgetItem(f"{rel}:{lineno}  {line.strip()[:60]}")
                                item.setData(Qt.ItemDataRole.UserRole, (fpath, lineno))
                                self._results.addItem(item)
                                found += 1
                                if found >= 200:
                                    break
                except Exception:
                    pass
                if found >= 200:
                    break
        self._status.setText(f"{found} result(s)" + (" (limited)" if found >= 200 else ""))

    def _open_result(self, item: QListWidgetItem):
        data = item.data(Qt.ItemDataRole.UserRole)
        if data:
            self.file_opened.emit(data[0], data[1])


class GitPanel(QWidget):
    """Full-featured Source Control panel — VS Code standard.
    Wraps GitPanelWidget from git_ui.py with GitManager for complete
    git integration: staging, commits, diffs, branches, push/pull.
    """
    file_opened = pyqtSignal(str)

    def __init__(self, git_manager=None, parent=None):
        super().__init__(parent)
        self._is_dark = True
        self._git_manager = git_manager
        self._git_widget = None
        self._no_repo_label = None
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        if self._git_manager:
            # Full-featured GitPanelWidget from git_ui.py
            from src.ui.components.git_ui import GitPanelWidget
            self._git_widget = GitPanelWidget(self._git_manager, self)
            layout.addWidget(self._git_widget)
        else:
            # Fallback placeholder when no GitManager provided
            self._no_repo_label = QLabel("No repository detected")
            self._no_repo_label.setWordWrap(True)
            self._no_repo_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._no_repo_label.setStyleSheet("font-size:12px; color:#858585; padding: 20px;")
            layout.addWidget(self._no_repo_label)

    def set_git_manager(self, git_manager):
        """Set or replace the GitManager (called when project opens)."""
        self._git_manager = git_manager
        # Rebuild UI with the real widget
        if self._git_widget is None and git_manager is not None:
            # Remove placeholder
            if self._no_repo_label:
                self._no_repo_label.setParent(None)
                self._no_repo_label.deleteLater()
                self._no_repo_label = None
            from src.ui.components.git_ui import GitPanelWidget
            self._git_widget = GitPanelWidget(git_manager, self)
            self.layout().addWidget(self._git_widget)
            self._git_widget.set_theme(self._is_dark)
        elif self._git_widget is not None:
            self._git_widget.git = git_manager

    def refresh(self):
        """Refresh git status display."""
        if self._git_widget:
            self._git_widget.refresh()

    def set_repository(self, path: str) -> bool:
        """Set repository path and refresh."""
        if self._git_manager:
            result = self._git_manager.set_repository(path)
            if result:
                self.refresh()
            return result
        return False

    def set_theme(self, is_dark: bool):
        self._is_dark = is_dark
        if self._git_widget:
            self._git_widget.set_theme(is_dark)
        if self._no_repo_label:
            color = "#858585" if is_dark else "#666666"
            self._no_repo_label.setStyleSheet(f"font-size:12px; color:{color}; padding: 20px;")

    def set_repo_info(self, branch: str = "", changes: list = None):
        """Legacy API compat — refresh handles this now."""
        self.refresh()


class AIToolsPanel(QWidget):
    """AI quick-action panel in the sidebar."""
    action_requested = pyqtSignal(str)  # action name

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        self._header = QLabel("AI TOOLS")
        layout.addWidget(self._header)

        layout.addWidget(self._make_separator())

        self.set_theme(True)

        layout.addWidget(self._make_separator())

        actions = [
            ("💡 Explain Code", "explain"),
            ("🔧 Refactor", "refactor"),
            ("🧪 Write Tests", "tests"),
            ("🐛 Debug Help", "debug"),
            ("📝 Add Docstrings", "docstring"),
        ]
        for label, action in actions:
            btn = QPushButton(label)
            btn.clicked.connect(lambda checked, a=action: self.action_requested.emit(a))
            btn.setStyleSheet("text-align: left; padding: 6px 10px;")
            layout.addWidget(btn)

        layout.addStretch()

    def set_theme(self, is_dark: bool):
        color = "#858585" if is_dark else "#666666"
        self._header.setStyleSheet(f"font-size:10px; font-weight:bold; color:{color}; letter-spacing:1px;")

    def get_model(self) -> str:
        from src.config.settings import get_settings
        return get_settings().get("ai", "model") or "gpt-4o-mini"

    def get_provider(self) -> str:
        from src.config.settings import get_settings
        return get_settings().get("ai", "provider") or "openai"

    def _make_separator(self) -> QFrame:
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        return line

    def get_temperature(self) -> float:
        from src.config.settings import get_settings
        return float(get_settings().get("ai", "temperature") or 0.7)


class ChangedFilesPanel(QWidget):
    """Panel showing AI-edited files with Accept/Reject buttons."""
    file_accepted = pyqtSignal(str)  # file_path
    file_rejected = pyqtSignal(str)  # file_path
    file_opened = pyqtSignal(str)    # file_path
    diff_requested = pyqtSignal(str) # file_path
    accept_all_requested = pyqtSignal()
    reject_all_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._files = {}  # path -> widget
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        # Header with count and bulk actions
        header_layout = QHBoxLayout()
        
        # Icon + "Changed Files" label with count
        header_left = QWidget()
        header_left_layout = QHBoxLayout(header_left)
        header_left_layout.setContentsMargins(0, 0, 0, 0)
        header_left_layout.setSpacing(4)
        
        folder_icon = QLabel("📁")
        folder_icon.setStyleSheet("font-size: 12px;")
        header_left_layout.addWidget(folder_icon)
        
        self._header = QLabel("Changed Files")
        self._header.setStyleSheet("font-size: 12px; font-weight: 500;")
        header_left_layout.addWidget(self._header)
        
        self._count_label = QLabel("(0)")
        self._count_label.setStyleSheet("font-size: 11px; color: #888;")
        header_left_layout.addWidget(self._count_label)
        
        header_layout.addWidget(header_left)
        header_layout.addStretch()
        
        # Bulk action buttons (hidden when no files)
        self._bulk_widget = QWidget()
        bulk_layout = QHBoxLayout(self._bulk_widget)
        bulk_layout.setContentsMargins(0, 0, 0, 0)
        bulk_layout.setSpacing(6)
        
        self._reject_all_btn = QPushButton("Reject")
        self._reject_all_btn.setStyleSheet("""
            QPushButton {
                padding: 4px 12px; 
                font-size: 11px;
                background: transparent;
                border: 1px solid #555;
                border-radius: 4px;
                color: #ccc;
            }
            QPushButton:hover {
                background: #450a0a;
                border-color: #7f1d1d;
                color: #f87171;
            }
        """)
        self._reject_all_btn.clicked.connect(self.reject_all_requested.emit)
        
        self._accept_all_btn = QPushButton("Accept")
        self._accept_all_btn.setStyleSheet("""
            QPushButton {
                padding: 4px 12px; 
                font-size: 11px;
                background: #14532d;
                border: 1px solid #166534;
                border-radius: 4px;
                color: #4ade80;
            }
            QPushButton:hover {
                background: #16a34a;
                color: #fff;
            }
        """)
        self._accept_all_btn.clicked.connect(self.accept_all_requested.emit)
        
        bulk_layout.addWidget(self._reject_all_btn)
        bulk_layout.addWidget(self._accept_all_btn)
        header_layout.addWidget(self._bulk_widget)
        
        layout.addLayout(header_layout)
        layout.addWidget(self._make_separator())

        # Files list
        self._files_list = QListWidget()
        self._files_list.setFrameShape(QFrame.Shape.NoFrame)
        layout.addWidget(self._files_list)
        
        self._update_bulk_buttons()
        self.set_theme(True)

    def add_file(self, file_path: str, edit_type: str = "M"):
        """Add a file to the changed files list."""
        if file_path in self._files:
            return
        
        from pathlib import Path
        file_name = Path(file_path).name
        
        # Create custom widget for the file row
        row_widget = QWidget()
        row_layout = QHBoxLayout(row_widget)
        row_layout.setContentsMargins(4, 4, 4, 4)
        row_layout.setSpacing(6)
        
        # File icon/label
        file_label = QLabel(f"📄 {file_name}")
        file_label.setStyleSheet("font-size: 12px;")
        file_label.setCursor(Qt.CursorShape.PointingHandCursor)
        file_label.mousePressEvent = lambda e: self.file_opened.emit(file_path)
        row_layout.addWidget(file_label)
        row_layout.addStretch()
        
        # Edit type badge
        badge = QLabel(edit_type)
        badge.setStyleSheet(f"""
            font-size: 9px; 
            padding: 1px 4px; 
            border-radius: 2px;
            background: {'#22c55e' if edit_type == 'C' else '#3b82f6' if edit_type == 'M' else '#ef4444'};
            color: white;
        """)
        row_layout.addWidget(badge)
        
        # Buttons container widget
        buttons_widget = QWidget()
        buttons_layout = QHBoxLayout(buttons_widget)
        buttons_layout.setContentsMargins(0, 0, 0, 0)
        buttons_layout.setSpacing(4)
        
        # Accept/Reject buttons
        accept_btn = QPushButton("✓")
        accept_btn.setStyleSheet("padding: 2px 6px; font-size: 11px; color: #22c55e; border: 1px solid #22c55e; border-radius: 3px; background: transparent;")
        accept_btn.setToolTip("Accept changes")
        accept_btn.setFixedSize(24, 24)
        accept_btn.clicked.connect(lambda: self._on_accept_clicked(file_path, buttons_widget))
        
        reject_btn = QPushButton("✗")
        reject_btn.setStyleSheet("padding: 2px 6px; font-size: 11px; color: #ef4444; border: 1px solid #ef4444; border-radius: 3px; background: transparent;")
        reject_btn.setToolTip("Reject changes")
        reject_btn.setFixedSize(24, 24)
        reject_btn.clicked.connect(lambda: self._on_reject_clicked(file_path, buttons_widget))
        
        buttons_layout.addWidget(accept_btn)
        buttons_layout.addWidget(reject_btn)
        row_layout.addWidget(buttons_widget)
        
        # Add to list
        item = QListWidgetItem()
        item.setData(Qt.ItemDataRole.UserRole, file_path)
        self._files_list.addItem(item)
        self._files_list.setItemWidget(item, row_widget)
        
        self._files[file_path] = item
        self._update_bulk_buttons()
        self._update_header()

    def _on_accept_clicked(self, file_path: str, buttons_widget: QWidget):
        """Handle accept button click - replace buttons with checkmark."""
        # Clear the buttons layout
        layout = buttons_widget.layout()
        while layout.count():
            child = layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()
        
        # Add checkmark label
        check_label = QLabel("✓")
        check_label.setStyleSheet("color: #22c55e; font-size: 14px; font-weight: bold;")
        layout.addWidget(check_label)
        
        # Emit signal
        self.file_accepted.emit(file_path)
        
        # Remove file after short delay
        from PyQt6.QtCore import QTimer
        QTimer.singleShot(500, lambda: self.remove_file(file_path))

    def _on_reject_clicked(self, file_path: str, buttons_widget: QWidget):
        """Handle reject button click - replace buttons with X."""
        # Clear the buttons layout
        layout = buttons_widget.layout()
        while layout.count():
            child = layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()
        
        # Add X label
        x_label = QLabel("✗")
        x_label.setStyleSheet("color: #ef4444; font-size: 14px; font-weight: bold;")
        layout.addWidget(x_label)
        
        # Emit signal
        self.file_rejected.emit(file_path)
        
        # Remove file after short delay
        from PyQt6.QtCore import QTimer
        QTimer.singleShot(500, lambda: self.remove_file(file_path))

    def remove_file(self, file_path: str):
        """Remove a file from the list."""
        if file_path in self._files:
            item = self._files.pop(file_path)
            row = self._files_list.row(item)
            self._files_list.takeItem(row)
            self._update_bulk_buttons()
            self._update_header()

    def clear_files(self):
        """Clear all files from the list."""
        self._files.clear()
        self._files_list.clear()
        self._update_bulk_buttons()
        self._update_header()

    def _update_bulk_buttons(self):
        """Show/hide bulk action buttons based on file count."""
        has_files = len(self._files) > 0
        self._bulk_widget.setVisible(has_files)

    def _update_header(self):
        """Update header with file count."""
        count = len(self._files)
        if self._count_label:
            self._count_label.setText(f"({count})")

    def set_theme(self, is_dark: bool):
        color = "#858585" if is_dark else "#666666"
        self._header.setStyleSheet(f"font-size:10px; font-weight:bold; color:{color}; letter-spacing:1px;")

    def _make_separator(self) -> QFrame:
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        return line


class SidebarWidget(QWidget):
    """
    Full left sidebar with icon strip + stacked panels.
    """
    file_opened = pyqtSignal(str)
    file_search_opened = pyqtSignal(str, int)
    ai_action_requested = pyqtSignal(str)
    file_renamed = pyqtSignal(str, str)
    file_deleted = pyqtSignal(str)
    
    # Changed files signals
    file_accepted = pyqtSignal(str)
    file_rejected = pyqtSignal(str)
    accept_all_requested = pyqtSignal()
    reject_all_requested = pyqtSignal()
    settings_requested = pyqtSignal()   # ⚙ gear button in icon-strip footer

    def __init__(self, file_manager=None, git_manager=None, parent=None):
        super().__init__(parent)
        self._file_manager = file_manager
        self._git_manager = git_manager
        self._build_ui()

    def _build_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Icon strip (vertical)
        self._icon_strip = QWidget()
        self._icon_strip.setObjectName("icon_strip")
        self._icon_strip.setFixedWidth(56)
        icon_layout = QVBoxLayout(self._icon_strip)
        icon_layout.setContentsMargins(4, 12, 4, 8)
        icon_layout.setSpacing(6)
        icon_layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        self._icon_buttons: list[QPushButton] = []
        # VS Code-style Activity Bar icons (high-quality SVG templates)
        self._panels_info = [
            ("explorer", "Explorer", 0),
            ("search-panel", "Search", 1),
            ("source-control", "Source Control", 2),
            ("ai-panel", "AI Tools", 3),
            ("changed-files-panel", "Changed Files", 4),
        ]
        for icon_name, tooltip, idx in self._panels_info:
            btn = QPushButton()
            btn.setIconSize(QSize(24, 24))
            btn.setToolTip(tooltip)
            btn.setFixedSize(46, 46)
            btn.setCheckable(True)
            btn.clicked.connect(lambda checked, i=idx: self._switch_panel(i))
            icon_layout.addWidget(btn)
            self._icon_buttons.append(btn)

        icon_layout.addStretch()

        # ── Footer: Settings / Memory gear button ──────────────────────
        self._settings_icon_btn = QPushButton()
        self._settings_icon_btn.setIconSize(QSize(22, 22))
        self._settings_icon_btn.setToolTip("Settings / Memory Manager\nCtrl+Shift+M")
        self._settings_icon_btn.setFixedSize(46, 46)
        self._settings_icon_btn.setCheckable(False)
        self._settings_icon_btn.clicked.connect(self.settings_requested.emit)
        icon_layout.addWidget(self._settings_icon_btn)
        icon_layout.setContentsMargins(4, 12, 4, 12)  # extra bottom padding

        layout.addWidget(self._icon_strip)

        # Stacked panels
        self._stack = QStackedWidget()
        self._explorer = FileExplorerPanel(self._file_manager)
        self._search = SearchPanel()
        self._git_panel = GitPanel(git_manager=self._git_manager)
        self._ai_tools = AIToolsPanel()
        self._changed_files = ChangedFilesPanel()

        self._stack.addWidget(self._explorer)       # 0
        self._stack.addWidget(self._search)          # 1
        self._stack.addWidget(self._git_panel)       # 2
        self._stack.addWidget(self._ai_tools)        # 3
        self._stack.addWidget(self._changed_files)   # 4
        layout.addWidget(self._stack)

        # Connect signals
        self._explorer.file_opened.connect(self.file_opened)
        self._explorer.file_renamed.connect(self.file_renamed)
        self._explorer.file_deleted.connect(self.file_deleted)
        self._search.file_opened.connect(self.file_search_opened)
        self._ai_tools.action_requested.connect(self.ai_action_requested)
        
        # Connect changed files panel signals
        self._changed_files.file_opened.connect(self.file_opened)
        self._changed_files.file_accepted.connect(self.file_accepted)
        self._changed_files.file_rejected.connect(self.file_rejected)
        self._changed_files.accept_all_requested.connect(self.accept_all_requested)
        self._changed_files.reject_all_requested.connect(self.reject_all_requested)

        self.set_theme(True)

        # Start on explorer
        self._switch_panel(0)

    def _switch_panel(self, index: int):
        self._stack.setCurrentIndex(index)
        for i, btn in enumerate(self._icon_buttons):
            btn.setChecked(i == index)

    def set_project(self, folder_path: str):
        self._explorer.set_project(folder_path)
        self._search.set_root(folder_path)
        # Initialize git for this project
        self._git_panel.set_repository(folder_path)

    def is_explorer_focused(self) -> bool:
        return self._explorer.is_tree_focused()

    def rename_selected_item(self) -> bool:
        return self._explorer.rename_selected()

    def set_theme(self, is_dark: bool):
        self._explorer.set_theme(is_dark)
        self._search.set_theme(is_dark)
        self._git_panel.set_theme(is_dark)
        self._ai_tools.set_theme(is_dark)
        self._changed_files.set_theme(is_dark)
        
        icon_color = "#cccccc" if is_dark else "#555555"
        hover_bg = "rgba(255,255,255,0.10)" if is_dark else "rgba(0,0,0,0.06)"
        checked_bg = "rgba(0,122,204,0.30)" if is_dark else "rgba(0,122,204,0.15)"
        
        btn_style = f"""
            QPushButton {{
                border-radius: 8px;
                background: transparent;
                border: none;
                padding: 2px;
            }}
            QPushButton:hover {{
                background: {hover_bg};
            }}
            QPushButton:checked {{
                background: {checked_bg};
                border-left: 3px solid #007acc;
            }}
        """
        for i, btn in enumerate(self._icon_buttons):
            icon_name = self._panels_info[i][0]
            btn.setIcon(make_icon(icon_name, icon_color, 24))
            btn.setStyleSheet(btn_style)

        # Style the gear / settings button in footer
        if hasattr(self, '_settings_icon_btn'):
            self._settings_icon_btn.setIcon(make_icon("settings", icon_color, 22))
            self._settings_icon_btn.setStyleSheet(f"""
                QPushButton {{
                    border-radius: 8px;
                    background: transparent;
                    border: none;
                    padding: 2px;
                }}
                QPushButton:hover {{
                    background: {hover_bg};
                }}
                QPushButton:pressed {{
                    background: rgba(0,122,204,0.35);
                }}
            """)

    def get_expanded_paths(self) -> list[str]:
        return self._explorer.get_expanded_paths()

    def restore_expanded_paths(self, paths: list[str]):
        self._explorer.restore_expanded_paths(paths)

    def refresh(self):
        """Refresh the file explorer and git panel to reflect changes."""
        if hasattr(self._explorer, '_refresh_explorer'):
            self._explorer._refresh_explorer()
        self._git_panel.refresh()


    def get_ai_model(self) -> str:
        return self._ai_tools.get_model()

    def get_ai_provider(self) -> str:
        return self._ai_tools.get_provider()

    def get_ai_temperature(self) -> float:
        return self._ai_tools.get_temperature()

    def add_changed_file(self, file_path: str, edit_type: str = "M"):
        """Add a file to the changed files panel."""
        self._changed_files.add_file(file_path, edit_type)

    def remove_changed_file(self, file_path: str):
        """Remove a file from the changed files panel."""
        self._changed_files.remove_file(file_path)

    def clear_changed_files(self):
        """Clear all files from the changed files panel."""
        self._changed_files.clear_files()

    def show_changed_files_panel(self):
        """Switch to the changed files panel."""
        self._switch_panel(4)
