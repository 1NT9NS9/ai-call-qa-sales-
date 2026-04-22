from sqlalchemy.orm import Mapped, mapped_column

from src.infrastructure.persistence.base import Base


class _DocumentRecord(Base):
    __tablename__ = "knowledge_documents"

    id: Mapped[int] = mapped_column(primary_key=True)
