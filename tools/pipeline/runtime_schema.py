#!/usr/bin/env python3
"""runtime_schema.py — WorldForge v1.6 shared strict-schema helpers.

Every v1.6 runtime contract (scenario, pawn, route, interaction, telemetry,
completion, save/load) validates a plain dict against a declared field set. This
module holds the small, dependency-free primitives they share so the STRICT
rules are identical everywhere:

    * required fields must be present and non-None
    * under STRICT no *unknown* field may appear (the brief: "No unknown fields
      in STRICT")
    * enum fields must be members of their registry
    * numeric fields must be real numbers, and where declared, > 0

Each helper returns a list of ``(check_name, ok, detail, failure_code)`` tuples
in the exact shape the validators feed to ``ValidationReport.check`` — so a
contract's ``validate_*`` is just a concatenation of these calls plus any
domain-specific cross-field checks. Stdlib only.
"""

import numbers

# Re-exported so contracts and validators share one truthy-flag resolver.
try:
    from report_meta import strict_from_env  # noqa: F401
except Exception:  # pragma: no cover - contracts may be imported in isolation
    import os

    def strict_from_env(default=False):
        val = os.environ.get("STRICT")
        if val is None:
            return default
        return str(val).strip().lower() in ("1", "true", "yes", "on")


def is_number(v):
    """True for a real int/float (bool is explicitly NOT a number here)."""
    return isinstance(v, numbers.Real) and not isinstance(v, bool)


def check_required(obj, required, code, prefix="", nullable=()):
    """One check per required field: present AND not None.

    Fields listed in ``nullable`` must be *present* (the key exists) but may hold
    None — e.g. a completion report's ``failure_code`` is None on success but the
    key must still be there, since an absent key is itself a report-integrity
    smell.
    """
    nullable = set(nullable)
    checks = []
    for f in required:
        has_key = isinstance(obj, dict) and f in obj
        if f in nullable:
            ok = has_key
            detail = ("required field {!r} present".format(f) if ok
                      else "required field {!r} missing (key absent)".format(f))
        else:
            ok = has_key and obj.get(f) is not None
            detail = ("required field {!r} present".format(f) if ok
                      else "required field {!r} missing or null".format(f))
        checks.append(("{}field::{}".format(prefix, f), ok, detail, code))
    return checks


def check_no_unknown(obj, allowed, code, strict, prefix=""):
    """STRICT-only: reject any field outside the allowed set.

    Non-strict runs record the same check as passing (unknown fields are a
    smell, not a hard error, until STRICT) so behaviour matches the rest of the
    platform: strict only ever ADDS blocking.
    """
    if not isinstance(obj, dict):
        return [("{}no_unknown_fields".format(prefix), False,
                 "not a mapping", code)]
    unknown = sorted(k for k in obj.keys() if k not in set(allowed))
    ok = (not unknown) or (not strict)
    detail = ("no unknown fields" if not unknown
              else "unknown field(s) {} {}".format(
                  unknown, "rejected under STRICT" if strict else "(allowed; STRICT would reject)"))
    return [("{}no_unknown_fields".format(prefix), ok, detail, code)]


def check_enum(obj, field, registry, code, prefix="", required=True):
    """The field's value must be a member of ``registry``."""
    if not isinstance(obj, dict) or obj.get(field) is None:
        if not required:
            return []
        return [("{}enum::{}".format(prefix, field), False,
                 "missing enum field {!r}".format(field), code)]
    val = obj.get(field)
    ok = val in registry
    return [("{}enum::{}".format(prefix, field), ok,
             "{}={!r} is a known value".format(field, val) if ok
             else "{}={!r} not in {}".format(field, val, tuple(registry)[:8]), code)]


def check_positive_number(obj, field, code, prefix="", allow_zero=False):
    """The field must be a real number, and > 0 (or >= 0 if allow_zero)."""
    if not isinstance(obj, dict) or field not in obj:
        return [("{}number::{}".format(prefix, field), False,
                 "missing numeric field {!r}".format(field), code)]
    val = obj.get(field)
    if not is_number(val):
        return [("{}number::{}".format(prefix, field), False,
                 "{}={!r} is not a number".format(field, val), code)]
    ok = (val >= 0) if allow_zero else (val > 0)
    return [("{}number::{}".format(prefix, field), ok,
             "{}={} is {}".format(field, val, ">=0" if allow_zero else ">0") if ok
             else "{}={} must be {}".format(field, val, ">=0" if allow_zero else ">0"), code)]


def check_type(obj, field, py_type, code, prefix="", required=True, type_label=None):
    """The field must be an instance of ``py_type`` (tuple of types allowed)."""
    if not isinstance(obj, dict) or field not in obj or obj.get(field) is None:
        if not required:
            return []
        return [("{}type::{}".format(prefix, field), False,
                 "missing field {!r}".format(field), code)]
    val = obj.get(field)
    # bool is a subclass of int — guard against it slipping through int checks.
    ok = isinstance(val, py_type) and not (py_type in (int, (int, float)) and isinstance(val, bool))
    label = type_label or getattr(py_type, "__name__", str(py_type))
    return [("{}type::{}".format(prefix, field), ok,
             "{} is {}".format(field, label) if ok
             else "{}={!r} must be {}".format(field, val, label), code)]


def check_transform(obj, field, code, prefix="", require_yaw=False):
    """A transform must be a mapping with numeric x/y/z (and yaw if required)."""
    t = obj.get(field) if isinstance(obj, dict) else None
    if not isinstance(t, dict):
        return [("{}transform::{}".format(prefix, field), False,
                 "{} must be an object with x/y/z".format(field), code)]
    keys = ("x", "y", "z") + (("yaw",) if require_yaw else ())
    bad = [k for k in keys if not is_number(t.get(k))]
    ok = not bad
    return [("{}transform::{}".format(prefix, field), ok,
             "{} has numeric {}".format(field, "/".join(keys)) if ok
             else "{} missing/non-numeric: {}".format(field, bad), code)]


def collect(rep, checks):
    """Feed a list of (name, ok, detail, code) tuples into a ValidationReport."""
    for name, ok, detail, code in checks:
        rep.check(name, ok, detail, code=code)
    return rep
