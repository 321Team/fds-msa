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
  - db01(기존 데이터 있음): 인덱스가 이미 존재하므로 upgrade()를 그대로
    실행하면 "relation already exists" 오류가 날 수 있음. 실행 전
    인덱스 존재 여부를 재확인한 뒤 `alembic stamp 0003`으로 "이미 이
    상태다"라고 채택한다 (0001과 동일한 패턴). 운영 fdsdb에는 당장
    upgrade()를 실행하지 않는다.
  - 신규(로컬/CI/재현 테스트) 환경: upgrade()를 그대로 실행하면
    0001+0002+0003으로 현재 운영 스키마와 동일한 상태가 재현된다.
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
    op.drop_index("idx_transactions_account_type_time", table_name="transactions")
    op.drop_index("idx_transactions_account_id", table_name="transactions")
