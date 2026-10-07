# 2026-10-07 lock 갱신 — openssl 4.0.3-r4, glibc 2.44-r8

[LOCK_FRESHNESS_POLICY.md](LOCK_FRESHNESS_POLICY.md)의 "DRIFT가 보이면 APP Lead가 3일 안에 lock 갱신 PR을 연다"에 따른 갱신입니다. 현재 main lock(`945e4d3`, author 2026-10-06 22:52 KST)의 3일 상한은 2026-10-09 22:52 KST입니다.

## 생성 원본

- 기준 main/source: `0494ca279882d4e0cab24fb5a25a136a2e8f46c1` (#21 병합)
- 생산: `apko-wolfi-py313.yml` workflow_dispatch [Run 37580146028](https://github.com/321Team/fds-msa/actions/runs/37580146028), job 112657698840, attempt 1, 2026-10-07 15:11:15~15:12:22 KST, 결과 success(`APKO_REPO_LOCKFILES_MATCH=DRIFT_NOT_BLOCKING`, lock-age 16h)
- artifact 11463967354 `apko-wolfi-py313-0494ca279882d4e0cab24fb5a25a136a2e8f46c1-1`, ZIP SHA256 `b4f1e4557b774ef6675ab8a186f04ddcb142084eb4bb0d898956c4ca42b03a38`(API digest와 같음). 내부 `SHA256SUMS` 50/50 OK
- artifact 안의 repo lock 사본 2개는 main 바이트와 같습니다. `apko-input-SHA256SUMS`의 해시는 builder `5a30df50…`, runtime `dfdca0fc…`입니다.
- **생성 lock 두 파일(`*.generated.lock.json`)을 편집 없이 그대로** `ci/apko/*.apko.lock.json`에 반영했습니다.

| lock | 이전 SHA256 | 새 SHA256 |
|---|---|---|
| builder | `5a30df50da4958b03beec1b2842cb22930c36548a91043b415a0cf1dc68db916` | `58888fd8e05517805bc66661ba2d41055093e006d7d11043e2b4f65efbc0cd55` |
| runtime | `dfdca0fc910a2362a2665c36f9c8db523c063860c8803dfae10d756485166d89` | `bfa66e14097be03d6db42b3ebd479aa68d5db802faa2d00cdc72f7b80e3541b3` |

## 변경 package

| package | 이전 → 새 | builder | runtime |
|---|---|---|---|
| openssl-4.0-libcrypto | 4.0.3-r3 → 4.0.3-r4 | ✓ | ✓ |
| openssl-4.0-libssl | 4.0.3-r3 → 4.0.3-r4 | ✓ | ✓ |
| glibc-2.44 | 2.44-r7 → 2.44-r8 | ✓ | ✓ |
| glibc-2.44-locale-posix | 2.44-r7 → 2.44-r8 | ✓ | ✓ |
| ld-linux-2.44 | 2.44-r7 → 2.44-r8 | ✓ | ✓ |
| libcrypt1-2.44 | 2.44-r7 → 2.44-r8 | ✓ | — |

- package 수는 builder 35, runtime 29로 그대로이며, 추가·삭제는 0입니다.
- 변경 package는 version·URL·byte range·checksum을 묶어 바꿨습니다. `contents.packages` 밖의 lock 필드(`config` 포함)는 같습니다.
- `check_apko_lock_binding.py` 결과는 builder·runtime 모두 PASS입니다.
- workflow의 SBOM 필수 package(python-3.13, py3.13-pip, tzdata) 버전은 바뀌지 않았으므로 workflow를 수정하지 않았습니다. app·requirements·Dockerfile·config·권한·UID 10001:GID 999도 변경 0입니다.

## 검증과 경계

- 새 HEAD의 정확한 source로 후보(`apko-wolfi-py313.yml`)와 공급(`apko-offline-supply.yml`)을 dispatch합니다. 기대 결과는 다음과 같습니다.
  - `APKO_REPO_LOCKFILES_MATCH=PASS`·`APKO_LOCK_FRESHNESS=MATCH`. 그 사이 상류가 또 바뀌면 DRIFT 경고가 나지만, 새 lock의 author 시각 기준으로 3일 안입니다.
  - 2회 OCI 동일, SBOM, 앱 smoke/livez, HIGH 0 / CRITICAL 0.
- 이 lock 후보는 기존 승인 공급물·scan·Harbor digest를 대신하지 않습니다. 새 공급물의 소비·Harbor Push·Deploy는 별도 Gate입니다.
- [fds-msa#20](https://github.com/321Team/fds-msa/pull/20)(openssl r4만 반영, glibc r7)은 이 PR로 대체됩니다.
- 복구: source revert PR. 서버 변경은 없습니다.

AI 사용: CLAUDE_ASSISTED
