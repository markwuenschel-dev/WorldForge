#!/usr/bin/env python3
"""wfcore.failure -- the ONE failure-code authority, re-exported for Core.

WHY THIS IS A SHIM AND NOT A SECOND CODE TABLE
----------------------------------------------
Failure codes are a repository-wide namespace. They are published to callers as
part of the contract surface, rolled up by lane in the shields, and checked for
orphans by ``validate_failure_codes``. A second table inside Core would create
two authorities for one namespace: codes could collide, drift in severity, or be
published as "owned" by one table while the other never raises them.

So Core does not define codes. It imports ``tools/pipeline/failure_codes.py``,
which remains the single source of truth, and adds its own band (WF1200-1299)
there alongside every other band.

THE sys.path INSERT
-------------------
``tools/pipeline`` is a flat script directory, not a package -- its modules
import each other bare (``import runtime_schema as RS``). Core is a real package
under ``tools/``, so a plain ``from pipeline import failure_codes`` cannot work
without turning that directory into a package and rewriting ~250 flat imports.

The insert is therefore deliberate, narrow, and idempotent: it makes exactly one
directory importable, appends rather than prepends where possible so Core cannot
shadow stdlib, and is confined to this module so no other Core file needs to
know the layout. If ``tools/pipeline`` ever becomes a package, only this file
changes.

A NOTE ON DEFINING NEW CODES (learned the hard way)
---------------------------------------------------
``failure_codes.py`` auto-backfills SEVERITY and GATE_TAXONOMY for any constant
typed into ``FailureCode``. That means DEFINING a code is free and proves
nothing: a code can be published to callers as owned while no code path in the
repository can raise it. Every code in the WF1200 band must therefore have a
real raise site and a negative test that observes it. Adding the constant is the
beginning of the work, not the end.
"""

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_PIPELINE = os.path.normpath(os.path.join(_HERE, os.pardir, "pipeline"))

if os.path.isdir(_PIPELINE) and _PIPELINE not in sys.path:
    # Appended, not inserted at 0: Core must never shadow a stdlib module for
    # the rest of the process just because it needed one flat directory.
    sys.path.append(_PIPELINE)

try:
    from failure_codes import FailureCode, all_codes, code_number, severity_of
except ImportError as exc:  # pragma: no cover - environment defect, not logic
    raise ImportError(
        "wfcore.failure could not import the repository failure-code authority "
        "from {!r}. Core deliberately has no fallback table: a second code "
        "table would be a second authority for a published namespace. Fix the "
        "path rather than defining codes locally.".format(_PIPELINE)) from exc

__all__ = ["FailureCode", "all_codes", "code_number", "severity_of"]
