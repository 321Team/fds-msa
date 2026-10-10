"""P1-E2E-01 회귀 시험(#20) 요청·판정 도구 — 2회차(10/5 이미지 전환 뒤)용.

실행 위치: edge01(요청). 표준 라이브러리만 쓴다(Python 3.6 이상).
  python3 rg.py run <OUT_DIR>                  기준 파일을 먼저 쓰고 케이스 요청을 보낸 뒤 판정한다.
  python3 rg.py judge <OUT_DIR>                저장된 results.jsonl로 다시 판정한다(요청 없음).
  python3 rg.py crosscheck <OUT_DIR> <DB_LOG>  db01 조회 결과와 API 응답을 transaction_id로 대조한다(요청 없음).

run은 멈춤 조건이 있다(fail-close):
- OUT_DIR에 파일이 있으면 시작하지 않는다(기록 덮어쓰기 방지).
- 요청 전에 Worker 3대 /readyz가 모두 200이 아니면 운영 DB에 쓰기 전에 멈춘다.
- 응답이 5xx이거나 연결에 실패하면 남은 요청을 보내지 않는다. 재시도하지 않는다(중복 행 방지).
종료 코드: 0 = 판정 대상 전부 PASS, 1 = FAIL 있음, 2 = 중단(STOP) 또는 사용 오류.
"""
import hashlib
import http.client
import json
import os
import re
import sys
import time
from datetime import datetime, timedelta, timezone

TARGETS = ('10.1.93.105', '10.1.93.107', '10.1.93.108')
PORT = 30080
TIMEOUT = 10
SOURCE_IP = '198.51.100.10'  # 문서용 IP
KST = timezone(timedelta(hours=9))
R02, R04 = frozenset({'R02'}), frozenset({'R04'})
NONE = frozenset()


def cases(run_id, today):
    """(케이스 ID, 요청 본문, 기대값). 기대값: Rule 집합 | 'HTTP422' | 'INFO'. 순서대로 보낸다."""
    def body(kind, amount, account, occurred_at=None):
        b = {'account_id': f'SIM_rg_{run_id}_{account}', 'amount': amount, 'currency': 'KRW',
             'transaction_type': kind, 'source_ip': SOURCE_IP}
        if occurred_at:
            b['occurred_at'] = occurred_at
        return b

    t0230, t0500 = f'{today}T02:30:00+09:00', f'{today}T05:00:00+09:00'
    out = [('P01', body('deposit', 10000, 'P01'), NONE),
           ('P02', body('deposit', 3000000, 'P02'), R02)]
    out += [(f'P03-{i}', body('withdrawal', 10000, 'P03'), frozenset({'R01'}) if i == 4 else NONE) for i in range(1, 5)]
    out += [(f'P04-{i}', body('transfer', 700000, 'P04'), frozenset({'R07'}) if i == 4 else NONE) for i in range(1, 5)]
    out += [('P05', body('deposit', 1500000, 'P05', t0230), R04),
            ('N01', body('deposit', 2999999, 'N01'), NONE),
            ('N02', body('deposit', 1500000, 'N02', t0500), NONE),
            ('N03', body('deposit', 999999, 'N03', t0230), NONE)]
    out += [(f'N04-{i}', body('transfer', 100000, 'N04'), NONE) for i in range(1, 5)]
    out += [(f'N05-{i}', body('deposit', 10000, 'N05'), NONE) for i in range(1, 5)]
    n07 = body('deposit', 10000, 'N07')
    del n07['amount']
    out += [('N06', body('refund', 10000, 'N06'), 'HTTP422'),
            ('N07', n07, 'HTTP422'),
            ('I01', body('deposit', 1500000, 'I01', f'{today}T02:30:00'), 'INFO')]
    return out


