"""
CK Monomorphizer
Resolves all $template instantiations into concrete StructDecl/FnDecl nodes.

Input:  Program containing StructDecl/TagUnionDecl with template_params,
        and TemplateInst nodes throughout expressions and types.
Output: New Program with no template definitions and no TemplateInst nodes —
        only concrete, named, C-emittable declarations.

Mangling rule:
    vector(i32)         → vector_i32
    Result(FILE*, char&) → Result_FILE_ptr_char_ref
    fixed_vector(i32, 16) → fixed_vector_i32_16
"""

from __future__ import annotations
import copy
from dataclasses import dataclass
from typing import Optional
from .ast import *
from . import checker as _checker


class MonoError(Exception):
    def __init__(self, msg: str, line: int = 0):
        super().__init__(f"[line {line}] MonoError: {msg}")


# ── name mangling ─────────────────────────────────────────────────────────────

def mangle_type(t: TypeName) -> str:
    """Produce a C-safe suffix string for a type argument."""
    name = t.name
    if t.args:
        name += "_" + "_".join(mangle_type(a) for a in t.args)
    if t.pointer: name += "_ptr"
    if t.ref:     name += "_ref"
    return name


def mangle_name(template_name: str, args: list[TypeName]) -> str:
    """Produce the concrete C name for a template instantiation."""
    if not args:
        return template_name
    return template_name + "_" + "_".join(mangle_type(a) for a in args)


# ── type substitution ─────────────────────────────────────────────────────────

def _subst_array_size(size: str | None, env: dict[str, TypeName]) -> str | None:
    """Substitute a template param name in an array size: N → 4."""
    if size is None:
        return None
    if size in env:
        return env[size].name
    return size


def subst_type(t: TypeName, env: dict[str, TypeName]) -> TypeName:
    """
    Substitute template parameters in a TypeName.
    env maps param name → concrete TypeName.
    """
    new_size = _subst_array_size(t.array_size, env)

    # function pointer type — substitute K/V in param/return types
    if t.name == "__fnptr__":
        new_params = [subst_type(p, env) for p in t.fn_params]
        new_ret    = subst_type(t.fn_ret, env) if t.fn_ret else None
        return TypeName(name="__fnptr__", fn_params=new_params, fn_ret=new_ret,
                        pointer=t.pointer, ref=t.ref, const=t.const)

    # direct param substitution: T → i32
    if t.name in env and not t.args:
        concrete = env[t.name]
        pointer = t.pointer or concrete.pointer
        ref     = t.ref     or concrete.ref
        result = TypeName(
            name=concrete.name,
            args=copy.deepcopy(concrete.args),
            pointer=pointer,
            ref=ref,
            const=(t.const or concrete.const),
            array_size=new_size,
            fn_params=copy.deepcopy(concrete.fn_params),
            fn_ret=copy.deepcopy(concrete.fn_ret) if concrete.fn_ret else None,
        )
        # T* where T is already a pointer → double pointer (e.g. char** for char*)
        if t.pointer and concrete.pointer:
            result.extra_stars = 1
        return result
    # recurse into template args
    new_args = [subst_type(a, env) for a in t.args]
    if new_args:
        return TypeName(
            name=mangle_name(t.name, new_args),
            args=[],
            pointer=t.pointer,
            ref=t.ref,
            const=t.const,
            array_size=new_size,
        )
    return TypeName(
        name=t.name,
        args=[],
        pointer=t.pointer,
        ref=t.ref,
        const=t.const,
        array_size=new_size,
    )


def subst_param(p: Param, env: dict[str, TypeName]) -> Param:
    return Param(
        type=subst_type(p.type, env),
        name=p.name,
        default=subst_expr(p.default, env) if p.default else None,
    )


