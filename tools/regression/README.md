# P1-E2E-01 회귀 시험 도구

P1-E2E-01 [#20](https://github.com/321Team/fds-project-baseline/issues/20) 회귀 시험 2회차(10/5 이미지 전환 [#110](https://github.com/321Team/fds-project-baseline/issues/110) 뒤)에 쓰는 요청·판정 도구다. 1회차([fds-project-evidence#68](https://github.com/321Team/fds-project-evidence/pull/68), RUN `202609291300`, 24 PASS)는 채팅으로 붙여넣은 명령으로 실행했고, 2회차는 같은 케이스와 기준을 이 파일로 고정해 실행한다.

운영 `fdsdb`에 시험 거래를 쓰는 코드라서 실행 전에 독립 코드 리뷰를 받는다(REVIEW_AUTHORITY_POLICY §3). 실행 기록에는 리뷰를 마친 SHA와 실제로 실행한 `rg.py`의 SHA-256이 같음을 남긴다. `rg.py`는 자기 SHA-256을 `criteria.txt`에 적는다.

## 파일

| 파일 | 실행 위치 | 역할 |
|---|---|---|
| `rg.py` | edge01 | `run`: 기준 기록 → 요청 → 판정. `judge`: 저장된 응답으로 재판정. `crosscheck`: db01 조회 결과와 응답 대조 |
| `../tests/test_regression_rg.py` | CI | selftest 18건(가짜 transaction-api·합성 로그): 기존 정상/중단 경로, 4개 Rule·boolean 계약, 누락/중복·source/기준 결속, DB 대조 |

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
- I01의 Rule 계산은 승인 소스 `affbc69`에서 시간대 없는 값을 UTC로 간주해 KST로 변환한다. 따라서 naive `02:30`은 KST `11:30`이며 R04가 아니다. transaction-api는 naive 값을 DB driver에 전달하므로 실제 DB 저장/표시 시각은 별도로 관측한다. I01의 기존 INFO 범위는 유지하며 새 업무 시간 정책을 채택하지 않는다.
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

`judge`/`crosscheck`는 `meta.json`의 도구 SHA-256과 현재 `rg.py` bytes, 기준 SHA-256과 `criteria.txt`, RUN·날짜·대상·port와 재생성한 기준이 일치할 때만 판정한다. 다른 버전의 도구로 과거 증적을 재판정하려면 해당 회차의 실제 도구를 보존해 사용한다. hash·meta를 편집해 새 도구와 맞추지 않는다.

- 케이스 중복/미정의 ID·대상 불일치·201 Transaction ID 중복·잘못된 기록은 `STOP EVIDENCE_INVALID` / rc2다. 기존 `judge.txt`는 덮어쓰지 않는다.
- 정상 201은 고유한 R01/R02/R04/R07 4개, boolean `triggered`/`fds_detected`, `skipped=false`와 검출 일치가 필요하다. 누락 Rule을 “false”로 간주하지 않는다.
- `judge`는 정상적으로 중단된 회차의 미전송 케이스를 FAIL로 기록한다. `crosscheck`는 모든 25개 요청 기록이 있어야 진행하며, 빈 응답/DB 두 파일이나 일부 응답의 일치만으로 PASS하지 않는다. 정상 API 케이스의 기대 판정을 먼저 확인하고 DB Transaction ID 중복·잘못된 행을 거부한다.
- 파일 내부 결속은 원본 생성자/독립 승인·외부 manifest의 진위를 증명하지 않는다. 실제 실행 도구 SHA와 승인 source, RUN의 사전 DB 0행 확인, 전체 원본 보관·독립 증적 리뷰는 실행안에서 함께 확인한다. RUN은 분 단위이므로 새 폴더만 만들고 같은 RUN을 재전송하지 않는다.

현행 Final Regression 준비·입력의 경계는 [P1 실행 준비 대조](../../docs/p1-final-regression-readiness-20261010.md)에 연결한다.

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

`crosscheck`는 201 응답마다 `transaction_id`로 DB 행을 찾아 계정·유형·금액·`fds_detected`·`fds_evaluation_skipped`·트리거 Rule을 비교하고, 응답에 없는 DB 행도 불일치로 센다. `occurred_at`은 출력만 한다. 이 조회는 해당 RUN으로 제한하고 원본 출력·종료 코드를 보관한다. 파서가 별도 SQL 집계나 timestamp 저장 의미까지 증명하지 않는다.

## 운영 영향

- 운영 `fdsdb`에 시험 거래 최대 25건(정상이면 23건, `SIM_rg_<RUN>_*`)이 남는다. 기능 시험 거래는 보존한다([#11 결정안 5887795557](https://github.com/321Team/fds-project-baseline/issues/11#issuecomment-5887795557)).
- 부하는 약 1초 동안 25건이다. Deployment·설정은 바꾸지 않는다.
- 범위 밖: N09(fds-engine 장애 → fail-open)는 CR [#119](https://github.com/321Team/fds-project-baseline/issues/119) 시험으로 따로 한다. 경로는 edge01 → Worker NodePort 직접이다(edge01 upstream 이관 전).

---

# P2-HYB-01·P2-E2E-01 ROSA 회귀 도구 (`p2e2e.py`)

Phase 2 #47→#50 작업창([#50 계획 6051395052](https://github.com/321Team/fds-project-baseline/issues/50#issuecomment-6051395052))에서 ROSA Route로 거래를 보내고 판정한다. `rg.py`(P1, 리뷰 완료)는 Worker NodePort·HTTP·실행 시 기준 생성 구조라 ROSA에 쓸 수 없어서([리뷰 B1 6051518639](https://github.com/321Team/fds-project-baseline/issues/50#issuecomment-6051518639)) 별도 파일로 둔다. `rg.py`는 바꾸지 않는다.

운영 `fdsdb`에 시험 거래를 쓰는 코드라서 ROSA Runtime 전에 독립 코드 리뷰를 받는다(REVIEW_AUTHORITY_POLICY §3). 표준 라이브러리만 쓴다(Python 3.6 이상).

## `rg.py`와 다른 점

| 항목 | `rg.py` (P1) | `p2e2e.py` (P2) |
|---|---|---|
| 대상 | Worker 3대 `:30080` HTTP 순환 | 승인 Route 하나, **HTTPS 인증서·호스트 이름 검증**(끄는 옵션 없음). 사설 CA면 `--cafile`, CA SHA-256은 plan에 고정 |
| 기준 | `run` 때 날짜·계정으로 새로 생성 | `plan`이 네트워크 없이 `criteria.json`을 만들고, `run`은 `--criteria-sha`·도구 SHA-256·CA SHA-256이 모두 같을 때만 실행 |
| 계정 | `SIM_rg_<RUN>_<ID>` | `SIM_p2_<RUN>_<ID>` |
| 실행 단위 | 25건 연속 | 사례군(`B1`·`B2`·`B3E`·`B3E-POST`·`B3D-POST`)별. `ledger.jsonl`에 보내기 **전** 기록해 같은 사례군 재전송을 막는다 |
| 장애 사례 | 없음 | `B3E` fail-open 판정(`201`·`skipped=true`·`fds_detected=null`·`fds_rules=null`) |
| DB 대조 | `occurred_at` 출력만 | 시간대가 있는 `occurred_at`은 보낸 값과 같은 시각인지 비교, `fds_detected=null` 처리. **사례↔응답↔DB 행 일대일**: 사례 기록 누락·중복, 서로 다른 사례의 같은 Transaction ID, DB 행 ID 중복은 불일치 |
| 재판정 결속 | 없음 | `judge`·`crosscheck`는 `run_meta.json`의 기준 SHA-256·RUN·Route·도구 SHA-256이 지금 입력과 같을 때만 판정. 다르면 `STOP EVIDENCE_BINDING_MISMATCH`, 기존 `judge.txt`를 덮어쓰지 않음 |

## 사례군

`R04` 시각은 plan의 `--fixture-date`로 고정한다(실행 날짜와 무관). 계정이 RUN마다 새로 생기므로 R01·R07 이력은 그 RUN 안의 요청만 센다.

| 사례군 | 사례 | 기대 | 실행 시점(#50 계획) |
|---|---|---|---|
| B1 | P01 deposit 10,000 / P02 3,000,000 / P03 withdrawal 10,000 ×4 / P04 transfer 700,000 ×4 / P05 1,500,000 `fixture 02:30+09:00` | 전부 false / R02 / 4번째 R01 / 4번째 R07 / R04 | 10/21 B1 |
| B2 | N01~N05(P1과 같음), N06 refund·N07 amount 누락 → 422, **X01 `GET /metrics` → 200이 아니어야 함**(Route 비노출), I01 시간대 없는 시각(INFO) | 전부 false / 422 / 200 아님 / 기록만 | 10/21 B2 |
| B3E | E01 10,000·E02 3,000,000 | 둘 다 fail-open(검출 안 함, 저장됨) | fds-engine 0개 확인 뒤 |
| B3E-POST | E03 3,000,000 | R02, `skipped=false` | fds-engine 복구 확인 뒤 |
| B3D-POST | D01 10,000 | 201, `skipped=false`, 검출 없음 | DB 경로 복구 확인 뒤 |

## 사용

```
python3 p2e2e.py plan <PLAN_DIR> --run <yyyymmddHHMM> --fixture-date <YYYY-MM-DD> --base-url https://<route-host> [--cafile <CA.pem>]
python3 p2e2e.py run <PLAN_DIR> <OUT_DIR> --group B1 --criteria-sha <criteria.sha256 값> [--cafile <CA.pem>]
python3 p2e2e.py judge <PLAN_DIR> <OUT_DIR>
python3 p2e2e.py crosscheck <PLAN_DIR> <OUT_DIR> <DB_LOG>
```

- `plan`은 10/20에 만든다. `PLAN_DIR`은 새 폴더여야 하고, `criteria.json`·`criteria.sha256`만 쓴다(요청 없음).
- `run`은 사례군마다 새 `OUT_DIR`을 쓴다. `run_meta.json`(기준·도구·CA SHA-256, 시작 시각)을 먼저 쓰고 `GET /readyz`(Route)가 200일 때만 보낸다. 결과는 `results.jsonl`·`<ID>.json`·`judge.txt`.

**멈춤 조건(fail-close)** — 위의 것은 모두 요청 전에 확인한다.

| 조건 | 기록 |
|---|---|
| `criteria.json` SHA-256 ≠ `--criteria-sha` | `STOP CRITERIA_SHA_MISMATCH` |
| 실행 중 도구 SHA-256 ≠ plan 때 값 | `STOP TOOL_SHA_MISMATCH` |
| CA 지정 여부·CA SHA-256이 plan과 다름 | `STOP CAFILE_MISMATCH` |
| `OUT_DIR`에 파일이 있음 / 같은 사례군을 이미 보냄 | `STOP OUT_DIR_NOT_EMPTY` / `STOP GROUP_ALREADY_SENT`(새 RUN으로 plan 다시) |
| Route `/readyz` ≠ 200, TLS·연결 실패 | `STOP NOT_READY <코드> <오류>` |
| 응답 5xx·연결 실패 | `STOP HTTP_<코드> <ID>` |
| B1·B2에서 `skipped=true`(의도하지 않은 fail-open) | `STOP UNEXPECTED_SKIPPED <ID>` |
| B3E에서 `skipped=false`(장애 주입이 효과 없음) | `STOP INJECTION_NOT_EFFECTIVE <ID>` |

재시도는 하지 않는다. 종료 코드: 0 = 판정 대상 전부 PASS, 1 = FAIL 있음, 2 = 중단 또는 사용 오류.

## 이 도구 밖에서 확인하는 것

- **장애 주입과 상태 확인:** fds-engine 0개·DB 경로 단절·복구는 도구가 하지 않는다. 주입 상태(engine serving endpoint 부재, 차단 규칙 readback·카운터)와 복구를 먼저 확인한 뒤 해당 사례군을 실행한다.
- **DB 장애 판정:** `/readyz` 503은 Router 응답이 아니라 Pod에서 관측하고, EndpointSlice의 해당 endpoint `ready=false`로 확인한다. 이 도구는 DB 장애 **중** 요청을 보내지 않는다.
- **Port 차단·fds-engine → DB 거부:** NetworkPolicy·DB 인증 쪽 수집 명령으로 따로 확인한다.
- **DB 대조 입력:** `criteria.json`의 `db_query`를 db01에서 `psql -At -F'|'`로 실행한 출력이 `<DB_LOG>`다(시간대 포함 `occurred_at`, null은 빈 칸). fail-open 행의 `fds_rules`는 앱이 JSON `null`로 저장하므로(SQLAlchemy JSONB 기본값), 조회식은 **JSON null과 SQL NULL만** 빈 배열로 바꾼다. 문자열·객체·숫자처럼 배열이 아닌 다른 저장값은 빈 배열로 바꾸지 않고 조회 단계에서 오류(SQLSTATE 22023)로 드러나게 한다(정상 판정으로 숨기지 않음).

## 운영 영향

- 운영 `fdsdb`에 `SIM_p2_<RUN>_*` 시험 거래가 최대 27행 남는다: B1 11 + B2 12(422 두 건은 저장 안 됨, I01 포함) + B3E 2 + B3E-POST 1 + B3D-POST 1. 기능 시험 거래는 보존한다([#11 결정안 5887795557](https://github.com/321Team/fds-project-baseline/issues/11#issuecomment-5887795557)).
- `selftest`: `../tests/test_regression_p2e2e.py` 16건(가짜 transaction-api, 실제 AWS·ROSA 호출 없음). 평문 서버에 실제 HTTPS로 붙여 TLS 실패 시 POST 0건으로 멈추는지 확인한다. 생성 `db_query`는 PostgreSQL(`initdb`)이 있으면 임시 클러스터에서 실제로 실행해 JSON null·SQL NULL·Rule 배열을 대조하고, 문자열·객체·숫자 저장값은 조회가 실패하는지 확인한다(CI Ubuntu 러너에서 실행, 없으면 그 1건만 skip).
