# 정본 대응과 저장소 책임

기준 확인: 2026-09-17 KST. 발행 정본 `docs-v3.1.18`, 승인 source `72599ae49342b0fb8dbd3d8ee60314afb9f907bb`. 이 문서는 정본을 새로 발행하거나 기존 Decision·AC를 변경하지 않는다.

| 정책 | 직접 근거 | 적용 성격 |
|---|---|---|
| Private, reviewed PR, 독립 Reviewer, 수동 merge, CI 미실행 표기 | [RELEASE_POLICY §1·§4·§5·§6](https://github.com/321Team/fds-project-baseline/blob/121fb744f0d816b3910a0bb07cf2bbe0d8883a16/governance/RELEASE_POLICY.md) | 정본의 보상 통제를 이번 신규 소스 운영에 적용 |
| Lead 구현 → Support 영향/보안/운영 검토 → 증적·승인 후 Done | [Baseline §3.4·§17](https://github.com/321Team/fds-project-baseline/blob/72599ae49342b0fb8dbd3d8ee60314afb9f907bb/baseline/FDS_Project_Implementation_Baseline_v3.1.18.md) | 기존 티켓 lifecycle/인수 조건 유지 |
| 기존 운영 담당과 정본 승인 역할 구분 | [Baseline §3](https://github.com/321Team/fds-project-baseline/blob/72599ae49342b0fb8dbd3d8ee60314afb9f907bb/baseline/FDS_Project_Implementation_Baseline_v3.1.18.md), [Identity Map](https://github.com/321Team/fds-project-baseline/blob/121fb744f0d816b3910a0bb07cf2bbe0d8883a16/governance/GITHUB_IDENTITY_MAP.md) | 기존 역할 유지, 권한 변경 없음 |
| 중앙 Delivery와 단순 소스 검증 분리 | [Baseline §5·§10](https://github.com/321Team/fds-project-baseline/blob/72599ae49342b0fb8dbd3d8ee60314afb9f907bb/baseline/FDS_Project_Implementation_Baseline_v3.1.18.md), [병합된 infra-cicd README/운영 기준](https://github.com/321Team/infra-cicd/blob/90f2f37d9e1ab77252b50e80bca339cfef48bd51/README.md) | Runner 접근 확대 없음 |
| 3개 저장소 이름, snapshot-copy, 폴더, 브랜치 접두어 | 이번 사용자 개설·정본 기준 정책·이관 요청 | 이번 운영 세칙, 정본의 원문 강제 사항으로 표시하지 않음 |

## 해당 저장소의 필수 경계

- 책임: P1-APP-01 [#15](https://github.com/321Team/fds-project-baseline/issues/15), [Baseline §7·D18/D34](https://github.com/321Team/fds-project-baseline/blob/72599ae49342b0fb8dbd3d8ee60314afb9f907bb/baseline/FDS_Project_Implementation_Baseline_v3.1.18.md). Lead 이재환, Support/Review Owner 이하영. 앱 instrumentation·계약·Dockerfile·앱 전용 manifests/tests와 앱 스키마 migration을 소유한다.
- 업무 포트는 API 8000 / engine 8001, metrics는 9091 / 9090, Probe는 /livez·/readyz다. 외부 진입 Service80→8000, edge01 제한 NodePort30080, externalTrafficPolicy Local 및 해당 Worker의 local endpoint를 유지한다. DB/FDS 장애 readiness503·endpoint 제외와 liveness 재시작 루프 부재를 실제 검증한다.
- fds-engine은 내부 노출만 허용하고 metrics는 클러스터 Prometheus에서 수집한다. 업무 서비스 노출과 metrics 경로를 혼동하지 않는다.
- 현재 탐지·기록·관측을 유지한다. DEC-P1-FDS/TXN/ADMIN의 승인된 기능 확대 유예에 따라 보류/해제/거절 API·상태 컬럼·운영 UI·새 역할/세션 정책을 이번에 추가하지 않는다.
- 이관된 DRAFT 계약·fail-open·DB 실패·시간대·Rule 구현은 현재 소스의 상태다. 이관이나 unit PASS가 정책 승인·Schema drift 해소·실제 DB/E2E 인수가 아니다. 호환성 파괴는 ICR·소비자 영향·회귀 검증을 거친다.
- 클러스터 PSA/RBAC/NetworkPolicy/HostEndpoint는 P1-SEC/infra-kubernetes, edge01/API LB는 infra-lb, DB 서버 운영은 infra-db, 중앙 Test/Build/Scan/Push/Deploy는 infra-cicd 책임이다. 앱 담당의 인계 책임과 실제 보안 정책 생산 책임을 구분한다.
- 기존 혼합 K8S manifests는 references에 보관한다. 미병합 infra-kubernetes PR #7을 승인된 앱 소스로 편입하지 않는다. 새 destination merge SHA와 소비자 변경 PR 검증 전 기존 중앙 CI의 승인 source pin을 바꾸지 않는다.
- Phase 2는 동일한 두 앱의 AWS/ROSA 배포와 조건부 OCI Relay 연계다. 저장소 분리를 이유로 플랫폼·업무 사양을 확대하지 않는다.

## 이관의 판정 범위

정본 AC의 값·담당·기한·상태를 변경하지 않는다. 초기 이관은 출처·무결성·의존성·비밀정보·적용 가능한 소스 검증과 독립 검토로 판단하며, 미실행 CI/Runtime은 각각 그대로 기록한다. 상세 Gate는 [운영 정책](POLICY.md)을 따른다.
