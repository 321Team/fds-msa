"""P1-DB-01 R1 remediation 후속: transactions 인덱스 2종 버전관리 편입 (schema drift 해소)

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-23

2026-09-22~23 TC-SCHEMA(형상 재현성) 재검증 중 db01(fdsdb)의 실제 인덱스를
pg_indexes로 직접 조회해 확인함. transactions 테이블에는 0001/0002에
정의되지 않은 아래 2개 인덱스가 Alembic 버전관리 밖에서(수동 CREATE INDEX로
추정) 이미 존재함:

  - idx_transactions_account_id        ON transactions (account_id)
  - idx_transactions_account_type_time ON transactions (account_id, transaction_type, occurred_at)

(`transactions_pkey`는 0001의 `transaction_id primary_key=True`로 이미
버전관리에 잡혀있어 이 revision의 대상이 아님)

이 revision은 위 2개 인덱스를 버전관리에 편입시켜 신규(빈) DB에서도 동일한
운영 스키마가 재현되도록 한다.

[적용 방법]
  - db01(기존 인덱스 있음): upgrade()를 실행하지 않는다. pg_indexes로 두
    인덱스의 indexdef가 upgrade() 정의와 같은지 확인한 뒤 채택(stamp)한다.
    db01에는 저장소가 없어 `alembic stamp`를 쓸 수 없으므로 아래 SQL로
    수동 stamp하고, 실행 기록(대상·계정·KST 시각·전후 값)을
    fds-project-evidence evidence/P1-DB-01/에 남긴다.
        BEGIN;
        SELECT version_num FROM alembic_version;          -- 0002 확인
        UPDATE alembic_version SET version_num = '0003'
         WHERE version_num = '0002';                       -- UPDATE 1 확인
        COMMIT;
    되돌리기(이 revision 반려 시, 인덱스는 유지):
        UPDATE alembic_version SET version_num = '0002'
         WHERE version_num = '0003';
    2026-09-25 db01 읽기 전용 실측에서 indexdef·컬럼·제약이 이 revision
    까지의 재현 결과와 일치함을 확인했다.
  - 신규(로컬/CI/재현 테스트) 환경: `alembic upgrade head`로
    0001+0002+0003이 현재 운영 스키마와 동일하게 재현된다.
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index(
        "idx_transactions_account_id",
        "transactions",
        ["account_id"],
    )
    op.create_index(
        "idx_transactions_account_type_time",
        "transactions",
        ["account_id", "transaction_type", "occurred_at"],
    )


def downgrade() -> None:
    """신규/재현 환경 전용. db01에서는 실행하지 않는다.

    db01의 두 인덱스는 0003 이전부터 존재한 운영 인덱스이므로, 되돌릴 때는
    alembic_version만 0002로 복구한다(인덱스는 유지).
    """
    op.drop_index("idx_transactions_account_type_time", table_name="transactions")
    op.drop_index("idx_transactions_account_id", table_name="transactions")
