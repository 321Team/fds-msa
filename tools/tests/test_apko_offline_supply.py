import io
import json
from pathlib import Path
import tarfile
import tempfile
import unittest
import zipfile

from tools.create_apko_offline_supply import normalize, oci_identity, parse_roots, wheel_metadata


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

    def test_oci_identity_binds_index_manifest_config_and_layers(self):
        import hashlib
        config = {
            "architecture": "amd64",
            "os": "linux",
            "rootfs": {"type": "layers", "diff_ids": ["sha256:" + "1" * 64]},
        }
        config_raw = json.dumps(config, separators=(",", ":")).encode()
        config_digest = "sha256:" + hashlib.sha256(config_raw).hexdigest()
        layer_raw = b"layer bytes"
        layer_digest = "sha256:" + hashlib.sha256(layer_raw).hexdigest()
        manifest = {
            "schemaVersion": 2,
            "mediaType": "application/vnd.oci.image.manifest.v1+json",
            "config": {
                "mediaType": "application/vnd.oci.image.config.v1+json",
                "digest": config_digest,
                "size": len(config_raw),
            },
            "layers": [{
                "mediaType": "application/vnd.oci.image.layer.v1.tar+gzip",
                "digest": layer_digest,
                "size": len(layer_raw),
            }],
        }
        manifest_raw = json.dumps(manifest, separators=(",", ":")).encode()
        manifest_digest = "sha256:" + hashlib.sha256(manifest_raw).hexdigest()
        index = {
            "schemaVersion": 2,
            "manifests": [{
                "mediaType": "application/vnd.oci.image.manifest.v1+json",
                "digest": manifest_digest,
                "size": len(manifest_raw),
                "platform": {"architecture": "amd64", "os": "linux"},
            }],
        }
        index_raw = json.dumps(index, separators=(",", ":")).encode()
        archive_path = self.root / "image.oci.tar"
        with tarfile.open(archive_path, "w") as archive:
            payloads = {
                "oci-layout": b'{"imageLayoutVersion":"1.0.0"}',
                "index.json": index_raw,
                "blobs/sha256/" + manifest_digest[7:]: manifest_raw,
                "blobs/sha256/" + config_digest[7:]: config_raw,
                "blobs/sha256/" + layer_digest[7:]: layer_raw,
            }
            for name, value in payloads.items():
                info = tarfile.TarInfo(name)
                info.size = len(value)
                archive.addfile(info, io.BytesIO(value))
        identity = oci_identity(archive_path)
        self.assertEqual(identity["manifest_digest"], manifest_digest)
        self.assertEqual(identity["config_digest"], config_digest)
        self.assertEqual(identity["platform"], "linux/amd64")
        self.assertEqual(identity["layer_count"], 1)


if __name__ == "__main__":
    unittest.main()