def subst_expr(e, env: dict[str, TypeName], template_name: str = "",
               mangled_name: str = ""):
    """Substitute type params in expressions (mainly for sizeof(T) and casts)."""
    if e is None:
        return None
    # substitute bare ident that is a template param (e.g. N in assert(i < N))
    if isinstance(e, Ident) and e.name in env:
        concrete = env[e.name]
        return Ident(name=concrete.name, line=e.line)
    # substitute tag enum values: Result_ok_ → Result_i32_char_ptr_ok_
    if isinstance(e, Ident) and template_name and mangled_name:
        if e.name.startswith(template_name + "_"):
            suffix = e.name[len(template_name):]  # e.g. "_ok_"
            return Ident(name=mangled_name + suffix, line=e.line)
    if isinstance(e, SizeOf):
        return SizeOf(type=subst_type(e.type, env), line=e.line)
    if isinstance(e, Cast):
        return Cast(type=subst_type(e.type, env),
                    expr=subst_expr(e.expr, env), line=e.line)
    if isinstance(e, TemplateInst):
        new_args = [subst_type(a, env) for a in e.args]
        return TemplateInst(name=e.name, args=new_args, line=e.line)
    if isinstance(e, BinOp):
        return BinOp(op=e.op, left=subst_expr(e.left, env),
                     right=subst_expr(e.right, env), line=e.line)
    if isinstance(e, UnaryOp):
        return UnaryOp(op=e.op, operand=subst_expr(e.operand, env),
                       prefix=e.prefix, line=e.line)
    if isinstance(e, Assign):
        return Assign(op=e.op, left=subst_expr(e.left, env),
                      right=subst_expr(e.right, env), line=e.line)
    if isinstance(e, Call):
        return Call(callee=subst_expr(e.callee, env),
                    args=[subst_expr(a, env) for a in e.args], line=e.line)
    if isinstance(e, MethodCall):
        return MethodCall(receiver=subst_expr(e.receiver, env),
                          method=e.method,
                          args=[subst_expr(a, env) for a in e.args],
                          line=e.line)
    if isinstance(e, FieldAccess):
        return FieldAccess(receiver=subst_expr(e.receiver, env),
                           field=e.field, line=e.line)
    if isinstance(e, Index):
        return Index(receiver=subst_expr(e.receiver, env),
                     index=subst_expr(e.index, env), line=e.line)
    if isinstance(e, Ternary):
        return Ternary(cond=subst_expr(e.cond, env),
                       then=subst_expr(e.then, env),
                       else_=subst_expr(e.else_, env), line=e.line)
    if isinstance(e, StructLit):
        return StructLit(
            type=subst_type(e.type, env) if e.type else None,
            fields=[(n, subst_expr(v, env)) for n, v in e.fields],
            line=e.line,
        )
    if isinstance(e, NullCoalesce):
        return NullCoalesce(left=subst_expr(e.left, env),
                            right=subst_expr(e.right, env), line=e.line)
    # literals, Ident, SelfExpr, NullLit, BoolLit — no substitution needed
    return e


def subst_stmt(s, env: dict[str, TypeName],
               template_name: str = "", mangled_name: str = ""):
    if isinstance(s, LetStmt):
        return LetStmt(type=subst_type(s.type, env), name=s.name,
                       value=subst_expr(s.value, env, template_name, mangled_name)
                             if s.value else None,
                       line=s.line)
    if isinstance(s, ReturnStmt):
        return ReturnStmt(
            value=subst_expr(s.value, env, template_name, mangled_name)
                  if s.value else None,
            line=s.line)
    if isinstance(s, ExprStmt):
        return ExprStmt(expr=subst_expr(s.expr, env, template_name, mangled_name),
                        line=s.line)
    tn, mn = template_name, mangled_name
    if isinstance(s, IfStmt):
        return IfStmt(
            cond=subst_expr(s.cond, env, tn, mn),
            then=subst_block(s.then, env, tn, mn),
            else_=subst_block(s.else_, env, tn, mn) if s.else_ else None,
            line=s.line,
        )
    if isinstance(s, ForStmt):
        return ForStmt(
            init=subst_stmt(s.init, env, tn, mn) if s.init else None,
            cond=subst_expr(s.cond, env, tn, mn) if s.cond else None,
            post=subst_expr(s.post, env, tn, mn) if s.post else None,
            body=subst_block(s.body, env, tn, mn),
            line=s.line,
        )
    if isinstance(s, WhileStmt):
        return WhileStmt(cond=subst_expr(s.cond, env, tn, mn),
                         body=subst_block(s.body, env, tn, mn), line=s.line)
    if isinstance(s, TagSwitchStmt):
        return TagSwitchStmt(
            expr=subst_expr(s.expr, env, tn, mn),
            cases=[TagCase(
                union_name=c.union_name,
                variant_name=c.variant_name,
                bind_name=c.bind_name,
                body=subst_block(c.body, env, tn, mn),
                line=c.line,
            ) for c in s.cases],
            line=s.line,
        )
    if isinstance(s, AssertStmt):
        return AssertStmt(expr=subst_expr(s.expr, env, tn, mn), line=s.line)
    if isinstance(s, Block):
        return subst_block(s, env, tn, mn)
    # BreakStmt, ContinueStmt — no substitution
    return s


