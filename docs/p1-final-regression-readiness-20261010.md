# Phase 1 Final Regression 실행 준비 대조 — 2026-10-10

작성: 이권욱 / CODEX_ASSISTED. 기존 인계값·고정 source·판정 도구를 오프라인 대조한 실행 준비다. 실제 배포/거래/DB/metrics 시험, 원본 수신, 독립 승인이나 AC 완료를 보고하는 문서가 아니다.

## 적용 기준과 코드 범위

- 실행 인수는 [#30 이관 결정](https://github.com/321Team/fds-project-baseline/issues/30#issuecomment-6082618226), 준비/개별 Runtime 구분은 [PR161의 실행 지도](https://github.com/321Team/fds-project-baseline/blob/21e7e6626159dc5e23b49fe6ac5d344bbb4f62fa/governance/handoffs/phase1-remaining-20261009/EXECUTION.md)를 따른다. 이권욱이 인수한 잔여를 준비한다. 새 Lead GO나 모든 담당자 회신을 공통 Gate로 추가하지 않는다.
- [#20 현행 AC/상태](https://github.com/321Team/fds-project-baseline/issues/20)는 Final Regression·Defect 승인 미완료다. 9/29의 24 PASS를 새 후보의 결과로 사용하지 않는다. [#15](https://github.com/321Team/fds-project-baseline/issues/15)의 업무 metrics 분리와 [#119](https://github.com/321Team/fds-project-baseline/issues/119)의 기존 실패 경로는 관련 실제 회차로 구분한다.
- APP 승인 후보 source는 `affbc69beef9967f7977d09a6fec14f7fb6c0e94`, 공급 도구는 `8eac4c982076e3c219840a13686b15c46879981f`다. main `52ab019a58134229a7296a99dbeeba181de94b6c`와의 변경은 Route 설명이며 후보를 자동 교체하지 않는다. 이번 `rg.py` 변경도 APP source/image/digest를 바꾸지 않는다.
- [J02 인계 회신](https://github.com/321Team/fds-project-baseline/pull/160#issuecomment-6082572533)의 기준은 [증적68](https://github.com/321Team/fds-project-evidence/pull/68), 고정 merge `435ab3aeb9944cec9ba5b6b40c1819f8477b8b9a`의 `edge01/criteria.txt`다. SHA-256 `8aad7cc215137b97168230926d0e9655eba4dd3386944bf6efc06bfc83aae8d8`을 실제 bytes로 확인했다.
- 이번 판정 도구 수정은 기존 P1 Rule/22행/metrics 기대값을 낮추거나 재승인하지 않는다. P2 도구·ROSA·IF19·새 기능을 포함하지 않는다. 도구의 독립 코드 리뷰와 이후 증적 리뷰는 구분한다.

## 오프라인 확인과 한계

기존 22개 유효 입력을 승인 소스 `fds-engine/app/rules.py`에 합성 context로 전달했을 때 기대 Rule 집합과 22/22 일치했고 R01/R02/R04/R07 각각 1회였다. 실제 PostgreSQL SQL·시각/경합·통신·저장·metrics 증가를 실행한 시험이 아니다. N06/07의 실제 HTTP422는 새 현장 회차에서 확인한다.

| 항목 | 승인 소스에서 확인한 의미 | 현장에서 확인할 부분 |
|---|---|---|
| R01 | 저장 전 context가 이전 10분 withdrawal 수를 조회. 이전 3건 뒤 4번째 요청이 R01 | 새 계정, 실제 DB 이력/UTC 비교, 10분 안의 실행 |
| R07 | 이전 1시간 transfer count≥3·sum≥2,000,000. 700,000×3 뒤 4번째 요청이 R07 | 실제 3행 합계·저장 및 새 계정의 이력 분리 |
| R04 | offset 있는 occurred_at을 KST로 변환, 01:00≤hour<05:00·amount≥1,000,000 | fixture/DB 저장·표시 시각과 원본 timestamp |
| naive I01 | Rule은 UTC로 간주. naive02:30은 KST11:30이어서 R04 false. API는 naive 값을 driver로 전달 | DB 저장/표시 의미는 미확인. 기존 INFO 유지, 새 정책 채택 없음 |
| 엔진 실패 | connect1초/read2초, httpx timeout/HTTPError 때 저장 fail-open·skipped=true | #119의 실제 장애/복구 회차·HTTP/DB/metric. 정상 회귀 중 skipped는 실패 |
| DB 저장 실패 | 저장 예외에서 rollback/HTTP500, save_failure 증가 | 실제 실패 경로·부분 저장 부재·복구 후 저장과 원본 |
| metrics | 업무8000/8001의 metrics 라우트 없음, 전용9091/9090과 공유 registry 유지 | 실제 replica/imageID·404·scrape200·증가·restartCount |

DB 경로에는 별도 차이가 있다. 후보 lock의 asyncpg0.30.0이 고정한 [driver codec source](https://github.com/MagicStack/py-pgproto/blob/1c3cad14d53c8f3088106f4eab8f612b7293569b/codecs/datetime.pyx#L202)는 datetime을 `astimezone(UTC)`로 변환한다. [Python3.13 문서](https://docs.python.org/3.13/library/datetime.html#datetime.datetime.astimezone)에 따르면 naive 입력은 이 연산에서 시스템 local timezone으로 간주된다. 따라서 **Rule은 UTC 고정, DB encoding은 app 프로세스 local timezone에 의존할 수 있다**는 것이 소스 대조에 따른 해석이다. 운영 column 형상·driver 사용/codec override·프로세스 timezone·실제 저장/표시는 아직 Runtime 미확인이다. DB 서버 표시 timezone과 app encoding timezone도 구분하며 I01을 새 자동 PASS 기준으로 만들지 않는다.

예전 도구는 빈 응답/DB 두 파일의 crosscheck가 rc0이고, 같은 케이스의 뒤쪽 기록이 앞선 실패를 가릴 수 있었다. Rule 목록 누락/정수가 boolean처럼 허용되는 반례도 합성 로그로 확인했다. 수정 도구는 이 입력들을 거부하고 완전한 케이스·고유 Transaction ID·4개 Rule/boolean·도구/기준 결속을 검사한다. 파일 내부 일치는 독립 승인이나 원본의 진위를 대신하지 않는다.

## 실행 단계별 준비와 미확인 입력

| 단계 | 재사용 가능한 것 | 해당 단계 직전에 필요한 것 |
|---|---|---|
| Push | 승인 후보·공급 ZIP/TBS 인계, 기존 Gate 구현 | 현행 scan/Robot/TLS·접근·비중첩·승인 입력. 새 receipt는 성공 Push에서 생성 |
| Deploy/rollback | [증적198](https://github.com/321Team/fds-project-evidence/pull/198)의 10/9 19:21 읽기 관측·입력표 | 리뷰된 workflow/tool SHA, 회차 UUID·SA UID/audience/900초 정책·실제 CA/RBAC·fresh TokenReview, 현행 Deployment UID/generation/container·정확한 target/복귀 Digest·budget·원본/Console |
| Final Regression | 고정 기준·수정 `rg.py`·기존 SQL/PromQL·기능 시험 데이터 보존 결정 | 독립 리뷰된 실제 도구 bytes·새 RUN/그 계정의 DB0행·최종 rollout/imageID·작업창/비중첩·3Worker local endpoint와 실제 health·metrics/Pod/DB 관측 접근 |
| 장애/복구 | #119와 기존 실패/Negative 원본 | 해당 미입증 행만의 고정 대상·주입/정상 기대값·권한·중단/복구·baseline. `rg.py run`은 장애를 주입하지 않음 |
| 최종 인수 | 승인/병합된 과거 증적·현행 AC·기존 인계 | 새 최종 형상 증적의 독립 리뷰·Critical/잔존 보안 판정·필수 제3자 재현/운영 인수 |

증적198은 당시 Deployment Ready3/3 및 Pod6개 관측이다. 현재 health나 rollback 승인으로 사용하지 않는다. 두 target의 `rollback_approved=false`를 보존한다. 새 Token 코드의 MOCK/CI 성공도 실제 900초 발급·소비 가능성을 증명하지 않는다. 900초 요청이어도 실제 잔여가 실행/rollback 예산보다 짧으면 기존 중단을 유지한다.

Delivery 선행조건은 사용하는 Registry의 정상성·인증·승인 입력과 비중첩이다. 격리 Harbor 자동복구 전체 완료를 새로운 Gate로 추가하지 않는다. 같은 Registry의 stop/restart 시험과 Push/Deploy는 겹치지 않는다. U01~03은 필요한 자료 전달/credential 변경에서 소비하며 전체 개발을 막지 않는다.

## 실제 회차의 순서·판정·실패 처리

아래 순서는 현장 실행안에 필요한 항목이다. 지금의 조회·합성 분석을 해당 실행으로 기록하지 않는다.

1. 이권욱은 승인된 도구 revision과 실제 파일 SHA-256, 최종 APP source/digest·deployment/pod UID/generation·작업창과 타 세션 비중첩·승인 복귀값/Console를 고정한다. 이전 digest로 원복하면 업무 metrics 노출도 돌아오므로 그 종료 상태를 미해결로 기록한다. 기존 원본을 덮어쓰지 않는다.
2. db01의 기존 허용 조회 경로에서 새 RUN의 계정이 0행인지 확인한다. `SIM_rg_<RUN>_`의 prefix를 정확히 비교한다. RUN은 KST 분 단위여서 새 OUT_DIR만 만드는 것으로 재전송 안전성을 확보하지 못한다. 기존 RUN/불확정 응답은 보존하고 같은 RUN을 재시도하지 않는다.

   ```sql
   select count(*) from transactions
   where left(account_id, length('SIM_rg_<RUN>_')) = 'SIM_rg_<RUN>_';
   ```

3. control01에서 기존 query의 metrics 원본·시각과 Pod UID/restartCount·Ready/imageID를 수집한다. 전용 scrape200과 업무 metrics404를 구분한다. `rg.py`의 Worker NodePort 경로는 Client→edge 전체 경로의 새 완료 증명이 아니므로 실제 edge 진입점/최종 upstream 관측과 함께 연결한다. Service 한 번의 응답을 engine 모든 replica의 결과로 확대하지 않는다.
4. edge01에서 새 OUT_DIR로 기존 `python3 rg.py run <OUT_DIR>`를 한 번 실행하고 직후 rc를 기록한다. 3Worker `/readyz` 모두200 뒤 요청을 보낸다. 기준과 meta는 요청 전에 생성되고 5xx/연결 실패면 남은 전송을 중단한다. 기본 timestamp를 쓰는 P02/N01 등이 심야에 R04를 추가로 trigger하지 않도록 **KST01:00~05:00 밖에서** 기존 기준 회귀를 수행한다. R04의 명시적 offset fixture는 낮에도 사용할 수 있다.
5. 실제 API 원본 25개 요청 기록을 보존한다. 기존 24개 판정 대상은 PASS, I01은 INFO다. 유효22건은 정상 저장/평가, N06/07은422다. I01이201이면 정상23행,422이면22행이며 전체 counter 기대값도 기존 도구 기준에 맞춰 분리한다. 누락/중복/틀린 Rule을 PASS로 합산하지 않는다.
6. db01에서 같은 RUN의 기존 8열 SQL 결과와 종료 코드·시각을 수집하고 `python3 rg.py crosscheck <OUT_DIR> <DB_LOG>`로 Transaction ID 대조한다. control01에서 후속 metrics·Pod 상태·N08/관련 보안 관측을 수집한다. API rc0만으로 DB/metrics·보안·전체 E2E AC 완료를 선언하지 않는다.
7. metrics의 기대 증가는 유효22건 기준 save_success/fds_evaluated+22, save_failure/missing_client_ip0, Rule각+1이다. I01이 정상 저장되면 save/evaluated는+23이며 Rule 증가분은 실제 I01 결과를 구분한다. 다른 writer가 있거나 Pod restart/교체가 있으면 단순 aggregate delta로 해당 RUN 성공을 단정하지 않고 영향과 필요한 최소 재검증을 남긴다.
8. 실패하면 다음 승격을 중단하고 요청·불확정 Transaction ID·DB 행·metric·실패 형상·rc를 보존한다. 기능 시험 거래는 [#11의 기존 보존 결정](https://github.com/321Team/fds-project-baseline/issues/11#issuecomment-5887795557)을 따른다. 임의 DELETE나 trace/log 삭제를 하지 않는다. 실제 형상 원복은 승인된 Delivery rollback 경로와 budget으로만 수행하고 health/업무·metrics의 종료 상태를 재확인한다.

기록은 STATIC/MOCK/CI/RUNTIME/REVIEW/MERGE/AC를 분리한다. 동일 회차에서 수집하더라도 정상 배포·Negative Gate·rollback·최종 형상 회귀·실패 경로와 각 원본의 귀속을 구분한다. #20 Status·체크박스·승인/유예·담당자를 이 문서나 도구 PR로 변경하지 않는다.
