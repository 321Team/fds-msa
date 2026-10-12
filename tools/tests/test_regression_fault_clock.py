"""#50 F1-R1·F2-R1 모의 검증: 시간 상한·정리 시작·대상 결속(순수 함수, 서버·oc·nft 없음)."""
import unittest

from tools.regression import fault_clock as fc

T0 = 1000.0  # t_start(최초 변경 요청 직전)
RUN = '202610211300'
ELEMS = ['10.20.10.11', '10.20.10.12']
# 실제 주입 정의(#50 B2 초안 6051891259, rev2·rev3 유지)를 `nft list table`로 다시 읽은 모양.
LISTING = '''table inet fds_fault {
\tset rosa_src {
\t\ttype ipv4_addr
\t\tflags interval
\t\telements = { 10.20.10.11, 10.20.10.12 }
\t}

\tchain fwd {
\t\ttype filter hook forward priority -10; policy accept;
\t\tip saddr @rosa_src ip daddr 10.1.93.55 tcp dport 5432 counter packets 7 bytes 420 reject with tcp reset comment "fds_fault RUN=202610211300"
\t}
}'''
APPROVED = dict(context='rosa-admin/fds', server='https://api.fds.example:443', cluster_id='c-1',
                namespace='fds-app', namespace_uid='ns-uid', deployment='fds-engine', deployment_uid='dep-uid')


class TimeBasisTests(unittest.TestCase):
    def test_observe_limit_and_feasibility(self):
        o = fc.observe_limit(10, 1, 3)
        self.assertEqual(o, 51)
        self.assertEqual(fc.feasible(o), {'inject': True, 'need': 141, 'cap': 300})
        self.assertTrue(fc.feasible(210)['inject'])        # 210+30+60 = 300
        self.assertFalse(fc.feasible(211)['inject'])       # 301 > 300 → 주입 전 STOP
        for bad in (0, -1, True, float('nan')):
            with self.assertRaises(fc.ClockError):
                fc.observe_limit(bad, 1, 3)

    def test_cleanup_start_is_reverse_calculated_from_t_start(self):
        self.assertEqual(fc.CLEANUP_START, 240)
        self.assertEqual(fc.hold_until(T0, T0 + 51), T0 + 111)
        self.assertEqual(fc.hold_until(T0, T0 + 200), T0 + 240, '유지 목표보다 정리 시작이 우선')
        self.assertEqual(fc.hold_until(T0, None), T0 + 240)

    def test_clock_regression_and_bad_input_raise(self):
        with self.assertRaises(fc.ClockError):
            fc.budget(T0 - 1, T0, 'fault', 10)
        with self.assertRaises(fc.ClockError):
            fc.budget(T0, T0, 'unknown', 10)
        with self.assertRaises(fc.ClockError):
            fc.fault_step(T0 - 1, T0, applied_confirmed=True, all_four_since=None, any_lost=False, o_limit=51)


