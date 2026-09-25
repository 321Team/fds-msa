"""
FDS 프로젝트 정식 스키마 모델 (P1-DB-03)

2026-09-03 db01(fdsdb) 실제 스키마(\\d+ transactions) 대조 후 재작성함.
기존 "임시 스켈레톤 SQL"이 이미 이 구조로 만들어져 있고 데이터가 있을 수
있으므로, 이 모델/마이그레이션은 **재생성용이 아니라 채택(stamp)용**이다.
자세한 절차는 프로젝트 README 참고.

[확인된 사실]
- transaction_id는 UUID가 아니라 TEXT다 (애초 설계가 이렇게 됨).
- fds_results라는 별도 테이블은 존재하지 않는다. fds_detected가
  transactions 테이블 안에 컬럼으로 직접 들어가 있다.
- (0002) R01/R02/R04/R07 판정 결과는 fds_rules(jsonb), fail-open 여부는
  fds_evaluation_skipped(boolean)에 저장한다.
- occurred_at(이벤트 발생 시각, R04 심야고액 판정 기준)과
  received_at(서버 수신 시각)이 분리돼 있다 — 기존에 "event_time"으로
  불렀던 것이 실제로는 occurred_at 컬럼이다.

[확인 완료 — 2026-09-23 pg_indexes 실측, 2026-09-25 db01 읽기 전용 재대조]
- transaction_id는 PRIMARY KEY(transactions_pkey)다.
- 인덱스(0003): idx_transactions_account_id(account_id),
  idx_transactions_account_type_time(account_id, transaction_type, occurred_at).
  occurred_at / received_at 단독 인덱스는 없다.

[미확인 — 확인 필요]
- Timezone 정책: 컬럼 자체는 이미 timestamptz라 UTC/KST 어느 쪽으로
  정책이 정해지든 값(aware datetime) 자체는 안전하다. 다만 애플리케이션이
  실제로 어느 시간대로 넣고 있는지는 코드 확인 필요(이 Migration의 범위 밖).
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, Index, Numeric, Text, text
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Transaction(Base):
    """거래 원본 + FDS 판정 결과 (fds_detected가 같은 테이블에 있음)."""

    __tablename__ = "transactions"
    __table_args__ = (
        # 0003: db01 실측으로 확인된 기존 인덱스 2종을 모델에도 반영 —
        # 여기 선언 안 해두면 autogenerate가 "모델에 없다"고 오판해
        # 삭제 마이그레이션을 제안할 수 있음.
        Index("idx_transactions_account_id", "account_id"),
        Index(
            "idx_transactions_account_type_time",
            "account_id",
            "transaction_type",
            "occurred_at",
        ),
    )

    transaction_id: Mapped[str] = mapped_column(Text, primary_key=True)
    account_id: Mapped[str] = mapped_column(Text, nullable=False)
    amount: Mapped[float] = mapped_column(Numeric, nullable=False)
    currency: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'KRW'::text")
    )
    transaction_type: Mapped[str] = mapped_column(Text, nullable=False)
    source_ip: Mapped[str | None] = mapped_column(Text, nullable=True)

    # 이벤트 발생 시각 — R04(심야고액) 판정 기준. timestamptz라 시간대
    # 자체는 안전하게 보관되지만, 정책(UTC/KST) 확정 전까지는 애플리케이션이
    # 실제로 무엇을 넣고 있는지 별도 확인 필요.
    occurred_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False
    )
    received_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False
    )

    fds_detected: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    # 0002: FDS 평가 결과 저장 컬럼
    fds_rules: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    fds_evaluation_skipped: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
