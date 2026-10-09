# 업무 포트 metrics 라우트 제거

근거: [baseline#15의 포트 분리 요구와 잔여](https://github.com/321Team/fds-project-baseline/issues/15#issuecomment-6052330629), [실제 관측 evidence#175](https://github.com/321Team/fds-project-evidence/pull/175). 2026-10-09 기존 실행본에서 Edge→Worker3대30080/metrics와 transaction-api 네트워크→engine8001/metrics가200이었다. Edge nginx의404는 별도 진입점 통제이며 업무 app 라우트 제거를 대신하지 않는다.

## 변경과 검증 범위

- transaction-api 업무8000, fds-engine 업무8001의 `/metrics` 라우트를 제거한다. 루트 경로·후행 슬래시·URL 인코딩 경로의 GET/HEAD는 redirect 없이404여야 한다.
- 기존 전용 metrics 앱과 동일 프로세스 registry는 유지한다. transaction-api9091 및 engine9090의 `/metrics`는200이고, 업무 카운터 증가가 전용 응답의 실제 수치에 반영돼야 한다.
- `/livez`, `/readyz`, 거래/평가 처리, Service/NetworkPolicy, 포트와 이미지/의존성 lock은 바꾸지 않는다. 기존 main의 logging 수정도 유지한다.
- pytest는 ASGI 계약과 공유 registry를 검증한다. CI 통과를 실제 바인딩·운영 배포·AC 인수로 표시하지 않는다.

별도로 `apko-wolfi-py313` 후보 workflow는 `--network none`인 실제 앱 컨테이너 안에서 `tools/check_listener_isolation.py`를 실행한다. 정상 entrypoint의 업무 `/livez`200, 전용 `/metrics`200과 앱 counter 존재, 업무 `/metrics`·`/metrics/`·`/%6detrics`의 GET/HEAD404·redirect 없음 총8개 조건을 loopback TCP로 확인한다. 시작 대기는 전체30초, 각 요청1초와 본문512KiB 상한이 있으며 최종 오류·예상 밖 응답이면 workflow가 실패한다. JSON에는 본문 대신 hash·상태·길이·시각·요청별 결과를 보존하고 실패 시에도 기존 EXIT trap으로 해당 CI 컨테이너를 제거한다.

이 검사는 컨테이너 안의 실제 listener 경로를 보완한다. 운영 Service/NodePort/NetworkPolicy·DB readiness·거래 저장·여러 replica·카운터 증가의 TCP E2E는 포함하지 않는다. Counter 증가/공유 registry는 별도 ASGI 시험의 범위다. 검사기 회귀시험은 실제 로컬 HTTP fixture로200 노출·redirect·지표 누락·준비 timeout·본문 상한 초과를 검증하며 운영 앱 실행과 구분한다.

## 배포와 원복 인계

실행 위치는 승인된 CI/CD 회차와 정본 클러스터이며, APP Lead가 리뷰·병합된 정확한 Source SHA, Build/Scan 결과, 새 image digest, 대상6개 Pod의 기존 digest/배포 사양, 비중첩 창과 복구 인수를 고정한 후 적용한다. 문서/코드 PR만으로 Push/Deploy를 실행하지 않는다.

1. 현재 전용9090/9091 Prometheus 수집과 업무 health/거래 대조군, 승인 Worker의 local endpoint, 이전 배포 digest를 보존한다. 전용 포트 대신 업무 포트를 scrape하는 소비자가 있으면 먼저 조율한다.
2. 해당 회차의 승인된 배포 절차로 새 digest를 적용하고 Pod imageID와 Source/Run/Attempt를 연결한다.
3. Edge→Worker3대30080/metrics 및 승인 앱 네트워크→engine8001/metrics가404인지 확인한다. Service가 backend 하나만 고르므로 engine 모든 배포 replica의 적용 상태와 필요한 직접 관측 범위를 별도로 고정한다.
4. 전용9091/9090 scrape200·지표 증가, health, local endpoint와 기존 Rule/API→DB 회귀 기준을 확인한다. Edge nginx404도 유지해야 한다.
5. 전용 수집 소실·업무/health 회귀·부분 rollout·예상 외 metrics200이면 다음 승격을 중단한다. 승인된 이전 digest와 배포 사양으로 복귀하고 Pod/endpoint·scrape·업무 대조군을 재확인한다. **이전 digest로 복귀하면 기존 업무 포트 metrics 노출도 돌아오므로 이를 해결 완료로 표시하지 않는다.** 보안 통제를 임의 해제하지 않는다.

Runtime 결과는 새 증적 회차에 시각·호스트·Source/digest·응답·원복을 남겨 독립 편입 리뷰로 연결한다. #15 AC 및 Known Issue 처분은 APP Lead/Review Owner가 판단한다.
