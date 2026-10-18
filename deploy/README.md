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
├── delivery/rosa.yaml       ROSA 전달 허용목록(기계 판독) — tools/check_delivery_render.py가 읽음
├── DELIVERY-CONTRACT-rosa.md  #43 생산 / #46 소비 배포 입력 계약
└── overlays/
    ├── p1-onprem/               Phase 1 운영(fds-app) 재현 — 비교 전용, apply하지 않음
    ├── openshift-render-check/  base + openshift + lab-db 렌더 확인 전용 — 자리표시값, apply하지 않음
    ├── rosa-app/                ROSA 앱 전용 렌더(Deployment·Service·Route) — 배포 SA가 적용. 자리표시값이 남으면 전달 거부
    └── rosa-prereq/             ROSA 사전 자원 중 앱 SA·앱 NetworkPolicy — #5/#7 실행자가 배포 전 적용
```

ROSA 전달은 [DELIVERY-CONTRACT-rosa.md](DELIVERY-CONTRACT-rosa.md)를 따릅니다. 배포 SA가 base 전체를 적용하지 않도록 앱 렌더와 사전 자원 렌더를 나눴습니다.

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
| host | 자리표시값 `fds-api.route-host-input-pending.invalid` | 실제 overlay가 클러스터 apps 도메인 아래 값으로 바꿉니다. ROSA는 `rosa-app`이 `delivery/rosa.yaml` 승인 host로 바꿉니다(2026-10-18) |
| 라우터 진입 | transaction-api 8000 ← namespace 라벨 `policy-group.network.openshift.io/ingress: ""` | 클러스터에서 라벨 확인 필요 |
| DNS | 두 앱 → `openshift-dns`의 `dns.operator.openshift.io/daemonset-dns: default` 5353·53 UDP/TCP | 서비스 53 → Pod 5353 |
| 넣지 않는 것 | 고정 UID/GID, pull secret, 모니터링 수집 경로 | UID는 restricted-v2 SCC 배정, 레지스트리는 #42, 모니터링은 별도 결정 |

Route 음성 시험(실제 클러스터에서 수행, 아직 NOT RUN): 같은 host의 `/metrics`·`/livez`·`/`는 라우터 503, `http://`는 HTTPS Redirect, `/api/v1/transactions`·`/readyz`만 앱 응답.

## 시험 DB — components/lab-db (명시적 opt-in)

권욱님 리뷰 §2·§3의 (가) 구현 조건을 이 절에 둡니다. **이 PR은 시험 DB 생성·실행 GO가 아닙니다.** ROSA·공용 Lab에서 쓰기 전에 해당 Lead 판단을 받습니다.

