"""
CK Compile-time Conditional Evaluator
Resolves $if blocks by evaluating their conditions against a build config,
keeping matching blocks and discarding non-matching ones.

Runs after import resolution, before monomorphization.

Supported conditions:
    target.os == "linux"       target.os != "windows"
    target.arch == "x86_64"   target.arch != "aarch64"
    build.debug                !build.debug
    build.opt == "speed"
"""

from __future__ import annotations
from dataclasses import dataclass
from .ast import *


class CondError(Exception):
    def __init__(self, msg: str, line: int = 0):
        super().__init__(f"[line {line}] CondError: {msg}")


@dataclass
class BuildConfig:
    os:    str  = "linux"      # linux | windows | macos | freestanding
    arch:  str  = "x86_64"    # x86_64 | aarch64 | riscv64 | wasm32
    debug: bool = False
    opt:   str  = "none"       # none | size | speed

    @staticmethod
    def from_args(args) -> "BuildConfig":
        return BuildConfig(
            os    = getattr(args, "target_os",   "linux"),
            arch  = getattr(args, "target_arch", "x86_64"),
            debug = getattr(args, "debug",       False),
            opt   = getattr(args, "opt",         "none"),
        )


def evaluate(prog: Program, cfg: BuildConfig) -> Program:
    """
    Walk the program, evaluate all ConditionalBlock nodes at both
    declaration level and inside function bodies.
    """
    new_decls = _resolve_decls(prog.decls, cfg)
    # also resolve $if inside function bodies
    final = []
    for d in new_decls:
        final.append(_resolve_fn_bodies(d, cfg))
    return Program(decls=final, filename=prog.filename)


def _resolve_fn_bodies(d, cfg: BuildConfig):
    """Recursively resolve $if inside function and method bodies."""
    if isinstance(d, FnDecl) and d.body:
        new_body = Block(stmts=_resolve_stmts(d.body.stmts, cfg), line=d.body.line)
        return FnDecl(name=d.name, params=d.params, return_type=d.return_type,
                      body=new_body, lifecycle=d.lifecycle,
                      template_params=d.template_params, operator=d.operator,
                      line=d.line)
    if isinstance(d, StructDecl):
        new_methods = [_resolve_fn_bodies(m, cfg) for m in d.methods]
        return StructDecl(name=d.name, fields=d.fields, methods=new_methods,
                          template_params=d.template_params,
                          is_interface=d.is_interface,
                          is_union=getattr(d, 'is_union', False),
                          implements=d.implements, line=d.line)
    if isinstance(d, TagUnionDecl):
        new_methods = [_resolve_fn_bodies(m, cfg) for m in d.methods]
        return TagUnionDecl(name=d.name, variants=d.variants, methods=new_methods,
                            template_params=d.template_params, line=d.line)
    return d


def _resolve_decls(decls: list, cfg: BuildConfig) -> list:
    result = []
    for d in decls:
        if isinstance(d, ConditionalBlock):
            if _eval_condition(d.condition, cfg, d.line):
                result.extend(_resolve_decls(d.body, cfg))
        else:
            result.append(d)
    return result


