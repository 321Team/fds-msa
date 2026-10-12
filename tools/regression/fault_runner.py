"""P2-E2E-01(#50) 장애 사례 실행 호출부의 절대 기한 강제.

fault_clock.can_start_whole은 작업을 *시작해도 되는지*만 본다. 이미 시작한 긴 작업(B3E 사례군·POST 묶음)이
예상보다 오래 걸려도 정리(원복) 시작 시각을 넘기지 않도록, 여기서 하위 프로세스를 절대 기한에 끊고
결과를 INCONCLUSIVE로 남긴 뒤 **반드시** 정리 함수를 부른다(#50 rev3 리뷰 6119176866 잔여 2·3).

- 운영자 취소(Ctrl-C=KeyboardInterrupt)·SystemExit 같은 BaseException에서도 하위 작업을 끝내고 정리를 한 번
  부른 뒤, 취소를 성공으로 바꾸지 않고 그대로 다시 올린다(PR32 재리뷰 F1-R2).
- 하위 작업은 POSIX에서 새 세션(프로세스 그룹)으로 띄워, 기한·취소 때 그 그룹 전체를 끝낸다. 출력 회수에도
  grace 시간 제한을 둔다. 후손이 파이프를 물고 있어도 정리 시작이 무한히 밀리지 않게 하기 위해서다(비차단 권고).
- SIGKILL·호스트 소실처럼 이 프로세스 자체가 사라지는 경우까지 정리를 보장하지는 않는다.

이 모듈은 클라우드 명령을 정의하지 않는다. 무엇을 실행하고 어떻게 원복할지는 호출자(실행 카드)가 넘긴다.
시각은 단조 시계(time.monotonic) 기준이다. 표준 라이브러리만 쓴다.
"""
import os
import signal
import subprocess
import time

_POSIX = os.name == 'posix'


def work_deadline(t_start, cleanup_start, grace):
    """장애 단계 작업의 절대 기한. 끊은 뒤 종료 대기(grace)까지 포함해 정리 시작이 t_start+cleanup_start를 넘지 않게 한다.

    끊기·출력 회수는 각각 최대 grace씩 걸릴 수 있으므로 호출자는 2×grace 여유를 두려면 grace를 그만큼 잡는다.
    """
    if grace < 0:
        raise ValueError('grace: 0 이상')
    return t_start + cleanup_start - grace


def _signal_group(proc, sig):
    """새 세션으로 띄운 작업이면 그룹 전체에, 아니면 그 프로세스에만 신호를 보낸다. 이미 끝났으면 무시."""
    try:
        if _POSIX:
            os.killpg(proc.pid, sig)
        elif sig == getattr(signal, 'SIGKILL', None):
            proc.kill()
        else:
            proc.terminate()
    except (ProcessLookupError, PermissionError, OSError):
        pass


def _stop(proc, grace):
    """terminate → grace 대기 → kill → grace 안에서 출력 회수. 회수가 끝나지 않으면 파이프를 닫고 표시만 남긴다."""
    _signal_group(proc, signal.SIGTERM)
    try:
        out, err = proc.communicate(timeout=grace)
        return out, err, False
    except subprocess.TimeoutExpired:
        pass
    _signal_group(proc, getattr(signal, 'SIGKILL', signal.SIGTERM))
    try:
        out, err = proc.communicate(timeout=grace)
        return out, err, False
    except subprocess.TimeoutExpired:
        for stream in (proc.stdout, proc.stderr):
            try:
                if stream is not None:
                    stream.close()
            except OSError:
                pass
        try:
            proc.wait(timeout=grace)
        except subprocess.TimeoutExpired:
            pass
        return b'', b'', True


def run_until(argv, deadline, *, clock=time.monotonic, grace=2.0, popen=subprocess.Popen):
    """argv를 실행하되 deadline(단조 시계 초)에 끊는다.

    반환 status:
    - NOT_STARTED: 이미 기한이 지나 시작하지 않음(popen 호출 없음)
    - DONE: 기한 안에 끝남(rc는 프로세스 종료 코드)
    - KILLED_AT_DEADLINE: 기한에 그룹 terminate, grace 안에 안 끝나면 kill. output_incomplete=True면
      출력 회수를 grace 안에 끝내지 못해 파이프를 닫았다는 뜻
    BaseException(취소)이 나면 작업 그룹을 끝낸 뒤 그 예외를 그대로 올린다.
    """
    now = clock()
    if now >= deadline:
        return {'status': 'NOT_STARTED', 'rc': None, 'stdout': b'', 'stderr': b''}
    kwargs = {'stdout': subprocess.PIPE, 'stderr': subprocess.PIPE}
    if _POSIX:
        kwargs['start_new_session'] = True
    proc = popen(argv, **kwargs)
    try:
        out, err = proc.communicate(timeout=max(0.0, deadline - clock()))
        return {'status': 'DONE', 'rc': proc.returncode, 'stdout': out, 'stderr': err}
    except subprocess.TimeoutExpired:
        out, err, incomplete = _stop(proc, grace)
        return {'status': 'KILLED_AT_DEADLINE', 'rc': proc.returncode, 'stdout': out, 'stderr': err,
                'output_incomplete': incomplete}
    except BaseException:
        _stop(proc, grace)
        raise


def run_then_cleanup(work_argv, deadline, cleanup, *, clock=time.monotonic, grace=2.0, popen=subprocess.Popen):
    """작업을 deadline에서 끊고, 작업 결과·취소와 상관없이 cleanup()을 반드시 한 번 부른다.

    작업이 rc0으로 기한 안에 끝난 경우만 WORK_DONE이다. 끊김·미시작·시작 실패·비0 종료는 INCONCLUSIVE다.
    - 취소(BaseException): 작업 그룹을 끝내고 cleanup()을 부른 뒤 같은 취소 예외를 다시 올린다.
    - cleanup()이 예외를 내면 그대로 올린다. 취소 중이었다면 원래 취소를 __cause__로 남긴다.
    """
    cancelled = None
    try:
        work = run_until(work_argv, deadline, clock=clock, grace=grace, popen=popen)
    except Exception as exc:  # 실행 자체가 실패해도 정리로 넘긴다
        work = {'status': 'START_FAILED', 'rc': None, 'error': type(exc).__name__}
    except BaseException as exc:  # 운영자 취소 등: 정리 뒤 다시 올린다
        cancelled = exc
        work = {'status': 'CANCELLED', 'rc': None, 'error': type(exc).__name__}
    cleanup_at = clock()
    try:
        cleanup_result = cleanup()
    except Exception as cexc:
        if cancelled is not None:
            raise cexc from cancelled
        raise
    if cancelled is not None:
        raise cancelled
    result = 'WORK_DONE' if work['status'] == 'DONE' and work['rc'] == 0 else 'INCONCLUSIVE'
    return {'result': result, 'work': work, 'cleanup_at': cleanup_at, 'cleanup': cleanup_result}
