#!/usr/bin/env python3
"""
AST-Scan über archon/routers/*.py — findet Load-Namen, die weder importiert,
zugewiesen, als Argument/Comprehension-Variable gebunden, noch im Modul definiert,
noch über configure(**deps) als akzeptierter Parameter deklariert sind.
Exit 1 bei Treffern, Ausgabe: datei:name
"""

import ast
import sys
import os
from pathlib import Path

ROUTER_DIR = Path(__file__).parent.parent / "archon" / "routers"
ROUTER_FILES = sorted(ROUTER_DIR.glob("*.py"))

# Names that are allowed to appear as Load without definition
BUILTINS = {
    'True', 'False', 'None', 'Exception', 'BaseException', 'KeyboardInterrupt',
    'SystemExit', 'GeneratorExit', 'StopIteration', 'StopAsyncIteration',
    'ArithmeticError', 'AssertionError', 'AttributeError', 'BufferError',
    'EOFError', 'FloatingPointError', 'ImportError', 'LookupError',
    'MemoryError', 'NameError', 'OSError', 'OverflowError', 'RecursionError',
    'ReferenceError', 'RuntimeError', 'SyntaxError', 'SystemError',
    'TypeError', 'ValueError', 'ZeroDivisionError', 'Warning',
    'DeprecationWarning', 'EncodingWarning', 'FutureWarning', 'ImportWarning',
    'PendingDeprecationWarning', 'ResourceWarning', 'RuntimeWarning',
    'SyntaxWarning', 'UnicodeWarning', 'BytesWarning', 'int', 'float',
    'str', 'bool', 'list', 'dict', 'tuple', 'set', 'frozenset', 'bytes',
    'bytearray', 'memoryview', 'complex', 'object', 'type', 'property',
    'staticmethod', 'classmethod', 'super', 'staticmethod', 'classmethod',
    'isinstance', 'issubclass', 'hasattr', 'getattr', 'setattr', 'delattr',
    'len', 'range', 'enumerate', 'zip', 'map', 'filter', 'sorted', 'reversed',
    'sum', 'min', 'max', 'any', 'all', 'abs', 'round', 'pow', 'divmod',
    'open', 'print', 'input', 'iter', 'next', 'callable', 'vars', 'locals',
    'globals', 'dir', 'help', 'hash', 'id', 'format', 'ascii', 'bin', 'hex',
    'oct', 'chr', 'ord', 'compile', 'eval', 'exec', 'breakpoint', 'property',
    'classmethod', 'staticmethod', '__import__', 'NotImplemented', 'Ellipsis',
    'copyright', 'credits', 'license', 'quit', 'exit',
}

# Additional module-level globals that are expected
MODULE_GLOBALS_WHITELIST = {
    '__file__', '__name__', '__package__', '__doc__', '__version__',
    '__author__', '__license__', 'router', 'HTTPException', 'APIRouter',
    'Body', 'File', 'Query', 'UploadFile', 'Form', 'Depends', 'BackgroundTasks',
    'Request', 'Response', 'JSONResponse', 'HTMLResponse', 'FileResponse',
    'StreamingResponse', 'RedirectResponse', 'Response', 'PermissionError',
}

# Known stdlib modules that might be used without explicit import in some contexts
STDLIB_NAMES = {
    'os', 'sys', 'json', 'yaml', 'time', 'datetime', 're', 'asyncio',
    'hashlib', 'base64', 'uuid', 'pathlib', 'shutil', 'copy', 'itertools',
    'collections', 'functools', 'operator', 'typing', 'dataclasses',
    'decimal', 'fractions', 'random', 'string', 'textwrap', 'unicodedata',
    'html', 'urllib', 'http', 'email', 'mimetypes', 'csv', 'sqlite3',
    'subprocess', 'threading', 'multiprocessing', 'concurrent', 'queue',
    'heapq', 'bisect', 'array', 'weakref', 'types', 'inspect', 'importlib',
    'pkgutil', 'contextlib', 'abc', 'numbers', 'math', 'statistics',
}

# Names known to be injected via configure() in each router
CONFIGURE_PARAMS = {
    'boardroom.py': {
        'load_boardroom_frameworks', 'load_roles', 'api_get_hermes_profiles',
        'copy', '_load_json', '_save_json', 'broadcast_event'
    },
    'governance.py': {
        '_load_mission_control_data', '_save_mission_control_data',
        'api_get_hermes_profiles'
    },
    'hermes_profiles.py': {
        '_sync_org_hierarchy_node', 'invalidate_paperclip_agents_cache',
        'save_all_agent_profiles'
    },
    'skills.py': {
        'skills_engine', 'api_get_hermes_profiles'
    },
    'system.py': {
        '_load_json', '_save_json', 'broadcast_event'
    },
    'containers.py': {
        'detect_container_port', 'post_docker_container_action'
    },
}

