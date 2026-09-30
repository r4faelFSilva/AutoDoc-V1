"""Mapa de código determinístico — zero custo de token, precisão de parser.

Extrai símbolos, rotas HTTP, variáveis de ambiente e grafo de imports:
- Python: módulo `ast` (parser real).
- JS/TS: heurísticas por regex (funções, classes, rotas Express/Nest, imports).

É a fonte de fatos usada pelo nó `verify` do documentador profundo (e, nas
próximas fases, pelo agente arquiteto para engenharia reversa).
"""

from __future__ import annotations

import ast
import re
from collections import Counter
from dataclasses import dataclass, field

PY_SUFFIXES = (".py",)
JS_SUFFIXES = (".js", ".jsx", ".ts", ".tsx")

_HTTP_METHODS = {"get", "post", "put", "patch", "delete", "head", "options"}


@dataclass
class Symbol:
    kind: str  # function | class | method
    name: str
    signature: str
    line: int


@dataclass
class Route:
    method: str
    path: str
    file: str
    handler: str


@dataclass
class FileMap:
    path: str
    language: str
    symbols: list[Symbol] = field(default_factory=list)
    imports: list[str] = field(default_factory=list)


@dataclass
class CodeMap:
    files: list[FileMap] = field(default_factory=list)
    routes: list[Route] = field(default_factory=list)
    env_vars: set[str] = field(default_factory=set)
    # arestas internas arquivo -> arquivo (resolvidas a partir dos imports)
    edges: list[tuple[str, str]] = field(default_factory=list)
    languages: Counter = field(default_factory=Counter)

    def summary_text(self, *, max_files: int = 120) -> str:
        """Resumo compacto para prompts de outline/draft."""
        lines: list[str] = []
        langs = ", ".join(f"{k} ({v})" for k, v in self.languages.most_common())
        lines.append(f"Linguagens: {langs or 'desconhecidas'}")
        if self.routes:
            lines.append("\nRotas HTTP detectadas:")
            for r in self.routes[:60]:
                lines.append(f"- {r.method.upper()} {r.path}  ({r.file} :: {r.handler})")
        if self.env_vars:
            lines.append("\nVariáveis de ambiente usadas: " + ", ".join(sorted(self.env_vars)[:40]))
        lines.append("\nArquivos e símbolos:")
        for f in self.files[:max_files]:
            syms = ", ".join(s.name for s in f.symbols[:12])
            lines.append(f"- {f.path}" + (f" → {syms}" if syms else ""))
        return "\n".join(lines)

    def facts_text(self) -> str:
        """Fatos verificáveis para o nó verify — nomes exatos, sem prosa."""
        lines = ["FATOS EXTRAÍDOS DO CÓDIGO (fonte da verdade):"]
        lines.append(
            "Rotas existentes: "
            + ("; ".join(f"{r.method.upper()} {r.path}" for r in self.routes) or "nenhuma detectada")
        )
        lines.append(
            "Variáveis de ambiente existentes: " + (", ".join(sorted(self.env_vars)) or "nenhuma detectada")
        )
        all_symbols = [f"{s.name} ({f.path})" for f in self.files for s in f.symbols]
        lines.append("Símbolos existentes: " + ("; ".join(all_symbols[:250]) or "nenhum detectado"))
        return "\n".join(lines)

    def mermaid_dependencies(self, *, max_edges: int = 40) -> str | None:
        if not self.edges:
            return None
        def node_id(path: str) -> str:
            return re.sub(r"[^a-zA-Z0-9]", "_", path)
        seen: set[tuple[str, str]] = set()
        lines = ["graph LR"]
        for src, dst in self.edges:
            if (src, dst) in seen or src == dst:
                continue
            seen.add((src, dst))
            lines.append(f'    {node_id(src)}["{src}"] --> {node_id(dst)}["{dst}"]')
            if len(seen) >= max_edges:
                break
        return "\n".join(lines) if len(lines) > 1 else None


def build_code_map(files: list[tuple[str, str]]) -> CodeMap:
    cmap = CodeMap()
    for path, content in files:
        lower = path.lower()
        if lower.endswith(PY_SUFFIXES):
            fm = _parse_python(path, content, cmap)
            cmap.languages["python"] += 1
        elif lower.endswith(JS_SUFFIXES):
            fm = _parse_js_ts(path, content, cmap)
            cmap.languages["ts/js"] += 1
        else:
            continue
        cmap.files.append(fm)
    _resolve_edges(cmap)
    return cmap


# ---------------------------------------------------------------- Python

