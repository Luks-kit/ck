#!/usr/bin/env python3
"""
ckc — CK compiler entry point
Usage: python ckc.py <input.ck> [-o output.c]
"""

import sys
import argparse
from src.lexer     import tokenize, LexError
from src.parser    import parse,    ParseError
from src.importer  import resolve,   ImportError
from src.condeval  import evaluate,  CondError, BuildConfig
from src.nsflat    import flatten
from src.mono      import monomorphize
from src.checker   import check,     InterfaceError
from src.lifetime  import inject_field_dinits, inject_tag_union_inits
from src.emitter   import emit
from src.header    import emit_header


def main():
    ap = argparse.ArgumentParser(description="CK compiler (v0 — transpiles to C)")
    ap.add_argument("input",          help="Input .ck file")
    ap.add_argument("-o", "--output", default=None, help="Output .c file (default: stdout)")
    ap.add_argument("--emit-header", default=None, metavar="FILE",
                        help="Also emit a C header (.h) for the compiled module")
    ap.add_argument("-I", "--include", action="append", default=[],
                    metavar="DIR",    help="Add directory to import search path")
    ap.add_argument("--os",    dest="target_os",   default="linux",
                    help="Target OS (linux, windows, macos, freestanding)")
    ap.add_argument("--arch",  dest="target_arch", default="x86_64",
                    help="Target arch (x86_64, aarch64, riscv64, wasm32)")
    ap.add_argument("--debug", dest="debug",       action="store_true",
                    help="Enable debug build")
    ap.add_argument("--opt",   dest="opt",         default="none",
                    choices=["none", "size", "speed"], help="Optimization level")
    ap.add_argument("--tokens",       action="store_true", help="Dump token stream and exit")
    ap.add_argument("--ast",          action="store_true", help="Dump AST and exit")
    args = ap.parse_args()

    try:
        source = open(args.input).read()
    except FileNotFoundError:
        print(f"ckc: error: file not found: {args.input}", file=sys.stderr)
        sys.exit(1)

    # ── lex ──────────────────────────────────────────────────────────────────
    try:
        tokens = tokenize(source, filename=args.input)
    except LexError as e:
        print(f"ckc: lexer error: {e}", file=sys.stderr)
        sys.exit(1)

    if args.tokens:
        for t in tokens:
            print(t)
        return

    # ── build search paths ───────────────────────────────────────────────────
    import os
    ckc_dir      = os.path.dirname(os.path.realpath(__file__))
    std_path     = os.path.join(ckc_dir, "std")
    search_paths = [std_path] + args.include

    # ── parse ────────────────────────────────────────────────────────────────
    try:
        ast = parse(tokens, filename=args.input,
                    search_paths=search_paths)
    except ParseError as e:
        print(f"ckc: {e}", file=sys.stderr)
        sys.exit(1)

    if args.ast:
        import pprint
        pprint.pprint(ast)
        return

    # ── resolve imports ───────────────────────────────────────────────────────
    try:
        ast = resolve(ast, args.input, search_paths)
    except ImportError as e:
        print(f"ckc: {e}", file=sys.stderr)
        sys.exit(1)

    # ── evaluate $if conditionals ─────────────────────────────────────────────
    try:
        cfg = BuildConfig.from_args(args)
        ast = evaluate(ast, cfg)
    except CondError as e:
        print(f"ckc: {e}", file=sys.stderr)
        sys.exit(1)

    # ── flatten namespaces ───────────────────────────────────────────────────
    ast = flatten(ast)

    # ── monomorphize ─────────────────────────────────────────────────────────
    try:
        ast = monomorphize(ast)
    except InterfaceError as e:
        print(f"ckc: {e}", file=sys.stderr)
        sys.exit(1)

    # ── inject auto $init for tag unions (per variant) ──────────────────────
    ast = inject_tag_union_inits(ast)

    # ── interface check ───────────────────────────────────────────────────────
    try:
        check(ast)
    except InterfaceError as e:
        print(f"ckc: {e}", file=sys.stderr)
        sys.exit(1)

    # ── inject auto $dinit for structs with dinit-able fields ────────────────
    ast = inject_field_dinits(ast)

    # ── emit ─────────────────────────────────────────────────────────────────
    output = emit(ast)

    if args.output:
        open(args.output, "w").write(output)
        print(f"ckc: wrote {args.output}")
    else:
        print(output)

    # ── emit header ───────────────────────────────────────────────────────────
    if args.emit_header:
        hdr = emit_header(ast, source_path=args.input)
        open(args.emit_header, "w").write(hdr)
        print(f"ckc: wrote {args.emit_header}")


if __name__ == "__main__":
    main()
