import os
import re
import json
import ast
import time
import random
from dotenv import load_dotenv
from collections import defaultdict
from google import genai

# --- Configuration ---

# Directories to ignore completely
IGNORE_DIRS = {
    '.git',
    'node_modules',
    '__pycache__',
    'dist',
    'build',
    '.vscode',
    '.idea',
    'venv',
    '.env'
}

# File extensions to scan
SCAN_EXTENSIONS = {
    '.py',
    '.js',
    '.jsx',
    '.ts',
    '.tsx',
    '.html',
    '.css',
    '.md',
    '.json',
    '.env'
}

# Mapping from extension to language name
LANG_MAP = {
    '.py': 'python',
    '.js': 'javascript',
    '.jsx': 'jsx',
    '.ts': 'typescript',
    '.tsx': 'tsx',
    '.html': 'html',
    '.css': 'css',
    '.md': 'markdown',
    '.json': 'json',
    '.env': 'dotenv'
}

# Patterns to detect side effects (keyword-based)
SIDE_EFFECT_PATTERNS = {
    'network': re.compile(r'requests\.|fetch\(|axios\.|urllib|socket\.|http\.client|httpx'),
    'database': re.compile(r'sqlite3\.|sqlalchemy\.|db\.execute|connect\(|cursor\('),
    'filesystem': re.compile(r'open\(|os\.path|pathlib\.Path|fs\.|writeFile|readFile'),
    'env_vars': re.compile(r'os\.getenv|dotenv\.|process\.env'),
    'subprocess': re.compile(r'subprocess\.|os\.system'),
    'auth': re.compile(r'jwt\.|jose\.|passlib|oauth2')
}

# --- Golden Sample Loading ---

def parse_golden_sample(filepath="map.txt"):
    """
    Parses the semi-structured map.txt file into a dictionary.
    This is a simplified parser and might need adjustments for complex cases.
    """
    if not os.path.exists(filepath):
        return None

    data = {"files": []}
    current_file = None

    with open(filepath, 'r') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue

            # Using regex to capture key-value pairs
            root_match = re.match(r"(\w+):\s*(.*)", line)
            if root_match and current_file is None:
                key, value = root_match.groups()
                if key in ['project', 'description']:
                    data[key] = value
                elif key == 'roots':
                    data[key] = {}
                elif value and data.get('roots') is not None: # Assumes it's a root definition
                    root_name, root_path = value.split(':', 1)
                    data['roots'][root_name.strip()] = root_path.strip()
                continue

            if line.startswith('- path:'):
                if current_file:
                    data['files'].append(current_file)
                current_file = {'path': line.split(':', 1)[1].strip()}
            elif current_file is not None:
                # Regex to handle keys, values, and lists
                kv_match = re.match(r"(\w+):\s*(.*)", line)
                if kv_match:
                    key, value = kv_match.groups()
                    if value.startswith('['): # It's a list
                        # Use regex to find all words, routes, or bracketed items inside the list
                        list_items = re.findall(r"'([^']+)'|([\w\.-]+)", value)
                        # The regex returns tuples if there are multiple groups, so we need to flatten and filter
                        cleaned_items = [item[0] or item[1] for item in list_items]
                        current_file[key] = cleaned_items
                    else:
                        current_file[key] = value
    if current_file:
        data['files'].append(current_file)

    # Convert list of files to a dictionary keyed by path for easy lookup
    files_dict = {f['path']: f for f in data['files']}
    data['files'] = files_dict
    return data

# --- Analyzers ---

def analyze_python(content, filepath):
    """Analyzes Python source code for imports, exports, and side effects."""
    deps = set()
    exports = set()

    # AST parsing for reliable import/export detection
    try:
        tree = ast.parse(content)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    deps.add(alias.name.split('.')[0])
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    deps.add(node.module.split('.')[0])
            elif isinstance(node, (ast.FunctionDef, ast.ClassDef)):
                if not node.name.startswith('_'):
                    exports.add(node.name)
            # FastAPI/Flask route detection
            elif isinstance(node, ast.FunctionDef):
                 for decorator in node.decorator_list:
                     if isinstance(decorator, ast.Call) and isinstance(decorator.func, ast.Attribute):
                         if decorator.func.attr in ('get', 'post', 'put', 'delete', 'patch'):
                             if len(decorator.args) > 0 and isinstance(decorator.args[0], ast.Constant):
                                 route = decorator.args[0].value
                                 method = decorator.func.attr.upper()
                                 exports.add(f"'{method} {route}'")

    except SyntaxError:
        # Fallback to regex for files with syntax errors or that are not pure python
        for line in content.splitlines():
            import_match = re.match(r'^\s*(?:import|from)\s+([\w\.]+)', line)
            if import_match:
                deps.add(import_match.group(1).split('.')[0])

    return list(deps), list(exports)


