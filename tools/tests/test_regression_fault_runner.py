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

    @unittest.skipIf(os.name == 'nt', '후손 프로세스 그룹 종료는 POSIX에서만(CI Linux에서 실행)')
    def test_descendant_holding_pipe_does_not_delay_cleanup(self):
        """비차단 권고 반례: 부모가 stdout을 물려준 자식(2.5초 sleep)을 만들어도 정리 시작이 밀리지 않는다."""
        parent = [PY, '-c', 'import subprocess, sys, time; '
                  'subprocess.Popen([sys.executable, "-c", "import time; time.sleep(2.5)"]); time.sleep(30)']
        c = Cleanup()
        deadline = time.monotonic() + 0.5
        r = fr.run_then_cleanup(parent, deadline, c, grace=0.1)
        self.assertEqual(r['work']['status'], 'KILLED_AT_DEADLINE')
        self.assertLess(r['cleanup_at'] - deadline, 3 * 0.1 + 1.0, '그룹 전체 종료 + 회수 제한으로 2.5초를 기다리지 않음')
        self.assertEqual(len(c.calls), 1)


class FakeProc:
    """communicate 첫 호출에서 지정 예외를 내는 가짜 프로세스(취소 모형). 실제 프로세스·신호 없음."""
    pid = -1

    def __init__(self, exc):
        self.exc = exc
        self.calls = 0
        self.returncode = None

    def communicate(self, timeout=None):
        self.calls += 1
        if self.calls == 1:
            raise self.exc
        self.returncode = -15
        return b'', b''

    def wait(self, timeout=None):
        return self.returncode


class CancellationTests(unittest.TestCase):
    """PR32 재리뷰 F1-R2: 작업 대기 중 취소(KeyboardInterrupt·SystemExit)에도 작업을 끝내고 원복을 1회 부른 뒤 취소를 올린다."""

    def setUp(self):
        self.signals = []
        self._orig = fr._signal_group
        fr._signal_group = lambda proc, sig: self.signals.append(sig)  # 가짜 pid로 실제 신호를 보내지 않게

    def tearDown(self):
        fr._signal_group = self._orig

    def run_cancel(self, exc, cleanup):
        proc = FakeProc(exc)
        return proc, (lambda argv, **k: proc), cleanup

    def test_keyboard_interrupt_cleans_up_once_and_propagates(self):
        c = Cleanup()
        proc, popen, _ = self.run_cancel(KeyboardInterrupt(), c)
        with self.assertRaises(KeyboardInterrupt):
            fr.run_then_cleanup(['work'], time.monotonic() + 30, c, grace=0.1, popen=popen)
        self.assertEqual(len(c.calls), 1, '취소돼도 원복 1회')
        self.assertEqual(self.signals[0], signal.SIGTERM, '작업 그룹 종료부터 시도')
        self.assertGreaterEqual(proc.calls, 2, '종료 뒤 회수 확인')

    def test_system_exit_cleans_up_once_and_propagates(self):
        c = Cleanup()
        _, popen, _ = self.run_cancel(SystemExit(2), c)
        with self.assertRaises(SystemExit):
            fr.run_then_cleanup(['work'], time.monotonic() + 30, c, grace=0.1, popen=popen)
        self.assertEqual(len(c.calls), 1)

    def test_cancel_then_cleanup_failure_keeps_original_cause(self):
        def failing_cleanup():
            raise RuntimeError('restore failed')
        _, popen, _ = self.run_cancel(KeyboardInterrupt(), None)
        with self.assertRaises(RuntimeError) as ctx:
            fr.run_then_cleanup(['work'], time.monotonic() + 30, failing_cleanup, grace=0.1, popen=popen)
        self.assertIsInstance(ctx.exception.__cause__, KeyboardInterrupt, '원복 실패를 올리되 원래 취소를 보존')


class CleanupStartBoundTests(unittest.TestCase):
    """F1-R1을 실행 호출부에 연결: t_start+240 직전에 시작한 긴 작업이어도 원복 시작이 240초를 넘지 않는다."""

    def test_cleanup_starts_by_t_start_plus_240(self):
        grace = 0.5
        # 단조 시계 원점은 호스트마다 다르다(갓 부팅한 CI 러너는 수십 초). 실제 경과는 그대로 두고 기준만 옮겨
        # t_start가 음수가 되지 않게 한다(fault_clock은 음수 시각을 거부).
        base = 100000.0
        clock = lambda: time.monotonic() + base  # noqa: E731
        t_start = clock() - (fc.CLEANUP_START - 2.0)  # 정리 시작까지 2초 남은 상황
        deadline = fr.work_deadline(t_start, fc.CLEANUP_START, grace)
        self.assertAlmostEqual(deadline, t_start + 238.5)
        c = Cleanup()
        r = fr.run_then_cleanup(SLEEP_LONG, deadline, c, clock=clock, grace=grace)
        self.assertEqual(r['work']['status'], 'KILLED_AT_DEADLINE')
        self.assertLessEqual(r['cleanup_at'] - t_start, fc.CLEANUP_START + SLACK)
        # 정리 단계 timeout은 CAP 안 남은 시간으로 제한된다
        b = fc.budget(r['cleanup_at'], t_start, 'cleanup', 10)
        self.assertFalse(b['cap_violation'])
        self.assertLessEqual(b['timeout'], fc.CAP - (r['cleanup_at'] - t_start))

    def test_stop_budget_worst_case_keeps_cleanup_by_240(self):
        """PR32 3차 리뷰 R5: 종료 절차가 모든 대기(TERM 회수·KILL 회수·wait)를 끝까지 써도 정리 시작이 t_start+240 이하.

        가짜 시계·가짜 프로세스로 최악 경로를 만든다(실제 프로세스·신호 없음). 수정 전 공식(−grace)은 244초였다.
        """
        now = [1000.0]
        clock = lambda: now[0]  # noqa: E731

        class Stuck:
            pid, returncode, stdout, stderr = -1, None, None, None

            def communicate(self, timeout=None):
                now[0] += timeout
                raise subprocess.TimeoutExpired('work', timeout)

            def wait(self, timeout=None):
                now[0] += timeout
                raise subprocess.TimeoutExpired('work', timeout)

        orig = fr._signal_group
        fr._signal_group = lambda proc, sig: None  # 가짜 pid로 실제 신호를 보내지 않게
        try:
            grace, t_start = 2.0, now[0]
            deadline = fr.work_deadline(t_start, fc.CLEANUP_START, grace)
            c = Cleanup()
            r = fr.run_then_cleanup(['work'], deadline, c, clock=clock, grace=grace, popen=lambda argv, **k: Stuck())
        finally:
            fr._signal_group = orig
        self.assertEqual((r['work']['status'], r['work']['output_incomplete']), ('KILLED_AT_DEADLINE', True))
        self.assertLessEqual(r['cleanup_at'] - t_start, fc.CLEANUP_START)
        self.assertEqual(len(c.calls), 1)

    def test_work_deadline_rejects_negative_grace(self):
        with self.assertRaises(ValueError):
            fr.work_deadline(0, fc.CLEANUP_START, -1)


if __name__ == '__main__':
    unittest.main()
