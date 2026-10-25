import uuid
from datetime import datetime

from sqlalchemy import (
    String,
    Boolean,
    DateTime,
    Numeric,
    ForeignKey,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from core.database import Base


class MonitoringRule(Base):
    __tablename__ = "monitoring_rules"

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

    rule_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )

    threshold: Mapped[float | None] = mapped_column(
        Numeric(18, 6),
        nullable=True,
    )

    enabled: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        nullable=False,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=datetime.utcnow,
        nullable=False,
    )

    config = relationship(
        "MonitoringConfig",
        back_populates="rules",
    )

    alerts = relationship(
        "Alert",
        back_populates="rule",
    )