class ApplyUnconfirmedTests(unittest.TestCase):
    """리뷰 재검증 1: 적재 성공 + readback 실패 → t_start 기준으로 즉시 정리, 소유 확인 뒤에만 삭제."""

    def test_unconfirmed_apply_goes_straight_to_cleanup(self):
        step = fc.fault_step(T0 + 3, T0, applied_confirmed=False, all_four_since=None, any_lost=False, o_limit=51)
        self.assertEqual(step, {'action': 'CLEANUP', 'result': 'APPLY_UNCONFIRMED'})
        b = fc.budget(T0 + 3, T0, 'cleanup', 10)
        self.assertEqual((b['run'], b['timeout'], b['cap_violation']), (True, 10, False))

    def test_owned_table_is_deleted_others_are_not(self):
        self.assertEqual(fc.may_delete_fault_table(LISTING, RUN, ELEMS), {'delete': True, 'reason': 'OWNED'})
        self.assertEqual(fc.may_delete_fault_table(None, RUN, ELEMS)['reason'], 'QUERY_FAILED')
        self.assertEqual(fc.may_delete_fault_table('', RUN, ELEMS)['reason'], 'ABSENT')
        other = LISTING.replace('RUN=202610211300', 'RUN=202610211200')
        self.assertFalse(fc.may_delete_fault_table(other, RUN, ELEMS)['delete'], '다른 RUN의 같은 이름 테이블')
        extra = LISTING.replace('10.20.10.12 }', '10.20.10.12, 10.20.10.99 }')
        self.assertFalse(fc.may_delete_fault_table(extra, RUN, ELEMS)['delete'], 'set 원소 불일치')
        self.assertEqual(fc.may_delete_fault_table('table inet other {}', RUN, ELEMS)['reason'], 'UNEXPECTED_LISTING')

    def test_review_b3_counterexamples_are_not_owned(self):
        """PR32 리뷰 B3 반례: RUN 접미사, 첫 set만 맞고 실제 src set이 다른 경우, 구조가 다른 경우."""
        suffix = LISTING.replace('RUN=202610211300"', 'RUN=202610211300-other"')
        self.assertEqual(fc.may_delete_fault_table(suffix, RUN, ELEMS)['delete'], False, 'RUN 접미사')
        decoy = LISTING.replace('\tset rosa_src {', '\tset decoy {\n\t\ttype ipv4_addr\n\t\telements = { 10.20.10.11, 10.20.10.12 }\n\t}\n\tset rosa_src {') \
                       .replace('elements = { 10.20.10.11, 10.20.10.12 }\n\t}\n\n', 'elements = { 10.20.10.99 }\n\t}\n\n')
        self.assertFalse(fc.may_delete_fault_table(decoy, RUN, ELEMS)['delete'], '다른 첫 set(원소 일치) + 실제 src set 불일치')
        two_rules = LISTING.replace('comment "fds_fault RUN=202610211300"',
                                    'comment "fds_fault RUN=202610211300"\n\t\tcounter accept comment "other"')
        self.assertEqual(fc.may_delete_fault_table(two_rules, RUN, ELEMS)['reason'], "RUN_MISMATCH ['fds_fault RUN=202610211300', 'other']")
        extra_chain = LISTING.replace('\tchain fwd {', '\tchain x {\n\t}\n\tchain fwd {')
        self.assertEqual(fc.may_delete_fault_table(extra_chain, RUN, ELEMS)['reason'], 'UNEXPECTED_CHAINS')
        two_tables = LISTING + '\ntable inet fds_fault2 {\n}'
        self.assertEqual(fc.may_delete_fault_table(two_tables, RUN, ELEMS)['reason'], 'UNEXPECTED_LISTING')
        no_comment = LISTING.replace(' comment "fds_fault RUN=202610211300"', '')
        self.assertFalse(fc.may_delete_fault_table(no_comment, RUN, ELEMS)['delete'], 'comment 없음')
        with self.assertRaises(fc.ClockError):
            fc.may_delete_fault_table(LISTING, 'RUN with space', ELEMS)

    def test_review_b3r1_extra_or_changed_rules_are_not_owned(self):
        """PR32 재리뷰 B3-R1: chain 안 추가 규칙(무주석·같은 주석)과 목적지/포트가 바뀐 규칙은 삭제하지 않는다."""
        rule_end = 'comment "fds_fault RUN=202610211300"'
        plain = LISTING.replace(rule_end, rule_end + '\n\t\tcounter accept')
        self.assertEqual(fc.may_delete_fault_table(plain, RUN, ELEMS), {'delete': False, 'reason': 'UNEXPECTED_RULES'},
                         '주석 없는 추가 규칙')
        dup = LISTING.replace(rule_end, rule_end + '\n\t\tip saddr @rosa_src counter accept ' + rule_end)
        self.assertEqual(fc.may_delete_fault_table(dup, RUN, ELEMS)['reason'], 'UNEXPECTED_RULES', '같은 주석의 두 번째 규칙')
        self.assertEqual(fc.may_delete_fault_table(LISTING.replace('daddr 10.1.93.55', 'daddr 10.1.93.54'), RUN, ELEMS)['reason'],
                         'UNEXPECTED_RULES', '목적지 변경')
        self.assertEqual(fc.may_delete_fault_table(LISTING.replace('dport 5432', 'dport 22'), RUN, ELEMS)['reason'],
                         'UNEXPECTED_RULES', '포트 변경')
        self.assertEqual(fc.may_delete_fault_table(LISTING.replace('reject with tcp reset', 'drop'), RUN, ELEMS)['reason'],
                         'UNEXPECTED_RULES', '동작 변경')
        self.assertEqual(fc.may_delete_fault_table(LISTING, RUN, ELEMS), {'delete': True, 'reason': 'OWNED'}, '정상 원문은 계속 허용')


