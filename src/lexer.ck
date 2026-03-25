$import "literals.ck";
$import "std/string.ck";
$import "std/hashmap.ck";
$import "std/vector.ck";

struct Span {
    String filename;
    usize row;
    usize col;

    fn $init new(String f) -> Self { return {f, 0, 0}; } 
    fn clone () -> Span { return {self.filename.clone(), self.row, self.col }; }
};

enum TokType {
    IntLit,
    FloatLit,
    StringLit,
    CharLit,
    BoolLit,
    Null,
    
    Ident,

    Dollar,
    Import,
    Template,
    Interface,
    Implement,
    Init,
    Dinit,
    Tag,
    ConstIf,
    Scope,
    Defer,
    Include,
    Extern,

    Fn,
    Struct,
    Union,
    Enum,
    Return,
    If,
    Else,
    For,
    While,
    Break,
    Continue,
    Switch,
    Case,
    Default,
    Let,
    ConstExpr,
    TypeDef,
    Type,
    NameSpace,
    Auto,
    Sizeof,
    Lenof,
    Self_,
    SelfType,
    Assert,
    True,
    False,

    LParen,
    RParen,
    LBrace,
    RBrace,
    LBracket,
    RBracket,
    LShift,
    RShift,
    Semi,
    Colon,
    Comma,
    Dot,
    Arrow,
    Question,
    NullCoal,

    Plus,
    Minus,
    Star,
    Slash,
    Percent,

    Eq,
    Neq,
    Less,
    Greater,
    LessEq,
    GreaterEq,
    
    And,
    Or,
    Bang,

    Assign,

    PlusEq,
    MinusEq,
    StarEq,
    SlashEq,

    Pipe,
    Amp,
    Caret,
    Tilde,

    PlusPlus,
    MinusMinus,

    EOF,
    NewLine,
    ErrorTok
}

struct Token {
    Span span;
    TokType tok_type;
    String lexeme;

    fn $init new (Span s, TokType t, String lex) -> Self {
        return {s, t, lex};
    }
    fn $dinit delete() -> void {
        $dinit(self.lexeme);
    }
    fn clone() -> Token {
        return { self.span.clone(), self.tok_type, self.lexeme.clone()}; 
    }
};


struct wordstore {
    hashmap(const char*, TokType) words; 
    hashmap(const char*, TokType) directives;
};


fn kw_init() -> wordstore {
    hashmap(const char*, TokType) words =
        hashmap(const char*, TokType).new(
            hash_cstr,
            eq_cstr,
            null,   // keys are string literals → do not free
            null    // values are enums → do nothing
        );

    hashmap(const char*, TokType) directives =
        hashmap(const char*, TokType).new(
            hash_cstr,
            eq_cstr,
            null,
            null
        );

    // Standard Keywords
    words.insert("fn", TokType.Fn);
    words.insert("struct", TokType.Struct);
    words.insert("union", TokType.Union);
    words.insert("enum", TokType.Enum);
    words.insert("return", TokType.Return);
    words.insert("if", TokType.If);
    words.insert("else", TokType.Else);
    words.insert("for", TokType.For);
    words.insert("while", TokType.While);
    words.insert("break", TokType.Break);
    words.insert("continue", TokType.Continue);
    words.insert("switch", TokType.Switch);
    words.insert("case", TokType.Case);
    words.insert("default", TokType.Default);
    words.insert("let", TokType.Let);
    words.insert("constexpr", TokType.ConstExpr);
    words.insert("typedef", TokType.TypeDef);
    words.insert("type", TokType.Type);
    words.insert("namespace", TokType.NameSpace);
    words.insert("auto", TokType.Auto);
    words.insert("sizeof", TokType.Sizeof);
    words.insert("lenof", TokType.Lenof);
    words.insert("self", TokType.Self_);
    words.insert("Self", TokType.SelfType);
    words.insert("assert", TokType.Assert);
    words.insert("true", TokType.True);
    words.insert("false", TokType.False);
    words.insert("null", TokType.Null);

    // $-prefixed Keywords
    directives.insert("import", TokType.Import);
    directives.insert("template", TokType.Template);
    directives.insert("interface", TokType.Interface);
    directives.insert("implement", TokType.Implement);
    directives.insert("init", TokType.Init);
    directives.insert("dinit", TokType.Dinit);
    directives.insert("tag", TokType.Tag);
    directives.insert("if", TokType.ConstIf);
    directives.insert("scope", TokType.Scope);
    directives.insert("defer", TokType.Defer);
    directives.insert("include", TokType.Include);
    directives.insert("extern", TokType.Extern);
    
    return { words, directives };
}
    




struct Lexer {
    String source;
    vector(Token) tokens;
    
    usize start;   // start of the current lexeme
    usize current; // current character being processed
    usize line;
    usize col;
    String filename;
    wordstore store;

    fn $init new(String source, String filename) -> Self {
        return { 
            source, 
            vector(Token).new(32), 
            0, 0, 1, 1, 
            filename,
            kw_init()
        };
    }
    
    fn $dinit delete() -> void {
        $dinit(self.source); $dinit(self.tokens);
        $dinit(self.filename); $dinit(self.store);

    }
    
    // Main entry point
    fn scan_tokens() -> vector(Token)& {
        while (!self._is_at_end()) {
            self.start = self.current;
            self._scan_token();
        }

        self.tokens.push(Token.new(
            self._make_span(),
            TokType.EOF,
            String.lit("")
        ));
        
        return self.tokens;
    }

