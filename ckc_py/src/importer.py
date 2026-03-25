"""
CK Import Resolver
Resolves $import declarations, parses imported files, and merges their
declarations into the importing program before monomorphization.

Resolution order:
1. Path relative to the importing file's directory
2. Path relative to each directory in search_paths (for std/)

Selective imports: $import "std/vector.ck" (vector)
  — only merges the named symbols, discards the rest.

Circular imports are a compile error.
"""

from __future__ import annotations
import os
from .lexer  import tokenize, LexError
from .parser import parse,    ParseError
from .ast    import *


class ImportError(Exception):
    def __init__(self, msg: str, line: int = 0):
        super().__init__(f"[line {line}] ImportError: {msg}")


def resolve(prog: Program,
            source_path: str,
            search_paths: list[str],
            _visited: set[str] | None = None) -> Program:
    """
    Walk prog.decls, resolve every ImportDecl, and return a new Program
    with all imported declarations prepended (in import order) and all
    ImportDecl nodes removed.
    """
    if _visited is None:
        _visited = set()

    # canonicalize the current file so we can detect cycles
    canon = os.path.realpath(source_path)
    _visited.add(canon)

    source_dir = os.path.dirname(os.path.realpath(source_path))

    merged: list = []   # declarations in final order

    for decl in prog.decls:
        if not isinstance(decl, ImportDecl):
            merged.append(decl)
            continue

        # ── resolve the path ─────────────────────────────────────────────────
        raw_path = decl.path
        # ensure it ends in .ck
        if not raw_path.endswith(".ck"):
            raw_path = raw_path.replace(".", "/") + ".ck"

        candidate = _find_file(raw_path, source_dir, search_paths)
        if candidate is None:
            raise ImportError(
                f'Cannot find import "{decl.path}" '
                f'(searched {source_dir} and {search_paths})',
                decl.line)

        canon_imp = os.path.realpath(candidate)

        # ── circular import check ────────────────────────────────────────────
        if canon_imp == canon:
            raise ImportError(f'File imports itself: "{decl.path}"', decl.line)
        if canon_imp in _visited:
            raise ImportError(
                f'Circular import detected: "{decl.path}"', decl.line)

        # ── parse the imported file ──────────────────────────────────────────
        try:
            source = open(candidate, encoding="utf-8").read()
        except OSError as e:
            raise ImportError(str(e), decl.line)

        try:
            tokens   = tokenize(source, filename=candidate)
            imp_prog = parse(tokens, filename=candidate,
                             search_paths=search_paths)
        except (LexError, ParseError) as e:
            raise ImportError(f'In "{candidate}": {e}', decl.line)

        # ── recurse — resolve imports inside the imported file ───────────────
        # We need to separate transitive imports from the file's own declarations
        # so selective filtering only applies to the file's own symbols.
        # Split: decls that came from sub-imports vs decls defined in this file.
        own_decl_names = {_decl_name(d) for d in imp_prog.decls if _decl_name(d)}
        imp_prog = resolve(imp_prog, candidate, search_paths,
                           _visited=set(_visited))

        # transitive = decls added by sub-imports (not defined in this file)
        transitive = [d for d in imp_prog.decls
                      if _decl_name(d) not in own_decl_names]
        direct     = [d for d in imp_prog.decls
                      if _decl_name(d) in own_decl_names or _decl_name(d) is None]

        # ── filter by selective import list (only direct symbols) ─────────────
        filtered_direct = _filter(direct, decl.symbols)

        # transitive deps always come through — they're needed by the selected symbols
        imp_decls = transitive + filtered_direct

        # prepend imported declarations before the current declaration
        merged = _merge(merged, imp_decls)

    return Program(decls=merged, filename=prog.filename)


# ── helpers ───────────────────────────────────────────────────────────────────

def _find_file(raw_path: str,
               source_dir: str,
               search_paths: list[str]) -> str | None:
    """
    Try candidates in order:
    1. raw_path relative to source_dir  (local imports)
    2. raw_path relative to each search_path  (e.g. "std/vector.ck" → <ckdir>/std/vector.ck)
    3. basename of raw_path relative to each search_path
       (e.g. "std/vector.ck" with search_path=".../std" → ".../std/vector.ck")
    """
    candidates = [
        os.path.join(source_dir, raw_path),
    ]
    for sp in search_paths:
        # full path: search_path / raw_path  (works when raw_path = "vector.ck")
        candidates.append(os.path.join(sp, raw_path))
        # strip leading dir component from raw_path so "std/vector.ck"
        # resolves against a search_path that IS the std directory
        basename = os.path.basename(raw_path)
        candidates.append(os.path.join(sp, basename))
        # also try raw_path with the first component stripped
        parts = raw_path.replace("\\", "/").split("/")
        if len(parts) > 1:
            candidates.append(os.path.join(sp, *parts[1:]))
    for c in candidates:
        if os.path.isfile(c):
            return c
    return None


def _decl_name(d) -> str | None:
    """Return the primary name of a declaration, or None if it has none."""
    if isinstance(d, (StructDecl, TagUnionDecl)):
        return d.name
    if isinstance(d, FnDecl):
        return d.name
    if isinstance(d, ConstExprDecl):
        return d.name
    if isinstance(d, ImportDecl):
        return None  # already resolved
    if isinstance(d, EnumDecl):
        return d.name
    if isinstance(d, TypeAlias):
        return d.name
    return None


def _filter(decls: list, symbols: list[str]) -> list:
    """
    If symbols is empty, return all decls.
    Otherwise return only decls whose name is in symbols.
    Always include ImportDecl nodes (already resolved, pass-through).
    """
    if not symbols:
        return list(decls)
    symbol_set = set(symbols)
    result = []
    for d in decls:
        name = _decl_name(d)
        if name is None or name in symbol_set:
            result.append(d)
    return result


def _merge(existing: list, incoming: list) -> list:
    """
    Prepend incoming declarations to existing, skipping any whose name
    is already present (first definition wins — avoid duplicates when
    multiple files import the same dependency).
    IncludeDecl are deduplicated by path.
    """
    existing_names = {_decl_name(d) for d in existing if _decl_name(d)}
    existing_includes = {d.path for d in existing if isinstance(d, IncludeDecl)}
    result = []
    for d in incoming:
        if isinstance(d, IncludeDecl):
            if d.path not in existing_includes:
                existing_includes.add(d.path)
                result.append(d)
        elif _decl_name(d) not in existing_names:
            result.append(d)
    return result + existing
