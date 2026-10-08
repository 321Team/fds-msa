# deploy — portable workload base + 환경별 overlay

P2-APP-01 [#43](https://github.com/321Team/fds-project-baseline/issues/43)의 portable base입니다. 권욱님 리뷰([6041356020](https://github.com/321Team/fds-project-baseline/issues/43#issuecomment-6041356020))와 W0 계획(`audit/phase2-rosa-topology-review-20261002/w0-portability-precheck.md`)의 구분을 따릅니다. 앱 코드와 이미지는 바꾸지 않습니다.

## 구조

```text
deploy/
├── base/                    어디서나 같은 앱 계약
│   ├── transaction-api.yaml ServiceAccount·Deployment·Service(ClusterIP)
│   ├── fds-engine.yaml      ServiceAccount·Deployment·Service(ClusterIP, 외부 노출 없음)
│   └── networkpolicy.yaml   기본 차단 + transaction-api → fds-engine 8001
├── components/
│   ├── openshift/           Route(/api·/readyz, 같은 host, edge TLS) + 라우터 진입·openshift-dns 허용
│   └── lab-db/              시험용 임시 PostgreSQL — 명시적 opt-in (아래 "시험 DB" 절)
└── overlays/
    ├── p1-onprem/               Phase 1 운영(fds-app) 재현 — 비교 전용, apply하지 않음
    └── openshift-render-check/  base + openshift + lab-db 렌더 확인 전용 — 자리표시값, apply하지 않음
```

## base에 두는 것 / 두지 않는 것

| base에 둠 | overlay가 정함 |
|---|---|
| 포트 8000·9091 / 8001·9090, `/readyz`·`/livez` 프로브, 리소스 250m/256Mi~500m/512Mi, replicas 3 | 네임스페이스, 레지스트리·digest(`images:`) |
| `runAsNonRoot`·RuntimeDefault·권한 상승 금지·읽기 전용 루트·`drop ALL`, SA 토큰 자동 마운트 끔 | **고정 UID/GID**(P1 이미지 10001/999 — OpenShift는 SCC가 배정), pull secret |
| Worker 분산(`topologySpreadConstraints`, hostname, maxSkew 1) | 외부 진입(NodePort·Route), 모니터링 수집 경로와 메트릭 Service |
| `DATABASE_URL` ← Secret `transaction-api-db-credentials` **참조**만(값은 저장소 밖) | DB egress(db01 `10.1.93.55:5432`), DNS egress(kube-dns / openshift-dns) |
| fds-engine에는 DB 접속정보 없음, NetworkPolicy 기본 차단·API→engine 8001 | 환경 IP·CIDR |

base만 단독 적용하지 않습니다. DNS egress가 없어 transaction-api가 `fds-engine` 서비스 이름을 조회하지 못합니다.

## 검증 — Phase 1 운영과 차이 0건

`overlays/p1-onprem`은 2026-10-08 14:45 KST에 control01에서 읽기 전용으로 수집한 운영 상태(`p2-app-43-live.tgz` SHA-256 `a2309982963ba509e3d57eb56bd39e70ec4810d74812bb6ba015f9cee71516a8`)를 재현합니다. 운영에서 `last-applied` 주석은 권위 원본이 아닙니다. `DATABASE_URL` env와 10/7 Worker 분산이 patch로 추가돼 주석에 없기 때문에, 이 overlay는 live 값을 기준으로 씁니다.

control01(읽기 전용, apply 없음):

```bash
sudo kubectl --kubeconfig=/etc/kubernetes/admin.conf kustomize deploy/overlays/p1-onprem > rendered.yaml
sudo kubectl --kubeconfig=/etc/kubernetes/admin.conf diff -k deploy/overlays/p1-onprem
```

- `kubectl diff` 종료 코드: 0 = 차이 없음, 1 = 차이 있음, 1보다 큼 = 오류. 오류·권한 문제를 "차이 0"으로 기록하지 않습니다.
- client-side diff는 `kubectl.kubernetes.io/last-applied-configuration` 주석 갱신을 차이로 표시할 수 있습니다(위 사유). 그 외 차이가 없으면 spec 동등으로 판정하고, 주석 차이는 사유와 함께 기록합니다. diff를 0으로 만들려고 운영을 바꾸지 않습니다.
- Secret은 참조만 하므로 diff·로그에 Secret 값이 나오지 않습니다.

결과(2026-10-08 14:58 KST, control01 `~/p43-diff-20261008T145807`, 커밋 `f618377`의 `git archive` 묶음 SHA-256 `0e778f37ea92d83b2e979595c4a3faf70bc7f8d636979cde65de795907f79141`):

| 항목 | 값 |
|---|---|
| `kubectl kustomize` | rc=0, 객체 12개, `rendered.yaml` SHA-256 `58fafcf70f2818c21d40db0bc9c02c66003bde5ac46e56fb39562d67aa6f0519` |
| `kubectl diff -k` | rc=0, stdout 0줄, stderr 0줄 (주석 차이도 없음) |

범위: 렌더된 12개 객체가 운영과 같다는 뜻입니다. fds-app에만 있는 다른 객체(Secret 등)는 비교 대상이 아닙니다.

## components/openshift

| 항목 | 값 | 근거·미정 |
|---|---|---|
| Route | `transaction-api-api`(path `/api`), `transaction-api-readyz`(path `/readyz`). 같은 host, Service `transaction-api` 포트 `http`(→ 8000) | 경로 없는 catch-all Route를 만들지 않습니다. 8000의 `/metrics`·`/livez`·`/`는 외부로 나가지 않습니다 |
| TLS | `edge`, HTTP는 HTTPS로 Redirect | 앱이 평문 8000이라 경로 라우팅이 되는 방식은 edge뿐입니다(passthrough 불가, reencrypt는 Pod TLS 필요). 인증서·최종 방식은 #38 handoff로 확인합니다 |
| host | 자리표시값 `fds-api.route-host-input-pending.invalid` | 실제 overlay가 클러스터 apps 도메인 아래 값으로 바꿉니다 |
| 라우터 진입 | transaction-api 8000 ← namespace 라벨 `policy-group.network.openshift.io/ingress: ""` | 클러스터에서 라벨 확인 필요 |
| DNS | 두 앱 → `openshift-dns`의 `dns.operator.openshift.io/daemonset-dns: default` 5353·53 UDP/TCP | 서비스 53 → Pod 5353 |
| 넣지 않는 것 | 고정 UID/GID, pull secret, 모니터링 수집 경로 | UID는 restricted-v2 SCC 배정, 레지스트리는 #42, 모니터링은 별도 결정 |

Route 음성 시험(실제 클러스터에서 수행, 아직 NOT RUN): 같은 host의 `/metrics`·`/livez`·`/`는 라우터 503, `http://`는 HTTPS Redirect, `/api/v1/transactions`·`/readyz`만 앱 응답.

## 시험 DB — components/lab-db (명시적 opt-in)

권욱님 리뷰 §2·§3의 (가) 구현 조건을 이 절에 둡니다. **이 PR은 시험 DB 생성·실행 GO가 아닙니다.** ROSA·공용 Lab에서 쓰기 전에 해당 Lead 판단을 받습니다.

| 항목 | 정한 값 |
|---|---|
| 적용 범위 | `components`로만 존재합니다. base·p1-onprem·기본 rosa overlay는 포함하지 않습니다. 쓰는 overlay가 `components:`에 명시합니다 |
| 이미지 | `registry.access.redhat.com/rhel9/postgresql-16@sha256:560660218b67e9f26dffdc70b8f790903095fe0035604af14376b1dbfd3026fb`(태그 `9.8-1791289385`, PostgreSQL 16.15, 2026-10-06 빌드, Red Hat 등급 A). 임의 UID용 이미지, db01(16.14)과 같은 16 계열. 레지스트리 출처는 #42 결정과 별도로 승인받습니다 |
| 데이터 | `emptyDir`(HOME 1Gi). PVC·StorageClass 없음. Pod가 다시 만들어지면 빈 DB에 schema만 다시 적용되고 시험 이력은 사라집니다. raw 증적은 실행 직후 수집합니다 |
| schema | `fds-schema.sql` = 루트 `alembic/versions` head `0003`의 offline SQL(생성물, 직접 수정 금지). 파일 머리에 migration 3개의 SHA-256을 적었고, 시험이 현재 파일과 대조합니다. 이미지의 `postgresql-init` 단계에서 `10-fds-schema.sh`가 앱 계정 소유로 1회 적용합니다. 실패하면 컨테이너가 종료돼 빈 DB로 Ready가 되지 않습니다 |
| 시험 데이터 | DB에 직접 넣지 않습니다. `tools/regression/p2e2e.py`가 고유 계정 `SIM_p2_<RUN>_<ID>`·고유 Transaction ID로 API를 호출해 이력을 만들고, 기대 Rule 결과는 실행 전 고정한 plan(SHA 결속)을 따릅니다. 운영 DB 데이터·credential은 복사하지 않습니다 |
| 네트워크 | 진입은 transaction-api → 5432만(`fds-lab-db-allow`). 시험 DB의 egress 규칙은 없습니다(전부 차단). fds-engine에는 DB 경로가 없습니다. Service는 ClusterIP, Route·NodePort 없음 |
| 보안 | `runAsNonRoot`, RuntimeDefault, 권한 상승 금지, 읽기 전용 루트, `drop ALL`, SA 토큰 자동 마운트 끔, 서비스 링크 env 끔. broad SCC·root·cluster-wide Operator를 쓰지 않습니다 |
| 자원 | 요청 100m/256Mi, 제한 500m/512Mi, replicas 1 |
| owner·만료 | `fds.321team/owner`·`fds.321team/expires` 주석. 실제 overlay가 값을 넣습니다 |

### 자격증명 Secret (저장소 밖에서 생성, 값 출력 금지)

```bash
NS=<namespace>
PW=$(openssl rand -hex 24)
oc -n "$NS" create secret generic fds-lab-db-credentials \
  --from-literal=POSTGRESQL_USER=fds_lab --from-literal=POSTGRESQL_PASSWORD="$PW" --from-literal=POSTGRESQL_DATABASE=fds_lab
oc -n "$NS" create secret generic transaction-api-db-credentials \
  --from-literal=DATABASE_URL="postgresql+asyncpg://fds_lab:${PW}@fds-lab-db:5432/fds_lab"
unset PW
oc -n "$NS" label secret fds-lab-db-credentials app.kubernetes.io/part-of=fds-lab-db
oc -n "$NS" label secret transaction-api-db-credentials fds.321team/db-target=test-db
```

`transaction-api-db-credentials`에는 `part-of=fds-lab-db`를 붙이지 않습니다. 시험 DB를 정리해도 앱 Secret 이름은 남고, #47 전환 때 값과 `db-target` 라벨만 바뀝니다.

### 정리와 readback

1. 시험 DB를 뺀 overlay를 먼저 apply합니다. transaction-api의 시험 DB egress 규칙이 사라집니다.
2. 시험 DB 자원을 지웁니다.

```bash
oc -n "$NS" delete deployment,service,serviceaccount,networkpolicy,configmap,secret -l app.kubernetes.io/part-of=fds-lab-db
oc -n "$NS" get all,configmap,secret,networkpolicy -l app.kubernetes.io/part-of=fds-lab-db   # 기대: No resources found
oc -n "$NS" get networkpolicy transaction-api-allow -o yaml | grep -c fds-lab-db                # 기대: 0
```

emptyDir라 남는 볼륨이 없습니다. readback 출력은 증적에 보존합니다.

### #47 전환 계약 — TEST_DB → ONPREM_DB

| 단계 | 내용 | 실패 시 |
|---|---|---|
| 0. 기록 | 전환 전 manifest revision(fds-msa SHA), 렌더 SHA-256, Secret **이름**·`db-target` 라벨, NetworkPolicy를 기록합니다 | — |
| 1. 선행 | #47 A1·A2(db01 출발지 관측·pg_hba/방화벽 변경)가 끝나야 시작합니다 | 시작하지 않음 |
| 2. 앱 Secret 교체 | `transaction-api-db-credentials`를 db01 접속값(TLS)으로 교체, 라벨 `db-target=onprem-db`. 이때 `fds-lab-db-credentials`와 시험 DB는 남겨 둡니다 | 3단계로 가지 않고 이전 값으로 복구 |
| 3. overlay 교체 | 시험 DB를 뺀 overlay + db01 egress(Relay 경유 `10.1.93.55/32:5432`, 별도 PR)를 apply, transaction-api 재시작 | 이전 overlay revision 재적용 + 시험 DB 값으로 Secret 복구 → Ready 재확인 |
| 4. 새 경로 검증 | 두 앱 Ready, Route `/readyz`, 저장·조회(p2e2e B1), fds-engine → DB 차단, VPN 끊김·복구(#50) | 3단계 복구 절차 |
| 5. 시험 DB 정리 | 4단계 통과 뒤에만 위 "정리와 readback"을 수행합니다 | — |

시험 DB 데이터는 운영 DB(db01)로 옮기지 않습니다. 시험 DB에서 얻은 결과는 `#43 ROSA APP / TEST_DB`로, db01 경로 결과는 `#47/#50 ROSA_HYBRID / ONPREM_DB`로 따로 기록합니다.

### 아직 확인하지 못한 것 (LAB-PRECHECK 1단계에서 확인, NOT VERIFIED)

- 이 이미지가 임의 UID + 읽기 전용 루트 + emptyDir HOME에서 initdb·기동하는지
- `postgresql-init` 스크립트가 계정·DB 생성 뒤에 실행되는지(테이블 소유자가 `fds_lab`인지 readback)
- `check-container` probe 동작, 레지스트리 pull 가능 여부(Lab·ROSA egress)
- 라우터 namespace 라벨·openshift-dns 라벨이 해당 클러스터에서 맞는지

실패하면 원인 로그를 보존하고, 보안 설정을 푸는 변경은 별도 리뷰를 거칩니다.

## 렌더 확인

`overlays/openshift-render-check`는 자리표시값으로 렌더만 확인합니다(apply 금지). 클러스터 접속 없이 실행됩니다.

```bash
kubectl kustomize deploy/overlays/openshift-render-check > rendered-openshift.yaml
```

정적 시험: `tools/tests/test_deploy_openshift_labdb.py`. 실제 PostgreSQL에 schema 스크립트를 적용하는 시험은 `initdb`가 있는 CI Ubuntu 러너에서 실행됩니다. 앱 계정 소유, `alembic_version=0003`, 컬럼·인덱스, 깨진 SQL이면 종료·롤백을 확인합니다.

## 다음 (아직 없음)

- `overlays/ocp-lab`: namespace(#34 Lab 경계 `j1-`/`j2-`), 레지스트리(#42), Route host, owner·만료가 정해진 뒤 작성합니다
- `overlays/rosa`: #38 Basic Ready·#42 결정 뒤 작성합니다
- db01 egress component: #47 전환 단계 3에서 사용합니다
