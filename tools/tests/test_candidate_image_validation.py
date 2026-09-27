"""Reject invalid evidence before a candidate scan can be considered."""
import copy
from datetime import datetime, timezone
import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location("candidate", Path(__file__).parents[1] / "candidate_image_validation.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class CandidateEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.image = {"Id": "sha256:example", "RootFS": {"Layers": ["sha256:layer"]}}
        self.report = {"SchemaVersion": 2, "Trivy": {"Version": "0.74.0"}, "ArtifactType": "container_image", "Metadata": {"ImageID": "sha256:example", "DiffIDs": ["sha256:layer"]}, "Results": [{"Class": "os-pkgs", "Packages": [{"Name": "example"}]}]}
        self.report["Results"].append({"Class": "lang-pkgs", "Type": "python-pkg", "Packages": [{"Name": "fastapi", "Version": "0.141.1"}, {"Name": "starlette", "Version": "1.7.0"}]})

    def test_clean_report(self):
        self.assertEqual(module.report_decision(self.report, 0, self.image)["status"], "PASS")

    def test_vulnerability_blocks(self):
        self.report["Results"][0]["Vulnerabilities"] = [{"Severity": "HIGH", "VulnerabilityID": "CVE-example"}]
        self.assertEqual(module.report_decision(self.report, 10, self.image)["counts"]["HIGH"], 1)

    def test_error_never_passes(self):
        with self.assertRaisesRegex(ValueError, "SCANNER_ERROR"):
            module.report_decision(self.report, 2, self.image)

    def test_empty_inventory_rejected(self):
        self.report["Results"] = []
        with self.assertRaisesRegex(ValueError, "OS_INVENTORY_MISSING"):
            module.report_decision(self.report, 0, self.image)

    def test_different_image_rejected(self):
        self.report["Metadata"]["ImageID"] = "sha256:other"
        with self.assertRaisesRegex(ValueError, "REPORT_IMAGE_ID"):
            module.report_decision(self.report, 0, self.image)

    def test_different_layers_rejected(self):
        self.report["Metadata"]["DiffIDs"] = []
        with self.assertRaisesRegex(ValueError, "REPORT_LAYERS"):
            module.report_decision(self.report, 0, self.image)

    def test_exit_count_mismatch_rejected(self):
        with self.assertRaisesRegex(ValueError, "EXIT_COUNT_MISMATCH"):
            module.report_decision(self.report, 10, self.image)

    def test_missing_application_inventory_rejected(self):
        self.report["Results"].pop()
        with self.assertRaisesRegex(ValueError, "APP_INVENTORY_MISSING_OR_STALE"):
            module.report_decision(self.report, 0, self.image)

    def test_stale_application_inventory_rejected(self):
        self.report["Results"][1]["Packages"][0]["Version"] = "0.115.5"
        with self.assertRaisesRegex(ValueError, "APP_INVENTORY_MISSING_OR_STALE"):
            module.report_decision(self.report, 0, self.image)

    def test_unexpected_severity_rejected(self):
        self.report["Results"][0]["Vulnerabilities"] = [{"Severity": "LOW"}]
        with self.assertRaisesRegex(ValueError, "REPORT_SEVERITY"):
            module.report_decision(self.report, 10, self.image)

    def test_metadata_boundaries(self):
        valid = {"Version": 2, "UpdatedAt": "2026-09-23T00:00:00Z", "DownloadedAt": "2026-09-23T01:00:00Z", "NextUpdate": "2026-09-24T00:00:00Z"}
        checked = datetime(2026, 9, 23, 2, tzinfo=timezone.utc)
        module.metadata_valid(valid, checked)
        for key, value in (("Version", 1), ("DownloadedAt", "2026-09-23T03:00:00Z"), ("NextUpdate", "2026-09-23T02:00:00Z"), ("UpdatedAt", "2026-09-23T00:00:00")):
            with self.subTest(key=key):
                data = copy.deepcopy(valid)
                data[key] = value
                with self.assertRaises(ValueError):
                    module.metadata_valid(data, checked)


if __name__ == "__main__":
    unittest.main()
