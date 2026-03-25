"""
CK Parser — recursive descent.
Consumes a token stream from the lexer and produces a Program AST.
"""

from __future__ import annotations
from typing import Optional
from .lexer import Token, TK, tokenize
from .ast import *


import os as _prescan_os

def _prescan_types(tokens: list[Token], source_path: str = "",
                   search_paths: list = None, _visited: set = None) -> set[str]:
    """
    Quick scan of the token stream to collect user-defined type names.
    Also follows $import directives to collect names from imported files.
    """
    if _visited is None:
        _visited = set()
    if source_path:
        _visited = _visited | {source_path}

    names: set[str] = set()
    i = 0
    while i < len(tokens):
        t = tokens[i]

        if t.kind in (TK.STRUCT, TK.UNION, TK.ENUM):
            if i + 1 < len(tokens) and tokens[i+1].kind == TK.IDENT:
                bare = tokens[i+1].value
                names.add(bare)
                for j in range(i-1, -1, -1):
                    if tokens[j].kind == TK.NAMESPACE and j+1 < len(tokens):
                        ns = tokens[j+1].value
                        names.add(f"{ns}_{bare}")
                        break

        # follow $import to collect names from imported files
        if (t.kind == TK.IMPORT
                and i+1 < len(tokens)
                and tokens[i+1].kind == TK.STRING_LIT):
            import_path = tokens[i+1].value
            src_dir = (_prescan_os.path.dirname(_prescan_os.path.abspath(source_path))
                       if source_path else "")
            candidates = []
            if src_dir:
                candidates.append(_prescan_os.path.join(src_dir, import_path))
            for sp in (search_paths or []):
                candidates.append(_prescan_os.path.join(sp, import_path))
                candidates.append(_prescan_os.path.join(
                    sp, _prescan_os.path.basename(import_path)))
            for cand in candidates:
                if _prescan_os.path.exists(cand) and cand not in _visited:
                    try:
                        imp_src = open(cand, encoding="utf-8").read()
                        imp_tokens = tokenize(imp_src, cand)
                        names |= _prescan_types(imp_tokens, cand,
                                                search_paths, _visited | {cand})
                    except Exception:
                        pass  # non-fatal, best-effort prescan
                    break

        i += 1
    return names


class ParseError(Exception):
    def __init__(self, msg: str, line: int, col: int):
        super().__init__(f"[{line}:{col}] ParseError: {msg}")
        self.line = line
        self.col  = col


