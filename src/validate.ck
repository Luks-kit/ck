$import "ast.ck";
$import "std/string.ck";
$import "std/result.ck";

// AST validation pass (bootstrap).
// This is the first intermediate phase before import resolution / lowering.

fn validate_program(Program prog) -> Result(bool, String) {
    // top-level duplicate name checks (same namespace for now)
    for (usize i = 0; i < prog.decls.len; i++) {
        String ni = _decl_name(prog.decls.data[i]);
        if (ni.length == 0) continue;
        for (usize j = i + 1; j < prog.decls.len; j++) {
            String nj = _decl_name(prog.decls.data[j]);
            if (nj.length == 0) continue;
            if (ni.eq(&nj)) {
                return Result(bool, String).err(String.lit("duplicate top-level declaration name"));
            }
        }
    }

    // per-decl structural checks
    for (usize i = 0; i < prog.decls.len; i++) {
        Decl d = prog.decls.data[i];
        $tag switch (d) {
            case (Decl.struct_d s): {
                Result(bool, String) r = _validate_struct(s);
                if (r.is_err()) return Result(bool, String).err(String_clone(&r.err));
            }
            case (Decl.tag_union_d u): {
                Result(bool, String) r = _validate_tag_union(u);
                if (r.is_err()) return Result(bool, String).err(String_clone(&r.err));
            }
            case (Decl.enum_d e): {
                Result(bool, String) r = _validate_enum(e);
                if (r.is_err()) return Result(bool, String).err(String_clone(&r.err));
            }
            case (Decl.fn_d f): {
                Result(bool, String) r = _validate_fn(f);
                if (r.is_err()) return Result(bool, String).err(String_clone(&r.err));
            }
            case (Decl.namespace_d _): {
                // TODO(namespace-flattening): validate + recursively flatten namespace scopes.
            }
            case (Decl.import_d _): {}
            case (Decl.include_d _): {}
            case (Decl.extern_d _): {}
            case (Decl.const_d _): {}
            case (Decl.alias_d _): {}
            case (Decl.conditional_d _): {}
        }
    }

    return Result(bool, String).ok(true);
}

fn _decl_name(Decl d) -> String {
    String out = String.lit("");
    $tag switch (d) {
        case (Decl.fn_d f): { out = f.name.clone(); }
        case (Decl.struct_d s): { out = s.name.clone(); }
        case (Decl.tag_union_d u): { out = u.name.clone(); }
        case (Decl.enum_d e): { out = e.name.clone(); }
        case (Decl.alias_d a): { out = a.name.clone(); }
        case (Decl.namespace_d n): { out = n.name.clone(); }
        case (Decl.import_d _): {}
        case (Decl.include_d _): {}
        case (Decl.extern_d _): {}
        case (Decl.const_d _): {}
    }
    return out;
}

fn _validate_struct(StructDecl s) -> Result(bool, String) {
    // duplicate field names
    for (usize i = 0; i < s.fields.len; i++) {
        for (usize j = i + 1; j < s.fields.len; j++) {
            if (s.fields.data[i].name.eq(&s.fields.data[j].name)) {
                return Result(bool, String).err(String.lit("duplicate struct field name"));
            }
        }
    }
    // method signatures
    for (usize i = 0; i < s.methods.len; i++) {
        Result(bool, String) r = _validate_fn(s.methods.data[i]);
        if (r.is_err()) return r;
    }
    return Result(bool, String).ok(true);
}

fn _validate_tag_union(TagUnionDecl u) -> Result(bool, String) {
    for (usize i = 0; i < u.variants.len; i++) {
        for (usize j = i + 1; j < u.variants.len; j++) {
            if (u.variants.data[i].name.eq(&u.variants.data[j].name)) {
                return Result(bool, String).err(String.lit("duplicate tag-union variant name"));
            }
        }
    }
    return Result(bool, String).ok(true);
}

fn _validate_enum(EnumDecl e) -> Result(bool, String) {
    for (usize i = 0; i < e.variants.len; i++) {
        for (usize j = i + 1; j < e.variants.len; j++) {
            if (e.variants.data[i].name.eq(&e.variants.data[j].name)) {
                return Result(bool, String).err(String.lit("duplicate enum variant name"));
            }
        }
    }
    return Result(bool, String).ok(true);
}

fn _validate_fn(FnDecl f) -> Result(bool, String) {
    for (usize i = 0; i < f.params.len; i++) {
        for (usize j = i + 1; j < f.params.len; j++) {
            if (f.params.data[i].name.eq(&f.params.data[j].name)) {
                return Result(bool, String).err(String.lit("duplicate function parameter name"));
            }
        }
    }
    return Result(bool, String).ok(true);
}
