# transaction-api ↔ fds-engine Internal Contract v1.0

> Status: DRAFT (G0 Design Freeze 대상)
> Owner: 이재환
> Related Ticket: P1-MSA-01
> Depends on: FDS_Network_Baseline_v2.2 (Deny: fds-engine → DB)

---

## 0. 설계 전제

`fds-engine`은 DB에 직접 접근할 수 없다 (Network Baseline Deny 정책).
따라서 이력 기반 Rule(R01, R07)에 필요한 집계값은 **transaction-api가 사전 계산**하여
`context` 필드로 전달한다. fds-engine은 완전히 stateless하게 판정만 수행한다.

---

## 1. Endpoint

| 항목 | 값 |
|---|---|
| Method | `POST` |
| URL | `http://fds-engine.<namespace>.svc.cluster.local:8001/evaluate` |
| 노출 범위 | ClusterIP 내부 전용 (외부 미노출) |
| Content-Type | `application/json` |
| Timeout | connect 1s / read 2s (transaction-api 측 설정) |

---

## 2. Request: transaction-api → fds-engine

```json
{
  "transaction_id": "b3f1c2e0-....",
  "account_id": "acc_00123",
  "amount": 1500000,
  "currency": "KRW",
  "transaction_type": "withdrawal",
  "source_ip": "203.0.113.10",
  "occurred_at": "2026-08-26T23:41:00Z",
  "received_at": "2026-08-26T23:41:00.120Z",
  "context": {
    "recent_withdrawal_count_10m": 3,
    "recent_transfer_count_1h": 0,
    "recent_transfer_sum_1h": 0
  }
}
```

| 필드 | 타입 | 필수 | 설명 |
|---|---|---|---|
| transaction_id | string (UUID) | Y | transaction-api 생성 |
| account_id | string | Y | 계좌/사용자 식별자 |
| amount | number | Y | 거래 금액 (KRW 정수 단위) |
| currency | string | Y | ISO 4217, 기본 `KRW` |
| transaction_type | enum | Y | `withdrawal` \| `transfer` \| `deposit` |
| source_ip | string | Y | 없으면 `missing_client_ip_total` 증가 후에도 필드는 전달 (빈 문자열 허용) |
| occurred_at | string (ISO8601 UTC) | Y | R04(심야) 판정 기준 시각 |
| received_at | string (ISO8601 UTC) | Y | 서버 수신 시각 (지연 측정용) |
| context.recent_withdrawal_count_10m | int | R01 대상 시 필수 | 최근 10분 내 동일 계좌 인출 횟수 |
| context.recent_transfer_count_1h | int | R07 대상 시 필수 | 최근 1시간 내 동일 계좌 이체 건수 |
| context.recent_transfer_sum_1h | number | R07 대상 시 필수 | 최근 1시간 내 동일 계좌 이체 합산액 |

> transaction_type이 `deposit`인 경우 context는 0으로 채워서 보내거나 생략 가능 (fds-engine 쪽에서 default 0 처리).

### 2.1. 신규 클라이언트 입력 규약