def _resolve_stmts(stmts: list, cfg: BuildConfig) -> list:
    """Resolve $if blocks inside function bodies."""
    result = []
    for s in stmts:
        if isinstance(s, ConditionalBlock):
            if _eval_condition(s.condition, cfg, s.line):
                # body is a list containing a single Block
                for item in s.body:
                    if isinstance(item, Block):
                        result.extend(_resolve_stmts(item.stmts, cfg))
                    else:
                        result.append(item)
        elif isinstance(s, Block):
            result.append(Block(stmts=_resolve_stmts(s.stmts, cfg), line=s.line))
        elif isinstance(s, IfStmt):
            result.append(IfStmt(
                cond=s.cond,
                then=Block(stmts=_resolve_stmts(s.then.stmts, cfg), line=s.then.line),
                else_=Block(stmts=_resolve_stmts(s.else_.stmts, cfg), line=s.else_.line)
                      if s.else_ else None,
                line=s.line))
        elif isinstance(s, ForStmt):
            result.append(ForStmt(init=s.init, cond=s.cond, post=s.post,
                                  body=Block(stmts=_resolve_stmts(s.body.stmts, cfg),
                                             line=s.body.line),
                                  line=s.line))
        elif isinstance(s, WhileStmt):
            result.append(WhileStmt(cond=s.cond,
                                    body=Block(stmts=_resolve_stmts(s.body.stmts, cfg),
                                               line=s.body.line),
                                    line=s.line))
        elif isinstance(s, SwitchStmt):
            result.append(SwitchStmt(
                expr=s.expr,
                cases=[SwitchCase(
                    value=c.value,
                    body=_resolve_stmts(c.body, cfg),
                    line=c.line,
                ) for c in s.cases],
                line=s.line))
        elif isinstance(s, DeferStmt):
            result.append(DeferStmt(
                body=Block(stmts=_resolve_stmts(s.body.stmts, cfg), line=s.body.line),
                line=s.line))
        elif isinstance(s, DInitCallStmt):
            result.append(s)
        else:
            result.append(s)
    return result


def _eval_condition(expr, cfg: BuildConfig, line: int) -> bool:
    """Evaluate a compile-time condition expression to bool."""

    # bare bool: $if (build.debug)
    if isinstance(expr, FieldAccess):
        return _eval_field(expr, cfg, line)

    # !expr
    if isinstance(expr, UnaryOp) and expr.op == "!":
        return not _eval_condition(expr.operand, cfg, line)

    # expr == "value"  or  expr != "value"
    if isinstance(expr, BinOp):
        if expr.op in ("==", "!="):
            left_val  = _eval_value(expr.left,  cfg, line)
            right_val = _eval_value(expr.right, cfg, line)
            result = (left_val == right_val)
            return result if expr.op == "==" else not result

        if expr.op == "&&":
            return (_eval_condition(expr.left, cfg, line) and
                    _eval_condition(expr.right, cfg, line))

        if expr.op == "||":
            return (_eval_condition(expr.left, cfg, line) or
                    _eval_condition(expr.right, cfg, line))

    raise CondError(
        f"Unsupported $if condition: {type(expr).__name__}. "
        f"Use target.os, target.arch, build.debug, build.opt", line)


def _eval_value(expr, cfg: BuildConfig, line: int):
    """Evaluate an expression to a scalar value for comparison."""
    if isinstance(expr, StringLit):
        return expr.value
    if isinstance(expr, BoolLit):
        return expr.value
    if isinstance(expr, FieldAccess):
        return _eval_field(expr, cfg, line)
    if isinstance(expr, Ident):
        # bare ident — try as a bool config key
        if expr.name == "true":  return True
        if expr.name == "false": return False
    raise CondError(
        f"Cannot evaluate '{_expr_str(expr)}' as a compile-time value", line)


def _eval_field(expr: FieldAccess, cfg: BuildConfig, line: int):
    """Evaluate a field access like target.os or build.debug."""
    if not isinstance(expr.receiver, Ident):
        raise CondError(
            f"Expected 'target.X' or 'build.X', got complex expression", line)

    ns = expr.receiver.name
    field = expr.field

    if ns == "target":
        if field == "os":   return cfg.os
        if field == "arch": return cfg.arch
        raise CondError(f"Unknown target field: '{field}'. Use os or arch", line)

    if ns == "build":
        if field == "debug": return cfg.debug
        if field == "opt":   return cfg.opt
        raise CondError(f"Unknown build field: '{field}'. Use debug or opt", line)

    raise CondError(
        f"Unknown namespace '{ns}'. Use 'target' or 'build'", line)


def _expr_str(expr) -> str:
    """Best-effort string repr of an expression for error messages."""
    if isinstance(expr, Ident):       return expr.name
    if isinstance(expr, StringLit):   return f'"{expr.value}"'
    if isinstance(expr, BoolLit):     return str(expr.value).lower()
    if isinstance(expr, FieldAccess): return f"{_expr_str(expr.receiver)}.{expr.field}"
    return type(expr).__name__
