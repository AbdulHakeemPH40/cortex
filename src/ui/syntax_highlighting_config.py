"""
Comprehensive Syntax Highlighting Configuration for main_window.py
Applies Dracula Theme to 100+ programming languages & all frameworks
Python, JavaScript, TypeScript, Java, C++, C, CSS, HTML, React, Vue, Angular, Django, Flask, etc.
EXACT COLORS from ai_chat.html - No white text for unsupported languages
"""
import re

# ==================== DRACULA COLOR PALETTE ====================
# Exact same colors as ai_chat.html hljs-fallback-styles
DRACULA_COLORS = {
    # Background
    'bg': '#282a36',
    'bg_light': '#44475a',
    'bg_current': '#44475a',
    
    # Text
    'text': '#f8f8f2',
    'text_faded': '#6272a4',
    
    # Syntax Elements (EXACT ai_chat.html colors)
    'keyword': '#bd93f9',       # Purple - def, class, if, etc.
    'string': '#50fa7b',        # Green - strings, text
    'number': '#bd93f9',        # Purple - numbers, literals
    'comment': '#6272a4',       # Blue-gray - comments
    'function': '#ffb86c',      # Orange - function names
    'tag': '#ff79c6',           # Pink - tags, attributes  
    'variable': '#ff5555',      # Red - variables, deletion
    'class': '#8be9fd',         # Cyan - class names
    'const': '#f1fa8c',         # Yellow - constants
    'import': '#ff79c6',        # Pink - imports, exports
    'builtin': '#8be9fd',       # Cyan - built-in functions
}

