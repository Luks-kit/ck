"""
CK Lexer
Tokenizes .ck source into a flat token stream.
"""

import re
from dataclasses import dataclass
from enum import Enum, auto


class TK(Enum):
    # literals
    INT_LIT    = auto()
    FLOAT_LIT  = auto()
    STRING_LIT = auto()
    CHAR_LIT   = auto()
    BOOL_LIT   = auto()
    NULL       = auto()

    # identifiers & keywords
    IDENT      = auto()

    # $ annotations
    DOLLAR     = auto()   # bare $, shouldn't appear after lexing
    IMPORT     = auto()   # $import
    TEMPLATE   = auto()   # $template
    INTERFACE  = auto()   # $interface
    IMPLEMENT  = auto()   # $implement
    INIT       = auto()   # $init
    DINIT      = auto()   # $dinit
    TAG        = auto()   # $tag
    IF_        = auto()   # $if   (IF_ to avoid clash with IF)
    SCOPE      = auto()   # reserved
    OWN        = auto()   # reserved
    DEFER      = auto()   # $defer
    INCLUDE    = auto()   # $include
    EXTERN     = auto()   # $extern

    # keywords
    FN         = auto()
    STRUCT     = auto()
    UNION      = auto()
    ENUM       = auto()
    RETURN     = auto()
    IF         = auto()
    ELSE       = auto()
    FOR        = auto()
    WHILE      = auto()
    BREAK      = auto()
    CONTINUE   = auto()
    SWITCH     = auto()
    STATIC     = auto()
    CASE       = auto()
    DEFAULT    = auto()
    LET        = auto()
    CONSTEXPR  = auto()
    TYPEDEF    = auto()
    TYPE       = auto()   # type alias: type Foo = Bar
    NAMESPACE  = auto()   # namespace keyword
    COLONCOLON = auto()   # :: namespace separator
    LSHIFT     = auto()   # <<
    RSHIFT     = auto()   # >>
    AUTO       = auto()   # type deduction
    SIZEOF     = auto()
    SELF       = auto()
    SELF_TYPE  = auto()   # Self (capital)
    ASSERT     = auto()
    TRUE       = auto()
    FALSE      = auto()

    # punctuation
    LPAREN     = auto()   # (
    RPAREN     = auto()   # )
    LBRACE     = auto()   # {
    RBRACE     = auto()   # }
    LBRACKET   = auto()   # [
    RBRACKET   = auto()   # ]
    SEMI       = auto()   # ;
    COLON      = auto()   # :
    COMMA      = auto()   # ,
    DOT        = auto()   # .
    ARROW      = auto()   # ->
    QUESTION   = auto()   # ?
    NULLCOAL   = auto()   # ??

    # type modifiers
    STAR       = auto()   # *  (pointer)
    AMP        = auto()   # &  (reference)

    # arithmetic operators
    PLUS       = auto()   # +
    MINUS      = auto()   # -
    SLASH      = auto()   # /
    PERCENT    = auto()   # %

    # comparison
    EQ         = auto()   # ==
    NEQ        = auto()   # !=
    LT         = auto()   # <
    GT         = auto()   # >
    LTE        = auto()   # <=
    GTE        = auto()   # >=

    # logical
    AND        = auto()   # &&
    OR         = auto()   # ||
    BANG       = auto()   # !

    # assignment
    ASSIGN     = auto()   # =
    PLUS_EQ    = auto()   # +=
    MINUS_EQ   = auto()   # -=
    STAR_EQ    = auto()   # *=
    SLASH_EQ   = auto()   # /=

    # bitwise
    PIPE       = auto()   # |
    CARET      = auto()   # ^
    TILDE      = auto()   # ~

    # increment/decrement
    PLUSPLUS   = auto()   # ++
    MINUSMINUS = auto()   # --

    # special
    EOF        = auto()
    NEWLINE    = auto()   # not emitted, used internally


