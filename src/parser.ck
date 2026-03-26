$import "lexer.ck";
$import "std/string.ck";
$import "std/vector.ck";
$import "std/result.ck";

$include <stdio.h>;

struct Parser {
    vector(Token)* toks;
    usize pos;

    fn $init new(vector(Token)& tokens) -> Self {
        return { tokens, 0 };
    }

    // Bootstrap parser entrypoint.
    // Returns number of parsed top-level declarations.
    fn parse() -> Result(usize, String) {
        usize count = 0;
        while (!self._is_eof()) {
            while (self._match(TokType.NewLine) || self._match(TokType.Semi)) {}
            if (self._is_eof()) break; 
            Result(bool, String) ok = self._parse_decl();
            $tag switch (ok) {
                case (Result.ok _): { count++; }
                case (Result.err e): { return Result(usize, String).err(e.clone()); }
            }
        }
        return Result(usize, String).ok(count);
    }

    fn _parse_decl() -> Result(bool, String) {
        if (self._match(TokType.Template))  return self._parse_template_decl();
        if (self._match(TokType.Import))    return self._parse_import_like();
        if (self._match(TokType.Include))   return self._parse_until_semi();
        if (self._match(TokType.ConstExpr)) return self._parse_until_semi();
        if (self._match(TokType.TypeDef))   return self._parse_until_semi();
        if (self._match(TokType.Enum))      return self._parse_braced_decl();
        if (self._match(TokType.Struct))    return self._parse_braced_decl();
        if (self._match(TokType.Union))     return self._parse_braced_decl();
        if (self._match(TokType.Tag)) {
            self._expect(TokType.Union, "expected union after $tag");
            return self._parse_braced_decl();
        }
        if (self._match(TokType.Extern))    return self._parse_braced_decl();
        if (self._match(TokType.NameSpace)) return self._parse_braced_decl();
        if (self._match(TokType.Fn))        return self._parse_fn_decl();
        return Result(bool, String).err(self._err_here("unexpected top-level token"));
    }

     fn _parse_template_decl() -> Result(bool, String) {
        self._expect(TokType.LParen, "expected '(' after $template");
        usize depth = 1;
        while (!self._is_eof() && depth > 0) {
            if (self._match(TokType.LParen)) depth++;
            else if (self._match(TokType.RParen)) depth--;
            else self._advance();
        }
        while (self._match(TokType.NewLine) || self._match(TokType.Semi)) {}

        // template applies to the following declaration
        if (self._match(TokType.Struct)) return self._parse_braced_decl();
        if (self._match(TokType.Union))  return self._parse_braced_decl();
        if (self._match(TokType.Tag)) {
            self._expect(TokType.Union, "expected union after $tag");
            return self._parse_braced_decl();
        }
        if (self._match(TokType.Fn))     return self._parse_fn_decl();

        return Result(bool, String).err(self._err_here("expected declaration after $template"));
    }

    fn _parse_import_like() -> Result(bool, String) {
        if (!self._match(TokType.StringLit) && !self._match(TokType.Ident)) {
            return Result(bool, String).err(self._err_here("expected path"));
        }
        self._expect(TokType.Semi, "expected ';'");
        return Result(bool, String).ok(true);
    }

    fn _parse_until_semi() -> Result(bool, String) {
        while (!self._is_eof() && !self._check(TokType.Semi)) self._advance();
        self._expect(TokType.Semi, "expected ';'");
        return Result(bool, String).ok(true);
    }

    fn _parse_braced_decl() -> Result(bool, String) {
        if (!self._match(TokType.Ident)) {
            return Result(bool, String).err(self._err_here("expected declaration name"));
        }
        self._expect(TokType.LBrace, "expected '{'");
        usize depth = 1;
        while (!self._is_eof() && depth > 0) {
            if (self._match(TokType.LBrace)) depth++;
            else if (self._match(TokType.RBrace)) depth--;
            else self._advance();
        }
        self._expect(TokType.Semi, "expected ';' after declaration");
        return Result(bool, String).ok(true);
    }

    fn _parse_fn_decl() -> Result(bool, String) {
        if (self._match(TokType.Init) || self._match(TokType.Dinit)) {}
        self._expect(TokType.Ident, "expected fn name");
        self._expect(TokType.LParen, "expected '('");

        // params (shallow parse)
        usize pdepth = 1;
        while (!self._is_eof() && pdepth > 0) {
            if (self._match(TokType.LParen)) pdepth++;
            else if (self._match(TokType.RParen)) pdepth--;
            else self._advance();
        }

        if (self._match(TokType.Arrow)) {
            while (!self._is_eof() && !self._check(TokType.LBrace)) self._advance();
        }

        self._expect(TokType.LBrace, "expected function body");
        usize bdepth = 1;
        while (!self._is_eof() && bdepth > 0) {
            if (self._match(TokType.LBrace)) bdepth++;
            else if (self._match(TokType.RBrace)) bdepth--;
            else self._advance();
        }
        return Result(bool, String).ok(true);
    }

    fn _err_here(const char* msg) -> String {
        char buf[256];
        sprintf(buf, "[line %lu] ParseError: %s", self._line(), msg);
        return String.from(buf);
    }

    fn _line() -> usize {
        if (self.pos >= self.toks->len) return 0;
        return self.toks->data[self.pos].span.row;
    }

    fn _expect(TokType tt, const char* msg) -> void {
        if (!self._match(tt)) {
            printf("parse error at line %lu: %s\n", self._line(), msg);
        }
    }

    fn _match(TokType tt) -> bool {
        if (!self._check(tt)) return false;
        self._advance();
        return true;
    }

    fn _check(TokType tt) -> bool {
        if (self._is_eof()) return false;
        return self.toks->data[self.pos].tok_type == tt;
    }

    fn _advance() -> Token {
        if (!self._is_eof()) self.pos++;
        return self.toks->data[self.pos - 1];
    }

    fn _is_eof() -> bool {
        return self.pos >= self.toks->len || self.toks->data[self.pos].tok_type == TokType.EOF;
    }
};
