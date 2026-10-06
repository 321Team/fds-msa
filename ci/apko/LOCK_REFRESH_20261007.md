# 2026-10-07 lock 갱신 후보 원본

기준 main/source: `881fce03e14862ff8f78489390227bd83325af8b`.
생산 원본: [진단 PR19](https://github.com/321Team/fds-msa/pull/19) tool9d801f26의 [Run37491203932](https://github.com/321Team/fds-msa/actions/runs/37491203932), job112364098107, attempt1. 실제 수집00:53:10 KST.
artifact11424953180 ZIP SHA256 `c38679d49a3ee81f0cc4c081adb2b49abb058d2e20d23bca5d9ca370e7a9d74b`; 내부9/9 hash 확인, repo lock·config4개는 기준 Git 바이트와 일치. 생성 lock 두 파일을 편집 없이 그대로 반영했다. 이는 이전 failed main Run37481990071의 원문을 복구한 증거가 아니라 새로운 CI 관측이다.

두 lock의 변경 package는 각각 openssl-4.0-libcrypto / openssl-4.0-libssl, `4.0.3-r3 → 4.0.3-r4`다. 버전·URL·control/data byte range·checksum 변경을 묶어 보존했다. package 추가/삭제0, architecture·그 외 lock 필드와 config 유지. app/requirements/Dockerfile·workflow·권한·UID10001:GID999 변경0.

builder old SHA256 `5a30df50da4958b03beec1b2842cb22930c36548a91043b415a0cf1dc68db916` → new `b69b10033534ad012de56f4cd345659f6cbefe1ba267ee7bfeba5e2ede6a5926`.
runtime old SHA256 `dfdca0fc910a2362a2665c36f9c8db523c063860c8803dfae10d756485166d89` → new `cfd07e8f597640371a073c95bc70f1e3ba45af44dcc3e8134d00840b7f0380cf`.

검증 순서: 정확한 새 HEAD의 Source validation → 기존 reusable apko candidate의 lock 재생성 동일성·두 번 OCI 재현·SBOM·앱 smoke·HIGH/CRITICAL0 → 작성자 외 독립 검토. PR offline-supply는 base SOURCE_SHA를 소비하므로 base881fce03 실패를 새 head의 성공으로 바꾸지 않는다. candidate PASS도 병합된 main push supply GREEN을 대신하지 않는다. 실제 CI/리뷰 결과는 PR 기록으로 확인한다. Wolfi index의 다음 drift는 새 원본으로 다시 판단하며 cmp를 우회하지 않는다.

기존 승인 supply/scan/image digest는 새 lock의 실행 결과로 전용하지 않는다. 새 공급물의 소비·Harbor Push·Deploy/rollback은 별도 Gate와 실행창이 필요하다. 이 lock 후보는 발급/배포/Runtime GO·인수·종결 승인이 아니다. APP 생산 책임과 CICD 소비 검증 책임을 기존 티켓대로 유지한다.

관련 [PR14](https://github.com/321Team/fds-msa/pull/14) main supply GREEN 조건은 유지. [#16](https://github.com/321Team/fds-project-baseline/issues/16)/[infra-cicd#11](https://github.com/321Team/infra-cicd/issues/11) 소비 입력의 자동 변경 없음. 복구는 검토된 source revert PR이며 승인된 기존 입력을 보존한다.

AI usage: CODEX_ASSISTED.