| 항목 | 정한 값 |
|---|---|
| 적용 범위 | `components`로만 존재합니다. base·p1-onprem·기본 rosa overlay는 포함하지 않습니다. 쓰는 overlay가 `components:`에 명시합니다 |
| 이미지 | `quay.io/sclorg/postgresql-16-c9s@sha256:d33717fd33c1a4b11afef94568d0c20812a19d62fb8c633fadee1e491e2edd4a`(태그 `20260930`, CentOS Stream 9, user 26, PostgreSQL 16.8 — CI `postgres --version` 출력). 임의 UID용 이미지이고, db01(16.14)과 같은 16 계열입니다. 레지스트리 출처는 #42 결정과 별도로 승인받습니다. **익명으로 pull할 수 있어서, 같은 digest로 실제 시작 경로를 CI에서 시험합니다**(아래 렌더 확인 절). Red Hat `rhel9/postgresql-16`은 `registry.redhat.io` 인증(이용약관 동의)이 필요해 처음 고른 것에서 바꿨습니다. 두 이미지는 같은 upstream 시작 스크립트를 씁니다. 커뮤니티 빌드라 Red Hat 지원·등급은 없고, 임시 시험 DB 용도로만 씁니다 |
| 데이터 | `emptyDir`(HOME 1Gi). PVC·StorageClass 없음. Pod가 다시 만들어지면 빈 DB에 schema만 다시 적용되고 시험 이력은 사라집니다. raw 증적은 실행 직후 수집합니다 |
| schema | `fds-schema.sql` = 루트 `alembic/versions` head `0003`의 offline SQL(생성물, 직접 수정 금지). 파일 머리에 migration 3개의 SHA-256을 적었고, 시험이 현재 파일과 대조합니다. `10-fds-schema.sh`는 이미지의 `postgresql-start` 훅입니다. 이미지 시작 스크립트(`run-postgresql`)가 계정·DB를 만든 **뒤**, 서버를 소켓 전용으로 띄운 상태에서 **매 시작마다** 실행합니다. 훅이 끝나야 TCP로 서비스합니다. 동작은 세 가지입니다. ① `public`이 비어 있으면 앱 계정 소유로 한 트랜잭션에 적용하고, 다시 확인합니다. ② `alembic_version`이 `0003` 한 행이고 `transactions`가 있으면 재적용하지 않습니다. ③ 그 밖의 상태(부분 적용, 다른 버전, 확인 실패)면 컨테이너를 끝냅니다. 같은 데이터로 재시작해도 같은 확인에서 다시 멈추므로, schema 없는 DB가 Ready가 되지 않습니다 |
| 시험 데이터 | DB에 직접 넣지 않습니다. `tools/regression/p2e2e.py`가 고유 계정 `SIM_p2_<RUN>_<ID>`·고유 Transaction ID로 API를 호출해 이력을 만들고, 기대 Rule 결과는 실행 전 고정한 plan(SHA 결속)을 따릅니다. 운영 DB 데이터·credential은 복사하지 않습니다 |
| 네트워크 | 진입은 transaction-api → 5432만(`fds-lab-db-allow`). 시험 DB의 egress 규칙은 없습니다(전부 차단). fds-engine에는 DB 경로가 없습니다. Service는 ClusterIP, Route·NodePort 없음 |
| 보안 | `runAsNonRoot`, RuntimeDefault, 권한 상승 금지, 읽기 전용 루트, `drop ALL`, SA 토큰 자동 마운트 끔, 서비스 링크 env 끔. broad SCC·root·cluster-wide Operator를 쓰지 않습니다 |
| 자원 | 요청 100m/256Mi, 제한 500m/512Mi, replicas 1 |
| owner·만료 | `fds.321team/owner`·`fds.321team/expires` 주석. 실제 overlay가 값을 넣습니다 |

### 대상 고정 — 모든 명령에 `--context`·`-n`

아래 명령은 `oc`의 현재 프로젝트에 의존하지 않습니다. 공용 Lab에서는 현재 프로젝트가 다른 팀 namespace일 수 있기 때문입니다. 실행자는 작업 시작 때 승인된 cluster context와 namespace를 정해 실행 기록 첫머리에 남깁니다.

```bash
CTX=<승인된 context>
NS=<승인된 namespace>
oc --context "$CTX" whoami --show-context
oc --context "$CTX" get namespace "$NS" -o name
```

아래 블록은 모두 서브셸 `( … )`입니다. 단계가 실패하면 `exit 1`로 그 블록만 끝나고, 터미널은 닫히지 않습니다. `CTX`·`NS`가 비어 있으면 시작하지 않습니다.

### 자격증명 Secret (저장소 밖에서 생성, 값 출력 금지)

```bash
(
  : "${CTX:?승인된 context 필요}"; : "${NS:?승인된 namespace 필요}"
  PW=$(openssl rand -hex 24)
  oc --context "$CTX" -n "$NS" create secret generic fds-lab-db-credentials \
    --from-literal=POSTGRESQL_USER=fds_lab --from-literal=POSTGRESQL_PASSWORD="$PW" \
    --from-literal=POSTGRESQL_DATABASE=fds_lab || { echo "STOP: 시험 DB Secret 생성 실패"; exit 1; }
  oc --context "$CTX" -n "$NS" create secret generic transaction-api-db-credentials \
    --from-literal=DATABASE_URL="postgresql+asyncpg://fds_lab:${PW}@fds-lab-db:5432/fds_lab" \
    || { echo "STOP: 앱 Secret 생성 실패"; exit 1; }
  unset PW
  oc --context "$CTX" -n "$NS" label secret fds-lab-db-credentials app.kubernetes.io/part-of=fds-lab-db || exit 1
  oc --context "$CTX" -n "$NS" label secret transaction-api-db-credentials fds.321team/db-target=test-db || exit 1
)
```

