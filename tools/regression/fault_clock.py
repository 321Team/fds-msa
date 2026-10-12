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
import math
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
    """0 이상 유한한 숫자만 받는다. bool·NaN·Infinity는 거부한다(PR32 리뷰 B1)."""
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
        raise ClockError(f'{name}: 0 이상 유한한 숫자여야 함({value!r})')
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


# 주입 정의(#50 B2 초안 6051891259, rev2·rev3 유지): set 1개 `rosa_src`(ipv4_addr, interval), chain 1개 `fwd`,
# 규칙 1개(comment "fds_fault RUN=<RUN>"). 이 모양과 다르면 자동 삭제하지 않는다.
FAULT_SET = 'rosa_src'
FAULT_CHAIN = 'fwd'
FAULT_DADDR = '10.1.93.55'
FAULT_DPORT = 5432


def may_delete_fault_table(live_listing, run_id, expected_elements):
    """정리 전 소유 확인. live 원문이 이 회차가 넣은 정의와 같을 때만 삭제한다(PR32 리뷰 B3).

    live_listing: `nft -y list table inet fds_fault` 원문(조회 실패면 None). 우선순위는 숫자(`-10`)와 nft 기본
    출력의 기호 표기(`filter - 10`)를 같은 값으로 본다(PR32 3차 리뷰 R3). 빈 원문을 부재로 쓰려면
    호출자가 rc로 "정상 조회 + 테이블 없음"을 먼저 확인해야 한다(조회 실패를 부재로 바꾸지 않음).
    확인하는 것: 테이블이 정확히 `inet fds_fault` 1개, set 이름이 정확히 `rosa_src` 1개,
    chain이 정확히 `fwd` 1개, 모든 규칙 comment가 정확히 `fds_fault RUN=<run_id>`(접미사·추가 문자 불가),
    그 set 원소 집합이 기록과 같음, chain 본문이 정해진 헤더 + 규칙 1개(목적지 10.1.93.55, 포트 5432)뿐임,
    set·chain을 뺀 나머지가 테이블 외곽뿐임(counter·map 등 다른 객체 불가).
    예상 밖 구조·미인식 출력 형식은 삭제하지 않고 사람에게 넘긴다.
    """
    if live_listing is None:
        return {'delete': False, 'reason': 'QUERY_FAILED'}
    text = live_listing.strip()
    if not text:
        return {'delete': False, 'reason': 'ABSENT'}
    if not run_id or not re.fullmatch(r'[0-9A-Za-z]+', run_id):
        raise ClockError(f'run_id: {run_id!r}')
    if not re.match(r'table\s+inet\s+fds_fault\s*\{', text) or len(re.findall(r'\btable\s+\w+\s+\w+', text)) != 1:
        return {'delete': False, 'reason': 'UNEXPECTED_LISTING'}
    comments = re.findall(r'\bcomment\s+"([^"]*)"', text)
    if not comments or any(c != f'fds_fault RUN={run_id}' for c in comments):
        return {'delete': False, 'reason': f'RUN_MISMATCH {sorted(set(comments))}'}
    if re.findall(r'\bset\s+(\S+)\s*\{', text) != [FAULT_SET]:
        return {'delete': False, 'reason': 'UNEXPECTED_SETS'}
    if re.findall(r'\bchain\s+(\S+)\s*\{', text) != [FAULT_CHAIN]:
        return {'delete': False, 'reason': 'UNEXPECTED_CHAINS'}
    m = re.search(r'\bset\s+' + FAULT_SET + r'\s*\{\s*type\s+ipv4_addr\s*;?\s*(?:flags\s+interval\s*;?\s*)?'
                  r'elements\s*=\s*\{([^{}]*)\}\s*;?\s*\}', text)
    if m is None:
        return {'delete': False, 'reason': 'UNEXPECTED_SET_FORMAT'}
    live = {e.strip() for e in m.group(1).split(',') if e.strip()}
    if live != set(expected_elements):
        return {'delete': False, 'reason': f'ELEMENTS_MISMATCH {sorted(live)}'}
    # chain 본문은 정해진 헤더와 규칙 정확히 1개뿐이어야 한다. 주석 없는 추가 규칙·같은 주석의 두 번째 규칙·
    # 목적지/포트가 바뀐 규칙은 이 회차 정의가 아니므로 삭제하지 않는다(PR32 재리뷰 B3-R1).
    chain = re.search(r'\bchain\s+' + FAULT_CHAIN + r'\s*\{([^{}]*)\}', text)
    rule = (r'\s*type\s+filter\s+hook\s+forward\s+priority\s+(?:-10|filter\s*-\s*10)\s*;\s*policy\s+accept\s*;\s*'
            r'ip\s+saddr\s+@' + FAULT_SET + r'\s+ip\s+daddr\s+' + re.escape(FAULT_DADDR) +
            r'\s+tcp\s+dport\s+' + str(FAULT_DPORT) + r'\s+'
            r'counter\s+packets\s+[0-9]+\s+bytes\s+[0-9]+\s+reject\s+with\s+tcp\s+reset\s+'
            r'comment\s+"' + re.escape(f'fds_fault RUN={run_id}') + r'"\s*')
    if len(comments) != 1 or chain is None or not re.fullmatch(rule, chain.group(1)):
        return {'delete': False, 'reason': 'UNEXPECTED_RULES'}
    # 확인한 set·chain 두 구간을 빼면 테이블 외곽만 남아야 한다. counter·map·flowtable 같은 다른 객체가 있으면
    # 테이블째 지울 때 회차 정의 밖의 객체까지 지우게 되므로 삭제하지 않는다(PR32 3차 리뷰 R4).
    cursor, pieces = 0, []
    for start, end in sorted((m.span(), chain.span())):
        if start < cursor:
            return {'delete': False, 'reason': 'UNEXPECTED_LISTING'}
        pieces.append(text[cursor:start])
        cursor = end
    pieces.append(text[cursor:])
    if not re.fullmatch(r'table\s+inet\s+fds_fault\s*\{\s*\}', ''.join(pieces)):
        return {'delete': False, 'reason': 'UNEXPECTED_TABLE_CONTENT'}
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


