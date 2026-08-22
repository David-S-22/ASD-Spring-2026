from flask_sqlalchemy import SQLAlchemy
from uuid import UUID
from sqlalchemy.orm import Mapped, mapped_column

db = SQLAlchemy()

class Anomaly(db.Model):
    id: Mapped[UUID] = mapped_column(primary_key=True)
    transaction_id: Mapped[UUID] = mapped_column(unique=True) # One anomaly per transaction
    agent_reason_suspected: Mapped[str] = mapped_column()
    is_confirmed_by_user: Mapped[bool] = mapped_column(nullable=True)

    def to_json(self):
        return dict(
            id=self.id,
            transaction_id=self.transaction_id,
            agent_reason_suspected=self.agent_reason_suspected,
            is_confirmed_by_user=self.is_confirmed_by_user
        )
