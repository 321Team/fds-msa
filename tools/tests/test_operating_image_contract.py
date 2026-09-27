"""Static contract for the approved DEC-P1-IMG-01 operating image boundary."""
from pathlib import Path
import re
import unittest
import yaml

ROOT = Path(__file__).resolve().parents[2]


class OperatingImageContractTests(unittest.TestCase):
    def test_apko_runtime_matches_sec04_identity(self):
        cfg = yaml.safe_load((ROOT / "ci/apko/wolfi-python313-runtime.apko.yaml").read_text())
        accounts = cfg["accounts"]
        self.assertEqual(accounts["run-as"], "fdsapp")
        self.assertIn({"groupname": "fdsapp", "gid": 999}, accounts["groups"])
        self.assertIn(
            {"username": "fdsapp", "uid": 10001, "gid": 999},
            accounts["users"],
        )

    def test_operating_dockerfiles_use_injected_apko_bases_and_sec04_user(self):
        for service in ("transaction-api", "fds-engine"):
            with self.subTest(service=service):
                text = (ROOT / service / "Dockerfile").read_text()
                self.assertRegex(text, r"(?m)^ARG BUILDER_IMAGE$")
                self.assertRegex(text, r"(?m)^ARG RUNTIME_IMAGE$")
                self.assertIn("FROM ${BUILDER_IMAGE} AS build", text)
                self.assertIn("FROM ${RUNTIME_IMAGE}", text)
                self.assertIn("RUN python3.13 -m venv --copies /venv", text)
                self.assertRegex(text, r"(?m)^USER 10001:999$")
                self.assertNotIn("gcr.io/distroless", text)
                self.assertNotIn("docker.io/library/python@", text)
                self.assertNotRegex(text, r"(?m)^ARG (?:BUILDER|RUNTIME)_IMAGE=")


if __name__ == "__main__":
    unittest.main()
