import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools.check_apko_lock_drift import collect


class LockEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source, self.work, self.output = (self.root / x for x in ('source', 'work', 'evidence'))
        (self.source / 'ci/apko').mkdir(parents=True)
        self.work.mkdir()
        self.meta = {'source_sha': 'a' * 40, 'supply_tool_sha': 'b' * 40,
                     'apko_archive_sha256': 'c' * 64, 'apko_version': '1.4.4',
                     'run_id': '123', 'run_attempt': '1', 'build_outcome': 'success'}
        for kind in ('builder', 'runtime'):
            self.original(kind).write_bytes(b'{"packages": [{"version": "1"}]}\n')
            self.generated(kind).write_bytes(self.original(kind).read_bytes())
            (self.source / ('ci/apko/wolfi-python313-' + kind + '.apko.yaml')).write_bytes(b'archs: [amd64]\n')

    def original(self, kind):
        return self.source / ('ci/apko/wolfi-python313-' + kind + '.apko.lock.json')

    def generated(self, kind):
        return self.work / (kind + '.generated.lock.json')

    def run_collect(self):
        return collect(self.source, self.work, self.output, self.meta)

    def test_exact_match_preserves_six_input_files(self):
        report, code = self.run_collect()
        self.assertEqual(('MATCH', 0, 6), (report['result'], code, len(report['files'])))
        for kind in ('builder', 'runtime'):
            self.assertEqual(self.original(kind).read_bytes(), (self.output / (kind + '.repo.lock.json')).read_bytes())

    def test_builder_drift_does_not_mask_runtime_comparison(self):
        self.generated('builder').write_bytes(b'{"packages": [{"version": "2"}]}\n')
        report, code = self.run_collect()
        self.assertEqual(('DRIFT', 1), (report['result'], code))
        self.assertFalse(report['pairs']['builder']['byte_equal'])
        self.assertTrue(report['pairs']['runtime']['byte_equal'])
        self.assertIn('"version": "2"', (self.output / 'builder.diff').read_text())

    def test_runtime_drift_fails(self):
        self.generated('runtime').write_bytes(b'{"packages": []}\n')
        self.assertEqual(1, self.run_collect()[1])

    def test_formatting_difference_fails_byte_comparison(self):
        self.generated('runtime').write_bytes(b'{ "packages": [{"version": "1"}]}\n')
        self.assertEqual(1, self.run_collect()[1])

    def test_missing_generated_lock_retains_other_pair_and_original(self):
        self.generated('runtime').unlink()
        report, code = self.run_collect()
        self.assertEqual(('INCOMPLETE', 2), (report['result'], code))
        self.assertIn('builder', report['pairs'])
        self.assertTrue((self.output / 'runtime.repo.lock.json').is_file())

    def test_invalid_json_is_preserved_but_not_passed(self):
        self.generated('builder').write_bytes(b'not JSON\n')
        report, code = self.run_collect()
        self.assertEqual(2, code)
        self.assertEqual(b'not JSON\n', (self.output / 'builder.generated.lock.json').read_bytes())

    def test_duplicate_json_keys_are_not_passed(self):
        self.generated('builder').write_bytes(b'{"packages": [], "packages": [1]}')
        self.assertEqual(2, self.run_collect()[1])

    def test_nonfinite_json_is_not_passed(self):
        self.generated('builder').write_bytes(b'{"value": NaN}')
        self.assertEqual(2, self.run_collect()[1])

    def test_nonobject_json_is_not_passed(self):
        self.generated('builder').write_bytes(b'[]')
        self.assertEqual(2, self.run_collect()[1])

    def test_oversize_input_is_not_passed(self):
        self.generated('builder').write_bytes(b' ' * (1024 * 1024 + 1))
        self.assertEqual(2, self.run_collect()[1])

    def test_manifest_verifies_raw_diff_result_and_metadata(self):
        report, _ = self.run_collect()
        for line in (self.output / 'SHA256SUMS').read_text().splitlines():
            expected, name = line.split('  ', 1)
            self.assertEqual(expected, hashlib.sha256((self.output / name).read_bytes()).hexdigest())
        self.assertEqual(self.meta, report['provenance'])
        self.assertFalse(report['policy']['delivery_authorization'])

    def test_no_source_or_generated_input_is_modified(self):
        inputs = list(self.source.rglob('*')) + list(self.work.iterdir())
        before = {p: p.read_bytes() for p in inputs if p.is_file()}
        self.run_collect()
        self.assertEqual(before, {p: p.read_bytes() for p in before})

    def test_output_under_source_is_refused(self):
        self.output = self.source / 'diagnostics'
        with self.assertRaises(ValueError):
            self.run_collect()

    def test_existing_evidence_is_not_overwritten(self):
        self.output.mkdir()
        marker = self.output / 'marker'
        marker.write_text('original')
        with self.assertRaises(FileExistsError):
            self.run_collect()
        self.assertEqual('original', marker.read_text())

    def test_invalid_source_provenance_is_refused_before_output(self):
        self.meta['source_sha'] = 'main'
        with self.assertRaises(ValueError):
            self.run_collect()
        self.assertFalse(self.output.exists())

    def test_input_read_failure_is_not_match(self):
        with patch('tools.check_apko_lock_drift.read_regular', side_effect=PermissionError):
            self.assertEqual(2, self.run_collect()[1])

    def test_evidence_write_failure_propagates(self):
        with patch.object(Path, 'write_bytes', side_effect=PermissionError):
            with self.assertRaises(PermissionError):
                self.run_collect()

    def test_failed_build_is_recorded_separately_from_matching_locks(self):
        self.meta['build_outcome'] = 'failure'
        report, code = self.run_collect()
        self.assertEqual(0, code)
        self.assertEqual('failure', report['provenance']['build_outcome'])
        self.assertEqual('MATCH', report['result'])


if __name__ == '__main__':
    unittest.main()
