# 최종 이미지 축약 부하 회귀 준비 — 2026-10-14

CODEX_ASSISTED / 이권욱 요청 `후속 절차 진행`에 따른 준비다.
코드/정적·로컬 시험과 운영 실행을 구분한다. **운영 NOT_RUN, 실행창 미확정,
이 변경의 독립 코드 리뷰·병합 전.** 이 문서는 Runtime GO·APP/E2E 인수·Phase1 Close가 아니다.

## 왜 남는가

- [APP 결정안 v2 §8](https://github.com/321Team/fds-project-baseline/issues/15#issuecomment-5885861552)과
  [G3 승인](https://github.com/321Team/fds-project-baseline/issues/15#issuecomment-5886568007)은
  이미지 전환 뒤 **20 rps 2분 → 50 rps 2분(8,400건)**을 regression gate로 정했다.
- [Resource 인수](https://github.com/321Team/fds-project-baseline/issues/15#issuecomment-5910524397)는
  이전 두 이미지의 baseline 범위다. 체크를 취소하거나 현재 이미지의 sizing 성공으로 확대하지 않는다.
- [증적224](https://github.com/321Team/fds-project-evidence/pull/224), merge
  `89f9d4cbd3ff77aa6fc70cfe3de34a71ffb09758`의 25요청 기능 회귀/DB23행은 유효하다.
  이는 4분 부하·Q1/Q2/Q3 관측을 포함하지 않는다. 새로 만든 합격조건이 아니다.
- 원 `gen3.py` CLI는 full 21,000건에 고정돼 있었다. 이번 변경은 기존 `run`의 단계 인자로
  승인 축약 프로파일을 선택하고, 회차 파일 중복만 차단한다. full 기본 동작은 유지한다.

## 고정 대상과 실행 전 입력

| 항목 | 준비값 / 실행 직전 확인 |
|---|---|
| 실행 위치 | edge01, 기존 승인 계정·SSH 경로. Prometheus 조회는 control01의 기존 관리 경로 |
| 앱 소스 | `affbc69beef9967f7977d09a6fec14f7fb6c0e94` |
| API image | `10.1.93.54/fds/transaction-api@sha256:338b8a2871507ce8b42deedc916b26e350577ee6efd18df23d7ff2dd4b17dff0` |
| engine image | `10.1.93.54/fds/fds-engine@sha256:8b257adb08b6d381f72b66d3386efea6112a8f072ecfafcbcd463bcd1c3be89d` |
| 공급/실행 연결 | [TBS217](https://github.com/321Team/fds-project-evidence/pull/217) → [Push218](https://github.com/321Team/fds-project-evidence/pull/218) → [Deploy219](https://github.com/321Team/fds-project-evidence/pull/219) |
| 배치/Resource | 두 앱 각3Ready·Worker별1/1·requests250m/256Mi·limits500m/512Mi. 직접 확인 전 현재 실시간 값으로 주장하지 않음 |
| 서비스 | edge01 → Worker `.105/.107/.108:30080` 순환. 기존 NodePort 경로 유지 |
| RUN / 창 | 승인 창 결정 후 새 12자리 RUN 고정. 기존 `202610141025` 기능 회귀 RUN을 재사용하지 않음 |
| 코드 | 이 PR의 독립 검토된 HEAD/병합 및 gen3.py·q_range.py·promql.txt SHA256을 실행 기록에 고정 |
| 현장 | 콘솔·DB 사전/사후 조회 가능, Harbor/H6·APP/DB/MON/노드 변경 및 다른 거래 writer 비중첩, 현장 공지 완료 |

과거 11:15 종료의 승인 창을 연장하거나 전용하지 않는다. 실제 시작·최종 종료 상한은
리뷰 완료 후 현장 조건과 함께 별도 고정한다. 이 단계에서는 파일 배치·port-forward·POST를 하지 않는다.

## 실행 순서

1. 코드/이미지·Service/Endpoint·Pod UID/restart/resources·Node Ready·MON 전체/앱 target 집합,
   edge01/control01 chrony와 시각을 읽는다. drift·누락이면 POST0건으로 중단한다.
2. DB 담당자가 db01의 기존 콘솔에서 새 `SIM_load_<RUN>_` prefix가0행인지 READ ONLY로 확인한다.
   prefix는 SQL `LIKE`의 `_` wildcard를 쓰지 않고 `left(account_id,length(prefix))=prefix`로 대조한다.
   DB 식별·시각·rc를 함께 기록한다. 기존 시험 데이터 삭제는 하지 않는다.
3. 새0700 OUT_DIR에 criteria(결정/승인 링크 포함)와 고정 `promql.txt`·도구 SHA를 기록한다.
   승인된 관리 경로로 Q1/Q2/Q3 사전 조회 및 Pod 이름/label을 확인한다.
   q_range.py의 localhost19091 포트는 **이번 회차 소유의 승인된** Prometheus port-forward에만 연결한다.
   다른 프로세스의 리스너를 재사용하거나 종료하지 않는다.
4. `python3 gen3.py <RUN> <OUT_DIR> --profile regression`을 **1회** 실행한다.
   B20rps120초→P50rps120초→무부하120초, 요청 timeout10초·최대 inflight64를 유지한다.
   Python 종료코드와 stages.log·requests.log·regression-attempt.json을 보존한다.
5. 기존 Q1~Q3를 `query_range(start=B시작-60초,end=idle끝,step=15s)`로 수집한다.
   CPU/throttle은 각 구간 시작+60초부터 끝까지의 유효 point만 사용한다.
   메모리는 B시작~idle끝 전체, workload별 Pod 최대다. query를 사후 바꾸지 않는다.
6. DB prefix 집계·save/eval delta·Pod/Resource/Ready/MON 회복을 대조한다.
   새8,400행은 HTTP201수와 일치해야 하며 기능회귀 RUN과 섞지 않는다.
   기존 생성기는 응답 Transaction ID를 기록하지 않으므로 이 집계를 PR224의 거래ID 1:1 검증으로 표시하지 않는다.
7. 해당 회차 소유의 port-forward/관측 프로세스만 종료하고 리스너 부재·정상 기준선을 확인한다.
   원본·해시·실제 시각·rc·코드/이미지 binding을 새 증적 PR로 편입한다. 독립 리뷰 후 업무 인수 판단을 연결한다.

## 합격과 중단

기존 §8의 합격조건: 201 외 응답·timeout·연결 오류0, Q3 throttle<25%, restart변화0/OOM0,
현재 Resource 초과 징후 없음. 승인 산식은 CPU request=B최대×1.5(50m 올림, 최소100m),
limit=P최대×2(100m 올림), memory request=전구간최대×1.2(64Mi 올림), limit=request×2다.
**경보선으로만 사용하고 Resource를 재산정하지 않는다.** 계획 발사 수는 B2,400/P6,000이며
실제 구간별 수·처리량·발사 지연·몰림을 함께 제출한다. 누락/미완료를 정상8,400건으로 표시하지 않는다.
p95는 기록만 하며 새 latency SLO를 만들지 않는다.

Q1/Q2/Q3의 필수 workload 시계열 또는 유효 샘플이 없으면 NOT_VERIFIED/STOP이다.
Q3 반환 NaN의0 취급은 실제 분모0인 반환값에 한하며 metric 부재에 적용하지 않는다.
구간 point 누락은 개수를 기록한다. 2분 profile은10분 메모리 추세를 증명하지 않는다.

기존 자동중단은 inflight64 포화·단계 종료2초 미배수·30초간 오류10건(마지막 tail포함)이다.
발견 오류1건도 최종 합격에는 실패다. 생성기 rc0을 PASS로 사용하지 않는다.
Pod NotReady/restart·관측 상실·다른 변경·자원 이상이면 현장 관측자가 해당 생성기 PID만 중단하고
잔여 요청 종료/상태를 확인한다. 자동중단은 기존 요청의 timeout 설정을 유지하며 기다린다.
수동 프로세스 종료로 응답 로그가 끊긴 요청은 DB 반영 여부를 따로 조회하고 미확인을0으로 처리하지 않는다.
중단 rc/원본과 영향은 그대로 남기며 반복·다음 단계 강제·보안통제 해제·DB삭제를 하지 않는다.

시험은 배포/설정 변경이 없어 정상 종료 때 되돌릴 앱 설정은 없다.
부하 중단 후 서비스가 회복하지 않으면 지정 콘솔 담당자가 상황을 인수한다.
이전 digest 배포는 자동복구 범위가 아니며 업무 metrics 노출을 되살리므로 별도 구체 판단이 필요하다.
실패 시 full sizing 재시험은 기존 승인상의 후속이지만 새 회차/창·원인/정상 복구 확인 전 자동 실행하지 않는다.

## E2E Defect/검증 공백의 현재 대조

기준: 2026-10-14 GitHub 원본. 원래 [D-01~D-06 표](https://github.com/321Team/fds-project-baseline/issues/20#issuecomment-5980751335)와
[QA 한정 수용](https://github.com/321Team/fds-project-baseline/issues/20#issuecomment-5989190539)을 유지한다.
아래는 현재 입력 대조이며 새 Severity·위험수용·수신 책임·Due를 승인하는 표가 아니다.

| 항목 | 현재 증적과 남는 범위 |
|---|---|
| D-01 local endpoint | 최종 Deploy219·HA221의 분산 복구, Probe223·회귀224의 Worker별1/1 확인. 해당 회차에서 해소; 미래 자동 재분산 보장은 아님 |
| D-02 감시 공백/통보 | cluster IF05C Discord 성공과 외부 monitor01 IF24 통보 부재·worker03 장애영역을 구분. MON#17의 잔존 제한 처분은 미완료 |
| D-03 실패 경로 | [기존 재사용 문서](https://github.com/321Team/fds-project-baseline/blob/ab87d83304e9af5e39770e9322113a22204dd181/governance/handoffs/phase1-execution-20261010/HTTP_PROBE_REUSE_20261013.md)에 따라 DB readiness66·engine 연결실패90/CR119를 재사용. read timeout·오류 응답·DB 저장 실패 rollback/500은 이 자료로 새 Runtime 검증되지 않음 |
| D-04 Client→edge | [증적169](https://github.com/321Team/fds-project-evidence/pull/169)의10/8 실제 PC거래 `cf7bb84b-370b-4d0f-abaf-5a1ea2964b6e`·DB1행·save+1 및 N1 차단 존재. 10/14의 새 이미지 Client 경유 POST는224에 없음. 당시 경로와 현재 정상 NodePort 회귀를 구분해 최종 재사용/영향 판단 |
| D-05 DB 통제 | [DB#11 사용자 최종 인수](https://github.com/321Team/fds-project-baseline/issues/11#issuecomment-6159292006) 완료. W4 NOT_MEASURED·새 패킷/다른 Namespace 전수 미검증 유지; SEC 전체 인수는 별개 |
| D-06 provenance | TBS217→Push218→Deploy219→HA/Probe/회귀224의 affbc69·두 최종 digest 연결 확보. 과거 이미지의 불명 provenance를 소급 수정하지 않음 |
| I01 | naive02:30→이번DB11:30+09, 탐지false/skippedfalse의INFO 유지. 명시offset 사용 권고, 계약 명문화 후보. 자동 PASS/새 정책/Phase2 이관 승인 아님 |
| 축약 부하 | 기존 승인 §8의 새 이미지 Gate 미실행. 이번 코드·카드는 준비 단계 |

Critical0은25건 FAIL0이나 open issue의 라벨 검색으로 확정하지 않는다.
위 잔여/현재영향·Severity·처분과 축약 회귀 결과를 종합한 뒤 #20의 미체크3줄 및 APP 최종 인수를 판단한다.
PR224·DB#11의 이미 완료된 인수를 되돌리지 않으며 전체 APP/E2E를 지금 종결하지 않는다.