def criteria_text(run_id, today, tool_sha, targets, port):
    return '\n'.join([
        f'P1-E2E-01 회귀 기준 (시험 전 기록) RUN={run_id} 도구 rg.py SHA-256={tool_sha}',
        f'계정=SIM_rg_{run_id}_<ID> source_ip={SOURCE_IP} 경로=edge01->' + '/'.join(targets) + f':{port} 순환, 재시도 없음',
        'P01 deposit 10000 -> 201 전부 false | P02 deposit 3000000 -> R02만 | P03 withdrawal 10000 x4 -> 1~3 false, 4번째 R01만',
        f'P04 transfer 700000 x4 -> 1~3 false, 4번째 R07만 | P05 deposit 1500000 occurred_at {today}T02:30:00+09:00 -> R04만',
        f'N01 deposit 2999999 -> false | N02 deposit 1500000 {today}T05:00:00+09:00 -> false | N03 deposit 999999 {today}T02:30:00+09:00 -> false',
        'N04 transfer 100000 x4 -> 전부 false | N05 deposit 10000 x4 -> 전부 false | N06 type=refund -> 422 | N07 amount 누락 -> 422',
        f'I01 deposit 1500000 occurred_at {today}T02:30:00(시간대 없음) -> 판정 제외(INFO): 응답 코드·Rule·DB 저장 시각만 기록. 5xx·연결 실패면 FAIL',
        '공통: 201 응답은 fds_evaluation_skipped=false, fds_detected=(트리거 있음).',
        'Metric 증가(I01 201 기준): save_success +23, save_failure 0, fds_evaluated +23, fds_detected R01/R02/R07 각 +1,'
        ' R04 +1(I01이 R04면 +2), missing_client_ip 0. DB 23행. I01이 422면 +22·22행.',
        'Critical: 오탐/미탐, 201인데 DB 미저장, 유효 입력 5xx. 시험 중 Pod restartCount 변화 없음.',
        'N08(control01 -> Worker:30080 = 000)은 control01에서 따로 확인한다.',
    ]) + '\n'


def sha256_file(path):
    with open(path, 'rb') as f:
        return hashlib.sha256(f.read()).hexdigest()


def call(method, target, port, path, payload=None, timeout=TIMEOUT):
    """(상태 코드, 본문). 연결 실패·timeout은 (0, 오류 이름)."""
    try:
        conn = http.client.HTTPConnection(target, port, timeout=timeout)
        data = None if payload is None else json.dumps(payload, ensure_ascii=False).encode('utf-8')
        conn.request(method, path, data, {'Content-Type': 'application/json'} if data else {})
        resp = conn.getresponse()
        text = resp.read().decode('utf-8', 'replace')
        conn.close()
        return resp.status, text
    except Exception as e:
        return 0, type(e).__name__


def load_meta(out_dir):
    with open(os.path.join(out_dir, 'meta.json'), encoding='utf-8') as f:
        meta = json.load(f)
    current_tool = sha256_file(os.path.abspath(__file__))
    if meta['tool_sha256'] != current_tool or meta['criteria_sha256'] != sha256_file(os.path.join(out_dir, 'criteria.txt')):
        raise ValueError('EVIDENCE_BINDING_MISMATCH')
    expected = criteria_text(meta['run'], meta['today'], current_tool, meta['targets'], meta['port'])
    with open(os.path.join(out_dir, 'criteria.txt'), encoding='utf-8') as f:
        if f.read() != expected:
            raise ValueError('CRITERIA_METADATA_MISMATCH')
    return meta


def judge_one(expect, code, text):
    """(판정, Rule 목록 문자열). 판정: PASS | FAIL | INFO."""
    if expect == 'HTTP422':
        return ('PASS' if code == 422 else 'FAIL'), ''
    trig = None
    if code == 201:
        try:
            j = json.loads(text)
            if not isinstance(j, dict) or not isinstance(j['transaction_id'], str) or not j['transaction_id']:
                raise ValueError('invalid transaction id')
            rules = j['fds_rules']
            if not isinstance(rules, list) or len(rules) != 4:
                raise ValueError('four rules required')
            ids = [r['rule_id'] for r in rules]
            if any(not isinstance(rid, str) for rid in ids) or set(ids) != {'R01', 'R02', 'R04', 'R07'}:
                raise ValueError('rule ids must be unique and complete')
            if any(type(r['triggered']) is not bool for r in rules):
                raise ValueError('triggered must be boolean')
            trig = sorted(r['rule_id'] for r in rules if r['triggered'])
            skipped, detected = j['fds_evaluation_skipped'], j['fds_detected']
            if type(detected) is not bool or skipped is not False or detected != bool(trig):
                raise ValueError('invalid normal evaluation flags')
        except (ValueError, KeyError, TypeError):
            return 'FAIL', 'invalid-json'
    if expect == 'INFO':
        if code == 0 or code >= 500:
            return 'FAIL', ''
        return 'INFO', '' if trig is None else ','.join(trig)
    if trig is None:
        return 'FAIL', ''
    good = set(trig) == set(expect) and detected == bool(expect) and skipped is False
    return ('PASS' if good else 'FAIL'), ','.join(trig)


