"""
CK C Emitter
Walks a CK AST and produces C99-compatible source code.
This is intentionally simple — readable output over clever output.
"""

from __future__ import annotations
from .ast import *
from . import lifetime as _lifetime


# Primitive types that map directly to C
_PRIM_MAP = {
    "i8":    "int8_t",
    "i16":   "int16_t",
    "i32":   "int32_t",
    "i64":   "int64_t",
    "u8":    "uint8_t",
    "u16":   "uint16_t",
    "u32":   "uint32_t",
    "u64":   "uint64_t",
    "usize": "size_t",
    "f32":   "float",
    "f64":   "double",
    "bool":  "int",       # _Bool in C99, int for max compat
    "void":  "void",
    "char":  "char",
    "Self":  "__SELF__",  # replaced during struct emit
}

_OP_MAP = {
    "+": "+", "-": "-", "*": "*", "/": "/", "%": "%",
    "==": "==", "!=": "!=", "<": "<", ">": ">", "<=": "<=", ">=": ">=",
    "&&": "&&", "||": "||",
    "|": "|", "^": "^", "&": "&", "<<": "<<", ">>": ">>",
}


class EmitError(Exception):
    pass


class Emitter:
    def __init__(self):
        self._lines:     list[str] = []
        self._indent:    int       = 0
        self._self_type: str       = ""  # current struct name, for Self substitution
        self._structs:   dict[str, StructDecl]   = {}
        self._unions:    dict[str, TagUnionDecl] = {}
        self._enums:     dict[str, EnumDecl]     = {}
        # symbol table: stack of {var_name: struct_type_name}
        # each function push/pops a frame; allows method call resolution
        self._scope_stack: list[dict[str, str]] = []
        # {type_name: dinit_method_name} — populated by emit_program
        self._dinit_types: dict[str, str] = {}
        # true when emitting a $init body — no self pointer exists
        self._in_init: bool = False
        self._current_return_type: str = ""
        self._current_return_ref:  bool = False
        # temp variables to emit before the current statement
        self._pending_temps: list[tuple[str,str,str]] = []
        self._tmp_counter: int = 0  # monotonic counter for unique temp names
        # stack of active defer blocks — each entry is a list of Block defers
        # pushed when entering a block, popped when leaving
        self._defer_stack: list[list] = []
        # live dinit variables — list of (type_name, var_name) in declaration order
        # pushed as LetStmt are emitted, popped at block exit
        # used for correct cleanup on early return across scopes
        self._live_dinits: list[tuple[str,str]] = []
        # tag enums already emitted — emit once per base template name
        self._emitted_tag_enums: set[str] = set()
        # {mangled_union_name: base_template_name} for tag enum value prefixes
        self._tag_base: dict[str, str] = {}
        # names of params declared as T& — field access uses ->, call sites auto-ref
        self._ref_params: set[str] = set()
        # {c_fn_name: [Param]} for call-site auto-ref
        self._fn_params: dict[str, list] = {}
        self._fn_return_types: dict[str, str] = {}
        self._fn_returns_ref:  dict[str, bool] = {}
        self._has_includes: bool = False  # true once any $include is emitted
        self._fwd_emitted: set[str] = set()  # names already emitted in fwd decls
        self._defer_method_emit: bool = False
        self._deferred_methods: list[tuple[FnDecl, str, str]] = []

    # ── output helpers ────────────────────────────────────────────────────────

    def _emit(self, line: str = ""):
        self._lines.append("    " * self._indent + line)

    def _emit_raw(self, text: str):
        self._lines.append(text)

    def _blank(self):
        self._lines.append("")

    def result(self) -> str:
        return "\n".join(self._lines)

    # ── type rendering ────────────────────────────────────────────────────────

    def _render_type(self, t: TypeName, name: str = "") -> str:
        """
        Render a TypeName to a C declaration string.
        If `name` is provided, produces 'type name' for declarations.
        For array types T[N], produces 'type name[N]' — the N goes after the name.
        For fn pointer types, produces 'R (*name)(params)'.
        """
        # function pointer: fn(T1, T2) -> R  →  R (*name)(T1, T2)
        if t.name == "__fnptr__":
            ret    = self._render_type(t.fn_ret) if t.fn_ret else "void"
            params = ", ".join(self._render_type(p) for p in t.fn_params) or "void"
            # always one * for the pointer-to-function; extra * if pointer to fnptr
            stars  = "*" + ("*" if t.pointer else "") + ("*" if t.ref else "")
            if name:
                return f"{ret} ({stars}{name})({params})"
            # anonymous fnptr (e.g. as param type without a name)
            return f"{ret} (*)({params})"
        base = self._base_type(t)
        stars = ""
        if t.pointer: stars += "*"
        if t.ref:     stars += "*"   # & → * in C
        # extra_stars from double-pointer substitution (e.g. K* where K=char*)
        stars += "*" * getattr(t, "extra_stars", 0)
        if t.const:   base = "const " + base
        if name:
            if t.array_size:
                return f"{base}{stars} {name}[{t.array_size}]".strip()
            return f"{base}{stars} {name}".strip()
        # no name — just the base type (array_size omitted, caller handles it)
        return f"{base}{stars}".strip()

    def _base_type(self, t: TypeName) -> str:
        name = t.name
        if name == "__fnptr__":
            return ""   # handled entirely by _render_type
        if name == "Self":
            name = self._self_type
        mapped = _PRIM_MAP.get(name, name)
        if t.args:
            # monomorphized name: vector(int) → vector_int
            args_str = "_".join(self._type_to_mangle(a) for a in t.args)
            return f"{mapped}_{args_str}"
        return mapped

    def _struct_fields(self, type_name: str) -> set[str]:
        """Return the set of field/variant names for a known struct or union type."""
        struct = self._structs.get(type_name)
        if struct is not None:
            return {f.name for f in struct.fields}
        union = self._unions.get(type_name)
        if union is not None:
            # include tag_ field and all variant names
            return {v.name for v in union.variants} | {"tag_"}
        return set()

    def _type_to_mangle(self, t: TypeName) -> str:
        """Produce a mangled suffix string for a type, used in monomorphized names."""
        s = _PRIM_MAP.get(t.name, t.name)
        if t.args:
            s += "_" + "_".join(self._type_to_mangle(a) for a in t.args)
        if t.pointer: s += "_ptr"
        if t.ref:     s += "_ref"
        return s

    def _render_param(self, p: Param) -> str:
        return self._render_type(p.type, p.name)

    def _collect_decl_value_deps(self, d, known_type_names: set[str]) -> set[str]:
        """
        Return same-module type dependencies that require complete definitions.
        Only by-value fields/variants require full size in C; pointer/ref fields do not.
        """
        deps: set[str] = set()

        def visit_type(t: TypeName, needs_complete: bool = True):
            if t is None:
                return
            if t.name == "__fnptr__":
                for pt in t.fn_params:
                    visit_type(pt, needs_complete=False)
                if t.fn_ret:
                    visit_type(t.fn_ret, needs_complete=False)
                return

            local_complete = needs_complete and not t.pointer and not t.ref
            if local_complete and t.name in known_type_names:
                deps.add(t.name)

            # template args are materialized by value in the instantiated type
            for arg in t.args:
                visit_type(arg, needs_complete=local_complete)

        if isinstance(d, StructDecl):
            for f in d.fields:
                visit_type(f.type, needs_complete=True)
            deps.discard(d.name)
        elif isinstance(d, TagUnionDecl):
            for v in d.variants:
                visit_type(v.type, needs_complete=True)
            deps.discard(d.name)

        return deps

    def _order_type_decls(self, type_decls: list) -> list:
        """
        Order type declarations so struct/union definitions appear before any
        by-value users that require their complete size in C.
        """
        types_with_identity = [
            d for d in type_decls
            if isinstance(d, (StructDecl, TagUnionDecl))
        ]
        if not types_with_identity:
            return type_decls

        decl_by_name = {d.name: d for d in types_with_identity}
        known_names = set(decl_by_name.keys())
        deps = {
            name: self._collect_decl_value_deps(decl, known_names)
            for name, decl in decl_by_name.items()
        }

        # stable Kahn: pick ready declarations in original source order
        source_order = [d.name for d in type_decls if hasattr(d, "name")]
        emitted: set[str] = set()
        ordered_names: list[str] = []

        while len(ordered_names) < len(types_with_identity):
            ready = [
                name for name in source_order
                if name in decl_by_name
                and name not in emitted
                and deps[name].issubset(emitted)
            ]
            if not ready:
                # cycle (e.g. mutual by-value recursion) — keep source order for remaining
                for name in source_order:
                    if name in decl_by_name and name not in emitted:
                        ordered_names.append(name)
                        emitted.add(name)
                break

            for name in ready:
                ordered_names.append(name)
                emitted.add(name)

        ordered_types = [decl_by_name[name] for name in ordered_names]
        ordered_type_names = {d.name for d in ordered_types}

        # keep non-struct declarations in their original relative positions
        # but splice struct/union declarations in dependency-resolved order.
        type_iter = iter(ordered_types)
        final: list = []
        for d in type_decls:
            if isinstance(d, (StructDecl, TagUnionDecl)) and d.name in ordered_type_names:
                final.append(next(type_iter))
            else:
                final.append(d)
        return final

    # ── program ───────────────────────────────────────────────────────────────

    def emit_program(self, prog: Program) -> str:
        self._emit_raw(f"/* Generated by CK — do not edit */")
        self._emit_raw(f"/* Source: {prog.filename} */")
        self._blank()
        self._emit_raw("#include <stdint.h>")
        self._emit_raw("#include <stddef.h>")
        self._blank()
                
        # first pass: register structs, unions, enums for name resolution
        for d in prog.decls:
            if isinstance(d, StructDecl):
                self._structs[d.name] = d
            elif isinstance(d, TagUnionDecl):
                self._unions[d.name] = d
            elif isinstance(d, EnumDecl):
                self._enums[d.name] = d

        # run lifetime pass — annotates blocks with $dinit info
        self._dinit_types = _lifetime.build_dinit_map(prog)
        _lifetime.annotate(prog, self._dinit_types)

        # pre-scan: if ANY $include exists, suppress $extern fn declarations
        self._has_includes = any(isinstance(d, IncludeDecl) for d in prog.decls)

        # bucket declarations by kind — order within each bucket preserves source order
        includes:   list = []
        externs:    list = []
        type_decls: list = []   # struct, union, enum, typedef, constexpr
        fn_decls_order: list = []
        other:      list = []   # import comments, etc.
        


        for d in prog.decls:
            if isinstance(d, IncludeDecl):
                includes.append(d)
            elif isinstance(d, ExternDecl):
                externs.append(d)
            elif isinstance(d, (StructDecl, TagUnionDecl,
                                 EnumDecl, TypeAlias, ConstExprDecl)):
                type_decls.append(d)
            elif isinstance(d, FnDecl):
                fn_decls_order.append(d)
            else:
                other.append(d)

        # 1. $include directives — must come before everything that references their types
        for d in includes:
            self._emit_decl(d)
        if includes:
            self._blank()

        # 2. $extern blocks — register signatures, emit #ifndef constants
        for d in externs:
            self._emit_decl(d)
        if externs:
            self._blank()

        # 3. forward declarations — struct typedefs + fn prototypes
        #    now safe since includes have been emitted
        self._emit_forward_decls(type_decls, fn_decls_order)

        # 4. full type definitions (structs, unions, enums, typedefs, constexprs)
        # dependency-order concrete structs/unions so by-value fields can compile
        self._defer_method_emit = True
        self._deferred_methods = []
        ordered_type_decls = self._order_type_decls(type_decls)
        for d in ordered_type_decls:
            self._emit_decl(d)
            self._blank()
        self._defer_method_emit = False

        # 5. other (import comments, etc.)
        for d in other:
            self._emit_decl(d)
            self._blank()

        # 6. deferred methods (after all concrete type layouts are known)
        for method, prefix, receiver_type in self._deferred_methods:
            saved_self = self._self_type
            self._self_type = receiver_type
            self._emit_fn(method, prefix=prefix, receiver_type=receiver_type)
            self._self_type = saved_self
            self._blank()

        # 7. all top-level functions
        for d in fn_decls_order:
            self._emit_decl(d)
            self._blank()

        return self.result()

    # ── declarations ─────────────────────────────────────────────────────────

    def _emit_decl(self, d):
        if isinstance(d, ImportDecl):
            self._emit(f'/* $import "{d.path}" */')
        elif isinstance(d, ConstExprDecl):
            if getattr(d, "name", None) in self._fwd_emitted:
                return
            self._emit_constexpr(d)
        elif isinstance(d, FnDecl):
            self._emit_fn(d, prefix="")
        elif isinstance(d, StructDecl):
            self._emit_struct(d)
        elif isinstance(d, TagUnionDecl):
            self._emit_tag_union(d)
        elif isinstance(d, TypeAlias):
            if d.name in self._fwd_emitted:
                return
            self._emit_type_alias(d)
        elif isinstance(d, IncludeDecl):
            self._emit_include(d)
        elif isinstance(d, ExternDecl):
            self._emit_extern(d)
        elif isinstance(d, NamespaceDecl):
            self._emit(f"/* namespace {d.name} — should be flattened */")
        elif isinstance(d, EnumDecl):
            if d.name in self._fwd_emitted:
                return
            self._emit_enum(d)
        elif isinstance(d, ConditionalBlock):
            # $if should be resolved by condeval — emit contents unconditionally
            for inner in d.body:
                self._emit_decl(inner)
        else:
            self._emit(f"/* unhandled decl: {type(d).__name__} */")

    def _emit_constexpr(self, d: ConstExprDecl):
        val = self._render_expr(d.value)
        self._emit(f"static const {self._render_type(d.type)} {d.name} = {val};")

    def _emit_conditional(self, d: ConditionalBlock):
        cond = self._render_expr(d.condition)
        self._emit(f"/* $if ({cond}) — compile-time conditional */")
        # In v0 we emit everything inside (no actual conditional compilation yet)
        # A future pass will evaluate target.os / build.debug
        for decl in d.body:
            self._emit_decl(decl)

    # ── forward declarations ─────────────────────────────────────────────────

    def _emit_forward_decls(self, type_decls: list, fn_decls_in: list) -> None:
        """
        Emit forward declarations for all structs, unions, and functions.
        Called after $include/$extern have already been emitted.
        """
        struct_names: list[str] = []
        fn_protos: list[tuple]  = []  # (FnDecl, prefix, receiver_type)
        early_decls: list       = []  # enums, typedefs, constexprs

        for d in type_decls:
            if isinstance(d, StructDecl) and not d.is_interface:
                struct_names.append((d.name, getattr(d, 'is_union', False)))
                for m in d.methods:
                    if m.body is not None:
                        fn_protos.append((m, d.name, d.name))
            elif isinstance(d, TagUnionDecl):
                struct_names.append(d.name)
                for m in d.methods:
                    if m.body is not None:
                        fn_protos.append((m, d.name, d.name))
            elif isinstance(d, (EnumDecl, TypeAlias, ConstExprDecl)):
                early_decls.append(d)

        for d in fn_decls_in:
            if d.body is not None:
                fn_protos.append((d, "", ""))

        if not struct_names and not fn_protos and not early_decls:
            return

        self._emit("/* ── forward declarations ── */")

        # struct/union typedefs — allow pointers before full definition
        for item in struct_names:
            name, is_union = item if isinstance(item, tuple) else (item, False)
            kw = "union" if is_union else "struct"
            self._emit(f"typedef {kw} {name}_s {name};")

        # enums, typedefs, constexprs before fn prototypes that reference them
        for d in early_decls:
            if isinstance(d, EnumDecl):
                self._emit_enum(d)
                self._fwd_emitted.add(d.name)
            elif isinstance(d, TypeAlias):
                self._emit_type_alias(d)
                self._fwd_emitted.add(d.name)
            elif isinstance(d, ConstExprDecl):
                self._emit_constexpr(d)
                self._fwd_emitted.add(d.name)

        self._blank()

        # function prototypes
        for fn, prefix, receiver_type in fn_protos:
            is_init = fn.lifecycle == "init"
            if fn.operator:
                safe = self._OP_MANGLE.get(fn.operator, fn.operator)
                c_name = f"{prefix}_op_{safe}" if prefix else f"op_{safe}"
            else:
                c_name = f"{prefix}_{fn.name}" if prefix else fn.name
            params = []
            if receiver_type and not is_init:
                params.append(f"{receiver_type}* self")
            for p in fn.params:
                params.append(self._render_param(p))
            if is_init and receiver_type:
                ret = receiver_type
            else:
                ret = self._render_type(fn.return_type)
            param_str = ", ".join(params) if params else "void"
            self._emit(f"{ret} {c_name}({param_str});")

        self._blank()

    # ── c interop ────────────────────────────────────────────────────────────

    def _emit_include(self, d: IncludeDecl):
        self._emit_raw(f"#include {d.path}")

    def _emit_extern(self, d: ExternDecl):
        # opaque struct — register in type system, no emission
        for name in d.structs:
            self._structs[name] = StructDecl(
                name=name, fields=[], methods=[],
                template_params=[], line=d.line)
        # full struct definitions — emit typedef and register with fields
        for sd in d.full_structs:
            self._structs[sd.name] = sd
            if not self._has_includes:
                # only emit the typedef if no header provides it
                self._emit_struct(sd)
        # constants — use #ifndef guard to avoid conflicts with included headers
        for c in d.consts:
            val = self._render_expr(c.value)
            self._emit(f"#ifndef {c.name}")
            self._emit(f"#define {c.name} ({val})")
            self._emit(f"#endif")
        # function signatures — register for CK type checking
        for fn in d.fns:
            c_name = fn.name
            self._fn_params[c_name] = fn.params
            ret = self._render_type(fn.return_type)
            self._fn_return_types[c_name] = ret
            # only emit extern declaration when no $include is present
            # if headers are included they already declare everything
            if not self._has_includes:
                param_list = ", ".join(self._render_param(p) for p in fn.params)
                param_str = param_list if param_list else "void"
                self._emit(f"extern {ret} {c_name}({param_str});")
        if d.consts or (d.fns and not self._has_includes):
            self._blank()

    # ── type alias ───────────────────────────────────────────────────────────

    def _emit_type_alias(self, d: TypeAlias):
        # fn-ptr typedef needs special form: typedef R (*Name)(params)
        if d.type.name == "__fnptr__":
            self._emit(f"typedef {self._render_type(d.type, d.name)};")
        else:
            self._emit(f"typedef {self._render_type(d.type)} {d.name};")

    # ── enum ─────────────────────────────────────────────────────────────────

    def _emit_enum(self, d: EnumDecl):
        self._emit(f"typedef enum {{")
        self._indent += 1
        for i, v in enumerate(d.variants):
            if v.value is not None:
                self._emit(f"{d.name}_{v.name} = {self._render_expr(v.value)},")
            else:
                self._emit(f"{d.name}_{v.name},")
        self._indent -= 1
        self._emit(f"}} {d.name};")

    # ── struct ────────────────────────────────────────────────────────────────

    def _emit_struct(self, d: StructDecl):
        if d.is_interface:
            self._emit(f"/* $interface {d.name} — compile-time contract only, no C output */")
            return

        saved_self = self._self_type
        self._self_type = d.name

        kw = "union" if getattr(d, "is_union", False) else "struct"
        self._emit(f"{kw} {d.name}_s {{")
        self._indent += 1
        for f in d.fields:
            self._emit(f"{self._render_param(f)};")
        self._indent -= 1
        self._emit(f"}};")
        self._blank()

        # emit methods as prefixed free functions
        for method in d.methods:
            if self._defer_method_emit:
                self._deferred_methods.append((method, d.name, d.name))
            else:
                self._emit_fn(method, prefix=d.name, receiver_type=d.name)

        self._self_type = saved_self

    # ── tag union ─────────────────────────────────────────────────────────────

    def _emit_tag_union(self, d: TagUnionDecl):
        saved_self = self._self_type
        self._self_type = d.name

        # Use template_base if set (monomorphized), otherwise use the name itself
        base_name = d.template_base if d.template_base else d.name
        self._tag_base[d.name] = base_name

        # Emit the tag enum ONCE per base template name — shared across instantiations
        # e.g. Result_ok_ / Result_err_ works for Result(i32,char*) AND Result(f32,char*)
        if base_name not in self._emitted_tag_enums:
            self._emitted_tag_enums.add(base_name)
            self._emit(f"typedef enum {{")
            self._indent += 1
            for v in d.variants:
                self._emit(f"{base_name}_{v.name}_,")
            self._indent -= 1
            self._emit(f"}} {base_name}_tag_;")
            self._blank()

        # Emit the concrete struct — uses the shared tag enum
        self._emit(f"struct {d.name}_s {{")
        self._indent += 1
        self._emit(f"{base_name}_tag_ tag_;")
        self._emit(f"union {{")
        self._indent += 1
        for v in d.variants:
            self._emit(f"{self._render_param(v)};")
        self._indent -= 1
        self._emit(f"}};")
        self._indent -= 1
        self._emit(f"}};")
        self._blank()

        # emit methods
        for method in d.methods:
            if self._defer_method_emit:
                self._deferred_methods.append((method, d.name, d.name))
            else:
                self._emit_fn(method, prefix=d.name, receiver_type=d.name)

        self._self_type = saved_self

    # ── functions ─────────────────────────────────────────────────────────────

    # operator symbol → safe C name suffix
    _OP_MANGLE = {
        "+": "add", "-": "sub", "*": "mul", "/": "div", "%": "mod",
        "==": "eq", "!=": "neq", "<": "lt", ">": "gt", "<=": "lte", ">=": "gte",
    }

    def _emit_fn(self, d: FnDecl, prefix: str = "", receiver_type: str = ""):
        # mangle operator name to valid C identifier
        if d.operator:
            safe = self._OP_MANGLE.get(d.operator, d.operator)
            c_name = f"{prefix}_op_{safe}" if prefix else f"op_{safe}"
        else:
            c_name = f"{prefix}_{d.name}" if prefix else d.name
        is_init  = d.lifecycle == "init"
        is_dinit = d.lifecycle == "dinit"
        # track return type for struct literal casts in return statements
        self._current_return_type = self._render_type(d.return_type) if d.return_type else ""
        self._current_return_ref = d.return_type.ref if d.return_type else False
        # register this function's param types for call-site ref handling
        self._fn_params[c_name] = d.params
        # track whether return type is a reference (T&) for call-site auto-deref
        self._fn_returns_ref[c_name] = (d.return_type is not None
                                         and d.return_type.ref)
        # _fn_return_types registered after ret is computed below

        # $init: static constructor — no self param, returns the struct by value
        # $dinit: destructor — has self param, returns void
        # regular method: has self param
        params = []
        if receiver_type and not is_init:
            params.append(f"{receiver_type}* self")
        for p in d.params:
            params.append(self._render_param(p))

        # $init return type is always the struct type
        if is_init and receiver_type:
            ret = receiver_type
        else:
            ret = self._render_type(d.return_type)

        param_str = ", ".join(params) if params else "void"
        # register return type now that ret is known
        self._fn_return_types[c_name] = ret

        if d.body is None:
            self._emit(f"{ret} {c_name}({param_str});")
            return

        self._emit(f"{ret} {c_name}({param_str}) {{")
        self._indent += 1
        self._scope_push()
        saved_in_init = self._in_init
        saved_ref_params = set(self._ref_params)
        self._ref_params.clear()
        self._in_init = is_init
        if receiver_type and not is_init:
            self._scope_define("self", receiver_type)
        for p in d.params:
            # register all struct-typed params so method calls resolve
            if p.type.name in self._structs or p.type.name in self._unions:
                self._scope_define(p.name, p.type.name)
            # ref params also get pointer-access treatment
            if p.type.ref and p.type.name in self._structs:
                self._ref_params.add(p.name)
        self._emit_block_body(d.body)
        self._ref_params = saved_ref_params
        self._in_init = saved_in_init
        self._scope_pop()
        self._indent -= 1
        self._emit(f"}}")

    def _collect_moved_names(self, expr, block_ann) -> set[str]:
        """
        Collect names of local dinit variables referenced in a return expression.
        These are being moved out — don't fire $dinit for them.
        """
        if expr is None or block_ann is None:
            return set()
        dinit_names = {dv.name for dv in block_ann.dinit_vars}
        found: set[str] = set()
        self._scan_idents(expr, dinit_names, found)
        return found

    def _scan_idents(self, e, targets: set[str], found: set[str]) -> None:
        """Recursively find Ident nodes whose names are in targets."""
        if e is None:
            return
        if isinstance(e, Ident) and e.name in targets:
            found.add(e.name)
        elif isinstance(e, BinOp):
            self._scan_idents(e.left, targets, found)
            self._scan_idents(e.right, targets, found)
        elif isinstance(e, UnaryOp):
            self._scan_idents(e.operand, targets, found)
        elif isinstance(e, Call):
            self._scan_idents(e.callee, targets, found)
            for a in e.args: self._scan_idents(a, targets, found)
        elif isinstance(e, MethodCall):
            self._scan_idents(e.receiver, targets, found)
            for a in e.args: self._scan_idents(a, targets, found)
        elif isinstance(e, FieldAccess):
            self._scan_idents(e.receiver, targets, found)
        elif isinstance(e, Index):
            self._scan_idents(e.receiver, targets, found)
            self._scan_idents(e.index, targets, found)
        elif isinstance(e, StructLit):
            for _, v in e.fields: self._scan_idents(v, targets, found)
        elif isinstance(e, Cast):
            self._scan_idents(e.expr, targets, found)

    def _expr_returns_ref(self, e) -> bool:
        """Returns True if expression e produces a T& (reference/pointer) result."""
        if isinstance(e, MethodCall):
            recv_type = self._infer_type_name(e.receiver)
            if not recv_type and isinstance(e.receiver, Ident):
                recv_type = e.receiver.name
            if recv_type:
                decl = self._structs.get(recv_type) or self._unions.get(recv_type)
                if decl:
                    for m in decl.methods:
                        if m.name == e.method and m.return_type.ref:
                            return True
            # check _fn_returns_ref
            fn_name = f"{recv_type}_{e.method}" if recv_type else e.method
            return self._fn_returns_ref.get(fn_name, False)
        return False

    def _render_ref_addr(self, e) -> str:
        """Render a T& expression as the underlying pointer (not auto-dereffed)."""
        if isinstance(e, MethodCall):
            # Get the raw pointer without the (*...) deref wrapper
            recv_type = self._infer_type_name(e.receiver)
            if not recv_type and isinstance(e.receiver, Ident):
                recv_type = e.receiver.name
            fn_name = f"{recv_type}_{e.method}" if recv_type else e.method
            recv = self._render_expr(e.receiver)
            method_params = self._fn_params.get(fn_name, [])
            arg_strs = []
            for i, arg in enumerate(e.args):
                rendered = self._render_expr(arg)
                if i < len(method_params) and method_params[i].type.ref:
                    if isinstance(arg, (Ident, FieldAccess, Index)):
                        already_ref = (isinstance(arg, Ident) and
                                      arg.name in self._ref_params)
                        if not already_ref:
                            rendered = f"&{rendered}"
                arg_strs.append(rendered)
            args = ", ".join(arg_strs)
            if isinstance(e.receiver, SelfExpr):
                all_args = f"self, {args}" if args else "self"
            else:
                all_args = f"&{recv}, {args}" if args else f"&{recv}"
            return f"{fn_name}({all_args})"
        # fallback
        return f"&({self._render_expr(e)})"

    def _emit_dinit_call(self, s: "DInitCallStmt") -> None:
        """
        $dinit(expr) — if the expression's type has a $dinit, call it.
        If the type is unknown or has no $dinit, emit nothing.
        For pointer types: call $dinit on the dereferenced value if non-null.
        For array index (T data[N]): call element $dinit.
        """
        type_name = self._infer_type_name(s.expr)
        if not type_name or type_name not in self._dinit_types:
            # no-op — type has no $dinit
            return
        method = self._dinit_types[type_name]
        rendered = self._render_expr(s.expr)
        # if expression is an array index, take address of the element
        if isinstance(s.expr, Index):
            self._emit(f"{type_name}_{method}(&{rendered});")
        elif isinstance(s.expr, (Ident, FieldAccess, SelfExpr)):
            self._emit(f"{type_name}_{method}(&{rendered});")
        else:
            # general case: wrap in a temp
            tmp = "_ck_dinit_tmp"
            self._emit(f"{type_name}* {tmp} = &({rendered});")
            self._emit(f"{type_name}_{method}({tmp});")

    def _emit_defers(self, ann: "_lifetime.BlockAnnotation") -> None:
        """Emit deferred blocks in reverse registration order (LIFO)."""
        for defer_block in reversed(ann.defer_stmts):
            self._emit_block_body(defer_block)

    def _emit_all_defers_to_return(self) -> None:
        """Emit ALL active defers from all enclosing scopes (for return statements)."""
        for frame in reversed(self._defer_stack):
            for defer_block in reversed(frame):
                self._emit_block_body(defer_block)

    def _flush_pending_temps(self):
        """Emit any pending temp variables accumulated by operator overload calls."""
        for type_name, tmp_name, value_str in self._pending_temps:
            self._emit(f"{type_name} {tmp_name} = {value_str};")
        self._pending_temps.clear()

    def _emit_stmt_with_temps(self, s, block_ann=None):
        """Emit a statement, flushing any pending temps generated during expression render."""
        self._pending_temps.clear()
        # render the statement — this may populate _pending_temps
        # we need to render first, then emit temps before the statement
        # so we capture lines, emit temps, then emit the captured lines
        saved_lines = self._lines
        self._lines = []
        self._emit_stmt(s, block_ann=block_ann)
        stmt_lines = self._lines
        self._lines = saved_lines
        # emit pending temps first
        self._flush_pending_temps()
        # then emit the statement lines
        self._lines.extend(stmt_lines)

    # ── statements ────────────────────────────────────────────────────────────

    def _emit_block_body(self, block: Block):
        ann = _lifetime.get_annotation(block)
        # push frames for this block
        self._defer_stack.append([])
        live_mark = len(self._live_dinits)  # snapshot position for this block
        for s in block.stmts:
            self._emit_stmt_with_temps(s, block_ann=ann)
        # end-of-block cleanup — skip if ALL paths already exited with explicit
        # cleanup (return/break/continue). A return buried in an if branch is
        # NOT the last stmt of the block, so we must check all_paths_exit.
        if ann.all_paths_exit:
            self._defer_stack.pop()
            del self._live_dinits[live_mark:]
            return
        for dv in reversed(ann.dinit_vars):
            method = self._dinit_types.get(dv.type_name, "delete")
            self._emit(f"{dv.type_name}_{method}(&{dv.name});")
        self._emit_defers(ann)
        self._defer_stack.pop()
        del self._live_dinits[live_mark:]

    def _emit_stmt(self, s, block_ann: "_lifetime.BlockAnnotation | None" = None):
        if isinstance(s, ReturnStmt):
            # collect variables being moved out — skip their $dinit
            moved_names: set[str] = self._collect_moved_names(s.value, block_ann)

            # evaluate return value into temp BEFORE cleanup fires
            # (so defers/dinits see valid state and returned value isn't freed)
            has_defers = any(frame for frame in self._defer_stack)
            ret_expr   = self._render_expr(s.value) if s.value else None
            ret_type   = self._current_return_type
            use_tmp    = (ret_expr is not None and has_defers
                          and ret_type and ret_type != "void")
            if use_tmp:
                tmp = "_ck_ret"
                self._emit(f"{ret_type} {tmp} = {ret_expr};")
                ret_expr = tmp

            # fire $dinit for all live variables (inner → outer)
            for type_name, var_name in reversed(self._live_dinits):
                if var_name in moved_names:
                    continue
                method = self._dinit_types.get(type_name, "delete")
                self._emit(f"{type_name}_{method}(&{var_name});")

            # fire all defers
            self._emit_all_defers_to_return()

            if ret_expr is not None:
                # T& return: take address of the returned lvalue
                if self._current_return_ref and not ret_expr.startswith("&"):
                    self._emit(f"return &({ret_expr});")
                else:
                    self._emit(f"return {ret_expr};")
            else:
                self._emit("return;")
        elif isinstance(s, LetStmt):
            # handle auto type deduction
            if s.type.name == "__auto__":
                if s.value is None:
                    self._emit(f"/* auto {s.name} — missing initializer */")
                    return
                inferred = self._infer_expr_type(s.value)
                if not inferred:
                    self._emit(f"/* auto */ auto {s.name} = {self._render_expr(s.value)};")
                    return
                val = self._render_expr(s.value)
                self._emit(f"{inferred} {s.name} = {val};")
                if inferred in self._structs or inferred in self._unions:
                    self._scope_define(s.name, inferred)
                return
            base = s.type.name if s.type.name != "Self" else self._self_type

            # check if RHS is a T& expression
            rhs_is_ref = (s.value is not None
                          and self._expr_returns_ref(s.value))

            # explicit pointer declaration from T& RHS: T* v = raw_ptr
            if s.type.pointer and rhs_is_ref:
                decl = self._render_type(s.type, s.name)
                val = self._render_ref_addr(s.value)
                self._emit(f"{decl} = {val};")
                if base in self._structs or base in self._unions:
                    self._scope_define(s.name, base)
                    self._ref_params.add(s.name)
                return

            # implicit reference binding: T v = T&_expr → T* v = raw_ptr
            if rhs_is_ref and not s.type.pointer and not s.type.ref:
                pass  # handled below
            elif rhs_is_ref:
                rhs_is_ref = False  # don't auto-bind refs for other cases

            if rhs_is_ref:
                # bind as pointer: T* v = <ref_expr_ptr>
                ptr_decl = f"{self._render_type(s.type)}* {s.name}"
                val_rendered = self._render_ref_addr(s.value)
                self._emit(f"{ptr_decl} = {val_rendered};")
                if base in self._structs or base in self._unions:
                    self._scope_define(s.name, base)
                    self._ref_params.add(s.name)
                # reference binding — no ownership, no $dinit
                return

            if base in self._structs or base in self._unions:
                self._scope_define(s.name, base)
                if s.type.pointer:
                    self._ref_params.add(s.name)
            # track for cross-scope $dinit on early return
            if (not s.type.pointer and not s.type.ref
                    and base in self._dinit_types):
                self._live_dinits.append((base, s.name))
            decl = self._render_type(s.type, s.name)
            if s.value is not None:
                self._emit(f"{decl} = {self._render_expr(s.value)};")
            else:
                self._emit(f"{decl};")
        elif isinstance(s, ExprStmt):
            self._emit(f"{self._render_expr(s.expr)};")
        elif isinstance(s, IfStmt):
            self._emit_if(s)
        elif isinstance(s, ForStmt):
            self._emit_for(s)
        elif isinstance(s, WhileStmt):
            self._emit(f"while ({self._render_expr(s.cond)}) {{")
            self._indent += 1
            self._emit_block_body(s.body)
            self._indent -= 1
            self._emit("}")
        elif isinstance(s, BreakStmt):
            if block_ann:
                for dv in reversed(block_ann.dinit_vars):
                    method = self._dinit_types.get(dv.type_name, "delete")
                    self._emit(f"{dv.type_name}_{method}(&{dv.name});")
                self._emit_defers(block_ann)
            self._emit("break;")
        elif isinstance(s, ContinueStmt):
            if block_ann:
                for dv in reversed(block_ann.dinit_vars):
                    method = self._dinit_types.get(dv.type_name, "delete")
                    self._emit(f"{dv.type_name}_{method}(&{dv.name});")
                self._emit_defers(block_ann)
            self._emit("continue;")
        elif isinstance(s, AssertStmt):
            self._emit(f"assert({self._render_expr(s.expr)});")
        elif isinstance(s, TagSwitchStmt):
            self._emit_tag_switch(s)
        elif isinstance(s, SwitchStmt):
            self._emit_switch(s)
        elif isinstance(s, DeferStmt):
            # register in current defer frame for scope-exit emission
            if self._defer_stack:
                self._defer_stack[-1].append(s.body)
        elif isinstance(s, DInitCallStmt):
            self._emit_dinit_call(s)
        elif isinstance(s, TypeAlias):
            # local type alias — emit as typedef
            self._emit_type_alias(s)
        elif isinstance(s, ConditionalBlock):
            # $if is resolved by condeval before emit — should never appear here
            # If it does, emit contents unconditionally (best-effort)
            for inner in s.body:
                self._emit_stmt(inner, block_ann=block_ann)
        elif isinstance(s, Block):
            self._emit("{")
            self._indent += 1
            self._emit_block_body(s)
            self._indent -= 1
            self._emit("}")
        elif isinstance(s, ConditionalBlock):
            # should be resolved by condeval — emit nothing if condition was false
            # or inline body if true (condeval handles this before we get here)
            pass
        else:
            self._emit(f"/* unhandled stmt: {type(s).__name__} */")

    def _emit_if(self, s: IfStmt):
        self._emit(f"if ({self._render_expr(s.cond)}) {{")
        self._indent += 1
        self._emit_block_body(s.then)
        self._indent -= 1
        if s.else_:
            self._emit("} else {")
            self._indent += 1
            self._emit_block_body(s.else_)
            self._indent -= 1
        self._emit("}")

    def _emit_for(self, s: ForStmt):
        init_str = ""
        if isinstance(s.init, LetStmt):
            if s.init.value:
                init_str = f"{self._render_type(s.init.type)} {s.init.name} = {self._render_expr(s.init.value)}"
            else:
                init_str = f"{self._render_type(s.init.type)} {s.init.name}"
        elif isinstance(s.init, ExprStmt):
            init_str = self._render_expr(s.init.expr)

        cond_str = self._render_expr(s.cond) if s.cond else ""
        post_str = self._render_expr(s.post) if s.post else ""

        self._emit(f"for ({init_str}; {cond_str}; {post_str}) {{")
        self._indent += 1
        self._emit_block_body(s.body)
        self._indent -= 1
        self._emit("}")

    def _emit_switch(self, s: SwitchStmt):
        expr = self._render_expr(s.expr)
        self._emit(f"switch ({expr}) {{")
        self._indent += 1
        for case in s.cases:
            if case.value is None:
                self._emit("default:")
            else:
                val = self._render_expr(case.value)
                self._emit(f"case {val}:")
            self._indent += 1
            for stmt in case.body:
                self._emit_stmt(stmt)
            self._indent -= 1
        self._indent -= 1
        self._emit("}")

    def _emit_tag_switch(self, s: TagSwitchStmt):
        expr = self._render_expr(s.expr)
        self._emit(f"switch ({expr}.tag_) {{")
        self._indent += 1

        # find the concrete union type from the switch expression
        expr_type = self._infer_type_name(s.expr)
        union_decl = self._unions.get(expr_type) if expr_type else None

        for case in s.cases:
            # case.union_name is now the BASE template name (e.g. "Result")
            # tag enum values are BaseType_variant_ (e.g. Result_ok_)
            tag_val = f"{case.union_name}_{case.variant_name}_"
            self._emit(f"case {tag_val}: {{")
            self._indent += 1
            # bind variant value using the concrete union decl
            if union_decl:
                variant = next((v for v in union_decl.variants
                                if v.name == case.variant_name), None)
                if variant:
                    vtype = self._render_type(variant.type)
                    self._emit(f"{vtype} {case.bind_name} = {expr}.{case.variant_name};")
                    base_type = variant.type.name
                    if base_type in self._structs or base_type in self._unions:
                        self._scope_define(case.bind_name, base_type)
                    # if the extracted type has $dinit, add to block annotation
                    # so it gets cleaned up at end of case body
                    if (not variant.type.pointer and not variant.type.ref
                            and base_type in self._dinit_types):
                        case_ann = _lifetime.get_annotation(case.body)
                        if case_ann is not None:
                            case_ann.dinit_vars.append(
                                _lifetime.DInitVar(name=case.bind_name,
                                                   type_name=base_type))
            self._emit_block_body(case.body)
            self._emit("break;")
            self._indent -= 1
            self._emit("}")
        self._indent -= 1
        self._emit("}")

    # ── expressions ───────────────────────────────────────────────────────────

    def _render_expr(self, e) -> str:
        if isinstance(e, IntLit):
            v = e.value
            # large unsigned constants need UL suffix in C
            if isinstance(v, int) and v > 0x7FFFFFFFFFFFFFFF:
                return f"{v}UL"
            return str(v)
        if isinstance(e, FloatLit):
            return repr(e.value)
        if isinstance(e, StringLit):
            # re-escape special characters for C output
            escaped = (e.value
                .replace("\\", "\\\\")
                .replace("\n", "\\n")
                .replace("\t", "\\t")
                .replace("\r", "\\r")
                .replace('"', '\\"'
                ).replace("\0", "\\0"))
            return f'"{escaped}"'
        if isinstance(e, BoolLit):
            return "1" if e.value else "0"
        if isinstance(e, CharLit):
            # re-escape special characters for C output
            escaped = (e.value
                .replace("\\", "\\\\")
                .replace("\n", "\\n")
                .replace("\t", "\\t")
                .replace("\r", "\\r")
                .replace('"', '\\"'
                ).replace("\0", "\\0"))
            return f"'{escaped}'"
        if isinstance(e, NullLit):
            return "NULL"
        if isinstance(e, Ident):
            # if inside a method (not $init) and the name is a field, prefix with self->
            if (self._self_type and not self._in_init
                    and e.name in self._struct_fields(self._self_type)):
                return f"self->{e.name}"
            return e.name
        if isinstance(e, SelfExpr):
            return "self"
        if isinstance(e, BinOp):
            # check if left operand's type has an operator overload for this op
            left_type = self._infer_type_name(e.left)
            if left_type and left_type in self._structs:
                struct = self._structs[left_type]
                if any(m.operator == e.op for m in struct.methods):
                    safe    = self._OP_MANGLE.get(e.op, e.op)
                    fn_name = f"{left_type}_op_{safe}"
                    l = self._render_expr(e.left)
                    r = self._render_expr(e.right)
                    # left side: addressable if ident/field/index/self
                    l_addressable = isinstance(e.left,
                        (Ident, FieldAccess, Index, SelfExpr))
                    if not l_addressable:
                        tmp = f"_ck_tmp_{self._tmp_counter}"; self._tmp_counter += 1
                        self._pending_temps.append((left_type, tmp, l))
                        l = tmp
                    # right side: same check
                    r_addressable = isinstance(e.right,
                        (Ident, FieldAccess, Index, SelfExpr))
                    if not r_addressable:
                        tmp = f"_ck_tmp_{self._tmp_counter}"; self._tmp_counter += 1
                        self._pending_temps.append((left_type, tmp, r))
                        r = tmp
                    return f"{fn_name}(&{l}, &{r})"
            l = self._render_expr(e.left)
            r = self._render_expr(e.right)
            return f"({l} {e.op} {r})"
        if isinstance(e, UnaryOp):
            operand = self._render_expr(e.operand)
            if e.prefix:
                return f"({e.op}{operand})"
            return f"({operand}{e.op})"
        if isinstance(e, Assign):
            l = self._render_expr(e.left)
            r = self._render_expr(e.right)
            return f"{l} {e.op} {r}"
        if isinstance(e, FieldAccess):
            # -> sugar: FieldAccess(UnaryOp("*", ptr), field) → ptr->field
            if (isinstance(e.receiver, UnaryOp) and e.receiver.op == "*"
                    and e.receiver.prefix):
                inner = self._render_expr(e.receiver.operand)
                return f"{inner}->{e.field}"
            recv = self._render_expr(e.receiver)
            # pointer receivers (self or ref params) use ->
            if isinstance(e.receiver, SelfExpr):
                return f"self->{e.field}"
            if isinstance(e.receiver, Ident) and e.receiver.name in self._ref_params:
                return f"{recv}->{e.field}"
            # enum member access: Color.Red → Color_Red
            if isinstance(e.receiver, Ident) and e.receiver.name in self._enums:
                return f"{e.receiver.name}_{e.field}"
            return f"{recv}.{e.field}"
        if isinstance(e, MethodCall):
            args = ", ".join(self._render_expr(a) for a in e.args)

            if isinstance(e.receiver, Ident):
                type_name = e.receiver.name
                if type_name in self._structs or type_name in self._unions:
                    fn_name = f"{type_name}_{e.method}"
                    # $init methods: no self pointer — check both structs and unions
                    decl = self._structs.get(type_name) or self._unions.get(type_name)
                    is_init_method = (decl and
                        any(m.name == e.method and m.lifecycle == "init"
                            for m in decl.methods))
                    if is_init_method:
                        return f"{fn_name}({args})"
                    # regular instance method on a type name (e.g. A.alloc(...))
                    # pass a temporary zero-size instance as self
                    self_arg = f"&({type_name}){{}}"
                    all_args = f"{self_arg}, {args}" if args else self_arg
                    return f"{fn_name}({all_args})"

            # Case 2: variable or self receiver
            recv_type = self._infer_type_name(e.receiver)

            # chained method call: if receiver is a non-addressable expression
            # (e.g. another method call returning T or T&), create a temp
            recv_is_addressable = isinstance(e.receiver,
                (Ident, FieldAccess, Index, SelfExpr))
            if (recv_type and not recv_is_addressable
                    and recv_type in self._structs):
                tmp = f"_ck_tmp_{self._tmp_counter}"; self._tmp_counter += 1
                recv_rendered = self._render_expr(e.receiver)
                self._pending_temps.append((recv_type, tmp, recv_rendered))
                recv = tmp
            else:
                recv = self._render_expr(e.receiver)

            if recv_type:
                # check if method is actually a fn-ptr field (not a real method)
                struct_decl = self._structs.get(recv_type)
                if struct_decl:
                    for f in struct_decl.fields:
                        if f.name == e.method and f.type.name == "__fnptr__":
                            # calling through a fn-ptr field: (recv->func)(args)
                            args_str = ", ".join(self._render_expr(a) for a in e.args)
                            if isinstance(e.receiver, SelfExpr):
                                return f"(self->{e.method})({args_str})"
                            elif recv in self._ref_params or isinstance(e.receiver, Ident) and e.receiver.name in self._ref_params:
                                return f"({recv}->{e.method})({args_str})"
                            else:
                                return f"({recv}.{e.method})({args_str})"
                fn_name = f"{recv_type}_{e.method}"
                # render args with auto-ref for T& params
                method_params = self._fn_params.get(fn_name, [])
                arg_strs = []
                for i, arg in enumerate(e.args):
                    rendered = self._render_expr(arg)
                    # auto-ref if param is T& and arg is an addressable ident/field
                    if i < len(method_params) and method_params[i].type.ref:
                        if isinstance(arg, (Ident, FieldAccess, Index)):
                            # skip if arg is already a ref/pointer param
                            already_ref = (isinstance(arg, Ident) and
                                          arg.name in self._ref_params)
                            if not already_ref:
                                rendered = f"&{rendered}"
                    arg_strs.append(rendered)
                args = ", ".join(arg_strs)
                if isinstance(e.receiver, SelfExpr):
                    all_args = (f"self, {args}" if args else "self")
                else:
                    # if receiver is already a pointer (ref param or ref-bound local),
                    # pass directly without taking address
                    already_ptr = (isinstance(e.receiver, Ident) and
                                   e.receiver.name in self._ref_params)
                    if already_ptr:
                        all_args = (f"{recv}, {args}" if args else recv)
                    else:
                        all_args = (f"&{recv}, {args}" if args else f"&{recv}")
                call = f"{fn_name}({all_args})"
                # auto-deref T& return: *fn_name(args)
                if self._fn_returns_ref.get(fn_name, False):
                    return f"(*{call})"
                return call

            # Case 3: unknown receiver — let C compiler catch it
            return f"{recv}.{e.method}({args})"
        if isinstance(e, Call):
            callee = self._render_expr(e.callee)
            params = self._fn_params.get(callee, [])
            arg_strs = []
            for i, arg in enumerate(e.args):
                rendered = self._render_expr(arg)
                # auto-ref if the corresponding param is T& and arg is not already &
                if i < len(params) and params[i].type.ref:
                    if not isinstance(arg, UnaryOp) or arg.op != "&":
                        rendered = f"&{rendered}"
                arg_strs.append(rendered)
            args = ", ".join(arg_strs)
            return f"{callee}({args})"
        if isinstance(e, Index):
            recv = self._render_expr(e.receiver)
            idx  = self._render_expr(e.index)
            return f"{recv}[{idx}]"
        if isinstance(e, Cast):
            return f"(({self._render_type(e.type)}){self._render_expr(e.expr)})"
        if isinstance(e, SizeOf):
            return f"sizeof({self._render_type(e.type)})"
        if isinstance(e, Ternary):
            c = self._render_expr(e.cond)
            t = self._render_expr(e.then)
            f_ = self._render_expr(e.else_)
            return f"({c} ? {t} : {f_})"
        if isinstance(e, StructLit):
            parts = []
            for fname, val in e.fields:
                v = self._render_expr(val)
                if fname:
                    parts.append(f".{fname} = {v}")
                else:
                    parts.append(v)
            inner = "{" + ", ".join(parts) + "}"
            # Cast comes purely from the function return type context,
            # NOT _self_type (which is the outer struct being defined —
            # would produce wrong cast for nested struct literals).
            cast_type = getattr(self, "_current_return_type", "")
            cast = f"({cast_type})" if cast_type else ""
            return f"{cast}{inner}"
        if isinstance(e, NullCoalesce):
            l = self._render_expr(e.left)
            r = self._render_expr(e.right)
            return f"(({l}) != NULL ? ({l}) : ({r}))"
        if isinstance(e, TemplateInst):
            args_str = "_".join(self._type_to_mangle(a) for a in e.args)
            return f"{e.name}_{args_str}"
        return f"/* unknown expr: {type(e).__name__} */"

    def _infer_expr_type(self, e) -> str:
        """
        Infer the C type string for an expression.
        Used for `auto` variable declarations.
        Returns empty string if inference fails.
        """
        if isinstance(e, IntLit):    return "int32_t"
        if isinstance(e, FloatLit):  return "double"
        if isinstance(e, BoolLit):   return "int"
        if isinstance(e, StringLit): return "char*"
        if isinstance(e, NullLit):   return "void*"

        if isinstance(e, Ident):
            # look up in scope
            for frame in reversed(self._scope_stack):
                if e.name in frame:
                    return frame[e.name]
            return ""

        if isinstance(e, TemplateInst):
            # e.g. Result(i32, char*) — the name after mono is the mangled struct name
            args_str = "_".join(self._type_to_mangle(a) for a in e.args)
            return f"{e.name}_{args_str}" if e.args else e.name

        if isinstance(e, MethodCall):
            # TypeName.method(args) — look up method return type
            if isinstance(e.receiver, Ident):
                type_name = e.receiver.name
                # check structs
                decl = self._structs.get(type_name) or self._unions.get(type_name)
                if decl:
                    for m in decl.methods:
                        if m.name == e.method:
                            rt = m.return_type
                            if rt.name == "Self":
                                return type_name
                            return self._render_type(rt)
            # variable.method — infer receiver type then look up method
            recv_type = self._infer_type_name(e.receiver)
            if recv_type:
                decl = self._structs.get(recv_type) or self._unions.get(recv_type)
                if decl:
                    for m in decl.methods:
                        if m.name == e.method:
                            rt = m.return_type
                            if rt.name == "Self":
                                return recv_type
                            return self._render_type(rt)
            return ""

        if isinstance(e, Call):
            callee = self._render_expr(e.callee) if not isinstance(e.callee, Ident) else e.callee.name
            params = self._fn_params.get(callee, [])
            # look up the function's return type from _fn_return_types
            return self._fn_return_types.get(callee, "")

        if isinstance(e, FieldAccess):
            recv_type = self._infer_type_name(e.receiver)
            if recv_type:
                struct = self._structs.get(recv_type)
                if struct:
                    for f in struct.fields:
                        if f.name == e.field:
                            return self._render_type(f.type)
            return ""

        if isinstance(e, StructLit):
            return self._current_return_type or self._self_type

        return ""

    def _infer_type_name(self, e) -> str:
        """Return the struct/union type name for a receiver, or empty string if unknown."""
        if isinstance(e, SelfExpr):
            return self._self_type
        if isinstance(e, Ident):
            for frame in reversed(self._scope_stack):
                if e.name in frame:
                    return frame[e.name]
            return ""
        if isinstance(e, FieldAccess):
            # handle -> sugar: FieldAccess(UnaryOp("*", ptr), field)
            recv = e.receiver
            if isinstance(recv, UnaryOp) and recv.op == "*" and recv.prefix:
                recv = recv.operand
            recv_type = self._infer_type_name(recv)
            if recv_type:
                struct = self._structs.get(recv_type)
                if struct:
                    for f in struct.fields:
                        if f.name == e.field:
                            return f.type.name
            return ""
        if isinstance(e, MethodCall):
            recv_type = self._infer_type_name(e.receiver)
            if not recv_type and isinstance(e.receiver, Ident):
                recv_type = e.receiver.name
            if recv_type:
                decl = self._structs.get(recv_type) or self._unions.get(recv_type)
                if decl:
                    for m in decl.methods:
                        if m.name == e.method:
                            rt = m.return_type
                            return recv_type if rt.name == "Self" else rt.name
                # also check tag unions
                union = self._unions.get(recv_type)
                if union:
                    for m in union.methods:
                        if m.name == e.method:
                            rt = m.return_type
                            return recv_type if rt.name == "Self" else rt.name
            return ""
        if isinstance(e, TemplateInst):
            return mangle_name(e.name, e.args) if e.args else e.name
        if isinstance(e, BinOp):
            # operator overload: result type = left type
            left_type = self._infer_type_name(e.left)
            if left_type and left_type in self._structs:
                if any(m.operator == e.op for m in self._structs[left_type].methods):
                    return left_type
            return ""
        if isinstance(e, Index):
            # arr[i] — element type is the receiver's dereferenced type
            # Case 1: receiver is a pointer/array field like data[i] → T
            # The receiver's inferred type gives us the struct; we need the
            # pointed-to element type. For p[i] where p is T*, element type = T.
            recv = e.receiver
            # FieldAccess(self, "data") where data is T* → element type T
            if isinstance(recv, FieldAccess):
                recv_struct_type = self._infer_type_name(recv.receiver
                    if not (isinstance(recv.receiver, UnaryOp) and recv.receiver.op == "*")
                    else recv.receiver.operand)
                if recv_struct_type:
                    struct = self._structs.get(recv_struct_type)
                    if struct:
                        for f in struct.fields:
                            if f.name == recv.field:
                                return f.type.name  # T from T* or T[N]
            # Case 2: plain ident array — scope lookup won't give element type
            # Fall back to empty (unknown element type)
            return ""
        if isinstance(e, Cast):
            return e.type.name
        return ""

    def _scope_push(self):
        self._scope_stack.append({})

    def _scope_pop(self):
        if self._scope_stack:
            self._scope_stack.pop()

    def _scope_define(self, var_name: str, type_name: str):
        """Record that var_name has struct type type_name in the current scope."""
        if self._scope_stack and type_name:
            self._scope_stack[-1][var_name] = type_name

def emit(prog: Program) -> str:
    return Emitter().emit_program(prog)
# patch: add _struct_fields as a standalone method at module level via monkey-patch