class FaultTimelineTests(unittest.TestCase):
    def step(self, elapsed, since=None, lost=False, o=51):
        return fc.fault_step(T0 + elapsed, T0, applied_confirmed=True, all_four_since=since, any_lost=lost, o_limit=o)

    def test_normal_observe_hold_cleanup(self):
        self.assertEqual(self.step(10)['action'], 'OBSERVE')
        self.assertEqual(self.step(60, since=T0 + 45)['action'], 'HOLD')
        self.assertEqual(self.step(105, since=T0 + 45), {'action': 'CLEANUP', 'result': 'OBSERVED'})

    def test_not_observed_by_limit_is_inconclusive(self):
        self.assertEqual(self.step(50)['action'], 'OBSERVE')
        self.assertEqual(self.step(51), {'action': 'CLEANUP', 'result': 'INCONCLUSIVE'})

    def test_lost_signal_is_unstable(self):
        self.assertEqual(self.step(70, since=T0 + 45, lost=True), {'action': 'CLEANUP', 'result': 'UNSTABLE'})

    def test_cleanup_deadline_overrides_everything(self):
        # 4항목이 늦게(230초) 보여 유지 목표(+60)가 남아 있어도 t_start+240이면 정리 시작
        self.assertEqual(self.step(239, since=T0 + 230, o=235)['action'], 'HOLD')
        self.assertEqual(self.step(240, since=T0 + 230, o=235), {'action': 'CLEANUP', 'result': 'CLEANUP_DEADLINE'})
        # 관측 한도 안이면 관측 계속
        self.assertEqual(self.step(209, o=210)['action'], 'OBSERVE')

    def test_full_walk_never_starts_cleanup_after_240(self):
        """5초 간격 관측을 끝까지 따라가도 정리 시작은 t_start+240을 넘지 않는다(4항목 미관측·관측 성공 두 경우)."""
        for since in (None, 200):
            for o in (51, 210):
                started = None
                for e in range(0, 300, 5):
                    s = self.step(e, since=None if since is None or e < since else T0 + since, o=o)
                    if s['action'] == 'CLEANUP':
                        started = e
                        break
                self.assertIsNotNone(started)
                self.assertLessEqual(started, 240, (since, o))


class LongB3ETests(unittest.TestCase):
    """리뷰 재검증 2: 긴 B3E — 장애 단계 작업은 정리 시작 전 남은 시간 이하로만, 모자라면 시작하지 않는다."""

    def test_budget_shrinks_to_cleanup_start(self):
        self.assertEqual(fc.budget(T0 + 100, T0, 'fault', 60)['timeout'], 60)
        self.assertEqual(fc.budget(T0 + 230, T0, 'fault', 60)['timeout'], 10)
        b = fc.budget(T0 + 239.5, T0, 'fault', 60)
        self.assertEqual((b['run'], b['reason']), (False, 'CLEANUP_DUE'), '1초 미만이면 시작하지 않음')
        self.assertEqual(fc.budget(T0 + 240, T0, 'fault', 60)['run'], False)

    def test_whole_b3e_starts_only_with_full_time_left(self):
        ok = fc.can_start_whole(T0 + 100, T0, 'fault', 90)
        self.assertEqual((ok['run'], ok['timeout']), (True, 90))
        short = fc.can_start_whole(T0 + 200, T0, 'fault', 90)  # 40초 남음 < 90초
        self.assertEqual((short['run'], short['reason']), (False, 'NOT_ENOUGH_TIME'))
        post = fc.can_start_whole(T0 + 850, T0, 'recovery', 60)  # 50초 남음 < 60초
        self.assertEqual((post['run'], post['reason']), (False, 'NOT_ENOUGH_TIME'))
        self.assertEqual(fc.can_start_whole(T0 + 901, T0, 'recovery', 60)['reason'], 'TOTAL_EXCEEDED_NO_NEW_WORK')


