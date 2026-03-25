"""
CK Lifetime Pass
Walks the AST and annotates each block with the set of local variables
that require $dinit calls, and at which exit points they fire.

This runs before the emitter. The emitter reads the annotations and
inserts cleanup calls at the right places.

Rules:
- At end of block: fire $dinit for all dinit-able locals, reverse decl order
- At return expr: skip the returned variable (name match), fire rest in reverse
- At break/continue: fire $dinit for locals in current block only
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional
from .ast import *


@dataclass
class DInitVar:
    """A local variable that needs $dinit cleanup."""
    name:      str   # variable name
    type_name: str   # resolved struct/union type name (mangled if needed)


@dataclass 
class BlockAnnotation:
    """
    Attached to a Block node after the lifetime pass.
    Tells the emitter which variables to clean up and where.
    """
    # variables declared in this block that need $dinit, in declaration order
    dinit_vars: list[DInitVar] = field(default_factory=list)
    # defer blocks registered in this block, in registration order
    defer_stmts: list["Block"] = field(default_factory=list)
    # True if every path through this block ends with an explicit exit stmt
    # (return/break/continue). If True the emitter must NOT emit end-of-block
    # cleanup since every exit path already emitted its own cleanup.
    all_paths_exit: bool = False


# We attach annotations as a side-table keyed by block id() rather than
# mutating the AST nodes, keeping ast.py pure.
_annotations: dict[int, BlockAnnotation] = {}


def get_annotation(block: Block) -> BlockAnnotation:
    return _annotations.get(id(block), BlockAnnotation())


def annotate(prog: Program, dinit_types: dict[str, str]) -> None:
    """
    Walk the program and populate _annotations.

    dinit_types: mapping of struct/union type name → $dinit method name
                 e.g. {"vector": "delete", "Result": "delete"}
                 Built from StructDecl and TagUnionDecl nodes.
    """
    _annotations.clear()
    visitor = LifetimeVisitor(dinit_types)
    visitor.visit_program(prog)


def _block_all_paths_exit(block: "Block") -> bool:
    """
    Returns True if every control flow path through this block
    ends with a ReturnStmt, BreakStmt, or ContinueStmt.
    """
    if not block.stmts:
        return False
    return _stmt_always_exits(block.stmts[-1])


def _stmt_always_exits(stmt) -> bool:
    if isinstance(stmt, (ReturnStmt, BreakStmt, ContinueStmt)):
        return True
    if isinstance(stmt, IfStmt):
        if stmt.else_ is None:
            return False  # if without else might fall through
        return (_block_all_paths_exit(stmt.then) and
                _block_all_paths_exit(stmt.else_))
    if isinstance(stmt, Block):
        return _block_all_paths_exit(stmt)
    return False


def build_dinit_map(prog: Program) -> dict[str, str]:
    """
    Scan the program for structs/unions that have a $dinit method.
    Returns {type_name: dinit_method_name}.
    """
    result: dict[str, str] = {}
    for decl in prog.decls:
        if isinstance(decl, StructDecl):
            for method in decl.methods:
                if method.lifecycle == "dinit":
                    result[decl.name] = method.name
        elif isinstance(decl, TagUnionDecl):
            for method in decl.methods:
                if method.lifecycle == "dinit":
                    result[decl.name] = method.name
    return result


def inject_field_dinits(prog: Program) -> Program:
    """
    For any struct that contains fields with $dinit but has no $dinit of its own,
    auto-generate a $dinit that chains to the field cleanups.
    This ensures nested ownership is always correctly released.
    """
    dinit_map = build_dinit_map(prog)

    new_decls = []
    for decl in prog.decls:
        if isinstance(decl, StructDecl) and not decl.is_interface:
            # check if struct already has a $dinit
            has_dinit = any(m.lifecycle == "dinit" for m in decl.methods)
            if not has_dinit:
                # find fields whose types have $dinit
                dinit_fields = [
                    f for f in decl.fields
                    if not f.type.pointer and not f.type.ref
                    and f.type.name in dinit_map
                ]
                if dinit_fields:
                    # auto-generate $dinit
                    stmts = []
                    for f in dinit_fields:
                        method_name = dinit_map[f.type.name]
                        fn_call = f"{f.type.name}_{method_name}"
                        # emit: TypeName_delete(&self->field);
                        stmts.append(ExprStmt(
                            expr=Call(
                                callee=Ident(name=fn_call, line=decl.line),
                                args=[UnaryOp(
                                    op="&",
                                    operand=FieldAccess(
                                        receiver=SelfExpr(line=decl.line),
                                        field=f.name, line=decl.line),
                                    prefix=True, line=decl.line)],
                                line=decl.line),
                            line=decl.line))
                    auto_dinit = FnDecl(
                        name="delete",
                        params=[],
                        return_type=TypeName(name="void"),
                        body=Block(stmts=stmts, line=decl.line),
                        lifecycle="dinit",
                        template_params=[],
                        line=decl.line,
                    )
                    new_methods = list(decl.methods) + [auto_dinit]
                    decl = StructDecl(
                        name=decl.name, fields=decl.fields,
                        methods=new_methods,
                        template_params=decl.template_params,
                        is_interface=decl.is_interface,
                        is_union=getattr(decl, 'is_union', False),
                        implements=decl.implements,
                        line=decl.line,
                    )
        new_decls.append(decl)
    return Program(decls=new_decls, filename=prog.filename)


class LifetimeVisitor:
    def __init__(self, dinit_types: dict[str, str]):
        self.dinit_types = dinit_types

    def visit_program(self, prog: Program) -> None:
        for decl in prog.decls:
            self._visit_decl(decl)

    def _visit_decl(self, decl) -> None:
        if isinstance(decl, FnDecl) and decl.body:
            self._visit_block(decl.body)
        elif isinstance(decl, StructDecl):
            for method in decl.methods:
                if method.body:
                    self._visit_block(method.body)
        elif isinstance(decl, TagUnionDecl):
            for method in decl.methods:
                if method.body:
                    self._visit_block(method.body)
        elif isinstance(decl, ConditionalBlock):
            for d in decl.body:
                self._visit_decl(d)

    def _visit_block(self, block: Block) -> None:
        ann = BlockAnnotation()
        _annotations[id(block)] = ann

        for stmt in block.stmts:
            self._visit_stmt(stmt, ann)

        ann.all_paths_exit = _block_all_paths_exit(block)

    def _visit_stmt(self, stmt, ann: BlockAnnotation) -> None:
        if isinstance(stmt, DeferStmt):
            ann.defer_stmts.append(stmt.body)

        elif isinstance(stmt, LetStmt):
            # only fire $dinit for owned values — not pointers or refs
            # a pointer means the caller manages lifetime
            if stmt.type.pointer or stmt.type.ref:
                pass
            else:
                type_name = stmt.type.name
                if type_name in self.dinit_types:
                    ann.dinit_vars.append(DInitVar(name=stmt.name, type_name=type_name))
            # recurse into initializer expr if it contains blocks (unlikely but possible)

        elif isinstance(stmt, IfStmt):
            self._visit_block(stmt.then)
            if stmt.else_:
                self._visit_block(stmt.else_)

        elif isinstance(stmt, ForStmt):
            self._visit_block(stmt.body)

        elif isinstance(stmt, WhileStmt):
            self._visit_block(stmt.body)

        elif isinstance(stmt, Block):
            self._visit_block(stmt)

        elif isinstance(stmt, TagSwitchStmt):
            for case in stmt.cases:
                self._visit_block(case.body)
        elif isinstance(stmt, SwitchStmt):
            for case in stmt.cases:
                # SwitchCase body is a list of stmts, not a Block
                for s in case.body:
                    self._visit_stmt(s, ann)
