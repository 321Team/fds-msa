"""P2-E2E-01(#50) 장애 사례 실행 호출부의 절대 기한 강제.

fault_clock.can_start_whole은 작업을 *시작해도 되는지*만 본다. 이미 시작한 긴 작업(B3E 사례군·POST 묶음)이
예상보다 오래 걸려도 정리(원복) 시작 시각을 넘기지 않도록, 여기서 하위 프로세스를 절대 기한에 끊고
결과를 INCONCLUSIVE로 남긴 뒤 **반드시** 정리 함수를 부른다(#50 rev3 리뷰 6119176866 잔여 2·3).

이 모듈은 클라우드 명령을 정의하지 않는다. 무엇을 실행하고 어떻게 원복할지는 호출자(실행 카드)가 넘긴다.
시각은 단조 시계(time.monotonic) 기준이다. 표준 라이브러리만 쓴다.
"""
import subprocess
import time


def work_deadline(t_start, cleanup_start, grace):
    """장애 단계 작업의 절대 기한. 끊은 뒤 종료 대기(grace)까지 포함해 정리 시작이 t_start+cleanup_start를 넘지 않게 한다."""
    if grace < 0:
        raise ValueError('grace: 0 이상')
    return t_start + cleanup_start - grace


def run_until(argv, deadline, *, clock=time.monotonic, grace=2.0, popen=subprocess.Popen):
    """argv를 실행하되 deadline(단조 시계 초)에 끊는다.

    반환 status:
    - NOT_STARTED: 이미 기한이 지나 시작하지 않음(popen 호출 없음)
    - DONE: 기한 안에 끝남(rc는 프로세스 종료 코드)
    - KILLED_AT_DEADLINE: 기한에 terminate, grace 안에 안 끝나면 kill
    """
    now = clock()
    if now >= deadline:
        return {'status': 'NOT_STARTED', 'rc': None, 'stdout': b'', 'stderr': b''}
    proc = popen(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        out, err = proc.communicate(timeout=max(0.0, deadline - clock()))
        return {'status': 'DONE', 'rc': proc.returncode, 'stdout': out, 'stderr': err}
    except subprocess.TimeoutExpired:
        proc.terminate()
        try:
            out, err = proc.communicate(timeout=grace)
        except subprocess.TimeoutExpired:
            proc.kill()
            out, err = proc.communicate()
        return {'status': 'KILLED_AT_DEADLINE', 'rc': proc.returncode, 'stdout': out, 'stderr': err}


def run_then_cleanup(work_argv, deadline, cleanup, *, clock=time.monotonic, grace=2.0, popen=subprocess.Popen):
    """작업을 deadline에서 끊고, 작업 결과와 상관없이 cleanup()을 반드시 한 번 부른다.

    작업이 rc0으로 기한 안에 끝난 경우만 WORK_DONE이다. 끊김·미시작·시작 실패·비0 종료는 INCONCLUSIVE다.
    cleanup()이 예외를 내면 그대로 올린다(호출자가 원복 실패로 보고·재시도·인계해야 하므로 숨기지 않음).
    """
    try:
        work = run_until(work_argv, deadline, clock=clock, grace=grace, popen=popen)
    except Exception as exc:  # 실행 자체가 실패해도 정리로 넘긴다
        work = {'status': 'START_FAILED', 'rc': None, 'error': type(exc).__name__}
    cleanup_at = clock()
    cleanup_result = cleanup()
    result = 'WORK_DONE' if work['status'] == 'DONE' and work['rc'] == 0 else 'INCONCLUSIVE'
    return {'result': result, 'work': work, 'cleanup_at': cleanup_at, 'cleanup': cleanup_result}
