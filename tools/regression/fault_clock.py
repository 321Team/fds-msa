"""P2-E2E-01(#50) 장애 사례 F-D·F-E의 시간 상한·대상 결속 판정(순수 함수).

#50 B2 rev3 실행 카드가 쓰는 판정만 담는다. 네트워크·oc·nft·시계를 직접 호출하지 않고,
호출자가 넘긴 시각(단조 시계 초)과 관측 결과만 보고 다음 행동과 허용 timeout을 돌려준다.
표준 라이브러리만 쓴다(Python 3.6 이상).

시간 기준(infra 리뷰 #50 F1-R1):
- t_start: 최초 변경 요청(nft 적재·oc scale)을 보내기 **직전** 시각. 모든 상한은 여기서 잰다.
  적재 확인(readback·scale 확인)에 실패해도 t_start는 이미 있으므로 상한 계산이 끊기지 않는다.
- CAP(300초): 장애가 걸려 있는 상한. 원복 확인까지 CAP 안에 끝나도록
  정리 시작 시각을 t_start + CAP - MARGIN으로 역산한다.
- TOTAL(900초): 회복 확인·POST까지 포함한 전체 상한. 넘으면 새 시험을 시작하지 않는다.
  남은 장애 정리는 상한을 넘어도 계속 시도하고 위반으로 기록한다(정리를 포기하지 않음).
"""
import re

CAP = 300
MARGIN = 60
TOTAL = 900
HOLD_TARGET = 60
MIN_HOLD = 30
MIN_TIMEOUT = 1
CLEANUP_START = CAP - MARGIN  # 240

# 단계별 기한: 'fault'는 장애 유지 중 작업(관측·B3E), 'cleanup'은 원복·원복 확인, 'recovery'는 회복 관측·POST.
PHASE_DEADLINE = {'fault': CLEANUP_START, 'cleanup': CAP, 'recovery': TOTAL}


class ClockError(ValueError):
    pass


def _num(value, name):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value != value or value < 0:
        raise ClockError(f'{name}: 0 이상 숫자여야 함({value!r})')
    return value


def observe_limit(period, timeout, failure_threshold, slack=20):
    """readiness probe로 4항목이 보일 때까지의 관측 한도 O = F×P + T + slack.

    시간표 계산 입력일 뿐, kubelet 실제 지연까지 포함한 Ready 전환 보증이 아니다.
    """
    for v, n in ((period, 'period'), (timeout, 'timeout'), (failure_threshold, 'failure_threshold')):
        _num(v, n)
        if v <= 0:
            raise ClockError(f'{n}: 0보다 커야 함')
    return failure_threshold * period + timeout + slack


def feasible(o_limit):
    """주입 전 판정: 관측 한도 + 최소 유지 + 정리 여유가 CAP 안에 들어가야 주입한다."""
    _num(o_limit, 'o_limit')
    need = o_limit + MIN_HOLD + MARGIN
    return {'inject': need <= CAP, 'need': need, 'cap': CAP}


def budget(now, t_start, phase, want):
    """명령 하나를 시작해도 되는지와 그 명령에 줄 timeout.

    반환: {'run': bool, 'timeout': 초, 'reason': str, 'cap_violation': bool}
    - fault 단계는 정리 시작(t_start+240) 전에만, 남은 시간 이하 timeout으로 실행한다.
    - cleanup 단계는 CAP 전이면 남은 시간으로 제한한다. CAP을 넘었어도 정리는 실행하되
      cap_violation=True로 기록하고 timeout은 요청값을 그대로 쓴다.
    - recovery 단계는 TOTAL 전에만 시작한다.
    """
    _num(now, 'now')
    _num(t_start, 't_start')
    _num(want, 'want')
    if phase not in PHASE_DEADLINE:
        raise ClockError(f'phase: {phase!r}')
    if now < t_start:
        raise ClockError('now < t_start (시계 역행)')
    elapsed = now - t_start
    left = PHASE_DEADLINE[phase] - elapsed
    if phase == 'cleanup':
        if left <= 0:
            return {'run': True, 'timeout': want, 'reason': 'CAP_EXCEEDED_CLEANUP_CONTINUES', 'cap_violation': True}
        return {'run': True, 'timeout': min(want, left), 'reason': 'OK', 'cap_violation': False}
    if left < MIN_TIMEOUT:
        reason = 'CLEANUP_DUE' if phase == 'fault' else 'TOTAL_EXCEEDED_NO_NEW_WORK'
        return {'run': False, 'timeout': 0, 'reason': reason, 'cap_violation': False}
    return {'run': True, 'timeout': min(want, left), 'reason': 'OK', 'cap_violation': False}


