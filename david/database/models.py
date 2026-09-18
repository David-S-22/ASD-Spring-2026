from dataclasses import dataclass
from typing import Optional
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from shared.backend import dto
import datetime

class Base(DeclarativeBase):
  pass

db = SQLAlchemy(model_class=Base)

@dataclass
class Goal(db.Model):
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(nullable=False)
    cost: Mapped[int] = mapped_column(nullable=False)
    date: Mapped[datetime.datetime] = mapped_column(nullable=False)

    def to_dto(self):
        return dto.Goal(self.id, self.name, self.cost, self.date)

@dataclass
class Suggestion(db.Model):
    id: Mapped[int] = mapped_column(primary_key=True)
    suggestion: Mapped[str] = mapped_column(nullable=False)
    accepted: Mapped[bool] = mapped_column(nullable=False)

    def to_dto(self):
        feedback = self.feedbacks[0].feedback if hasattr(self, "feedbacks") and self.feedbacks else None
        return dto.Suggestion(self.id, self.suggestion, self.accepted, feedback)

@dataclass
class Feedback(db.Model):
    id: Mapped[int] = mapped_column(primary_key=True)
    feedback: Mapped[str] = mapped_column(nullable=False)
    suggestion_id: Mapped[Optional[int]] = mapped_column(db.ForeignKey("suggestion.id", ondelete="CASCADE"), nullable=True)
    suggestion: Mapped[Optional["Suggestion"]] = db.relationship("Suggestion", backref=db.backref("feedbacks", cascade="all, delete-orphan"), foreign_keys=[suggestion_id])

    def to_dto(self):
        return dto.Feedback(self.id, self.feedback, self.suggestion_id)

