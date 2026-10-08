# deploy — portable workload base + 환경별 overlay

P2-APP-01 [#43](https://github.com/321Team/fds-project-baseline/issues/43)의 portable base입니다. 권욱님 리뷰([6041356020](https://github.com/321Team/fds-project-baseline/issues/43#issuecomment-6041356020))와 W0 계획(`audit/phase2-rosa-topology-review-20261002/w0-portability-precheck.md`)의 구분을 따릅니다. 앱 코드와 이미지는 바꾸지 않습니다.

## 구조

```text
deploy/
├── base/                    어디서나 같은 앱 계약
│   ├── transaction-api.yaml ServiceAccount·Deployment·Service(ClusterIP)
│   ├── fds-engine.yaml      ServiceAccount·Deployment·Service(ClusterIP, 외부 노출 없음)
│   └── networkpolicy.yaml   기본 차단 + transaction-api → fds-engine 8001
└── overlays/
    └── p1-onprem/           Phase 1 운영(fds-app) 재현 — 비교 전용, apply하지 않음
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

## 다음 (이 디렉터리에 추가 예정, 아직 없음)

- `components/openshift`: Route(경로 `/api`·`/readyz`만, `/metrics` 비노출), openshift-dns(53·5353)·라우터 허용 NetworkPolicy
- `components/lab-db`: 공용 OCP Lab용 임시 PostgreSQL(명시적 opt-in, 기본 overlay에 포함하지 않음)
- `overlays/ocp-lab`, `overlays/rosa`
