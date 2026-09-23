# 이관 기록 및 전환 계획

상태: PR 준비 / 독립 REVIEW=PENDING / destination MERGE=NOT_DONE / RUNTIME=NOT_RUN.

54개 기존 파일을 이 저장소의 책임 경계에 맞게 복사했다. 파일별 원본 repository/commit/path/Git blob/SHA256/mode, destination hash 및 변경 사유는 [MIGRATION_MANIFEST.json](MIGRATION_MANIFEST.json)에 있다. 원본 Git 전체 이력은 재작성하거나 합치지 않았다.

## 확인된 source

- 앱·관측: [supreme33-kr/fds-msa main](https://github.com/supreme33-kr/fds-msa/tree/254b82231f8af79a06419b581174647bbccbe2bc), `254b82231f8af79a06419b581174647bbccbe2bc`. [PR #3](https://github.com/supreme33-kr/fds-msa/pull/3) 관측 스택, [PR #4](https://github.com/supreme33-kr/fds-msa/pull/4) 테스트, [PR #5](https://github.com/supreme33-kr/fds-msa/pull/5) 전용 metrics listener가 병합되어 있다.
- PKI: [infra-cicd main](https://github.com/321Team/infra-cicd/tree/90f2f37d9e1ab77252b50e80bca339cfef48bd51), `90f2f37d9e1ab77252b50e80bca339cfef48bd51`. [PR #2](https://github.com/321Team/infra-cicd/pull/2) merge `ffaa764623c5941b14fe12384e9ba5629bd60a6f`의 profile/CSR 도구·Runbook을 현재 main에서 대조했다.
- 기준: [발행 v3.1.18](https://github.com/321Team/fds-project-baseline/releases/tag/docs-v3.1.18), 이후 #15/#17/#63/#64/#74/#75 및 관련 PR의 최신 기록. 원본 문서의 CANDIDATE/미발급/미리뷰 문구는 작성 당시 이력이며 현재 상태로 재발행하지 않는다.

## 보존·제외 및 책임

- 기존 저장소의 파일·브랜치·Issue·PR·Release와 Runtime 증적을 변경하거나 삭제하지 않았다.
- infra-kubernetes의 open PR #7(보안/앱 보완), #12(Alertmanager egress)와 infra-ansible의 open 후속 PR #18은 미병합이므로 가져오지 않았다. 해당 PR은 원래 위치에서 검토한다.
- Squid 공통 role/inventory는 infra-ansible에 남긴다. 원본 앱의 edge-proxy와 ci-cd Runner RBAC는 infra-lb/infra-cicd 책임 자료이므로 이번 신규 3개 저장소의 운영 소스로 채택하지 않는다.
- 앱의 혼합 namespace/ServiceAccount는 references에 보관한다. app-only split와 보안 정합성은 후속 PR에서 검토하며 클러스터 전체 소유권을 앱 저장소로 옮기지 않는다.
- 원본 Workflow는 활성 `.github/workflows/`로 복사하지 않았다. 고정되지 않은 이미지, insecure TLS, 기본 관리자 암호 등 임시 설정은 정본 정책이 아니다. Grafana 기본 암호는 참고 snapshot에서도 비실행 placeholder로 치환했고 해당 1건의 해시 차이를 기록했다.
- PKI 실제 공개 인증서·승인 지문·키·서명 DB는 이번 이관에 포함하지 않는다. 원본 증적의 공개값이라도 승인 자산 식별과 현재 유효성을 검토한 뒤 별도 PR로 등록한다.

## 무결성 검증 및 다음 단계

저장소 루트에서 `python tools/verify_migration.py --rev d9f7bb0cf600bf18623dcae2769372d357dd594d`(초기 이관 commit)를 실행한다. `--rev` 없이 실행하면 작업 트리를 읽으므로, 이관 이후 의도적으로 변경된 파일(예: `7a8f329`의 Dockerfile 2개)은 hash 불일치로 FAIL이 되며 이는 결함이 아니다. 종료 0은 이관 파일의 hash 일치만 의미한다. `docs/VALIDATION.md`에서 구문·unit/mock 및 미실행 범위를 확인한다. 이 검증기는 초기 이관 commit에 대한 도구이며 이후 의도된 구현 변경을 옛 snapshot에 맞추라고 요구하는 영구 CI gate가 아니다.

독립 승인·병합 후 새 merge SHA를 고정하여 CI 소스·배포 키트·문서 참조 변경 PR을 준비한다. 원본 정리/삭제는 그 이후 별도 승인으로 처리한다. 전환 전에는 기존 승인 source pin이 계속 유효하다. 이번 이관은 Runtime 인수·업무 계약 승인·정본 발행·티켓 종결을 대체하지 않는다.
