# The following is a list of models used as DTOs between microservices
# They expose the public shape of the data, whilst leaving the internals
# for the database engine to maintain
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

# Represents a transaction the user has entered into the application
@dataclass(frozen=True)
class Transaction:
    id: int
    amount: float
    merchant: str
    date: datetime
    description: str
    category_id: int

@dataclass(frozen=True)
class Category:
    id: int
    name: str
    type: Optional[str]

# Represents a transaction an agent has decided may be suspicious. The user can confirm
# whether it is true positive or false positive, which is represented by is_confirmed_by_user
@dataclass(frozen=True)
class Anomaly:
    id: int
    transaction_id: int
    agent_reason_suspected: str
    is_confirmed_by_user: Optional[bool]

@dataclass(frozen=True)
class Goal:
    id: int
    name: str
    cost: int
    date: datetime

@dataclass(frozen=True)
class Suggestion:
    id: int
    suggestion: str
    accepted: bool

@dataclass(frozen=True)
class Feedback:
    id: int
    feedback: str
