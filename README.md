# fds-msa

transaction-api / fds-engine의 소스, Dockerfile, unit/contract tests, 앱 데이터 migration 및 계약을 관리한다.

**상태: 병합된 앱 소스의 조직 저장소 이관 PR. 정본 배포·업무 계약 승인·Runtime 인수 완료가 아니다.**

| 경로 | 역할 |
|---|---|
| `transaction-api/`, `fds-engine/` | 원본 main의 앱 코드·Dockerfile·tests |
| `alembic/`, `database/`, `app/` | 앱 소유 스키마/모델·migration. DB 서버 구축은 infra-db |
| `docs/transaction-api_fds-engine_contract_v1.0.md` | 원본 DRAFT 계약, 새 승인으로 승격하지 않음 |
| `references/upstream/kubernetes/` | 기존 앱·혼합 security manifest의 검토용 snapshot. 정본 배포 입력 아님 |
| `references/upstream/ci.yml.txt` | 기존 k3s/self-hosted 자동 배포 Workflow 원문. 실행되지 않음 |
| `docs/POLICY.md`, `docs/MIGRATION.md` | 운영 정책, 출처 및 전환 조건 |

업무 Lead는 이재환, Support는 이하영(P1-APP-01 #15)이다. 이번 저장소 이관 작성·최종 판단은 이권욱, 독립 검토는 이하영을 기준으로 하며 실제 승인 기록은 PR에서 확인한다.

정본의 업무 8000/8001, metrics 9091/9090, /livez·/readyz를 유지한다. 기존 main에 병합된 전용 metrics listener(PR #5)를 포함했다. 테스트의 성공은 fail-open/DB 실패·시간/Rule·스키마의 미확정 계약 승인이나 정본 E2E 성공을 의미하지 않는다.

Monitoring 전체는 [infra-monitoring](https://github.com/321Team/infra-monitoring), CA는 [infra-pki](https://github.com/321Team/infra-pki), 중앙 build/scan/승격은 [infra-cicd](https://github.com/321Team/infra-cicd)가 소유한다. 앱 instrumentation과 앱 전용 metrics 계약은 여기 남긴다. 기존 CI consumer의 source pin은 아직 변경하지 않았다.

## 로컬 시험

각 서비스 디렉터리에서 별도 Python 3.12 venv를 만들고 `python -m pip install -r requirements-test.txt`, `python -m pytest -q`를 실행한다. transaction-api fixture는 테스트용 localhost URL을 사용하고 DB readiness는 mock한다. 실제 DB·클러스터 연결이나 배포를 하지 않는다. 런타임 이미지에 test 의존성을 추가하지 않는다.

## 정본에 따른 운영 결정

[운영 정책](docs/POLICY.md)과 [정본 대응·책임 경계](docs/CANONICAL_POLICY.md)를 적용한다. Private/main을 유지하고, 이번 소스 이관은 로컬 검증 증적과 독립 검토 후 수동 병합으로 판단한다. Actions 활성화는 이관의 새 필수 AC가 아니며 CI 미실행은 NOT RUN으로 기록한다. 중앙 Delivery는 기존 infra-cicd 전용 Runner 경계를 유지한다.