# keywords that map directly to token kinds
_KEYWORDS = {
    "fn":       TK.FN,
    "static":   TK.STATIC,
    "struct":   TK.STRUCT,
    "union":    TK.UNION,
    "enum":     TK.ENUM,
    "return":   TK.RETURN,
    "if":       TK.IF,
    "else":     TK.ELSE,
    "for":      TK.FOR,
    "while":    TK.WHILE,
    "break":    TK.BREAK,
    "continue": TK.CONTINUE,
    "switch":   TK.SWITCH,
    "case":     TK.CASE,
    "default":  TK.DEFAULT,
    "let":      TK.LET,
    "constexpr":TK.CONSTEXPR,
    "typedef":  TK.TYPEDEF,
    "type":     TK.TYPE,
    "namespace": TK.NAMESPACE,
    "auto":      TK.AUTO,
    "sizeof":   TK.SIZEOF,
    "self":     TK.SELF,
    "Self":     TK.SELF_TYPE,
    "assert":   TK.ASSERT,
    "true":     TK.TRUE,
    "false":    TK.FALSE,
    "null":     TK.NULL,
}

# $-prefixed annotations
_DOLLAR_KEYWORDS = {
    "import":    TK.IMPORT,
    "template":  TK.TEMPLATE,
    "interface": TK.INTERFACE,
    "implement": TK.IMPLEMENT,
    "init":      TK.INIT,
    "dinit":     TK.DINIT,
    "tag":       TK.TAG,
    "if":        TK.IF_,
    "scope":     TK.SCOPE,
    "own":       TK.OWN,
    "defer":     TK.DEFER,
    "include":   TK.INCLUDE,
    "extern":    TK.EXTERN,
}


@dataclass
class Token:
    kind:   TK
    value:  str
    line:   int
    col:    int

    def __repr__(self):
        return f"Token({self.kind.name}, {self.value!r}, {self.line}:{self.col})"


class LexError(Exception):
    def __init__(self, msg, line, col):
        super().__init__(f"[{line}:{col}] LexError: {msg}")
        self.line = line
        self.col  = col