def subst_block(b: Block, env: dict[str, TypeName],
                template_name: str = "", mangled_name: str = "") -> Block:
    return Block(stmts=[subst_stmt(s, env, template_name, mangled_name)
                        for s in b.stmts], line=b.line)


def subst_fn(fn: FnDecl, env: dict[str, TypeName],
             new_name: str, receiver_type: str = "",
             template_name: str = "", mangled_name: str = "") -> FnDecl:
    """Produce a concrete FnDecl from a template method with env applied."""
    self_env = dict(env)
    if receiver_type:
        self_env["Self"] = TypeName(name=receiver_type)
    new_ret    = subst_type(fn.return_type, self_env)
    new_params = [subst_param(p, self_env) for p in fn.params]
    new_body   = subst_block(fn.body, self_env,
                             template_name, mangled_name) if fn.body else None
    return FnDecl(
        name=fn.name,
        params=new_params,
        return_type=new_ret,
        body=new_body,
        lifecycle=fn.lifecycle,
        template_params=[],
        operator=fn.operator,
        line=fn.line,
    )


# ── monomorphizer ─────────────────────────────────────────────────────────────

class Monomorphizer:
    def __init__(self, prog: Program):
        self.prog = prog
        # template definitions: name → StructDecl | TagUnionDecl | FnDecl
        self._struct_templates:    dict[str, StructDecl]   = {}
        self._union_templates:     dict[str, TagUnionDecl] = {}
        self._fn_templates:        dict[str, FnDecl]       = {}
        # already-emitted instantiations: mangled_name → True
        self._emitted: set[str] = set()
        # output declarations in emission order
        self._output: list = []
        # populated by _build_env: {param_name: [bound1, bound2, ...]}
        self._param_bounds: dict[str, list[str]] = {}
        # variable name → resolved concrete type name, for $tag switch resolution
        self._var_types: list[dict[str, str]] = [{}]
        # mangled union name → base template name, for $tag switch tag enum resolution
        self._tag_base_map: dict[str, str] = {}
        # current source line for error reporting
        self._current_line: int = 0

    def run(self) -> Program:
        # collect template definitions
        for d in self.prog.decls:
            if isinstance(d, StructDecl) and d.template_params:
                self._struct_templates[d.name] = d
            elif isinstance(d, TagUnionDecl) and d.template_params:
                self._union_templates[d.name] = d
            elif isinstance(d, FnDecl) and d.template_params:
                self._fn_templates[d.name] = d

        # process non-template declarations, collecting instantiation demands
        for d in self.prog.decls:
            self._process_decl(d)

        return Program(decls=self._output, filename=self.prog.filename)

    # ── declaration processing ────────────────────────────────────────────────

    def _process_decl(self, d):
        """Emit d into output, instantiating any templates it references."""
        if isinstance(d, StructDecl):
            if d.template_params:
                return  # skip — only emitted on demand
            # concrete struct: scan for template refs in fields/methods
            new_fields  = [self._resolve_param(f) for f in d.fields]
            new_methods = [self._resolve_fn(m, d.name) for m in d.methods]
            self._output.append(StructDecl(
                name=d.name, fields=new_fields, methods=new_methods,
                template_params=[], is_interface=d.is_interface,
                is_union=d.is_union, implements=d.implements, line=d.line,
            ))

        elif isinstance(d, TagUnionDecl):
            if d.template_params:
                return
            new_variants = [self._resolve_param(v) for v in d.variants]
            new_methods  = [self._resolve_fn(m, d.name) for m in d.methods]
            self._output.append(TagUnionDecl(
                name=d.name, variants=new_variants, methods=new_methods,
                template_params=[], line=d.line,
            ))

        elif isinstance(d, FnDecl):
            if d.template_params:
                return
            self._output.append(self._resolve_fn(d, ""))

        elif isinstance(d, ImportDecl):
            self._output.append(d)

        elif isinstance(d, ConstExprDecl):
            self._output.append(d)
        elif isinstance(d, EnumDecl):
            self._output.append(d)
        elif isinstance(d, TypeAlias):
            self._output.append(d)
        elif isinstance(d, NamespaceDecl):
            self._output.append(d)  # should be flattened before mono
        elif isinstance(d, IncludeDecl):
            self._output.append(d)
        elif isinstance(d, ExternDecl):
            # register full structs for type tracking during mono
            for sd in d.full_structs:
                self._struct_templates.pop(sd.name, None)
            self._output.append(d)

        elif isinstance(d, ConditionalBlock):
            new_body = []
            for inner in d.body:
                saved = self._output
                self._output = new_body
                self._process_decl(inner)
                self._output = saved
            self._output.append(ConditionalBlock(
                condition=d.condition, body=new_body, line=d.line))

    def _resolve_param(self, p: Param) -> Param:
        new_type = self._resolve_type(p.type)
        return Param(type=new_type, name=p.name, default=p.default)

    def _resolve_type(self, t: TypeName) -> TypeName:
        """If t references a template, instantiate it and return the mangled name."""
        extra = getattr(t, 'extra_stars', 0)
        # function pointer type — resolve param/ret types but don't template-instantiate
        if t.name == "__fnptr__":
            new_params = [self._resolve_type(p) for p in t.fn_params]
            new_ret    = self._resolve_type(t.fn_ret) if t.fn_ret else None
            r = TypeName(name="__fnptr__", fn_params=new_params, fn_ret=new_ret,
                         pointer=t.pointer, ref=t.ref, const=t.const)
            if extra: r.extra_stars = extra
            return r
        new_args = [self._resolve_type(a) for a in t.args]
        if new_args:
            self._instantiate(t.name, new_args, self._current_line)
            mangled = mangle_name(t.name, new_args)
            r = TypeName(name=mangled, args=[], pointer=t.pointer, ref=t.ref,
                         const=t.const, array_size=t.array_size)
            if extra: r.extra_stars = extra
            return r
        r = TypeName(name=t.name, args=[], pointer=t.pointer, ref=t.ref,
                     const=t.const, array_size=t.array_size)
        if extra: r.extra_stars = extra
        return r

    def _resolve_fn(self, fn: FnDecl, receiver_type: str) -> FnDecl:
        new_params = [self._resolve_param(p) for p in fn.params]
        new_ret    = self._resolve_type(fn.return_type)
        new_body   = self._resolve_block(fn.body) if fn.body else None
        return FnDecl(
            name=fn.name, params=new_params, return_type=new_ret,
            body=new_body, lifecycle=fn.lifecycle,
            template_params=[], operator=fn.operator, line=fn.line,
        )

    def _resolve_block(self, b: Block) -> Block:
        self._var_types.append({})
        stmts = [self._resolve_stmt(s) for s in b.stmts]
        self._var_types.pop()
        return Block(stmts=stmts, line=b.line)

    def _resolve_stmt(self, s):
        if isinstance(s, LetStmt):
            self._current_line = s.line
            # auto type — defer resolution to emitter, just resolve the value
            if s.type.name == "__auto__":
                new_val = self._resolve_expr(s.value) if s.value else None
                return LetStmt(type=s.type, name=s.name, value=new_val, line=s.line)
            new_type = self._resolve_type(s.type)
            new_val  = self._resolve_expr(s.value) if s.value else None
            self._var_types[-1][s.name] = new_type.name
            return LetStmt(type=new_type, name=s.name, value=new_val, line=s.line)
        if isinstance(s, ReturnStmt):
            return ReturnStmt(
                value=self._resolve_expr(s.value) if s.value else None,
                line=s.line)
        if isinstance(s, ExprStmt):
            return ExprStmt(expr=self._resolve_expr(s.expr), line=s.line)
        if isinstance(s, IfStmt):
            return IfStmt(
                cond=self._resolve_expr(s.cond),
                then=self._resolve_block(s.then),
                else_=self._resolve_block(s.else_) if s.else_ else None,
                line=s.line)
        if isinstance(s, ForStmt):
            return ForStmt(
                init=self._resolve_stmt(s.init) if s.init else None,
                cond=self._resolve_expr(s.cond) if s.cond else None,
                post=self._resolve_expr(s.post) if s.post else None,
                body=self._resolve_block(s.body),
                line=s.line)
        if isinstance(s, WhileStmt):
            return WhileStmt(cond=self._resolve_expr(s.cond),
                             body=self._resolve_block(s.body), line=s.line)
        if isinstance(s, TagSwitchStmt):
            resolved_expr = self._resolve_expr(s.expr)
            # resolve to the BASE template name for tag enum values
            # e.g. Result_i32_char_ptr → Result  so cases use Result_ok_
            resolved_union = s.cases[0].union_name if s.cases else ""
            if isinstance(s.expr, Ident):
                for frame in reversed(self._var_types):
                    if s.expr.name in frame:
                        mangled = frame[s.expr.name]
                        # find base name from registered union templates
                        if mangled in self._union_templates:
                            resolved_union = mangled
                        else:
                            # mangled name — base is the original template name
                            # look it up from what we instantiated
                            resolved_union = self._tag_base_map.get(mangled, mangled)
                        break
            return TagSwitchStmt(
                expr=resolved_expr,
                cases=[TagCase(
                    union_name=resolved_union,
                    variant_name=c.variant_name,
                    bind_name=c.bind_name,
                    body=self._resolve_block(c.body), line=c.line,
                ) for c in s.cases],
                line=s.line)
        if isinstance(s, AssertStmt):
            return AssertStmt(expr=self._resolve_expr(s.expr), line=s.line)
        if isinstance(s, SwitchStmt):
            return SwitchStmt(
                expr=self._resolve_expr(s.expr),
                cases=[SwitchCase(
                    value=self._resolve_expr(c.value) if c.value else None,
                    body=[self._resolve_stmt(b) for b in c.body],
                    line=c.line,
                ) for c in s.cases],
                line=s.line)
        if isinstance(s, DeferStmt):
            return DeferStmt(body=self._resolve_block(s.body), line=s.line)
        if isinstance(s, DInitCallStmt):
            return DInitCallStmt(expr=self._resolve_expr(s.expr), line=s.line)
        if isinstance(s, Block):
            return self._resolve_block(s)
        return s  # BreakStmt, ContinueStmt

    def _resolve_expr(self, e):
        if e is None:
            return None
        if isinstance(e, TemplateInst):
            resolved_args = [self._resolve_type(a) for a in e.args]
            self._current_line = e.line
            self._instantiate(e.name, resolved_args, e.line)
            mangled = mangle_name(e.name, resolved_args)
            return Ident(name=mangled, line=e.line)
        if isinstance(e, SizeOf):
            return SizeOf(type=self._resolve_type(e.type), line=e.line)
        if isinstance(e, Cast):
            return Cast(type=self._resolve_type(e.type),
                        expr=self._resolve_expr(e.expr), line=e.line)
        if isinstance(e, BinOp):
            return BinOp(op=e.op, left=self._resolve_expr(e.left),
                         right=self._resolve_expr(e.right), line=e.line)
        if isinstance(e, UnaryOp):
            return UnaryOp(op=e.op, operand=self._resolve_expr(e.operand),
                           prefix=e.prefix, line=e.line)
        if isinstance(e, Assign):
            return Assign(op=e.op, left=self._resolve_expr(e.left),
                          right=self._resolve_expr(e.right), line=e.line)
        if isinstance(e, Call):
            return Call(callee=self._resolve_expr(e.callee),
                        args=[self._resolve_expr(a) for a in e.args],
                        line=e.line)
        if isinstance(e, MethodCall):
            return MethodCall(
                receiver=self._resolve_expr(e.receiver),
                method=e.method,
                args=[self._resolve_expr(a) for a in e.args],
                line=e.line)
        if isinstance(e, FieldAccess):
            return FieldAccess(receiver=self._resolve_expr(e.receiver),
                               field=e.field, line=e.line)
        if isinstance(e, Index):
            return Index(receiver=self._resolve_expr(e.receiver),
                         index=self._resolve_expr(e.index), line=e.line)
        if isinstance(e, Ternary):
            return Ternary(cond=self._resolve_expr(e.cond),
                           then=self._resolve_expr(e.then),
                           else_=self._resolve_expr(e.else_), line=e.line)
        if isinstance(e, StructLit):
            return StructLit(
                type=self._resolve_type(e.type) if e.type else None,
                fields=[(n, self._resolve_expr(v)) for n, v in e.fields],
                line=e.line)
        if isinstance(e, NullCoalesce):
            return NullCoalesce(left=self._resolve_expr(e.left),
                                right=self._resolve_expr(e.right), line=e.line)
        return e

    # ── instantiation ─────────────────────────────────────────────────────────

    def _instantiate(self, template_name: str, args: list[TypeName],
                     line: int = 0):
        """
        Produce a concrete StructDecl or TagUnionDecl for the given
        template + argument list, if not already emitted.
        """
        mangled = mangle_name(template_name, args)
        if mangled in self._emitted:
            return
        self._emitted.add(mangled)

        if template_name in self._struct_templates:
            tmpl = self._struct_templates[template_name]
            env  = self._build_env(tmpl.template_params, args, template_name, line)
            # check interface bounds before instantiating
            iface_map  = _checker.build_interface_map(self.prog)
            struct_map = _checker.build_struct_map(self.prog)
            # use merged bounds from _build_env (set above)
            for param_name, bounds in self._param_bounds.items():
                arg_type = env.get(param_name)
                if arg_type:
                    for bound in bounds:
                        _checker.check_bound(arg_type.name, bound,
                                             iface_map, struct_map, line)
            self._instantiate_struct(tmpl, mangled, env)

        elif template_name in self._union_templates:
            tmpl = self._union_templates[template_name]
            env  = self._build_env(tmpl.template_params, args, template_name, line)
            self._instantiate_union(tmpl, mangled, env)

        elif template_name in self._fn_templates:
            tmpl = self._fn_templates[template_name]
            env  = self._build_env(tmpl.template_params, args, template_name, line)
            self._instantiate_fn(tmpl, mangled, env)

        # if not found in templates, it might be a non-template type used
        # with generic syntax — leave it alone

    def _build_env(self, params: list[TemplateParam],
                   args: list[TypeName],
                   template_name: str, line: int) -> dict[str, TypeName]:
        """
        Build substitution env, filling in defaults if needed.
        Params with the same name are merged — they represent multiple bounds
        on a single type parameter, e.g. $template(Drawable T, Resizable T).
        Only unique param names are counted against the arg list.
        """
        # deduplicate params by name, preserving first-seen order
        # collect all bounds per unique name
        seen: dict[str, list[str]] = {}
        unique_params: list[TemplateParam] = []
        for p in params:
            if p.name not in seen:
                seen[p.name] = [p.bound]
                unique_params.append(p)
            else:
                seen[p.name].append(p.bound)

        env: dict[str, TypeName] = {}
        for i, param in enumerate(unique_params):
            if i < len(args):
                env[param.name] = args[i]
            elif param.default is not None:
                env[param.name] = param.default
            else:
                raise MonoError(
                    f"Template '{template_name}' param '{param.name}' "
                    f"has no argument and no default", line)

        # store merged bounds for bound checking: param_name → [bound1, bound2, ...]
        self._param_bounds = seen
        return env

    def _instantiate_struct(self, tmpl: StructDecl,
                             mangled: str, env: dict[str, TypeName]):
        # Self always refers to the concrete mangled name
        self_env = dict(env)
        self_env["Self"] = TypeName(name=mangled)

        new_fields = [Param(
            type=self._resolve_type(subst_type(f.type, self_env)),
            name=f.name,
            default=subst_expr(f.default, self_env) if f.default else None,
        ) for f in tmpl.fields]

        new_methods = []
        for m in tmpl.methods:
            concrete = subst_fn(m, self_env, m.name, receiver_type=mangled)
            resolved = self._resolve_fn(concrete, mangled)
            new_methods.append(resolved)

        self._output.append(StructDecl(
            name=mangled, fields=new_fields, methods=new_methods,
            template_params=[], is_interface=tmpl.is_interface,
            is_union=getattr(tmpl, 'is_union', False),
            implements=tmpl.implements, line=tmpl.line,
        ))

    def _instantiate_union(self, tmpl: TagUnionDecl,
                            mangled: str, env: dict[str, TypeName]):
        self_env = dict(env)
        self_env["Self"] = TypeName(name=mangled)

        new_variants = [Param(
            type=self._resolve_type(subst_type(v.type, self_env)),
            name=v.name,
        ) for v in tmpl.variants]

        new_methods = []
        for m in tmpl.methods:
            concrete = subst_fn(m, self_env, m.name, receiver_type=mangled)
            resolved = self._resolve_fn(concrete, mangled)
            new_methods.append(resolved)

        self._tag_base_map[mangled] = tmpl.name
        self._output.append(TagUnionDecl(
            name=mangled, variants=new_variants, methods=new_methods,
            template_params=[], template_base=tmpl.name, line=tmpl.line,
        ))



    def _instantiate_fn(self, tmpl: FnDecl,
                         mangled: str, env: dict[str, TypeName]):
        concrete = subst_fn(tmpl, env, mangled)
        resolved = self._resolve_fn(concrete, "")
        resolved = FnDecl(
            name=mangled, params=resolved.params,
            return_type=resolved.return_type, body=resolved.body,
            lifecycle=resolved.lifecycle, template_params=[],
            operator=resolved.operator, line=resolved.line,
        )
        self._output.append(resolved)


def monomorphize(prog: Program) -> Program:
    return Monomorphizer(prog).run()
