"""
CK AST nodes.
Every node is a plain dataclass. No methods except __repr__.
The transpiler walks these.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional


# ── types ─────────────────────────────────────────────────────────────────────

@dataclass
class TypeName:
    """A resolved or unresolved type reference, e.g. i32, T*, FILE*&, vector(int)"""
    name:       str                        # base name: "i32", "vector", "void", etc.
    args:       list[TypeName] = field(default_factory=list)  # template args
    pointer:    bool = False               # T*
    ref:        bool = False               # T&  (non-null)
    const:      bool = False
    array_size: Optional[str] = None       # "4", "N", "BUF_SIZE" — if this is T[N]
    # function pointer: name == "__fnptr__", fn_params = param types, fn_ret = return type
    fn_params:  list[TypeName] = field(default_factory=list)
    fn_ret:     Optional[TypeName] = None

    def __repr__(self):
        s = self.name
        if self.args:
            s += f"({', '.join(repr(a) for a in self.args)})"
        if self.pointer: s += "*"
        if self.ref:     s += "&"
        if self.array_size: s += f"[{self.array_size}]"
        return s


# Sentinel TypeName for auto-deduced types
AUTO_TYPE = TypeName(name="__auto__")

# ── template parameters ───────────────────────────────────────────────────────

@dataclass
class TemplateParam:
    """$template(type T) / $template(numeric T) / $template(usize N)"""
    bound: str          # "type", "numeric", "integer", "float", "usize", or interface name
    name:  str          # parameter name, e.g. "T", "N"
    default: Optional[TypeName] = None


# ── declarations ──────────────────────────────────────────────────────────────

@dataclass
class ImportDecl:
    path:    str                     # "std/io" or "vector.ck"
    symbols: list[str]               # [] means import all
    line:    int = 0


@dataclass
class ConstExprDecl:
    name:  str
    type:  TypeName
    value: "Expr"
    line:  int = 0


@dataclass
class Param:
    type:    TypeName
    name:    str
    default: Optional["Expr"] = None


@dataclass
class FnDecl:
    name:         str
    params:       list[Param]
    return_type:  TypeName
    body:         Optional["Block"]   # None = forward declaration
    lifecycle:    Optional[str]       # "init" | "dinit" | None
    template_params: list[TemplateParam] = field(default_factory=list)
    operator:     Optional[str] = None  # "+" | "-" | "==" etc. if op overload
    line:         int = 0


@dataclass
class StructDecl:
    name:            str
    fields:          list[Param]
    methods:         list[FnDecl]
    template_params: list[TemplateParam] = field(default_factory=list)
    is_interface:    bool = False
    is_union:        bool = False   # plain C union (not $tag union)
    implements:      list[str] = field(default_factory=list)  # interface names
    allocator_param: Optional[TemplateParam] = None
    line:            int = 0


@dataclass
class IncludeDecl:
    """$include <header.h> or $include "header.h" """
    path:   str   # the raw include path including < > or " "
    line:   int = 0


@dataclass
class ExternDecl:
    """$extern { fn ...; struct ...; constexpr ...; }"""
    fns:          list["FnDecl"]        = field(default_factory=list)
    structs:      list[str]             = field(default_factory=list)  # opaque names
    full_structs: list["StructDecl"]    = field(default_factory=list)  # with fields
    consts:       list["ConstExprDecl"] = field(default_factory=list)
    line:         int = 0


@dataclass
class NamespaceDecl:
    name:  str
    decls: list["Decl"]
    line:  int = 0


@dataclass
class TypeAlias:
    name: str
    type: "TypeName"
    line: int = 0


@dataclass
class EnumVariant:
    name:  str
    value: Optional["Expr"] = None  # explicit value, e.g. North = 0


@dataclass
class EnumDecl:
    name:     str
    variants: list[EnumVariant]
    line:     int = 0


@dataclass
class TagUnionDecl:
    name:            str
    variants:        list[Param]      # each variant: name + type
    methods:         list[FnDecl]
    template_params: list[TemplateParam] = field(default_factory=list)
    template_base:   str = ""          # original template name before mangling
    line:            int = 0


@dataclass
class ConditionalBlock:
    """$if (target.os == ...) { ... }"""
    condition: "Expr"
    body:      list["Decl"]
    line:      int = 0


# ── statements ────────────────────────────────────────────────────────────────

@dataclass
class Block:
    stmts: list["Stmt"]
    line:  int = 0


@dataclass
class ReturnStmt:
    value: Optional["Expr"]
    line:  int = 0


@dataclass
class LetStmt:
    type:  TypeName
    name:  str
    value: Optional["Expr"]
    line:  int = 0


@dataclass
class ExprStmt:
    expr: "Expr"
    line: int = 0


@dataclass
class IfStmt:
    cond:      "Expr"
    then:      Block
    else_:     Optional[Block]
    line:      int = 0


@dataclass
class ForStmt:
    init:   Optional["Stmt"]
    cond:   Optional["Expr"]
    post:   Optional["Expr"]
    body:   Block
    line:   int = 0


@dataclass
class WhileStmt:
    cond: "Expr"
    body: Block
    line: int = 0


@dataclass
class BreakStmt:
    line: int = 0


@dataclass
class ContinueStmt:
    line: int = 0


@dataclass
class TagSwitchStmt:
    """$tag switch (expr) { case (Union.variant name): { ... } }"""
    expr:  "Expr"
    cases: list["TagCase"]
    line:  int = 0


@dataclass
class TagCase:
    union_name:   str
    variant_name: str
    bind_name:    str
    body:         Block
    line:         int = 0


@dataclass
class DInitCallStmt:
    """$dinit(expr) — calls the $dinit method on expr if its type has one, else no-op."""
    expr: "Expr"
    line: int = 0


@dataclass
class DeferStmt:
    body: "Block"
    line: int = 0


@dataclass
class SwitchCase:
    value: Optional["Expr"]  # None = default
    body:  list["Stmt"]
    line:  int = 0


@dataclass
class SwitchStmt:
    expr:  "Expr"
    cases: list[SwitchCase]
    line:  int = 0


@dataclass
class AssertStmt:
    expr: "Expr"
    line: int = 0


# ── expressions ───────────────────────────────────────────────────────────────

@dataclass
class IntLit:
    value: int
    line:  int = 0

@dataclass
class FloatLit:
    value: float
    line:  int = 0

@dataclass
class StringLit:
    value: str
    line:  int = 0

@dataclass
class BoolLit:
    value: bool
    line:  int = 0
@dataclass
class CharLit:
    value: str
    line: int = 0

@dataclass
class NullLit:
    line: int = 0

@dataclass
class Ident:
    name: str
    line: int = 0

@dataclass
class SelfExpr:
    line: int = 0

@dataclass
class BinOp:
    op:    str
    left:  "Expr"
    right: "Expr"
    line:  int = 0

@dataclass
class UnaryOp:
    op:      str     # "!", "-", "~", "*" (deref), "&" (address-of), "++", "--"
    operand: "Expr"
    prefix:  bool = True
    line:    int = 0

@dataclass
class Assign:
    op:    str       # "=", "+=", "-=", etc.
    left:  "Expr"
    right: "Expr"
    line:  int = 0

@dataclass
class Call:
    callee: "Expr"
    args:   list["Expr"]
    line:   int = 0

@dataclass
class MethodCall:
    receiver: "Expr"
    method:   str
    args:     list["Expr"]
    line:     int = 0

@dataclass
class FieldAccess:
    receiver: "Expr"
    field:    str
    line:     int = 0

@dataclass
class Index:
    receiver: "Expr"
    index:    "Expr"
    line:     int = 0

@dataclass
class Cast:
    type:  TypeName
    expr:  "Expr"
    line:  int = 0

@dataclass
class SizeOf:
    type:  TypeName
    line:  int = 0

@dataclass
class Ternary:
    cond:  "Expr"
    then:  "Expr"
    else_: "Expr"
    line:  int = 0

@dataclass
class StructLit:
    """{ .field = expr, ... } or { expr, expr, ... }"""
    type:   Optional[TypeName]
    fields: list[tuple[Optional[str], "Expr"]]
    line:   int = 0

@dataclass
class NullCoalesce:
    """expr ?? fallback"""
    left:  "Expr"
    right: "Expr"
    line:  int = 0

@dataclass
class TemplateInst:
    """vector(int) — template instantiation used as an expression/type"""
    name: str
    args: list[TypeName]
    line: int = 0


# ── type aliases ──────────────────────────────────────────────────────────────

Expr = (IntLit | FloatLit | StringLit | BoolLit | NullLit |
        Ident | SelfExpr | BinOp | UnaryOp | Assign | Call |
        MethodCall | FieldAccess | Index | Cast | SizeOf |
        Ternary | StructLit | NullCoalesce | TemplateInst)

Stmt = (ReturnStmt | LetStmt | ExprStmt | IfStmt | ForStmt |
        WhileStmt | BreakStmt | ContinueStmt | TagSwitchStmt |
        SwitchStmt | AssertStmt | DeferStmt | DInitCallStmt | Block | ConditionalBlock)

Decl = (ImportDecl | IncludeDecl | ExternDecl | ConstExprDecl | TypeAlias |
        FnDecl | StructDecl | TagUnionDecl | EnumDecl | NamespaceDecl | ConditionalBlock)


@dataclass
class Program:
    decls: list[Decl]
    filename: str = "<input>"
