$import "ast.ck";
$import "std/string.ck";
$import "std/result.ck";
$import "std/vector.ck";

$include <stdio.h>;

// Bootstrap namespace flattening:
// - lifts nested declarations from `namespace` blocks to top-level
// - prefixes names as `ns_name_decl`
// - recursively flattens nested namespaces

fn flatten_namespaces_phase(Program prog) -> Result(Program, String) {
    vector(Decl) out = vector(Decl).new(prog.decls.len);
    for (usize i = 0; i < prog.decls.len; i++) {
        Result(vector(Decl), String) r = _flatten_decl(prog.decls.data[i], String.lit(""));
        if (r.is_err()) return Result(Program, String).err(String_clone(&r.err));
        for (usize j = 0; j < r.ok.len; j++) {
            out.push(r.ok.data[j]);
        }
    }
    Program flat;
    flat.decls = out;
    flat.filename = prog.filename.clone();
    return Result(Program, String).ok(flat);
}

fn _flatten_decl(Decl d, String prefix) -> Result(vector(Decl), String) {
    vector(Decl) out = vector(Decl).new(4);

    $tag switch (d) {
        case (Decl.namespace_d ns): {
            String ns_prefix = _join_prefix(prefix, ns.name);
            for (usize i = 0; i < ns.decls.len; i++) {
                Result(vector(Decl), String) r = _flatten_decl(ns.decls.data[i], ns_prefix);
                if (r.is_err()) return r;
                for (usize j = 0; j < r.ok.len; j++) {
                    out.push(r.ok.data[j]);
                }
            }
            return Result(vector(Decl), String).ok(out);
        }
        case (Decl.fn_d fdecl): {
            FnDecl x = fdecl;
            if (prefix.length > 0) x.name = _join_prefix(prefix, fdecl.name);
            out.push(Decl.fn_d(x));
            return Result(vector(Decl), String).ok(out);
        }
        case (Decl.struct_d st): {
            StructDecl x = st;
            if (prefix.length > 0) x.name = _join_prefix(prefix, st.name);
            out.push(Decl.struct_d(x));
            return Result(vector(Decl), String).ok(out);
        }
        case (Decl.tag_union_d un): {
            TagUnionDecl x = un;
            if (prefix.length > 0) x.name = _join_prefix(prefix, un.name);
            out.push(Decl.tag_union_d(x));
            return Result(vector(Decl), String).ok(out);
        }
        case (Decl.enum_d en): {
            EnumDecl x = en;
            if (prefix.length > 0) x.name = _join_prefix(prefix, en.name);
            out.push(Decl.enum_d(x));
            return Result(vector(Decl), String).ok(out);
        }
        case (Decl.alias_d al): {
            TypeAlias x = al;
            if (prefix.length > 0) x.name = _join_prefix(prefix, al.name);
            out.push(Decl.alias_d(x));
            return Result(vector(Decl), String).ok(out);
        }
        case (Decl.const_d ct): {
            ConstExprDecl x = ct;
            if (prefix.length > 0) x.name = _join_prefix(prefix, ct.name);
            out.push(Decl.const_d(x));
            return Result(vector(Decl), String).ok(out);
        }
        case (Decl.import_d _): { out.push(d); return Result(vector(Decl), String).ok(out); }
        case (Decl.include_d _): { out.push(d); return Result(vector(Decl), String).ok(out); }
        case (Decl.extern_d _): { out.push(d); return Result(vector(Decl), String).ok(out); }
        case (Decl.conditional_d _): { out.push(d); return Result(vector(Decl), String).ok(out); }
    }
}

fn _join_prefix(String prefix, String name) -> String {
    if (prefix.length == 0) return name.clone();
    char buf[512];
    snprintf(buf, 512, "%s_%s", prefix.ptr(), name.ptr());
    return String.from(buf);
}

