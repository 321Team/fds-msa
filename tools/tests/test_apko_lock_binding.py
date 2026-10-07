import json
import os
from pathlib import Path
import tempfile
import unittest

from tools.check_apko_lock_binding import apko_checksum, main

CFG = 'ci/apko/wolfi-python313-builder.apko.yaml'


class LockBindingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.cwd = os.getcwd()
        os.chdir(self.temp.name)
        self.addCleanup(os.chdir, self.cwd)
        Path('ci/apko').mkdir(parents=True)
        self.cfg_bytes = b'contents:\n  packages:\n    - busybox\n'
        Path(CFG).write_bytes(self.cfg_bytes)
        self.lock = Path('builder.lock.json')
        self.write_lock()

    def write_lock(self, name=CFG, checksum=None, packages=None, raw=None):
        if raw is not None:
            self.lock.write_text(raw)
            return
        self.lock.write_text(json.dumps({
            'version': 'v1',
            'config': {'name': name, 'checksum': checksum or apko_checksum(self.cfg_bytes)},
            'contents': {'packages': [{'name': 'busybox'}] if packages is None else packages},
        }))

    def test_matching_binding_passes(self):
        self.assertEqual(main([CFG, str(self.lock)]), 0)

    def test_known_apko_checksum_format(self):
        # Real main lock: YAML sha256 c2c0d81e... is recorded as base64 "wsDYHsSi...".
        digest = bytes.fromhex('c2c0d81ec4a20fb06417b66c5a1d1a1c04a068f1c0c76d37a35f2c12bab264b2')
        import base64
        self.assertEqual('sha256-' + base64.b64encode(digest).decode(),
                         'sha256-wsDYHsSiD7BkF7ZsWh0aHASgaPHAx203o18sErqyZLI=')

    def test_changed_yaml_fails(self):
        Path(CFG).write_bytes(self.cfg_bytes + b'    - tzdata\n')
        self.assertEqual(main([CFG, str(self.lock)]), 1)

    def test_wrong_config_name_fails(self):
        self.write_lock(name='/tmp/abs/' + CFG)
        self.assertEqual(main([CFG, str(self.lock)]), 1)

    def test_empty_packages_fails(self):
        self.write_lock(packages=[])
        self.assertEqual(main([CFG, str(self.lock)]), 1)

    def test_duplicate_key_fails(self):
        self.write_lock(raw='{"config": {}, "config": {}}')
        self.assertEqual(main([CFG, str(self.lock)]), 1)

    def test_missing_lock_fails(self):
        self.assertEqual(main([CFG, 'missing.json']), 1)

    def test_bad_arguments(self):
        self.assertEqual(main([CFG]), 2)


if __name__ == '__main__':
    unittest.main()
