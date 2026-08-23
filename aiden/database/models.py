from flask_sqlalchemy import SQLAlchemy
from uuid import UUID, uuid4
from sqlalchemy.orm import Mapped, mapped_column
from shared.backend import dto

db = SQLAlchemy()

class Anomaly(db.Model):
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    transaction_id: Mapped[UUID] = mapped_column(unique=True) # One anomaly per transaction
    agent_reason_suspected: Mapped[str] = mapped_column()
    is_confirmed_by_user: Mapped[bool] = mapped_column(nullable=True)

    def to_dto(self):
        return dto.Anomaly(self.id, self.transaction_id, self.agent_reason_suspected, self.is_confirmed_by_user)
