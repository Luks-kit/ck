$import "ast.ck";
$import "lexer.ck";
$import "parser.ck";
$import "std/string.ck";
$import "std/result.ck";
$import "std/io.ck";
$import "std/vector.ck";

$include <stdio.h>;

// Import resolution/coalescing phase (bootstrap).
// Current behavior:
//  - resolves and parses imported files recursively for validation
//  - removes ImportDecl nodes from the returned Program
//  - (TODO) append imported AST decls once parser emits full decl nodes

fn resolve_imports_phase(Program prog, String root_dir) -> Result(Program, String) {
    vector(Decl) out = vector(Decl).new(prog.decls.len);

    for (usize i = 0; i < prog.decls.len; i++) {
        Decl d = prog.decls.data[i];
        bool keep_decl = true;

        $tag switch (d) {
            case (Decl.import_d imp): {
                keep_decl = false;
                Result(bool, String) r = _load_and_validate_import(imp.path, root_dir);
                if (r.is_err()) return Result(Program, String).err(String_clone(&r.err));
            }
            case (Decl.include_d _): {}
            case (Decl.extern_d _): {}
            case (Decl.const_d _): {}
            case (Decl.alias_d _): {}
            case (Decl.fn_d _): {}
            case (Decl.struct_d _): {}
            case (Decl.tag_union_d _): {}
            case (Decl.enum_d _): {}
            case (Decl.namespace_d _): {}
            case (Decl.conditional_d _): {}
        }

        if (keep_decl) out.push(d);
    }

    Program merged;
    merged.decls = out;
    merged.filename = prog.filename.clone();
    return Result(Program, String).ok(merged);
}

fn _load_and_validate_import(String import_path, String root_dir) -> Result(bool, String) {
    String resolved = _resolve_import_path(import_path, root_dir);
    Result(String, char*) file_r = io_read_file(resolved.ptr());
    String src;
    $tag switch (file_r) {
        case (Result.ok s): { src = s.clone(); }
        case (Result.err e): {
            char msg[512];
            snprintf(msg, 512, "import read error (%s): %s", resolved.ptr(), e);
            return Result(bool, String).err(String.from(msg));
        }
    }

    Lexer lx = Lexer.new(src.clone(), resolved.clone());
    vector(Token) toks = lx.scan_tokens();
    Parser p = Parser.new(toks);
    Result(usize, String) pr = p.parse();
    if (pr.is_err()) return Result(bool, String).err(String_clone(&pr.err));

    return Result(bool, String).ok(true);
}

fn _resolve_import_path(String import_path, String root_dir) -> String {
    // absolute or explicit relative
    if (import_path.length > 0 && import_path.at(0) == '/') return import_path.clone();
    if (import_path.length > 1 && import_path.at(0) == '.') return import_path.clone();

    // std/* maps to ckc_py/std/*
    if (import_path.length >= 4
        && import_path.at(0) == 's'
        && import_path.at(1) == 't'
        && import_path.at(2) == 'd'
        && import_path.at(3) == '/') {
        char buf[512];
        snprintf(buf, 512, "ckc_py/%s", import_path.ptr());
        return String.from(buf);
    }

    // default: rooted under current module dir
    char buf[512];
    snprintf(buf, 512, "%s/%s", root_dir.ptr(), import_path.ptr());
    return String.from(buf);
}

