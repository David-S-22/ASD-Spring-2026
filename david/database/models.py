from dataclasses import dataclass
from sqlalchemy.orm import mapped_column
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
        return dto.Suggestion(self.id, self.suggestion, self.accepted)

@dataclass
class Feedback(db.Model):
    id: Mapped[int] = mapped_column(primary_key=True)
    feedback: Mapped[str] = mapped_column(nullable=False)

    def to_dto(self):
        return dto.Feedback(self.id, self.feedback)