def can_start_whole(now, t_start, phase, need):
    """중간에 끊으면 의미가 없는 작업(B3E 사례군·POST 묶음)은 필요한 시간 전체가 남았을 때만 시작한다.

    p2e2e.py의 요청당 timeout은 사례군 전체 한도가 아니므로, 시작 전에 이 판정으로 묶는다.
    """
    _num(need, 'need')
    b = budget(now, t_start, phase, need)
    if b['run'] and phase != 'cleanup' and b['timeout'] < need:
        return {'run': False, 'timeout': 0, 'reason': 'NOT_ENOUGH_TIME', 'cap_violation': False}
    return b


def hold_until(t_start, t_obs):
    """4항목이 모두 보인 시각 t_obs가 있으면 삭제 시각 = min(t_obs + 60, t_start + 240)."""
    _num(t_start, 't_start')
    if t_obs is None:
        return t_start + CLEANUP_START
    _num(t_obs, 't_obs')
    return min(t_obs + HOLD_TARGET, t_start + CLEANUP_START)


def fault_step(now, t_start, *, applied_confirmed, all_four_since, any_lost, o_limit):
    """F-D 장애 유지 중 다음 행동. 반환: {'action': ..., 'result': ...}.

    applied_confirmed: 적재 readback 성공 여부(False면 적재 성공 여부를 모르는 상태 → 즉시 정리).
    all_four_since: 4항목이 처음 모두 보인 시각(없으면 None).
    any_lost: 4항목을 모두 본 뒤 하나라도 풀렸는지.
    """
    _num(now, 'now')
    _num(t_start, 't_start')
    _num(o_limit, 'o_limit')
    elapsed = now - t_start
    if elapsed < 0:
        raise ClockError('now < t_start (시계 역행)')
    if not applied_confirmed:
        return {'action': 'CLEANUP', 'result': 'APPLY_UNCONFIRMED'}
    if elapsed >= CLEANUP_START:
        return {'action': 'CLEANUP', 'result': 'CLEANUP_DEADLINE'}
    if all_four_since is None:
        if elapsed >= o_limit:
            return {'action': 'CLEANUP', 'result': 'INCONCLUSIVE'}
        return {'action': 'OBSERVE', 'result': None}
    if any_lost:
        return {'action': 'CLEANUP', 'result': 'UNSTABLE'}
    if now >= hold_until(t_start, all_four_since):
        return {'action': 'CLEANUP', 'result': 'OBSERVED'}
    return {'action': 'HOLD', 'result': None}


def may_delete_fault_table(live_listing, run_id, expected_elements):
    """정리 전 소유 확인. live 원문의 규칙 comment RUN과 set 원소가 이 회차 기록과 같을 때만 삭제한다.

    live_listing: `nft list table inet fds_fault` 원문(조회 실패면 None).
    조회 실패·다른 RUN·원소 불일치는 삭제하지 않는다(사람 인수). 테이블 부재는 'ABSENT'.
    """
    if live_listing is None:
        return {'delete': False, 'reason': 'QUERY_FAILED'}
    text = live_listing.strip()
    if not text:
        return {'delete': False, 'reason': 'ABSENT'}
    if 'table inet fds_fault' not in text:
        return {'delete': False, 'reason': 'UNEXPECTED_LISTING'}
    runs = set(re.findall(r'fds_fault RUN=(\w+)', text))
    if runs != {run_id}:
        return {'delete': False, 'reason': f'RUN_MISMATCH {sorted(runs)}'}
    m = re.search(r'elements\s*=\s*\{([^}]*)\}', text)
    live = {e.strip() for e in m.group(1).split(',') if e.strip()} if m else set()
    if live != set(expected_elements):
        return {'delete': False, 'reason': f'ELEMENTS_MISMATCH {sorted(live)}'}
    return {'delete': True, 'reason': 'OWNED'}


TARGET_KEYS = ('context', 'server', 'cluster_id', 'namespace', 'namespace_uid', 'deployment', 'deployment_uid')


def target_mismatch(approved, live):
    """F2-R1: 실행 카드의 승인 대상과 live 식별자가 모두 같아야 변경한다. 다르면 변경 0으로 STOP."""
    out = []
    for k in TARGET_KEYS:
        a, b = (approved or {}).get(k), (live or {}).get(k)
        if not a or a != b:
            out.append(k)
    return out


def oc_change(approved, verb, *args, timeout):
    """변경·원복 명령을 항상 같은 --context·-n·--request-timeout으로 만든다(실행하지 않음)."""
    _num(timeout, 'timeout')
    if verb not in ('scale', 'rollout', 'get'):
        raise ClockError(f'verb: {verb!r}')
    missing = [k for k in ('context', 'namespace') if not (approved or {}).get(k)]
    if missing:
        raise ClockError(f'승인 대상 누락: {missing}')
    t = max(MIN_TIMEOUT, int(timeout))
    return ['oc', '--context', approved['context'], f'--request-timeout={t}s', '-n', approved['namespace'], verb, *args]
