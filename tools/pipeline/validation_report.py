#!/usr/bin/env python3
"""validation_report.py — WorldForge v0.9 shared validation report + status semantics.

Canonical, dependency-free helper that formalizes the check/report pattern every
WorldForge validator already uses and extends it with v0.9 strict-mode semantics
and the v0.9 status vocabulary.  This is a *thin shared helper, NOT a framework*:
it exists only so that strict / warn / fail semantics are identical across
every validator and so reports share one machine-readable shape.

It is a strict SUPERSET of the legacy inline pattern:

    result = {"<entity>": id, "checks": {}, "failures": []}
    def check(name, ok, detail="", warn_only=False): ...
    result["passed"] = len(result["failures"]) == 0
    result["status"] = "ok" if result["passed"] else "fail"

The on-disk JSON keeps every legacy key (``checks[*].ok``, ``checks[*].detail``,
``checks[*].warn_only``, ``failures``, ``warnings``, ``passed``, ``status``) so
existing consumers (e.g. validate_slice_pack.py reading ``rep["passed"]`` and
``checks[*].ok``) keep working unchanged.  New keys are additive.

------------------------------------------------------------------------------
Per-check verdict vocabulary
------------------------------------------------------------------------------
    PASS                  check evaluated and passed
    WARN                  soft failure: non-blocking in normal mode, BLOCKING in
                          strict mode (unless explicitly allowed) — a genuine
                          warning that production hardening should catch
    WARN_ONLY             intentionally non-blocking in BOTH modes (legacy
                          compatibility or an explicitly-allowed warning)
    FAIL                  blocking failure in BOTH modes
    SKIP_NOT_APPLICABLE   not evaluated because the spec genuinely lacks this
                          surface; non-blocking

------------------------------------------------------------------------------
Overall report status
------------------------------------------------------------------------------
    ok      no blocking failures and no unresolved soft warnings
    warn    no blocking failures, but unresolved WARN/WARN_ONLY present
    fail    one or more blocking failures
    error   validation could not run (missing / unparseable inputs)

``passed`` is True iff status in {"ok", "warn"} — i.e. no blocking failure.
Exit code is 0 when passed, else 1.

------------------------------------------------------------------------------
Strict mode (STRICT=1)
------------------------------------------------------------------------------
    FAIL                  always blocking
    WARN                  becomes blocking unless allow_in_strict=True
    WARN_ONLY             stays non-blocking (explicitly allowed / legacy)
    SKIP_NOT_APPLICABLE   stays non-blocking

Because nothing set STRICT before v0.9, non-strict behavior is byte-for-byte the
legacy behavior; strict only ever ADDS blocking, never removes it.

------------------------------------------------------------------------------
UE checks
------------------------------------------------------------------------------
``ue_check(name, ok, detail)`` is a normal blocking check for an artifact that
the tooling materializes by driving the Unreal editor (a generated map, a
heightmap import, an MI parameter override). If the artifact is present and
valid it PASSes; if it is missing it FAILs — the tooling runs the editor to
produce it. There is no "deferred" state: UE work is done, not postponed.
"""

import json
import os
import sys
from pathlib import Path

# -- Per-check verdicts -------------------------------------------------------
PASS = "PASS"
WARN = "WARN"
WARN_ONLY = "WARN_ONLY"
FAIL = "FAIL"
SKIP_NOT_APPLICABLE = "SKIP_NOT_APPLICABLE"

VERDICTS = (PASS, WARN, WARN_ONLY, FAIL, SKIP_NOT_APPLICABLE)

# -- Overall report status ----------------------------------------------------
STATUS_OK = "ok"
STATUS_WARN = "warn"
STATUS_FAIL = "fail"
STATUS_ERROR = "error"

SCHEMA_VERSION = "v0.9"


def strict_from_env(default=False):
    """Resolve STRICT from the environment (Makefile passes STRICT=1)."""
    val = os.environ.get("STRICT")
    if val is None:
        return default
    return str(val).strip().lower() in ("1", "true", "yes", "on")


