# ROSA 배포 입력 계약 — #43 생산 / #46 소비 (CONTRACT_PREPARATION)

근거:
- [#43 배포 입력 계약 보완 요청 6099489688](https://github.com/321Team/fds-project-baseline/issues/43#issuecomment-6099489688)
- [infra-rosa#5 v3 §3-4](https://github.com/321Team/infra-rosa/issues/5#issuecomment-6108735303)
- [v3 심층 리뷰 6109084044](https://github.com/321Team/infra-rosa/issues/5#issuecomment-6109084044) 1·2·5번
- infra-rosa `platform/netpol/00~03`(PR35 merge `b636dec`)
- [infra-rosa#5 v3.2 6109421149](https://github.com/321Team/infra-rosa/issues/5#issuecomment-6109421149): `routes/custom-host` (a) 채택·조건 3개
- [infra-rosa#7 6109434697](https://github.com/321Team/infra-rosa/issues/7#issuecomment-6109434697): 앱 NetworkPolicy·기본 차단 소유 확정

이 문서는 **렌더·계약 준비**입니다.
- ROSA 배포, 권한 부여, token 발급의 GO가 아닙니다.
- Phase 1 운영(`overlays/p1-onprem`)은 바꾸지 않습니다.
- 앱 NP 소유·`default-deny-all` 제외는 #7에서, `routes/custom-host`는 #5 v3.2에서 확정됐습니다. 실제 ROSA 적용·시험은 NOT_RUN입니다.

## 1. 산출물 두 개

base가 SA 2·Deployment 2·Service 2·NetworkPolicy 3을 한 번에 렌더하면 배포 SA가 SA·NetworkPolicy에서 403을 받습니다. 그래서 같은 base + `components/openshift`를 두 렌더로 나눕니다. Role은 넓히지 않습니다.

| 렌더 | 적용 주체 | 객체 (namespace `fds-app`) |
|---|---|---|
| `overlays/rosa-app` | 배포 SA `ci-cd/fds-deployer` (#46 Runner) | Deployment `transaction-api`·`fds-engine`, Service `transaction-api`·`fds-engine`, Route `transaction-api-api`·`transaction-api-readyz` (6개) |
| `overlays/rosa-prereq` | #5/#7 bootstrap 실행자(named admin), 배포 전 | ServiceAccount `transaction-api-sa`·`fds-engine-sa`, NetworkPolicy `transaction-api-allow`·`fds-engine-allow` (4개) |
| 어디에도 넣지 않음 | — | NetworkPolicy `default-deny-all` (플랫폼 `fds-platform-default-deny`와 같은 기능, #7 확정) |

- ConfigMap은 0개입니다. ConfigMap을 추가하려면 이 계약과 `deploy/delivery/rosa.yaml`을 먼저 바꿉니다.
- 기계 판독 허용목록은 [`delivery/rosa.yaml`](delivery/rosa.yaml)입니다.
- 시험 `tools/tests/test_deploy_rosa_delivery.py`가 두 렌더와 제외 목록의 합이 base+openshift 전체와 정확히 같은지 확인합니다. 빠지거나 겹치는 객체가 없습니다.
- `lab-db`는 두 렌더 모두에 넣지 않습니다. ROSA의 DB는 db01(#47)입니다.

## 2. 플랫폼 사전 자원과 receipt (배포 전, 배포 SA 밖)

| 자원 | 생산 | #43이 정하는 것 | receipt에 남길 것 |
|---|---|---|---|
| Namespace `fds-app` | #5 | 이름 | 이름·UID·label |
| SA `transaction-api-sa`, `fds-engine-sa` | #5 (rosa-prereq 적용) | 이름, `automountServiceAccountToken: false`, 추가 binding 없음 | 이름·UID |
| 앱 NP `transaction-api-allow`, `fds-engine-allow` | #5/#7 실행자가 배포 전에 rosa-prereq 적용·정리 (#7 확정) | 규칙 내용(아래 3절) | 이름·UID·내용 SHA(= #43 렌더) |
| 플랫폼 NP 00~03 | #7 | 앱 쪽 라벨 계약(아래) | 이름·UID·내용 SHA. 03은 자리표시값이 채워진 승인본 |
| Secret `transaction-api-db-credentials` (key `DATABASE_URL`) | #43/#12 승인 경로 | 이름·key | 이름·resourceVersion (**값 없음**) |

- receipt 생산은 #5(named admin), 소비 판정은 #46입니다(infra-rosa#5 v3 §3-4).
- **#43이 receipt와 묶을 것:** `rosa-app` 렌더 파일 SHA-256, `delivery/rosa.yaml` SHA-256, fds-msa source commit.
  - 앞의 두 SHA-256은 `tools/check_delivery_render.py` 출력(`rendered_sha256`·`contract_sha256`)에 나옵니다.
  - source commit은 검사기가 검증하지 않습니다. 렌더한 clean checkout의 commit을 receipt에 별도 인수 메타데이터로 적습니다. 문자열만 적은 것을 원본 결속 검증으로 표시하지 않습니다.
- 하나라도 누락·불일치·오래됨이면 **첫 쓰기 전에 STOP**합니다.

## 3. NetworkPolicy 소유와 최종 허용 경로 (#7 6109434697 확정)

같은 namespace의 NetworkPolicy는 허용이 **합산**됩니다. 그래서 정책 이름이 아니라 합산 결과로 대조합니다.

| Pod | 방향 | 허용 | 출처 |
|---|---|---|---|
| transaction-api | ingress | 라우터 namespace(`policy-group.network.openshift.io/ingress: ""`) → **8000** | 앱 NP(openshift component) |
| transaction-api | egress | fds-engine **8001** | 앱 NP(base) |
| transaction-api | egress | openshift-dns 53/5353 UDP·TCP | 앱 NP + 플랫폼 01 (중복, 결과 같음) |
| transaction-api | egress | db01 `10.1.93.55:5432` | **플랫폼 03**, Pod 라벨 `onprem-egress: "true"`(rosa-app이 붙임). IF-18 승인값으로 03의 자리표시값이 채워진 뒤에만 열림 |
| fds-engine | ingress | transaction-api → **8001** | 앱 NP(base) |
| fds-engine | egress | openshift-dns 53/5353 | 앱 NP + 플랫폼 01 |
| 둘 다 | 그 밖 | 차단 | 플랫폼 00 `fds-platform-default-deny` |

- **앱 NP에는 DB egress를 넣지 않습니다.** DB ACL의 출처를 플랫폼 03 한 곳(IF-18)으로 둡니다. fds-engine에는 `onprem-egress` 라벨을 붙이지 않습니다.
- **신뢰 경계(#5 v3.2 §2·#7):** `onprem-egress: "true"`는 `transaction-api` Pod template에만 허용합니다. 다른 workload에 있으면 렌더 검사가 FAIL하고 #46은 첫 변경 전에 STOP합니다. 앱 렌더 허용목록에 Deployment 2개 외의 workload 종류는 없습니다. 이것은 CI 경로 통제이며 admission 통제가 아닙니다.
- 플랫폼 02 `allow-ingress-from-router`는 `route-exposed: "true"` Pod의 8080(probe)용입니다. 앱 Pod에는 이 라벨을 붙이지 않습니다. 앱 8000 진입은 앱 NP가 엽니다.
- **메트릭 포트 9091·9090으로의 진입은 없습니다.** ROSA 수집 경로는 아직 정해지지 않았습니다(아래 5절).
- `default-deny-all`을 빼도 기본 차단은 플랫폼 00이 맡습니다. 00이 없으면 기본 차단이 사라지므로 receipt에서 00이 필수입니다.

## 4. 권한과 순서

배포 SA Role(infra-rosa#5 v3 §3-2)과 대조했습니다.

| 단계 | 동작 | 필요한 권한 | Role |
|---|---|---|---|
| 공통 | 렌더 검사 `check_delivery_render.py --mode app` PASS + receipt PASS | 없음(로컬) | — |
| 최초 배포 | `kubectl apply --server-side --field-manager=fds-deployer -f app.yaml` (prune·force-conflicts 없음) | services·deployments·routes `create`/`patch`/`get` | 있음 |
| 〃 | Route `spec.host` 지정(생성 시) | `route.openshift.io` **`routes/custom-host` `create`** | **추가 — #5 v3.2 (a)** |
| 〃 | `kubectl rollout status deploy/transaction-api deploy/fds-engine --timeout=300s` | deployments·replicasets `get`/`watch`, pods·events `get`/`list` | 있음 |
| 업데이트 | 새 승인 digest로 다시 렌더 → 같은 apply → rollout status | 위와 같음 | 있음 |
| 이전 버전 복구 | **직전 승인 렌더 파일(previous digest)을 다시 apply** → rollout status. `rollout undo`는 쓰지 않습니다(렌더 SHA와 결과가 묶이지 않음) | 위와 같음 | 있음 |
| 사람만 | 삭제·이름 변경, SA·NP·Secret 변경, 렌더 밖 수정 | — | 넣지 않음 |

- **`routes/custom-host` — (a) 채택([#5 v3.2](https://github.com/321Team/infra-rosa/issues/5#issuecomment-6109421149)):** `fds-app` Role에 `routes/custom-host` `create` 한 규칙만 추가합니다. 조건은 셋입니다.
  1. `create`만 부여합니다.
     - `update`를 주지 않는 것은 host·subdomain 변경을 막을 뿐입니다. **TLS 불변 통제가 아닙니다.**
     - OpenShift는 생성할 때 host나 인증서 필드가 있으면 `create`를 확인합니다. host가 같고 인증서만 바뀌는 수정도 `create`로 허용합니다([권욱 rosa#5 리뷰 6109978967](https://github.com/321Team/infra-rosa/issues/5#issuecomment-6109978967) B1, openshift-apiserver `hostassignment` 구현).
     - 그래서 이번 CI 배포의 TLS 범위를 **렌더 검사로 고정**합니다. Route `spec.tls`에는 `termination: edge`와 `insecureEdgeTerminationPolicy: Redirect`만 허용합니다. `certificate`·`key`·`caCertificate`·`destinationCACertificate`·`externalCertificate` 등 다른 필드가 있으면 FAIL합니다(기본 apps 인증서 사용, #38 회신).
     - 이 검사는 admission 통제가 아닙니다. 배포 token으로 API를 직접 호출하면 인증서 필드를 설정할 수 있는 잔여 권한이 남습니다. 이 잔여 권한의 수용 여부는 #5 Lead 판단입니다.
  2. 두 Route의 `spec.host`는 계약의 승인 host 1개(`delivery/rosa.yaml` `app.route_host.approved`)와 같아야 합니다. 다르거나 비었거나, 승인 host가 아직 `PENDING`이면 렌더 검사가 FAIL하고 첫 변경 전에 STOP합니다. 승인 host는 ingress domain 확정 뒤 infra-rosa#4 Handoff 2 기준으로 PR을 통해 기록합니다.
  3. 시험 행 A-09·A-10·D-13a·D-13b·D-13c(infra-rosa#5 v3.2 표)는 NOT_RUN입니다. A-10(같은 host 재적용 허용)은 ROSA 실측 전에 가정하지 않습니다. 거부되면 STOP 후 재검토합니다.
- server-side apply가 다른 field manager와 충돌하면 강제로 덮어쓰지 않고 STOP합니다. 예: named admin이 같은 객체를 먼저 만든 경우.
- 배포 SA에 `delete`, `secrets`, `pods/exec`가 필요한 절차는 없습니다.

## 5. monitoring-api

**이번 Runner 배포 대상에 넣지 않습니다.**
- 두 렌더 모두 `fds-app`만 대상입니다. `monitoring-api` 권한은 자동으로 넓히지 않습니다(infra-rosa#5 §7-2).
- ROSA 수집 위치는 별도 결정입니다. `openshift-monitoring`/user workload monitoring이나 On-Prem 수집 같은 후보가 있고, #25는 Deferred 후보입니다.
- 수집 경로가 정해지면 9091·9090 진입 NP와 대상 namespace를 이 계약의 개정으로 추가합니다.

## 6. 배포 token — #46에 넘기는 #43 쪽 입력

| 항목 | #43 입력 | 결정 |
|---|---|---|
| 작업 시간 | apply 수 초 + rollout 2개 × 최대 300초. 상한 약 11분 | 근거: replicas 3, readiness 5s/10s, maxSurge 1·maxUnavailable 0, cold pull 포함 |
| 요청 수명 | 900초로 충분. 1h로 늘릴 근거 없음 | #46 |
| 첫 쓰기 전 STOP | 실제 `expirationTimestamp`까지 남은 시간이 660초 미만이면 쓰지 않음 | #46 |
| 실행 중 만료 | 갱신·재시도하지 않고 STOP, 사람 판단 | #46 |
| audience | 클러스터 API 서버 기본 audience. 앱은 token을 쓰지 않음 | #46 |

## 7. 렌더와 전달 검사

```bash
kubectl kustomize deploy/overlays/rosa-app > app.yaml
python3 tools/check_delivery_render.py --mode app app.yaml          # 전달: 자리표시값이 남으면 FAIL
kubectl kustomize deploy/overlays/rosa-prereq > prereq.yaml
python3 tools/check_delivery_render.py --mode prereq prereq.yaml
```

- 종료 코드: 0 = PASS, 1 = FAIL(사유는 JSON), 2 = 입력 오류.
- 출력에 객체 목록·이미지·Route host·`rendered_sha256`·`contract_sha256`이 나옵니다.

**검사 내용**
- 허용목록과 객체가 정확히 같은지(빠짐·추가·중복 없음)
- namespace `fds-app`, cluster-scope 자원 없음
- Deployment마다 승인 앱 SA 명시, `automountServiceAccountToken: false`
- 승인된 Secret 참조만 사용(env·envFrom·volume·projected·**imagePullSecrets**)
- 이미지가 `이름@sha256:<64자리 소문자 hex>` 전체 형식으로 고정됨
- 고정 UID·privileged·host namespace 없음
- `onprem-egress` 라벨은 transaction-api에만 있음
- Route 두 개 모두 비어 있지 않은 DNS host이고, 서로 같고, 계약의 승인 host와 같음(승인 host `PENDING`이면 FAIL)
- 계약·렌더 구조가 예상과 다르면 traceback 없이 `ERROR`·종료 코드 2

`--allow-placeholders`는 CI 렌더 확인 전용입니다. 이 경우에만 자리표시값과 승인 host `PENDING`을 허용합니다. 전달 회차에서 쓰지 않습니다.

strict PASS는 렌더 구조 검사이며 전달 승인·Runtime GO가 아닙니다. 레지스트리는 [D22 FINAL 6337537087](https://github.com/321Team/fds-project-baseline/issues/42#issuecomment-6337537087)로 확정됐고, 실제 전달은 #46의 승인 입력·원본·receipt 대조를 따릅니다.

## 8. 아직 비어 있는 입력

| 입력 | 출처 | 현재 |
|---|---|---|
| 레지스트리 | [321Team/fds-project-baseline#42](https://github.com/321Team/fds-project-baseline/issues/42)(D22) | **`10.1.93.54/fds/<앱>`**(Harbor Primary, `rosa-app` 반영). D22 FINAL: [`D22=GO:Harbor` 6337537087](https://github.com/321Team/fds-project-baseline/issues/42#issuecomment-6337537087)(2026-10-22, 승인 digest 2개의 레지스트리 소스·소비 계약 결정. #46 배포·DB 개방·창 C Runtime GO는 아님). ECR 수동 A는 운영 준비 미확인, 자동 전환 없음. pull 자격은 앱 SA 연결(플랫폼, [하영 채택 infra-rosa#12 6315085580](https://github.com/321Team/infra-rosa/issues/12#issuecomment-6315085580)) |
| current digest | #43 채택(2026-10-15) | 앱별 고정: transaction-api `338b8a28…`, fds-engine `8b257adb…`(Push 38404449622). 아래 9절 |
| previous digest | #43 채택(2026-10-15) | **없음(최초 P2 배포)**. 아래 9절 |
| Route 승인 host | infra-rosa#4 Handoff 2 → `delivery/rosa.yaml` `app.route_host.approved` | **`fds-api.apps.rosa.fds-rosa-hcp.khht.p3.openshiftapps.com`** (2026-10-18 기록). Handoff 2 = [baseline#38 6249632930](https://github.com/321Team/fds-project-baseline/issues/38#issuecomment-6249632930) 2행 Ingress domain, [권욱 수신 검토 6250017909](https://github.com/321Team/fds-project-baseline/issues/38#issuecomment-6250017909). `rosa-app` overlay가 두 Route에 넣고, `components/openshift`는 자리표시값 유지. default 인증서가 이 host를 덮는지는 #38 TLS handoff 전 NOT VERIFIED |
| `routes/custom-host` 처리 | #5 | (a) 채택, Role 반영·시험은 NOT_RUN |
| 앱 NP 적용 주체, `default-deny-all` 제외 | #7 | 확정(문서), 적용 NOT_RUN |
| 플랫폼 03의 IF-18 승인값 | #37·#47 | 대기 |
| Secret 생성 경로 | #43/#12 | 대기 |
| 라우터·openshift-dns 라벨, SCC 배정 UID 동작 | #38·#6 PG-03 | NOT VERIFIED |

## 9. 앱별 current/previous 채택 (#43, 2026-10-15)

| 앱 | current | previous |
|---|---|---|
| transaction-api | `sha256:338b8a2871507ce8b42deedc916b26e350577ee6efd18df23d7ff2dd4b17dff0` | 없음(최초 P2 배포) |
| fds-engine | `sha256:8b257adb08b6d381f72b66d3386efea6112a8f072ecfafcbcd463bcd1c3be89d` | 없음(최초 P2 배포) |

- **current 출처:** source `affbc69beef9967f7977d09a6fec14f7fb6c0e94`(fds-msa#27 승인) → TBS run 38395350748 → Push run 38404449622. 인계 원본은 evidence PR218 커밋 `7e6bb13d`의 `evidence/P1-CICD-01/push-run-38404449622-20261013/NEXT_DEPLOY_HANDOFF.json`입니다(push receipt `8be5cef6…`, scan 결과 `2326e501…`). `affbc69` 이후 `transaction-api/`·`fds-engine/`·`ci/apko/` 변경은 없습니다.
- **previous를 두지 않는 이유:** P1 롤백 digest(`a7093136…`/`5e2a081c…`)는 Pod spec 관측값입니다. registry manifest·scan·승인 source lineage가 묶이지 않아, 현재 승인된 P2 lineage가 없습니다(D22 입력 계약). P1 복구 수용이나 해당 digest의 영구 사용 금지를 뜻하지 않습니다. evidence `P1-CICD-01`의 Push 실행 원본은 38404449622 1건뿐이라 다른 previous 후보도 없습니다.
- **최초 배포 실패 시:** 최초 P2 배포에는 승인된 previous 렌더가 없습니다. 일부 적용 후 실패·timeout·응답 불명확·rollout 실패 시 자동 재적용/복구/삭제 없이 STOP하고, 해당 회차 증적과 실제 대상 상태를 대조해 사람이 정리 범위를 판단합니다. P1 workload·트래픽·DB 및 운영 설정은 이 절차의 변경 대상이 아닙니다. 이는 P1 실제 가용성 검증을 대신하지 않습니다.
- **이후:** 최초 P2 배포의 검증·인수가 완료되면 승인 reference와 함께 앱별 digest, source/render/contract hash 및 필요한 설정·플랫폼 receipt를 묶어 다음 업데이트의 previous 후보로 기록합니다. 실제 restore는 그 이전 승인본의 유효성·가용성을 확인하고 별도 action/작업창 승인으로 수행합니다.
- **레지스트리:** #42(D22)로 이름만 바꿉니다. 복사 뒤 digest가 같아야 하며, 다르면 #46은 첫 쓰기 전에 STOP합니다.
- **미검증:** ROSA SCC가 배정하는 임의 UID로 실행되는지는 NOT VERIFIED입니다(8절 SCC 행). 이미지는 `USER 10001:999`이고 `readOnlyRootFilesystem: true`·`PYTHONDONTWRITEBYTECODE=1`입니다. 실행 시점의 scan 최신성은 #46이 판단합니다.