def _duration(seconds):
    """남은 시간을 넘지 않는 duration 문자열(올림·최소값 상향 없음, 지수 표기 없음)."""
    _num(seconds, 'timeout')
    if seconds <= 0:
        raise ClockError('timeout: 0보다 커야 함')
    micros = math.floor(seconds * 1_000_000)  # 마이크로초 아래는 버림(올리지 않음)
    t = format(micros / 1_000_000, '.6f').rstrip('0').rstrip('.')
    if micros <= 0 or not t or float(t) <= 0 or float(t) > seconds:
        raise ClockError(f'timeout: 표현 불가({seconds!r})')
    return t + 's'


def oc_change(approved, verb, *args, timeout, allow_restart=False):
    """승인 Deployment에 결속된 변경·원복 명령만 만든다(실행하지 않음, PR32 리뷰 B1·B2).

    대상은 승인값 `deployment/<approved['deployment']>`에서만 만들고, 허용한 동작 인자 외에는 거부한다.
    전역 옵션(--context·--namespace 등)을 추가로 받지 않는다. timeout은 남은 시간을 넘지 않게 그대로 쓴다.
    rollout restart는 실행 카드의 별도 승인이 있을 때만(allow_restart=True) 만든다.
    live 7개 식별자 확인(target_mismatch)은 실제 호출 직전에 따로 해야 하며 이 함수가 대신하지 않는다.
    """
    if any(not (approved or {}).get(k) for k in TARGET_KEYS):
        raise ClockError('승인 대상 누락')
    t = _duration(timeout)
    target = 'deployment/' + approved['deployment']
    if verb == 'scale':
        if len(args) != 2 or args[0] != target or not re.fullmatch(r'--replicas=[0-9]+', args[1]):
            raise ClockError('scale: 승인 Deployment와 --replicas=N만 허용')
        tail = [target, args[1]]
    elif verb == 'rollout':
        if len(args) != 2 or args[1] != target or args[0] not in ('status', 'restart'):
            raise ClockError('rollout: status|restart 와 승인 Deployment만 허용')
        if args[0] == 'restart' and not allow_restart:
            raise ClockError('rollout restart: 별도 승인 없음')
        tail = [args[0], target] + (['--timeout=' + t] if args[0] == 'status' else [])
    elif verb == 'get':
        if args != (target,):
            raise ClockError('get: 승인 Deployment만 허용')
        tail = [target]
    else:
        raise ClockError(f'verb: {verb!r}')
    return ['oc', '--context', approved['context'], '--request-timeout=' + t, '-n', approved['namespace'], verb, *tail]
