# rhel9/postgresql-16 이미지가 데이터 디렉터리를 처음 초기화할 때 source한다(postgresql-init).
# 업무 schema(fds-schema.sql = Alembic head offline SQL)를 앱 계정 소유로 만든다.
# 실패하면 컨테이너를 끝내 Ready가 되지 않게 한다(빈 DB로 Ready가 되는 것을 막는다).
FDS_SCHEMA_SQL="${FDS_SCHEMA_SQL:-/opt/app-root/src/postgresql-init/fds-schema.sql}"
if psql -X -q -v ON_ERROR_STOP=1 -d "$POSTGRESQL_DATABASE" \
    -c "SET ROLE \"$POSTGRESQL_USER\"" -f "$FDS_SCHEMA_SQL"; then
  echo "fds-lab-db: schema 적용 완료 ($FDS_SCHEMA_SQL)"
else
  echo "fds-lab-db: schema 적용 실패 — 컨테이너를 종료합니다" >&2
  exit 1
fi
