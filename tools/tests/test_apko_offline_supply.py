import io
import json
from pathlib import Path
import tarfile
import tempfile
import unittest
import zipfile

from tools.create_apko_offline_supply import image_archive_identity, normalize, parse_roots, wheel_metadata


class OfflineSupplyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_parse_roots_expands_test_profile(self):
        service = self.root / "transaction-api"
        service.mkdir()
        (service / "requirements.txt").write_text("fastapi==0.141.1\nuvicorn[standard]==0.30.6\n")
        (service / "requirements-test.txt").write_text("-r requirements.txt\npytest==8.3.3\n")
        self.assertEqual(
            parse_roots(self.root, "transaction-api", "runtime"),
            ["fastapi==0.141.1", "uvicorn[standard]==0.30.6"],
        )
        self.assertEqual(
            parse_roots(self.root, "transaction-api", "test"),
            ["fastapi==0.141.1", "uvicorn[standard]==0.30.6", "pytest==8.3.3"],
        )

    def test_wheel_metadata_normalizes_name_and_reads_version(self):
        wheel = self.root / "Example_Pkg-1.2.3-py3-none-any.whl"
        with zipfile.ZipFile(wheel, "w") as archive:
            archive.writestr(
                "Example_Pkg-1.2.3.dist-info/METADATA",
                "Metadata-Version: 2.1\nName: Example_Pkg\nVersion: 1.2.3\n",
            )
        self.assertEqual(wheel_metadata(wheel), ("example-pkg", "1.2.3"))
        self.assertEqual(normalize("Example_Pkg"), "example-pkg")

    def test_image_archive_identity_binds_config_and_layer_diff_ids(self):
        import gzip
        import hashlib
        config = {
            "architecture": "amd64",
            "os": "linux",
            "rootfs": {"type": "layers", "diff_ids": []},
        }
        layer_plain = b"layer bytes"
        layer_raw = gzip.compress(layer_plain, mtime=0)
        diff_id = "sha256:" + hashlib.sha256(layer_plain).hexdigest()
        config["rootfs"]["diff_ids"] = [diff_id]
        config_raw = json.dumps(config, separators=(",", ":")).encode()
        config_digest = "sha256:" + hashlib.sha256(config_raw).hexdigest()
        layer_name = hashlib.sha256(layer_raw).hexdigest() + ".tar.gz"
        manifest = [{
            "Config": config_digest,
            "RepoTags": ["fds-apko-wolfi:test"],
            "Layers": [layer_name],
        }]
        manifest_raw = json.dumps(manifest, separators=(",", ":")).encode()
        index_raw = b'{"manifests":[]}'
        archive_path = self.root / "image.tar"
        with tarfile.open(archive_path, "w") as archive:
            payloads = {
                config_digest: config_raw,
                layer_name: layer_raw,
                "manifest.json": manifest_raw,
                "index.json": index_raw,
            }
            for name, value in payloads.items():
                info = tarfile.TarInfo(name)
                info.size = len(value)
                archive.addfile(info, io.BytesIO(value))
        identity = image_archive_identity(archive_path)
        self.assertEqual(identity["format"], "docker-archive")
        self.assertEqual(identity["config_digest"], config_digest)
        self.assertEqual(identity["platform"], "linux/amd64")
        self.assertEqual(identity["layer_count"], 1)



if __name__ == "__main__":
    unittest.main()
