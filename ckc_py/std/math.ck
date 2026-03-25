// std/math.ck
// Wrapper around <math.h>.
// All functions operate on f64 unless suffixed with _f (f32).

$include <math.h>;

$extern {
    // ── constants ─────────────────────────────────────────────────────────────
    constexpr f64 PI    = 3.14159265358979323846;
    constexpr f64 TAU   = 6.28318530717958647692;
    constexpr f64 E     = 2.71828182845904523536;
    constexpr f64 SQRT2 = 1.41421356237309504880;

    // ── basic ─────────────────────────────────────────────────────────────────
    fn sqrt(f64 x)              -> f64;
    fn sqrtf(f32 x)             -> f32;
    fn cbrt(f64 x)              -> f64;
    fn fabs(f64 x)              -> f64;
    fn fabsf(f32 x)             -> f32;
    fn ceil(f64 x)              -> f64;
    fn floor(f64 x)             -> f64;
    fn round(f64 x)             -> f64;
    fn trunc(f64 x)             -> f64;
    fn fmod(f64 x, f64 y)       -> f64;
    fn pow(f64 x, f64 y)        -> f64;

    // ── trig ──────────────────────────────────────────────────────────────────
    fn sin(f64 x)               -> f64;
    fn cos(f64 x)               -> f64;
    fn tan(f64 x)               -> f64;
    fn asin(f64 x)              -> f64;
    fn acos(f64 x)              -> f64;
    fn atan(f64 x)              -> f64;
    fn atan2(f64 y, f64 x)      -> f64;
    fn sinf(f32 x)              -> f32;
    fn cosf(f32 x)              -> f32;
    fn tanf(f32 x)              -> f32;

    // ── exponential / log ─────────────────────────────────────────────────────
    fn exp(f64 x)               -> f64;
    fn exp2(f64 x)              -> f64;
    fn log(f64 x)               -> f64;
    fn log2(f64 x)              -> f64;
    fn log10(f64 x)             -> f64;

    // ── min / max / clamp ─────────────────────────────────────────────────────
    fn fmin(f64 a, f64 b)       -> f64;
    fn fmax(f64 a, f64 b)       -> f64;
    fn fminf(f32 a, f32 b)      -> f32;
    fn fmaxf(f32 a, f32 b)      -> f32;

    // ── hypot / lerp ──────────────────────────────────────────────────────────
    fn hypot(f64 x, f64 y)      -> f64;
    fn hypotf(f32 x, f32 y)     -> f32;
};
