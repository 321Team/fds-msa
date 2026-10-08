"""P2-HYB-01(#47)·P2-E2E-01(#50) ROSA Route 대상 회귀 요청·판정 도구.

P1 rg.py(#20)는 Worker NodePort·HTTP·실행 시 기준 생성 구조라 ROSA에 그대로 쓸 수 없다.
이 도구는 기준 고정(plan)과 사례군 실행(run)을 나누고, HTTPS Route의 인증서·호스트를 검증한다.
표준 라이브러리만 쓴다(Python 3.6 이상).

  python3 p2e2e.py plan <PLAN_DIR> --run RUN --fixture-date YYYY-MM-DD --base-url https://HOST [--cafile CA.pem]
      네트워크 없이 criteria.json·criteria.sha256을 쓴다(10/20 준비).
  python3 p2e2e.py run <PLAN_DIR> <OUT_DIR> --group B1|B2|B3E|B3E-POST|B3D-POST --criteria-sha SHA [--cafile CA.pem]
      고정 기준·도구·CA를 대조한 뒤 /readyz를 확인하고 한 사례군만 보낸다.
  python3 p2e2e.py judge <PLAN_DIR> <OUT_DIR>                 저장된 응답으로 다시 판정한다(요청 없음).
  python3 p2e2e.py crosscheck <PLAN_DIR> <OUT_DIR> <DB_LOG>   db01 조회 결과와 응답을 transaction_id로 대조한다(요청 없음).

run은 멈춤 조건이 있다(fail-close). 모두 POST 전에 확인한다.
- criteria.json SHA-256이 --criteria-sha와 다르거나, 실행 중인 도구 SHA-256이 plan 때와 다르면 멈춘다.
- plan에 CA를 고정했는데 다른 CA를 주면 멈춘다.
- OUT_DIR에 파일이 있거나, 같은 사례군을 이미 보낸 기록(ledger.jsonl)이 있으면 멈춘다(계정 충돌·중복 행 방지).
- Route /readyz가 200이 아니거나 TLS·연결이 실패하면 멈춘다.
보내는 중에는 5xx·연결 실패, 의도하지 않은 fail-open(B1·B2), 장애 주입이 안 된 상태(B3E)에서 멈추고 재시도하지 않는다.
종료 코드: 0 = 판정 대상 전부 PASS, 1 = FAIL 있음, 2 = 중단(STOP) 또는 사용 오류.
"""
import argparse
import hashlib
import http.client
import json
import os
import re
import ssl
import sys
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit

TIMEOUT = 10
SOURCE_IP = '198.51.100.10'  # 문서용 IP
KST = timezone(timedelta(hours=9))
API_PATH, READY_PATH = '/api/v1/transactions', '/readyz'
GROUPS = ('B1', 'B2', 'B3E', 'B3E-POST', 'B3D-POST')
GROUP_NOTES = {
    'B1': '정상 + 4 Rule(R01·R02·R04·R07). engine 정상, DB 연결 정상 상태에서 실행',
    'B2': '경계값·입력 오류(422)·Route 비노출 경로(/metrics). engine 정상 상태에서 실행',
    'B3E': 'fds-engine 0개 상태(장애 주입은 도구 밖에서 확인한 뒤 실행). 201·skipped=true·DB 저장',
    'B3E-POST': 'fds-engine 복구 뒤 1건. skipped=false·R02 정상 평가',
    'B3D-POST': 'DB 경로 복구 뒤 1건. 201·DB 저장 재개. 장애 중 /readyz 503·Endpoint 제외는 Pod·EndpointSlice로 따로 관측',
}
RUN_RE = re.compile(r'^\d{12}$')
DATE_RE = re.compile(r'^\d{4}-\d{2}-\d{2}$')
TS_RE = re.compile(r'^(\d{4})-(\d\d)-(\d\d)[ T](\d\d):(\d\d):(\d\d)(?:\.(\d+))?([+-])(\d\d)(?::?(\d\d))?$')


class Stop(Exception):
    pass


def account(run_id, name):
    return f'SIM_p2_{run_id}_{name}'


