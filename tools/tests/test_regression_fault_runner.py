"""#50 rev3 리뷰 잔여 2·3 모의 검증: 이미 시작한 긴 작업을 절대 기한에 끊고 반드시 원복으로 넘어가는지.

실제 하위 프로세스(현재 Python으로 sleep)를 쓴다. 서버·oc·nft·클라우드 호출 없음.
"""
import os
import signal
import subprocess
import sys
import time
import unittest

from tools.regression import fault_clock as fc
from tools.regression import fault_runner as fr

PY = sys.executable
SLEEP_LONG = [PY, '-c', 'import time; time.sleep(30)']
IGNORE_TERM = [PY, '-c', 'import signal, time; signal.signal(signal.SIGTERM, signal.SIG_IGN); print("ready", flush=True); time.sleep(30)']
SLACK = 1.5  # 프로세스 생성·종료 지연 여유(초)


class Cleanup:
    def __init__(self):
        self.calls = []

    def __call__(self):
        self.calls.append(time.monotonic())
        return 'RESTORED'


class RunUntilTests(unittest.TestCase):
    def test_quick_work_done(self):
        c = Cleanup()
        r = fr.run_then_cleanup([PY, '-c', 'print("ok")'], time.monotonic() + 20, c, grace=0.5)
        self.assertEqual((r['result'], r['work']['status'], r['work']['rc']), ('WORK_DONE', 'DONE', 0))
        self.assertEqual(len(c.calls), 1, '정상 종료여도 원복은 한 번 부른다')
        self.assertEqual(r['cleanup'], 'RESTORED')

    def test_nonzero_exit_is_inconclusive_and_cleans_up(self):
        c = Cleanup()
        r = fr.run_then_cleanup([PY, '-c', 'raise SystemExit(3)'], time.monotonic() + 20, c, grace=0.5)
        self.assertEqual((r['result'], r['work']['rc']), ('INCONCLUSIVE', 3))
        self.assertEqual(len(c.calls), 1)

    def test_long_work_is_killed_at_deadline_then_cleanup(self):
        """예상보다 긴 B3E: 기한에 끊고 INCONCLUSIVE, 원복은 기한 직후 시작."""
        c = Cleanup()
        start = time.monotonic()
        deadline = start + 1.0
        r = fr.run_then_cleanup(SLEEP_LONG, deadline, c, grace=0.5)
        self.assertEqual((r['result'], r['work']['status']), ('INCONCLUSIVE', 'KILLED_AT_DEADLINE'))
        self.assertEqual(len(c.calls), 1)
        self.assertGreaterEqual(r['cleanup_at'], deadline)
        self.assertLess(r['cleanup_at'], deadline + 0.5 + SLACK, '종료 대기(grace) 뒤 바로 원복')

    @unittest.skipIf(os.name == 'nt', 'SIGTERM 무시는 POSIX에서만 의미가 있음(CI Linux에서 실행)')
    def test_term_ignored_is_killed_after_grace(self):
        c = Cleanup()
        deadline = time.monotonic() + 1.0
        r = fr.run_then_cleanup(IGNORE_TERM, deadline, c, grace=0.5)
        self.assertEqual(r['work']['status'], 'KILLED_AT_DEADLINE')
        self.assertEqual(r['work']['rc'], -signal.SIGKILL)
        self.assertLess(r['cleanup_at'], deadline + 0.5 + SLACK)
        self.assertEqual(len(c.calls), 1)

    def test_deadline_already_passed_not_started_but_cleans_up(self):
        def no_popen(*a, **k):
            raise AssertionError('기한이 지났으면 시작하지 않아야 함')
        c = Cleanup()
        r = fr.run_then_cleanup(SLEEP_LONG, time.monotonic() - 1, c, popen=no_popen)
        self.assertEqual((r['result'], r['work']['status']), ('INCONCLUSIVE', 'NOT_STARTED'))
        self.assertEqual(len(c.calls), 1)

    def test_start_failure_still_cleans_up(self):
        def broken_popen(*a, **k):
            raise FileNotFoundError('no such tool')
        c = Cleanup()
        r = fr.run_then_cleanup(['missing-tool'], time.monotonic() + 5, c, popen=broken_popen)
        self.assertEqual((r['result'], r['work']['status']), ('INCONCLUSIVE', 'START_FAILED'))
        self.assertEqual(len(c.calls), 1)

    def test_cleanup_failure_is_not_hidden(self):
        def failing_cleanup():
            raise RuntimeError('restore failed')
        with self.assertRaises(RuntimeError):
            fr.run_then_cleanup([PY, '-c', 'pass'], time.monotonic() + 5, failing_cleanup, grace=0.5)


class CleanupStartBoundTests(unittest.TestCase):
    """F1-R1을 실행 호출부에 연결: t_start+240 직전에 시작한 긴 작업이어도 원복 시작이 240초를 넘지 않는다."""

    def test_cleanup_starts_by_t_start_plus_240(self):
        grace = 0.5
        t_start = time.monotonic() - (fc.CLEANUP_START - 2.0)  # 정리 시작까지 2초 남은 상황
        deadline = fr.work_deadline(t_start, fc.CLEANUP_START, grace)
        self.assertAlmostEqual(deadline, t_start + 239.5)
        c = Cleanup()
        r = fr.run_then_cleanup(SLEEP_LONG, deadline, c, grace=grace)
        self.assertEqual(r['work']['status'], 'KILLED_AT_DEADLINE')
        self.assertLessEqual(r['cleanup_at'] - t_start, fc.CLEANUP_START + SLACK)
        # 정리 단계 timeout은 CAP 안 남은 시간으로 제한된다
        b = fc.budget(r['cleanup_at'], t_start, 'cleanup', 10)
        self.assertFalse(b['cap_violation'])
        self.assertLessEqual(b['timeout'], fc.CAP - (r['cleanup_at'] - t_start))

    def test_work_deadline_rejects_negative_grace(self):
        with self.assertRaises(ValueError):
            fr.work_deadline(0, fc.CLEANUP_START, -1)


if __name__ == '__main__':
    unittest.main()
