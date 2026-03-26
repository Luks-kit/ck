$import "ast.ck";
$import "std/string.ck";
$import "std/result.ck";
$import "std/vector.ck";

// Bootstrap conditional compilation pass.
// Supports compile-time bool literal conditions in ConditionalDecl.
// Non-literal conditions return an error for now.

fn conditional_compile_phase(Program prog) -> Result(Program, String) {
    vector(Decl) out = vector(Decl).new(prog.decls.len);

    for (usize i = 0; i < prog.decls.len; i++) {
        Decl d = prog.decls.data[i];
        $tag switch (d) {
            case (Decl.conditional_d c): {
                Result(bool, String) ev = _eval_const_bool(c.condition);
                if (ev.is_err()) return Result(Program, String).err(String_clone(&ev.err));
                if (ev.ok) {
                    for (usize j = 0; j < c.body.len; j++) {
                        out.push(c.body.data[j]);
                    }
                }
            }
            case (Decl.import_d _): { out.push(d); }
            case (Decl.include_d _): { out.push(d); }
            case (Decl.extern_d _): { out.push(d); }
            case (Decl.const_d _): { out.push(d); }
            case (Decl.alias_d _): { out.push(d); }
            case (Decl.fn_d _): { out.push(d); }
            case (Decl.struct_d _): { out.push(d); }
            case (Decl.tag_union_d _): { out.push(d); }
            case (Decl.enum_d _): { out.push(d); }
            case (Decl.namespace_d _): { out.push(d); }
        }
    }

    Program out_prog;
    out_prog.decls = out;
    out_prog.filename = prog.filename.clone();
    return Result(Program, String).ok(out_prog);
}

fn _eval_const_bool(Expr* cond) -> Result(bool, String) {
    if (cond == null) {
        return Result(bool, String).err(String.lit("conditional compilation: null condition"));
    }

    Expr c = *cond;
    if (c.tag_ == Expr_bool_lit_) {
        return Result(bool, String).ok(c.bool_lit);
    }
    return Result(bool, String).err(String.lit("conditional compilation: condition must be const bool"));
}