def case_table(run_id, fixture_date):
    """사례 목록. expect.kind: rules | http422 | info | failopen | not200."""
    def post(cid, group, kind, amount, acct, occurred_at=None, expect=None, drop_amount=False):
        body = {'account_id': account(run_id, acct), 'amount': amount, 'currency': 'KRW',
                'transaction_type': kind, 'source_ip': SOURCE_IP}
        if occurred_at:
            body['occurred_at'] = occurred_at
        if drop_amount:
            del body['amount']
        return {'id': cid, 'group': group, 'method': 'POST', 'path': API_PATH, 'payload': body, 'expect': expect}

    def rules(*r):
        return {'kind': 'rules', 'rules': sorted(r)}

    t0230, t0500 = f'{fixture_date}T02:30:00+09:00', f'{fixture_date}T05:00:00+09:00'
    out = [post('P01', 'B1', 'deposit', 10000, 'P01', expect=rules()),
           post('P02', 'B1', 'deposit', 3000000, 'P02', expect=rules('R02'))]
    out += [post(f'P03-{i}', 'B1', 'withdrawal', 10000, 'P03', expect=rules('R01') if i == 4 else rules())
            for i in range(1, 5)]
    out += [post(f'P04-{i}', 'B1', 'transfer', 700000, 'P04', expect=rules('R07') if i == 4 else rules())
            for i in range(1, 5)]
    out += [post('P05', 'B1', 'deposit', 1500000, 'P05', t0230, rules('R04')),
            post('N01', 'B2', 'deposit', 2999999, 'N01', expect=rules()),
            post('N02', 'B2', 'deposit', 1500000, 'N02', t0500, rules()),
            post('N03', 'B2', 'deposit', 999999, 'N03', t0230, rules())]
    out += [post(f'N04-{i}', 'B2', 'transfer', 100000, 'N04', expect=rules()) for i in range(1, 5)]
    out += [post(f'N05-{i}', 'B2', 'deposit', 10000, 'N05', expect=rules()) for i in range(1, 5)]
    out += [post('N06', 'B2', 'refund', 10000, 'N06', expect={'kind': 'http422'}),
            post('N07', 'B2', 'deposit', 10000, 'N07', expect={'kind': 'http422'}, drop_amount=True),
            {'id': 'X01', 'group': 'B2', 'method': 'GET', 'path': '/metrics', 'payload': None,
             'expect': {'kind': 'not200'}},
            post('I01', 'B2', 'deposit', 1500000, 'I01', f'{fixture_date}T02:30:00', {'kind': 'info'}),
            post('E01', 'B3E', 'deposit', 10000, 'E01', expect={'kind': 'failopen'}),
            post('E02', 'B3E', 'deposit', 3000000, 'E02', expect={'kind': 'failopen'}),
            post('E03', 'B3E-POST', 'deposit', 3000000, 'E03', expect=rules('R02')),
            post('D01', 'B3D-POST', 'deposit', 10000, 'D01', expect=rules())]
    return out


def db_query(run_id):
    return ("select account_id, transaction_id, transaction_type, amount, fds_detected, fds_evaluation_skipped, "
            "coalesce((select string_agg(r->>'rule_id', ',' order by r->>'rule_id') from jsonb_array_elements("
            "coalesce(nullif(fds_rules, 'null'::jsonb), '[]'::jsonb)) r "
            "where (r->>'triggered')::bool), '-'), occurred_at "
            f"from transactions where account_id like 'SIM\\_p2\\_{run_id}\\_%' order by received_at;")


def sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()


def sha256_file(path):
    with open(path, 'rb') as f:
        return sha256_bytes(f.read())


def tool_sha():
    return sha256_file(os.path.abspath(__file__))


def parse_base_url(base_url):
    u = urlsplit(base_url)
    if u.scheme != 'https' or not u.hostname:
        raise Stop(f'BASE_URL_NOT_HTTPS {base_url}')
    if u.path not in ('', '/') or u.query or u.fragment or u.username or u.password:
        raise Stop(f'BASE_URL_NOT_ROOT {base_url}')
    return u.hostname, u.port or 443


def https_call(base_url, cafile, method, path, payload=None, timeout=TIMEOUT):
    """(상태 코드, 본문). 인증서 검증·호스트 이름 확인은 끄지 않는다. 연결·TLS 실패는 (0, 오류 이름)."""
    host, port = parse_base_url(base_url)
    try:
        ctx = ssl.create_default_context(cafile=cafile)
        conn = http.client.HTTPSConnection(host, port, timeout=timeout, context=ctx)
        data = None if payload is None else json.dumps(payload, ensure_ascii=False).encode('utf-8')
        conn.request(method, path, data, {'Content-Type': 'application/json'} if data else {})
        resp = conn.getresponse()
        text = resp.read().decode('utf-8', 'replace')
        conn.close()
        return resp.status, text
    except Exception as e:
        return 0, type(e).__name__


