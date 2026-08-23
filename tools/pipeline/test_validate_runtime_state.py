#!/usr/bin/env python3
"""Focused regression tests for runtime-state UE authority evidence.

The validator is exercised through its public CLI entry point against a temporary
copy of the tracked runtime-state inputs.  This keeps the legacy UE report as a
realistic regression fixture without rewriting any generated repository report.
"""

import contextlib
import io
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path


PIPELINE_ROOT = Path(__file__).resolve().parent
REPO_ROOT = Path(__file__).resolve().parents[2]
if str(PIPELINE_ROOT) not in sys.path:
    sys.path.insert(0, str(PIPELINE_ROOT))

import validate_runtime_state as validator


NAME = "Desert_Ash_IndustrialYard_01"
SCENARIO = "activate_industrial_forge"
RUN_ID = "{}__{}".format(NAME, SCENARIO)
RUN_ROOT = Path("procedural/generated/scenarios") / RUN_ID
REPORT_ROOT = Path("procedural/reports/scenarios") / RUN_ID
LEGACY_UE_REPORT = REPORT_ROOT / "ue_state_scenario_report.json"


class RuntimeStateAuthorityEvidenceTests(unittest.TestCase):
    """The UE readback can pass only on an explicit native-owner record."""

    def _legacy_report(self):
        return json.loads((REPO_ROOT / LEGACY_UE_REPORT).read_text(encoding="utf-8"))

    def _run_with_ue_report(self, ue_report):
        """Run the public validator in a temporary repository and return its check."""
        with tempfile.TemporaryDirectory() as tmp:
            temp_root = Path(tmp)
            for rel in (
                RUN_ROOT / "result.json",
                RUN_ROOT / "state_save.json",
                Path("procedural/definitions/scenarios") / (SCENARIO + ".yaml"),
                Path("procedural/generated/worldforge_scenario_registry.json"),
            ):
                destination = temp_root / rel
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(REPO_ROOT / rel, destination)

            ue_path = temp_root / LEGACY_UE_REPORT
            ue_path.parent.mkdir(parents=True, exist_ok=True)
            ue_path.write_text(json.dumps(ue_report), encoding="utf-8")

            old_root = validator.REPO_ROOT
            try:
                validator.REPO_ROOT = temp_root
                with contextlib.redirect_stdout(io.StringIO()):
                    with self.assertRaises(SystemExit):
                        validator.main(["--name", NAME, "--scenario", SCENARIO])
            finally:
                validator.REPO_ROOT = old_root

            result = json.loads(
                (temp_root / REPORT_ROOT / "validate_runtime_state_report.json").read_text(
                    encoding="utf-8"))
            return result["checks"]["ue_state_applied"]

    @staticmethod
    def _native_success_authority(writer="native"):
        return {
            "record_version": 1,
            "kind": "native_state_write_lease",
            "status": "success",
            "writer": writer,
            "scope": "Region",
            "context_id": NAME,
            "state_keys": ["industrial_pressure"],
        }

    def test_tracked_legacy_report_without_authority_is_rejected(self):
        check = self._run_with_ue_report(self._legacy_report())
        self.assertFalse(check["ok"])
        self.assertEqual("FAIL", check["verdict"])
        self.assertEqual("WF082_UE_STATE_NOT_APPLIED", check["code"])

    def test_incomplete_native_success_evidence_is_rejected(self):
        report = self._legacy_report()
        report["authority"] = {
            "record_version": 1,
            "kind": "native_state_write_lease",
            "status": "success",
            "writer": "native",
        }
        check = self._run_with_ue_report(report)
        self.assertFalse(check["ok"])
        self.assertEqual("FAIL", check["verdict"])

    def test_native_authority_required_is_rejected(self):
        report = self._legacy_report()
        report["authority"] = {
            "status": "native_authority_required",
            "detail": "native state-write authority is required",
        }
        check = self._run_with_ue_report(report)
        self.assertFalse(check["ok"])
        self.assertEqual("FAIL", check["verdict"])

    def test_unavailable_authority_detail_is_not_republished(self):
        report = self._legacy_report()
        report["authority"] = {
            "status": "native_authority_required",
            "detail": "opaque_lease_payload=must-not-be-republished",
        }
        check = self._run_with_ue_report(report)
        self.assertFalse(check["ok"])
        self.assertEqual("native state-write authority is required", check["detail"])

    def test_non_native_reporter_cannot_authorize_a_pass(self):
        for writer in ("editor_python", "console", "blueprint"):
            with self.subTest(writer=writer):
                report = self._legacy_report()
                report["authority"] = self._native_success_authority(writer=writer)
                check = self._run_with_ue_report(report)
                self.assertFalse(check["ok"])
                self.assertEqual("FAIL", check["verdict"])

    def test_authority_record_cannot_carry_a_capability_payload(self):
        report = self._legacy_report()
        authority = self._native_success_authority()
        authority["opaque_lease_payload"] = "must-not-be-serialized"
        report["authority"] = authority
        check = self._run_with_ue_report(report)
        self.assertFalse(check["ok"])
        self.assertEqual("FAIL", check["verdict"])

    def test_native_success_must_bind_the_descriptor_state_address(self):
        for field, wrong_value in (
                ("scope", "Local"),
                ("context_id", "Other_Context"),
                ("state_keys", ["other_state_key"])):
            with self.subTest(field=field):
                report = self._legacy_report()
                authority = self._native_success_authority()
                authority[field] = wrong_value
                report["authority"] = authority
                check = self._run_with_ue_report(report)
                self.assertFalse(check["ok"])
                self.assertEqual("FAIL", check["verdict"])

    def test_native_success_requires_each_ue_evidence_surface(self):
        for field in ("passed", "applied", "mpc_readback", "checks"):
            with self.subTest(field=field):
                report = self._legacy_report()
                report["authority"] = self._native_success_authority()
                report.pop(field)
                check = self._run_with_ue_report(report)
                self.assertFalse(check["ok"])
                self.assertEqual("FAIL", check["verdict"])

    def test_well_formed_native_success_authorizes_ue_readback(self):
        report = self._legacy_report()
        report["authority"] = self._native_success_authority()
        check = self._run_with_ue_report(report)
        self.assertTrue(check["ok"])
        self.assertEqual("PASS", check["verdict"])


if __name__ == "__main__":
    unittest.main()
