"""P1-APP-01 부하 생성기 v3 — 결정안 v2 프로파일(B 20 rps 600초 -> P 50 rps 180초 -> 무부하 120초).

실행: python3 gen3.py <RUN> <OUT_DIR> > <OUT_DIR>/stages.log 2>&1

실패하면 멈춘다(fail-close):
- 동시 요청은 MAX_INFLIGHT개까지만 둔다. 보낼 시각에 빈자리가 없으면 LOAD_GENERATOR_SATURATED로
  새 요청을 멈춘다. 요청이 대기열에 쌓이지 않으므로 다음 단계나 관찰 구간으로 넘어가 시작되지 않는다.
- 단계가 끝나면 그 단계 요청이 DRAIN초 안에 모두 끝나야 다음 단계(또는 관찰)로 간다.
  아니면 STAGE_NOT_DRAINED로 멈춘다.
- PROGRESS초 사이 201 외 응답이 ERROR_STOP건 이상 늘면 ERROR_THRESHOLD로 멈춘다. 단계가 끝나 그 단계
  요청이 모두 끝난 뒤에도 마지막 진행 기록 이후 늘어난 수를 같은 기준으로 한 번 더 본다.
멈추면 이미 보낸 요청이 끝날 때까지(요청마다 TIMEOUT초 이내) 기다린 뒤 종료 코드 2로 끝낸다.
정상 종료는 남은 요청 0건을 기록하고 종료 코드 0이다.
"""
import http.client
import json
import random
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, wait

TARGETS = ('10.1.93.105', '10.1.93.107', '10.1.93.108')
PORT = 30080
STAGES = (('B', 20, 600), ('P', 50, 180))
IDLE = 120
MAX_INFLIGHT = 64
TIMEOUT = 10
DRAIN = 2
PROGRESS = 30
ERROR_STOP = 10


def run(run_id, out_dir, targets=TARGETS, port=PORT, stages=STAGES, idle=IDLE, max_inflight=MAX_INFLIGHT,
        timeout=TIMEOUT, drain=DRAIN, progress=PROGRESS, error_stop=ERROR_STOP, emit=None):
    emit = emit or (lambda line: print(line, flush=True))

    def log(*parts):
        emit(' '.join([time.strftime('%H:%M:%S')] + [str(p) for p in parts]))

    rnd = random.Random(run_id)
    lock = threading.Lock()
    codes = {}
    out = open(f'{out_dir}/requests.log', 'a', encoding='utf-8')

    def send(i, stage, kind):
        target = targets[i % len(targets)]
        body = json.dumps({"account_id": f"SIM_load_{run_id}_{i}", "amount": 10000, "currency": "KRW",
                           "transaction_type": kind, "source_ip": "198.51.100.10"})
        t0 = time.time()
        try:
            conn = http.client.HTTPConnection(target, port, timeout=timeout)
            conn.request('POST', '/api/v1/transactions', body, {'Content-Type': 'application/json'})
            resp = conn.getresponse()
            resp.read()
            code = resp.status
            conn.close()
        except Exception:
            code = -1
        with lock:
            out.write(f"{t0:.3f} {stage} {target} {kind} {code} {(time.time() - t0) * 1000:.1f}\n")
            codes[code] = codes.get(code, 0) + 1

    def snapshot():
        with lock:
            out.flush()
            return dict(codes)

    def errors(counts):
        return sum(n for code, n in counts.items() if code != 201)

    stop = None
    pending = set()
    i = 0
    with ThreadPoolExecutor(max_workers=max_inflight) as ex:
        for stage, rps, duration in stages:
            start = time.time()
            log('START', stage, rps, 'rps', duration, 's', f'{start:.3f}')
            sent = 0
            stage_futures = []
            next_progress = start + progress
            last_errors = errors(snapshot())
            while time.time() - start < duration:
                if time.time() >= next_progress:
                    counts = snapshot()
                    log('..', stage, 'sent', sent, 'inflight', sum(1 for f in pending if not f.done()), 'codes', counts)
                    if errors(counts) - last_errors >= error_stop:
                        stop = 'ERROR_THRESHOLD'
                        break
                    last_errors = errors(counts)
                    next_progress += progress
                delay = start + sent / rps - time.time()
                if delay > 0:
                    time.sleep(min(delay, 0.05))
                    continue
                pending = {f for f in pending if not f.done()}
                if len(pending) >= max_inflight:
                    stop = 'LOAD_GENERATOR_SATURATED'
                    break
                x = rnd.random()
                future = ex.submit(send, i, stage, 'deposit' if x < 0.6 else ('withdrawal' if x < 0.8 else 'transfer'))
                pending.add(future)
                stage_futures.append(future)
                i += 1
                sent += 1
            if stop:
                log('STOP', stop, stage, 'sent', sent, 'inflight', sum(1 for f in pending if not f.done()), f'{time.time():.3f}')
                break
            log('END', stage, 'sent', sent, f'{time.time():.3f}')
            _, not_done = wait([f for f in stage_futures if not f.done()], timeout=drain)
            if not_done:
                stop = 'STAGE_NOT_DRAINED'
                log('STOP', stop, stage, 'outstanding', len(not_done), f'{time.time():.3f}')
                break
            # 마지막 진행 기록 뒤(단계 끝까지와 drain 중) 늘어난 201 외 응답도 같은 기준으로 본다.
            tail_errors = errors(snapshot()) - last_errors
            if tail_errors >= error_stop:
                stop = 'ERROR_THRESHOLD'
                log('STOP', stop, stage, 'tail_errors', tail_errors, f'{time.time():.3f}')
                break
            log('DRAINED', stage, f'{time.time():.3f}')
        if not stop:
            log('IDLE START', f'{time.time():.3f}')
            time.sleep(idle)
            log('IDLE END', f'{time.time():.3f}', 'codes', snapshot())
    # with 블록을 나오면 이미 보낸 요청은 모두 끝난 상태다(요청마다 timeout 이내).
    outstanding = sum(1 for f in pending if not f.done())
    counts = snapshot()
    out.close()
    if stop or outstanding:
        log('FAIL', stop or 'OUTSTANDING', 'outstanding', outstanding, 'codes', counts)
        return 2
    log('DONE', 'outstanding', outstanding, 'codes', counts)
    return 0


if __name__ == '__main__':
    sys.exit(run(sys.argv[1], sys.argv[2]))