def write_text(path, text):
    with open(path, 'w', encoding='utf-8') as f:
        f.write(text)


def plan(plan_dir, run_id, fixture_date, base_url, cafile=None, emit=print):
    try:
        if not RUN_RE.match(run_id or ''):
            raise Stop(f'BAD_RUN {run_id}')
        if not DATE_RE.match(fixture_date or ''):
            raise Stop(f'BAD_FIXTURE_DATE {fixture_date}')
        datetime.strptime(fixture_date, '%Y-%m-%d')
        parse_base_url(base_url)
        if cafile and not os.path.isfile(cafile):
            raise Stop(f'CAFILE_NOT_FOUND {cafile}')
    except (Stop, ValueError) as e:
        emit(f'STOP {e}')
        return 2
    os.makedirs(plan_dir, exist_ok=True)
    if os.listdir(plan_dir):
        emit(f'STOP PLAN_DIR_NOT_EMPTY {plan_dir}')
        return 2
    criteria = {
        'schema': 1, 'tool': 'p2e2e.py', 'tool_sha256': tool_sha(), 'run': run_id, 'fixture_date': fixture_date,
        'account_prefix': account(run_id, ''), 'source_ip': SOURCE_IP, 'base_url': base_url.rstrip('/'),
        'cafile_sha256': sha256_file(cafile) if cafile else None, 'groups': GROUP_NOTES,
        'cases': case_table(run_id, fixture_date), 'db_query': db_query(run_id),
        'common': ['201 응답(B1·B2·POST 사례)은 fds_evaluation_skipped=false, fds_detected=(트리거 있음)',
                   'B3E는 201, fds_evaluation_skipped=true, fds_detected=null, fds_rules=null',
                   'X01: Route로 /metrics가 200이면 FAIL(노출). 연결 실패도 판정 근거가 아니므로 FAIL',
                   'I01은 시간대 없는 occurred_at이라 판정 제외(INFO). 5xx·연결 실패면 FAIL',
                   '재시도 없음. 같은 사례군을 두 번 보내지 않는다(ledger.jsonl)'],
    }
    data = (json.dumps(criteria, ensure_ascii=False, sort_keys=True, indent=1) + '\n').encode('utf-8')
    with open(os.path.join(plan_dir, 'criteria.json'), 'wb') as f:
        f.write(data)
    crit_sha = sha256_bytes(data)
    write_text(os.path.join(plan_dir, 'criteria.sha256'), f'{crit_sha}  criteria.json\n')
    emit(f'CRITERIA {crit_sha} RUN={run_id} FIXTURE={fixture_date} TOOL={criteria["tool_sha256"]}')
    return 0


def load_criteria(plan_dir):
    with open(os.path.join(plan_dir, 'criteria.json'), 'rb') as f:
        data = f.read()
    return json.loads(data.decode('utf-8')), sha256_bytes(data)


def read_ledger(plan_dir):
    path = os.path.join(plan_dir, 'ledger.jsonl')
    if not os.path.exists(path):
        return []
    with open(path, encoding='utf-8') as f:
        return [json.loads(line) for line in f if line.strip()]


def load_bound(plan_dir, out_dir):
    """judge·crosscheck 공통: 실행 당시 기준·RUN·Route·도구와 지금 입력이 같은지 확인한다. 다르면 Stop."""
    crit, actual_sha = load_criteria(plan_dir)
    with open(os.path.join(out_dir, 'run_meta.json'), encoding='utf-8') as f:
        meta = json.load(f)
    if (actual_sha != meta.get('criteria_sha256') or crit.get('run') != meta.get('run')
            or crit.get('base_url') != meta.get('base_url') or crit.get('tool_sha256') != meta.get('tool_sha256')
            or tool_sha() != meta.get('tool_sha256')):
        raise Stop(f'EVIDENCE_BINDING_MISMATCH criteria={actual_sha} run_meta={meta.get("criteria_sha256")}')
    group = meta.get('group')
    cases = [c for c in crit['cases'] if c['group'] == group]
    if group not in GROUPS or not cases:
        raise Stop(f'BAD_GROUP {group}')
    return crit, meta, cases