근거는 APP Lead 이재환의 [09:49 회신6205473163](https://github.com/321Team/fds-project-baseline/issues/20#issuecomment-6205473163)과 [11:39 보완 회신6206804605](https://github.com/321Team/fds-project-baseline/issues/20#issuecomment-6206804605)이다(2026-10-16 KST). 기존 필드 표는 보존하고 신규 입력 규약·서버 구현·잔여 항목을 아래에서 구분한다. 이 절은 위 APP Lead 채택 결정에 따른 신규 입력 규약을 기록한다. 문서 변경의 리뷰·병합 이력은 [fds-msa#38](https://github.com/321Team/fds-msa/pull/38)에서 확인하며, 서버 검증 구현을 뜻하지 않는다.

| 구분 | 규약 및 반영 상태 |
|---|---|
| I01 시간 입력 | 신규 클라이언트·시험 도구가 `occurred_at` 값을 제공하면 `Z` 또는 명시적 offset을 포함한다는 규약을 APP Lead가 채택했다. `2026-10-14T02:30:00+09:00`과 `2026-10-13T17:30:00Z`는 같은 시각이다. UTC Z만으로 제한하지 않는다 |
| 금액 입력 | 신규 클라이언트·시험 도구는 `amount > 0`만 보낸다(APP Lead 채택). 0과 음수는 이 규약의 허용 금액이 아니다. API/DB에 범위 검증이 구현됐다는 뜻은 아니다 |
| 기존 동작·필드와의 구분 | 위 내부 계약 표의 `occurred_at` 필수 여부·UTC 표기·amount 타입/설명은 그대로 둔다. 외부 API의 시각 생략/null 서버 시각 경로와 내부 `/evaluate` 필수 필드를 구분한다 |
| 적용 경계 | 기존 저장 행을 소급 보정/삭제하지 않는다. 시간 규약과 금액 규약을 구분하고, I01 Minor와 별도 Major 후보의 분리를 유지한다 |

### 2.2. I01 — 시간 입력 Minor·규약 문서 반영·잔여 위험

APP Lead의 **I01 Minor, P1 코드 변경 없음** 판단을 유지한다. 규약 문서 반영은 I01의 수정·종결이 아니다. 서버의 naive 입력 거부나 미래 이력 상한은 구현되지 않았으며, 잔여 위험을 유지한다.

- **소스 사실:** Phase1 앱 source `affbc69beef9967f7977d09a6fec14f7fb6c0e94`의 [API](https://github.com/321Team/fds-msa/blob/affbc69beef9967f7977d09a6fec14f7fb6c0e94/transaction-api/app/main.py#L55)는 시각 문자열을 파싱하지만 naive 여부를 거부하지 않는다. 생략/null/빈 문자열은 aware UTC 서버 now로 처리한다. 빈 문자열 처리는 구현 설명이며 신규 규약의 권장 입력으로 추가하지 않는다. `received_at`은 별도의 서버 수신시각이다.
- **소스 사실:** [R04](https://github.com/321Team/fds-msa/blob/affbc69beef9967f7977d09a6fec14f7fb6c0e94/fds-engine/app/rules.py#L43)는 naive를 UTC로 간주한 뒤 KST로 판정한다. 기존 KST 01:00 이상 05:00 미만·금액 기준은 유지한다. 신규 규약을 기존 입력에 소급 적용하지 않는다.
- **기존 실측:** [224](https://github.com/321Team/fds-project-evidence/pull/224)의 naive02:30 입력은 API201·탐지 false·skipped false, DB 표시11:30+09인 I01 INFO다. 해당 deposit 행은 R01 withdrawal/R07 transfer 이력에 포함되지 않는다. 모든 드라이버·DB의 저장 의미나 후속 오탐 실측으로 일반화하지 않는다.
- **잔여:** [이력 조회](https://github.com/321Team/fds-msa/blob/affbc69beef9967f7977d09a6fec14f7fb6c0e94/transaction-api/app/context.py#L13)에 미래 상한이 없어 명시 offset 미래 입력도 영향을 줄 수 있다. 비음수 금액 이력에서 추가 행은 count/sum을 감소시키지 않지만, 모든 허용 입력의 위험을 오탐만으로 제한하지 않는다. 음수 금액 문제는 §2.3의 독립 항목이다. 실제 후속 오탐·미탐 재현은 NOT_RUN이다.

### 2.3. 음수 금액 검증 부재 — 독립 Major 후보·문서/잔여 기록

임시 설명명은 **“음수 금액 검증 부재”**다. APP Lead가 신규 Defect 후보·Severity **Major**로 분리했다. I01의 Minor를 Major로 변경하거나 신규 공식 Defect ID·담당·기한을 부여한 것이 아니다.

- **소스 사실:** [API `amount: float`](https://github.com/321Team/fds-msa/blob/c9c42cc1cc0c135320b81480984941f2a118f592/transaction-api/app/main.py#L25), [DB Numeric 모델](https://github.com/321Team/fds-msa/blob/c9c42cc1cc0c135320b81480984941f2a118f592/transaction-api/app/db.py#L25), [저장소 migration SQL](https://github.com/321Team/fds-msa/blob/c9c42cc1cc0c135320b81480984941f2a118f592/database/migrations/001_create_transactions.sql)에는 금액 양수 검증이 없다. 이는 정적 사실이며 실제 운영 DB 저장 성공을 실측했다는 뜻이 아니다. 문서 main `c9c42cc1cc0c135320b81480984941f2a118f592`를 새 배포 승인으로 사용하지 않는다.
- **정적 추론 예시:** 후속 transfer 요청을 평가하기 **직전**, 같은 계좌의 최근 1시간 이력에 1,000,000원 이체 3행이 이미 저장돼 있으면 count3·sum3,000,000으로 R07 조건을 만족한다. 같은 시간 범위의 -1,500,000원 이체 1행도 이미 저장돼 있다면 count4·sum1,500,000이 되어 합계 조건을 만족하지 않는다. API가 현재 요청을 INSERT하기 전에 이력을 계산하므로 이 예시는 현재 요청을 포함한 전송 건수와 다르다. 미래 시각이나 naive 입력은 필요 없다. 실제 음수 행 저장·후속 탐지 누락 재현은 **NOT_RUN**이다.
- **Rule 범위:** 음수 거래 자체는 R02/R04의 양수 금액 하한을 충족하지 않는다. R01은 count 기반이라 음수 금액의 합계 감소 경로는 없지만, 음수 withdrawal 행도 조회 건수에 포함될 수 있으므로 모든 R01 영향이 없다고 확대하지 않는다.
- **처분:** APP Lead는 Critical0·Regression/Defect 승인을 유지하고 이 Major 후보를 이름 붙인 잔여로 추가했다. P1 코드 변경은 선택하지 않았다. `Field(..., gt=0)`/422 거절, 0·음수 시험, DB `CHECK (amount > 0)`은 후속 변경안 선택지이며 구현·시험·일정 승인이 아니다.

D03의 기존 3실패 경로 제품 Defect0 처분은 그 검증 범위에 유지한다. 위 신규 Major 후보까지 포함한 현재 제품 결함0으로 확대하지 않는다. D02 HTTPS SEC 결정과 전체 Phase1 Close는 별도 판단이다. I01 및 음수 금액 Major 후보의 규약 문서 반영이 서버 검증 구현이나 잔여 위험의 해소를 뜻하지 않는다. 기존 성공 회귀·D04·CICD AC03/AC10은 재사용한다.

---

## 3. Response: fds-engine → transaction-api

```json
{
  "transaction_id": "b3f1c2e0-....",
  "fds_detected": true,
  "fds_rules": [
    { "rule_id": "R01", "triggered": true, "detail": "10분 내 인출 3회 (threshold 3)" },
    { "rule_id": "R02", "triggered": false, "detail": null },
    { "rule_id": "R04", "triggered": false, "detail": null },
    { "rule_id": "R07", "triggered": false, "detail": null }
  ],
  "evaluated_at": "2026-08-26T23:41:00.180Z"
}
```

| 필드 | 타입 | 설명 |
|---|---|---|
| transaction_id | string | 요청 echo, 매칭용 |
| fds_detected | boolean | 4개 rule 중 하나라도 triggered면 true |
| fds_rules | array | **4개 rule 전부 항상 포함** (미탐지도 `triggered: false`로 명시 — 부분 응답 금지) |
| fds_rules[].rule_id | string | R01/R02/R04/R07 고정값 |
| fds_rules[].triggered | boolean | 개별 판정 결과 |
| fds_rules[].detail | string \| null | 사람이 읽을 수 있는 판정 근거, 미탐지 시 null |
| evaluated_at | string (ISO8601 UTC) | fds-engine 판정 완료 시각 |

---

## 4. Rule별 판정 기준 (초안 — 실제 threshold는 구현 시 확정)

| Rule | 필요 입력 | Stateless 여부 |
|---|---|---|
| R01 REPEAT_WITHDRAWAL | `transaction_type=withdrawal` + `context.recent_withdrawal_count_10m` | context 필요 |
| R02 HIGH_AMOUNT | `amount` | 완전 stateless |
| R04 LATE_NIGHT_HIGH_AMOUNT | `occurred_at`(시각) + `amount` | 완전 stateless |
| R07 SMALL_TRANSFER_SPLIT | `transaction_type=transfer` + `context.recent_transfer_count_1h`/`sum_1h` | context 필요 |

---

## 5. 장애/타임아웃 처리 — 기존 Phase 1 정책 연결

[CR-P1-APP-01-01 (#119)](https://github.com/321Team/fds-project-baseline/issues/119)의 DB/FDS 장애 분리와 고정 APP source `affbc69beef9967f7977d09a6fec14f7fb6c0e94`를 따른다. 과거 Option A/B 선택 문구를 새 승인 조건으로 사용하지 않는다.

- fds-engine 호출의 connect timeout은 1초, read timeout은 2초다. `httpx.TimeoutException` 또는 `httpx.HTTPError`이면 `fds_evaluation_error_total`을 증가시키고 fail-open 처리한다. transaction-api는 `fds_detected=null`, `fds_evaluation_skipped=true`로 DB 저장을 시도하며, 저장 성공 시 HTTP201을 반환한다.
- DB 저장 단계의 예외는 rollback·HTTP500·`transaction_save_failure_total` 증가로 처리한다. transaction-api `/readyz`는 DB 연결을 확인하므로 DB 연결 실패 시 HTTP503이며, fds-engine 호출 실패 자체를 readiness 실패로 취급하지 않는다.
- [기존 정상 회귀 기준](https://github.com/321Team/fds-msa/blob/c9c42cc1cc0c135320b81480984941f2a118f592/docs/p1-final-regression-readiness-20261010.md)에서 평가 생략은 정상 성공으로 계산하지 않는다. 위 fail-open은 엔진 실패 경로의 기존 정책이며 모든 장애에서 저장 성공을 보장한다는 뜻이 아니다.
- 이 정정은 기존 정책의 문서 연결이다. §2.1–2.3의 채택 규약·미구현 상태·제품 잔여를 변경하거나 전체 APP/E2E 인수를 판정하지 않는다.

---

## 6. Health Check — 고정 Runtime source 기준

기준은 APP source `affbc69beef9967f7977d09a6fec14f7fb6c0e94`의 두 `app/main.py` 및 `deploy/base/{transaction-api,fds-engine}.yaml`이다. 저장소 최신 HEAD와 실제 배포 버전을 구분한다.

- transaction-api: `/livez`(liveness, 업무 포트8000), `/readyz`(readiness, DB 연결 확인, 실패 시503).
- fds-engine: `/livez`와 `/readyz`(업무 포트8001), DB 의존성 없음.
- 위 deploy/base 두 파일에는 liveness/readiness가 정의되며 startupProbe는 없다. 실제 배포의 startupProbe 여부·값은 해당 Runtime manifest와 Probe223 원본에 따라 판정한다.
- metrics는 API9091/engine9090으로 업무 Probe 포트와 구분한다. 실제 HTTP Probe 적용/오프라인 판독 범위는 [HTTP Probe Runbook](https://github.com/321Team/infra-kubernetes/blob/e60e022333a51a9a1690649ef170c0bda92ad9b9/ops/p1-http-probe/README.md)과 원본 증적223을 따른다.

---

## 7. Open Issues

- [x] §5 기존 Phase 1 장애 처리 정책 연결 — CR-P1-APP-01-01. 이번 문서 정정의 Review·반영은 별도.
- [ ] Rule threshold 실제 값 (R01 횟수, R02 금액, R04 시간대+금액, R07 건수/합산액) — 구현 시 확정
- [ ] `context` 계산 쿼리가 transaction-api → db01 부하에 미치는 영향 측정 (P1-MON-01 이후 확인)
