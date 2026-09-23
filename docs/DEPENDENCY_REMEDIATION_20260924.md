# 앱 취약점 개선 후보 — 2026-09-24

**후보 구현·로컬 검증 완료 / 독립 코드 리뷰·실제 이미지 Build/Scan 대기.**
책임: [P1-APP-01](https://github.com/321Team/fds-project-baseline/issues/15) 앱 Lead 이재환, Support 이하영; [P1-CICD-01 #11](https://github.com/321Team/infra-cicd/issues/11) 인계 담당 이권욱.
사용자 “착수” 지시에 따른 Codex 보조 구현이며 역할·승인권·운영 Source를 변경하지 않는다.
기준 Source: `5b35fdbd8293e258daaad56d3e535721ca3c90ff`. 변경 분류는 의존성·lock·Dockerfile·시험을 포함한 코드 변경이다. Pre-check 예외 대상이 아니다.

## 문제와 변경

기존 Run35683010080/1은 transaction-api HIGH57/CRITICAL3으로 BLOCK됐고 fds-engine은 NOT_SCANNED였다.
현재 승인 Source ec69b67067decf35abbfed0a6a99f3073132787b와 새 후보를 구분한다. 아래 변경만으로 기존 BLOCK이나 Runtime AC1/10, Delivery NOT_VERIFIED를 상향하지 않는다.

- 두 서비스: FastAPI 0.115.5 → **0.141.1**, Starlette 0.41.3 → **1.7.0**. Starlette를 roots에도 명시한다.
- 새 전이 의존성: annotated-doc **0.0.2**, typing-inspection **0.4.2**. 나머지 기존 lock의 버전·wheel hash는 보존했다.
- Linux x86_64 CPython3.12.14/glibc2.39에서 wheel만 내려받아 runtime/test 4개 lock·inventory를 재생성했다. PyPI의 파일명·size·SHA256·non-yanked와 실제 **31개 고유 wheel**을 대조했다.
- 두 Dockerfile은 공식 Python3.12.14 slim-trixie의 아래 **linux/amd64 manifest digest**로 변경한다. 오프라인 설치·hash 강제·pip check·USER/포트/실행 명령은 보존한다.
- 두 .trivyignore의 과거 perl CVE3개 제외값을 제거한다. 중앙 HIGH/CRITICAL 차단·빈 ignorefile·ignore-unfixed=false 기준을 완화하지 않는다.
- 기존 시험32개에 회귀8개를 추가한다. 앱 업무 구현·DB migration·배포 manifest·CICD config는 변경하지 않는다.

공식 버전 선언: [FastAPI](https://github.com/fastapi/fastapi/blob/0.141.1/pyproject.toml), [Starlette](https://github.com/Kludex/starlette/blob/1.7.0/pyproject.toml).
FastAPI는 Python>=3.10 / Starlette>=0.46.0 / Pydantic>=2.9.0이고, Starlette는 AnyIO>=4,<5다. 기존 Pydantic2.9.2·AnyIO4.15.1 유지 상태에서 아래 실제 설치·시험을 수행했다.
선택 버전은 기존 Starlette 탐지의 수정 경계 이후지만, 새 취약점 DB 기반 전체 이미지 PASS는 아직 아니다.

## Base와 공급 식별

- 조회 태그: `docker.io/library/python:3.12.14-slim-trixie` (태그는 조회용이며 Dockerfile은 digest로 고정).
- registry 조회: `2026-09-23T20:14:58.075201+00:00`.
- amd64 manifest: `sha256:44ff437bba879d4941b710a369a8f19266aea34b29002807f0c487fabc9eec9b`.
- config: `sha256:9e87977b867847e186d066f531ef783b006d582a985c341c269446088d90f2c4`.
- OCI archive: `e1addec5df8ab8583c4900fa1cd928626b2949e8184838c7d0b6119a5e9bc62e` / 43,264,000 bytes.
- 공식 Dockerfile Source: [688a0b86bb44289df16a363e9f41d90514c1a5f9](https://github.com/docker-library/python/blob/688a0b86bb44289df16a363e9f41d90514c1a5f9/3.12/slim-trixie/Dockerfile).
- manifest/config·압축 layer4개 SHA256·size와 비압축 diff ID4개를 재계산했다. 원 registry JSON/압축 바이트를 보존해 단일 이미지 OCI archive를 구성했다. 이미지를 실행하거나 rebuild한 것이 아니다.

| 프로필 | wheel 수 | requirements lock SHA256 |
|---|---:|---|
| transaction-api-runtime | 27 | `9b5a3908c2c35af01a1faf5dedfa210f96a3065302d5987f254f11509ca2d913` |
| transaction-api-test | 31 | `ccb967c96ea09cb7fcb4d2a7a642c51c84054e5ecd963845fb6a1a14f4b0e9c8` |
| fds-engine-runtime | 20 | `c4270a4dbc5fc3423cdde700053bfd55e27b464014ed5145d040c1bd99c4e665` |
| fds-engine-test | 28 | `0ac2af171d81946c116017125d8695ccb38dce85740db808fd31edba07c8b9c3` |

기존 공급 경로·60분 다운로드 허용·Runner의 온라인 경로를 재사용하지 않았다. Codex의 별도 로컬 작업 공간에서 공개 upstream을 조회했다. 서버 전송·운영 공급 경로 채택·source/config 승인·변경은 미수행이다.

## 검증 결과

| 단계 | 실제 결과 | 범위·제한 |
|---|---|---|
| STATIC | PASS | 원본73파일 blob 대조, 변경 후 UTF-8/AST/YAML/JSON·제한 credential pattern·diff 공백 검사 |
| 의존성 | 4/4 PASS | 새 venv별 --no-index --only-binary=:all: --require-hashes 설치와 pip check. hash는 실제 다운로드 바이트에서 산출 |
| MOCK/UNIT | **40 PASS, skip0** | transaction-api14, fds-engine26; Python3.12.14/Linux x86_64 |
| 공급·소스 대조 | PASS | infra-cicd de6289f995da751ccfa1b343807ec1b3beb0a50c의 offline_supply.stage/validate_source/verify_staged. local candidate record와 최소 config fixture 사용; 운영 config 변경 아님 |
| CI | PR Checks에서 별도 확인 | 해당 HEAD/Run으로 판단, 로컬40PASS를 CI로 표시하지 않음 |
| RUNTIME | NOT RUN | OCI import·최소 Build·실제 앱 두 이미지 Build/Trivy Scan·DB/E2E·Push/Deploy 미실행 |
| REVIEW/MERGE | PENDING / NOT_DONE | 작성자 외 독립 코드 리뷰 후 Lead 판단 |

추가 회귀는 양쪽 JSON/OpenAPI, API 정상 저장 응답·mock commit, 실제 call_fds_engine 함수의 모의 timeout/fail-open, 모의 DB 쓰기 실패500·rollback, 잘못된 JSON의 422와 외부 처리 미호출을 확인한다.
실제 DB 저장·클러스터 네트워크·metrics listener 바인딩·실제 engine timeout 시험이 아니다. 기존 fail-open 업무 계약을 새로 승인하지 않는다.
각 앱은 httpx TestClient 사용에 대한 Starlette deprecation warning1건이 있다. httpx0.27.2 호환 시험은 PASS이며 httpx2 전환은 이 변경 범위에 포함하지 않았다.

## 다음 실행과 중단·복구

1. 앱 Lead/독립 검토자가 본 PR의 정확한 HEAD·전체 변경·시험 결과를 검토한다. 최종 병합 Source SHA와 시험 범위·실행 판단을 #11에 인계한다. 현재 HEAD를 운영 승인 SHA로 미리 등록하지 않는다.
2. 승인된 격리 Linux/공급 위치에 후보 묶음을 **새 디렉터리**로 전달하고 외부 SHA256 및 내부 SHA256SUMS를 확인한다. Python3.12/Linux amd64·승인 Podman 경계가 필요하다. 기존 공급 폴더를 덮어쓰지 않는다.
3. 기존 공급 소비기에서 실제 대상 경로·4프로필·requirements4개·OCI identity를 검증한다. 로컬 record의 scratch 경로는 운영 입력이 아니다. 새 base의 Podman load/inspect와 기존 최소 Build 검증을 수행한다. Codex 환경에는 Docker/Podman이 없어 이 단계는 미실행이다.
4. 최종 앱 SHA·실제 공급 경로/바이트·base digest가 확정되면 별도 CICD config PR을 독립 리뷰한다. 새 config에는 본 묶음의 실제 hash와 검증한 경로만 기록한다.
5. 승인한 Source/config에서 Test→Build→Scan을 수행한다. 신규 API 회귀 파일도 해당 Contract 명령에 포함한다. 현행 명시적 시험 목록에 없으면 config PR에서 보완한다. 첫 이미지가 BLOCK이면 fds-engine은 NOT_SCANNED로 기록하고 차단을 우회하지 않는다.
6. HIGH/CRITICAL·DB/스캐너 오류·hash/platform/source 불일치·설치/시험 실패는 중단한다. 현재 운영 config와 승인 Source를 유지하고 실패 로그를 보존한다. Push/Deploy·Harbor/Pod digest·복구 인수는 후속 범위다.

병합 전 복구는 후보 보류다. 병합 후 결함이면 코드 revert PR과 소비자 pin을 함께 검토하며, 과거 취약 버전을 안전한 배포본으로 간주하지 않는다. 현재 운영 서버 변경이 없어 이번 작업의 서버 rollback은 없다.
독립 증적 편입 [PR22](https://github.com/321Team/fds-project-evidence/pull/22)는 별도다. 본 작성자 검증을 독립 증적 승인으로 표시하지 않는다.