def read_results(out_dir):
    """results.jsonl → {사례: [기록, ...]}. 같은 사례가 두 번 있으면 둘 다 남긴다."""
    got = {}
    path = os.path.join(out_dir, 'results.jsonl')
    if os.path.exists(path):
        with open(path, encoding='utf-8') as f:
            for line in f:
                if line.strip():
                    r = json.loads(line)
                    got.setdefault(r['case'], []).append(r)
    return got


def judge_one(expect, code, text):
    """(판정, 내용). 판정: PASS | FAIL | INFO."""
    kind = expect['kind']
    if kind == 'http422':
        return ('PASS' if code == 422 else 'FAIL'), ''
    if kind == 'not200':
        return ('PASS' if code not in (0, 200) else 'FAIL'), ''
    body = None
    if code == 201:
        try:
            body = json.loads(text)
            skipped, detected, frules = body['fds_evaluation_skipped'], body['fds_detected'], body['fds_rules']
        except (ValueError, KeyError, TypeError):
            return 'FAIL', 'invalid-json'
    if kind == 'info':
        if code == 0 or code >= 500:
            return 'FAIL', ''
        trig = '' if body is None or not body.get('fds_rules') else ','.join(
            sorted(r['rule_id'] for r in body['fds_rules'] if r['triggered']))
        return 'INFO', trig
    if body is None:
        return 'FAIL', ''
    if kind == 'failopen':
        if skipped is True and detected is None and frules is None:
            return 'PASS', 'skipped'
        return 'FAIL', 'INJECTION_NOT_EFFECTIVE' if skipped is False else 'unexpected-body'
    if skipped is not False or not isinstance(frules, list):
        return 'FAIL', 'UNEXPECTED_SKIPPED'
    try:
        trig = sorted(r['rule_id'] for r in frules if r['triggered'])
    except (KeyError, TypeError):
        return 'FAIL', 'invalid-json'
    good = trig == expect['rules'] and detected == bool(expect['rules'])
    return ('PASS' if good else 'FAIL'), ','.join(trig)


def judge(plan_dir, out_dir, emit=print):
    try:
        _, meta, cases = load_bound(plan_dir, out_dir)
    except (Stop, OSError, ValueError, KeyError) as e:
        emit(f'STOP {e}')  # 기존 judge.txt는 건드리지 않는다
        return 2
    group = meta['group']
    got = read_results(out_dir)
    counts = {'PASS': 0, 'FAIL': 0, 'INFO': 0}
    lines = []
    for c in cases:
        recs = got.get(c['id'], [])
        if not recs:
            verdict, detail, code = 'FAIL', 'NOT_SENT', '-'
        elif len(recs) > 1:
            verdict, detail, code = 'FAIL', f'DUPLICATE_RECORD x{len(recs)}', recs[0]['http']
        else:
            r = recs[0]
            verdict, detail = judge_one(c['expect'], r['http'], r['body'])
            code = r['http']
        counts[verdict] += 1
        lines.append(f'{verdict} {c["id"]} {code} {detail}'.rstrip())
    lines.append(f"== {group} {counts['PASS']} PASS / {counts['FAIL']} FAIL / {counts['INFO']} INFO"
                 f" (판정 대상 {counts['PASS'] + counts['FAIL']}건)")
    write_text(os.path.join(out_dir, 'judge.txt'), '\n'.join(lines) + '\n')
    for line in lines:
        emit(line)
    return 1 if counts['FAIL'] else 0


