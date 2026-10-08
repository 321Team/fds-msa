-- 생성물 — 직접 고치지 않는다. 루트 alembic/versions가 바뀌면 다시 생성하고 아래 SHA-256을 갱신한다.
-- 생성: DATABASE_URL=postgresql://offline@invalid/offline alembic upgrade head --sql  (Alembic 1.20.0, SQLAlchemy 2.1.4, 오프라인)
-- alembic head: 0003
-- sha256 alembic/versions/0001_initial_schema.py c847a31355a9ebc4cafb0e8f87c43fd85720e52553d00ed363382a721d82f1b9
-- sha256 alembic/versions/0002_add_fds_evaluation_columns.py 29040110fa10a7df7fa50d9d21a4c0c5f4d09204705fe37688ea2481472b94e0
-- sha256 alembic/versions/0003_add_transactions_indexes.py 471547aef06d2417c69463625302a7d11bd8e7b7d8d1253df5828fd9ca3057c9
-- 시험 DB 전용. db01에는 적용하지 않는다(db01은 stamp 이력 — MIGRATION_README.md).

BEGIN;

CREATE TABLE alembic_version (
    version_num VARCHAR(32) NOT NULL,
    CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num)
);

-- Running upgrade  -> 0001

CREATE TABLE transactions (
    transaction_id TEXT NOT NULL,
    account_id TEXT NOT NULL,
    amount NUMERIC NOT NULL,
    currency TEXT DEFAULT 'KRW'::text NOT NULL,
    transaction_type TEXT NOT NULL,
    source_ip TEXT,
    occurred_at TIMESTAMP WITH TIME ZONE NOT NULL,
    received_at TIMESTAMP WITH TIME ZONE NOT NULL,
    fds_detected BOOLEAN,
    PRIMARY KEY (transaction_id)
);

INSERT INTO alembic_version (version_num) VALUES ('0001') RETURNING alembic_version.version_num;

-- Running upgrade 0001 -> 0002

ALTER TABLE transactions ADD COLUMN fds_rules JSONB;

ALTER TABLE transactions ADD COLUMN fds_evaluation_skipped BOOLEAN DEFAULT false NOT NULL;

UPDATE alembic_version SET version_num='0002' WHERE alembic_version.version_num = '0001';

-- Running upgrade 0002 -> 0003

CREATE INDEX idx_transactions_account_id ON transactions (account_id);

CREATE INDEX idx_transactions_account_type_time ON transactions (account_id, transaction_type, occurred_at);

UPDATE alembic_version SET version_num='0003' WHERE alembic_version.version_num = '0002';

COMMIT;
