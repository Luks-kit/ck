$import "std/string.ck";
$import "std/io.ck";
$import "lexer.ck";

type cstr = char*;

fn main(i32 argc, cstr* argv) -> i32 {

    String filename = String.lit(argv[1]);
    String source;
    Result(String, char*) read_string = io_read_file(filename.ptr());
    $tag switch(read_string) {
        case(Result.ok s): { source = s.clone(); }
        case(Result.err e): { printf("Error opening %s: %s\n",filename.ptr() e); return 1; }
    }

    // 2. Initialize Lexer and scan
    Lexer lexer = Lexer.new(source.clone(), filename.clone());
    vector(Token) tokens = lexer.scan_tokens();

    // 3. Dump tokens
    Token tok;
    for (usize i = 0; i < tokens.len; i++) {
        tok = tokens.data[i];
        printf("%s ", tok.lexeme.ptr()); 
    }
    tok = Token.new(Span.new(filename), TokType.EOF, String.from("")); 

    return 0;
}