def load_results(out_dir, meta, complete=False):
    """Reject ambiguous evidence before writing a new judgement. No network calls."""
    expected = {cid for cid, _, _ in cases(meta['run'], meta['today'])}
    got, transaction_ids = {}, set()
    with open(os.path.join(out_dir, 'results.jsonl'), encoding='utf-8') as f:
        for line in f:
            r = json.loads(line)
            if not isinstance(r, dict) or r.get('case') not in expected or r['case'] in got:
                raise ValueError('CASE_DUPLICATE_OR_UNKNOWN')
            if type(r.get('http')) is not int or not isinstance(r.get('body'), str) or not isinstance(r.get('worker'), str):
                raise ValueError('RECORD_INVALID')
            if r['worker'] not in meta['targets'] or not (r['http'] == 0 or 100 <= r['http'] <= 599):
                raise ValueError('RECORD_TARGET_OR_STATUS_INVALID')
            if r['http'] == 201:
                j = json.loads(r['body'])
                if not isinstance(j, dict) or not isinstance(j.get('transaction_id'), str) or not j['transaction_id']:
                    raise ValueError('TRANSACTION_ID_INVALID')
                tid = j['transaction_id']
                if tid in transaction_ids:
                    raise ValueError('TRANSACTION_ID_DUPLICATE')
                transaction_ids.add(tid)
            got[r['case']] = r
    if complete and set(got) != expected:
        raise ValueError('CASE_RECORDS_INCOMPLETE')
    return got


def judge(out_dir, emit=print):
    try:
        meta = load_meta(out_dir)
        got = load_results(out_dir, meta)
    except (OSError, ValueError, KeyError, TypeError) as e:
        emit('STOP EVIDENCE_INVALID ' + type(e).__name__)
        return 2
    counts = {'PASS': 0, 'FAIL': 0, 'INFO': 0}
    lines = []
    for cid, _, expect in cases(meta['run'], meta['today']):
        r = got.get(cid)
        if r is None:
            verdict, rules, worker, code = 'FAIL', 'NOT_SENT', '-', '-'
        else:
            verdict, rules = judge_one(expect, r['http'], r['body'])
            worker, code = r['worker'], r['http']
        counts[verdict] += 1
        lines.append(f'{verdict} {cid} {worker} {code} {rules}'.rstrip())
    lines.append(f"== {counts['PASS']} PASS / {counts['FAIL']} FAIL / {counts['INFO']} INFO (판정 대상 {counts['PASS'] + counts['FAIL']}건)")
    with open(os.path.join(out_dir, 'judge.txt'), 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines) + '\n')
    for line in lines:
        emit(line)
    return 1 if counts['FAIL'] else 0


def run(out_dir, run_id=None, targets=TARGETS, port=PORT, timeout=TIMEOUT, now=None, emit=print):
    now = now or datetime.now(KST)
    run_id = run_id or now.strftime('%Y%m%d%H%M')
    today = now.strftime('%Y-%m-%d')
    os.makedirs(out_dir, exist_ok=True)
    if os.listdir(out_dir):
        emit(f'STOP OUT_DIR_NOT_EMPTY {out_dir}')
        return 2
    tool_sha = sha256_file(os.path.abspath(__file__))
    with open(os.path.join(out_dir, 'criteria.txt'), 'w', encoding='utf-8') as f:
        f.write(criteria_text(run_id, today, tool_sha, targets, port))
    crit_sha = sha256_file(os.path.join(out_dir, 'criteria.txt'))
    with open(os.path.join(out_dir, 'criteria.sha256'), 'w', encoding='utf-8') as f:
        f.write(f'{crit_sha}  criteria.txt\n')
    meta = {'run': run_id, 'today': today, 'tool_sha256': tool_sha, 'criteria_sha256': crit_sha,
            'targets': list(targets), 'port': port, 'criteria_written_epoch': round(time.time(), 3)}
    with open(os.path.join(out_dir, 'meta.json'), 'w', encoding='utf-8') as f:
        json.dump(meta, f, ensure_ascii=False)
    emit(f'CRITERIA {crit_sha} RUN={run_id} TOOL={tool_sha}')

    for t in targets:
        code, _ = call('GET', t, port, '/readyz', timeout=timeout)
        emit(f'READYZ {t} {code}')
        if code != 200:
            emit(f'STOP NOT_READY {t} {code}')
            return 2

    stop = None
    with open(os.path.join(out_dir, 'results.jsonl'), 'a', encoding='utf-8') as out:
        for n, (cid, payload, _) in enumerate(cases(run_id, today)):
            target = targets[n % len(targets)]
            t0 = time.time()
            code, text = call('POST', target, port, '/api/v1/transactions', payload, timeout)
            rec = {'t': round(t0, 3), 'case': cid, 'worker': target, 'http': code,
                   'ms': round((time.time() - t0) * 1000, 1), 'body': text}
            out.write(json.dumps(rec, ensure_ascii=False) + '\n')
            out.flush()
            with open(os.path.join(out_dir, f'{cid}.json'), 'w', encoding='utf-8') as f:
                f.write(text)
            emit(f'{time.strftime("%H:%M:%S")} {cid} {target} http={code}')
            if code == 0 or code >= 500:
                stop = f'STOP HTTP_{code} {cid}'
                emit(stop)
                break
    rc = judge(out_dir, emit)
    return 2 if stop else rc