def run(plan_dir, out_dir, group, criteria_sha, cafile=None, timeout=TIMEOUT, emit=print, call=https_call):
    try:
        if group not in GROUPS:
            raise Stop(f'BAD_GROUP {group}')
        crit, actual_sha = load_criteria(plan_dir)
        if actual_sha != (criteria_sha or '').lower():
            raise Stop(f'CRITERIA_SHA_MISMATCH file={actual_sha} given={criteria_sha}')
        if tool_sha() != crit['tool_sha256']:
            raise Stop(f'TOOL_SHA_MISMATCH running={tool_sha()} planned={crit["tool_sha256"]}')
        want_ca = crit['cafile_sha256']
        if (want_ca is None) != (cafile is None):
            raise Stop('CAFILE_MISMATCH plan과 실행의 CA 지정 여부가 다르다')
        if cafile and sha256_file(cafile) != want_ca:
            raise Stop(f'CAFILE_MISMATCH {sha256_file(cafile)} != {want_ca}')
        os.makedirs(out_dir, exist_ok=True)
        if os.listdir(out_dir):
            raise Stop(f'OUT_DIR_NOT_EMPTY {out_dir}')
        cases = [c for c in crit['cases'] if c['group'] == group]
        sent = {e['case'] for e in read_ledger(plan_dir)}
        if any(c['id'] in sent for c in cases):
            raise Stop(f'GROUP_ALREADY_SENT {group} — 새 RUN으로 plan을 다시 만든다')
    except (Stop, OSError, ValueError, KeyError) as e:
        emit(f'STOP {e}')
        return 2

    base = crit['base_url']
    meta = {'group': group, 'run': crit['run'], 'criteria_sha256': actual_sha, 'tool_sha256': crit['tool_sha256'],
            'cafile_sha256': want_ca, 'base_url': base, 'started_epoch': round(time.time(), 3),
            'started_kst': datetime.now(KST).isoformat(timespec='seconds')}
    write_text(os.path.join(out_dir, 'run_meta.json'), json.dumps(meta, ensure_ascii=False) + '\n')
    emit(f'RUN {group} RUN={crit["run"]} CRITERIA={actual_sha}')

    code, text = call(base, cafile, 'GET', READY_PATH, None, timeout)
    emit(f'READYZ {code}')
    if code != 200:
        emit(f'STOP NOT_READY {code} {text if code == 0 else ""}'.rstrip())
        return 2

    stop = None
    ledger = os.path.join(plan_dir, 'ledger.jsonl')
    with open(os.path.join(out_dir, 'results.jsonl'), 'a', encoding='utf-8') as out:
        for c in cases:
            with open(ledger, 'a', encoding='utf-8') as lg:  # 보내기 전에 남긴다(응답 유실 뒤 재전송 방지)
                lg.write(json.dumps({'case': c['id'], 'group': group, 'out_dir': os.path.abspath(out_dir),
                                     't': round(time.time(), 3)}, ensure_ascii=False) + '\n')
            t0 = time.time()
            code, text = call(base, cafile, c['method'], c['path'], c['payload'], timeout)
            rec = {'t': round(t0, 3), 'case': c['id'], 'http': code, 'ms': round((time.time() - t0) * 1000, 1),
                   'body': text}
            out.write(json.dumps(rec, ensure_ascii=False) + '\n')
            out.flush()
            write_text(os.path.join(out_dir, f'{c["id"]}.json'), text)
            emit(f'{time.strftime("%H:%M:%S")} {c["id"]} http={code}')
            if c['method'] == 'GET':
                continue
            if code == 0 or code >= 500:
                stop = f'STOP HTTP_{code} {c["id"]}'
            else:
                verdict, detail = judge_one(c['expect'], code, text)
                if detail in ('UNEXPECTED_SKIPPED', 'INJECTION_NOT_EFFECTIVE'):
                    stop = f'STOP {detail} {c["id"]}'
            if stop:
                emit(stop)
                break
    rc = judge(plan_dir, out_dir, emit)
    return 2 if stop else rc


def parse_ts(value):
    """psql timestamptz 출력 → UTC epoch. 시간대가 없으면 None."""
    m = TS_RE.match(value.strip())
    if not m:
        return None
    y, mo, d, h, mi, s, frac, sign, oh, om = m.groups()
    dt = datetime(int(y), int(mo), int(d), int(h), int(mi), int(s), int((frac or '0')[:6].ljust(6, '0')))
    off = timedelta(hours=int(oh), minutes=int(om or 0)) * (1 if sign == '+' else -1)
    return dt.replace(tzinfo=timezone(off)).timestamp()


