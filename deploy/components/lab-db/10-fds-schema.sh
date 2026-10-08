# sclorg postgresql-16 이미지(quay.io/sclorg/postgresql-16-c9s)의 postgresql-start 훅. run-postgresql이 계정·DB 생성(create_users) 뒤,
# 서버를 소켓 전용(-h '')으로 띄운 상태에서 **매 시작마다** source한다. 이 훅이 끝나야 TCP로 서비스한다.
# 업무 schema(fds-schema.sql = Alembic head offline SQL)를 확인한다:
#   - public에 테이블이 하나도 없으면 앱 계정 소유로 한 트랜잭션에 적용하고 다시 확인
#   - alembic_version이 FDS_SCHEMA_HEAD 한 행이고 transactions가 있으면 그대로 둔다(재적용 없음)
#   - 그 밖의 상태(부분 적용·다른 버전·확인 실패)는 컨테이너를 끝낸다 → 재시작해도 같은 확인에서 다시 멈춘다
FDS_SCHEMA_SQL="${FDS_SCHEMA_SQL:-/opt/app-root/src/postgresql-start/fds-schema.sql}"
FDS_SCHEMA_HEAD="${FDS_SCHEMA_HEAD:-0003}"

fds_schema_fail() {
  echo "fds-lab-db: $1 — 컨테이너를 종료합니다" >&2
  # 소켓 전용 임시 서버를 정상 종료해 postmaster.pid를 남기지 않는다. 남으면 같은 emptyDir로 재시작할 때
  # "another server might be running"으로 서버가 뜨지 않아, 고친 schema로도 복구되지 않는다.
  if [ -n "${PGDATA:-}" ]; then
    pg_ctl stop -D "$PGDATA" -m fast -w > /dev/null 2>&1 || echo "fds-lab-db: 임시 서버 정상 종료 실패" >&2
  fi
  exit 1
}

fds_schema_state() {
  local tables version
  tables=$(psql -X -At -v ON_ERROR_STOP=1 -d "$POSTGRESQL_DATABASE" \
    -c "SELECT count(*) FROM pg_tables WHERE schemaname = 'public'") || return 1
  if [ "$tables" = "0" ]; then
    echo EMPTY
    return 0
  fi
  if [ "$(psql -X -At -v ON_ERROR_STOP=1 -d "$POSTGRESQL_DATABASE" \
      -c "SELECT to_regclass('public.alembic_version') IS NOT NULL AND to_regclass('public.transactions') IS NOT NULL")" != "t" ]; then
    echo PARTIAL
    return 0
  fi
  version=$(psql -X -At -v ON_ERROR_STOP=1 -d "$POSTGRESQL_DATABASE" \
    -c "SELECT coalesce(string_agg(version_num, ',' ORDER BY version_num), 'NONE') FROM alembic_version") || return 1
  echo "VERSION:$version"
}

fds_state=$(fds_schema_state) || fds_schema_fail "schema 상태 확인 실패"
case "$fds_state" in
  EMPTY)
    psql -X -q -v ON_ERROR_STOP=1 -d "$POSTGRESQL_DATABASE" \
      -c "SET ROLE \"$POSTGRESQL_USER\"" -f "$FDS_SCHEMA_SQL" > /dev/null \
      || fds_schema_fail "schema 적용 실패 ($FDS_SCHEMA_SQL)"
    fds_state=$(fds_schema_state) || fds_schema_fail "적용 후 schema 상태 확인 실패"
    [ "$fds_state" = "VERSION:$FDS_SCHEMA_HEAD" ] || fds_schema_fail "적용 후 상태가 기대와 다름: $fds_state"
    echo "fds-lab-db: schema $FDS_SCHEMA_HEAD 적용 완료"
    ;;
  "VERSION:$FDS_SCHEMA_HEAD")
    echo "fds-lab-db: schema $FDS_SCHEMA_HEAD 확인 — 재적용하지 않음"
    ;;
  *)
    fds_schema_fail "예상하지 못한 schema 상태: $fds_state"
    ;;
esac
unset fds_state