class Lexer:
    def __init__(self, source: str, filename: str = "<input>"):
        self.src      = source
        self.filename = filename
        self.pos      = 0
        self.line     = 1
        self.col      = 1
        self.tokens: list[Token] = []

    # ── helpers ───────────────────────────────────────────────────────────────

    def _peek(self, offset=0) -> str:
        i = self.pos + offset
        return self.src[i] if i < len(self.src) else ""

    def _advance(self) -> str:
        ch = self.src[self.pos]
        self.pos += 1
        if ch == "\n":
            self.line += 1
            self.col = 1
        else:
            self.col += 1
        return ch

    def _match(self, expected: str) -> bool:
        if self.pos < len(self.src) and self.src[self.pos] == expected:
            self._advance()
            return True
        return False

    def _tok(self, kind: TK, value: str, line: int, col: int) -> Token:
        t = Token(kind, value, line, col)
        self.tokens.append(t)
        return t

    def _error(self, msg: str):
        raise LexError(msg, self.line, self.col)

    # ── scanners ─────────────────────────────────────────────────────────────

    def _skip_whitespace_and_comments(self):
        while self.pos < len(self.src):
            ch = self._peek()
            if ch in " \t\r\n":
                self._advance()
            elif ch == "/" and self._peek(1) == "/":
                # line comment
                while self.pos < len(self.src) and self._peek() != "\n":
                    self._advance()
            elif ch == "/" and self._peek(1) == "*":
                # block comment
                self._advance(); self._advance()
                while self.pos < len(self.src):
                    if self._peek() == "*" and self._peek(1) == "/":
                        self._advance(); self._advance()
                        break
                    self._advance()
                else:
                    self._error("Unterminated block comment")
            else:
                break

    def _scan_string(self) -> Token:
        line, col = self.line, self.col
        self._advance()  # opening "
        buf = []
        while self.pos < len(self.src):
            ch = self._peek()
            if ch == "\\":
                self._advance()
                esc = self._advance()
                buf.append({"n": "\n", "t": "\t", "r": "\r",
                            "\\": "\\", '"': '"', "0": "\0"}.get(esc, esc))
            elif ch == '"':
                self._advance()
                return self._tok(TK.STRING_LIT, "".join(buf), line, col)
            elif ch == "\n":
                self._error("Unterminated string literal")
            else:
                buf.append(self._advance())
        self._error("Unterminated string literal")

    def _scan_char(self) -> Token:
        line, col = self.line, self.col
        self._advance()  # opening '
        if self._peek() == "\\":
            self._advance()
            ch = self._advance()
            val = {"n": "\n", "t": "\t", "r": "\r",
                   "\\": "\\", "'": "'", "0": "\0"}.get(ch, ch)
        else:
            val = self._advance()
        if not self._match("'"):
            self._error("Unterminated char literal")
        return self._tok(TK.CHAR_LIT, val, line, col)

    def _scan_number(self) -> Token:
        line, col = self.line, self.col
        buf = []
        is_float = False
        # hex literal: 0x...
        if self._peek() == "0" and self._peek(1) in ("x", "X"):
            buf.append(self._advance())  # 0
            buf.append(self._advance())  # x/X
            while self.pos < len(self.src) and (
                    self._peek() in "0123456789abcdefABCDEF_"):
                ch = self._advance()
                if ch != "_":
                    buf.append(ch)
            val = "".join(buf)
            # consume integer suffixes: UL, ULL, LL, L, U, u, etc.
            while self.pos < len(self.src) and self._peek().lower() in ('u','l'):
                self._advance()
            return self._tok(TK.INT_LIT, val, line, col)
        # binary literal: 0b...
        if self._peek() == "0" and self._peek(1) in ("b", "B"):
            buf.append(self._advance())  # 0
            buf.append(self._advance())  # b/B
            while self.pos < len(self.src) and self._peek() in "01_":
                ch = self._advance()
                if ch != "_":
                    buf.append(ch)
            val = "".join(buf)
            while self.pos < len(self.src) and self._peek().lower() in ('u','l'):
                self._advance()
            return self._tok(TK.INT_LIT, val, line, col)
        # decimal / float
        while self.pos < len(self.src) and (self._peek().isdigit() or self._peek() == "."):
            ch = self._peek()
            if ch == ".":
                if is_float:
                    break
                is_float = True
            buf.append(self._advance())
        # optional scientific notation: e+10, e-3, e308
        if self._peek() in ("e", "E"):
            is_float = True
            buf.append(self._advance())
            if self._peek() in ("+", "-"):
                buf.append(self._advance())
            while self.pos < len(self.src) and self._peek().isdigit():
                buf.append(self._advance())
        # optional f32 suffix
        if self._peek() in ("f", "F"):
            buf.append(self._advance())
            is_float = True
        val = "".join(buf)
        # consume integer suffixes (UL, ULL, LL, L, U) — ignored, sizes are explicit in CK
        if not is_float:
            while self.pos < len(self.src) and self._peek().lower() in ('u','l'):
                self._advance()
        return self._tok(TK.FLOAT_LIT if is_float else TK.INT_LIT, val, line, col)

    def _scan_ident_or_keyword(self) -> Token:
        line, col = self.line, self.col
        buf = []
        while self.pos < len(self.src) and (self._peek().isalnum() or self._peek() == "_"):
            buf.append(self._advance())
        word = "".join(buf)
        kind = _KEYWORDS.get(word, TK.IDENT)
        return self._tok(kind, word, line, col)

    def _scan_dollar(self) -> Token:
        line, col = self.line, self.col
        self._advance()  # consume $
        buf = []
        while self.pos < len(self.src) and (self._peek().isalnum() or self._peek() == "_"):
            buf.append(self._advance())
        word = "".join(buf)
        if not word:
            self._error("Bare $ with no annotation name")
        kind = _DOLLAR_KEYWORDS.get(word)
        if kind is None:
            self._error(f"Unknown $ annotation: ${word}")
        return self._tok(kind, f"${word}", line, col)

    # ── main tokenize ────────────────────────────────────────────────────────

    def tokenize(self) -> list[Token]:
        while True:
            self._skip_whitespace_and_comments()
            if self.pos >= len(self.src):
                self._tok(TK.EOF, "", self.line, self.col)
                break

            line, col = self.line, self.col
            ch = self._peek()

            # string / char
            if ch == '"':
                self._scan_string()
            elif ch == "'":
                self._scan_char()
            # number
            elif ch.isdigit():
                self._scan_number()
            # identifier or keyword
            elif ch.isalpha() or ch == "_":
                self._scan_ident_or_keyword()
            # $ annotation
            elif ch == "$":
                self._scan_dollar()
            # two-char operators first
            elif ch == "-" and self._peek(1) == ">":
                self._advance(); self._advance()
                self._tok(TK.ARROW, "->", line, col)
            elif ch == ":" and self._peek(1) == ":":
                self._advance(); self._advance()
                self._tok(TK.COLONCOLON, "::", line, col)
            elif ch == "<" and self._peek(1) == "<":
                self._advance(); self._advance()
                self._tok(TK.LSHIFT, "<<", line, col)
            elif ch == ">" and self._peek(1) == ">":
                self._advance(); self._advance()
                self._tok(TK.RSHIFT, ">>", line, col)
            elif ch == "=" and self._peek(1) == "=":
                self._advance(); self._advance()
                self._tok(TK.EQ, "==", line, col)
            elif ch == "!" and self._peek(1) == "=":
                self._advance(); self._advance()
                self._tok(TK.NEQ, "!=", line, col)
            elif ch == "<" and self._peek(1) == "=":
                self._advance(); self._advance()
                self._tok(TK.LTE, "<=", line, col)
            elif ch == ">" and self._peek(1) == "=":
                self._advance(); self._advance()
                self._tok(TK.GTE, ">=", line, col)
            elif ch == "&" and self._peek(1) == "&":
                self._advance(); self._advance()
                self._tok(TK.AND, "&&", line, col)
            elif ch == "|" and self._peek(1) == "|":
                self._advance(); self._advance()
                self._tok(TK.OR, "||", line, col)
            elif ch == "+" and self._peek(1) == "+":
                self._advance(); self._advance()
                self._tok(TK.PLUSPLUS, "++", line, col)
            elif ch == "-" and self._peek(1) == "-":
                self._advance(); self._advance()
                self._tok(TK.MINUSMINUS, "--", line, col)
            elif ch == "+" and self._peek(1) == "=":
                self._advance(); self._advance()
                self._tok(TK.PLUS_EQ, "+=", line, col)
            elif ch == "-" and self._peek(1) == "=":
                self._advance(); self._advance()
                self._tok(TK.MINUS_EQ, "-=", line, col)
            elif ch == "*" and self._peek(1) == "=":
                self._advance(); self._advance()
                self._tok(TK.STAR_EQ, "*=", line, col)
            elif ch == "/" and self._peek(1) == "=":
                self._advance(); self._advance()
                self._tok(TK.SLASH_EQ, "/=", line, col)
            elif ch == "<" and self._peek(1) == "<":
                self._advance(); self._advance()
                self._tok(TK.LSHIFT, "<<", line, col)
            elif ch == ">" and self._peek(1) == ">":
                self._advance(); self._advance()
                self._tok(TK.RSHIFT, ">>", line, col)
            elif ch == "?" and self._peek(1) == "?":
                self._advance(); self._advance()
                self._tok(TK.NULLCOAL, "??", line, col)
            # single-char
            else:
                self._advance()
                single = {
                    "(": TK.LPAREN,  ")": TK.RPAREN,
                    "{": TK.LBRACE,  "}": TK.RBRACE,
                    "[": TK.LBRACKET,"]": TK.RBRACKET,
                    ";": TK.SEMI,    ":": TK.COLON,
                    ",": TK.COMMA,   ".": TK.DOT,
                    "*": TK.STAR,    "&": TK.AMP,
                    "+": TK.PLUS,    "-": TK.MINUS,
                    "/": TK.SLASH,   "%": TK.PERCENT,
                    "<": TK.LT,      ">": TK.GT,
                    "=": TK.ASSIGN,  "!": TK.BANG,
                    "|": TK.PIPE,    "^": TK.CARET,
                    "~": TK.TILDE,   "?": TK.QUESTION,
                }.get(ch)
                if single is None:
                    self._error(f"Unexpected character: {ch!r}")
                self._tok(single, ch, line, col)

        return self.tokens


def tokenize(source: str, filename: str = "<input>") -> list[Token]:
    return Lexer(source, filename).tokenize()
