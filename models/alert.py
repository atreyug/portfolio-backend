import uuid
from datetime import datetime

from sqlalchemy import (
    String,
    Text,
    Boolean,
    DateTime,
    ForeignKey,
    JSON,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from core.database import Base


class Alert(Base):
    __tablename__ = "alerts"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    manager_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "managers.id",
            ondelete="CASCADE",
        ),
        nullable=False,
        index=True,
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

    holding_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "monitoring_holdings.id",
            ondelete="SET NULL",
        ),
        nullable=True,
        index=True,
    )

    rule_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "monitoring_rules.id",
            ondelete="SET NULL",
        ),
        nullable=True,
        index=True,
    )

    severity: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
    )

    title: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )

    message: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    trigger_data: Mapped[dict | None] = mapped_column(
        JSON,
        nullable=True,
    )

    is_read: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=datetime.utcnow,
        nullable=False,
    )

    manager = relationship(
        "Manager",
        back_populates="alerts",
    )

    config = relationship(
        "MonitoringConfig",
        back_populates="alerts",
    )

    holding = relationship(
        "MonitoringHolding",
        back_populates="alerts",
    )

    rule = relationship(
        "MonitoringRule",
        back_populates="alerts",
    )