# ==================== 100+ PROGRAMMING LANGUAGES & FRAMEWORKS ====================
LANGUAGE_KEYWORDS = {
    # ===== WEB LANGUAGES =====
    'python': ['def', 'class', 'import', 'from', 'if', 'elif', 'else', 'for', 'while', 'return', 'try', 'except', 'finally', 'with', 'as', 'lambda', 'yield', 'async', 'await', 'pass', 'break', 'continue', 'raise', 'assert', 'del', 'global', 'nonlocal', 'and', 'or', 'not', 'in', 'is', 'None', 'True', 'False', 'self'],
    'javascript': ['function', 'const', 'let', 'var', 'if', 'else', 'for', 'while', 'do', 'return', 'class', 'import', 'export', 'async', 'await', 'switch', 'case', 'default', 'break', 'continue', 'this', 'new', 'typeof', 'instanceof', 'delete', 'void', 'true', 'false', 'null', 'undefined', 'try', 'catch', 'finally', 'throw'],
    'typescript': ['function', 'const', 'let', 'var', 'if', 'else', 'for', 'while', 'do', 'return', 'class', 'interface', 'type', 'enum', 'namespace', 'module', 'import', 'export', 'async', 'await', 'switch', 'case', 'public', 'private', 'protected', 'readonly', 'static', 'abstract', 'extends', 'implements', 'generic', 'keyof', 'typeof'],
    'jsx': ['function', 'const', 'let', 'return', 'import', 'export', 'from', 'className', 'onClick', 'onChange', 'onSubmit', 'props', 'state', 'useState', 'useEffect', 'useContext', 'useReducer'],
    'tsx': ['function', 'const', 'let', 'interface', 'type', 'props', 'state', 'useState', 'useEffect', 'Props', 'FC', 'ReactNode', 'ReactElement', 'JSX'],
    'html': ['DOCTYPE', 'html', 'head', 'body', 'div', 'span', 'p', 'a', 'href', 'class', 'id', 'style', 'script', 'link', 'meta', 'title', 'h1', 'h2', 'h3', 'form', 'input', 'button', 'img', 'src', 'alt'],
    'css': ['selector', 'property', 'value', 'color', 'background', 'font-size', 'padding', 'margin', 'border', 'display', 'flex', 'grid', 'animation', 'transition', 'transform', 'box-shadow', 'opacity', 'z-index', '@media', '@keyframes', '@import'],
    'scss': ['$variable', '@import', '@mixin', '@include', '@extend', '@function', '@return', '@if', '@else', '@for', '@while', '@each', 'darken', 'lighten', 'mix', 'rgba'],
    'less': ['@variable', '@import', '@mixin', '@media', 'darken', 'lighten', 'saturate', 'desaturate', 'fadeIn', 'fadeOut'],
    'xml': ['<?xml', 'DOCTYPE', 'CDATA', 'encoding', 'version', 'xmlns', 'xsi', 'schemaLocation', 'element', 'attribute'],
    'svg': ['svg', 'g', 'path', 'd', 'circle', 'rect', 'line', 'polyline', 'polygon', 'text', 'tspan', 'image', 'defs', 'pattern', 'linearGradient', 'radialGradient'],
    'json': ['null', 'true', 'false', 'string', 'number', 'array', 'object'],
    'yaml': ['---', '...', 'key', 'value', 'null', 'true', 'false', '-', '?', '&', '*', '!tag', '!!str', '!!int', '!!float', '!!bool'],
    'toml': ['[section]', 'key', 'string', 'integer', 'float', 'boolean', 'array', 'datetime'],
    'markdown': ['#', '##', '###', '####', '#####', '######', '-', '*', '+', '>', '[', ']', '(', ')', '`', '```', '**', '*', '__', '_'],
    'bash': ['if', 'then', 'else', 'elif', 'fi', 'for', 'while', 'do', 'done', 'case', 'esac', 'function', 'return', 'echo', 'read', 'export', 'source', '[[', ']]', 'test', '[', ']'],
    'powershell': ['function', 'param', 'return', 'Write-Host', 'Get-', 'Set-', 'New-', 'Remove-', 'if', 'else', 'foreach', 'while', 'for', 'switch', 'try', 'catch', 'finally', '$', '|', 'Where-Object', 'Select-Object'],
    'cmd': ['ECHO', 'SET', 'FOR', 'IF', 'ELSE', 'REM', 'GOTO', 'CALL', 'EXIT', 'DIR', 'CD', 'DEL', 'COPY', 'MOVE', 'REN', 'TYPE', 'FINDSTR', 'TIMEOUT'],
    
    # ===== BACKEND LANGUAGES =====
    'java': ['public', 'private', 'protected', 'static', 'final', 'class', 'interface', 'extends', 'implements', 'void', 'return', 'if', 'else', 'for', 'while', 'try', 'catch', 'finally', 'throw', 'throws', 'new', 'this', 'super', 'package', 'import', 'abstract', 'synchronized', 'volatile', 'transient', 'native'],
    'kotlin': ['fun', 'val', 'var', 'class', 'object', 'interface', 'enum', 'data', 'sealed', 'when', 'if', 'else', 'for', 'while', 'return', 'try', 'catch', 'finally', 'is', 'as', 'in', 'by', 'with', 'companion', 'operator', 'infix'],
    'cpp': ['void', 'int', 'float', 'double', 'bool', 'char', 'long', 'short', 'unsigned', 'signed', 'class', 'struct', 'union', 'public', 'private', 'protected', 'template', 'namespace', 'if', 'else', 'for', 'while', 'do', 'return', 'new', 'delete', 'nullptr', 'const', 'static', 'virtual', 'override', 'final', 'noexcept'],
    'c': ['void', 'int', 'float', 'double', 'char', 'long', 'short', 'struct', 'union', 'typedef', 'enum', 'if', 'else', 'for', 'while', 'do', 'return', 'switch', 'case', 'default', 'break', 'continue', 'malloc', 'free', 'sizeof', 'define', 'ifdef', 'endif', 'include'],
    'csharp': ['public', 'private', 'protected', 'internal', 'static', 'readonly', 'const', 'class', 'interface', 'struct', 'enum', 'void', 'async', 'await', 'return', 'if', 'else', 'switch', 'case', 'for', 'foreach', 'while', 'do', 'try', 'catch', 'finally', 'throw', 'namespace', 'using', 'var', 'dynamic', 'null', 'true', 'false'],
    'go': ['func', 'package', 'import', 'const', 'var', 'type', 'struct', 'interface', 'if', 'else', 'for', 'range', 'switch', 'case', 'default', 'return', 'defer', 'panic', 'recover', 'go', 'select', 'chan', 'map', 'append', 'copy', 'delete', 'len', 'cap'],
    'rust': ['fn', 'let', 'mut', 'const', 'static', 'pub', 'crate', 'super', 'self', 'struct', 'enum', 'trait', 'impl', 'type', 'use', 'mod', 'if', 'else', 'match', 'for', 'while', 'loop', 'break', 'continue', 'return', 'async', 'await', 'unsafe', 'dyn', 'as', 'move', 'ref', 'where', 'Result', 'Option'],
    'swift': ['func', 'var', 'let', 'class', 'struct', 'enum', 'protocol', 'extension', 'if', 'else', 'guard', 'switch', 'case', 'for', 'while', 'repeat', 'break', 'continue', 'return', 'defer', 'do', 'try', 'catch', 'throw', 'async', 'await', 'final', 'override', 'convenience', 'required', 'optional'],
    'objc': ['@interface', '@implementation', '@property', '@synthesize', '@dynamic', '@protocol', '@optional', '@required', 'IBOutlet', 'IBAction', 'self', 'super', 'id', 'void', 'return', 'if', 'else', 'for', 'while', 'do', 'switch', 'case', 'break', 'continue', 'autoreleasepool', 'retain', 'release'],
    'php': ['<?php', 'function', 'class', 'interface', 'trait', 'namespace', 'use', 'const', 'public', 'private', 'protected', 'static', 'final', 'abstract', 'if', 'else', 'foreach', 'for', 'while', 'do', 'switch', 'case', 'return', 'echo', 'print', 'require', 'require_once', 'include', 'include_once', '$this', 'new', 'throw', 'try', 'catch'],
    'ruby': ['def', 'class', 'module', 'if', 'elsif', 'else', 'unless', 'case', 'when', 'for', 'while', 'until', 'break', 'next', 'return', 'yield', 'lambda', 'proc', 'begin', 'rescue', 'ensure', 'require', 'require_relative', 'attr_reader', 'attr_writer', 'attr_accessor', 'alias', 'super', 'self', 'puts', 'print', 'gets'],
    'perl': ['sub', 'my', 'our', 'local', 'if', 'elsif', 'else', 'unless', 'while', 'until', 'for', 'foreach', 'return', 'use', 'require', 'package', 'BEGIN', 'END', 'last', 'next', 'redo', 'goto', 'die', 'warn', 'eval', 'do', 'no', 'strict', 'warnings'],
    'lua': ['function', 'local', 'if', 'then', 'else', 'elseif', 'end', 'for', 'do', 'while', 'repeat', 'until', 'return', 'break', 'and', 'or', 'not', 'in', 'true', 'false', 'nil', 'require', 'module', 'pairs', 'ipairs', 'next', 'tonumber', 'tostring'],
    
    # ===== SQL & DATABASE =====
    'sql': ['SELECT', 'FROM', 'WHERE', 'AND', 'OR', 'NOT', 'IN', 'LIKE', 'BETWEEN', 'JOIN', 'INNER', 'LEFT', 'RIGHT', 'FULL', 'OUTER', 'ON', 'GROUP', 'BY', 'HAVING', 'ORDER', 'LIMIT', 'OFFSET', 'INSERT', 'UPDATE', 'DELETE', 'CREATE', 'ALTER', 'DROP', 'TABLE', 'DATABASE', 'INDEX', 'VIEW', 'TRIGGER'],
    'plsql': ['BEGIN', 'END', 'DECLARE', 'CURSOR', 'FOR', 'LOOP', 'EXIT', 'WHEN', 'IF', 'THEN', 'ELSE', 'ELSIF', 'PROCEDURE', 'FUNCTION', 'RETURN', 'INSERT', 'UPDATE', 'DELETE', 'SELECT', 'FETCH', 'OPEN', 'CLOSE'],
    'tsql': ['SELECT', 'FROM', 'WHERE', 'INSERT', 'UPDATE', 'DELETE', 'CREATE', 'ALTER', 'DROP', 'DECLARE', 'SET', 'IF', 'ELSE', 'BEGIN', 'END', 'VALUES', 'JOIN', 'GROUP', 'ORDER', 'EXEC', 'EXECUTE', 'PROCEDURE', 'FUNCTION', 'TRIGGER', 'VIEW', 'INDEX'],
    'mysql': ['SELECT', 'FROM', 'WHERE', 'INSERT', 'UPDATE', 'DELETE', 'CREATE', 'ALTER', 'DROP', 'table', 'database', 'INDEX', 'PRIMARY', 'FOREIGN', 'KEY', 'CONSTRAINT', 'JOIN', 'LEFT', 'RIGHT', 'INNER', 'OUTER', 'ON', 'GROUP', 'ORDER', 'LIMIT', 'OFFSET'],
    'mongodb': ['db', 'collection', 'find', 'findOne', 'insertOne', 'insertMany', 'updateOne', 'updateMany', 'deleteOne', 'deleteMany', 'aggregate', 'match', 'project', 'sort', 'limit', 'skip', 'group', 'lookup', 'unwind', 'out'],
    'redis': ['GET', 'SET', 'MGET', 'MSET', 'INCR', 'DECR', 'LPUSH', 'RPUSH', 'LPOP', 'RPOP', 'LLEN', 'SADD', 'SREM', 'SMEMBERS', 'ZADD', 'ZREM', 'ZRANGE', 'HSET', 'HGET', 'HDEL', 'HGETALL', 'EXPIRE', 'TTL', 'DEL'],
    
    # ===== DATA SCIENCE / ANALYSIS =====
    'r': ['function', 'if', 'else', 'for', 'while', 'repeat', 'break', 'next', 'return', 'library', 'require', 'source', 'data.frame', 'c', 'list', 'matrix', 'array', 'factor', 'TRUE', 'FALSE', 'NULL', 'NA', 'NaN', 'Inf', 'c', 'mean', 'sum', 'length', 'nrow', 'ncol'],
    'julia': ['function', 'end', 'if', 'elseif', 'else', 'for', 'while', 'break', 'continue', 'return', 'const', 'global', 'local', 'let', 'Tuple', 'Array', 'Dict', 'AbstractArray', 'struct', 'mutable', 'type', 'import', 'using', 'export', 'module', 'abstract'],
    'matlab': ['function', 'if', 'elseif', 'else', 'end', 'for', 'while', 'switch', 'case', 'otherwise', 'try', 'catch', 'return', 'break', 'continue', 'global', 'persistent', 'classdef', 'properties', 'methods', 'events'],
    
    # ===== WEB FRAMEWORKS =====
    'django': ['from', 'django', 'import', 'models', 'views', 'urls', 'forms', 'admin', 'Model', 'View', 'ListView', 'DetailView', 'CreateView', 'UpdateView', 'DeleteView', 'ForeignKey', 'CharField', 'TextField', 'IntegerField', 'DateTimeField', 'models.py', 'views.py', 'urls.py'],
    'flask': ['from', 'flask', 'import', 'Flask', 'render_template', 'request', 'jsonify', 'redirect', 'url_for', 'session', 'Blueprint', '@app.route', 'route', 'methods', 'GET', 'POST', 'PUT', 'DELETE', 'app'],
    'fastapi': ['from', 'fastapi', 'import', 'FastAPI', 'APIRouter', 'Depends', 'HTTPException', 'Path', 'Query', 'Body', 'Header', 'Cookie', 'app.get', 'app.post', 'app.put', 'app.delete', 'BaseModel', 'async def'],
    'react': ['import', 'export', 'function', 'const', 'useState', 'useEffect', 'useContext', 'useReducer', 'useCallback', 'useMemo', 'useRef', 'Props', 'children', 'className', 'onClick', 'onChange', 'onSubmit', 'JSX', 'components', '<>', '<div>', '<span>', '<p>'],
    'vue': ['import', 'export', 'template', 'script', 'style', 'data', 'methods', 'computed', 'watch', 'mounted', 'updated', 'destroyed', 'props', 'emits', 'slots', 'v-if', 'v-for', 'v-bind', 'v-on', '@click', ':key'],
    'angular': ['import', 'export', 'class', 'Component', 'NgModule', 'Injectable', 'OnInit', 'OnDestroy', 'Input', 'Output', 'EventEmitter', '@Component', '@Injectable', 'selector', 'templateUrl', 'styleUrls', 'constructor', 'ngOnInit', 'DependencyInjection'],
    'next': ['import', 'export', 'getStaticProps', 'getServerSideProps', 'useRouter', 'Link', 'Image', 'Head', 'pages', 'api', 'public', 'styles', 'components', 'lib', 'utils', 'context', 'hooks', 'middleware'],
    'nuxt': ['nuxt.config.js', 'pages', 'components', 'layouts', 'plugins', 'store', 'middleware', 'static', 'assets', 'layouts/default.vue', 'pages/index.vue', '<nuxt />', 'asyncData', 'fetch', 'computed', 'methods', 'watch'],
    'svelte': ['<script>', '{', '}', 'let', 'const', 'if', 'each', 'on:', 'class:', 'bind:', 'transition:', 'animate:', 'use:', 'import', 'export', 'components', 'stores', '$:', '@transitions', '@animations'],
    'ember': ['Route', 'Component', 'Service', 'Helper', 'Modifier', 'Controller', 'Model', 'Serializer', 'Adapter', 'Mixin', 'import', 'export', 'class extends', 'actions', 'properties', 'computed', 'tracked'],
    'laravel': ['Route', 'Controller', 'Model', 'Migration', 'Eloquent', 'Blade', 'Artisan', 'Middleware', 'Request', 'Response', '$app', '$this', 'public function', 'protected function', 'private function', 'namespace', 'use'],
    'symfony': ['Route', 'Controller', 'Service', 'Entity', 'Repository', 'Form', 'Validator', 'Security', 'Authentication', 'Authorization', 'middleware', 'event_listener', 'command', 'subscriber', 'namespace', 'use'],
    'asp_net': ['public', 'private', 'class', 'async', 'Task', 'ActionResult', 'ViewResult', 'RedirectResult', 'View', 'Model', 'DbSet', 'DbContext', 'Attribute', 'Route', 'HttpGet', 'HttpPost', 'HttpPut', 'HttpDelete'],
    
    # ===== MOBILE & DESKTOP =====
    'dart': ['void', 'main', 'class', 'extends', 'implements', 'function', 'const', 'static', 'final', 'if', 'else', 'for', 'while', 'do', 'switch', 'case', 'return', 'async', 'await', 'Future', 'Stream', 'var', 'dynamic', 'List', 'Map', 'Set'],
    'flutter': ['main', 'Widget', 'StatefulWidget', 'StatelessWidget', 'build', 'State', 'setState', 'initState', 'dispose', 'MaterialApp', 'Scaffold', 'AppBar', 'FloatingActionButton', 'Container', 'Column', 'Row', 'Text', 'ListView', 'GridView'],
    'react_native': ['import', 'export', 'function', 'useState', 'useEffect', 'View', 'Text', 'ScrollView', 'FlatList', 'TouchableOpacity', 'StyleSheet', 'Platform', 'AppRegistry', 'AsyncStorage', 'NetInfo', 'Animated'],
    'electron': ['require', 'const', 'app', 'BrowserWindow', 'ipcMain', 'ipcRenderer', 'Menu', 'dialog', 'remote', 'process', 'mainWindow', 'createWindow', 'app.on', 'ipcMain.on', 'ipcRenderer.send', 'preload.js'],
    'tauri': ['#[tauri::command]', 'invoke', 'event', 'emit', 'listen', 'window', 'app', 'path', 'fs', 'http', 'process', 'shell', 'dialog', 'notification', 'Cargo.toml', 'src-tauri'],
    'wpf': ['Window', 'DataContext', 'Binding', 'Command', 'DependencyProperty', 'AttachedBehavior', 'XAML', 'Code-behind', 'RoutedEvent', 'EventTrigger', 'Style', 'Template', 'Animation', 'Storyboard'],
    
    # ===== CONFIGURATION & INFRASTRUCTURE =====
    'dockerfile': ['FROM', 'RUN', 'CMD', 'ENTRYPOINT', 'WORKDIR', 'COPY', 'ADD', 'EXPOSE', 'ENV', 'VOLUME', 'USER', 'ARG', 'LABEL', 'HEALTHCHECK', 'SHELL'],
    'docker_compose': ['version:', 'services:', 'image:', 'build:', 'container_name:', 'ports:', 'volumes:', 'environment:', 'networks:', 'depends_on:', 'restart_policy:'],
    'kubernetes': ['apiVersion', 'kind', 'metadata', 'spec', 'Pod', 'Service', 'Deployment', 'StatefulSet', 'DaemonSet', 'Job', 'CronJob', 'ConfigMap', 'Secret', 'PersistentVolume', 'labels', 'selectors'],
    'terraform': ['resource', 'data', 'variable', 'output', 'module', 'local', 'provider', 'terraform', 'backend', 'provisioner', 'for_each', 'count', 'dynamic', 'depends_on', 'lifecycle'],
    'ansible': ['hosts', 'tasks', 'handlers', 'roles', 'vars', 'notify', 'block', 'rescue', 'always', 'when', 'loop', 'async', 'serial', 'strategy', 'tags', 'name'],
    'makefile': ['.PHONY', 'target', 'dependencies', 'recipe', 'variable', '$@', '$<', '$^', '$?', '$(', ')', 'include', 'ifdef', 'ifeq', 'ifneq', '@', '-', '+'],
    'gradle': ['buildscript', 'plugins', 'dependencies', 'repositories', 'tasks', 'build', 'clean', 'test', 'jar', 'war', 'ear', 'run', 'bootRun', 'compile', 'testCompile'],
    'maven': ['groupId', 'artifactId', 'version', 'packaging', 'dependencies', 'dependency', 'plugins', 'plugin', 'build', 'properties', 'repositories', 'repository', 'pluginRepositories'],
    
    # ===== ADDITIONAL LANGUAGES =====
    'groovy': ['def', 'class', 'void', 'return', 'if', 'else', 'for', 'while', 'switch', 'case', 'closure', 'println', 'assert', 'package', 'import', 'static', 'private', 'public', 'protected', 'abstract'],
    'scala': ['def', 'val', 'var', 'class', 'object', 'trait', 'case', 'if', 'else', 'for', 'while', 'match', 'case', 'yield', 'return', 'import', 'package', 'sealed', 'abstract', 'override', 'implicit'],
    'clojure': ['defn', 'let', 'if', 'cond', 'loop', 'recur', 'doseq', 'map', 'filter', 'reduce', 'quote', 'unquote', 'require', 'import', 'defmacro', 'defprotocol', 'deftype', 'defrecord', 'ns'],
    'elixir': ['defmodule', 'def', 'defp', 'case', 'cond', 'if', 'do', 'end', 'fn', 'when', 'import', 'require', 'use', 'alias', 'pipe', '|>', 'pattern_matching', 'guard', 'protocol'],
    'erlang': ['module', 'function', 'if', 'case', 'of', 'receive', 'after', 'spawn', 'send', 'apply', 'call', 'cast', 'handle_call', 'handle_cast', 'handle_info', 'init', 'terminate'],
    'haskell': ['module', 'import', 'where', 'function', 'case', 'of', 'let', 'in', 'if', 'then', 'else', 'do', 'return', 'data', 'type', 'class', 'instance', 'deriving'],
    'lisp': ['defun', 'defvar', 'setq', 'let', 'if', 'progn', 'cond', 'loop', 'dolist', 'mapcar', 'lambda', 'quote', 'eval', 'apply', 'funcall', 'require', 'provide'],
    'prolog': ['rule', 'fact', 'query', 'clause', 'unify', 'backtrack', 'cut', '!', 'assert', 'retract', 'findall', 'bagof', 'setof', 'member', 'append', 'length'],
    'cobol': ['IDENTIFICATION', 'DIVISION', 'ENVIRONMENT', 'DATA', 'PROCEDURE', 'ACCEPT', 'DISPLAY', 'IF', 'ELSE', 'PERFORM', 'UNTIL', 'VARYING', 'MOVE', 'COMPUTE', 'ADD', 'SUBTRACT'],
    'assembly': ['.text', '.data', '.bss', 'mov', 'add', 'sub', 'mul', 'div', 'push', 'pop', 'call', 'ret', 'jmp', 'je', 'jne', 'jl', 'jg', 'cmp', 'test', 'lea'],
    'vb_net': ['Module', 'Class', 'Sub', 'Function', 'If', 'Then', 'Else', 'For', 'Next', 'While', 'End', 'Do', 'Until', 'Select', 'Case', 'Try', 'Catch', 'Finally', 'Public', 'Private'],
    'pascel': ['program', 'unit', 'interface', 'implementation', 'procedure', 'function', 'begin', 'end', 'if', 'then', 'else', 'for', 'to', 'do', 'while', 'repeat', 'until', 'case', 'var', 'const'],
    'ada': ['procedure', 'function', 'package', 'with', 'use', 'type', 'record', 'array', 'if', 'else', 'elsif', 'end', 'for', 'loop', 'exit', 'when', 'begin', 'exception', 'private'],
    'fortran': ['PROGRAM', 'SUBROUTINE', 'FUNCTION', 'END', 'IF', 'THEN', 'ELSE', 'DO', 'WHILE', 'SELECT', 'CASE', 'INTEGER', 'REAL', 'CHARACTER', 'LOGICAL', 'DIMENSION', 'PARAMETER'],
    'ocaml': ['let', 'rec', 'in', 'function', 'match', 'with', 'type', 'module', 'open', 'exception', 'if', 'then', 'else', 'and', 'or', 'not', 'val', 'external', 'ref', 'when'],
    'fsharp': ['let', 'rec', 'in', 'function', 'match', 'with', 'type', 'module', 'open', 'namespace', 'if', 'then', 'else', 'for', 'do', 'while', 'try', 'catch', 'async', 'do!'],
    
    # ===== TEMPLATING LANGUAGES =====
    'jinja': ['{%', '{{', '{#', 'if', 'for', 'block', 'extends', 'include', 'import', 'from', 'macro', 'call', 'filter', 'test', 'set', 'namespace', 'autoescape', 'raw'],
    'template': ['<script type="text/template">', 'template', 'slot', 'bind', 'if', 'for', 'each', 'let', 'key', 'on:', '>'],
    'handlebars': ['{{', '}}}', '{{#if', '{{#each', '{{#with', '{{#unless', 'as |', 'helper', '{{>', '{{*inline', 'register'],
    'ejs': ['<%', '%>', '<%=', '%-', 'include', 'if', 'for', 'each', 'while', 'function', 'locals', 'async', 'cache'],
    'pug': ['mixin', 'extends', 'include', 'block', 'doctype', 'html', 'head', 'body', '.', '#', 'attributes', '-', '=', 'if', 'for', 'each', 'while', 'script', 'style'],
    
    # ===== GRAPHICS & GAME ENGINES =====
    'glsl': ['varying', 'uniform', 'attribute', 'in', 'out', 'vec', 'mat', 'sampler', 'void', 'float', 'int', 'bool', 'texture', 'normalize', 'dot', 'cross', 'reflect', 'refract', 'precision'],
    'hlsl': ['cbuffer', 'Texture2D', 'SamplerState', 'float4', 'float3', 'float2', 'void', 'VS', 'PS', 'GS', 'HS', 'DS', 'CS', 'mul', 'normalize', 'reflect', 'refract', 'saturate'],
    'cg': ['#pragma', 'vertex', 'fragment', 'void', 'float4', 'float3', 'float2', 'TRANSFORM', 'TEXCOORD', 'COLOR', 'NORMAL', 'POSITION', 'sampler2D', 'uniform', 'varying'],
    'unity': ['MonoBehaviour', 'Start', 'Update', 'FixedUpdate', 'LateUpdate', 'OnCollisionEnter', 'OnTriggerEnter', 'GetComponent', 'Instantiate', 'Destroy', 'transform', 'rigidbody', 'animator', 'collider'],
    'unreal': ['UCLASS', 'UPROPERTY', 'UFUNCTION', 'UPARAM', 'void', 'bool', 'float', 'int32', 'FVector', 'FRotator', 'AActor', 'APawn', 'ACharacter', 'AGameMode', 'APlayerController'],
    'godot': ['extends', 'class_name', 'func', 'signal', 'export', 'onready', '_ready', '_process', '_physics_process', 'get_node', 'add_child', 'queue_free', 'connect', 'emit_signal'],
}

