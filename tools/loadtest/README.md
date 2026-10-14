# P1-APP-01 부하 시험 도구

P1-APP-01 [#15](https://github.com/321Team/fds-project-baseline/issues/15) 핵심 요구 "Workload별 Request/Limit을 부하 시험으로 확정한다"를 판정하는 부하 시험에 쓰는 스크립트다. 목표 부하·합격 기준·산식·관측 query는 [결정안 v2](https://github.com/321Team/fds-project-baseline/issues/15#issuecomment-5885861552)와 [G3 확인](https://github.com/321Team/fds-project-baseline/issues/15#issuecomment-5886568007)을 따른다.

운영 서버에서 부하를 발생시키는 코드라서 실행 전에 독립 코드 리뷰를 받는다(REVIEW_AUTHORITY_POLICY §3, §3.2 4-1(5)). 실행 기록에는 리뷰를 마친 SHA와 실제로 실행한 파일의 SHA-256이 같음을 남긴다.

## 파일

| 파일 | 실행 위치 | 역할 |
|---|---|---|
| `gen3.py` | edge01 | 부하 생성. 실패하면 멈춘다(fail-close, 아래) |
| `q_range.py` | k8s-control01 | Prometheus 조회(읽기 전용) |
| `promql.txt` | k8s-control01 | `q_range.py`가 읽는 query·집계 규칙 |
| `../tests/test_loadtest_gen.py` | CI | `gen3.py` selftest: 정상, 처리 용량 초과, 단계 끝 미완료, 오류 임계(단계 중간·단계 끝 마지막 구간) |

`q_range.py`·`promql.txt`는 2026-09-29 RUN `202609291754`에서 실행한 파일과 바이트가 같다. 그 RUN의 생성기 `gen2.py`(SHA-256 `60f09400…768c2916`)는 대기 요청 수에 상한이 없어 이 저장소에 두지 않고 `gen3.py`로 바꿨다. 그 RUN은 사전 리뷰가 없어 진단·이력 증적으로만 편입했다([fds-project-evidence#75](https://github.com/321Team/fds-project-evidence/pull/75)). 판정에 쓸 RUN은 이 도구의 리뷰를 마친 뒤 새로 실행한다.

## `gen3.py`

```
python3 gen3.py <RUN> <OUT_DIR> > <OUT_DIR>/stages.log 2>&1
```

- 대상: `10.1.93.105`, `10.1.93.107`, `10.1.93.108`의 `:30080`(NodePort)에 요청마다 순서대로 보낸다. `POST /api/v1/transactions`
- 단계: B 20 rps 600초 → P 50 rps 180초 → 부하 없이 120초 관찰(정상이면 21,000건). 값은 코드 상수로 고정했다(결정안 v2 전용).
- 요청: 요청마다 새 계정 `SIM_load_<RUN>_<n>`, 입금 60·출금 20·이체 20%(시드 = RUN), 10,000원, `source_ip` 198.51.100.10(문서용 IP). R01/R02/R04/R07이 걸리지 않는 입력이다.
- 연결: 요청마다 새 연결, timeout 10초. 예외는 상태 코드 `-1`로 기록한다.
- 발사 시각: 요청 n은 단계 시작 + n/rps초에 보낸다. 생성기가 잠시 멈췄다가 돌아오면 밀린 요청을 곧바로 보내므로 짧은 순간 목표보다 빠르게 보낼 수 있다. 판정 때 `requests.log`의 초당 시작 건수로 이런 몰림과 발사 지연을 함께 확인한다.
- 출력: `<OUT_DIR>/requests.log`(한 줄에 `시작epoch 단계 Worker 유형 상태코드 지연ms`), 표준 출력(`START`·`END`·`DRAINED`·`IDLE START`·`IDLE END` epoch, 30초마다 보낸 수·진행 중 요청 수·누적 상태 코드, 마지막 `DONE` 또는 `FAIL`). 30초마다 로그를 디스크에 쓴다.
- 표준 라이브러리만 쓴다(Python 3.6 이상).

### 이미지 전환 후 축약 회귀

[기존 결정안 v2 §8](https://github.com/321Team/fds-project-baseline/issues/15#issuecomment-5885861552)의
20 rps 120초 → 50 rps 120초를 `--profile regression`으로 선택한다(계획 8,400건).
기존 무부하 120초 관측과 요청·동시성·timeout·자동 중단 방식은 유지한다.
프로파일을 생략하거나 `--profile full`이면 기존 21,000건 전체 시험이다.

```text
python3 gen3.py <12자리_RUN> <새_OUT_DIR> --profile regression > <새_OUT_DIR>/stages.log 2>&1
```

실제 실행창·DB 사전0행·독립 리뷰·현재 형상 확인 후에만 사용한다.
`regression-attempt.json`을 배타적으로 생성하며 같은 OUT_DIR의 재실행 또는 기존
`requests.log`가 있으면 전송 전에 중단한다. 다른 OUT_DIR에 같은 RUN을 넣는 것은
이 검사로 막지 못하므로, DB 조회와 실행 기록으로 RUN을 별도 확인한다.
진행 중인 실행의 stages.log를 다시 redirection으로 덮어쓰지 않는다.

생성기 rc0은 발사·정리 정상 종료이며 합격 판정이 아니다. 요청 수/HTTP201 외0건,
Q1~Q3 원본·필수 시계열/유효 샘플, throttle<25%, restart/OOM0 및 기존 Resource
초과 징후를 따로 판정한다. 이 결과로 Resource를 재산정하지 않는다.
판정 실패 시 full profile 재시험이 후속이지만 자동 실행하지 않는다.
[준비 카드](../../docs/p1-short-load-regression-20261014.md)를 따른다.

**fail-close**

| 조건 | 기록 | 동작 |
|---|---|---|
| 보낼 시각에 진행 중 요청이 64개(상한) | `STOP LOAD_GENERATOR_SATURATED` | 새 요청을 멈춘다. 요청을 대기열에 쌓지 않으므로 다음 단계·관찰 구간으로 넘어가 시작되는 요청이 없다 |
| 단계가 끝나고 2초 안에 그 단계 요청이 다 끝나지 않음 | `STOP STAGE_NOT_DRAINED` | 다음 단계(또는 관찰)로 가지 않는다 |
| 30초 사이 201 외 응답이 10건 이상 늘어남 | `STOP ERROR_THRESHOLD` | 새 요청을 멈춘다 |
| 단계가 끝나 그 단계 요청이 모두 끝난 뒤, 마지막 30초 기록 이후 201 외 응답이 10건 이상 늘어남 | `STOP ERROR_THRESHOLD <단계> tail_errors <건수>` | 다음 단계(또는 관찰)로 가지 않는다 |

멈추면 이미 보낸 요청이 끝날 때까지(요청마다 10초 이내) 기다린 뒤 `FAIL <이유> outstanding 0`을 쓰고 종료 코드 2로 끝낸다. 정상이면 `DONE outstanding 0`을 쓰고 종료 코드 0이다. 멈춘 RUN은 불합격으로 기록한다.

## `q_range.py`

```
python3 q_range.py check                  # 사전 점검·감시: Q1~Q3 instant 조회, Pod별 값 출력
python3 q_range.py <start> <end>          # 판정용: query_range(step 15초) → q1.json·q2.json·q3.json
```

- 현재 폴더의 `promql.txt`에서 `Q1_`·`Q2_`·`Q3_` 줄을 읽는다.
- `http://127.0.0.1:19091`(control01에서 `monitoring-api/prometheus` 9090으로 띄운 이 시험 전용 port-forward)에 조회만 한다. 쓰기·설정 변경은 없다.

## 운영 영향과 중단

- 운영 `fdsdb`에 시험 거래가 최대 21,000건 쌓인다. Deployment·Resource·설정은 바꾸지 않는다.
- 부하는 약 15분, 최대 50 rps다. 시작 전에 팀 채팅으로 공지한다.
- 시작 조건: 실행할 `gen3.py`의 SHA-256이 리뷰를 마친 저장소 파일과 같고, Worker 3대 `/readyz`가 모두 200일 때만 시작한다.
- 수동 중단: Pod NotReady·재시작이 보이면 `kill <PID>`로 멈추고 그 RUN을 불합격으로 기록한다.