def crosscheck(plan_dir, out_dir, db_log, emit=print):
    """201 응답과 DB 행을 Transaction ID로 일대일 대조한다. 중복 ID·사례 기록 누락/중복·DB 행 중복은 불일치."""
    try:
        _, meta, group_cases = load_bound(plan_dir, out_dir)
    except (Stop, OSError, ValueError, KeyError) as e:
        emit(f'STOP {e}')
        return 2
    group = meta['group']
    cases = {c['id']: c for c in group_cases if c['method'] == 'POST'}
    accounts = {c['payload']['account_id'] for c in cases.values()}
    bad = 0
    db = {}
    with open(db_log, encoding='utf-8') as f:
        for line in f:
            p = line.rstrip('\n').split('|')
            if len(p) != 8 or p[0] not in accounts:
                continue
            if p[1] in db:
                bad += 1
                emit(f'NG DB 행 Transaction ID 중복 {p[0]} {p[1]}')
                continue
            db[p[1]] = p
    got = read_results(out_dir)
    n201, owner = 0, {}
    for cid, c in cases.items():
        recs = got.get(cid, [])
        if len(recs) != 1:
            bad += 1
            emit(f'NG {cid} 결과 기록 {len(recs)}건(1건이어야 함)')
            if not recs:
                continue
        r = recs[0]
        if r['http'] != 201:
            emit(f"-- {cid} http={r['http']} (201이 아니므로 DB 행 없음 기대)")
            continue
        n201 += 1
        try:
            j = json.loads(r['body'])
            tid = j['transaction_id']
        except (ValueError, KeyError, TypeError):
            j, tid = {}, None
        if not isinstance(tid, str) or not tid:
            bad += 1
            emit(f'NG {cid} 응답에 Transaction ID 없음')
            continue
        if tid in owner:
            bad += 1
            emit(f'NG {cid} {tid} 중복 Transaction ID ({owner[tid]}와 같음)')
            continue
        owner[tid] = cid
        row = db.get(tid)
        if row is None:
            bad += 1
            emit(f'NG {cid} {tid} DB 행 없음')
            continue
        p = c['payload']
        rules = sorted(x['rule_id'] for x in (j.get('fds_rules') or []) if x.get('triggered'))
        det = '' if j.get('fds_detected') is None else ('t' if j['fds_detected'] else 'f')
        want = [p['account_id'], tid, p['transaction_type'], float(p['amount']), det,
                't' if j.get('fds_evaluation_skipped') else 'f', ','.join(rules) or '-']
        try:
            have = [row[0], row[1], row[2], float(row[3]), row[4], row[5], row[6]]
        except ValueError:
            have = row[:7]
        ok = want == have
        note = ''
        if p.get('occurred_at') and '+' in p['occurred_at'][10:]:
            sent_ts, db_ts = parse_ts(p['occurred_at']), parse_ts(row[7])
            if db_ts is None or abs(sent_ts - db_ts) > 0.001:
                ok, note = False, f' occurred_at 불일치 sent={p["occurred_at"]} db={row[7]}'
        bad += not ok
        emit(f"{'OK' if ok else 'NG'} {cid} {tid} occurred_at={row[7]}{note}"
             + ('' if want == have else f' want={want} have={have}'))
    for k, v in db.items():
        if k not in owner:
            bad += 1
            emit(f'NG 응답에 없는 DB 행 {v[0]} {v[1]}')
    emit(f'== {group} 응답 201 {n201}건 / 고유 ID {len(owner)} / DB {len(db)}행 / 불일치 {bad}')
    return 1 if bad else 0


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    sub = ap.add_subparsers(dest='cmd')
    p = sub.add_parser('plan')
    p.add_argument('plan_dir')
    p.add_argument('--run', required=True)
    p.add_argument('--fixture-date', required=True)
    p.add_argument('--base-url', required=True)
    p.add_argument('--cafile')
    r = sub.add_parser('run')
    r.add_argument('plan_dir')
    r.add_argument('out_dir')
    r.add_argument('--group', required=True, choices=GROUPS)
    r.add_argument('--criteria-sha', required=True)
    r.add_argument('--cafile')
    j = sub.add_parser('judge')
    j.add_argument('plan_dir')
    j.add_argument('out_dir')
    x = sub.add_parser('crosscheck')
    x.add_argument('plan_dir')
    x.add_argument('out_dir')
    x.add_argument('db_log')
    try:
        a = ap.parse_args(argv[1:])
    except SystemExit:
        return 2
    if a.cmd == 'plan':
        return plan(a.plan_dir, a.run, a.fixture_date, a.base_url, a.cafile)
    if a.cmd == 'run':
        return run(a.plan_dir, a.out_dir, a.group, a.criteria_sha, a.cafile)
    if a.cmd == 'judge':
        return judge(a.plan_dir, a.out_dir)
    if a.cmd == 'crosscheck':
        return crosscheck(a.plan_dir, a.out_dir, a.db_log)
    print(__doc__)
    return 2


if __name__ == '__main__':
    sys.exit(main(sys.argv))