# ==================== FONTS ====================
FONTS = {
    'mono': ['JetBrains Mono', 'Cascadia Code', 'Fira Code', 'Consolas', 'monospace'],
    'sans': ['Inter', 'SF Pro Display', '-apple-system', 'BlinkMacSystemFont', 'Segoe UI', 'sans-serif'],
}

# ==================== MARKDOWN STYLING ====================
# EXACT colors for markdown as specified
MARKDOWN_COLORS = {
    'heading': '#0047AB',       # Blue for headings
    'text': '#ffffff',          # White for text
    'code': '#50fa7b',          # Green (from string)
    'code_bg': 'rgba(82, 250, 123, 0.1)',
    'link': '#ff79c6',          # Pink (from tag)
    'bold': '#ffffff',
    'italic': '#ffffff',
}

# ==================== CSS CLASS GENERATOR ====================
def generate_language_css(language):
    """Generate CSS for a specific programming language"""
    keywords = LANGUAGE_KEYWORDS.get(language, [])
    
    css = f"""
    /* {language.upper()} Syntax Highlighting */
    .language-{language} .hljs-keyword {{ color: {DRACULA_COLORS['keyword']}; }}
    .language-{language} .hljs-string {{ color: {DRACULA_COLORS['string']}; }}
    .language-{language} .hljs-number {{ color: {DRACULA_COLORS['number']}; }}
    .language-{language} .hljs-comment {{ color: {DRACULA_COLORS['comment']}; }}
    .language-{language} .hljs-function {{ color: {DRACULA_COLORS['function']}; }}
    .language-{language} .hljs-title {{ color: {DRACULA_COLORS['function']}; }}
    .language-{language} .hljs-attr {{ color: {DRACULA_COLORS['tag']}; }}
    .language-{language} .hljs-tag {{ color: {DRACULA_COLORS['tag']}; }}
    """
    return css

