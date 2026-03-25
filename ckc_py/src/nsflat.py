"""
CK Namespace Flattener
Converts NamespaceDecl nodes into flat, prefixed top-level declarations.

  namespace math { fn abs(...) }  →  fn math_abs(...)
  namespace std  { struct Vec2 }  →  struct std_Vec2

Runs after import resolution and $if evaluation, before monomorphization.
All NamespaceDecl nodes are eliminated — the output contains only flat decls.
"""

from __future__ import annotations
import copy
from .ast import *


def flatten(prog: Program) -> Program:
    """Flatten all namespaces in the program."""
    new_decls = _flatten_decls(prog.decls, prefix="")
    return Program(decls=new_decls, filename=prog.filename)


def _flatten_decls(decls: list, prefix: str) -> list:
    result = []
    for d in decls:
        if isinstance(d, NamespaceDecl):
            ns_prefix = f"{prefix}{d.name}_" if prefix else f"{d.name}_"
            result.extend(_flatten_decls(d.decls, prefix=ns_prefix))
        else:
            if prefix:
                result.append(_prefix_decl(d, prefix))
            else:
                result.append(d)
    return result


def _prefix_decl(d, prefix: str):
    """Rename the declaration's primary name with the given prefix."""
    if isinstance(d, FnDecl):
        return FnDecl(
            name=f"{prefix}{d.name}",
            params=d.params,
            return_type=d.return_type,
            body=d.body,
            lifecycle=d.lifecycle,
            template_params=d.template_params,
            operator=d.operator,
            line=d.line,
        )
    if isinstance(d, StructDecl):
        new_name = f"{prefix}{d.name}"
        # fix Self references in methods
        new_methods = [_fix_self_in_fn(m, d.name, new_name) for m in d.methods]
        return StructDecl(
            name=new_name,
            fields=d.fields,
            methods=new_methods,
            template_params=d.template_params,
            is_interface=d.is_interface,
            is_union=getattr(d, 'is_union', False),
            implements=d.implements,
            line=d.line,
        )
    if isinstance(d, TagUnionDecl):
        new_name = f"{prefix}{d.name}"
        return TagUnionDecl(
            name=new_name,
            variants=d.variants,
            methods=d.methods,
            template_params=d.template_params,
            template_base=d.template_base,
            line=d.line,
        )
    if isinstance(d, EnumDecl):
        return EnumDecl(
            name=f"{prefix}{d.name}",
            variants=d.variants,
            line=d.line,
        )
    if isinstance(d, TypeAlias):
        return TypeAlias(
            name=f"{prefix}{d.name}",
            type=d.type,
            line=d.line,
        )
    if isinstance(d, ConstExprDecl):
        return ConstExprDecl(
            name=f"{prefix}{d.name}",
            type=d.type,
            value=d.value,
            line=d.line,
        )
    # ImportDecl, ConditionalBlock — pass through unchanged
    return d


def _fix_self_in_fn(fn: FnDecl, old_name: str, new_name: str) -> FnDecl:
    """Replace Self type references in a method after struct rename."""
    if fn.return_type.name == "Self":
        # Self is resolved by the emitter, no fix needed
        pass
    return fn
