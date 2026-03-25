// std/result.ck
// Result(T, E) — the standard error handling primitive.

$template(type T, type E)
$tag union Result {
    T ok;
    E err;

    fn $init ok(T val) -> Self {
        Self r;
        r.tag_ = Result_ok_;
        r.ok   = val;
        return r;
    }

    fn $init err(E val) -> Self {
        Self r;
        r.tag_ = Result_err_;
        r.err  = val;
        return r;
    }

    fn is_ok() -> bool {
        return self.tag_ == Result_ok_;
    }

    fn is_err() -> bool {
        return self.tag_ == Result_err_;
    }
};