`transaction-api-db-credentials`에는 `part-of=fds-lab-db`를 붙이지 않습니다. 시험 DB를 정리해도 앱 Secret 이름은 남고, #47 전환 때 값과 `db-target` 라벨만 바뀝니다.

### 정리와 readback

1. 시험 DB를 뺀 overlay를 먼저 apply합니다(`oc --context "$CTX" -n "$NS" apply -k <overlay>`). transaction-api의 시험 DB egress 규칙이 사라집니다. overlay의 namespace가 `$NS`와 다르면 `oc`가 거부하므로 대상 확인도 됩니다.
2. 아래 블록을 실행합니다. 각 단계의 원본 출력과 rc를 파일로 남기고, 조회 결과와 판정을 분리합니다.

```bash
(
  : "${CTX:?승인된 context 필요}"; : "${NS:?승인된 namespace 필요}"
  oc --context "$CTX" -n "$NS" delete deployment,service,serviceaccount,networkpolicy,configmap,secret     -l app.kubernetes.io/part-of=fds-lab-db > cleanup.delete.txt 2> cleanup.delete.err
  echo $? > cleanup.delete.rc
  [ "$(cat cleanup.delete.rc)" = 0 ] || { echo "STOP: 삭제 명령 실패"; exit 1; }

  # 삭제 대상과 그 하위 자원(ReplicaSet·Pod)을 kind로 모두 적는다. `all`은 ServiceAccount 등을 포함하지 않는다.
  oc --context "$CTX" -n "$NS" get deployment,replicaset,pod,service,serviceaccount,configmap,secret,networkpolicy     -l app.kubernetes.io/part-of=fds-lab-db -o name > cleanup.remaining.txt 2> cleanup.remaining.err
  echo $? > cleanup.remaining.rc
  [ "$(cat cleanup.remaining.rc)" = 0 ] || { echo "STOP: 잔여 조회 실패(권한·API 오류)"; exit 1; }
  [ -s cleanup.remaining.txt ] && { echo "STOP: 잔여 자원 있음"; cat cleanup.remaining.txt; exit 1; }

  # 조회 성공(rc 0)을 확인한 뒤에만 내용을 판정한다. grep rc 1 = 일치 없음, 0 = 잔여 규칙, 2 이상 = 검사 오류.
  oc --context "$CTX" -n "$NS" get networkpolicy transaction-api-allow -o yaml     > cleanup.api-policy.yaml 2> cleanup.api-policy.err
  echo $? > cleanup.api-policy.rc
  [ "$(cat cleanup.api-policy.rc)" = 0 ] || { echo "STOP: 정책 조회 실패"; exit 1; }
  grep -c fds-lab-db cleanup.api-policy.yaml > cleanup.api-policy.match
  echo $? > cleanup.api-policy.match.rc
  [ "$(cat cleanup.api-policy.match.rc)" = 1 ] || { echo "STOP: 잔여 규칙 있음 또는 검사 오류"; exit 1; }
  echo "CLEANUP_OK"
)
```

| 경우 | 결과 |
|---|---|
| 모두 삭제됨 | `CLEANUP_OK` |
| 일부 자원 남음(ServiceAccount만 남은 경우 포함) | `STOP: 잔여 자원 있음` + 이름 목록 |
| 조회 Forbidden·API 오류 | `STOP: … 조회 실패`(`*.rc` ≠ 0, `*.err`에 원인) |
| transaction-api 정책에 시험 DB 규칙 남음 | `STOP: 잔여 규칙 있음 또는 검사 오류` |

emptyDir라 남는 볼륨이 없습니다. `transaction-api-db-credentials`는 삭제 라벨이 없어 대상이 아닙니다. `cleanup.*` 파일(값 없음)은 증적에 보존합니다.

### #47 전환 계약 — TEST_DB → ONPREM_DB

