# 저장소 운영 정책

상태: 사용자 요청에 따라 정본 기준으로 정리한 이관 PR의 운영 정책. PR 병합·독립 승인·서버 실행·권한 변경은 각각 별도 기록한다. 기준 확인: 2026-09-17 KST.

## 1. 적용 근거와 권한 범위

1. 요구사항·AC·아키텍처는 [발행 정본 v3.1.18](https://github.com/321Team/fds-project-baseline/blob/72599ae49342b0fb8dbd3d8ee60314afb9f907bb/baseline/FDS_Project_Implementation_Baseline_v3.1.18.md)과 이후 승인된 Decision/CR을 따른다. 승인 source는 `72599ae49342b0fb8dbd3d8ee60314afb9f907bb`다. 후보 문서, 미병합 PR, 구현 편의로 AC를 새로 확정하지 않는다.
2. [정본 발행 정책 §1·§4·§5·§6](https://github.com/321Team/fds-project-baseline/blob/121fb744f0d816b3910a0bb07cf2bbe0d8883a16/governance/RELEASE_POLICY.md)의 Private·PR·독립 검토·수동 병합·검증 표기 원칙을 이번 세 신규 소스 저장소의 운영에도 적용한다. 이는 정본 문서 전용 Release/XLSX/ZIP 절차 전체를 소스 저장소에 강제한다는 뜻이 아니다.
3. [infra-cicd의 병합된 운영 기준](https://github.com/321Team/infra-cicd/blob/90f2f37d9e1ab77252b50e80bca339cfef48bd51/docs/governance.md)과 [중앙 Delivery 경계](https://github.com/321Team/infra-cicd/blob/90f2f37d9e1ab77252b50e80bca339cfef48bd51/README.md)는 해당 구현 책임과 승인 범위에서 준용한다. 저장소 분리로 Runner·배포·발급 권한을 확대하지 않는다.
4. 저장소 이름, 아래 작업 브랜치 이름, snapshot-copy와 폴더 배치는 사용자 요청에 따른 이번 운영 세칙이다. 정본이 특정 GitHub 저장소 이름이나 이관 방식을 강제했다고 표시하지 않는다. 항목별 근거는 [정본 대응표](CANONICAL_POLICY.md)에 있다.

## 2. 소유권과 검토

- 요구사항/AC/Decision/CR/WBS/Release 정본은 `fds-project-baseline`, 수신된 실행 원본·독립 검토 증적은 `fds-project-evidence`에 둔다. 각 소스 저장소에는 구현·안전한 예제·Runbook과 증적 commit/path/SHA256 참조를 둔다.
- 업무 Lead·Support는 책임 티켓의 기존 배정을 유지한다. 계정은 [Identity Map](https://github.com/321Team/fds-project-baseline/blob/121fb744f0d816b3910a0bb07cf2bbe0d8883a16/governance/GITHUB_IDENTITY_MAP.md)으로 연결한다. 이재환의 Application/Data/Monitoring/QA 역할과 정본 승인·리뷰·병합·발행 역할 제외는 구분한다. 정본 권한 제한을 모든 업무 소스 검토 금지로 확대하지 않는다.
- 이번 이관 작성자는 이권욱/GWONUK이다. 이하영/hayeounglee의 독립 검토 결과와 최신 HEAD를 확인한 뒤 이권욱이 수동 병합을 판단한다. 반대 작성 관계에는 이권욱이 독립 검토한다. AI 보조 점검과 작성자 자신의 검토는 타인의 독립 승인이 아니다.
- CODEOWNERS는 GWONUK/hayeounglee 검토 경로를 기록한다. 실제 업무 Owner·승인자·계정 권한을 이 파일로 바꾸지 않으며, 파일 존재만으로 리뷰가 기술적으로 강제된다고 주장하지 않는다.

## 3. 브랜치와 병합

- `main`은 검토된 소스만 관리한다. `feat/`, `fix/`, `docs/`, `chore/` 작업 브랜치와 PR을 사용한다. 직접 main push·자동 merge·force push·main 삭제·기존 이력 재작성을 하지 않는다. 브랜치 접두어는 이번 운영 세칙이다.
- PR에는 책임 티켓/AC, 변경 이유, 영향과 복구, 검토 HEAD, 검증 명령·환경·결과·제한을 기록한다. 최소 1인의 작성자 외 독립 검토·승인 근거를 연결한다. GitHub APPROVED, 기술 검토 의견, 단순 reviewer 지정은 구분하며 자신의 PR에 자기 APPROVE를 요구하지 않는다.
- 새 commit이 추가되면 변경 부분과 영향을 받은 범위를 재검토한다. 무관한 시험을 반복하지 않는다. 병합 직전 승인 대상 HEAD·미해결 차단사항·해당 단계 필수 검증을 재확인한다.
- Private를 유지한다. 보호 기능이 제한된 경우 PR의 SHA·검증·독립 리뷰를 승인 운영자가 확인하는 수동 보상 통제를 적용한다. 유료 전환이나 Public 전환을 선행조건으로 요구하지 않는다.
- Branch protection/ruleset은 이번에 적용하지 않는다. 향후 사용 가능한 경우 PR·독립 리뷰·대화 해결·force push/삭제 차단을 구현하되 실제 실행되고 채택된 check만 필수로 지정한다. 이관 merge commit 방식은 추적성 권고이며 정본 AC가 아니다.

## 4. CI 결정과 보상 검증

**현재 결정: 세 신규 저장소의 Actions 비활성 상태를 유지하고, 이번 이관은 소스 검증 증적과 독립 검토로 판단한다. Actions 활성화 자체를 이관의 새 필수 AC로 추가하지 않는다.**

- 정본 발행 정책 §6의 `Actions 미실행 → 로컬 결과만 기록, CI PASS로 오인 표시 금지`를 신규 소스에 적용한다. §2.1의 동일 스크립트 로컬 보상 방식도 참고하되 WBS 전용 검사를 앱/PKI에 요구하지 않는다. 보상 검증은 실제 검사 실패·누락을 숨기는 면제가 아니다.
- 새 source-validation Workflow는 활성화될 경우를 위한 소스 검사 정의다. 기존 [infra-cicd 소스 검사](https://github.com/321Team/infra-cicd/blob/90f2f37d9e1ab77252b50e80bca339cfef48bd51/.github/workflows/source-validation.yml)처럼 GitHub-hosted/읽기 전용/제한 시간/고정 checkout/credential 비보존을 사용한다. 정본 내부 Delivery는 Self-hosted Runner이고, 이 소스 검사와 별개다.
- 새 저장소 CI가 0건이면 `CI=NOT RUN`이다. 로컬 검증은 STATIC 또는 MOCK/UNIT로 기록한다. 과거 원본 CI 성공은 원본 SHA/Run/Attempt의 이력이며 새 저장소 CI 성공이 아니다.
- 로컬 검증은 저장소 루트에서 `python tools/check_source.py`, `python tools/verify_migration.py`를 실행하고 원본/대상 해시·mode·문서 링크를 확인한다. source checker는 Git 추적 파일을 대상으로 하므로 신규 파일도 검토 대상에 포함한다. 환경/의존성/명령/종료 코드/로그/시각을 함께 남긴다.
- 앱은 서비스별 격리 환경에서 기존 단위/계약 시험을, Monitoring은 각 셸 파일 구문 검사를 수행한다. PKI Linux 시험은 승인된 Linux 검증 환경에서 `python3 -m unittest discover -s tools/pki -p 'test_*.py' -v`로 실행한다. 실제 key/CSR 생성과 시연 스크립트 실행은 소스 검증에 포함하지 않는다.
- 환경상 실행하지 못한 시험은 미실행으로 남긴다. 이번처럼 로직·프로파일·의존성 경로가 동일한 이관은 원본의 승인·시험 이력과 파일 동일성을 독립 검토자가 대조하여 제한 수용 여부를 명시한다. 이 문서가 그 수용·승인을 대신하지 않는다. 기능·경로·의존성 변경 시 관련 시험을 새로 수행한다.
- 조직 Actions 허용, 신규 저장소의 중앙 Runner 접근, 배포 Secret/Token 제공은 이번 변경에 포함하지 않는다. 향후 소스 CI 활성화를 채택하더라도 중앙 Runner 등록 범위나 내부망 접근을 자동 확대하지 않는다.

## 5. 비밀정보·실행·증적

- 개인키, 토큰, 비밀번호, 실제 Secret, kubeconfig, CA 서명 DB와 민감 백업은 Git·PR·로그·증적 묶음에 넣지 않는다. `.gitignore`는 보조 수단이며 전체 변경 내용도 확인한다. 공개 CA/Leaf/CSR·지문은 별도의 자산·유효성·공개자료 검토를 거친다.
- 기존 `.trivyignore` 복사는 CVE 예외 재승인이 아니다. 실제 Build/Security Gate 실패 시 Deploy 금지라는 정본 §10을 유지한다. 임시 self-hosted 자동 배포 Workflow는 비활성 참고 파일로 보관한다.
- 실행에는 승인 source/workflow SHA·대상 서버·계정·권한·경로·선행조건·성공/중단 기준·복구안을 고정한다. TLS 검증, SELinux, 방화벽을 우회하지 않는다. 배포는 승인 Image Digest를 사용한다.
- STATIC / MOCK / CI / RUNTIME / REVIEW / MERGE / PUBLICATION을 구분한다. 해시 일치는 무결성일 뿐 시험 성공·실제 인수 완료가 아니다. 증적의 호스트·KST 시각·버전·명령·종료 코드·원본 로그·해시를 연결한다.

## 6. 단계별 완료조건

| 단계 | 필요한 판정 | 이 단계가 승인하지 않는 것 |
|---|---|---|
| 이번 snapshot 이관 PR | 병합된 원본 SHA, 파일별 출처·hash·mode, 변환 사유, 의존성/책임 경계, 정적·적용 가능한 단위 검증, 미실행 제한과 독립 검토 | 신규 Runtime AC 추가, CI PASS 위장, 서버 적용, 기존 파일 삭제 |
| 소비자 소스 전환 PR | destination merge SHA 고정, CI/키트/참조 변경 영향, 해당 기능 재검증·복구, 책임자 검토 | 미승인 계약·SAN·Trust·Runner 권한 변경 |
| Runtime/티켓 인수 | 책임 티켓의 필수 AC, Positive/Negative 및 장애/복구, 원본 증적, Support Review와 필요한 승인 | 소스 병합이나 P1 준비만으로 P0/G1/G2/Done 자동 승격 |

기존 저장소·원본 이력·증적은 보존한다. 운영 소비자는 전환 PR 승인 전까지 기존 승인 pin을 유지한다. 삭제/포인터화는 전환 검증 후 별도 승인 PR로 처리한다. Git revert는 서버·인증서 신뢰 상태의 복구 증적이 아니다. P1/P2 고도화 미완료는 정본에 없는 P0 전역 차단조건으로 추가하지 않는다.
