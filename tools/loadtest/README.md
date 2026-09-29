# P1-APP-01 부하 시험 도구

P1-APP-01 [#15](https://github.com/321Team/fds-project-baseline/issues/15) 핵심 요구 "Workload별 Request/Limit을 부하 시험으로 확정한다"를 판정하는 부하 시험에 쓰는 스크립트다. 목표 부하·합격 기준·산식·관측 query는 [결정안 v2](https://github.com/321Team/fds-project-baseline/issues/15#issuecomment-5885861552)와 [G3 확인](https://github.com/321Team/fds-project-baseline/issues/15#issuecomment-5886568007)을 따른다.

운영 서버에서 부하를 발생시키는 코드라서 실행 전에 독립 코드 리뷰를 받는다(REVIEW_AUTHORITY_POLICY §3, §3.2 4-1(5)). 실행 기록에는 리뷰를 마친 SHA와 실제로 실행한 파일의 SHA-256이 같음을 남긴다.

## 파일

| 파일 | 실행 위치 | 역할 | SHA-256 |
|---|---|---|---|
| `gen2.py` | edge01 | 부하 생성 | `60f09400221775a015afc17fc69a2ed600dd73e786cb12216c8601ae768c2916` |
| `q_range.py` | k8s-control01 | Prometheus 조회(읽기 전용) | `5b59d0d5d8205154b350377599645734f801154f1532681453a8cf27b65cfd85` |
| `promql.txt` | k8s-control01 | `q_range.py`가 읽는 query·집계 규칙 | `deccc54929862a137de59ae8f4d32b62b23a4461a2de77249381eb19863d91a1` |

세 파일은 2026-09-29 RUN `202609291754`에서 실행한 파일과 바이트가 같다. 그 RUN은 이 리뷰를 거치지 않아 진단·이력 증적으로만 편입했다([fds-project-evidence#75](https://github.com/321Team/fds-project-evidence/pull/75)). 판정에 쓸 RUN은 이 PR 리뷰를 마친 뒤 새로 실행한다.

## `gen2.py`

```
python3 gen2.py <RUN> <OUT_DIR> > <OUT_DIR>/stages.log 2>&1
```

- 대상: `10.1.93.105`, `10.1.93.107`, `10.1.93.108`의 `:30080`(NodePort)에 요청마다 순서대로 보낸다. `POST /api/v1/transactions`
- 단계: B 20 rps 600초 → P 50 rps 180초 → 부하 없이 120초 관찰(총 21,000건). 값은 코드에 고정했다(결정안 v2 전용).
- 요청: 요청마다 새 계정 `SIM_load_<RUN>_<n>`, 입금 60·출금 20·이체 20%(시드 = RUN), 10,000원, `source_ip` 198.51.100.10(문서용 IP). R01/R02/R04/R07이 걸리지 않는 입력이다.
- 동시성: 스레드 64개 상한, 요청마다 새 연결, timeout 10초. 예외는 상태 코드 `-1`로 기록한다.
- 출력: `<OUT_DIR>/requests.log`(한 줄에 `시작epoch 단계 Worker 유형 상태코드 지연ms`), 표준 출력(단계 시작·끝 epoch, 30초마다 누적 상태 코드). 30초마다 로그를 디스크에 쓴다.
- 표준 라이브러리만 쓴다(Python 3.6 이상).

## `q_range.py`

```
python3 q_range.py check                  # 사전 점검·감시: Q1~Q3 instant 조회, Pod별 값 출력
python3 q_range.py <start> <end>          # 판정용: query_range(step 15초) → q1.json·q2.json·q3.json
```

- 현재 폴더의 `promql.txt`에서 `Q1_`·`Q2_`·`Q3_` 줄을 읽는다.
- `http://127.0.0.1:19091`(control01에서 `monitoring-api/prometheus` 9090으로 띄운 이 시험 전용 port-forward)에 조회만 한다. 쓰기·설정 변경은 없다.

## 운영 영향과 중단

- 운영 `fdsdb`에 시험 거래 21,000건이 쌓인다. Deployment·Resource·설정은 바꾸지 않는다.
- 부하는 약 15분, 최대 50 rps다. 시작 전에 팀 채팅으로 공지한다.
- 시작 조건: `gen2.py`의 SHA-256이 위 표와 같고, Worker 3대 `/readyz`가 모두 200일 때만 시작한다.
- 중단: 진행 로그에서 30초 사이 201 외 코드가 10건 이상 늘거나 Pod NotReady·재시작이 보이면 `kill <PID>`로 멈춘다. 그 RUN은 불합격으로 기록한다.
