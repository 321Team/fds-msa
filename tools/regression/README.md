# P1-E2E-01 회귀 시험 도구

P1-E2E-01 [#20](https://github.com/321Team/fds-project-baseline/issues/20) 회귀 시험 2회차(10/5 이미지 전환 [#110](https://github.com/321Team/fds-project-baseline/issues/110) 뒤)에 쓰는 요청·판정 도구다. 1회차([fds-project-evidence#68](https://github.com/321Team/fds-project-evidence/pull/68), RUN `202609291300`, 24 PASS)는 채팅으로 붙여넣은 명령으로 실행했고, 2회차는 같은 케이스와 기준을 이 파일로 고정해 실행한다.

운영 `fdsdb`에 시험 거래를 쓰는 코드라서 실행 전에 독립 코드 리뷰를 받는다(REVIEW_AUTHORITY_POLICY §3). 실행 기록에는 리뷰를 마친 SHA와 실제로 실행한 `rg.py`의 SHA-256이 같음을 남긴다. `rg.py`는 자기 SHA-256을 `criteria.txt`에 적는다.

## 파일

| 파일 | 실행 위치 | 역할 |
|---|---|---|
| `rg.py` | edge01 | `run`: 기준 기록 → 요청 → 판정. `judge`: 저장된 응답으로 재판정. `crosscheck`: db01 조회 결과와 응답 대조 |
| `../tests/test_regression_rg.py` | CI | selftest 7건(가짜 transaction-api): 정상, Rule 미탐, 5xx 중단, 준비 안 됨, 결과 폴더 재사용 거부, 재판정 일치, DB 대조 |

표준 라이브러리만 쓴다(Python 3.6 이상).

## 케이스 (1회차와 같음 + I01)

| ID | 입력 | 기대 |
|---|---|---|
| P01 | deposit 10,000 | 모두 false |
| P02 | deposit 3,000,000 | R02만 |
| P03-1~4 | withdrawal 10,000 ×4 (같은 계정) | 1~3 false, 4번째 R01만 |
| P04-1~4 | transfer 700,000 ×4 (같은 계정) | 1~3 false, 4번째 R07만 |
| P05 | deposit 1,500,000, `occurred_at` 당일 02:30 +09:00 | R04만 |
| N01 | deposit 2,999,999 | 모두 false |
| N02 | deposit 1,500,000, 05:00 +09:00 | 모두 false |
| N03 | deposit 999,999, 02:30 +09:00 | 모두 false |
| N04-1~4 | transfer 100,000 ×4 | 모두 false |
| N05-1~4 | deposit 10,000 ×4 | 모두 false |
| N06 | `transaction_type=refund` | 422 |
| N07 | `amount` 누락 | 422 |
| I01 | deposit 1,500,000, `occurred_at` 02:30 **시간대 없음** | 판정 제외(INFO). 응답 코드·Rule·DB 저장 시각만 기록. 5xx·연결 실패면 FAIL |

- 계정 `SIM_rg_<RUN>_<ID>`(RUN = KST `yyyymmddHHMM`), `source_ip` 198.51.100.10(문서용 IP), 통화 KRW.
- 201 응답은 `fds_evaluation_skipped=false`이고 `fds_detected`가 트리거 유무와 같아야 PASS다.
- I01은 transaction-api가 시간대 없는 시각을 그대로 받아(`datetime.fromisoformat`) 저장·Rule 판단이 실행 환경 시간대에 따라 달라질 수 있어서 기록만 한다.
- 대상: `10.1.93.105/107/108:30080`에 순서대로 순환(요청마다 새 연결, timeout 10초).

## 사용

```
python3 rg.py run <OUT_DIR>                  # edge01. OUT_DIR은 새 폴더
python3 rg.py judge <OUT_DIR>                # 재판정(요청 없음)
python3 rg.py crosscheck <OUT_DIR> <DB_LOG>  # DB 대조(요청 없음)
```

`run` 순서:
1. `criteria.txt`(케이스·기대값·Metric 기준·도구 SHA-256) → `criteria.sha256` → `meta.json`을 쓴다. 요청보다 먼저다.
2. Worker 3대 `GET /readyz`가 모두 200인지 확인한다.
3. 케이스를 위 순서로 보내고 `results.jsonl`(한 줄에 시각·케이스·Worker·상태 코드·지연·응답 본문)과 `<ID>.json`을 남긴다.
4. `judge.txt`에 케이스별 `PASS/FAIL/INFO`와 합계를 쓴다.

**멈춤 조건(fail-close)**

| 조건 | 기록 | 동작 |
|---|---|---|
| OUT_DIR에 파일이 있음 | `STOP OUT_DIR_NOT_EMPTY` | 아무것도 쓰지 않고 끝낸다 |
| `/readyz`가 200이 아닌 Worker가 있음 | `STOP NOT_READY` | 운영 DB에 쓰기 전에 끝낸다 |
| 응답이 5xx이거나 연결 실패(상태 코드 0) | `STOP HTTP_<코드> <ID>` | 남은 요청을 보내지 않는다. 보내지 않은 케이스는 `FAIL … NOT_SENT` |

재시도는 하지 않는다(같은 케이스가 두 번 저장되면 R01/R07 판정이 달라진다). 종료 코드: 0 = 판정 대상 전부 PASS, 1 = FAIL 있음, 2 = 중단 또는 사용 오류.

## 함께 확인하는 것 (읽기 전용, 이 도구 밖)

- control01: 시험 전·후 Metric(1회차와 같은 6개 query)과 Pod `restartCount`, N08(control01 → Worker `:30080/readyz`가 `000`).
- db01: 아래 조회 출력을 `crosscheck`의 `<DB_LOG>`로 쓴다(`<RUN>`은 `criteria.txt`의 값).

```sql
select account_id, transaction_id, transaction_type, amount, fds_detected, fds_evaluation_skipped,
       coalesce((select string_agg(r->>'rule_id', ',') from jsonb_array_elements(fds_rules) r
                 where (r->>'triggered')::bool), '-'),
       occurred_at
from transactions where account_id like 'SIM_rg_<RUN>_%' order by received_at;
```

`crosscheck`는 201 응답마다 `transaction_id`로 DB 행을 찾아 계정·유형·금액·`fds_detected`·`fds_evaluation_skipped`·트리거 Rule을 비교하고, 응답에 없는 DB 행도 불일치로 센다. `occurred_at`은 출력만 한다.

## 운영 영향

- 운영 `fdsdb`에 시험 거래 최대 25건(정상이면 23건, `SIM_rg_<RUN>_*`)이 남는다. 기능 시험 거래는 보존한다([#11 결정안 5887795557](https://github.com/321Team/fds-project-baseline/issues/11#issuecomment-5887795557)).
- 부하는 약 1초 동안 25건이다. Deployment·설정은 바꾸지 않는다.
- 범위 밖: N09(fds-engine 장애 → fail-open)는 CR [#119](https://github.com/321Team/fds-project-baseline/issues/119) 시험으로 따로 한다. 경로는 edge01 → Worker NodePort 직접이다(edge01 upstream 이관 전).