class RestoreRetryTests(unittest.TestCase):
    """리뷰 재검증 3: 원복 명령 실패·재시도 — CAP 안이면 남은 시간으로, 넘으면 위반 기록하며 정리는 계속."""

    def test_retry_timeouts_and_cap_violation(self):
        first = fc.budget(T0 + 240, T0, 'cleanup', 10)
        self.assertEqual((first['run'], first['timeout']), (True, 10))
        retry = fc.budget(T0 + 295, T0, 'cleanup', 10)
        self.assertEqual((retry['run'], retry['timeout'], retry['cap_violation']), (True, 5, False))
        late = fc.budget(T0 + 305, T0, 'cleanup', 10)
        self.assertEqual((late['run'], late['cap_violation'], late['reason']),
                         (True, True, 'CAP_EXCEEDED_CLEANUP_CONTINUES'), '상한을 넘어도 정리는 포기하지 않음')


class BoundaryTests(unittest.TestCase):
    """리뷰 재검증 4: 300초·900초 경계."""

    def test_cap_boundary(self):
        self.assertFalse(fc.budget(T0 + 299, T0, 'cleanup', 10)['cap_violation'])
        self.assertEqual(fc.budget(T0 + 299, T0, 'cleanup', 10)['timeout'], 1)
        self.assertTrue(fc.budget(T0 + 300, T0, 'cleanup', 10)['cap_violation'])

    def test_total_boundary_stops_new_work(self):
        b = fc.budget(T0 + 899, T0, 'recovery', 600)
        self.assertEqual((b['run'], b['timeout']), (True, 1))
        b = fc.budget(T0 + 900, T0, 'recovery', 600)
        self.assertEqual((b['run'], b['reason']), (False, 'TOTAL_EXCEEDED_NO_NEW_WORK'))
        # rollout 600초를 그대로 줄 수 없는 시점이면 남은 시간으로 줄인다(F-E: 원복 뒤 rollout+POST 직렬)
        self.assertEqual(fc.budget(T0 + 300, T0, 'recovery', 600)['timeout'], 600)
        self.assertEqual(fc.budget(T0 + 500, T0, 'recovery', 600)['timeout'], 400)


