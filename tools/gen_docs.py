#!/usr/bin/env python3
"""
Generate structure docs from the source tree.

Hand-drawn class diagrams rot on every refactor — docs/images/Class_diagram.png
was roughly half wrong within six months. Anything this script emits is derived
from the AST instead, so it is either correct or regenerated.

    python tools/gen_docs.py

Writes Mermaid diagrams to docs/generated/. Stdlib only, no network, no LLM.
Do not hand-edit the output; edit the code or this script.
"""
from __future__ import annotations

import ast
import os
import sys
from datetime import date

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(ROOT, 'docs', 'generated')

# Package directories to document (skip tests, vendored JS, the C++ extension).
PACKAGES = ['analysis', 'core', 'data', 'gui', 'interface', 'strategies']

MAX_MEMBERS = 12  # per class, to keep diagrams legible


def iter_python_files():
    for pkg in PACKAGES:
        pkg_dir = os.path.join(ROOT, pkg)
        for dirpath, dirnames, filenames in os.walk(pkg_dir):
            dirnames[:] = [d for d in dirnames if d != '__pycache__']
            for fn in sorted(filenames):
                if fn.endswith('.py'):
                    yield os.path.join(dirpath, fn)


def rel(path):
    return os.path.relpath(path, ROOT).replace('\\', '/')


def module_name(path):
    return rel(path)[:-3].replace('/', '.').removesuffix('.__init__')


def base_name(node):
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def init_attributes(cls):
    """Names assigned to self.* inside __init__."""
    attrs = []
    for item in cls.body:
        if not (isinstance(item, ast.FunctionDef) and item.name == '__init__'):
            continue
        for sub in ast.walk(item):
            targets = []
            if isinstance(sub, ast.Assign):
                targets = sub.targets
            elif isinstance(sub, ast.AnnAssign):
                targets = [sub.target]
            for t in targets:
                if (isinstance(t, ast.Attribute)
                        and isinstance(t.value, ast.Name)
                        and t.value.id == 'self'
                        and not t.attr.startswith('_')
                        and t.attr not in attrs):
                    attrs.append(t.attr)
    return attrs


def signature(fn):
    args = [a.arg for a in fn.args.args if a.arg not in ('self', 'cls')]
    if fn.args.vararg:
        args.append('*' + fn.args.vararg.arg)
    if fn.args.kwarg:
        args.append('**' + fn.args.kwarg.arg)
    return f"{fn.name}({', '.join(args)})"


def collect():
    classes, edges, imports = [], [], []

    for path in iter_python_files():
        try:
            with open(path, 'r', encoding='utf-8') as f:
                tree = ast.parse(f.read(), filename=path)
        except (SyntaxError, UnicodeDecodeError) as e:
            print(f"  skip {rel(path)}: {e}", file=sys.stderr)
            continue

        mod = module_name(path)

        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                head = node.module.split('.')[0]
                if head in PACKAGES and head != mod.split('.')[0]:
                    edge = (mod.split('.')[0], head)
                    if edge not in imports:
                        imports.append(edge)

        for node in tree.body:
            if not isinstance(node, ast.ClassDef):
                continue

            methods, is_abstract = [], False
            for item in node.body:
                if not isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                decorators = {base_name(d) for d in item.decorator_list}
                if 'abstractmethod' in decorators:
                    is_abstract = True
                if item.name.startswith('_') and item.name != '__init__':
                    continue
                if item.name == '__init__':
                    continue
                methods.append(signature(item))

            bases = [b for b in (base_name(b) for b in node.bases) if b]
            if 'ABC' in bases:
                is_abstract = True

            classes.append({
                'name': node.name,
                'module': mod,
                'bases': bases,
                'methods': methods,
                'attrs': init_attributes(node),
                'abstract': is_abstract,
            })
            for b in bases:
                edges.append((b, node.name))

    return classes, edges, imports


def mermaid_classes(classes, edges):
    known = {c['name'] for c in classes}
    by_module = {}
    for c in classes:
        by_module.setdefault(c['module'], []).append(c)

    lines = ['```mermaid', 'classDiagram']

    for mod in sorted(by_module):
        for c in sorted(by_module[mod], key=lambda x: x['name']):
            members = []
            for a in c['attrs'][:MAX_MEMBERS]:
                members.append(f"    +{a}")
            room = MAX_MEMBERS - len(members)
            for m in c['methods'][:max(room, 0)]:
                members.append(f"    +{m}")

            hidden = (len(c['attrs']) + len(c['methods'])) - len(members)
            if hidden > 0:
                members.append(f"    +{hidden} more...")

            lines.append(f"    class {c['name']} {{")
            if c['abstract']:
                lines.append("    <<abstract>>")
            lines.extend(members or ["    "])
            lines.append("    }")

    for base, child in sorted(set(edges)):
        if base in known:
            lines.append(f"    {base} <|-- {child}")

    lines.append('```')
    return '\n'.join(lines)


def mermaid_modules(imports):
    lines = ['```mermaid', 'flowchart LR']
    for pkg in PACKAGES:
        lines.append(f"    {pkg}[{pkg}/]")
    for src, dst in sorted(set(imports)):
        lines.append(f"    {src} --> {dst}")
    lines.append('```')
    return '\n'.join(lines)


HEADER = """<!-- GENERATED FILE — DO NOT EDIT BY HAND -->
<!-- Regenerate with: python tools/gen_docs.py -->

*Generated {stamp} from the source tree. Any hand edit will be overwritten.*
"""


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    classes, edges, imports = collect()
    stamp = date.today().isoformat()

    class_doc = os.path.join(OUT_DIR, 'CLASS_DIAGRAM.md')
    with open(class_doc, 'w', encoding='utf-8') as f:
        f.write(HEADER.format(stamp=stamp))
        f.write('\n# Class Diagram (generated)\n\n')
        f.write(mermaid_classes(classes, edges))
        f.write('\n\n## Classes by module\n\n')
        f.write('| Module | Class | Bases |\n|---|---|---|\n')
        for c in sorted(classes, key=lambda x: (x['module'], x['name'])):
            bases = ', '.join(c['bases']) or '—'
            f.write(f"| `{c['module']}` | `{c['name']}` | {bases} |\n")

    mod_doc = os.path.join(OUT_DIR, 'MODULE_GRAPH.md')
    with open(mod_doc, 'w', encoding='utf-8') as f:
        f.write(HEADER.format(stamp=stamp))
        f.write('\n# Module Dependencies (generated)\n\n')
        f.write(mermaid_modules(imports))
        f.write('\n')

    print(f"{len(classes)} classes, {len(set(imports))} package edges")
    print(f"  {rel(class_doc)}")
    print(f"  {rel(mod_doc)}")


if __name__ == '__main__':
    main()