def parse_db_log(path):
    """db01 조회 출력: account|transaction_id|type|amount|detected|skipped|rules|occurred_at 줄만 읽는다."""
    rows = {}
    with open(path, encoding='utf-8') as f:
        for line in f:
            p = line.rstrip('\n').split('|')
            if p[0].startswith('SIM_rg_'):
                if len(p) != 8 or not p[1] or p[1] in rows:
                    raise ValueError('DB_ROW_AMBIGUOUS')
                rows[p[1]] = p
    return rows


def crosscheck(out_dir, db_log, emit=print):
    bad, seen = 0, set()
    try:
        meta = load_meta(out_dir)
        prefix = f"SIM_rg_{meta['run']}_"
        case_list = cases(meta['run'], meta['today'])
        payloads = {cid: p for cid, p, _ in case_list}
        got = load_results(out_dir, meta, complete=True)
        db = {k: v for k, v in parse_db_log(db_log).items() if v[0].startswith(prefix)}
        # Matching two empty/malformed sources is not a successful regression.
        for cid, _, expected in case_list:
            r = got[cid]
            if judge_one(expected, r['http'], r['body'])[0] == 'FAIL':
                raise ValueError('API_CASE_FAILED')
        results = [got[cid] for cid, _, _ in case_list]
    except (OSError, ValueError, KeyError, TypeError):
        emit('STOP EVIDENCE_INVALID')
        return 2
    for r in results:
        cid = r['case']
        if r['http'] != 201:
            emit(f"-- {cid} http={r['http']} (201이 아니므로 DB 행 없음 기대)")
            continue
        j = json.loads(r['body'])
        tid = j['transaction_id']
        seen.add(tid)
        row = db.get(tid)
        if row is None:
            bad += 1
            emit(f'NG {cid} {tid} DB 행 없음')
            continue
        p = payloads[cid]
        rules = sorted(x['rule_id'] for x in j['fds_rules'] if x['triggered'])
        want = [p['account_id'], tid, p['transaction_type'], p['amount'],
                't' if j['fds_detected'] else 'f', 't' if j['fds_evaluation_skipped'] else 'f', ','.join(rules) or '-']
        try:
            have = [row[0], row[1], row[2], float(row[3]), row[4], row[5], row[6]]
        except ValueError:
            bad += 1
            emit(f'NG {cid} {tid} DB amount invalid')
            continue
        want[3] = float(want[3])
        ok = want == have
        bad += not ok
        emit(f"{'OK' if ok else 'NG'} {cid} {tid} occurred_at={row[7]}" + ('' if ok else f' want={want} have={have}'))
    extra = [v for k, v in db.items() if k not in seen]
    for v in extra:
        bad += 1
        emit(f'NG 응답에 없는 DB 행 {v[0]} {v[1]}')
    emit(f'== DB {len(db)}행 / 응답 201 {len(seen)}건 / 불일치 {bad}')
    return 1 if bad else 0


def main(argv):
    if len(argv) == 3 and argv[1] == 'run':
        return run(argv[2])
    if len(argv) == 3 and argv[1] == 'judge':
        return judge(argv[2])
    if len(argv) == 4 and argv[1] == 'crosscheck':
        return crosscheck(argv[2], argv[3])
    print(__doc__)
    return 2


if __name__ == '__main__':
    sys.exit(main(sys.argv))