def analyze_js(content, filepath):
    """Analyzes JavaScript/JSX source code for imports and exports."""
    deps = set()
    exports = set()

    # Regex for imports and exports
    import_regex = re.compile(r'import(?:[\s\w{},*\'"]+from)?\s+[\'\"]([./\w-]+)[\'\"]')
    require_regex = re.compile(r'require\([\'\"]([./\w-]+)[\'\"]\)')
    export_regex = re.compile(r'export\s+(?:(?:const|let|var|function|class|default)\s+)?(\w+)')

    for line in content.splitlines():
        for match in import_regex.finditer(line):
            deps.add(match.group(1))
        for match in require_regex.finditer(line):
            deps.add(match.group(1))
        for match in export_regex.finditer(line):
            exports.add(match.group(1))

    # Clean up dependencies
    cleaned_deps = set()
    for dep in deps:
        if dep.startswith('./') or dep.startswith('../'):
            # Resolve relative path
            abs_path = os.path.normpath(os.path.join(os.path.dirname(filepath), dep))
            # Make it relative to the project root
            cleaned_deps.add(os.path.relpath(abs_path, '.').replace('\\', '/'))
        else:
            cleaned_deps.add(dep) # It's a library

    return list(cleaned_deps), list(exports)


def detect_side_effects(content):
    """Detects potential side effects based on keyword matching."""
    effects = set()
    for effect_type, pattern in SIDE_EFFECT_PATTERNS.items():
        if pattern.search(content):
            effects.add(effect_type)
    return list(effects)


# --- Main Logic ---

def scan_codebase(root_dir='.'):
    """Scans the codebase and builds the map."""
    file_map = {}
    all_deps = defaultdict(list)

    for root, dirs, files in os.walk(root_dir, topdown=True):
        # Modify dirs in-place to skip ignored directories
        dirs[:] = [d for d in dirs if d not in IGNORE_DIRS]

        for filename in files:
            filepath = os.path.join(root, filename)
            rel_path = os.path.relpath(filepath, root_dir).replace('\\', '/')
            _, ext = os.path.splitext(filename)

            if ext not in SCAN_EXTENSIONS:
                continue

            try:
                with open(filepath, 'r', encoding='utf-8') as f:
                    content = f.read()
            except (IOError, UnicodeDecodeError):
                content = "" # Skip binary or unreadable files

            lang = LANG_MAP.get(ext, 'unknown')
            deps, exports = [], []
            if lang == 'python':
                deps, exports = analyze_python(content, rel_path)
            elif lang in ['javascript', 'jsx']:
                deps, exports = analyze_js(content, rel_path)

            side_effects = detect_side_effects(content)
            role = f"A {lang} file with exports: {exports} and side effects: {side_effects}" if exports or side_effects else f"A {lang} file."


            file_map[rel_path] = {
                'path': rel_path,
                'lang': lang,
                'role': role,
                'exports': sorted(exports),
                'deps': sorted(deps),
                'side_effects': sorted(side_effects)
            }
            for dep in deps:
                all_deps[dep].append(rel_path)


    # Calculate dependents
    for path, data in file_map.items():
        dependents = []
        # Check based on file path
        if path in all_deps:
            dependents.extend(all_deps[path])
        # Check based on module name (for python)
        module_name = path.replace('.py', '').replace('/', '.')
        if module_name in all_deps:
            dependents.extend(all_deps[module_name])

        file_map[path]['dependents'] = sorted(list(set(dependents)))

    return file_map

def compare_maps(generated, golden):
    """Compares the generated map with the golden sample and prints a diff."""
    if golden is None:
        print("--- No golden sample (map.txt) found. Printing generated map. ---")
        print(json.dumps(generated, indent=2))
        return

    print("--- Comparing Generated Map with Golden Sample (map.txt) ---")
    golden_files = golden.get('files', {})
    all_paths = sorted(list(set(generated.keys()) | set(golden_files.keys())))

    for path in all_paths:
        gen_file = generated.get(path)
        gold_file = golden_files.get(path)

        if gen_file and not gold_file:
            print(f"\n[+] ADDED: {path}")
            continue
        if gold_file and not gen_file:
            print(f"\n[-] REMOVED: {path}")
            continue

        print(f"\n--- FILE: {path} ---")
        diffs = []
        for key in ['lang', 'exports', 'deps', 'dependents', 'side_effects']:
            gen_val = set(gen_file.get(key, []))
            gold_val = set(gold_file.get(key, []))

            # Normalize for comparison
            if key == 'deps':
                 # Golden sample has .py extensions, analyzer might strip them
                 gold_val = {d.replace('.py', '') for d in gold_val}
                 gen_val = {d.replace('.py', '') for d in gen_val}


            if gen_val != gold_val:
                added = gen_val - gold_val
                removed = gold_val - gen_val
                diff_str = f"  - {key.upper()}: "
                if added:
                    diff_str += f"Script found: {sorted(list(added))}. "
                if removed:
                    diff_str += f"Golden has: {sorted(list(removed))}"
                diffs.append(diff_str)

        if not diffs:
            print("  ✅ OK")
        else:
            for d in diffs:
                print(d)


