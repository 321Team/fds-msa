# CICD 오프라인 Build 입력 후속안 — 2026-09-17

[소스 이관 PR #1](https://github.com/321Team/fds-msa/pull/1)은 2026-09-18 09:57 KST에 병합됐다.
이 후속 PR은 main `c25ebd6b2307ee4f9c4801ca5f991302ae14eff0`을 반영하고 main을 대상으로 검토한다.
이관 시점의 앱27파일은 기존 공개 Source254b822와 일치했고, 이번 입력 변경은 아래6파일에 한정한다.
이관 이후의 09-18 Lead 위임 정책 문서5개는 main과 동일하게 보존한다.
독립 리뷰는 코드/실행 설정 병합에 적용하며, 병합된 코드의 실행·증적 수용은 해당 Lead가 판단한다.

## 변경 이유와 범위

기존 두 Dockerfile은 가변 base 태그와 온라인 pip 설치를 사용하여 중앙 오프라인 소비 경로에 맞지 않았다.
이미 Runner에서 확보한 동일 base digest와 네 프로필의 hash lock을 반영한다.

- Dockerfile2개: 고정 linux/amd64 manifest, `python-wheels` 추가 Build context,
  `--no-index --only-binary=:all: --require-hashes` 설치와 `pip check`.
- lock4개: 기존 검증 공급물의 바이트 그대로. 새 의존성 버전을 재해결하지 않았다.
- 기존 requirements4개, 앱 코드·테스트·run.py, UID10001, API8000/9091 및 engine8001/9090은 그대로다.
- 기존 단독 `docker build .` 사용자는 추가 context 없이는 이 Dockerfile을 빌드할 수 없다.
  이 입력은 [infra-cicd PR #19의 소비 경로](https://github.com/321Team/infra-cicd/pull/19)와 함께 검토한다.
  원격 pull 또는 온라인 설치로 실패를 우회하지 않는다.

Base reference:
`docker.io/library/python@sha256:2fe5997d249a808b8eeea52c58a1dbffbba28754dc11699ef5c029f2d818ce79`

| 파일 | 항목 수 | SHA256 |
|---|---:|---|
| transaction-api/requirements-runtime.lock | 25 | `3a71d0d227415f3f818642b5370920f02a23a9bcb28f4dd31aac1d59d96c756e` |
| transaction-api/requirements-test.lock | 29 | `72137816616e16e2b88f86630c507800414c3b37c14c7f624b9042fd66a8ef85` |
| fds-engine/requirements-runtime.lock | 18 | `c9d6138da341b431f0b7fdaf4aee78d59f9207e9d3f2bf4636b0505681c1f80b` |
| fds-engine/requirements-test.lock | 26 | `3a51dbbb6dd56d09658f0d2343e4b4847394f006f1f2aa082886bc468e797b65` |

출처: [CICD 인계 후보](https://github.com/321Team/infra-cicd/tree/20474c3d671fa19f8a2c718d6d10d429cc190994/handoff/offline-app-20260917),
[공급 수신 기록](https://github.com/321Team/fds-project-baseline/tree/7636a609989a91d6f107353b199ebe0857396132/audit/v3.1.19/intake/p1-cicd-supply-20260917T010757Z).
기존 patch SHA256은 `eee3869cb0135769d7da2f3929455aa46ac19b8e185b5770b4cf6e00b782bb02`다.

## 검증 범위

- 변경 전 원격 snapshot68개 blob 일치 및 이관 manifest54개 PASS.
- 이관 후보에 기존 patch의 `git apply --check`와 실제 적용, diff 공백 검사 PASS.
- 변경6파일이 CICD 인계 후보와 바이트 일치. 기존 앱 소스·requirements·시험 파일은 유지한다.
- CICD 소비기의 `offline_supply.validate_source`로 requirements·프로필별 roots·lock·Dockerfile 형식을 대조한다.
  이는 입력 호환성 검사이며 실제 wheel 재설치 또는 이미지 Build가 아니다.
- `tools/check_source.py` 정적 검사를 전체 추적 파일에 수행한다. 결과와 파일 수는 PR 본문에 기록한다.
- `verify_migration.py`는 모듈 설명대로 이관 시점 snapshot 전용이다.
  이 PR에서 변경한 Dockerfile을 원본과 동일하다고 기록하거나 과거 manifest를 다시 쓰지 않는다.
  변경 후 검증은 위 원본 보존/변경6파일 대조로 수행한다.
- 이 환경에 앱 pytest 의존성은 설치되어 있지 않았으며, 실제 wheel 원본·Podman 실행은 수행하지 않았다.
  새 앱 pytest·Build·Scan은 NOT RUN이며 과거32개 앱 시험이나 공급 설치 PASS를 새 Source의 결과로 승계하지 않는다.
- 저장소 Actions 비활성 운영 결정은 유지한다. 이 PR의 CI=NOT RUN이며 새 Runner·Secret을 추가하지 않는다.

## 담당자 회신과 소비자 전환

앱 Lead 이재환은 6개 입력 파일과 시험 범위를 확인하고, 병합된 최종40자리 Source SHA와
내부 Test→Build→Scan 실행 승인 또는 보류를 [CICD Issue #11](https://github.com/321Team/infra-cicd/issues/11)에 남긴다.
독립 코드 검토는 저장소 정책의 작성자 외 검토자로 수행한다.

| 서비스·단계 | 후보 명령·잔여 판단 |
|---|---|
| fds-engine Unit | cwd=fds-engine, `.venv/bin/python -m pytest -q tests/test_rules.py` |
| fds-engine Contract | cwd=fds-engine, `.venv/bin/python -m pytest -q tests/test_health.py tests/test_metrics.py` |
| transaction-api Contract | cwd=transaction-api, `.venv/bin/python -m pytest -q tests/test_health.py tests/test_metrics.py` |
| transaction-api Unit | 앱 담당이 실제 Unit 명령을 인계하거나, 별도 Unit 해당 없음의 구체적 사유·판단자·근거를 명시. 현재 미확정 |

[기존 회신 양식](https://github.com/321Team/infra-cicd/blob/20474c3d671fa19f8a2c718d6d10d429cc190994/handoff/offline-app-20260917/APPROVAL_REPLY.md)을 사용할 때
저장소/Source에는 실제 채택·병합한 값을 기재한다. 이전 승인01758583 또는 미병합 후보 SHA로 대체하지 않는다.

**조직 저장소는 Private이며, 현재 CICD 소비기는 기존 공개 저장소의 익명 HTTPS fetch만 구현한다.**
따라서 이 PR만으로 CICD source repository를 바꾸지 않는다. 조직 저장소 채택 시에는
승인된 읽기 인증 경로·권한/비밀값 미노출·실패 차단을 포함한 별도 소비자 전환 PR과 검증이 필요하다.
기존 공개 저장소를 당장 유지할 경우 같은6파일 patch를 앱 담당이 그 저장소에서 검토·반영할 수 있다.
새 저장소 공개 전환이나 인증 우회는 제안하지 않는다.

## 복구와 완료 판정

병합 전에는 이 후속 브랜치/PR만 보류하면 된다. 병합 뒤 문제가 확인되면 승인된 코드 되돌림 PR과
직전 소비자 Source pin을 기준으로 복구한다. 코드 변경 취소가 서버/이미지 복구 완료를 뜻하지 않는다.
이 PR은 실제 앱 실행 승인·독립 리뷰 완료·배포·티켓 종결을 선언하지 않는다.