    // ── Internal Helpers ──────────────────────────────────────────────────────

    fn _scan_token() -> void {
        char c = self._advance();
        switch (c) {
            case ('('): self._add_token(TokType.LParen); break;
            case (')'): self._add_token(TokType.RParen); break;
            case ('{'): self._add_token(TokType.LBrace); break;
            case ('}'): self._add_token(TokType.RBrace); break;
            case ('['): self._add_token(TokType.LBracket); break;
            case (']'): self._add_token(TokType.RBracket); break;
            case (';'): self._add_token(TokType.Semi); break;
            case (','): self._add_token(TokType.Comma); break;
            case ('.'): self._add_token(TokType.Dot); break;
            case ('-'): self._add_token(self._match('>') ? TokType.Arrow : TokType.Minus); break;
            case ('+'): self._add_token(self._match('+') ? TokType.PlusPlus : TokType.Plus); break;
            
            case ('$'): self._parse_dollar(); break;

            case ('='): 
                self._add_token(self._match('=') ? TokType.Eq : TokType.Assign); 
                break;
            case ('!'): 
                self._add_token(self._match('=') ? TokType.Neq : TokType.Bang); 
                break;

            case ('/'):
                if (self._match('/')) {
                    // A comment goes until the end of the line.
                    while (self._peek() != '\n' && !self._is_at_end()) self._advance();
                } else {
                    self._add_token(TokType.Slash);
                }
                break;

            case (' '):
            case ('\r'):
            case ('\t'):
                // Ignore whitespace.
                self.col++;
                break;

            case ('\n'):
                self.line++;
                self.col = 1;
                self._add_token(TokType.NewLine);
                break;

            case ('"'): self._string(); break;

            default:
                if (self._is_digit(c)) self._number();
                else if (self._is_alpha(c)) self._identifier();
                else self._add_token(TokType.ErrorTok);
                break;
        }
    }

    fn _advance() -> char {
        char c = self.source.at(self.current++);
        self.col++;
        return c;
    }

    fn _match(char expected) -> bool {
        if (self._is_at_end()) return false;
        if (self.source.at(self.current) != expected) return false;
        self.current++;
        self.col++;
        return true;
    }

    fn _peek() -> char {
        if (self._is_at_end()) return '\0';
        return self.source.at(self.current);
    }
    
    fn _number() -> void {
        while (self._is_digit(self._peek())) {
            self._advance();
        }

        // Look for a fractional part.
        if (self._peek() == '.' && self._is_digit(self._peek_next())) {
            // Consume the "."
            self._advance();

            while (self._is_digit(self._peek())) {
                self._advance();
            }
            self._add_token(TokType.FloatLit);
        } else {
            self._add_token(TokType.IntLit);
        }
    }

    // Helper to look two characters ahead (needed for float detection)
    fn _peek_next() -> char {
        if (self.current + 1 >= self.source.length) return '\0';
        return self.source.at(self.current + 1);
    }
    
    fn _string() -> void {
        while (self._peek() != '"' && !self._is_at_end()) {
            if (self._peek() == '\n') {
                self.line++;
                self.col = 1;
            }
            self._advance();
        }

        if (self._is_at_end()) {
            self._add_token(TokType.ErrorTok); // Unterminated string
            return;
        }

        // The closing ".
        self._advance();

        // Trim the surrounding quotes for the lexeme value
        String value = String.from_range(
            self.source.ptr() + self.start + 1, 
            self.current - self.start - 2
        );
        
        self.tokens.push(Token.new(self._make_span(), TokType.StringLit, value.clone()));
    }

    fn _is_at_end() -> bool {
        return self.current >= self.source.length;
    }

    fn _make_span() -> Span {
        return { self.filename, self.line, self.col - (self.current - self.start) };
    }

    fn _add_token(TokType t) -> void {
        String text = self._get_lexeme();
        self.tokens.push(Token.new(self._make_span(), t, text.clone()));
    }

    fn _get_lexeme() -> String {
        return String.from_range(self.source.ptr() + self.start, self.current - self.start);
    }

    fn _is_digit(char c) -> bool { return c >= '0' && c <= '9'; }
    fn _is_alpha(char c) -> bool { 
        return (c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') || c == '_'; 
    }
    
    // Logic for Identifiers and Keywords
    fn _identifier() -> void {
        while (self._is_alpha(self._peek()) || self._is_digit(self._peek())) {
            self._advance();
        }

        String text = self._get_lexeme();
        // Check if the lexeme exists in our keyword map
        auto type_tok = self.store.words.get(text.ptr());
        $tag switch(type_tok) {
            case (Result.ok t): { self._add_token(t); break; }
            case (Result.err e): { self._add_token(TokType.Ident); break; }
        }
    }

    // Logic for $-prefixed directives
    fn _parse_dollar() -> void {
        if (self._is_alpha(self._peek())) {
            while (self._is_alpha(self._peek()) || self._is_digit(self._peek())) {
                self._advance();
            }
            String directive_name = String.from_range(
                                self.source.ptr() + self.start + 1, 
                                self.current - self.start - 1);
            
            auto type_tok = self.store.directives.get(directive_name.ptr());
            $tag switch(type_tok) {
                case (Result.ok t): { self._add_token(t); break; }
                case (Result.err e): { self._add_token(TokType.Dollar); break; }
            }

        } else {
            self._add_token(TokType.Dollar);
        }
    }

};