def _format_args(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    return ", ".join(a.arg for a in node.args.args)


def _parse_python(path: str, content: str, cmap: CodeMap) -> FileMap:
    fm = FileMap(path=path, language="python")
    try:
        tree = ast.parse(content)
    except SyntaxError:
        return fm

    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            if isinstance(node, ast.Import):
                fm.imports.extend(a.name for a in node.names)
            elif node.module:
                fm.imports.append(node.module)
                # `from pacote import modulo` — o alvo pode ser o submódulo
                fm.imports.extend(f"{node.module}.{a.name}" for a in node.names)

    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            fm.symbols.append(
                Symbol("function", node.name, f"{node.name}({_format_args(node)})", node.lineno)
            )
            _extract_route(node, path, cmap)
        elif isinstance(node, ast.ClassDef):
            fm.symbols.append(Symbol("class", node.name, f"class {node.name}", node.lineno))
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    fm.symbols.append(
                        Symbol(
                            "method",
                            f"{node.name}.{item.name}",
                            f"{node.name}.{item.name}({_format_args(item)})",
                            item.lineno,
                        )
                    )
                    _extract_route(item, path, cmap)

    for m in re.finditer(r"os\.(?:environ(?:\.get)?[\[\(]|getenv\()\s*['\"](\w+)['\"]", content):
        cmap.env_vars.add(m.group(1))
    return fm


def _extract_route(node: ast.FunctionDef | ast.AsyncFunctionDef, path: str, cmap: CodeMap) -> None:
    for dec in node.decorator_list:
        if not isinstance(dec, ast.Call):
            continue
        func = dec.func
        if isinstance(func, ast.Attribute) and func.attr in _HTTP_METHODS:
            if dec.args and isinstance(dec.args[0], ast.Constant) and isinstance(dec.args[0].value, str):
                cmap.routes.append(Route(func.attr, dec.args[0].value, path, node.name))


# ---------------------------------------------------------------- JS / TS

_JS_FUNC = re.compile(r"(?:export\s+)?(?:async\s+)?function\s+(\w+)\s*\(([^)]*)\)")
_JS_ARROW = re.compile(r"(?:export\s+)?const\s+(\w+)\s*=\s*(?:async\s*)?\(([^)]*)\)\s*(?::[^=]*)?=>")
_JS_CLASS = re.compile(r"(?:export\s+)?class\s+(\w+)")
_JS_ROUTE = re.compile(r"\b(?:app|router|server)\.(get|post|put|patch|delete)\s*\(\s*['\"`]([^'\"`]+)['\"`]")
_JS_IMPORT = re.compile(r"import\s+(?:[^'\"]*?\s+from\s+)?['\"]([^'\"]+)['\"]")
_JS_ENV = re.compile(r"process\.env\.(\w+)")


def _parse_js_ts(path: str, content: str, cmap: CodeMap) -> FileMap:
    fm = FileMap(path=path, language="ts/js")
    for regex, kind in ((_JS_FUNC, "function"), (_JS_ARROW, "function"), (_JS_CLASS, "class")):
        for m in regex.finditer(content):
            line = content.count("\n", 0, m.start()) + 1
            args = m.group(2) if regex is not _JS_CLASS and m.lastindex and m.lastindex >= 2 else ""
            name = m.group(1)
            sig = f"{name}({args.strip()})" if kind == "function" else f"class {name}"
            fm.symbols.append(Symbol(kind, name, sig, line))
    for m in _JS_ROUTE.finditer(content):
        cmap.routes.append(Route(m.group(1), m.group(2), path, "?"))
    fm.imports.extend(m.group(1) for m in _JS_IMPORT.finditer(content))
    for m in _JS_ENV.finditer(content):
        cmap.env_vars.add(m.group(1))
    return fm


# ---------------------------------------------------------------- Grafo

def _resolve_edges(cmap: CodeMap) -> None:
    """Resolve imports para arquivos internos do próprio projeto (heurística)."""
    by_module: dict[str, str] = {}
    for f in cmap.files:
        # app/services/x.py → chaves "app.services.x", "services.x", "x"
        no_ext = re.sub(r"\.(py|jsx?|tsx?)$", "", f.path)
        dotted = no_ext.replace("/", ".")
        parts = dotted.split(".")
        for i in range(len(parts)):
            by_module.setdefault(".".join(parts[i:]), f.path)

    for f in cmap.files:
        for imp in f.imports:
            key = imp.lstrip("./").replace("/", ".")
            target = by_module.get(key)
            if target and target != f.path:
                cmap.edges.append((f.path, target))