# ==================== HTML HELPER ====================
def get_syntax_highlighting_link():
    """Returns the HTML link tag for syntax highlighting CSS"""
    return '<link rel="stylesheet" href="syntax-highlighting.css">'

# ==================== UNIVERSAL CODE COLORIZER ====================
class UniversalCodeColorizer:
    """
    Applies Dracula syntax highlighting to ALL programming languages.
    Uses regex-based pattern matching for comprehensive coverage.
    EVERY language gets colors - NO white text fallback.
    """
    
    def __init__(self):
        self.colors = DRACULA_COLORS
    
    def colorize(self, code, language='plaintext'):
        """
        Universal colorizer: Apply Dracula colors to any language.
        Returns HTML with proper color spans.
        EVERY element is colored - NO white text for any language.
        """
        if not code:
            return code
            
        # Normalize language name
        lang = language.lower().strip()
        
        # Try language-specific method first
        method_name = f'_colorize_{lang.replace("-", "_").replace(".", "_")}'
        if hasattr(self, method_name):
            return getattr(self, method_name)(code)
        
        # Fallback: Generic universal colorization
        return self._colorize_generic(code)
    
    def _colorize_generic(self, code):
        """
        Generic colorization for ANY unsupported language.
        Ensures ALL code is colored - NO white text.
        """
        result = code
        
        # Comments (multiple styles) - Blue-gray
        result = re.sub(
            r'(//.*?$|#.*?$|--.*?$|/\*[\s\S]*?\*/|<!--[\s\S]*?-->)',
            f'<span style="color: {self.colors["comment"]};">\\1</span>',
            result,
            flags=re.MULTILINE
        )
        
        # Strings (all types) - Green
        result = re.sub(
            r'(["\'])(?:(?=(\\?))\2.)*?\1|`[^`]*`|\'\'\'[\s\S]*?\'\'\'|"""[\s\S]*?"""',
            f'<span style="color: {self.colors["string"]};">\\g<0></span>',
            result
        )
        
        # Numbers - Purple
        result = re.sub(
            r'\b(\d+\.?\d*([eE][+-]?\d+)?|0[xX][0-9a-fA-F]+|0[bB][01]+)\b',
            f'<span style="color: {self.colors["number"]};">\\1</span>',
            result
        )
        
        # Common keywords from ALL languages - Purple
        all_keywords = set()
        for keywords_list in LANGUAGE_KEYWORDS.values():
            all_keywords.update(keywords_list)
        
        # Sort by length (longest first) to avoid partial matches
        for keyword in sorted(all_keywords, key=len, reverse=True):
            if keyword.isalnum() or keyword in ('self', '$', '->'):
                result = re.sub(
                    f'\\b{re.escape(keyword)}\\b',
                    f'<span style="color: {self.colors["keyword"]}">{keyword}</span>',
                    result,
                    flags=re.IGNORECASE
                )
        
        # Function/method calls - Orange
        result = re.sub(
            r'\b([a-zA-Z_][a-zA-Z0-9_]*)\s*\(',
            f'<span style="color: {self.colors["function"]};">\\1</span>(',
            result
        )
        
        # HTML/XML tags - Pink
        result = re.sub(
            r'(<[^>]+>)',
            f'<span style="color: {self.colors["tag"]};">\\1</span>',
            result
        )
        
        # Variables ($var, $this, etc) - Red
        result = re.sub(
            r'(\$[a-zA-Z_][a-zA-Z0-9_]*)',
            f'<span style="color: {self.colors["variable"]};">\\1</span>',
            result
        )
        
        return result
    
    def _colorize_python(self, code):
        """Python with exact Dracula colors"""
        result = code
        
        # Docstrings - Green
        result = re.sub(
            r'("""[\s\S]*?"""|\'\'\'[\s\S]*?\'\'\')',
            f'<span style="color: {self.colors["string"]};">\\1</span>',
            result
        )
        
        # Comments - Blue-gray
        result = re.sub(
            r'(#.*?)($|\n)',
            f'<span style="color: {self.colors["comment"]};">\\1</span>\\2',
            result,
            flags=re.MULTILINE
        )
        
        # Strings - Green
        result = re.sub(
            r'(["\'])(?:(?=(\\?))\2.)*?\1',
            f'<span style="color: {self.colors["string"]};">\\g<0></span>',
            result
        )
        
        # Keywords - Purple
        for keyword in LANGUAGE_KEYWORDS.get('python', []):
            result = re.sub(
                f'\\b{keyword}\\b',
                f'<span style="color: {self.colors["keyword"]}">{keyword}</span>',
                result
            )
        
        # Decorators - Pink  
        result = re.sub(
            r'(@[a-zA-Z_][a-zA-Z0-9_]*)',
            f'<span style="color: {self.colors["tag"]};">\\1</span>',
            result
        )
        
        # Built-in functions - Cyan
        builtins = ['print', 'len', 'range', 'str', 'int', 'float', 'list', 'dict', 'set', 'tuple', 'open', 'isinstance', 'type', 'super', 'getattr', 'setattr', 'hasattr', 'callable']
        for builtin in builtins:
            result = re.sub(
                f'\\b{builtin}\\b',
                f'<span style="color: {self.colors["builtin"]}">{builtin}</span>',
                result
            )
        
        # Numbers - Purple
        result = re.sub(
            r'\b(\d+\.?\d*([eE][+-]?\d+)?|0[xX][0-9a-fA-F]+|0[bB][01]+)\b',
            f'<span style="color: {self.colors["number"]};">\\1</span>',
            result
        )
        
        # Class definitions - Cyan
        result = re.sub(
            r'\bclass\s+([a-zA-Z_][a-zA-Z0-9_]*)',
            f'<span style="color: {self.colors["keyword"]};">class</span> <span style="color: {self.colors["class"]};">\\1</span>',
            result
        )
        
        # Function definitions - Orange
        result = re.sub(
            r'\bdef\s+([a-zA-Z_][a-zA-Z0-9_]*)',
            f'<span style="color: {self.colors["keyword"]};">def</span> <span style="color: {self.colors["function"]};">\\1</span>',
            result
        )
        
        return result
    
    def _colorize_javascript(self, code):
        """JavaScript with exact Dracula colors"""
        result = code
        
        # Comments - Blue-gray
        result = re.sub(
            r'(//.*?$|/\*[\s\S]*?\*/)',
            f'<span style="color: {self.colors["comment"]};">\\1</span>',
            result,
            flags=re.MULTILINE
        )
        
        # Template literals - Green
        result = re.sub(
            r'(`[^`]*`)',
            f'<span style="color: {self.colors["string"]};">\\1</span>',
            result
        )
        
        # Strings - Green
        result = re.sub(
            r'(["\'])(?:(?=(\\?))\2.)*?\1',
            f'<span style="color: {self.colors["string"]};">\\g<0></span>',
            result
        )
        
        # Keywords - Purple
        for keyword in LANGUAGE_KEYWORDS.get('javascript', []):
            result = re.sub(
                f'\\b{keyword}\\b',
                f'<span style="color: {self.colors["keyword"]}">{keyword}</span>',
                result
            )
        
        # Numbers - Purple
        result = re.sub(
            r'\b(\d+\.?\d*([eE][+-]?\d+)?|0[xX][0-9a-fA-F]+)\b',
            f'<span style="color: {self.colors["number"]};">\\1</span>',
            result
        )
        
        # Function calls - Orange
        result = re.sub(
            r'\b([a-zA-Z_$][a-zA-Z0-9_$]*)\s*\(',
            f'<span style="color: {self.colors["function"]};">\\1</span>(',
            result
        )
        
        return result
    
    def _colorize_typescript(self, code):
        """TypeScript with exact Dracula colors"""
        # Same as JavaScript + type annotations
        result = self._colorize_javascript(code)
        
        # Type annotations - Cyan
        result = re.sub(
            r':\s*([A-Za-z_][A-Za-z0-9_<>[\],\s]*)',
            f': <span style="color: {self.colors["class"]};">\\1</span>',
            result
        )
        
        return result
    
    def _colorize_html(self, code):
        """HTML with exact Dracula colors"""
        result = code
        
        # Comments - Blue-gray
        result = re.sub(
            r'(<!--[\s\S]*?-->)',
            f'<span style="color: {self.colors["comment"]};">\\1</span>',
            result
        )
        
        # Tags - Pink
        result = re.sub(
            r'(&lt;/?[a-z][a-z0-9]*\s*/?&gt;)',
            f'<span style="color: {self.colors["tag"]};">\\1</span>',
            result,
            flags=re.IGNORECASE
        )
        
        # Attributes - Pink
        result = re.sub(
            r'([a-z-]+)\s*=',
            f'<span style="color: {self.colors["tag"]};">\\1</span>=',
            result,
            flags=re.IGNORECASE
        )
        
        # Strings - Green
        result = re.sub(
            r'(["\'])(?:(?=(\\?))\2.)*?\1',
            f'<span style="color: {self.colors["string"]};">\\g<0></span>',
            result
        )
        
        return result
    
    def _colorize_css(self, code):
        """CSS with exact Dracula colors"""
        result = code
        
        # Comments - Blue-gray
        result = re.sub(
            r'(\/\*[\s\S]*?\*\/)',
            f'<span style="color: {self.colors["comment"]};">\\1</span>',
            result
        )
        
        # Selectors - Orange
        result = re.sub(
            r'^([.#]?[a-zA-Z][a-zA-Z0-9\-_:]*)\s*{',
            f'<span style="color: {self.colors["function"]};">\\1</span> {{',
            result,
            flags=re.MULTILINE
        )
        
        # Properties - Pink
        result = re.sub(
            r'([a-z-]+)\s*:',
            f'<span style="color: {self.colors["tag"]};">\\1</span>:',
            result,
            flags=re.IGNORECASE
        )
        
        # Values (colors, sizes) - Yellow
        result = re.sub(
            r':\s*(#[0-9a-fA-F]{3,6}|[0-9]+px|[0-9.]+em|[0-9.]+%|[0-9.]+)',
            f': <span style="color: {self.colors["const"]};">\\1</span>',
            result
        )
        
        # Strings - Green
        result = re.sub(
            r'(["\'])(?:(?=(\\?))\2.)*?\1',
            f'<span style="color: {self.colors["string"]};">\\g<0></span>',
            result
        )
        
        return result
    
    def _colorize_sql(self, code):
        """SQL with exact Dracula colors"""
        result = code
        
        # Comments - Blue-gray
        result = re.sub(
            r'(--.*?$|/\*[\s\S]*?\*/)',
            f'<span style="color: {self.colors["comment"]};">\\1</span>',
            result,
            flags=re.MULTILINE
        )
        
        # Strings - Green
        result = re.sub(
            r"(['\"])(?:(?=(\\?))\2.)*?\1",
            f'<span style="color: {self.colors["string"]};">\\g<0></span>',
            result
        )
        
        # Keywords - Purple
        for keyword in LANGUAGE_KEYWORDS.get('sql', []):
            result = re.sub(
                f'\\b{keyword}\\b',
                f'<span style="color: {self.colors["keyword"]}">{keyword}</span>',
                result,
                flags=re.IGNORECASE
            )
        
        # Numbers - Purple
        result = re.sub(
            r'\b(\d+\.?\d*)\b',
            f'<span style="color: {self.colors["number"]};">\\1</span>',
            result
        )
        
        return result
    
    def _colorize_java(self, code):
        """Java with exact Dracula colors"""
        result = code
        
        # Comments - Blue-gray
        result = re.sub(
            r'(//.*?$|/\*[\s\S]*?\*/)',
            f'<span style="color: {self.colors["comment"]};">\\1</span>',
            result,
            flags=re.MULTILINE
        )
        
        # Strings - Green
        result = re.sub(
            r'(["\'])(?:(?=(\\?))\2.)*?\1',
            f'<span style="color: {self.colors["string"]};">\\g<0></span>',
            result
        )
        
        # Keywords - Purple
        for keyword in LANGUAGE_KEYWORDS.get('java', []):
            result = re.sub(
                f'\\b{keyword}\\b',
                f'<span style="color: {self.colors["keyword"]}">{keyword}</span>',
                result
            )
        
        # Class names - Cyan (after 'class' keyword)
        result = re.sub(
            r'class\s+([A-Z][a-zA-Z0-9_]*)',
            f'<span style="color: {self.colors["keyword"]};">class</span> <span style="color: {self.colors["class"]};">\\1</span>',
            result
        )
        
        # Numbers - Purple
        result = re.sub(
            r'\b(\d+\.?\d*([eE][+-]?\d+)?|0[xX][0-9a-fA-F]+)\b',
            f'<span style="color: {self.colors["number"]};">\\1</span>',
            result
        )
        
        return result
    
    def _colorize_cpp(self, code):
        """C++ with exact Dracula colors"""
        result = code
        
        # Comments - Blue-gray
        result = re.sub(
            r'(//.*?$|/\*[\s\S]*?\*/)',
            f'<span style="color: {self.colors["comment"]};">\\1</span>',
            result,
            flags=re.MULTILINE
        )
        
        # Preprocessor - Pink
        result = re.sub(
            r'(#\s*include|#\s*define|#\s*ifdef)',
            f'<span style="color: {self.colors["tag"]};">\\1</span>',
            result
        )
        
        # Strings - Green
        result = re.sub(
            r'(["\'])(?:(?=(\\?))\2.)*?\1',
            f'<span style="color: {self.colors["string"]};">\\g<0></span>',
            result
        )
        
        # Keywords - Purple
        for keyword in LANGUAGE_KEYWORDS.get('cpp', []):
            result = re.sub(
                f'\\b{keyword}\\b',
                f'<span style="color: {self.colors["keyword"]}">{keyword}</span>',
                result
            )
        
        # Numbers - Purple
        result = re.sub(
            r'\b(\d+\.?\d*([eE][+-]?\d+)?|0[xX][0-9a-fA-F]+)\b',
            f'<span style="color: {self.colors["number"]};">\\1</span>',
            result
        )
        
        return result


