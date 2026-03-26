$import "ast.ck";
$import "std/string.ck";
$import "std/result.ck";
$import "validate.ck";

// Bootstrap compiler intermediate phases.
// We begin with AST validation, then add/expand the remaining phases.
//
// TODO(conditional-compilation): evaluate and strip/retain $if blocks.
// TODO(namespace-flattening): flatten namespace-scoped names into global symbols.
// TODO(qbe-backend): lower validated/monomorphized IR into QBE SSA.

fn run_frontend_phases(Program prog) -> Result(bool, String) {
    Result(bool, String) r = validate_program(prog);
    if (r.is_err()) return r;

    r = resolve_imports(prog);
    if (r.is_err()) return r;

    r = conditional_compile(prog);
    if (r.is_err()) return r;

    r = flatten_namespaces(prog);
    if (r.is_err()) return r;

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

fn resolve_imports(Program p) -> Result(bool, String) { return Result(bool, String).ok(true); }
fn conditional_compile(Program p) -> Result(bool, String) { return Result(bool, String).ok(true); }
fn flatten_namespaces(Program p) -> Result(bool, String) { return Result(bool, String).ok(true); }
fn monomorphize_program(Program p) -> Result(bool, String) { return Result(bool, String).ok(true); }
fn interface_check(Program p) -> Result(bool, String) { return Result(bool, String).ok(true); }
fn emit_program(Program p) -> Result(bool, String) { return Result(bool, String).ok(true); }
