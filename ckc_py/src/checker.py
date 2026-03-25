"""
CK Interface Checker
Validates that every struct annotated with $implement(Iface) satisfies
the contract defined by $interface struct Iface.

Runs after monomorphization, before emission.
Errors are reported at the $implement declaration site.
"""

from __future__ import annotations
from .ast import *


class InterfaceError(Exception):
    def __init__(self, msg: str, line: int = 0):
        super().__init__(f"[line {line}] InterfaceError: {msg}")


def _render_type(t: TypeName) -> str:
    """Human-readable type string for error messages."""
    s = t.name
    if t.args:
        s += "(" + ", ".join(_render_type(a) for a in t.args) + ")"
    if t.pointer: s += "*"
    if t.ref:     s += "&"
    return s


def _sig(method: FnDecl) -> str:
    """Canonical signature string for comparison: name(T1,T2,...)->R"""
    params = ",".join(_render_type(p.type) for p in method.params)
    ret    = _render_type(method.return_type)
    return f"{method.name}({params})->{ret}"


def check(prog: Program) -> None:
    """
    Walk the program, collect interface definitions, then validate
    every $implement annotation. Raises InterfaceError on first violation.
    """
    # collect all $interface structs: name → {method_name → FnDecl}
    interfaces: dict[str, dict[str, FnDecl]] = {}
    for d in prog.decls:
        if isinstance(d, StructDecl) and d.is_interface:
            method_map = {m.name: m for m in d.methods}
            interfaces[d.name] = method_map

    if not interfaces:
        return  # nothing to check

    # validate every $implement struct
    for d in prog.decls:
        if not isinstance(d, StructDecl):
            continue
        if not d.implements:
            continue

        # build method map for this struct
        struct_methods = {m.name: m for m in d.methods}

        for iface_name in d.implements:
            if iface_name not in interfaces:
                raise InterfaceError(
                    f"Struct '{d.name}' implements unknown interface '{iface_name}'",
                    d.line)

            required = interfaces[iface_name]

            for method_name, iface_method in required.items():
                if method_name not in struct_methods:
                    raise InterfaceError(
                        f"Struct '{d.name}' is missing method '{method_name}' "
                        f"required by interface '{iface_name}'\n"
                        f"  expected: {_sig(iface_method)}",
                        d.line)

                impl_method = struct_methods[method_name]

                # check param count
                if len(impl_method.params) != len(iface_method.params):
                    raise InterfaceError(
                        f"Struct '{d.name}' method '{method_name}' has wrong "
                        f"number of parameters for interface '{iface_name}'\n"
                        f"  expected: {_sig(iface_method)}\n"
                        f"  got:      {_sig(impl_method)}",
                        impl_method.line)

                # check param types
                for i, (ip, ep) in enumerate(
                        zip(impl_method.params, iface_method.params)):
                    if _render_type(ip.type) != _render_type(ep.type):
                        raise InterfaceError(
                            f"Struct '{d.name}' method '{method_name}' "
                            f"param {i+1} type mismatch for interface '{iface_name}'\n"
                            f"  expected: {_render_type(ep.type)}\n"
                            f"  got:      {_render_type(ip.type)}",
                            impl_method.line)

                # check return type
                if _render_type(impl_method.return_type) != \
                   _render_type(iface_method.return_type):
                    raise InterfaceError(
                        f"Struct '{d.name}' method '{method_name}' "
                        f"return type mismatch for interface '{iface_name}'\n"
                        f"  expected: {_render_type(iface_method.return_type)}\n"
                        f"  got:      {_render_type(impl_method.return_type)}",
                        impl_method.line)


def check_bound(type_name: str, bound: str,
                interfaces: dict[str, dict[str, FnDecl]],
                structs: dict[str, StructDecl],
                line: int = 0) -> None:
    """
    Verify that type_name satisfies the interface bound.
    Called by the monomorphizer when instantiating a bounded template.
    """
    if bound not in interfaces:
        return  # not a known interface — skip (might be type/numeric/etc)
    required = interfaces[bound]
    struct = structs.get(type_name)
    if struct is None:
        return  # primitive type — no methods to check
    struct_methods = {m.name: m for m in struct.methods}
    for method_name, iface_method in required.items():
        if method_name not in struct_methods:
            raise InterfaceError(
                f"Type '{type_name}' does not satisfy bound '{bound}': "
                f"missing method '{method_name}'\n"
                f"  expected: {_sig(iface_method)}",
                line)


def build_interface_map(prog: Program) -> dict[str, dict[str, FnDecl]]:
    """Build {interface_name: {method_name: FnDecl}} from a program."""
    result: dict[str, dict[str, FnDecl]] = {}
    for d in prog.decls:
        if isinstance(d, StructDecl) and d.is_interface:
            result[d.name] = {m.name: m for m in d.methods}
    return result


def build_struct_map(prog: Program) -> dict[str, StructDecl]:
    """Build {struct_name: StructDecl} from a program."""
    return {d.name: d for d in prog.decls if isinstance(d, StructDecl)}
