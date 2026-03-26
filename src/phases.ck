$import "ast.ck";
$import "conditional.ck";
$import "imports.ck";
$import "namespaces.ck";
$import "std/string.ck";
$import "std/result.ck";
$import "validate.ck";

// Bootstrap compiler intermediate phases.
// We begin with AST validation, then add/expand the remaining phases.
//
// TODO(namespace-flattening): flatten namespace-scoped names into global symbols.
// TODO(qbe-backend): lower validated/monomorphized IR into QBE SSA.

fn run_frontend_phases(Program prog) -> Result(bool, String) {
    Result(bool, String) r = validate_program(prog);
    if (r.is_err()) return r;

    Result(Program, String) ir = resolve_imports_phase(prog, String.lit("src"));
    if (ir.is_err()) return Result(bool, String).err(String_clone(&ir.err));
    prog = ir.ok;

    Result(Program, String) cc = conditional_compile_phase(prog);
    if (cc.is_err()) return Result(bool, String).err(String_clone(&cc.err));
    prog = cc.ok;    
    
    Result(Program, String) nf = flatten_namespaces_phase(prog);
    if (nf.is_err()) return Result(bool, String).err(String_clone(&nf.err));
    prog = nf.ok;

    r = monomorphize_program(prog);
    if (r.is_err()) return r;

    r = interface_check(prog);
    if (r.is_err()) return r;

    // Emission is final stage (currently placeholder).
    r = emit_program(prog);
    if (r.is_err()) return r;

    return Result(bool, String).ok(true);
}

// ── placeholders: wired now, implemented incrementally ──────────────────────

fn monomorphize_program(Program p) -> Result(bool, String) { return Result(bool, String).ok(true); }
fn interface_check(Program p) -> Result(bool, String) { return Result(bool, String).ok(true); }
fn emit_program(Program p) -> Result(bool, String) { return Result(bool, String).ok(true); }
