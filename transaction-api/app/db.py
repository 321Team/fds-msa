import os

from sqlalchemy import (
    Column, String, Numeric, DateTime, Boolean, Text, MetaData, Table
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

# credential은 Secret에서 주입 (하드코딩 금지 — FDS_SECURITY_BASELINE_v2)
DATABASE_URL = os.environ["DATABASE_URL"]  # postgresql+asyncpg://user:pass@10.1.93.55:5432/fdsdb

engine = create_async_engine(DATABASE_URL, pool_size=5, max_overflow=5, pool_pre_ping=True)
async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

# 스키마(인덱스 포함)의 권위 정의는 루트 alembic/versions 이다. 이 Table은
# 쿼리 작성용 표현이며 create_all에 쓰지 않는다.
metadata = MetaData()

transactions = Table(
    "transactions",
    metadata,
    Column("transaction_id", String, primary_key=True),
    Column("account_id", String, nullable=False),
    Column("amount", Numeric, nullable=False),
    Column("currency", String, nullable=False, default="KRW"),
    Column("transaction_type", String, nullable=False),
    Column("source_ip", String, nullable=True),
    Column("occurred_at", DateTime(timezone=True), nullable=False),
    Column("received_at", DateTime(timezone=True), nullable=False),
    Column("fds_detected", Boolean, nullable=True),
    Column("fds_rules", JSONB, nullable=True),
    Column("fds_evaluation_skipped", Boolean, nullable=False, default=False),
)


async def db_ping():
    async with engine.connect() as conn:
        await conn.exec_driver_sql("SELECT 1")
