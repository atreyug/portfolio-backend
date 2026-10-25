import uuid
from datetime import datetime

from sqlalchemy import (
    String,
    DateTime,
    Numeric,
    ForeignKey,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from core.database import Base


class MonitoringHolding(Base):
    __tablename__ = "monitoring_holdings"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    config_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "monitoring_configs.id",
            ondelete="CASCADE",
        ),
        nullable=False,
        index=True,
    )

    client_id: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        index=True,
    )

    symbol: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        index=True,
    )

    quantity: Mapped[float | None] = mapped_column(
        Numeric(18, 6),
        nullable=True,
    )

    exposure: Mapped[float | None] = mapped_column(
        Numeric(18, 2),
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=datetime.utcnow,
        nullable=False,
    )

    config = relationship(
        "MonitoringConfig",
        back_populates="holdings",
    )

    alerts = relationship(
        "Alert",
        back_populates="holding",
    )