class TargetBindingTests(unittest.TestCase):
    """F2-R1: 승인 대상 결속과 변경 명령의 --context·-n 고정."""

    def test_target_mismatch(self):
        self.assertEqual(fc.target_mismatch(APPROVED, dict(APPROVED)), [])
        live = dict(APPROVED, namespace_uid='other')
        self.assertEqual(fc.target_mismatch(APPROVED, live), ['namespace_uid'])
        self.assertEqual(fc.target_mismatch(dict(APPROVED, deployment_uid=''), APPROVED), ['deployment_uid'],
                         '승인 값이 비어 있으면 일치로 보지 않음')
        self.assertEqual(fc.target_mismatch(APPROVED, None), list(fc.TARGET_KEYS))

    def test_change_commands_always_carry_context_and_namespace(self):
        cmd = fc.oc_change(APPROVED, 'scale', 'deployment/fds-engine', '--replicas=0', timeout=7.9)
        self.assertEqual(cmd[:6], ['oc', '--context', 'rosa-admin/fds', '--request-timeout=7.9s', '-n', 'fds-app'])
        self.assertEqual(cmd[6:], ['scale', 'deployment/fds-engine', '--replicas=0'])
        st = fc.oc_change(APPROVED, 'rollout', 'status', 'deployment/fds-engine', timeout=30)
        self.assertEqual(st[6:], ['rollout', 'status', 'deployment/fds-engine', '--timeout=30s'])
        self.assertEqual(fc.oc_change(APPROVED, 'get', 'deployment/fds-engine', timeout=5)[6:], ['get', 'deployment/fds-engine'])
        with self.assertRaises(fc.ClockError):
            fc.oc_change(dict(APPROVED, context=''), 'scale', 'deployment/fds-engine', '--replicas=0', timeout=5)
        with self.assertRaises(fc.ClockError):
            fc.oc_change(APPROVED, 'delete', 'deployment/fds-engine', timeout=5)

    def test_review_b1_timeout_never_exceeds_remaining(self):
        """PR32 리뷰 B1: 300초 직전 0.2초 남았을 때 1초로 올리지 않는다. 0·음수·NaN·Infinity 거부."""
        b = fc.budget(T0 + 299.8, T0, 'cleanup', 10)
        self.assertAlmostEqual(b['timeout'], 0.2, places=6)
        cmd = fc.oc_change(APPROVED, 'scale', 'deployment/fds-engine', '--replicas=1', timeout=b['timeout'])
        t = [a for a in cmd if a.startswith('--request-timeout=')][0]
        self.assertLessEqual(float(t.split('=')[1].rstrip('s')), b['timeout'])
        self.assertEqual(fc.oc_change(APPROVED, 'get', 'deployment/fds-engine', timeout=0.1234567)[3], '--request-timeout=0.123456s',
                         '자릿수 정리도 올림하지 않음')
        for bad in (0, -1, float('nan'), float('inf'), True, 1e-9):
            with self.assertRaises(fc.ClockError, msg=repr(bad)):
                fc.oc_change(APPROVED, 'get', 'deployment/fds-engine', timeout=bad)
        with self.assertRaises(fc.ClockError):
            fc.budget(float('inf'), T0, 'cleanup', 10)

    def test_review_b2_target_and_options_bound_to_approval(self):
        """PR32 리뷰 B2: 승인 deployment=fds-engine인데 다른 대상·전역 옵션을 넣으면 거부."""
        with self.assertRaises(fc.ClockError):
            fc.oc_change(APPROVED, 'scale', 'deployment/transaction-api', '--replicas=0',
                         '--context=phase1', '--namespace=phase1', timeout=5)
        for args in (('deployment/transaction-api', '--replicas=0'),
                     ('deployment/fds-engine', '--replicas=0', '--context=phase1'),
                     ('deployment/fds-engine', '--namespace=phase1'),
                     ('deployment/fds-engine', '--replicas=-1')):
            with self.assertRaises(fc.ClockError, msg=repr(args)):
                fc.oc_change(APPROVED, 'scale', *args, timeout=5)
        with self.assertRaises(fc.ClockError):
            fc.oc_change(APPROVED, 'rollout', 'undo', 'deployment/fds-engine', timeout=5)
        with self.assertRaises(fc.ClockError):
            fc.oc_change(APPROVED, 'get', 'deployment/fds-engine', '-o', 'yaml', timeout=5)
        with self.assertRaises(fc.ClockError):
            fc.oc_change(dict(APPROVED, deployment_uid=''), 'get', 'deployment/fds-engine', timeout=5)
        # restart는 별도 승인이 있을 때만
        with self.assertRaises(fc.ClockError):
            fc.oc_change(APPROVED, 'rollout', 'restart', 'deployment/transaction-api', timeout=5)
        approved_tx = dict(APPROVED, deployment='transaction-api')
        with self.assertRaises(fc.ClockError):
            fc.oc_change(approved_tx, 'rollout', 'restart', 'deployment/transaction-api', timeout=5)
        self.assertEqual(fc.oc_change(approved_tx, 'rollout', 'restart', 'deployment/transaction-api', timeout=5,
                                      allow_restart=True)[6:], ['rollout', 'restart', 'deployment/transaction-api'])


if __name__ == '__main__':
    unittest.main()