class Parser:
    def __init__(self, tokens: list[Token], filename: str = "<input>",
                 known_types: set[str] | None = None):
        self.tokens      = tokens
        self.pos         = 0
        self.filename    = filename
        # user-defined type names recognised as template arguments
        # populated by a pre-scan of the token stream
        self._known_types: set[str] = known_types if known_types is not None else _prescan_types(tokens)

    # ── helpers ───────────────────────────────────────────────────────────────

    def _peek(self, offset: int = 0) -> Token:
        i = self.pos + offset
        if i < len(self.tokens):
            return self.tokens[i]
        return self.tokens[-1]  # EOF

    def _advance(self) -> Token:
        t = self.tokens[self.pos]
        if self.pos < len(self.tokens) - 1:
            self.pos += 1
        return t

    def _check(self, *kinds: TK) -> bool:
        return self._peek().kind in kinds

    def _match(self, *kinds: TK) -> Optional[Token]:
        if self._peek().kind in kinds:
            return self._advance()
        return None

    def _expect(self, kind: TK, msg: str = "") -> Token:
        if self._peek().kind != kind:
            t = self._peek()
            raise ParseError(
                msg or f"Expected {kind.name}, got {t.kind.name} ({t.value!r})",
                t.line, t.col
            )
        return self._advance()

    def _error(self, msg: str) -> ParseError:
        t = self._peek()
        return ParseError(msg, t.line, t.col)

    # ── program ───────────────────────────────────────────────────────────────

    def parse(self) -> Program:
        decls = []
        while not self._check(TK.EOF):
            decls.append(self._parse_decl())
        return Program(decls=decls, filename=self.filename)

    # ── declarations ─────────────────────────────────────────────────────────

    def _parse_decl(self) -> Decl:
        t = self._peek()

        if t.kind == TK.IMPORT:
            return self._parse_import()
        if t.kind == TK.CONSTEXPR:
            return self._parse_constexpr()
        if t.kind == TK.IF_:
            return self._parse_conditional_block()
        if t.kind == TK.TEMPLATE:
            return self._parse_template_decl()
        if t.kind == TK.INTERFACE:
            return self._parse_interface_struct()
        if t.kind == TK.IMPLEMENT:
            return self._parse_implement_struct()
        if t.kind == TK.FN:
            return self._parse_fn(template_params=[])
        if t.kind == TK.STRUCT:
            return self._parse_struct(template_params=[], is_interface=False, implements=[])
        if t.kind == TK.UNION:
            return self._parse_plain_union(template_params=[])
        if t.kind == TK.TAG:
            return self._parse_tag_union(template_params=[])
        if t.kind == TK.ENUM:
            return self._parse_enum()
        if t.kind == TK.TYPE:
            return self._parse_type_alias()
        if t.kind == TK.NAMESPACE:
            return self._parse_namespace()
        if t.kind == TK.INCLUDE:
            return self._parse_include()
        if t.kind == TK.EXTERN:
            return self._parse_extern()
        raise self._error(f"Unexpected token at top level: {t.kind.name} ({t.value!r})")

    def _parse_include(self) -> IncludeDecl:
        """Parse: $include <path>; or $include "path";"""
        line = self._peek().line
        self._expect(TK.INCLUDE)
        # the path is either a string literal or an angle-bracket include
        # angle-bracket: lex as LT ... GT — but that's complex
        # simpler: require string literal, user writes "$include "SDL2/SDL.h""
        # OR we handle < specially here by consuming raw tokens
        if self._check(TK.LT):
            # consume everything up to GT as the raw path
            self._advance()  # consume <
            parts = []
            while not self._check(TK.GT, TK.EOF):
                parts.append(self._peek().value)
                self._advance()
            self._expect(TK.GT)
            path = f"<{''.join(parts)}>"
        else:
            path_tok = self._expect(TK.STRING_LIT)
            path = f'"{path_tok.value}"'
        self._match(TK.SEMI)
        return IncludeDecl(path=path, line=line)

    def _parse_extern(self) -> ExternDecl:
        """Parse: $extern { fn ...; struct Name; constexpr ...; }"""
        line = self._peek().line
        self._expect(TK.EXTERN)
        self._expect(TK.LBRACE)
        fns: list = []
        structs: list = []
        full_structs: list = []
        consts: list = []
        while not self._check(TK.RBRACE, TK.EOF):
            t = self._peek()
            if t.kind == TK.FN:
                # forward declaration — no body
                fn = self._parse_fn(template_params=[])
                fns.append(fn)
            elif t.kind == TK.STRUCT:
                # either opaque: struct Name;
                # or full def:   struct Name { fields };
                self._advance()
                name = self._expect(TK.IDENT).value
                if self._check(TK.LBRACE):
                    # full struct definition inside $extern — parse it normally
                    # back up and let _parse_struct handle it
                    self.pos -= 2  # back up past the name and struct keyword
                    sd = self._parse_struct(
                        template_params=[], is_interface=False, implements=[])
                    full_structs.append(sd)
                    self._known_types.add(sd.name)
                else:
                    self._expect(TK.SEMI)
                    structs.append(name)
                    self._known_types.add(name)
            elif t.kind == TK.CONSTEXPR:
                c = self._parse_constexpr()
                consts.append(c)
            else:
                raise self._error(
                    f"Expected fn, struct, or constexpr in $extern block, "
                    f"got {t.kind.name}")
        self._expect(TK.RBRACE)
        self._match(TK.SEMI)  # optional trailing ;
        return ExternDecl(fns=fns, structs=structs,
                          full_structs=full_structs, consts=consts, line=line)

    def _parse_namespace(self) -> NamespaceDecl:
        line = self._peek().line
        self._expect(TK.NAMESPACE)
        name = self._expect(TK.IDENT).value
        self._expect(TK.LBRACE)
        decls = []
        while not self._check(TK.RBRACE, TK.EOF):
            decls.append(self._parse_decl())
        self._expect(TK.RBRACE)
        # register all namespace-qualified names as known types
        for d in decls:
            if hasattr(d, "name"):
                self._known_types.add(f"{name}_{d.name}")
        return NamespaceDecl(name=name, decls=decls, line=line)

    def _parse_type_alias(self) -> TypeAlias:
        line = self._peek().line
        self._expect(TK.TYPE)
        name = self._expect(TK.IDENT).value
        self._expect(TK.ASSIGN)
        t = self._parse_type()
        self._expect(TK.SEMI)
        # register as known type for template arg recognition
        self._known_types.add(name)
        return TypeAlias(name=name, type=t, line=line)

    def _parse_enum(self) -> EnumDecl:
        line = self._peek().line
        self._expect(TK.ENUM)
        name = self._expect(TK.IDENT).value
        # register as known type for template arg lookahead
        self._known_types.add(name)
        self._expect(TK.LBRACE)
        variants = []
        while not self._check(TK.RBRACE, TK.EOF):
            vname = self._expect(TK.IDENT).value
            value = None
            if self._match(TK.ASSIGN):
                value = self._parse_expr()
            variants.append(EnumVariant(name=vname, value=value))
            self._match(TK.COMMA)
        self._expect(TK.RBRACE)
        self._match(TK.SEMI)  # optional trailing semicolon
        return EnumDecl(name=name, variants=variants, line=line)

    def _parse_import(self) -> ImportDecl:
        line = self._peek().line
        self._expect(TK.IMPORT)
        path_tok = self._expect(TK.STRING_LIT, "Expected string path after $import")
        symbols: list[str] = []
        if self._match(TK.LPAREN):
            while not self._check(TK.RPAREN, TK.EOF):
                symbols.append(self._expect(TK.IDENT).value)
                self._match(TK.COMMA)
            self._expect(TK.RPAREN)
        self._expect(TK.SEMI)
        return ImportDecl(path=path_tok.value, symbols=symbols, line=line)

    def _parse_constexpr(self) -> ConstExprDecl:
        line = self._peek().line
        self._expect(TK.CONSTEXPR)
        type_ = self._parse_type()
        name  = self._expect(TK.IDENT).value
        self._expect(TK.ASSIGN)
        value = self._parse_expr()
        self._expect(TK.SEMI)
        return ConstExprDecl(name=name, type=type_, value=value, line=line)

    def _parse_conditional_block(self) -> ConditionalBlock:
        line = self._peek().line
        self._expect(TK.IF_)
        self._expect(TK.LPAREN)
        cond = self._parse_expr()
        self._expect(TK.RPAREN)
        self._expect(TK.LBRACE)
        decls = []
        while not self._check(TK.RBRACE, TK.EOF):
            decls.append(self._parse_decl())
        self._expect(TK.RBRACE)
        return ConditionalBlock(condition=cond, body=decls, line=line)

    def _parse_conditional_stmt(self) -> ConditionalBlock:
        """$if inside a function body — body contains statements."""
        line = self._peek().line
        self._expect(TK.IF_)
        self._expect(TK.LPAREN)
        cond = self._parse_expr()
        self._expect(TK.RPAREN)
        # body is a block of statements, stored as a single Block decl
        block = self._parse_block()
        return ConditionalBlock(condition=cond, body=[block], line=line)

    def _parse_template_params(self) -> list[TemplateParam]:
        self._expect(TK.TEMPLATE)
        self._expect(TK.LPAREN)
        params = []
        while not self._check(TK.RPAREN, TK.EOF):
            # bound can be an ident OR the "type" keyword (which is now TK.TYPE)
            if self._check(TK.TYPE):
                bound = self._advance().value  # "type"
            else:
                bound = self._expect(TK.IDENT, "Expected bound (type, numeric, integer, float, usize, or interface name)").value
            name  = self._expect(TK.IDENT, "Expected parameter name").value
            default = None
            if self._match(TK.ASSIGN):
                default = self._parse_type()
            params.append(TemplateParam(bound=bound, name=name, default=default))
            self._match(TK.COMMA)
        self._expect(TK.RPAREN)
        # register type params so template bodies can parse Result(V, char*) etc.
        for p in params:
            if p.bound in ("type", "integer", "numeric", "float"):
                self._known_types.add(p.name)
        return params

    def _parse_template_decl(self) -> Decl:
        template_params = self._parse_template_params()
        t = self._peek()
        if t.kind == TK.STRUCT:
            return self._parse_struct(template_params, is_interface=False, implements=[])
        if t.kind == TK.UNION:
            return self._parse_plain_union(template_params)
        if t.kind == TK.TAG:
            return self._parse_tag_union(template_params)
        if t.kind == TK.FN:
            return self._parse_fn(template_params)
        if t.kind == TK.INTERFACE:
            return self._parse_interface_struct(template_params)
        if t.kind == TK.IMPLEMENT:
            return self._parse_implement_struct(template_params)
        raise self._error(f"Expected struct, union, or fn after $template(...)")

    def _parse_interface_struct(self, template_params=None) -> StructDecl:
        line = self._peek().line
        self._expect(TK.INTERFACE)
        return self._parse_struct(template_params or [], is_interface=True, implements=[], line=line)

    def _parse_implement_struct(self, template_params=None) -> StructDecl:
        line = self._peek().line
        self._expect(TK.IMPLEMENT)
        self._expect(TK.LPAREN)
        implements = []
        while not self._check(TK.RPAREN, TK.EOF):
            implements.append(self._expect(TK.IDENT).value)
            self._match(TK.COMMA)
        self._expect(TK.RPAREN)
        return self._parse_struct(template_params or [], is_interface=False, implements=implements, line=line)

    def _parse_struct(self, template_params: list[TemplateParam],
                      is_interface: bool, implements: list[str],
                      line: int = 0) -> StructDecl:
        if not line:
            line = self._peek().line
        self._expect(TK.STRUCT)
        name = self._expect(TK.IDENT).value
        self._expect(TK.LBRACE)
        fields: list[Param]  = []
        methods: list[FnDecl] = []
        while not self._check(TK.RBRACE, TK.EOF):
            if self._check(TK.FN) and self._peek(1).kind != TK.LPAREN:
                # fn keyword followed by name = method; fn( = fn-ptr field
                methods.append(self._parse_method())
            else:
                # field: type name[N]?;
                ftype  = self._parse_type()
                # allow keywords as field names (e.g. "type", "default")
                if self._peek().kind == TK.TYPE:
                    fname = self._advance().value
                else:
                    fname = self._expect(TK.IDENT).value
                ftype  = self._parse_array_suffix(ftype)
                default = None
                if self._match(TK.ASSIGN):
                    default = self._parse_expr()
                self._expect(TK.SEMI)
                fields.append(Param(type=ftype, name=fname, default=default))
        self._expect(TK.RBRACE)
        self._expect(TK.SEMI)
        return StructDecl(
            name=name, fields=fields, methods=methods,
            template_params=template_params,
            is_interface=is_interface, implements=implements,
            line=line
        )

    def _parse_method(self) -> FnDecl:
        """Parse a method inside a struct body: fn [$init|$dinit] name(...) -> T { }"""
        line = self._peek().line
        self._expect(TK.FN)
        lifecycle = None
        if self._check(TK.INIT):
            self._advance()
            lifecycle = "init"
        elif self._check(TK.DINIT):
            self._advance()
            lifecycle = "dinit"
        return self._parse_fn_body(template_params=[], lifecycle=lifecycle, line=line)

    def _parse_fn(self, template_params: list[TemplateParam],
                  lifecycle: Optional[str] = None,
                  line: int = 0) -> FnDecl:
        """Parse a top-level fn declaration, consuming the fn keyword itself."""
        if not line:
            line = self._peek().line
        self._expect(TK.FN)
        return self._parse_fn_body(template_params=template_params,
                                   lifecycle=lifecycle, line=line)

    def _parse_fn_body(self, template_params: list[TemplateParam],
                       lifecycle: Optional[str] = None,
                       line: int = 0) -> FnDecl:
        """Parse everything after the fn keyword: name, params, return type, body."""
        # operator overload: fn op+(T other) -> T
        # lexed as IDENT("op") followed by operator token
        operator = None
        _OP_TOKENS = {
            TK.PLUS: "+", TK.MINUS: "-", TK.STAR: "*",
            TK.SLASH: "/", TK.PERCENT: "%",
            TK.EQ: "==", TK.NEQ: "!=",
            TK.LT: "<", TK.GT: ">", TK.LTE: "<=", TK.GTE: ">=",
        }
        if self._peek().kind == TK.IDENT and self._peek().value == "op":
            self._advance()  # consume "op"
            if self._peek().kind in _OP_TOKENS:
                op_sym = _OP_TOKENS[self._advance().kind]
                name   = f"op{op_sym}"
                operator = op_sym
            else:
                # not an operator — treat "op" as a plain method name
                name = "op"
        else:
            name = self._expect(TK.IDENT).value

        self._expect(TK.LPAREN)
        params = []
        while not self._check(TK.RPAREN, TK.EOF):
            ptype = self._parse_type()
            pname = self._expect(TK.IDENT).value
            ptype = self._parse_array_suffix(ptype)
            default = None
            if self._match(TK.ASSIGN):
                default = self._parse_expr()
            params.append(Param(type=ptype, name=pname, default=default))
            self._match(TK.COMMA)
        self._expect(TK.RPAREN)

        return_type = TypeName("void")
        if self._match(TK.ARROW):
            return_type = self._parse_type()

        body = None
        if self._check(TK.LBRACE):
            body = self._parse_block()
        else:
            self._expect(TK.SEMI)

        return FnDecl(
            name=name, params=params, return_type=return_type,
            body=body, lifecycle=lifecycle,
            template_params=template_params, operator=operator,
            line=line
        )

    def _parse_plain_union(self, template_params) -> StructDecl:
        """Parse a plain C-style union: union Name { fields; }"""
        line = self._peek().line
        self._expect(TK.UNION)
        name = self._expect(TK.IDENT).value
        self._known_types.add(name)
        self._expect(TK.LBRACE)
        fields = []
        while not self._check(TK.RBRACE, TK.EOF):
            ftype = self._parse_type()
            if self._peek().kind == TK.TYPE:
                fname = self._advance().value
            else:
                fname = self._expect(TK.IDENT).value
            ftype = self._parse_array_suffix(ftype)
            self._expect(TK.SEMI)
            fields.append(Param(type=ftype, name=fname))
        self._expect(TK.RBRACE)
        self._match(TK.SEMI)
        return StructDecl(name=name, fields=fields, methods=[],
                          template_params=template_params,
                          is_union=True, line=line)

    def _parse_tag_union(self, template_params: list[TemplateParam]) -> TagUnionDecl:
        line = self._peek().line
        self._expect(TK.TAG)
        self._expect(TK.UNION)
        name = self._expect(TK.IDENT).value
        self._expect(TK.LBRACE)
        variants: list[Param]  = []
        methods:  list[FnDecl] = []
        while not self._check(TK.RBRACE, TK.EOF):
            if self._check(TK.FN):
                methods.append(self._parse_method())
            else:
                vtype = self._parse_type()
                vname = self._expect(TK.IDENT).value
                self._expect(TK.SEMI)
                variants.append(Param(type=vtype, name=vname))
        self._expect(TK.RBRACE)
        self._expect(TK.SEMI)
        return TagUnionDecl(
            name=name, variants=variants, methods=methods,
            template_params=template_params, line=line
        )

    # ── types ─────────────────────────────────────────────────────────────────

    def _parse_type(self) -> TypeName:
        # optional const prefix
        const = False
        if self._peek().kind == TK.IDENT and self._peek().value == "const":
            self._advance()
            const = True

        # function pointer type: fn(T1, T2) -> R
        if self._peek().kind == TK.FN:
            return self._parse_fnptr_type()

        # base type name
        name_tok = self._peek()
        if name_tok.kind in (TK.IDENT, TK.SELF_TYPE):
            name = self._advance().value
            # namespace::Type → namespace_Type (chain multiple ::)
            while self._check(TK.COLONCOLON):
                self._advance()
                member = self._expect(TK.IDENT).value
                name = f"{name}_{member}"
        elif name_tok.value in ("void",):
            name = self._advance().value
        else:
            raise self._error(f"Expected type name, got {name_tok.kind.name} ({name_tok.value!r})")

        # optional template args: vector(i32) / Result(T, E)
        # In a type context, Name(...) is ALWAYS a template instantiation —
        # no ambiguity with function calls, so no lookahead guard needed.
        args = []
        if self._check(TK.LPAREN):
            self._advance()  # consume (
            while not self._check(TK.RPAREN, TK.EOF):
                # integer literals are valid template args: fixed_array(i32, 4)
                if self._peek().kind == TK.INT_LIT:
                    val = self._advance().value
                    args.append(TypeName(name=val))
                else:
                    args.append(self._parse_type())
                self._match(TK.COMMA)
            self._expect(TK.RPAREN)

        # pointer/ref qualifiers
        pointer = bool(self._match(TK.STAR))
        ref     = bool(self._match(TK.AMP))

        return TypeName(name=name, args=args, pointer=pointer, ref=ref, const=const)

    def _parse_fnptr_type(self) -> TypeName:
        """Parse: fn(T1, T2, ...) -> R  as a function pointer type."""
        self._expect(TK.FN)
        self._expect(TK.LPAREN)
        params = []
        while not self._check(TK.RPAREN, TK.EOF):
            params.append(self._parse_type())
            self._match(TK.COMMA)
        self._expect(TK.RPAREN)
        ret = TypeName(name="void")
        if self._match(TK.ARROW):
            ret = self._parse_type()
        pointer = bool(self._match(TK.STAR))
        ref     = bool(self._match(TK.AMP))
        return TypeName(name="__fnptr__", fn_params=params, fn_ret=ret,
                        pointer=pointer, ref=ref)

    def _parse_array_suffix(self, t: TypeName) -> TypeName:
        """
        If the next token is [ parse T[N] array suffix.
        Called after parsing a variable name in declarations.
        Returns a new TypeName with array_size set, or the original if no [.
        """
        if not self._check(TK.LBRACKET):
            return t
        self._advance()  # consume [
        # size can be an integer literal, ident (constexpr), or template param
        size_tok = self._peek()
        if size_tok.kind == TK.INT_LIT:
            size = self._advance().value
        elif size_tok.kind == TK.IDENT:
            size = self._advance().value
        else:
            raise self._error(f"Expected array size (integer or name), got {size_tok.kind.name}")
        self._expect(TK.RBRACKET)
        return TypeName(name=t.name, args=t.args, pointer=t.pointer,
                        ref=t.ref, const=t.const, array_size=size)

    # ── statements ────────────────────────────────────────────────────────────

    def _parse_block(self) -> Block:
        line = self._peek().line
        self._expect(TK.LBRACE)
        stmts = []
        while not self._check(TK.RBRACE, TK.EOF):
            stmts.append(self._parse_stmt())
        self._expect(TK.RBRACE)
        return Block(stmts=stmts, line=line)

    def _parse_stmt(self) -> Stmt:
        t = self._peek()

        if t.kind == TK.RETURN:
            return self._parse_return()
        if t.kind == TK.LET:
            return self._parse_let()
        if t.kind == TK.IF:
            return self._parse_if()
        if t.kind == TK.FOR:
            return self._parse_for()
        if t.kind == TK.WHILE:
            return self._parse_while()
        if t.kind == TK.BREAK:
            self._advance(); self._expect(TK.SEMI)
            return BreakStmt(line=t.line)
        if t.kind == TK.CONTINUE:
            self._advance(); self._expect(TK.SEMI)
            return ContinueStmt(line=t.line)
        if t.kind == TK.AUTO:
            return self._parse_auto()
        if t.kind == TK.TYPE:
            # type alias inside function body — treat as a local type declaration
            # In generated C this just emits a typedef
            return self._parse_type_alias_stmt()
        if t.kind == TK.DEFER:
            return self._parse_defer()
        if t.kind == TK.DINIT and self._peek(1).kind == TK.LPAREN:
            return self._parse_dinit_call()
        if t.kind == TK.ASSERT:
            return self._parse_assert()
        if t.kind == TK.TAG:
            return self._parse_tag_switch()
        if t.kind == TK.SWITCH:
            return self._parse_switch()
        if t.kind == TK.IF_:
            return self._parse_conditional_stmt()
        if t.kind == TK.LBRACE:
            return self._parse_block()

        # fn-pointer variable: fn(...) -> R name = expr;
        if t.kind == TK.FN and self._is_fnptr_decl_lookahead():
            return self._parse_var_decl()
        # variable declaration: type name = expr; OR type name;
        if self._is_type_start() and self._is_decl_lookahead():
            return self._parse_var_decl()

        # expression statement
        expr = self._parse_expr()
        self._expect(TK.SEMI)
        return ExprStmt(expr=expr, line=t.line)

    def _is_type_start(self) -> bool:
        t = self._peek()
        if t.kind == TK.IDENT:
            return True
        if t.kind == TK.SELF_TYPE:
            return True
        if t.value in ("void", "const"):
            return True
        if t.kind == TK.FN:
            return True   # fn(...)->R is a function pointer type
        return False

    def _is_fnptr_decl_lookahead(self) -> bool:
        """Peek: fn(...)->R name — function pointer variable declaration."""
        saved = self.pos
        try:
            if not self._check(TK.FN): return False
            self._advance()  # fn
            if not self._check(TK.LPAREN): return False
            # skip param list
            depth = 1; self._advance()
            while depth > 0 and not self._check(TK.EOF):
                if self._check(TK.LPAREN): depth += 1
                if self._check(TK.RPAREN): depth -= 1
                self._advance()
            # optional -> R
            if self._check(TK.ARROW):
                self._advance()
                # skip return type (ident, optional * &, optional template args)
                if not self._check(TK.IDENT, TK.SELF_TYPE): return False
                self._advance()
                while self._check(TK.STAR, TK.AMP): self._advance()
            # now we need an ident (the variable name)
            return self._check(TK.IDENT)
        finally:
            self.pos = saved

    def _is_cast_lookahead(self) -> bool:
        """Peek: type [* | &]* ) — indicates a C-style cast."""
        saved = self.pos
        try:
            if self._peek().kind == TK.IDENT and self._peek().value == "const":
                self._advance()
            if not self._check(TK.IDENT, TK.SELF_TYPE):
                return False
            self._advance()  # type name
            # optional ::
            while self._check(TK.COLONCOLON):
                self._advance()
                if not self._check(TK.IDENT): return False
                self._advance()
            # optional template args
            if self._check(TK.LPAREN):
                depth = 1
                self._advance()
                while depth > 0 and not self._check(TK.EOF):
                    if self._check(TK.LPAREN): depth += 1
                    if self._check(TK.RPAREN): depth -= 1
                    self._advance()
            # optional * or &
            while self._check(TK.STAR, TK.AMP):
                self._advance()
            return self._check(TK.RPAREN)
        finally:
            self.pos = saved

    def _is_decl_lookahead(self) -> bool:
        """Peek ahead: type [::member]? [* | &]* ident — heuristic."""
        saved = self.pos
        try:
            # skip const
            if self._peek().kind == TK.IDENT and self._peek().value == "const":
                self._advance()
            if not self._check(TK.IDENT, TK.SELF_TYPE):
                return False
            self._advance()  # type name
            # optional namespace::member::member (chain)
            while self._check(TK.COLONCOLON):
                self._advance()
                if not self._check(TK.IDENT):
                    return False
                self._advance()
            # optional template args
            if self._check(TK.LPAREN):
                depth = 0
                while not self._check(TK.EOF):
                    if self._check(TK.LPAREN): depth += 1
                    if self._check(TK.RPAREN):
                        depth -= 1
                        self._advance()
                        if depth == 0: break
                    else:
                        self._advance()
            # optional * or &
            while self._check(TK.STAR, TK.AMP):
                self._advance()
            # must be followed by an ident
            return self._check(TK.IDENT)
        finally:
            self.pos = saved

    def _parse_var_decl(self) -> LetStmt:
        line = self._peek().line
        type_ = self._parse_type()
        name  = self._expect(TK.IDENT).value
        type_ = self._parse_array_suffix(type_)  # handle T name[N]
        value = None
        if self._match(TK.ASSIGN):
            value = self._parse_expr()
        self._expect(TK.SEMI)
        return LetStmt(type=type_, name=name, value=value, line=line)

    def _parse_return(self) -> ReturnStmt:
        line = self._peek().line
        self._expect(TK.RETURN)
        value = None
        if not self._check(TK.SEMI):
            value = self._parse_expr()
        self._expect(TK.SEMI)
        return ReturnStmt(value=value, line=line)

    def _parse_let(self) -> LetStmt:
        line = self._peek().line
        self._expect(TK.LET)
        type_ = self._parse_type()
        name  = self._expect(TK.IDENT).value
        type_ = self._parse_array_suffix(type_)
        value = None
        if self._match(TK.ASSIGN):
            value = self._parse_expr()
        self._expect(TK.SEMI)
        return LetStmt(type=type_, name=name, value=value, line=line)

    def _parse_if(self) -> IfStmt:
        line = self._peek().line
        self._expect(TK.IF)
        self._expect(TK.LPAREN)
        cond = self._parse_expr()
        self._expect(TK.RPAREN)
        # allow single-statement body without braces
        if self._check(TK.LBRACE):
            then = self._parse_block()
        else:
            stmt = self._parse_stmt()
            then = Block(stmts=[stmt], line=stmt.line if hasattr(stmt, "line") else line)
        else_ = None
        if self._match(TK.ELSE):
            if self._check(TK.IF):
                else_ = Block(stmts=[self._parse_if()], line=self._peek().line)
            elif self._check(TK.LBRACE):
                else_ = self._parse_block()
            else:
                stmt = self._parse_stmt()
                else_ = Block(stmts=[stmt], line=stmt.line if hasattr(stmt, "line") else line)
        return IfStmt(cond=cond, then=then, else_=else_, line=line)

    def _parse_for(self) -> ForStmt:
        line = self._peek().line
        self._expect(TK.FOR)
        self._expect(TK.LPAREN)
        # init
        init = None
        if not self._check(TK.SEMI):
            if self._is_type_start() and self._is_decl_lookahead():
                init = self._parse_var_decl()
            else:
                expr = self._parse_expr()
                self._expect(TK.SEMI)
                init = ExprStmt(expr=expr, line=line)
        else:
            self._expect(TK.SEMI)
        # cond
        cond = None
        if not self._check(TK.SEMI):
            cond = self._parse_expr()
        self._expect(TK.SEMI)
        # post
        post = None
        if not self._check(TK.RPAREN):
            post = self._parse_expr()
        self._expect(TK.RPAREN)
        body = self._parse_block()
        return ForStmt(init=init, cond=cond, post=post, body=body, line=line)

    def _parse_while(self) -> WhileStmt:
        line = self._peek().line
        self._expect(TK.WHILE)
        self._expect(TK.LPAREN)
        cond = self._parse_expr()
        self._expect(TK.RPAREN)
        if self._check(TK.LBRACE):
            body = self._parse_block()
        else:
            stmt = self._parse_stmt()
            body = Block(stmts=[stmt],
                         line=stmt.line if hasattr(stmt, 'line') else line)
        return WhileStmt(cond=cond, body=body, line=line)

    def _parse_switch(self) -> "SwitchStmt":
        line = self._peek().line
        self._expect(TK.SWITCH)
        self._expect(TK.LPAREN)
        expr = self._parse_expr()
        self._expect(TK.RPAREN)
        self._expect(TK.LBRACE)
        cases = []
        while not self._check(TK.RBRACE, TK.EOF):
            if self._check(TK.CASE):
                self._advance()
                val = self._parse_expr()
                self._expect(TK.COLON)
                body = []
                while not self._check(TK.CASE, TK.DEFAULT, TK.RBRACE, TK.EOF):
                    body.append(self._parse_stmt())
                cases.append(SwitchCase(value=val, body=body, line=line))
            elif self._check(TK.DEFAULT):
                self._advance()
                self._expect(TK.COLON)
                body = []
                while not self._check(TK.CASE, TK.DEFAULT, TK.RBRACE, TK.EOF):
                    body.append(self._parse_stmt())
                cases.append(SwitchCase(value=None, body=body, line=line))
            else:
                break
        self._expect(TK.RBRACE)
        return SwitchStmt(expr=expr, cases=cases, line=line)

    def _parse_type_alias_stmt(self):
        """type Foo = T; inside a function body — emit as typedef."""
        return self._parse_type_alias()  # reuse top-level parser, returns TypeAlias

    def _parse_dinit_call(self) -> DInitCallStmt:
        """Parse: $dinit(expr); — explicit dinit call on a value"""
        line = self._peek().line
        self._expect(TK.DINIT)
        self._expect(TK.LPAREN)
        expr = self._parse_expr()
        self._expect(TK.RPAREN)
        self._match(TK.SEMI)
        return DInitCallStmt(expr=expr, line=line)

    def _parse_defer(self) -> DeferStmt:
        line = self._peek().line
        self._expect(TK.DEFER)
        body = self._parse_block()
        return DeferStmt(body=body, line=line)

    def _parse_auto(self) -> LetStmt:
        """Parse: auto name = expr;"""
        line = self._peek().line
        self._expect(TK.AUTO)
        name = self._expect(TK.IDENT).value
        self._expect(TK.ASSIGN)
        value = self._parse_expr()
        self._expect(TK.SEMI)
        return LetStmt(type=AUTO_TYPE, name=name, value=value, line=line)

    def _parse_assert(self) -> AssertStmt:
        line = self._peek().line
        self._expect(TK.ASSERT)
        self._expect(TK.LPAREN)
        expr = self._parse_expr()
        self._expect(TK.RPAREN)
        self._expect(TK.SEMI)
        return AssertStmt(expr=expr, line=line)

    def _parse_tag_switch(self) -> TagSwitchStmt:
        line = self._peek().line
        self._expect(TK.TAG)
        self._expect(TK.SWITCH)
        self._expect(TK.LPAREN)
        expr = self._parse_expr()
        self._expect(TK.RPAREN)
        self._expect(TK.LBRACE)
        cases = []
        while not self._check(TK.RBRACE, TK.EOF):
            cases.append(self._parse_tag_case())
        self._expect(TK.RBRACE)
        return TagSwitchStmt(expr=expr, cases=cases, line=line)

    def _parse_tag_case(self) -> TagCase:
        line = self._peek().line
        self._expect(TK.CASE)
        self._expect(TK.LPAREN)
        union_name   = self._expect(TK.IDENT).value
        self._expect(TK.DOT)
        variant_name = self._expect(TK.IDENT).value
        bind_name    = self._expect(TK.IDENT).value
        self._expect(TK.RPAREN)
        self._expect(TK.COLON)
        body = self._parse_block()
        return TagCase(union_name=union_name, variant_name=variant_name,
                       bind_name=bind_name, body=body, line=line)

    # ── expressions (Pratt-style precedence) ──────────────────────────────────

    def _parse_expr(self) -> Expr:
        return self._parse_assign()

    def _parse_assign(self) -> Expr:
        left = self._parse_ternary()
        op_map = {
            TK.ASSIGN: "=", TK.PLUS_EQ: "+=", TK.MINUS_EQ: "-=",
            TK.STAR_EQ: "*=", TK.SLASH_EQ: "/=",
        }
        if self._peek().kind in op_map:
            op  = op_map[self._advance().kind]
            right = self._parse_assign()
            return Assign(op=op, left=left, right=right, line=left.line)
        return left

    def _parse_ternary(self) -> Expr:
        cond = self._parse_nullcoal()
        if self._match(TK.QUESTION):
            then  = self._parse_expr()
            self._expect(TK.COLON)
            else_ = self._parse_expr()
            return Ternary(cond=cond, then=then, else_=else_, line=cond.line)
        return cond

    def _parse_nullcoal(self) -> Expr:
        left = self._parse_or()
        if self._match(TK.NULLCOAL):
            right = self._parse_or()
            return NullCoalesce(left=left, right=right, line=left.line)
        return left

    def _parse_or(self) -> Expr:
        left = self._parse_and()
        while self._match(TK.OR):
            right = self._parse_and()
            left = BinOp(op="||", left=left, right=right, line=left.line)
        return left

    def _parse_and(self) -> Expr:
        left = self._parse_bitor()
        while self._match(TK.AND):
            right = self._parse_bitor()
            left = BinOp(op="&&", left=left, right=right, line=left.line)
        return left

    def _parse_bitor(self) -> Expr:
        left = self._parse_bitxor()
        while self._check(TK.PIPE):
            self._advance()
            right = self._parse_bitxor()
            left = BinOp(op="|", left=left, right=right, line=left.line)
        return left

    def _parse_bitxor(self) -> Expr:
        left = self._parse_bitand()
        while self._check(TK.CARET):
            self._advance()
            right = self._parse_bitand()
            left = BinOp(op="^", left=left, right=right, line=left.line)
        return left

    def _parse_bitand(self) -> Expr:
        left = self._parse_eq()
        while self._check(TK.AMP) and self._peek(1).kind != TK.AMP:
            self._advance()
            right = self._parse_eq()
            left = BinOp(op="&", left=left, right=right, line=left.line)
        return left

    def _parse_eq(self) -> Expr:
        left = self._parse_cmp()
        while self._check(TK.EQ, TK.NEQ):
            op = self._advance().value
            right = self._parse_cmp()
            left = BinOp(op=op, left=left, right=right, line=left.line)
        return left

    def _parse_cmp(self) -> Expr:
        left = self._parse_shift()
        while self._check(TK.LT, TK.GT, TK.LTE, TK.GTE):
            op = self._advance().value
            right = self._parse_shift()
            left = BinOp(op=op, left=left, right=right, line=left.line)
        return left

    def _parse_shift(self) -> Expr:
        left = self._parse_add()
        while self._check(TK.LSHIFT, TK.RSHIFT):
            op = self._advance().value
            right = self._parse_add()
            left = BinOp(op=op, left=left, right=right, line=left.line)
        return left

    def _parse_add(self) -> Expr:
        left = self._parse_mul()
        while self._check(TK.PLUS, TK.MINUS):
            op = self._advance().value
            right = self._parse_mul()
            left = BinOp(op=op, left=left, right=right, line=left.line)
        return left

    def _parse_mul(self) -> Expr:
        left = self._parse_unary()
        while self._check(TK.STAR, TK.SLASH, TK.PERCENT):
            op = self._advance().value
            right = self._parse_unary()
            left = BinOp(op=op, left=left, right=right, line=left.line)
        return left

    def _parse_unary(self) -> Expr:
        t = self._peek()
        if t.kind == TK.BANG:
            self._advance()
            return UnaryOp(op="!", operand=self._parse_unary(), prefix=True, line=t.line)
        if t.kind == TK.MINUS:
            self._advance()
            return UnaryOp(op="-", operand=self._parse_unary(), prefix=True, line=t.line)
        if t.kind == TK.TILDE:
            self._advance()
            return UnaryOp(op="~", operand=self._parse_unary(), prefix=True, line=t.line)
        if t.kind == TK.STAR:
            self._advance()
            return UnaryOp(op="*", operand=self._parse_unary(), prefix=True, line=t.line)
        if t.kind == TK.AMP:
            self._advance()
            return UnaryOp(op="&", operand=self._parse_unary(), prefix=True, line=t.line)
        if t.kind == TK.PLUSPLUS:
            self._advance()
            return UnaryOp(op="++", operand=self._parse_unary(), prefix=True, line=t.line)
        if t.kind == TK.MINUSMINUS:
            self._advance()
            return UnaryOp(op="--", operand=self._parse_unary(), prefix=True, line=t.line)
        return self._parse_postfix()

    def _parse_postfix(self) -> Expr:
        expr = self._parse_primary()
        while True:
            t = self._peek()
            if t.kind == TK.DOT or t.kind == TK.ARROW:
                self._advance()
                # allow keywords as field names after . or ->
                if self._peek().kind in (TK.TYPE, TK.NAMESPACE, TK.ENUM,
                                          TK.STRUCT, TK.UNION, TK.DEFAULT):
                    field = self._advance().value
                else:
                    field = self._expect(TK.IDENT).value
                # -> dereferences the pointer first: p->f is (*p).f
                receiver = expr
                if t.kind == TK.ARROW:
                    receiver = UnaryOp(op="*", operand=expr, prefix=True, line=t.line)
                if self._check(TK.LPAREN):
                    args = self._parse_arg_list()
                    expr = MethodCall(receiver=receiver, method=field, args=args, line=t.line)
                else:
                    expr = FieldAccess(receiver=receiver, field=field, line=t.line)
            elif t.kind == TK.LPAREN:
                args = self._parse_arg_list()
                expr = Call(callee=expr, args=args, line=t.line)
            elif t.kind == TK.LBRACKET:
                self._advance()
                idx = self._parse_expr()
                self._expect(TK.RBRACKET)
                expr = Index(receiver=expr, index=idx, line=t.line)
            elif t.kind == TK.PLUSPLUS:
                self._advance()
                expr = UnaryOp(op="++", operand=expr, prefix=False, line=t.line)
            elif t.kind == TK.MINUSMINUS:
                self._advance()
                expr = UnaryOp(op="--", operand=expr, prefix=False, line=t.line)
            else:
                break
        return expr

    def _parse_arg_list(self) -> list[Expr]:
        self._expect(TK.LPAREN)
        args = []
        while not self._check(TK.RPAREN, TK.EOF):
            args.append(self._parse_expr())
            self._match(TK.COMMA)
        self._expect(TK.RPAREN)
        return args

    def _parse_primary(self) -> Expr:
        t = self._peek()

        if t.kind == TK.INT_LIT:
            self._advance()
            raw = t.value.rstrip("uUlL")
            return IntLit(value=int(raw, 0), line=t.line)

        if t.kind == TK.FLOAT_LIT:
            self._advance()
            return FloatLit(value=float(t.value.rstrip("fF")), line=t.line)

        if t.kind == TK.STRING_LIT:
            self._advance()
            return StringLit(value=t.value, line=t.line)
        
        if t.kind == TK.CHAR_LIT:
            self._advance()
            # Basic unquoting and escape handling for the bootstrap
            val = t.value
            if val.startswith("'") and val.endswith("'"):
                val = val[1:-1]
            
            # Simple escape translation if your lexer doesn't do it
            if val.startswith("\\") and len(val) > 1:
                escapes = {'n': '\n', 'r': '\r', 't': '\t', '0': '\0', '\\': '\\', "'": "'"}
                char_code = val[1]
                val = escapes.get(char_code, char_code)
                
            return CharLit(value=val, line=t.line)

        if t.kind == TK.TRUE:
            self._advance(); return BoolLit(value=True, line=t.line)

        if t.kind == TK.FALSE:
            self._advance(); return BoolLit(value=False, line=t.line)

        if t.kind == TK.NULL:
            self._advance(); return NullLit(line=t.line)

        if t.kind == TK.SELF:
            self._advance(); return SelfExpr(line=t.line)

        if t.kind == TK.SIZEOF:
            self._advance()
            self._expect(TK.LPAREN)
            type_ = self._parse_type()
            self._expect(TK.RPAREN)
            return SizeOf(type=type_, line=t.line)

        if t.kind == TK.LPAREN:
            self._advance()
            # check for C-style cast: (type)expr
            # heuristic: if content is a type name followed by ), it's a cast
            if self._is_type_start() and self._is_cast_lookahead():
                cast_type = self._parse_type()
                self._expect(TK.RPAREN)
                operand = self._parse_unary()
                return Cast(type=cast_type, expr=operand, line=t.line)
            expr = self._parse_expr()
            self._expect(TK.RPAREN)
            return expr

        if t.kind == TK.LBRACE:
            return self._parse_struct_lit()

        if t.kind == TK.IDENT:
            self._advance()
            # namespace access: a::b::c — collapse to a_b_c ident (chain)
            if self._check(TK.COLONCOLON):
                ns_name = t.value
                while self._check(TK.COLONCOLON):
                    self._advance()  # consume ::
                    member = self._expect(TK.IDENT).value
                    ns_name = f"{ns_name}_{member}"
                # check for template instantiation after ::
                if self._check(TK.LPAREN) and self._is_template_inst_lookahead():
                    args = self._parse_template_arg_list()
                    return TemplateInst(name=ns_name, args=args, line=t.line)
                return Ident(name=ns_name, line=t.line)
            # check for template instantiation: name(type, ...)
            if self._check(TK.LPAREN) and self._is_template_inst_lookahead():
                args = self._parse_template_arg_list()
                return TemplateInst(name=t.value, args=args, line=t.line)
            return Ident(name=t.value, line=t.line)

        raise self._error(f"Unexpected token in expression: {t.kind.name} ({t.value!r})")

    # Primitive and well-known type names — used to distinguish
    # template instantiation (vector(int)) from a function call (foo(x))
    _TYPE_NAMES = {
        "i8","i16","i32","i64","u8","u16","u32","u64",
        "f32","f64","usize","bool","void","char",
        "Self","size_t","int8_t","int16_t","int32_t","int64_t",
        "uint8_t","uint16_t","uint32_t","uint64_t",
    }

    def _is_template_inst_lookahead(self) -> bool:
        """
        Distinguish vector(int) from realloc(data, n).
        Rule: the first argument inside ( must be a known primitive type name
        optionally followed by * or &, then ) or ,.
        We do NOT treat arbitrary identifiers as types here — that would cause
        realloc(data, ...) to be misread as a template instantiation.
        """
        saved = self.pos
        try:
            self._advance()  # consume (
            if self._check(TK.RPAREN): return False  # empty () — not a template inst
            # skip optional 'const' qualifier
            if self._check(TK.IDENT) and self._peek().value == "const":
                self._advance()
            if not self._check(TK.IDENT, TK.SELF_TYPE):
                return False
            name = self._peek().value
            if name not in self._TYPE_NAMES and name not in self._known_types:
                return False
            self._advance()
            # optional nested template args
            if self._check(TK.LPAREN):
                return True   # e.g. Result(vector(int), char*)
            # optional ptr/ref qualifiers
            while self._check(TK.STAR, TK.AMP):
                self._advance()
            # must close or continue with another type arg
            return self._check(TK.RPAREN, TK.COMMA)
        finally:
            self.pos = saved

    def _parse_template_arg_list(self) -> list[TypeName]:
        self._expect(TK.LPAREN)
        args = []
        while not self._check(TK.RPAREN, TK.EOF):
            # numeric literals like 4, 16 are valid template args for usize N params
            if self._peek().kind == TK.INT_LIT:
                val = self._advance().value
                args.append(TypeName(name=val))
            else:
                args.append(self._parse_type())
            self._match(TK.COMMA)
        self._expect(TK.RPAREN)
        return args

    def _parse_struct_lit(self) -> StructLit:
        line = self._peek().line
        self._expect(TK.LBRACE)
        fields = []
        while not self._check(TK.RBRACE, TK.EOF):
            if self._check(TK.DOT):
                # .field = expr
                self._advance()
                fname = self._expect(TK.IDENT).value
                self._expect(TK.ASSIGN)
                val = self._parse_expr()
                fields.append((fname, val))
            else:
                fields.append((None, self._parse_expr()))
            self._match(TK.COMMA)
        self._expect(TK.RBRACE)
        return StructLit(type=None, fields=fields, line=line)


def parse(tokens: list[Token], filename: str = "<input>",
          known_types: set[str] | None = None,
          search_paths: list | None = None) -> Program:
    # if no known_types provided, prescan with import-following
    if known_types is None:
        known_types = _prescan_types(tokens,
                                      source_path=filename,
                                      search_paths=search_paths or [])
    return Parser(tokens, filename, known_types=known_types).parse()
