"""Reject stale/malformed locks by mutating copies of the real app profiles."""
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from check_dependency_locks import check


class DependencyLockTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        source = Path(__file__).resolve().parents[2]
        for service in ("transaction-api", "fds-engine"):
            (self.root / service).mkdir()
            for path in (source / service).glob("requirements*"):
                shutil.copyfile(path, self.root / service / path.name)

    def change(self, name, old, new):
        path = self.root / "transaction-api" / name
        text = path.read_text()
        self.assertIn(old, text)
        path.write_text(text.replace(old, new, 1))

    def test_current_profiles(self):
        check(self.root)

    def test_changed_root_version_requires_new_lock(self):
        self.change("requirements.txt", "fastapi==0.141.1", "fastapi==0.141.2")
        with self.assertRaisesRegex(ValueError, "root/lock mismatch"):
            check(self.root)

    def test_missing_runtime_package(self):
        self.change("requirements-runtime.lock", "fastapi==", "missing-fastapi==")
        with self.assertRaisesRegex(ValueError, "root/lock mismatch"):
            check(self.root)

    def test_required_extras_cannot_disappear(self):
        self.change("requirements-runtime.lock", "uvicorn[standard]", "uvicorn")
        with self.assertRaisesRegex(ValueError, "root/lock mismatch"):
            check(self.root)

    def test_invalid_hash(self):
        self.change("requirements-test.lock", "--hash=sha256:", "--hash=md5:")
        with self.assertRaisesRegex(ValueError, "invalid hash"):
            check(self.root)

    def test_duplicate_package(self):
        path = self.root / "transaction-api/requirements-runtime.lock"
        path.write_text(path.read_text() + path.read_text().splitlines()[0] + "\n")
        with self.assertRaisesRegex(ValueError, "duplicate package"):
            check(self.root)

    def test_runtime_test_wheel_drift(self):
        path = self.root / "transaction-api/requirements-test.lock"
        text = path.read_text()
        digest = text.split("--hash=sha256:", 1)[1][:64]
        path.write_text(text.replace(digest, "0" * 64, 1))
        with self.assertRaisesRegex(ValueError, "runtime/test lock drift"):
            check(self.root)

    def test_test_roots_cannot_include_remote_inputs(self):
        self.change("requirements-test.txt", "-r requirements.txt", "-r https://example.invalid/requirements.txt")
        with self.assertRaisesRegex(ValueError, "local runtime include"):
            check(self.root)
