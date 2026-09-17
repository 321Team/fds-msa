# 저장소 운영 정책

상태: 이관 PR의 정책 제안. PR 병합 전에는 기존 승인 기준과 소스가 유효하다. 이 문서는 실제 GitHub 권한 부여, 보호 규칙 적용, 독립 승인 또는 Runtime 승인을 기록하지 않는다.

## 기준과 책임

- 승인 정본은 [docs-v3.1.18](https://github.com/321Team/fds-project-baseline/releases/tag/docs-v3.1.18), 승인 source `72599ae49342b0fb8dbd3d8ee60314afb9f907bb`와 이후 공식 Decision/CR이다. `CURRENT.md`와 옛 문서의 미발행 표현은 실제 Release/PR 기록과 대조한다.
- 요구사항·AC·Decision·일정의 정본은 `fds-project-baseline`, Runtime 원본 증적은 `fds-project-evidence`에 둔다. 코드 저장소에는 실행 소스, 비밀값 없는 예제, 증적의 commit/path/SHA256 참조를 둔다.
- Phase 2의 현재 이슈는 AWS/ROSA와 조건부 OCI Relay 구조다. 이전 대화의 OCI 중심 설명 및 잘못 연결한 이슈 번호를 사양으로 사용하지 않는다. 새 플랫폼 결정이 승인될 때까지 범위를 확대하지 않는다.
- 계정 매핑은 [GITHUB_IDENTITY_MAP](https://github.com/321Team/fds-project-baseline/blob/121fb744f0d816b3910a0bb07cf2bbe0d8883a16/governance/GITHUB_IDENTITY_MAP.md)을 따른다. 업무 담당과 정본 승인 권한은 다르다.

## 브랜치·리뷰·병합

1. `main`은 승인된 소스만 관리한다. 작업은 `feat/`, `fix/`, `docs/`, `chore/` 브랜치와 PR로 제출한다. 직접 push, 자동 merge, force push, main 삭제, 이력 재작성을 금지한다.
2. PR에는 관련 AC/티켓, 영향·복구 방식, source/destination SHA, 검증 명령·결과·미확인을 기록한다. 최소 1인의 작성자와 다른 리뷰어가 최신 HEAD를 검토한다.
3. 이권욱 작성 변경은 이하영이, 이하영 작성 변경은 이권욱이 독립 검토한다. 앱/모니터링 업무 담당 이재환의 구현·인계 역할을 유지하되 정본 승인·발행 역할을 부여하지 않는다.
4. CODEOWNERS의 GWONUK/hayeounglee는 검토 경로다. 2026-09-17 API에서 두 계정의 새 3개 저장소 Admin 권한을 확인했으며 이번 작업으로 권한을 변경하지 않았다. 작성자 자신의 검토를 독립 승인으로 세지 않는다.
5. 승인 이후 commit 추가 시 영향 부분을 재검토한다. 이권욱은 독립 리뷰·해당 HEAD·필수 검증·미해결 차단사항을 확인한 뒤 수동 병합한다. migration PR은 merge commit 방식으로 이관 경계와 원본 provenance를 유지하는 것을 권고한다.
6. 병합, Release 발행, Runtime 적용, 영구 반영, 정본 발행, 티켓 종결은 별도 판정이다. 정책 PR 병합이 배포·인증서 발급·기존 원본 삭제 승인이 되지 않는다.

## Private 저장소 보상 통제

신규 main은 조회 시점에 protected=false였다. infra-pki rulesets 조회는 GitHub 요금제 제한으로 HTTP 403을 반환했다. Private를 유지하며 유료 전환이나 Public 전환을 수행하지 않는다. CODEOWNERS 파일만으로 승인 강제를 주장하지 않는다.

보호 기능을 사용할 수 있을 때의 설정안은 main 대상 PR 필수, 독립 승인 1인 이상, 새 push 후 기존 승인 무효화, 대화 해결 필수, force push/삭제 차단, 관리자 우회 금지다. 실제 실행되고 안정된 check 이름만 required status check로 지정한다. 존재하지 않는 CI 이름을 등록하지 않는다. 이 설정은 본 PR의 문서 제안이며 적용하지 않았다.

현재는 PR에 최신 HEAD·독립 리뷰 URL·검증 로그를 연결하고 승인 운영자가 수동 확인한다. CI 0건은 NOT RUN이다. 로컬 PASS는 CI PASS 또는 Runtime PASS로 바꾸어 기록하지 않는다.

## 검증·비밀정보·변경 통제

- STATIC / MOCK / CI / RUNTIME / REVIEW / MERGE / PUBLICATION 상태를 분리한다. 출처 commit, 실행 호스트·시각(KST), 명령, 종료 코드, 원본 로그와 필요한 해시를 기록한다.
- 개인키, 토큰, 비밀번호, 실제 Secret, kubeconfig, CA 서명 DB와 민감 백업을 저장하지 않는다. `.gitignore`는 보조 조치이므로 staged diff·전체 신규 파일도 검사한다. 공개 인증서 허용은 PKI 정책의 별도 검증을 따른다.
- `.trivyignore` 이관은 해당 CVE 예외의 재승인이 아니다. 만료·근거·담당·소비 파이프라인 검증 전 새 예외로 사용하지 않는다.
- GitHub Actions/Runner/배포 권한과 Secret을 자동 이관하지 않는다. 현재 중앙 Runner는 `infra-cicd` 전용이다. 앱 원본의 self-hosted 자동 배포 Workflow는 비활성 참고 파일로만 보존한다.
- 실행 변경에는 대상 서버·계정·권한·작업 경로·선행조건·성공/중단 기준·복구 절차가 필요하다. TLS 검증, SELinux, 방화벽을 임의 해제하지 않는다.

## 이관 및 전환 완료조건

원본은 보존한 채 승인 main의 고정 snapshot만 가져온다. Git 전체 이력을 새 저장소로 합치지 않고 원본 URL/commit/blob/SHA256/파일 mode를 manifest로 보존한다. 과거 PR 승인·Runtime 증적은 원래 저장소 permalink로 연결한다.

1. destination PR의 파일별 무결성·의존성·검증 결과를 독립 검토한다.
2. 승인·병합 후 destination merge SHA를 고정한다.
3. 소비자(CI build source, 문서 링크, 배포/발급 키트)의 source pin 변경을 별도 PR로 검토한다. 기존 승인 pin을 임의로 새 main으로 바꾸지 않는다.
4. 동일 입력에 대한 기능·보안·실패/복구 재검증 후 소유권 전환을 기록한다.
5. 기존 저장소의 삭제·포인터화는 위 단계 완료 후 별도 승인 PR로만 처리한다. 과거 evidence/tag/release/permalink는 유지한다.

되돌리기는 새 source pin 채택을 보류하거나 소비자 pin을 직전 승인본으로 되돌리는 PR이다. 인증서 신뢰나 서버 상태를 Git revert만으로 복구했다고 표시하지 않는다.

## 신규 소스 CI

이 PR은 GitHub 제공 Runner의 읽기 전용 source-validation을 추가한다. 기존 self-hosted 배포 Workflow의 비활성 보존과 구분한다. repo guard·contents:read·timeout·checkout credential 비보존을 적용하며, server Secret이나 배포 권한을 부여하지 않는다. 실제 Check 상태는 해당 PR HEAD와 연결해 확인한다.
