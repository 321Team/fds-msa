# apko lock: 재현 검사와 신선도 검사 분리

관련: [MSA PR14](https://github.com/321Team/fds-msa/pull/14), [P1-CICD-01](https://github.com/321Team/fds-project-baseline/issues/16), [LOCK_DRIFT_DIAGNOSTICS.md](LOCK_DRIFT_DIAGNOSTICS.md).

## 왜 바꾸나

두 workflow는 실행할 때마다 rolling Wolfi index로 lock을 다시 만들고, 커밋된 lock과 바이트가 다르면 실패했습니다. 2026-10-06~07 사이 12시간 동안 상류가 세 번 바뀌었습니다(openssl 4.0.3-r2→r3→r4, glibc 2.44-r7→r8). 그래서 lock 갱신 PR이 리뷰·병합되는 사이에 main 공급 CI가 다시 깨졌습니다. 이 방식에서는 "공급물이 재현되는가"와 "상류가 바뀌었는가"가 한 검사에 섞여 있습니다.

## 바꾼 뒤

| 검사 | 성격 | 내용 |
|---|---|---|
| lock–YAML 결속 | **차단** | `tools/check_apko_lock_binding.py`: 커밋된 lock의 `config.name`이 YAML 경로와 같고, `config.checksum`이 YAML 바이트의 `sha256-<base64>`와 같으며, 패키지가 1개 이상 |
| 재현성 | **차단(유지)** | 커밋된 lock으로 2회 빌드한 OCI 바이트 동일(`cmp`), runtime UID/GID, 앱 import/livez, Trivy HIGH 0 / CRITICAL 0 |
| 신선도 | **비차단(관측)** | 같은 실행에서 현재 상류로 lock을 다시 만들어 비교. 다르면 `::warning`과 `APKO_LOCK_FRESHNESS=DRIFT_NOT_BLOCKING`(supply), `APKO_REPO_LOCKFILES_MATCH=DRIFT_NOT_BLOCKING`(후보)으로 남기고, 원문·diff는 기존 진단 artifact(supply)와 job 로그 diff(후보)에 보존 |

- 공급물과 후보 이미지는 **커밋된 lock으로만** 만듭니다. 상류 변경은 검토된 lock 갱신 PR로만 반영합니다.
- 진단 수집기(`check_apko_lock_drift.py`)는 그대로입니다. 종료코드 1(DRIFT)은 기록하되 job을 막지 않고, 2(INCOMPLETE)와 그 밖의 실패는 계속 막습니다.
- 저장소에 lock이 없을 때(`NOT_YET_PINNED`)의 후보 동작은 기존과 같습니다(생성 lock으로 빌드).

## 보안 영향과 보완

- 상류 보안 갱신이 자동으로 들어오지 않습니다. 대신 매 실행 DRIFT 경고와 진단 원문으로 변화를 알 수 있습니다.
- HIGH/CRITICAL 게이트는 커밋된 lock으로 만든 실제 이미지에 그대로 적용됩니다.
- DRIFT가 보이면 APP Lead가 lock 갱신 PR을 열고, 후보 검증(정확한 HEAD dispatch)을 거쳐 반영합니다. 이번 변경 후에는 그 PR이 리뷰되는 사이 상류가 다시 바뀌어도 main 공급 CI가 깨지지 않습니다.

## 남는 위험

- 커밋된 lock이 가리키는 apk 파일이 상류에서 삭제되면 빌드가 실패합니다. 이것은 패키지 보존소(별도 설계, 미도입)로만 막을 수 있으며, 이 변경은 그 위험을 늘리거나 줄이지 않습니다.
- 결속 검사는 lock이 그 YAML로 만들어졌다는 기록을 확인하는 것이며, lock 안의 패키지 선택이 그 시점 상류와 같았음을 증명하지 않습니다. 그 증명은 lock 갱신 PR의 생성 원문(호스트·시각·명령·SHA)이 맡습니다.

AI usage: CLAUDE_ASSISTED.
