# P1 D-03 실패 경로 — 격리 Runtime 실행 준비

관련: [E2E #20 후속 검토](https://github.com/321Team/fds-project-baseline/issues/20#issuecomment-6162223765), APP #15, Review #30.
상태: **코드·실행안 검토용. 신규 Runtime 창/공급/실행은 미승인·미실행.** CODEX_ASSISTED.

### 10/14 21:10 실행 실패 후 수정 검토

위 상태와 아래 준비 관측은 PR34 작성 당시 기록이다. [새 회차 결정](https://github.com/321Team/fds-project-baseline/issues/20#issuecomment-6167814983)으로 RUN `202610142110`을21:10:13 KST에1회 실행했으나 최초 DB `podman create`가 `unknown mount option "uid=26"`/rc125로 종료됐다. start/POST0, 원본 결과는 `CLEANUP_FAILED`다. CID 미확정 생성 실패를 자동 정리 성공으로 보지 않는 기존 보수적 판정을 유지한다. 21:11:35 읽기 확인은 이번4개 정확 이름 부재·전체컨테이너0·credential파일 부재·POST intent0·claim보존이며 원본 결과를 PASS로 바꾸지 않는다.

수정은 DB의 두 tmpfs에서 Podman6.1이 거부하는 `uid=26,gid=0`만 제거한다. [Podman v6.1.0 옵션 파서](https://github.com/containers/podman/blob/v6.1.0/pkg/util/mount_opts.go)는 tmpfs `size`/`mode`를 허용하고 해당 uid/gid 키는 거부한다. DB 프로세스의 `--user=26:0`, 두 디렉터리의 `mode=0770`, 크기·read-only·cap-drop·network-none·900초 상한은 유지한다. GID0의 쓰기/탐색 권한을 사용하며 world 쓰기나 root 실행으로 바꾸지 않는다. 실제 DB 기동·쓰기 가능 여부는 아직 확인되지 않았으며 다음 허용된 Runtime에서 판정한다.

새 MOCK은 `Lab.execute()`가 조립한 DB 인자를 받아 허용 옵션·UID:GID·group 권한·world 접근 부재·크기 상한을 확인하고 create 전에 중단한다. 실제 Podman 기동 시험을 대신하지 않는다. 이번 claim/실패 원본을 보존하고 자동 재실행하지 않는다. 수정 코드의 독립 리뷰·CI·병합, 새 plan/hash·새 RUN/창 결정이 끝나기 전 서버 번들을 고치거나 추가 컨테이너를 생성하지 않는다. 공급물은 이미 정확 digest/ID로 검증되어 다시 load/pull할 필요가 없다.

## 목적과 인수 범위

남은 세 경로(engine read timeout, engine HTTP 오류, DB INSERT 실패 rollback/HTTP500)를 배포된 앱의 불변 이미지와 실제 PostgreSQL로 재현한다. 기존 성공 회귀224·부하228, connect-failure90/CR119, DB readiness66을 반복하지 않는다. 전체 정본 Runtime/Phase1 인수와 구분한다.

**권장안:** `cicd-runner01`의 기존 UID1000 `server01_cicd-runner`가 rootless Podman으로 임시 DB/API/engine/fixture 네 컨테이너만 만든다. DB는 `--network=none`, 나머지는 정확한 DB CID의 네트워크를 공유한다. HTTP·DB 연결은 그 namespace 안의 `127.0.0.1`만 사용한다. 공개 포트, Kubernetes, db01 접속, Harbor Push/Deploy, 기존 Secret 읽기는 없다. Podman의 [none/container 네트워크 정의](https://docs.podman.io/en/latest/markdown/podman-run.1.html#network-mode-net)에 근거하고, 실행 시 실제 인터페이스가 lo뿐이고 IPv4 route가 비어 있는지 확인한 뒤 POST한다.

독립 검토에서 다음 두 판단을 구분한다.

1. 도구·실패 주입·격리·정리·증적 판정 코드가 실행 준비에 적절한지.
2. 이 시험이 성공하면 **고정 앱 이미지의 실패 처리 계약에 대한 격리 Runtime 근거**로 사용할 수 있는 범위. 이것만으로 운영 K8S 정책/TLS/db01 16.14/외부 경로·전체 E2E PASS를 주장하지 않는다. 시험 DB는 기존 저장소에 고정된 커뮤니티 PostgreSQL **16.8** 이미지이므로 운영 16.14와 patch 버전이 다르다. Phase1 D-03 최종 처분은 결과와 이 차이를 포함해 판단한다.

#43의 기존 ROSA 수신 기록이 참조한 #30 예외안은 철회됐다. 이 준비는 Phase2 이관 승인이나 기존 미충족의 면제가 아니다.

## 현재 준비 상태 — 2026-10-14 KST

| 항목 | 읽기 전용 조회 결과 |
|---|---|
| 15:45 Runner | hostname cicd-runner01, uid1000, Podman 6.1.0/rootless=true, 컨테이너0, Runner.Worker0 |
| 16:00 용량·기능 | 메모리 available 8,872MiB, `/home` 가용 약42.8GiB(15:45); create의 network/pull/timeout/stop-timeout 옵션 존재 |
| 16:26 이미지 ID 형식 | Podman6.1.0의 기존 캐시 이미지 `image inspect` JSON `Id`·`--format '{{.Id}}'` 모두 접두사 없는64자리. 형식 검증 후 `sha256:` 형태로 정규화하여 앱 config ID를 비교하고 원본 ID도 보존 |
| 기존 앱 공급물 | TBS38395350748 원본의 두 OCI archive가 그대로 존재하고 SHA256 일치(아래 표) |
| 로컬 이미지 | 두 앱·시험 DB가 Podman store에 없음. load/pull 미실행 |
| 검증 | 새 도구의 정적·합성/loopback fixture selftest를 수행. 실제 앱/DB 컨테이너 통합, Runtime, 독립 승인, 새 실행창은 별도 |

관측 시점의 상태이며 실제 실행 직전 다시 확인한다. 로컬 조회 원본·collector·receipt는 `deliverables/phase1-d03-preparation-20261014/{runner-inventory,supply-read-v2}/`에 보존한다. 최초 공급 조회는 검색 결과 수 제한에서 중단됐고 파일 경로를 두 고정 archive로 좁힌 뒤 위 결과를 수집했다. 두 조회 모두 host 변경/컨테이너 실행 0이다.

PR34 독립 리뷰의 두 차단사항은 저장소 경로 계산을 host 전용 명령으로 지연하고, 이미지 config ID의 접두사를 검증·정규화하도록 수정했다. `/d03/d03_lab.py` 얕은 경로에서 import·host 명령 거부를 별도 프로세스로 검사하며, Linux CI는 두 파일만 복사한 경로에서 `_isolation` subprocess도 실행한다. 16:26 기존 이미지 조회 원본은 `deliverables/phase1-d03-review-fix-20261014/podman-id-read/`에 보존한다. 수정 코드의 독립 재검토는 별도다.

## 고정 입력과 공급 준비

앱 Source: `affbc69beef9967f7977d09a6fec14f7fb6c0e94`, 증적217→218→219→224/228.

| 앱 | OCI archive SHA256 | 실행에 사용하는 image config ID |
|---|---|---|
| transaction-api | `ff3d145047f53b67f44b8a91994d7ab2b72998d9b276184b3c70a2148d52e3cf` | `sha256:ab34196baf2b878222857be47b200baed0151679a5b19fe15635ba50f77bffee` |
| fds-engine | `319ab0af288d32a156feb1867193d3b7be0e663f2a17ee3efaa95aa505cd7031` | `sha256:b82d35a60e7a7f4a30366a926699fa4b673e69610f64fa0e7f294673ed12f4fc` |

운영 manifest는 API `sha256:338b8a2871507ce8b42deedc916b26e350577ee6efd18df23d7ff2dd4b17dff0`, engine `sha256:8b257adb08b6d381f72b66d3386efea6112a8f072ecfafcbcd463bcd1c3be89d`다. OCI import 후 RepoDigest alias가 없어도 **검증된 config ID**로 실행하며, 두 ID와 manifest의 원 연결은 위 TBS/Push/Deploy 증적을 사용한다.

시험 DB는 기존 [lab-db](../deploy/README.md#시험-db--componentslab-db-명시적-opt-in)의 `quay.io/sclorg/postgresql-16-c9s@sha256:d33717fd33c1a4b11afef94568d0c20812a19d62fb8c633fadee1e491e2edd4a`를 제안한다. 새 이미지 출처의 P1 시험 사용·공급 허용, 현재 공급 가능성/보안 검토는 실행 전 확정한다. 과거 P2용 고정만으로 승인된 것으로 보지 않는다.

16:29 Runner의 `skopeo inspect --no-creds --tls-verify=true --raw/--config` 읽기 전용 조회는 모두 rc0이었다. 공개 registry index 원문 SHA는 위 `d33717…`과 일치하고, linux/amd64 manifest는 `sha256:862cf9364c60a1c47f1721b4700302a959969a09091a8434b3c64949730ed1f1`이다. 선택 config의 SHA는 `d0614d16e62078e0d1b6b55d86e834225988348162a0abb608944fa37a1091ef`, User26, linux/amd64를 확인했다. 메타데이터 조회는 공급 경로·고정 대상 확인이며 이미지 취약점 검사, 계층 다운로드/import, 기동 검증, 사용 승인이 아니다. 원본·receipt는 `deliverables/phase1-d03-review-fix-20261014/db-registry-metadata-read/`에 보존한다.

**아래 공급 명령은 향후 확정된 공급 범위/창에서만 사용한다. 현재 실행하지 않았다.** 위치는 Runner/UID1000. 앱 archive 경로는 `/home/server01_cicd-runner/FDS_CICD_AppWorkflow.3_geu2kf/build-scan/`이다. 두 SHA를 재확인한 뒤 해당 archive만 `podman load --input <고정 경로>`로 import한다. DB는 승인된 공급 경로에서 **위 digest 그대로** 공급한다. `podman pull --tls-verify=false`, latest 태그, 임의 대체 이미지, Harbor Robot 재등록을 사용하지 않는다. 도구 자체에는 load/pull 기능이 없고 `--pull=never`만 사용한다. DB RepoDigest나 앱 config ID가 다르면 컨테이너 생성 전에 중단한다.

## 실행 단위와 판정

도구: `tools/regression/d03_lab.py`, `d03_fixture.py`. 새 RUN마다 **최대7 POST**, 자동 재시도 없음. 정상4건·fail-open2건은 총6행, 의도한 DB 오류1건은0행이다. 운영 DB에는 접근하지 않으며 임시 DB 데이터는 사후 전체 행을 증적으로 수집한 뒤 컨테이너 정리 시 소멸한다.

| 순서 | 장애 주입/요청 | 필수 기대값 |
|---|---|---|
| PRE | 정상 engine, 정상 DB | 201, skipped=false, R01/R02/R04/R07 모두false, DB1행 |
| READ | fixture가 요청 body를 실제 수신하고 응답 헤더 전송을3.5초 지연 | API read2초 timeout 후201/null/null/true, DB1행, save+1/error+1 |
| READ_POST | fixture가 실제 engine으로 전달 | 정상201/DB1행/skip=false |
| HTTP | fixture가 실제 HTTP500 반환 | API201/null/null/true, DB1행, save+1/error+1; fixture500 전송 로그 |
| HTTP_POST | 실제 engine으로 전달 | 정상201/DB1행/skip=false |
| DB | 시험 DB의 이번 `SIM_d03_<RUN>_DB` 한 계정에만 BEFORE INSERT 오류 | API500 `transaction save failed`, 해당 DB0행, save_failure+1/save_success+0; 주입 PID의 **후속 ROLLBACK 로그** |
| DB_POST | trigger/function 제거 후 실제 engine·DB | 정상201/DB1행/skip=false |

모든 요청은 별도 계정, deposit10,000 KRW, 문서용 IP, RUN 당일12:00+09:00이다. 금액/유형/시각/응답ID·Rule·boolean을 실제 DB와 비교한다. 최종 카운터 차이는 save_success6/save_failure1/evaluation_error2, DB6행·고유ID6이어야 한다. fixture는 수신7건의 순서·모드·거래ID를 대조한다. 정상 경로를 가짜 성공 응답으로 대체하지 않고 실제 engine으로 전달한다.

`build_context`가 INSERT try보다 앞서므로 DB 전체 중단으로 대신하지 않는다. DB guard는 `current_database()='fds_lab'`, 기존 empty-schema hook/head0003 재사용, 실제16계열 확인이다. 기본 정상 소스를 수정하거나 DB 오류를 monkeypatch하지 않는다. PID가 다르거나 주입보다 앞선 ROLLBACK, 단순0행만으로 rollback PASS를 판정하지 않는다.

## 실행 순서와 진입 조건

1. 코드의 정확 HEAD 독립 리뷰·필요 보완·CI 확인. code review와 위 인수 범위 판단을 따로 남긴다.
2. 기존 승인 이미지를 고정 공급하고 코드/schema/hash를 보존한 실행 bundle을 만든다. Runner 전용 사용·현재 메모리/디스크·Worker0/컨테이너0을 확인한다. shared Runner를 예약하는 확인은 직전 상태 조회로 대신할 수 없다.
3. 회차 RUN·실제 시작창·종료 상한과 격리 DB 이미지 사용/공급, 최대7POST/1회, 임시 컨테이너·데이터 정리 범위를 확정한다. 이전15:00 종료창은 재사용하지 않는다.
4. 고정 checkout에서 아래 `plan`을 실행한다. 이것은 네트워크나 컨테이너 작업 없는 오프라인 준비다. RUN은 실제 결정한 KST `YYYYMMDDHHMM`으로 넣는다.

```text
python3 -B tools/regression/d03_lab.py plan /approved/path/plan.json --run <RUN>
```

plan은 도구2개·기존 schema hook/SQL·migration3개의 SHA256, 고정 이미지, 케이스·요청 상한을 결속한다. 승인 기록은 **실제 사용자/독립 리뷰의 URL**과 정확 plan SHA에 연결해야 하며 예제 문자열을 승인으로 쓰지 않는다.

```json
{
  "approved": false,
  "plan_sha256": "실제 plan SHA256",
  "start_after": "미확정: timezone 포함 실제 ISO 시각",
  "start_before": "미확정: 실제 시작 마감",
  "finish_before": "미확정: 정리 종료 상한",
  "user_authorization_reference": "미확정",
  "independent_review_reference": "미확정",
  "runner_exclusive": false,
  "lab_db_image_accepted": false
}
```

도구는 기록 형식/정확 plan/time 조건을 검사한다. URL의 실제 승인 의미·review commit은 실행자가 GitHub 원본으로 확인한다. URL 문자열이 있다는 것만으로 타인의 승인을 인증하지 않는다.

5. 실제 시작 시 종료까지12분 이상/30분 이하가 있어야 한다. 아래 명령은 **새 실행 승인이 있고 진입조건이 모두 충족된 때만** 실행한다.

```text
python3 -B tools/regression/d03_lab.py run /approved/path/plan.json /home/server01_cicd-runner/FDS_D03_<RUN> --plan-sha <SHA256> --authorization /approved/path/authorization.json
```

6. 새 RUN의 영구 claim을 먼저 만들고 결과 폴더를0700으로 만든다. claim은 실패해도 지우지 않는다. 컨테이너는 read-only/cap-drop ALL/no-new-privileges, host port 없음, DB tmpfs와 코드 read-only bind만 사용한다. 일시 자격증명은 새 random 값으로0600 env파일에 넣고 로그에서 제거하며 종료 시 파일을 회수한다. 기존 운영 인증은 필요 없다.
7. DB768MiB/API256MiB/engine256MiB/fixture128MiB, CPU각1/1/0.5/0.25, pids128, 컨테이너 자동 수명900초. 작업은 최대660초 또는 창 종료120초 전 중 이른 시점까지만 진행한다. 현재 host 자원이 이 상한을 감당할 때만 진입한다.
8. 장애/예상외 응답/로그 미확보/회복 실패 시 남은 POST를 중단하고 정리한다. 다시 실행하려면 새 RUN·별도 결정이 필요하다.

### 컨테이너 없는 helper 사전 점검

독립 재검토에서 드러난 `http()`/`http.client` 이름 충돌은 모듈을 `http_client`로 별칭 import하여 수정했다. HTTP helper 자체의 실제 GET/POST와 두 파일만 staging한 CLI `_probe`를 검증한다. 이 점검은 실제 회차의 claim·이미지 import·컨테이너 생성 **전에**, 검토한 bundle의 Runner 고정 checkout에서 아래 두 시험으로 수행한다.

```text
python3 -B -m unittest -v tools.tests.test_d03_lab.StagedInvocation.test_staged_probe_reaches_loopback_fixture tools.tests.test_d03_lab.FixtureWireBehavior.test_lab_helper_get_and_post_reach_actual_fixture
```

- 전제: Runner/UID1000의 검토한 checkout, Python3 표준 라이브러리, `127.0.0.1:18081`을 이 점검 동안 독점할 수 있음. 포트 점유 시 기존 프로세스를 종료하거나 연결을 재사용하지 않고 점검을 중단한다.
- 동작: 임시 폴더에 도구 두 파일만 복사하고 로컬 fixture를 연다. 별도 Python 프로세스의 `_probe 18081 /readyz`와 helper GET은200, 합성 HTTP 케이스 POST는 fixture의 의도한500/marker를 받아야 한다. POST 대상은 별도 loopback fixture이며 실제 API/engine/DB로 전달하지 않는다. 합성 RUN은 selftest 값이고 실제 RUN·1회 claim을 만들지 않는다.
- 정상: 두 시험 OK/rc0, fixture 서버·소유 스레드·임시 폴더 정리. 명령/시각/HEAD·코드 SHA/stdout/stderr/rc를 준비 증적으로 보존한다. subprocess는10초 상한이며 예외 시에도 fixture를 닫는다.
- 실패: image import와 실제 회차에 진입하지 않고 원본을 보존한다. helper 점검 성공은 컨테이너/앱·DB Runtime 성공이나 신규 실행창 승인이 아니다. Runner 점검 실제 수행 여부는 별도 기록한다.

## 복구·정리와 원본 보존

- 시험 SQL trigger는 DB 케이스 직후 finally에서 제거한다. 예상 실패 중단이어도 임시 DB 컨테이너만 정리한다. 운영 DB의 rollback이나 설정 원복은 이 시험에 포함되지 않는다.
- 정확 CID와 `fds.d03.run=<RUN>` 라벨을 함께 확인한 이 회차 컨테이너만 역순 제거한다. 로그 수집 timeout이 소유 컨테이너 정리를 건너뛰게 하지 않는다. 다른 라벨·조회 실패면 삭제하지 않고 `CLEANUP_FAILED`로 남긴다.
- create 결과가 불명확하고 객체가 안 보이는 경우도 정리 성공으로 단정하지 않는다. 같은 user가 기록된 **정확 이름/CID·라벨**을 다시 조회해 인계한다. 무차별 prune/kill/rm은 금지한다.
- 자동900초 수명은 실행 프로세스 소실 때 컨테이너가 계속 서비스하는 시간을 제한한다. SIGKILL·호스트 소실 후 컨테이너 객체/파일 삭제나 증적 수집까지 보장하지 않는다. 잔존 시 원본 보존 후 정확 소유 범위만 운영자가 정리한다.
- 원본: plan/승인 기록, command/rc/시간, 실제 image metadata·namespace/route·listener, POST 전 intent, 응답/DB 행/카운터, fixture·DB 로그, 동일 PID ROLLBACK, 최종6행, cleanup/result/SHA256SUMS. 케이스 결과는 DB 필드/계약 판정 전에 저장한다. 원래 오류와 trigger 제거 오류는 `<case>-errors.json`에 각각 비밀값을 가려 보존하고 원래 오류를 유지하여 중단한다. env 자격증명 파일은 manifest에서 제외하고 외부 편입하지 않는다. 회수 실패 시 해당 파일을 포함하는 폴더 전체 업로드도 금지한다.
- `LAB_RUNTIME_PASS`는 모든 케이스와 정리 성공·창 준수를 뜻한다. `production_runtime_claim=false`를 유지한다. 이후 증적 저장소 독립 리뷰·병합과 APP/E2E 최종 처분은 별도다.

## 검증 구분

새 selftest는 기대 응답/DB/metric 반례, 승인·시각·plan 변조, ROLLBACK PID/순서, 타 회차 삭제 방지, 로그수집 실패 중 정리, 실제 loopback fixture의500·응답 지연을 확인한다. 이 시험의 DB 자료/컨테이너 호출은 합성·mock이므로 앱/DB Runtime PASS가 아니다. 기존 Source validation CI가 테스트를 발견한다. 새 자동 Runtime workflow/dispatch는 추가하지 않는다.
