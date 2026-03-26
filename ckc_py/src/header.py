"""
CK Header Emitter
Generates a C header (.h) from a monomorphized CK program.

Contains:
  - Include guard
  - Struct/union forward declarations (typedef)
  - Full struct/union definitions (fields only)
  - Enum definitions
  - Type aliases
  - constexpr as #define
  - Function prototypes (non-static)

Excludes:
  - Function bodies
  - $import / $include directives
  - $interface declarations (compile-time only)
  - Internal helpers prefixed with _ck_
"""

from __future__ import annotations
import os
import re
from .ast import (
    Program, StructDecl, TagUnionDecl, FnDecl, EnumDecl,
    TypeAlias, ConstExprDecl, Param, TypeName,
)


# ── primitive type map (mirrors emitter) ────────────────────────────────────

_PRIM = {
    "i8":   "int8_t",   "i16":  "int16_t",  "i32":  "int32_t",  "i64":  "int64_t",
    "u8":   "uint8_t",  "u16":  "uint16_t", "u32":  "uint32_t", "u64":  "uint64_t",
    "f32":  "float",    "f64":  "double",
    "usize":"size_t",   "bool": "int",       "char": "char",
    "void": "void",     "Self": "/* Self */",
}

_OP_MANGLE = {
    "+": "add", "-": "sub", "*": "mul", "/": "div", "%": "mod",
    "==": "eq", "!=": "neq", "<": "lt", ">": "gt", "<=": "lte", ">=": "gte",
}


def emit_header(prog: Program, source_path: str = "") -> str:
    return HeaderEmitter(prog, source_path).emit()