| 단계 | 내용 | 실패 시 |
|---|---|---|
| 0. 기록 | 전환 전 manifest revision(fds-msa SHA), 렌더 SHA-256, Secret **이름**·`db-target` 라벨, NetworkPolicy를 기록합니다 | — |
| 1. 선행 | #47 A1·A2(db01 출발지 관측·pg_hba/방화벽 변경)가 끝나야 시작합니다 | 시작하지 않음 |
| 2. 앱 Secret 교체 | `transaction-api-db-credentials`를 db01 접속값(TLS)으로 교체, 라벨 `db-target=onprem-db`. 이때 `fds-lab-db-credentials`와 시험 DB는 남겨 둡니다 | 3단계로 가지 않고 이전 값으로 복구 |
| 3. overlay 교체 | 시험 DB를 뺀 overlay(ROSA는 `rosa-app`) + db01 egress(Relay 경유 `10.1.93.55/32:5432`. ROSA는 플랫폼 NP 03과 `onprem-egress` 라벨, [계약 3절](DELIVERY-CONTRACT-rosa.md))를 같은 `CTX`·`NS`로 apply하고, `oc --context "$CTX" -n "$NS" rollout restart deployment/transaction-api` 후 `rollout status deployment/transaction-api --timeout=<작업창 상한>`까지 확인 | 아래 "전환 실패 복구" 순서 |
| 4. 새 경로 검증 | 두 앱 Ready, Route `/readyz`, 저장·조회(p2e2e B1), fds-engine → DB 차단, VPN 끊김·복구(#50) | 아래 "전환 실패 복구" 순서 |
| 5. 시험 DB 정리 | 4단계 통과 뒤에만 위 "정리와 readback"을 수행합니다 | — |

**전환 실패 복구** — `DATABASE_URL`은 env의 `secretKeyRef`라 실행 중인 Pod에는 반영되지 않습니다. 그래서 Secret을 먼저 되돌리고, 그다음 재시작합니다.

```bash
(
  : "${CTX:?승인된 context 필요}"; : "${NS:?승인된 namespace 필요}"
  : "${PREV_OVERLAY:?0단계에 기록한 이전 revision의 overlay 경로 필요}"
  OC="oc --context $CTX -n $NS"
  # 1. 앱 Secret을 시험 DB 값으로 먼저 복구한다. 값은 fds-lab-db-credentials에서 읽어 바로 넣고 출력하지 않는다.
  U=$($OC get secret fds-lab-db-credentials -o jsonpath='{.data.POSTGRESQL_USER}' | base64 -d)
  P=$($OC get secret fds-lab-db-credentials -o jsonpath='{.data.POSTGRESQL_PASSWORD}' | base64 -d)
  D=$($OC get secret fds-lab-db-credentials -o jsonpath='{.data.POSTGRESQL_DATABASE}' | base64 -d)
  [ -n "$U" ] && [ -n "$P" ] && [ -n "$D" ] || { echo "STOP: 시험 DB Secret 읽기 실패"; exit 1; }
  $OC create secret generic transaction-api-db-credentials     --from-literal=DATABASE_URL="postgresql+asyncpg://${U}:${P}@fds-lab-db:5432/${D}" --dry-run=client -o yaml     | $OC apply -f - || { echo "STOP: 앱 Secret 복구 실패"; exit 1; }
  unset U P D
  $OC label secret transaction-api-db-credentials fds.321team/db-target=test-db --overwrite || exit 1
  # 2. 이전 overlay revision 재적용(overlay namespace가 $NS와 다르면 oc가 거부한다)
  $OC apply -k "$PREV_OVERLAY" || { echo "STOP: 이전 overlay 재적용 실패"; exit 1; }
  # 3. env를 다시 읽도록 재시작하고 끝까지 확인한다(상한은 작업창에 맞춘다)
  $OC rollout restart deployment/transaction-api || { echo "STOP: restart 실패"; exit 1; }
  $OC rollout status deployment/transaction-api --timeout=180s || { echo "STOP: rollout 미완료"; exit 1; }
  echo "ROLLBACK_APPLIED"
)
```

4. `ROLLBACK_APPLIED`가 나온 뒤에만 시험 DB 저장·조회와 두 앱 Ready를 재확인합니다.
5. 어느 단계든 `STOP`이면 중단하고 로그를 보존합니다. 저장·조회 판정이나 시험 DB 정리로 넘어가지 않고, 시험 DB는 삭제하지 않습니다.

시험 DB 데이터는 운영 DB(db01)로 옮기지 않습니다. 시험 DB에서 얻은 결과는 `#43 ROSA APP / TEST_DB`로, db01 경로 결과는 `#47/#50 ROSA_HYBRID / ONPREM_DB`로 따로 기록합니다.

### 아직 확인하지 못한 것 (LAB-PRECHECK 1단계에서 확인, NOT VERIFIED)

- 이 이미지가 임의 UID + 읽기 전용 루트 + emptyDir HOME에서 initdb·기동하는지
- 위 시작 순서는 upstream [`16/root/usr/bin/run-postgresql`](https://github.com/sclorg/postgresql-container/blob/b455357a2e281bb224c547dbf948cc8745937181/16/root/usr/bin/run-postgresql) 기준입니다(`postgresql-init` → `migrate_db` → `create_users` → `postgresql-start`). 고정 digest 안의 실제 동작은 `tools/tests/test_labdb_image_entrypoint.py`(workflow `labdb-image-it`)로 확인합니다. 클러스터 SCC·fsGroup 아래 동작은 Lab에서 다시 확인합니다
- `check-container` probe 동작, 레지스트리 pull 가능 여부(Lab·ROSA egress)
- 라우터 namespace 라벨·openshift-dns 라벨이 해당 클러스터에서 맞는지

실패하면 원인 로그를 보존하고, 보안 설정을 푸는 변경은 별도 리뷰를 거칩니다.

## 렌더 확인

`overlays/openshift-render-check`는 자리표시값으로 렌더만 확인합니다(apply 금지). 클러스터 접속 없이 실행됩니다.

```bash
kubectl kustomize deploy/overlays/openshift-render-check > rendered-openshift.yaml
```

정적 시험은 `tools/tests/test_deploy_openshift_labdb.py`입니다. CI Ubuntu 러너에서는 다음 두 시험도 실행됩니다.
- `kubectl kustomize` 렌더 시험: p1-onprem 12개, render-check 16개
- 실제 PostgreSQL 훅 시험: 빈 DB 적용(앱 계정 소유, `alembic_version=0003`, 컬럼·인덱스), 재실행 멱등, 깨진 SQL이면 실패·롤백하고 다시 실행해도 실패, 고친 SQL로 복구, 부분 상태·다른 버전이면 중단

`tools/tests/test_labdb_image_entrypoint.py`(workflow `labdb-image-it`, lab-db 변경 PR에서 실행)는 **고정 digest 이미지를 실제 시작 경로로** 띄웁니다. 조건은 임의 UID(gid 0), 읽기 전용 루트, `--cap-drop ALL`, `no-new-privileges`, Docker 기본 seccomp, `--network none`입니다. 컨테이너 보안 설정은 매니페스트와 같게 맞췄지만, 다음은 **다릅니다**.
- 쓰기 볼륨이 host 디렉터리 `0777`입니다. 실제 클러스터의 emptyDir 소유권, SCC가 배정하는 UID/GID·fsGroup, SELinux는 재현하지 않습니다.
- CPU·memory 제한이 없습니다.
- 런타임이 Docker입니다(CRI-O 아님).

이 차이는 Lab·ROSA 실제 기동에서 확인합니다. 현장에서 `0777`이나 anyuid로 우회하지 않습니다. 확인하는 것:
1. 빈 HOME 첫 기동
2. 같은 데이터로 재시작
3. 깨진 SQL이면 Ready 전에 종료하고, 같은 데이터로 다시 시작해도 종료
4. 고친 SQL로 복구
5. 이미지 안 `run-postgresql`의 훅 순서

## 다음 (아직 없음)

- `overlays/ocp-lab`: namespace(#34 Lab 경계 `j1-`/`j2-`), 레지스트리(#42), Route host, owner·만료가 정해진 뒤 작성합니다
- ROSA: `overlays/rosa-app`·`rosa-prereq`는 계약 준비본입니다. 레지스트리·digest(#42·#46), Route host(#38)를 받으면 자리표시값을 바꿉니다
- ROSA db01 egress: 앱 NetworkPolicy에 넣지 않고 플랫폼 NP `allow-egress-onprem-approved`(infra-rosa#7)와 Pod 라벨 `onprem-egress: "true"`로 엽니다([계약 3절](DELIVERY-CONTRACT-rosa.md), infra-rosa#7 확정). 시험 DB에서 db01로 바꾸는 단계 3은 이 경로를 씁니다