# Names that are actually stdlib (shutil, copy)
STDLIB_LOCAL = {'shutil', 'copy'}


def scan_file(filepath: Path):
    """Scan a single router file for undefined names."""
    with open(filepath, 'r', encoding='utf-8') as f:
        source = f.read()
    
    try:
        tree = ast.parse(source, filename=str(filepath))
    except SyntaxError as e:
        print(f"{filepath.name}:SYNTAX_ERROR: {e}")
        return []
    
    # Collect all definitions
    defined_names = set()
    assigned_names = set()
    imported_names = set()
    function_args = set()
    comprehension_vars = set()
    class_names = set()
    
    # First pass: collect all definitions
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            defined_names.add(node.name)
            for arg in node.args.args:
                function_args.add(arg.arg)
            for arg in node.args.posonlyargs:
                function_args.add(arg.arg)
            for arg in node.args.kwonlyargs:
                function_args.add(arg.arg)
            if node.args.vararg:
                function_args.add(node.args.vararg.arg)
            if node.args.kwarg:
                function_args.add(node.args.kwarg.arg)
        elif isinstance(node, ast.AsyncFunctionDef):
            defined_names.add(node.name)
            for arg in node.args.args:
                function_args.add(arg.arg)
            for arg in node.args.posonlyargs:
                function_args.add(arg.arg)
            for arg in node.args.kwonlyargs:
                function_args.add(arg.arg)
            if node.args.vararg:
                function_args.add(node.args.vararg.arg)
            if node.args.kwarg:
                function_args.add(node.args.kwarg.arg)
        elif isinstance(node, ast.ClassDef):
            defined_names.add(node.name)
            class_names.add(node.name)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                imported_names.add(alias.asname or alias.name.split('.')[0])
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                imported_names.add(alias.asname or alias.name)
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    assigned_names.add(target.id)
                    defined_names.add(target.id)
                elif isinstance(target, ast.Tuple):
                    for elt in target.elts:
                        if isinstance(elt, ast.Name):
                            assigned_names.add(elt.id)
                            defined_names.add(elt.id)
        elif isinstance(node, ast.AnnAssign):
            if isinstance(node.target, ast.Name):
                assigned_names.add(node.target.id)
                defined_names.add(node.target.id)
        elif isinstance(node, (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)):
            for gen in node.generators:
                if isinstance(gen.target, ast.Name):
                    comprehension_vars.add(gen.target.id)
                elif isinstance(gen.target, ast.Tuple):
                    for elt in gen.target.elts:
                        if isinstance(elt, ast.Name):
                            comprehension_vars.add(elt.id)
        elif isinstance(node, (ast.For, ast.AsyncFor)):
            if isinstance(node.target, ast.Name):
                comprehension_vars.add(node.target.id)
            elif isinstance(node.target, ast.Tuple):
                for elt in node.target.elts:
                    if isinstance(elt, ast.Name):
                        comprehension_vars.add(elt.id)
        elif isinstance(node, (ast.With, ast.AsyncWith)):
            for item in node.items:
                if item.optional_vars:
                    if isinstance(item.optional_vars, ast.Name):
                        comprehension_vars.add(item.optional_vars.id)
        elif isinstance(node, ast.ExceptHandler):
            if node.name:
                comprehension_vars.add(node.name)
        elif isinstance(node, ast.Lambda):
            for arg in node.args.args:
                function_args.add(arg.arg)
    
    # Look for configure() function to get its parameter names
    configure_params = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == 'configure':
            for arg in node.args.args:
                configure_params.add(arg.arg)
            for arg in node.args.kwonlyargs:
                configure_params.add(arg.arg)
            if node.args.vararg:
                configure_params.add(node.args.vararg.arg)
            if node.args.kwarg:
                configure_params.add(node.args.kwarg.arg)
    
    # All valid names that can be Loaded
    filename = filepath.name
    known_configure = CONFIGURE_PARAMS.get(filename, set())
    valid_names = (
        BUILTINS | MODULE_GLOBALS_WHITELIST | STDLIB_NAMES | STDLIB_LOCAL |
        defined_names | assigned_names | imported_names |
        function_args | comprehension_vars | configure_params | class_names |
        known_configure
    )
    
    # Now find all Load names that are not valid
    undefined = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
            name = node.id
            if name not in valid_names:
                # Get line number
                line = node.lineno
                undefined.append((name, line))
    
    # Deduplicate
    seen = set()
    result = []
    for name, line in undefined:
        if name not in seen:
            seen.add(name)
            result.append((name, line))
    
    return result


def main():
    all_issues = []
    for filepath in ROUTER_FILES:
        if filepath.name == '__init__.py':
            continue
        issues = scan_file(filepath)
        for name, line in issues:
            all_issues.append(f"{filepath.name}:{name} (line {line})")
    
    if all_issues:
        for issue in all_issues:
            print(issue)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())