class HeaderEmitter:
    def __init__(self, prog: Program, source_path: str):
        self.prog        = prog
        self.source_path = source_path
        self._lines: list[str] = []

    # ── output helpers ────────────────────────────────────────────────────────

    def _w(self, line: str = "") -> None:
        self._lines.append(line)

    def result(self) -> str:
        return "\n".join(self._lines) + "\n"

    # ── type rendering (mirrors emitter._render_type) ────────────────────────

    def _rtype(self, t: TypeName, name: str = "") -> str:
        base = _PRIM.get(t.name, t.name)
        if t.const:
            base = f"const {base}"
        if t.pointer:
            base = f"{base}*"
        if t.ref:
            base = f"{base}*"
        if name:
            if t.array_size is not None:
                return f"{base} {name}[{t.array_size}]"
            return f"{base} {name}"
        return base

    def _rparam(self, p: Param) -> str:
        return self._rtype(p.type, p.name)

    # ── include guard name ────────────────────────────────────────────────────

    def _guard_name(self) -> str:
        if self.source_path:
            base = os.path.basename(self.source_path)
            # strip extension, uppercase, replace non-alnum with _
            stem = os.path.splitext(base)[0]
        else:
            stem = "ck_module"
        guard = re.sub(r"[^A-Za-z0-9]", "_", stem).upper()
        return f"{guard}_H"

    def _collect_value_deps(self, d, known_type_names: set[str]) -> set[str]:
        deps: set[str] = set()

        def visit(t: TypeName, needs_complete: bool = True):
            if t is None:
                return
            if t.name == "__fnptr__":
                for pt in t.fn_params:
                    visit(pt, needs_complete=False)
                if t.fn_ret:
                    visit(t.fn_ret, needs_complete=False)
                return

            local_complete = needs_complete and not t.pointer and not t.ref
            if local_complete and t.name in known_type_names:
                deps.add(t.name)
            for arg in t.args:
                visit(arg, needs_complete=local_complete)

        if isinstance(d, StructDecl):
            for f in d.fields:
                visit(f.type, needs_complete=True)
            deps.discard(d.name)
        elif isinstance(d, TagUnionDecl):
            for v in d.variants:
                visit(v.type, needs_complete=True)
            deps.discard(d.name)
        return deps

    def _order_layout_types(self, decls: list) -> list:
        layout = [d for d in decls if isinstance(d, (StructDecl, TagUnionDecl))]
        if not layout:
            return decls

        by_name = {d.name: d for d in layout}
        known = set(by_name.keys())
        deps = {n: self._collect_value_deps(d, known) for n, d in by_name.items()}
        source_order = [d.name for d in decls if hasattr(d, "name")]

        emitted: set[str] = set()
        ordered_names: list[str] = []
        while len(ordered_names) < len(layout):
            ready = [
                n for n in source_order
                if n in by_name and n not in emitted and deps[n].issubset(emitted)
            ]
            if not ready:
                for n in source_order:
                    if n in by_name and n not in emitted:
                        ordered_names.append(n)
                        emitted.add(n)
                break
            for n in ready:
                ordered_names.append(n)
                emitted.add(n)

        ordered_layout = [by_name[n] for n in ordered_names]
        it = iter(ordered_layout)
        final: list = []
        for d in decls:
            if isinstance(d, (StructDecl, TagUnionDecl)) and d.name in by_name:
                final.append(next(it))
            else:
                final.append(d)
        return final

    # ── main emit ─────────────────────────────────────────────────────────────

    def emit(self) -> str:
        guard = self._guard_name()
        src   = os.path.basename(self.source_path) if self.source_path else "?"

        self._w(f"/* Generated by CK — do not edit */")
        self._w(f"/* Source: {src} */")
        self._w(f"#ifndef {guard}")
        self._w(f"#define {guard}")
        self._w()
        self._w("#include <stdint.h>")
        self._w("#include <stddef.h>")
        self._w()

        decls = self.prog.decls

        # ── 1. forward declarations ───────────────────────────────────────────
        fwd = []
        for d in decls:
            if isinstance(d, StructDecl) and not d.is_interface:
                kw = "union" if getattr(d, "is_union", False) else "struct"
                fwd.append(f"typedef {kw} {d.name}_s {d.name};")
            elif isinstance(d, TagUnionDecl):
                fwd.append(f"typedef struct {d.name}_s {d.name};")

        if fwd:
            self._w("/* ── forward declarations ── */")
            for line in fwd:
                self._w(line)
            self._w()

        # ── 2. enums ──────────────────────────────────────────────────────────
        enums = [d for d in decls if isinstance(d, EnumDecl)]
        if enums:
            for d in enums:
                self._emit_enum(d)
            self._w()

        # ── 3. type aliases ───────────────────────────────────────────────────
        aliases = [d for d in decls if isinstance(d, TypeAlias)]
        if aliases:
            for d in aliases:
                self._w(f"typedef {self._rtype(d.type)} {d.name};")
            self._w()

        # ── 4. constexprs as #define ──────────────────────────────────────────
        consts = [d for d in decls if isinstance(d, ConstExprDecl)]
        if consts:
            for d in consts:
                self._emit_constexpr(d)
            self._w()

        # ── 5. struct/union definitions ───────────────────────────────────────
        ordered_decls = self._order_layout_types(decls)
        for d in ordered_decls:
            if isinstance(d, StructDecl) and not d.is_interface:
                self._emit_struct(d)
                self._w()
            elif isinstance(d, TagUnionDecl):
                self._emit_tag_union(d)
                self._w()

        # ── 6. function prototypes ────────────────────────────────────────────
        protos = []
        for d in decls:
            if isinstance(d, FnDecl) and d.body is not None:
                protos.append(self._fn_proto(d, prefix="", receiver=""))
            elif isinstance(d, StructDecl) and not d.is_interface:
                for m in d.methods:
                    if m.body is not None:
                        protos.append(self._fn_proto(m, prefix=d.name,
                                                      receiver=d.name))
            elif isinstance(d, TagUnionDecl):
                for m in d.methods:
                    if m.body is not None:
                        protos.append(self._fn_proto(m, prefix=d.name,
                                                      receiver=d.name))

        if protos:
            self._w("/* ── function prototypes ── */")
            for p in protos:
                self._w(p)
            self._w()

        self._w(f"#endif /* {guard} */")
        return self.result()

    # ── helpers ───────────────────────────────────────────────────────────────

    def _emit_enum(self, d: EnumDecl) -> None:
        self._w(f"typedef enum {{")
        for v in d.variants:
            if v.value is not None:
                self._w(f"    {d.name}_{v.name} = {self._render_const_expr(v.value)},")
            else:
                self._w(f"    {d.name}_{v.name},")
        self._w(f"}} {d.name};")

    def _emit_constexpr(self, d: ConstExprDecl) -> None:
        val = self._render_const_expr(d.value)
        self._w(f"#ifndef {d.name}")
        self._w(f"#define {d.name} ({val})")
        self._w(f"#endif")

    def _render_const_expr(self, e) -> str:
        """Simple expression renderer for constexpr values."""
        from .ast import IntLit, FloatLit, BoolLit, StringLit, Ident, BinOp, UnaryOp
        if isinstance(e, IntLit):   return str(e.value)
        if isinstance(e, FloatLit): return repr(e.value)
        if isinstance(e, BoolLit):  return "1" if e.value else "0"
        if isinstance(e, StringLit):return f'"{e.value}"'
        if isinstance(e, Ident):    return e.name
        if isinstance(e, UnaryOp):
            return f"({e.op}{self._render_const_expr(e.operand)})"
        if isinstance(e, BinOp):
            l = self._render_const_expr(e.left)
            r = self._render_const_expr(e.right)
            return f"({l} {e.op} {r})"
        return "/* ? */"

    def _emit_struct(self, d: StructDecl) -> None:
        kw = "union" if getattr(d, "is_union", False) else "struct"
        self._w(f"{kw} {d.name}_s {{")
        for f in d.fields:
            self._w(f"    {self._rparam(f)};")
        self._w(f"}};")

    def _emit_tag_union(self, d: TagUnionDecl) -> None:
        # tag enum — use base template name (unmangled)
        base = getattr(d, "template_base", None) or d.name
        if d.variants:
            self._w(f"typedef enum {{")
            for v in d.variants:
                self._w(f"    {base}_{v.name}_,")
            self._w(f"}} {base}_tag_;")
            self._w()
        self._w(f"struct {d.name}_s {{")
        self._w(f"    {base}_tag_ tag_;")
        self._w(f"    union {{")
        for v in d.variants:
            self._w(f"        {self._rparam(v)};")
        self._w(f"    }};")
        self._w(f"}};")

    def _fn_proto(self, fn: FnDecl, prefix: str, receiver: str) -> str:
        is_init  = fn.lifecycle == "init"
        is_dinit = fn.lifecycle == "dinit"

        if fn.operator:
            safe   = _OP_MANGLE.get(fn.operator, fn.operator)
            c_name = f"{prefix}_op_{safe}" if prefix else f"op_{safe}"
        else:
            c_name = f"{prefix}_{fn.name}" if prefix else fn.name

        params = []
        if receiver and not is_init:
            params.append(f"{receiver}* self")
        for p in fn.params:
            params.append(self._rparam(p))

        if is_init and receiver:
            ret = receiver
        else:
            ret = self._rtype(fn.return_type)

        param_str = ", ".join(params) if params else "void"
        return f"{ret} {c_name}({param_str});"
