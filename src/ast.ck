$import "std/string.ck";
$import "std/vector.ck";

// Core types
//

struct TypeName {
    String name;
    vector(TypeName) args;
    bool pointer;
    bool ref;
    bool const_;
    String array_size;
    vector(TypeName) fn_params;
    TypeName* fn_ret;
};

struct TemplateParam {
    String bound;
    String name;
    TypeName* default_type;
};

struct Param {
    TypeName type;
    String name;
    Expr* default_val;
};

//
// Expr-related structs (must come before Expr union)
//

struct BinOp { String op; Expr* left; Expr* right; usize line; };
struct UnaryOp { String op; Expr* operand; bool prefix; usize line; };
struct Assign { String op; Expr* left; Expr* right; usize line; };
struct Call { Expr* callee; vector(Expr*) args; usize line; };
struct MethodCall { Expr* receiver; String method; vector(Expr*) args; usize line; };
struct FieldAccess { Expr* receiver; String field; usize line; };
struct Index { Expr* receiver; Expr* index; usize line; };
struct Cast { TypeName type; Expr* expr; usize line; };
struct Ternary { Expr* cond; Expr* then_branch; Expr* else_branch; usize line; };
struct NullCoalesce { Expr* left; Expr* right; usize line; };
struct TemplateInst { String name; vector(TypeName) args; usize line; };

struct StructLitField { String name; Expr* value; };
struct StructLit { TypeName* type; vector(StructLitField) fields; usize line; };

//
// Expr union
//

$tag union Expr {
    i64 int_lit;
    f64 float_lit;
    String string_lit;
    bool bool_lit;
    void* null_lit;
    String ident;
    void* self_expr;
    
    BinOp binary;
    UnaryOp unary;
    Assign assign;
    Call call;
    MethodCall method;
    FieldAccess field;
    Index index;
    Cast cast;
    Ternary ternary;
    StructLit struct_lit;
    NullCoalesce null_coal;
    TemplateInst temp_inst;
    usize sizeof_type;
};

//
// Stmt-related structs (need Expr + Block forward)
//

struct LetStmt { TypeName type; String name; Expr* value; usize line; };
struct ExprStmt { Expr* expr; usize line; };
struct ReturnStmt { Expr* value; usize line; };

struct IfStmt { 
    Expr* cond; 
    Block* then_branch; 
    Block* else_branch; 
    usize line; 
};

struct ForStmt {
    Stmt* init;
    Expr* cond;
    Expr* post;
    Block* body;
    usize line;
};

struct WhileStmt { Expr* cond; Block* body; usize line; };

struct TagCase {
    String union_name;
    String variant_name;
    String bind_name;
    Block* body;
    usize line;
};

struct TagSwitchStmt {
    Expr* control;
    vector(TagCase) cases;
    usize line;
};

struct SwitchCase {
    Expr* value;
    vector(Stmt) body;
    usize line;
};

struct SwitchStmt {
    Expr* control;
    vector(SwitchCase) cases;
    usize line;
};

//
// Stmt union (Block still forward-declared here)
//

$tag union Stmt {
    LetStmt let_s;
    ExprStmt expr_s;
    ReturnStmt ret_s;
    IfStmt if_s;
    ForStmt for_s;
    WhileStmt while_s;
    TagSwitchStmt tag_switch_s;
    SwitchStmt switch_s;
    Block block_s;
    Expr* defer_s;
    Expr* dinit_s;
    Expr* assert_s;
    void* break_s;
    void* continue_s;
};

//
// Block (after Stmt is fully known)
//

struct Block {
    vector(Stmt) stmts;
};

//
// Decls (depend on everything above)
//

struct ImportDecl {
    String path;
    vector(String) symbols;
    usize line;
};

struct ConstExprDecl { String name; TypeName type; Expr* value; usize line; };

struct FnDecl {
    String name;
    vector(Param) params;
    TypeName return_type;
    Block* body;
    String lifecycle;
    vector(TemplateParam) template_params;
    String operator_sym;
    usize line;
};

struct StructDecl {
    String name;
    vector(Param) fields;
    vector(FnDecl) methods;
    vector(TemplateParam) template_params;
    bool is_interface;
    bool is_union;
    vector(String) implements;
    usize line;
};

struct EnumVariant { String name; Expr* value; };
struct EnumDecl { String name; vector(EnumVariant) variants; usize line; };

struct TagUnionDecl {
    String name;
    vector(Param) variants;
    vector(FnDecl) methods;
    vector(TemplateParam) template_params;
    String template_base;
    usize line;
};

struct ExternDecl {
    vector(FnDecl) fns;
    vector(String) opaque_structs;
    vector(StructDecl) full_structs;
    vector(ConstExprDecl) consts;
    usize line;
};

struct TypeAlias { String name; TypeName type; usize line; };
struct IncludeDecl { String path; usize line; };

//
// Decl union (last)
//

$tag union Decl {
    ImportDecl import_d;
    IncludeDecl include_d;
    ExternDecl extern_d;
    ConstExprDecl const_d;
    TypeAlias alias_d;
    FnDecl fn_d;
    StructDecl struct_d;
    TagUnionDecl tag_union_d;
    EnumDecl enum_d;
    NamespaceDecl namespace_d;
};