# --- AI Enrichment ---

def get_ai_role(client, file_data, full_map):
    """Generates a high-level role for a file using the Gemini API."""
    # Construct the detailed prompt
    prompt = f"Analyze the following file's data to determine its architectural role in the project. " \
             f"Provide a concise, one-sentence description of its primary responsibility.\n\n"

    prompt += f"File Path: {file_data['path']}\n"
    prompt += f"Language: {file_data['lang']}\n"
    prompt += f"Exports: {file_data['exports'] if file_data['exports'] else 'None'}\n"
    prompt += f"Side Effects: {file_data['side_effects'] if file_data['side_effects'] else 'None'}\n\n"

    prompt += "This file is used by (dependents):\n"
    if file_data['dependents']:
        for dep_path in file_data['dependents']:
            prompt += f"- {dep_path}\n"
    else:
        prompt += "- None\n"

    prompt += "\nThis file uses (dependencies):\n"
    if file_data['deps']:
        for dep_name in file_data['deps']:
            # Find the full path for internal dependencies
            dep_path = next((path for path in full_map if path.endswith(dep_name)), dep_name)
            prompt += f"- {dep_path}\n"
    else:
        prompt += "- None\n"

    prompt += "\nBased on this context, what is the file's role?"

    retries = 3
    delay = 5  # Initial delay in seconds

    for i in range(retries):
        try:
            response = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=prompt
            )
            return response.text.strip()
        except Exception as e:
            error_message = str(e)
            if "RESOURCE_EXHAUSTED" in error_message:
                # Extract retry delay from the error message if available
                delay_match = re.search(r"retryDelay': '(\d+)s'", error_message)
                if delay_match:
                    wait_time = int(delay_match.group(1)) + random.uniform(0, 1)
                    print(f"    - Rate limit hit. Retrying in {wait_time:.2f} seconds...")
                    time.sleep(wait_time)
                else:
                    # Fallback to exponential backoff
                    wait_time = delay * (2 ** i) + random.uniform(0, 1)
                    print(f"    - Rate limit hit. Retrying in {wait_time:.2f} seconds...")
                    time.sleep(wait_time)
            else:
                return f"Error generating role: {e}"
    return "Error: Max retries exceeded."

def format_as_map_txt(project_info, file_map):
    """Formats the final map into the map.txt structure."""
    output = f"project: {project_info.get('project', 'Unknown')}\n"
    output += f"description: {project_info.get('description', 'N/A')}\n"
    output += "roots:\n"
    for name, path in project_info.get('roots', {}).items():
        output += f"  {name}: {path}\n"
    output += "files:\n"

    for path, data in sorted(file_map.items()):
        output += f"  - path: {path}\n"
        output += f"    lang: {data['lang']}\n"
        output += f"    role: {data['role']}\n"
        output += f"    exports: {data['exports']}\n"
        output += f"    deps: {data['deps']}\n"
        output += f"    dependents: {data['dependents']}\n"
        output += f"    side_effects: {data['side_effects']}\n"

    return output

if __name__ == "__main__":
    # 1. Configure API Key
    load_dotenv()
    api_key = os.getenv("GEMINI_API_KEY2")
    if not api_key:
        print("Error: GEMINI_API_KEY environment variable not set.")
        exit(1)
    
    # Print partial key for verification
    print(f"Using Gemini API Key: {api_key[:5]}...{api_key[-4:]}")

    client = genai.Client(api_key=api_key)

    # 2. Scan codebase to get the basic structure and dependency graph
    print("Scanning codebase...")
    generated_map = scan_codebase()

    # 3. Enrich the map with AI-generated roles
    print("Enriching map with AI-generated roles... (This may take a moment)")
    for path, data in generated_map.items():
        print(f"  - Analyzing {path}...")
        # Don't analyze the mapper script itself
        if path == 'code_mapper.py':
            data['role'] = "This script! An automated tool to scan a codebase and generate a map.txt file using static analysis and AI enrichment."
            continue
        ai_role = get_ai_role(client, data, generated_map)
        data['role'] = ai_role

    # 4. Load original project info from golden sample if it exists
    print("\nLoading project info from golden sample...")
    golden_sample = parse_golden_sample()
    project_info = {
        'project': golden_sample.get('project', 'My Project') if golden_sample else 'My Project',
        'description': golden_sample.get('description', 'An automatically generated code map.') if golden_sample else 'An automatically generated code map.',
        'roots': golden_sample.get('roots', {'root': '.'}) if golden_sample else {'root': '.'}
    }

    # 5. Format and print the final map
    final_map_output = format_as_map_txt(project_info, generated_map)

    print("\n--- Generated Code Map ---")
    print(final_map_output)

    # 6. Optionally, write to a new file
    with open("generated_map.txt", "w", encoding="utf-8") as f:
        f.write(final_map_output)
    print("\nMap has been written to generated_map.txt")