class ValidationReport:
    """Accumulates checks and renders the canonical v0.9 report.

    Usage mirrors the legacy local ``check()`` closure::

        rep = ValidationReport("terrain_name", name, strict=strict_from_env())
        rep.check("descriptor_exists", path.is_file(), str(path))
        rep.check("terrain_imported_in_ue", imported,
                  "run 'make import-terrain ...'", warn_only=True)   # -> WARN
        rep.ue_check("asset_exists_in_ue_as_static_mesh", ue_ok, detail)  # -> PASS/FAIL
        rep.finalize()
        rep.write(report_dir, "validate_terrain_report.json")
        rep.print_summary("validate-terrain")
        sys.exit(rep.exit_code)
    """

    def __init__(self, entity_key, entity_id, strict=False):
        self.entity_key = entity_key
        self.entity_id = entity_id
        self.strict = bool(strict)
        self.checks = {}
        self.failures = []   # blocking, "name: detail"
        self.warnings = []   # non-blocking soft/gated, "name: detail"
        self._status = None  # set by finalize(); "error" may be forced earlier
        self._passed = None
        self._meta = None    # optional v1.0x report-metadata block (see report_meta.py)

    # -- v1.0x metadata ------------------------------------------------------
    def set_meta(self, meta):
        """Attach a v1.0x report-metadata block; emitted under ``meta`` in to_dict().

        Counts (status/failure_count/warning_count/skipped_count) are refreshed
        from the finalized report at write time so the meta block cannot drift
        from the actual check results.
        """
        self._meta = dict(meta) if meta else None
        return self

    # -- recording -----------------------------------------------------------
    def _record(self, name, verdict, detail, code, warn_only_legacy):
        ok = verdict == PASS
        blocking = self._is_blocking(verdict)
        self.checks[name] = {
            "ok": ok,
            "detail": str(detail),
            "warn_only": bool(warn_only_legacy),  # legacy back-compat key
            "verdict": verdict,
            "code": code,
            "blocking": blocking,
        }
        if not ok:
            line = "{}: {}".format(name, detail or verdict.lower())
            if blocking:
                self.failures.append(line)
            else:
                self.warnings.append(line)
        return ok

    def _is_blocking(self, verdict):
        if verdict == FAIL:
            return True
        if verdict == WARN:
            return self.strict
        # PASS, WARN_ONLY, SKIP_NOT_APPLICABLE
        return False

    # -- public check API ----------------------------------------------------
    def check(self, name, ok, detail="", warn_only=False, code=None,
              allow_in_strict=False):
        """Primary check. Behaves exactly like the legacy closure plus strict.

        ok=True                       -> PASS
        ok=False, warn_only=False     -> FAIL  (blocking in both modes)
        ok=False, warn_only=True      -> WARN  (blocking only under strict),
                                         or WARN_ONLY if allow_in_strict=True
        """
        if ok:
            return self._record(name, PASS, detail, None, warn_only)
        if not warn_only:
            return self._record(name, FAIL, detail, code, False)
        verdict = WARN_ONLY if allow_in_strict else WARN
        return self._record(name, verdict, detail, code, True)

    def ue_check(self, name, ok, detail="", code=None):
        """A check for an artifact the tooling materializes by driving the editor.

        Normal blocking check: present+valid -> PASS, missing -> FAIL. There is no
        deferred state — UE work is run, not postponed.
        """
        return self.check(name, ok, detail, code=code)

    def warn_only(self, name, ok, detail="", code=None):
        """Explicitly non-blocking warning in both modes (legacy compatibility)."""
        return self.check(name, ok, detail, warn_only=True, code=code,
                          allow_in_strict=True)

    def skip(self, name, detail="", code=None):
        """The spec genuinely lacks this surface; record and move on (non-blocking)."""
        return self._record(name, SKIP_NOT_APPLICABLE, detail, code, True)

    # -- terminal states -----------------------------------------------------
    def error(self, detail=""):
        """Force an ``error`` status (inputs missing/unparseable). Always blocking."""
        if detail:
            self.failures.append(detail)
        self._status = STATUS_ERROR
        self._passed = False
        return self

    def finalize(self):
        if self._status == STATUS_ERROR:
            self._passed = False
            return self
        self._passed = len(self.failures) == 0
        if not self._passed:
            self._status = STATUS_FAIL
        elif self.warnings:
            self._status = STATUS_WARN
        else:
            self._status = STATUS_OK
        return self

    # -- counts --------------------------------------------------------------
    def _counts(self):
        counts = {v: 0 for v in VERDICTS}
        for c in self.checks.values():
            counts[c.get("verdict", PASS)] = counts.get(c.get("verdict", PASS), 0) + 1
        return counts

    # -- output --------------------------------------------------------------
    def to_dict(self):
        if self._status is None:
            self.finalize()
        d = {
            self.entity_key: self.entity_id,
            "schema_version": SCHEMA_VERSION,
            "strict": self.strict,
            "checks": self.checks,
            "failures": self.failures,
        }
        if self.warnings:
            d["warnings"] = self.warnings
        d["counts"] = self._counts()
        d["passed"] = self._passed
        d["status"] = self._status
        if self._meta is not None:
            # Keep the meta block's derived counters honest with the real report.
            meta = dict(self._meta)
            meta["status"] = self._status
            meta["failure_count"] = len(self.failures)
            meta["warning_count"] = len(self.warnings)
            counts = self._counts()
            meta["skipped_count"] = counts.get(SKIP_NOT_APPLICABLE, 0)
            d["meta"] = meta
        return d

    @property
    def passed(self):
        if self._passed is None:
            self.finalize()
        return self._passed

    @property
    def status(self):
        if self._status is None:
            self.finalize()
        return self._status

    @property
    def exit_code(self):
        return 0 if self.passed else 1

    def write(self, report_dir, filename, quiet=False):
        report_dir = Path(report_dir)
        report_dir.mkdir(parents=True, exist_ok=True)
        rpt_path = report_dir / filename
        with rpt_path.open("w", encoding="utf-8") as fh:
            json.dump(self.to_dict(), fh, indent=2, ensure_ascii=False)
            fh.write("\n")
        if not quiet:
            try:
                shown = rpt_path.relative_to(Path.cwd())
            except ValueError:
                shown = rpt_path
            print("[{}] report -> {}".format(self.entity_key, shown))
        return rpt_path

    def print_summary(self, tag, stream=None):
        stream = stream or sys.stdout
        verdict = "PASS" if self.passed else "FAIL"
        n_fail = len(self.failures)
        n_warn = len(self.warnings)
        stream.write("[{}] {} — {} ({} failure(s), {} warning(s), strict={})\n".format(
            tag, verdict, self.entity_id, n_fail, n_warn, "on" if self.strict else "off"))
        for f in self.failures:
            stream.write("[{}]   FAIL: {}\n".format(tag, f))
        for name, c in self.checks.items():
            if c.get("verdict") in (WARN, WARN_ONLY) and not c["ok"]:
                stream.write("[{}]   {}: {}: {}\n".format(
                    tag, c["verdict"], name, c.get("detail", "")))
