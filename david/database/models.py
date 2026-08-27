from dataclasses import dataclass
from sqlalchemy.orm import mapped_column
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
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

@dataclass
class Suggestion(db.Model):
    id: Mapped[int] = mapped_column(primary_key=True)
    suggestion: Mapped[str] = mapped_column(nullable=False)

@dataclass
class Feedback(db.Model):
    id: Mapped[int] = mapped_column(primary_key=True)
    feedback: Mapped[str] = mapped_column(nullable=False)
