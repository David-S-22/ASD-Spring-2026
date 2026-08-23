# The following is a list of models used as DTOs between microservices
# They expose the public shape of the data, whilst leaving the internals
# for the database engine to maintain
from dataclasses import dataclass
from typing import Optional
from uuid import UUID

# Represents a transaction the user has entered into the application
@dataclass(frozen=True)
class Transaction:
    id: UUID
    amount: float
    merchant: str

# Represents a transaction an agent has decided may be suspicious. The user can confirm
# whether it is true positive or false positive, which is represented by is_confirmed_by_user
@dataclass(frozen=True)
class Anomaly:
    id: UUID
    transaction_id: UUID
    agent_reason_suspected: str
    is_confirmed_by_user: Optional[bool]
