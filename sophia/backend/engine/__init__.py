"""Pure, stdlib-only bill projection engine.

Exposes the core dataclasses shared across the engine modules and the
BARELY_USING_THRESHOLD constant used by the chat "barely using" question.
"""
from dataclasses import dataclass
from datetime import date
from typing import Optional

BARELY_USING_THRESHOLD = 3


@dataclass(frozen=True)
class Bill:
    id: int
    name: str
    merchant: str
    amount_cents: int
    cadence: str
    next_billing_date: date
    type: str
    payment_method: Optional[str] = None
    end_date: Optional[date] = None
    confirmed_at: Optional[date] = None
    created_at: Optional[date] = None


@dataclass(frozen=True)
class Payment:
    bill_id: int
    date: date
    amount_cents: int


@dataclass(frozen=True)
class Occurrence:
    bill_id: int
    name: str
    date: date
    amount_cents: int
    kind: str
    cycle_index: int