# ==================== MARKDOWN COLORIZER ====================
class MarkdownColorizer:
    """Applies Dracula colors to Markdown - Blue headings, White text"""
    
    @staticmethod
    def colorize(markdown_text):
        """Apply Markdown coloring with EXACT color scheme"""
        if not markdown_text:
            return markdown_text
            
        result = markdown_text
        
        # Headings - Blue (#0047AB)
        result = re.sub(
            r'^(#{1,6})\s+(.+)$',
            f'<span style="color: {MARKDOWN_COLORS["heading"]}; font-weight: 700;">\\1 \\2</span>',
            result,
            flags=re.MULTILINE
        )
        
        # Code blocks - Green
        result = re.sub(
            r'`([^`]+)`',
            f'<span style="color: {MARKDOWN_COLORS["code"]}; background: {MARKDOWN_COLORS["code_bg"]}; padding: 2px 6px; border-radius: 4px;">\\1</span>',
            result
        )
        
        # Links - Pink
        result = re.sub(
            r'\[([^\]]+)\]\(([^)]+)\)',
            f'<a href="\\2" style="color: {MARKDOWN_COLORS["link"]};">\\1</a>',
            result
        )
        
        # Bold - White with weight
        result = re.sub(
            r'\*\*(.+?)\*\*',
            f'<span style="font-weight: 700; color: {MARKDOWN_COLORS["bold"]};">\\1</span>',
            result
        )
        
        # Italic - White with style
        result = re.sub(
            r'\*(.+?)\*',
            f'<span style="font-style: italic; color: {MARKDOWN_COLORS["italic"]};">\\1</span>',
            result
        )
        
        return result


# ==================== EXPORTS ====================
__all__ = [
    'DRACULA_COLORS',
    'LANGUAGE_KEYWORDS',
    'FONTS',
    'MARKDOWN_COLORS',
    'UniversalCodeColorizer',
    'MarkdownColorizer',
    'generate_language_css',
    'get_syntax_highlighting_link',
]

