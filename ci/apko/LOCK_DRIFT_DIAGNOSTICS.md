# apko lock 비교 실패 원본 수집

관련: [MSA PR14](https://github.com/321Team/fds-msa/pull/14), [P1-CICD-01](https://github.com/321Team/fds-project-baseline/issues/16).

main `881fce03e14862ff8f78489390227bd83325af8b`의 supply Run37481990071/job112332207451는 builder lock byte13689/line407 비교에서 실패했다. 당시 생성 lock 원문과 artifact가 없으므로 정확한 package/version delta를 판정할 수 없다. 이 보완은 이후 실행의 원본을 남긴다. 과거 실행 원문을 복구하거나 재현한 것으로 표시하지 않는다.

(#19 병합 당시) 기존 두 `apko lock`, repo lock의 `cmp`, OCI 이중 빌드의 `cmp`와 실패 중단을 유지했다. **이후 변경([LOCK_FRESHNESS_POLICY.md](LOCK_FRESHNESS_POLICY.md), [DEC-P1-IMG-01 변경 결정](https://github.com/321Team/fds-project-baseline/issues/110#issuecomment-6030105982)):** 빌드 입력은 repo lock이며, repo lock↔생성 lock `cmp`는 비차단 신선도 관측이다. 이 collector는 그 원본을 그대로 남기고, 종료코드 1(DRIFT)은 기록만 하며 2(INCOMPLETE)는 계속 실패로 처리된다. OCI 이중 빌드 `cmp`의 실패 중단은 그대로다. GitHub hosted Ubuntu job에서 Build step이 시도되면 성공/실패 후 collector를 실행하고, 그 수집 성공/실패와 별개로 고정 upload-artifact action으로 전용 디렉터리를 보관한다. credentials, checkout 전체, apko 실행파일, OCI 본체, wheelhouse를 이 진단 artifact에 포함하지 않는다.

artifact: `apko-lock-diagnostics-<SOURCE_SHA>-<run_id>-<attempt>` (보관7일). `RESULT.json`에는 source/tool SHA, apko 버전/archive SHA, run/attempt, Build step outcome, 수집 시각·collector SHA 및 입력 파일 SHA가 있다. source SHA는 workflow가 검증한 exact checkout이다. builder/runtime의 repo·generated lock와 YAML6개, 두 unified diff, SHA256SUMS를 보관한다. 생성 중단 시 가능한 원본을 남기며 누락을 INCOMPLETE로 기록한다.

collector exit0=MATCH(두 유효 lock의 바이트 동일), exit1=DRIFT, exit2=INCOMPLETE. MATCH는 lock 비교에만 해당하며 Build step 실패·supply·delivery 성공을 뜻하지 않는다. artifact 해시 일치도 무결성 확인이다. 수집·upload 실패를 continue-on-error로 숨기지 않는다.

Job 강제 취소나 Runner 상실 시 수집 완료를 보장하지 않는다. 실제 artifact 존재와 manifest/readback을 확인해야 한다.

APP 생산 담당은 원본 두 lock의 package/URL/hash 차이를 검토하고, 필요하면 별도 lock 갱신 PR에 반영한다. CICD 소비 담당은 검토된 exact source의 새 supply GREEN과 scan/manifest를 확인한다. 승인된 옛 공급물·Harbor digest·현장 적용 조건을 자동 변경하지 않는다. 현재 lock 갱신, cmp 우회, Harbor Push, K8s Deploy, Runtime GO는 수행하지 않는다.

로컬: `python3 -m unittest discover -s tools/tests -p 'test_apko_lock_drift.py' -v`. CI에서 전체 source checks와 기존 시험도 실행한다. 실패한 main run을 무조건 rerun하지 않고, 진단 보완 PR의 새 head/tool과 base/source를 분리해 기록한다. 이전 run과 이후 관측의 차이를 구분한다.

복구: source-only 보완은 검토된 revert PR로 되돌린다. 서버 변경·원복 대상은 없다. 원본 FAIL을 유지하며 해당 원본을 소비할 수 있을 때까지 PR14의 main supply GREEN 조건은 미충족이다.

AI usage: CODEX_ASSISTED.
