from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, ForeignKey, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class Area(Base):
    __tablename__ = "areas"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(128), unique=True)


class Equipment(Base):
    __tablename__ = "equipment"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(256))
    area_id: Mapped[UUID] = mapped_column(ForeignKey("areas.id"), index=True)


class WorkCode(Base):
    __tablename__ = "work_codes"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    code: Mapped[str] = mapped_column(String(64), unique=True)
    name: Mapped[str] = mapped_column(String(256))


class Material(Base):
    __tablename__ = "materials"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(256))
    unit: Mapped[str] = mapped_column(String(32))


class MaterialNorm(Base):
    __tablename__ = "material_norms"
    __table_args__ = (
        CheckConstraint("quantity > 0", name="positive_quantity"),
        UniqueConstraint("equipment_id", "work_code_id", "material_id"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    equipment_id: Mapped[UUID] = mapped_column(ForeignKey("equipment.id"), index=True)
    work_code_id: Mapped[UUID] = mapped_column(ForeignKey("work_codes.id"))
    material_id: Mapped[UUID] = mapped_column(ForeignKey("materials.id"))
    quantity: Mapped[Decimal] = mapped_column(Numeric(14, 4))
