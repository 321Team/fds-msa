import os
from pathlib import Path
import subprocess
import tempfile
import unittest

from tools.check_apko_lock_age import main

LOCK = 'ci/apko/builder.lock.json'
T0 = 1791000000  # fixed author time for the lock commit
DAY = 86400


class LockAgeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.cwd = os.getcwd()
        os.chdir(self.temp.name)
        self.addCleanup(os.chdir, self.cwd)
        self.git('init', '-q')
        Path('ci/apko').mkdir(parents=True)
        Path(LOCK).write_text('{}')
        self.commit(T0, LOCK)

    def git(self, *args, env=None):
        subprocess.run(['git', *args], check=True, capture_output=True, env=env)

    def commit(self, when, path):
        env = dict(os.environ, GIT_AUTHOR_NAME='t', GIT_AUTHOR_EMAIL='t@example.invalid',
                   GIT_COMMITTER_NAME='t', GIT_COMMITTER_EMAIL='t@example.invalid',
                   GIT_AUTHOR_DATE=f'@{when} +0000', GIT_COMMITTER_DATE=f'@{when} +0000')
        self.git('add', path, env=env)
        self.git('commit', '-q', '-m', 'c', env=env)

    def test_within_limit_passes(self):
        self.assertEqual(main(['--now', str(T0 + 3 * DAY), LOCK]), 0)

    def test_over_limit_fails(self):
        self.assertEqual(main(['--now', str(T0 + 3 * DAY + 1), LOCK]), 1)

    def test_later_unrelated_commit_does_not_reset_age(self):
        Path('README').write_text('x')
        self.commit(T0 + 5 * DAY, 'README')
        self.assertEqual(main(['--now', str(T0 + 5 * DAY), LOCK]), 1)

    def test_lock_refresh_resets_age(self):
        Path(LOCK).write_text('{"v": 2}')
        self.commit(T0 + 5 * DAY, LOCK)
        self.assertEqual(main(['--now', str(T0 + 5 * DAY), LOCK]), 0)

    def test_shallow_clone_fails(self):
        Path('.git/shallow').write_text('0' * 40 + '\n')
        self.assertEqual(main(['--now', str(T0), LOCK]), 1)

    def test_uncommitted_lock_fails(self):
        self.assertEqual(main(['--now', str(T0), 'ci/apko/missing.lock.json']), 1)

    def test_bad_arguments(self):
        self.assertEqual(main([]), 2)
        self.assertEqual(main(['--max-days', '0', LOCK]), 2)
        self.assertEqual(main(['--max-days', 'x', LOCK]), 2)


if __name__ == '__main__':
    unittest.main()
