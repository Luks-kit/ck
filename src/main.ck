$import "std/string.ck";
$import "std/io.ck";
$import "lexer.ck";
$import "parser.ck";
$import "ast.ck";
$import "phases.ck";

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

    // 3. Parse tokens
    Parser parser = Parser.new(tokens);
    Result(usize, String) parsed = parser.parse();
    $tag switch(parsed) {
        case(Result.ok decl_count): {
            printf("parsed decls: %lu\n", decl_count);
            Program prog;
            prog.decls = vector(Decl).new(0);
            prog.filename = filename.clone();
            Result(bool, String) phase_result = run_frontend_phases(prog);
            $tag switch (phase_result) {
                case (Result.ok ok_): {
                    printf("frontend phases: ok\n");
                }
                case (Result.err err): {
                    printf("frontend phases error: %s\n", err.ptr());
                    return 1;
                }
            }
        }
        case(Result.err e): {
            printf("%s\n", e.ptr());
            return 1;
        }
    }

    return 0;
}
